# app.py
"""纹初迹现 · 传统纹样可溯源生成系统 —— 演示界面（B7）。

单页两个标签页：
  Tab 1「生成与溯源」    一句需求 → 配方 → 检索 → 校验 → 溯源卡片
  Tab 2「版权相似度审查」 上传任意图片 → 与样本库比对的相似度风险分级

★ 为什么 M7 单独一个标签页：
    M4（组合式合成）尚未实现，生成流程里没有"合成图"可供比对。
    而 M7 的真实价值本来就是"审查任意一张设计图与本库是否雷同"，
    所以它天然适合作为独立入口，而不是硬挂在生成流程末尾。

★ 分步进度：
    pipeline.run() 支持 on_step 回调，界面据此逐步显示"解析需求… / 检索元素…"，
    让使用者看清每一步在做什么 —— 评审关心的正是"过程可见"。

启动（在工程根目录 work/ 下执行）：
    streamlit run app.py
"""
import json
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.m6_provenance import ATTRIBUTION_SHORT, to_markdown
from src.m7_copyright import assess
from src.pipeline import run, save_all
from src.utils import CFG

st.set_page_config(page_title="纹初迹现 · 可溯源纹样生成系统", layout="wide")

DEFAULT_REQ = "做一个有吉祥寓意的窗花，用于春节礼品包装"

# 配方槽位的中文名（用于标注"槽位保底命中"）
SLOT_CN = {"border": "边饰", "corner": "角花"}


@st.cache_data(show_spinner=False)
def sample_count():
    try:
        return len(json.loads((ROOT / CFG["paths"]["samples"]).read_text(encoding="utf-8")))
    except Exception:
        return 0


def _embed_viewer(glb_info, ground="neutral"):
    """把 GLB 复制到 Streamlit 的静态目录，并用 iframe 嵌入 Three.js 查看器。

    ★ 为什么必须走"静态目录 + iframe"（实测踩到）
      直觉做法是 `st.components.v1.html(open("viewer.html").read())` ——
      **不行**：组件 html 是 srcdoc 沙箱，里面的相对路径 `vendor/three.min.js`
      和 `glb/pattern_*.glb` 都解析不到（没有 base URL），
      浏览器会直接 404，页面一片空白。

      正解：Streamlit 有官方静态目录，把 viewer.html + vendor + glb 放进去，
      再用 `components.iframe("/app/static/...")` 指过去 —— 这样是一个
      **同源的真实页面**，相对路径、WebGL、文件下载全都正常。

    ★★ 静态目录的位置（实测踩到，别再猜）
        Streamlit 启动时会打印：
          "WARNING: Static file serving is enabled, but no static folder
           found at <app_dir>/static"
        —— 即目录必须是**应用目录下的 `static/`**（这里是 `work/static/`），
        **不是** `.streamlit/static/`。放错位置这条警告就是唯一线索，
        页面会静默 404 白屏。URL 前缀是 `/app/static/`。

      ⚠️ 副作用：每次生成 GLB 都要把文件复制进静态目录。
         仅 3 个文件、约 3 MB，成本可接受。
    """
    import shutil
    import streamlit.components.v1 as components

    static_dir = ROOT / "static" / "viewer"
    (static_dir / "vendor").mkdir(parents=True, exist_ok=True)
    (static_dir / "glb").mkdir(parents=True, exist_ok=True)

    # 查看器与 Three.js（只需拷一次，但检查一下以防首次）
    for rel in ("viewer.html", "vendor/three.min.js", "vendor/GLTFLoader.js"):
        src = ROOT / "web" / rel
        dst = static_dir / rel
        if src.exists() and (not dst.exists()
                             or src.stat().st_mtime > dst.stat().st_mtime):
            shutil.copy2(src, dst)

    ok_kinds = []
    for kind, info in glb_info.items():
        if not info.get("ok"):
            continue
        # 查看器用静态目录里的副本（iframe 需要可通过 HTTP 取到）
        shutil.copy2(info["path"], static_dir / "glb" / f"pattern_{kind}.glb")
        ok_kinds.append(kind)

    if not ok_kinds:
        st.error("没有通过校验的 GLB 可预览。")
        return

    order = [k for k in ("vase", "box", "fan") if k in ok_kinds]
    # ★ URL 必须是**以 / 开头**的 `/app/static/...`：
    #   不带前导斜杠会被当成"相对当前页面的路径"而 404（实测踩到）。
    # ★ ground 参数让查看器内的溯源说明与实际贴图方案一致：
    #   启用 AI 地子时不能再说"非 AI 生成"（会失实）。
    url = "/app/static/viewer/viewer.html"
    if ground == "ai":
        url += "?ground=ai"
    components.iframe(url, height=580, scrolling=False)

    # 下载按钮：data 直接取 outputs 里的原始字节，不必再依赖静态目录
    st.markdown("**下载 GLB**")
    label = {"vase": "陶瓶（梅瓶）", "box": "包装方盒", "fan": "团扇"}
    for col, kind in zip(st.columns(len(order)), order):
        col.download_button(
            f"⬇ {label[kind]}（{glb_info[kind]['kb']} KB）",
            data=Path(glb_info[kind]["path"]).read_bytes(),
            file_name=f"pattern_{kind}.glb",
            mime="model/gltf-binary",
            key=f"dl_{kind}",
            use_container_width=True,
        )


