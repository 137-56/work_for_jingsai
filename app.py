# app.py
"""纹初迹现 · 传统纹样可溯源生成系统 —— 演示界面（B7）。

单页三个标签页：
  Tab 1「生成与溯源」    一句需求 → 配方 → 检索 → 校验 → 溯源卡片
  Tab 2「版权相似度审查」 上传任意图片 → 与样本库比对的相似度风险分级
  Tab 3「纹样谱系」      全库 100 条母题的关联网络 / 五族谱系（**全库级视图**）

★ 为什么 M7 单独一个标签页：
    M4（组合式合成）尚未实现，生成流程里没有"合成图"可供比对。
    而 M7 的真实价值本来就是"审查任意一张设计图与本库是否雷同"，
    所以它天然适合作为独立入口，而不是硬挂在生成流程末尾。

★ 为什么谱系图也单独一个标签页：
    它是**全库级**视图（100 条母题之间的关联），与"某一个配方怎么生成"无关。
    硬塞进生成页末尾会造成语义混乱 —— 用户会以为它跟当前配方有关。
    注意区分两种溯源：① 本页是**谱系级**（这一类纹样跟谁最近）；
                     ② 生成页的溯源卡片是**元素级**（这张图的每个部件来自哪条母题）。
    两者互补，谱系级回答的是元素级给不出的问题。

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
    st.markdown("**三种溯源层次**")
    st.caption(
        "- 元素级 — 每个部件的出处（生成页）\n"
        "- 谱系级 — 这类纹样跟谁最近（纹样谱系页）\n"
        "- 风险级 — 与库内是否雷同（版权审查页）"
    )
    st.divider()
    st.caption("**数据来源**")
    st.caption(ATTRIBUTION_SHORT)
    st.divider()
    st.caption("首次运行需加载 CLIP 模型（约 20–40 秒），之后会缓存。")


st.title("纹初迹现 · 传统纹样可溯源生成系统")
st.caption("一句需求 →《纹样文化配方》→ 真实纹样元素检索 → 文化校验 → 元素级溯源卡片")

tab_gen, tab_check, tab_kin = st.tabs(
    ["生成与溯源", "版权相似度审查", "纹样谱系"])

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


# ================================================================ Tab 3
# 纹样谱系 —— 全库级视图。
#
# ★ 为什么用缓存的静态图，而不是在 Streamlit 里重绘
#   scripts/build_kinship_graph.py 里的绘图逻辑已经调好了中文字体、配色与排版，
#   在界面里再写一套 matplotlib 渲染 = 两套实现必然发散（改了脚本忘了改界面）。
#   这里只做三件事：① 直接展示脚本产出的 PNG；② 现算指标卡；③ 现算五族名单。
#
# ★ 为什么指标与名单要现算、不能写死
#   B2-3 曾硬编码"排不到第 1 的 5 条"，实测其中 2 条其实排到了第 1。
#   凡清单必须从 samples.json 现算 —— 数据一变，图与文字就不同步了。
def _load_kinship():
    """复用 build_kinship_graph 的建图逻辑，返回 (母题图 G, 统计 dict, 五族列表)。

    ★ 必须复用脚本里的 load_graph()，不能在这里另写一遍读 samples.json 的逻辑 ——
      否则"图里画的"与"界面说的"是两套代码算出来的，迟早不一致。
      该脚本无第三方副作用（matplotlib 用 Agg 后端，仅导入不弹窗）。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_kinship_build", ROOT / "scripts" / "build_kinship_graph.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    G, _H, stats = mod.load_graph()
    try:
        from networkx.algorithms.community import (
            greedy_modularity_communities, modularity)
        comms = list(greedy_modularity_communities(G))
        stats["modularity"] = round(float(modularity(G, comms)), 3)
        stats["n_community"] = len(comms)
    except Exception:
        comms = []
        stats["modularity"], stats["n_community"] = None, 0
    deg = dict(G.degree())
    if deg:
        stats["max_degree_node"] = max(deg, key=deg.get)
        stats["max_degree"] = max(deg.values())
        stats["isolated"] = len(list(__import__("networkx").isolates(G)))
    return G, stats, sorted(comms, key=len, reverse=True)


@st.cache_data(show_spinner=False)
def _kinship():
    """把图对象转成可缓存的基本类型（networkx 对象不能被 cache_data 序列化）。

    社群检测（385 边）与度数统计耗时约数十毫秒，缓存后 rerun 不再重算。
    """
    import networkx as nx

    G, stats, comms = _load_kinship()
    deg = dict(G.degree())
    families = []
    for c in comms:
        mem = sorted(c, key=lambda n: -deg.get(n, 0))
        families.append({
            "size": len(mem),
            "hub": mem[0] if mem else "—",
            "hub_degree": deg.get(mem[0], 0) if mem else 0,
            "members": [(n, deg.get(n, 0)) for n in mem],
        })
    return stats, families, nx.number_of_isolates(G)


