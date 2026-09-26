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
            c3, c4 = st.columns([3, 2])
            with c3:
                q = st.radio("渲染质量",
                             options=["fast", "high"],
                             format_func=lambda v: ("快速预览（约 15 秒，适合演示）"
                                                    if v == "fast" else
                                                    "高清（约 2 分钟，适合出图）"),
                             key="p3d_q")
            with c4:
                st.caption("纯 CPU 解析渲染，**无需 GPU**，结果可复现。需手动点击。")
                go3 = st.button("生成 3D 文创预览", key="p3d_go", type="primary")

            if go3:
                with st.spinner(f"渲染三种形态（{q}）…"):
                    try:
                        from src.preview3d import render_preview
                        rec = json.loads((Path(st.session_state["out"]) / "recipe.json")
                                         .read_text(encoding="utf-8"))
                        paths = render_preview(comp, Path(st.session_state["out"]),
                                               rec, quality=q)
                        st.session_state["p3d_paths"] = {k: str(v) for k, v in paths.items()}
                    except Exception as e:
                        st.error(f"3D 预览失败：{type(e).__name__}: {e}")

            p3 = st.session_state.get("p3d_paths") or {}
            tri = p3.get("triptych")
            if tri and Path(tri).exists():
                st.image(tri, width="stretch")
                with st.expander("查看单形态大图"):
                    cols = st.columns(3)
                    for col, (k, lab) in zip(cols, (("vase", "陶瓶"),
                                                    ("box", "包装方盒"),
                                                    ("plate", "赏盘"))):
                        p = p3.get(k)
                        if p and Path(p).exists():
                            col.image(p, caption=lab, width="stretch")
                st.caption("纹样层：来自语义层母题库，元素级可溯　｜　"
                           "载体层：程序化生成的标准几何体（非文物三维模型、非 AI 生成），仅作形态预览")

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