# ---------------------------------------------------------------- 侧边栏
with st.sidebar:
    st.header("关于本系统")
    st.markdown(
        "- **可解释**：以《纹样文化配方》为中间表示，生成依据全程可读、可审\n"
        "- **可溯源**：元素级出处标注，**生成时即确定**，非事后推测\n"
        "- **可校验**：文化规则独立于模型，可扩充、可审计\n"
        "- **低门槛**：无需 GPU，普通笔记本即可运行"
    )
    st.divider()
    st.caption(f"样本库：**{sample_count()} 条**纹样母题")
    st.divider()
    st.caption("**数据来源**")
    st.caption(ATTRIBUTION_SHORT)
    st.divider()
    st.caption("首次运行需加载 CLIP 模型（约 20–40 秒），之后会缓存。")


st.title("纹初迹现 · 传统纹样可溯源生成系统")
st.caption("一句需求 →《纹样文化配方》→ 真实纹样元素检索 → 文化校验 → 元素级溯源卡片")

tab_gen, tab_check = st.tabs(["生成与溯源", "版权相似度审查"])

# ================================================================ Tab 1
with tab_gen:
    req = st.text_input("请输入你的纹样需求", value=DEFAULT_REQ,
                        help="例如：做一个有吉祥寓意的窗花，用于春节礼品包装")
    go = st.button("生成纹样方案", type="primary")

    if go and req.strip():
        with st.status("正在生成…", expanded=True) as status:
            result = run(req.strip(), on_step=lambda m: st.write(m))
            status.update(label="生成完成", state="complete", expanded=False)
        out = save_all(result)
        st.session_state["result"] = result
        st.session_state["out"] = str(out)

    res = st.session_state.get("result")
    if not res:
        st.info("在上方输入需求后点击「生成纹样方案」。")
    else:
        recipe, card, hits = res["recipe"], res["card"], res["hits"]
        st.divider()

        # ---------- ① 配方 ----------
        st.subheader("① 纹样文化配方")
        it = recipe.get("intent") or {}
        stc = recipe.get("structure") or {}
        cm = stc.get("center_motif") or {}
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**场合**：{'、'.join(it.get('occasion') or []) or '—'}")
            st.markdown(f"**用途**：{it.get('purpose') or '—'}")
            st.markdown(f"**寓意**：{'、'.join(it.get('blessing') or []) or '—'}")
            st.markdown(f"**风格**：{it.get('style') or '—'}")
        with c2:
            st.markdown(f"**中心母题**：{cm.get('name') or '—'}")
            st.markdown(f"**构成元素**：{'、'.join(cm.get('elements') or []) or '—'}")
            st.markdown(f"**边饰**：{(stc.get('border') or {}).get('pattern') or '—'}")
            st.markdown(f"**角花**：{(stc.get('corner') or {}).get('pattern') or '—'}")
            st.markdown(f"**对称**：{stc.get('symmetry') or '—'}")
        for w in recipe.get("warnings") or []:
            st.warning(w)
        with st.expander("查看配方 JSON"):
            st.json(recipe)

        # ---------- ② 检索结果 ----------
        # ★ 注意：retrieve() 会把"配方指定槽位（边饰/角花）"的命中**钉到榜单最前面**（槽位保底机制），
        #   所以这份列表**不是**严格按相似度排序的。必须把这个机制显式标出来 ——
        #   否则界面上会出现"相似度 0.45 排在 0.75 前面"，看起来像 bug。
        st.subheader("② 真实纹样元素检索结果")
        n_pin = sum(1 for h in hits if h.get("slot"))
        if n_pin:
            st.caption(f"共 {len(hits)} 个候选。其中前 {n_pin} 个为**配方指定槽位（边饰 / 角花）的保底命中**"
                       "——它们的绝对相似度天然偏低，若不保底会被挤出榜单；其余按相似度排序。")
        else:
            st.caption(f"共 {len(hits)} 个候选（按相似度排序）")
        if hits:
            ncol = min(5, len(hits))
            cols = st.columns(ncol)
            for i, h in enumerate(hits):
                s = h["sample"]
                with cols[i % ncol]:
                    ip = ROOT / s["image_path"]
                    if ip.exists():
                        st.image(str(ip), width=150)
                    st.markdown(f"**{s['name']}**")
                    if h.get("slot"):
                        st.caption(f"★ 配方「{SLOT_CN.get(h['slot'], h['slot'])}」槽位保底命中")
                    st.caption(f"相似度 {h.get('score', 0):.2f}｜{s.get('category', '')}")

        # ---------- ③ 文化校验 ----------
        st.subheader("③ 文化规则校验")
        vs = recipe.get("violations") or []
        if not vs:
            st.success("未检出文化规则违规")
        else:
            painter = {"high": st.error, "medium": st.warning, "low": st.info}
            for v in vs:
                painter.get(v.get("severity"), st.info)(
                    f"[{v.get('rule_id', '')}] {v.get('message', '')}")
                if v.get("source"):
                    st.caption(f"依据：{v['source']}")

        # ---------- ④ 溯源卡片 ----------
        st.subheader("④ 元素级溯源卡片")
        png = Path(st.session_state.get("out", "")) / "provenance_card.png"
        if png.exists():
            st.image(str(png), width="stretch")
        else:
            st.caption("（卡片图未生成，以下为文字版）")
        with st.expander("查看卡片文字版", expanded=False):
            st.markdown(to_markdown(card))

        if res.get("errors"):
            with st.expander("降级记录（不影响主链路）"):
                for e in res["errors"]:
                    st.write("- " + e)

        # ---------- ⑤ AI 风格化（可选，不可溯源） ----------
        st.divider()
        st.subheader("⑤ AI 风格化（可选）")
        # ★★ 这段声明必须显式放在界面上，不能只写在文档里。
        #    指南要求："报告与界面中必须明确区分【组合式合成（可溯源）】
        #    与【AI 风格化（不可溯源）】，不要混在一起宣称 100% 可溯源。"
        st.warning("**AI 风格化 · 元素级溯源不适用** —— 本步骤由扩散模型重绘，"
                   "元素与纹理为 AI 生成，**不参与元素级溯源**。"
                   "可溯源的部分只有 ①–④（配方 / 检索 / 校验 / 溯源卡片）。"
                   "**请勿把本步结果与溯源卡片混在一起展示。**")

        comp = Path(st.session_state.get("out", "")) / "composed_pattern.png"
        if comp.exists():
            st.caption("参考图（M4a 组合纹样图，元素级可溯源）：")
            st.image(str(comp), width=420)

        c1, c2 = st.columns([3, 2])
        with c1:
            strength = st.radio(
                "风格化强度",
                options=[0.30, 0.85],
                format_func=lambda v: ("探索档 0.30 —— 好看，但元素会被重绘"
                                       if v < 0.5 else
                                       "保构图档 0.85 —— 构图保住，风格化明显"),
                key="m5_strength")
        with c2:
            st.caption("每张约 35 秒并消耗 API 额度，**刻意不自动跑**，需手动点击。")
            go_s = st.button("生成风格化效果", key="m5_go", type="primary")

        if go_s and comp.exists():
            with st.spinner(f"调用通义万相风格化（ref_strength={strength}），约 35 秒…"):
                try:
                    from src.m5_stylize import stylize
                    rec = json.loads((Path(st.session_state["out"]) / "recipe.json")
                                     .read_text(encoding="utf-8"))
                    info = stylize(comp, rec,
                                   Path(st.session_state["out"]) / f"stylized_{int(strength * 100)}.png",
                                   strength, rec.get("recipe_id", ""))
                except Exception as e:
                    info = None
                    st.error(f"风格化失败：{type(e).__name__}: {e}")
            if info:
                st.session_state["m5_info"] = info

        info = st.session_state.get("m5_info")
        if info and Path(info["file"]).exists():
            st.image(info["file"], width="stretch")
            m1, m2 = st.columns(2)
            m1.metric("构图漂移（phash）", info["phash_drift"])
            m2.metric("ref_strength", info["ref_strength"])
            st.caption(f"⚠️ {info['disclaimer']}")

        # ---------- ⑥ 文创效果预览（3D，载体层不参与元素级溯源） ----------
        st.divider()
        st.subheader("⑥ 文创效果预览（3D）")
        # ★ 与 ⑤ 同理：这里的声明必须显式放在界面上，不能只写在文档里。
        st.info("**纹样层可溯，载体层不参与元素级溯源** —— "
                "本例把上一步的**组合纹样图**贴附到三种器物形态上，用于预览文创落地效果。"
                "纹样仍来自语义层母题库（**元素级可溯**）；"
                "而三种器物形态是**程序化生成的标准几何体**，"
                "**不是文物三维模型、也不是 AI 生成**，因此不引入新的溯源问题。")
        st.caption("⚠️ 形态为示意性预览，**不代表任何具体器物的真实形制或三维复原**。")

        if comp.exists():
            st.caption(
                "下方**交互式三维预览**可直接拖拽旋转查看 —— 它是**经 Three.js 渲染的真实 GLB 文件**，"
                "与 ⑤ 的静态效果图是两回事：静态图只能看，而这里可以转、可以下载、可以带进别的软件。"
            )
            c3, c4 = st.columns([3, 2])
            with c3:
                q = st.radio("静态效果图质量",
                             options=["fast", "high"],
                             format_func=lambda v: ("快速预览（约 15 秒，适合演示）"
                                                    if v == "fast" else
                                                    "高清（约 2 分钟，适合出图）"),
                             key="p3d_q")
                # ★ 贴图方案：让用户自己选"要不要把 AI 风格化图用进 3D"
                #   两种方案**只在"地子（底色层）"上不同**，主题纹/边饰的来源
                #   完全一致 —— 所以元素级溯源口径不受影响。
                tile_mode = st.radio(
                    "3D 贴图方案",
                    options=["plain", "style"],
                    format_func=lambda v: (
                        "① 合成贴图（推荐·口径最简）" if v == "plain"
                        else "② 风格化贴图（底纹取 AI 图·更饱满）"),
                    key="p3d_tex",
                    help="两者纹样来源相同；区别只在底色层。"
                         "② 会把 M5 风格化图的色彩氛围抽成底纹，"
                         "解决白底太素的问题，底注会自动注明「底纹经风格化」。")
            with c4:
                st.caption("静态图：纯 CPU 解析渲染，**无需 GPU**。")
                go3 = st.button("生成静态效果图 + GLB", key="p3d_go", type="primary")

            if go3:
                out_dir = Path(st.session_state["out"])
                rec = json.loads((out_dir / "recipe.json").read_text(encoding="utf-8"))
                # ⓪ 先检索一次（静态图与 GLB 共用同一份 hits）
                #    ★ 必须放在两个 try 之外：检索一旦失败就该整体中止，
                #      而且 hits 若在静态图的 try 里赋值，静态图失败时
                #      下面 export_all(rec, hits, ...) 会抛 NameError，
                #      报错信息会完全指错方向（实测踩过）。
                from src.m2_retrieve import retrieve
                hits = retrieve(rec, top_k=10)
                # ⓪b 风格化方案：找 M5 的风格化图（找不到就退回合成贴图）
                style_img = None
                if tile_mode == "style":
                    cands = sorted(out_dir.glob("stylized_*.png"),
                                   key=lambda p: p.stat().st_mtime, reverse=True)
                    if cands:
                        style_img = cands[0]
                    else:
                        st.warning("没找到本配方的风格化图（stylized_*.png），"
                                   "本次退回「合成贴图」。请先在 ⑤ 区生成风格化图。")
                # ① 静态效果图（三形态三联图）
                with st.spinner(f"渲染三种形态静态图（{q}）…"):
                    try:
                        from src.preview3d import render_preview
                        paths = render_preview(comp, out_dir, rec, hits=hits,
                                               quality=q, style_img=style_img)
                        st.session_state["p3d_paths"] = {k: str(v)
                                                         for k, v in paths.items()}
                        # 记下本次是否真的用了 AI 地子（供查看器文案用）
                        st.session_state["p3d_ground"] = (
                            "ai" if style_img is not None else "neutral")
                    except Exception as e:
                        st.error(f"静态效果图失败：{type(e).__name__}: {e}")
                # ② GLB（带贴图，供查看器与下载）
                with st.spinner("导出 GLB（可直接下载 / 进 Blender）…"):
                    try:
                        from src.glb_export import export_all
                        made = export_all(rec, hits, out_dir, style_img=style_img)
                        ok = sum(1 for m in made.values() if m["ok"])
                        st.session_state["glb_info"] = {
                            k: {"path": m["info"]["path"],
                                "kb": round(m["info"]["bytes"] / 1024),
                                "ok": m["ok"]}
                            for k, m in made.items()}
                        if ok != 3:
                            st.warning(f"GLB 结构校验 {ok}/3 通过，"
                                       "请检查 outputs 目录。")
                    except Exception as e:
                        st.session_state["glb_info"] = None
                        st.error(f"GLB 导出失败：{type(e).__name__}: {e}")

            p3 = st.session_state.get("p3d_paths") or {}
            tri = p3.get("triptych")
            if tri and Path(tri).exists():
                st.image(tri, width="stretch")
                with st.expander("查看单形态大图"):
                    cols = st.columns(3)
                    for col, (k, lab) in zip(cols, (("vase", "陶瓶（梅瓶）"),
                                                    ("box", "包装方盒"),
                                                    ("fan", "团扇"))):
                        p = p3.get(k)
                        if p and Path(p).exists():
                            col.image(p, caption=lab, width="stretch")
                st.caption("纹样层：来自语义层母题库，元素级可溯　｜　"
                           "载体层：程序化生成的标准几何体（非文物三维模型、非 AI 生成），仅作形态预览")

            # ---------- 交互式三维查看器（内嵌 GLB） ----------
            glb = st.session_state.get("glb_info")
            if glb:
                st.markdown("##### 交互式三维预览")
                st.caption("拖拽旋转 · 滚轮缩放 · 右键平移。"
                           "下面嵌入的是**真实的 GLB 模型**（纹样贴图已打包在内）。")
                _embed_viewer(glb, st.session_state.get("p3d_ground", "neutral"))
                st.caption("下载的 `.glb` 是业界通用格式，可直接拖进 Blender / Unity "
                           "或任意在线 glTF 预览器打开。")