@st.cache_data(show_spinner=False)
def _family_names():
    """族名 —— 从脚本 import，**不在界面里另写一份**（两处各写必然错位）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_kinship_names", ROOT / "scripts" / "build_kinship_graph.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return list(mod.FAMILY_NAMES)


with tab_kin:
    st.markdown("### 纹样谱系 · 全库级视图")
    st.caption(
        "把「单个纹样的溯源」升级为「纹样谱系」—— 回答一个元素级溯源给不出的问题："
        "**这类纹样在谱系上跟谁最近？**"
    )

    stats_k, families, n_iso = _kinship()

    st.divider()

    # ---------- ① 指标卡 ----------
    st.subheader("① 全库谱系指标")
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("母题节点", stats_k.get("n_motif", "—"))
    k2.metric("关联边（去重）", stats_k.get("n_edge", "—"),
              help=f"源数据「关联纹样」字段共 {stats_k.get('raw_refs', '—')} 次引用，"
                   f"本库内去重后为无向边数")
    k3.metric("社群（族）", stats_k.get("n_community", "—"))
    k4.metric("模块度", stats_k.get("modularity", "—"),
              help="modularity 社群检测算法的质量指标，越高说明分群越清晰")
    k5.metric("孤立母题", n_iso,
              help="没有任何关联边的母题数。为 0 说明全库连通，没有掉队的纹样")

    if stats_k.get("max_degree_node"):
        st.markdown(
            f"**枢纽纹样**：`{stats_k['max_degree_node']}`（度 "
            f"{stats_k['max_degree']}）—— 全库关联最多的母题，处在谱系中心位置。"
        )
    st.caption("关联数据完全取自源数据既有字段，**未作任何推测性补充**。")

    st.divider()

    # ---------- ② 五族谱系图 ----------
    st.subheader("② 五族谱系图")
    _ft = ROOT / "docs" / "figures" / "kinship_family_tree.png"
    if _ft.exists():
        st.image(str(_ft), width="stretch")
        st.caption(
            "分群由 modularity 社群检测算法得出；**族名是人工按成员构成元素读出的归类**，"
            "不是算法输出。◆ 标记该族枢纽纹样。"
        )
    else:
        st.warning(f"未找到五族谱系图（{_ft.relative_to(ROOT)}）。"
                   "请运行 `python scripts/build_kinship_graph.py` 生成。")

    # 五族名单：现算，可展开逐个查看
    st.markdown("**各族成员名单**（按关联度数降序，现算自 `samples.json`）")
    st.caption("族名按社群规模降序对应图谱系图中的列（从左到右）。"
               "族名与图共用同一常量，不会错位。")
    _names = _family_names()
    for i, fam in enumerate(families):
        _name = _names[i] if i < len(_names) else f"族 {i + 1}"
        with st.expander(f"{_name} ｜ {fam['size']} 条 ｜ 枢纽：{fam['hub']}"
                         f"（度 {fam['hub_degree']}）"):
            _cols = st.columns(3)
            for j, (n, d) in enumerate(fam["members"]):
                _mark = "◆ " if n == fam["hub"] else "· "
                _cols[j % 3].markdown(f"{_mark}{n}　`{d}`")

    st.divider()

    # ---------- ③ 网络图 ----------
    st.subheader("③ 母题关联网络 / 元素共现网络")
    _n1, _n2 = st.columns(2)
    with _n1:
        _p = ROOT / "docs" / "figures" / "kinship_motif_network.png"
        if _p.exists():
            st.image(str(_p), width="stretch")
            st.caption("母题关联网络：节点大小按关联度数、颜色按社群。适合做 PPT 主视觉。")
    with _n2:
        _p = ROOT / "docs" / "figures" / "kinship_element_network.png"
        if _p.exists():
            st.image(str(_p), width="stretch")
            st.caption("构成元素共现网络：两个元素若出现在同一条母题里则连边。")

    st.divider()

    # ---------- ④ 诚实的负结论（★ 必须有，否则演示时会被问住）----------
    st.subheader("④ 这张图的价值，以及它**没有**做到的事")
    st.markdown(
        "关联数据对本系统的**检索指标没有正向作用** —— 这一点我们做了消融实验，如实报告："
    )
    _abl = [
        ("输入=仅名称", "0.59", "0.19", "0.16"),
        ("输入=名称+元素", "0.97", "0.96", "0.94"),
        ("输入=仅元素", "0.96", "0.94", "0.91"),
    ]
    st.table({
        "检索输入": [a[0] for a in _abl],
        "基线 Top-1": [a[1] for a in _abl],
        "+ 关联扩展 (expand)": [a[2] for a in _abl],
        "+ 关联加权 (boost)": [a[3] for a in _abl],
    })
    st.caption("Top-1 命中率。三种输入下，引入关联数据均**未带来提升**（多为下降）。")

    st.markdown(
        "我们把这条**负结论**留在系统里，因为它是真的，而且它澄清了关联数据的正确用法：\n\n"
        "- **不该**拿它去做检索扩展或加权 —— 实测无效，还会拖低指标；\n"
        "- **应当**拿它做**可解释性**与**相关参考** —— 在检索结果里回答"
        "「为什么这几个纹样常一起出现」，这是相似度分数给不出的信息。\n\n"
        "`expand`（把关联纹样一并塞进候选）会把噪声一起带进来，"
        "在「仅名称」输入下 Top-1 从 0.59 掉到 0.19，正说明这一点。"
    )

    st.info(
        "**一句话总结**：谱系图不提升准确率，它提升的是**可理解性**。"
        "这恰好是「可溯源生成系统」立项时最想解决的问题 —— "
        "让机器给出的结果**有据可查、有理可讲**。"
    )

    with st.expander("查看完整消融实验结果（JSON）"):
        _exp = ROOT / "docs" / "exp_related_motifs.json"
        if _exp.exists():
            st.json(json.loads(_exp.read_text(encoding="utf-8")))
        else:
            st.caption("未找到 docs/exp_related_motifs.json")