# ================================================================ Tab 2
with tab_check:
    st.markdown("上传一张纹样图片，系统会与样本库比对，给出**相似度风险分级**。")
    st.caption("可用于审查 AI 生成结果，也可用于审查自带的文创设计稿。")
    up = st.file_uploader("选择图片", type=["jpg", "jpeg", "png"])

    if up:
        tmp = ROOT / "outputs" / "_upload_tmp.jpg"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(up.getbuffer())
        c1, c2 = st.columns([1, 2])
        with c1:
            st.image(str(tmp), width="stretch")
            st.caption(up.name)
        with c2:
            with st.spinner("正在双路比对…"):
                try:
                    r = assess(tmp)
                except Exception as e:
                    r = None
                    st.error(f"比对失败：{type(e).__name__}: {e}")
            if r:
                painter = {"high": st.error, "medium": st.warning, "low": st.success}
                painter.get(r["risk_level"], st.info)(
                    f"风险等级：**{r['risk_level'].upper()}**")
                m1, m2 = st.columns(2)
                m1.metric("结构层·最近汉明距离", r["phash"]["min_distance"])
                m2.metric("语义层·最高余弦相似度", r["semantic"]["max_similarity"])
                for x in r.get("reasons", []):
                    st.write("· " + x)
                st.caption(f"⚠️ {r.get('disclaimer', '')}")
        tmp.unlink(missing_ok=True)