# app.py
"""纹初迹现 · 传统纹样可溯源生成系统 —— 演示界面（B7）。

单页三个标签页：
  Tab 1「生成与溯源」    一句需求 → 配方 → 检索 → 校验 → 溯源卡片
  Tab 2「版权相似度审查」 上传任意图片 → 与样本库比对的相似度风险分级
  Tab 3「纹样谱系」      全库 100 条母题的关联网络 / 五族谱系（**全库级视图**）

★ 为什么 M7 单独一个标签页：
    M4 已实现设计依据板与 composed_pattern.png 真组合合成，生成流程内已有合成图。
    但 M7 的价值是审查任意一张设计图与本库是否雷同（不限于流程内产出），
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

from src.m6_provenance import ATTRIBUTION_SHORT, SCORE_NOTE, to_markdown
from src.m7_copyright import assess
from src.pipeline import run, save_all
from src.utils import CFG
from src import disclosure
from src.run_source import FINAL_RUN
from src.wizard import (
    STATE_EMPTY, STATE_OPTIONAL, STATE_READY,
    WIZARD_STEPS, derive_states, step_by_id,
)

st.set_page_config(page_title="纹初迹现 · 可溯源纹样生成系统", layout="wide")

# ---------------------------------------------------------------- 视觉 token
# ★ 单一真源是 web/design-tokens.css（取值来自产物 design_board.png 的逐像素采样）。
#   这里只负责**注入**，不重复定义任何色值 —— 否则就又多出第四套配色。
#   为什么注入 <style> 而不是 <link href="/app/static/...">：
#   静态目录依赖 server.enableStaticServing，注入 <style> 不依赖任何静态服务，
#   离线、headless 截图、打包分发三种场景都成立。
_TOKENS_CSS = ROOT / "web" / "design-tokens.css"


def _inject_tokens() -> None:
    """把 design-tokens.css 注入页面。取不到就静默退回 Streamlit 默认主题。"""
    try:
        css = _TOKENS_CSS.read_text(encoding="utf-8")
    except Exception:
        return
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


_inject_tokens()

DEFAULT_REQ = "做一个有吉祥寓意的窗花，用于春节礼品包装"

# 配方槽位的中文名（用于标注"槽位保底命中"）
SLOT_CN = {"border": "边饰", "corner": "角花"}


@st.cache_data(show_spinner=False)
def sample_count():
    try:
        return len(json.loads((ROOT / CFG["paths"]["samples"]).read_text(encoding="utf-8")))
    except Exception:
        return 0


def _embed_viewer(glb_info, ground="neutral", disclosure_lines=None):
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

    # ★ 把六句声明写成 JSON 交给查看器读取 —— 查看器是纯静态页，import 不了 Python，
    #   若不这么做，viewer.html 里就必须再硬编码一份（历史上正是"4 份副本"之一）。
    #   没有 JSON 时查看器会回退到内置文案，不会白屏。
    if disclosure_lines:
        try:
            (static_dir / "disclosure.json").write_text(
                json.dumps([{"label": x["label"], "text": x["text"]}
                            for x in disclosure_lines if x.get("status") != "pending"],
                           ensure_ascii=False, indent=1),
                encoding="utf-8")
        except Exception:
            pass  # 写不进去不影响主流程，查看器走内置兜底

    # 查看器与 Three.js（只需拷一次，但检查一下以防首次）
    # ★ design-tokens.css 必须一起拷：viewer.html 用 <link href="./design-tokens.css">
    #   引用它。漏拷的后果是查看器拿不到 CSS 变量，页面配色全丢（但不报错）。
    for rel in ("viewer.html", "design-tokens.css",
                "vendor/three.min.js", "vendor/GLTFLoader.js"):
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


def _render_elements(items, width=150, strong=True, show_category=True):
    """渲染一组溯源元素（图 + 名 + 匹配分 + 出处 id）。

    ★ 为什么分组渲染而不是一列到底（2026-10-28 实测）
      `card.json.elements` 的顺序是 **role 语义序**，不是分数序：
        蝙蝠纹 0.75(center) → 回纹 0.45(border) → 如意纹 0.45(corner)
        → 祥云纹 0.60 → 麒麟纹 0.59 → …（reference 组内降序）
      如果按分数全局排，中心母题会被挤到第 2 位、边饰角花掉到 9/10 位 —— 结构就散了；
      如果原样平铺，又会出现「0.45 后面跟着 0.60」，看起来像排序 bug。
      两条路都错，所以按 role 分组：结构组在上、参考组在下，各组标题写明排序依据。

    ★ 降级手段只允许改尺寸/留白/字重/边框，**不许碰像素**
      （opacity / grayscale / 蒙层 都不行）—— 参考组的图也是证据，调暗等于对证据做视觉降权。
    """
    if not items:
        return
    ncol = min(5, len(items))
    cols = st.columns(ncol)
    for i, e in enumerate(items):
        with cols[i % ncol]:
            ip = ROOT / (e.get("image_path") or "")
            if e.get("image_path") and ip.exists():
                st.image(str(ip), width=width)
            else:
                # ★ 缺图必须如实说。Web 演示版用的是 onerror 回落到首图 —— 张冠李戴。
                st.caption("图像缺失")
            name = e.get("element") or e.get("source_name") or "—"
            st.markdown(f"**{name}**" if strong else name)
            sim = e.get("similarity")
            sim_txt = f"匹配分 {sim:.2f}" if isinstance(sim, (int, float)) else "匹配分 —"
            tail = f"｜{e.get('source_id', '')}"
            if show_category and e.get("category"):
                tail += f"｜{e['category']}"
            st.caption(sim_txt + tail)


_FORM_CN = {"vase": "陶瓶（梅瓶）", "box": "包装方盒", "fan": "团扇"}


def _band_rows(bands):
    """把 preview3d_layout 的环带数组转成表格行。

    ★ `sample: null` 的环带是"素地弦纹"（分隔带），不是缺数据 ——
      写成「素地（无母题）」而不是留空，否则看起来像溯源断了。
    """
    rows = []
    for b in bands or []:
        v = b.get("v")
        rows.append({
            "band": b.get("label") or "—",
            "v": f"{v[0]:.2f}–{v[1]:.2f}" if isinstance(v, (list, tuple)) and len(v) == 2 else "—",
            "motif": b.get("motif") or "素地（无母题）",
            "sample": b.get("sample") or "—",
        })
    return rows


def _md_table(rows):
    if not rows:
        return ""
    out = ["| 环带 | 位置 v | 纹样 | 出处 |", "|---|---|---|---|"]
    out += [f"| {r['band']} | {r['v']} | {r['motif']} | {r['sample']} |" for r in rows]
    return "\n".join(out)


def _bands_block(layout):
    """渲染逐环带溯源清单。

    ★ 这是本项目 3D 部分**真正的资产**，不是装饰：
      它回答"这件器物的哪一圈来自哪条纹样"，而 Web 演示版的 `<model-viewer>`
      只能转、转完说不出任何出处。所以 3D 这一项不是 work_two 更强，而是相反。
    ★ 行数用 len(bands) 递归求和，不硬编码（实测 vase 8 / box 5+盒盖 2 / fan 3）。
    """
    if not isinstance(layout, dict):
        return
    forms = [k for k in ("vase", "box", "fan") if isinstance(layout.get(k), dict)]
    if not forms:
        return

    with st.expander("查看各形态的逐环带出处 —— 哪一圈来自哪条纹样", expanded=False):
        for k in forms:
            node = layout[k]
            st.markdown(f"**{_FORM_CN[k]}**")
            lid = node.get("lid") or {}
            if lid.get("bands"):
                # ★ 盒盖是嵌套子结构，**不能平铺**：平铺会把"盒盖主题纹"
                #   说成盒身的一个环带。分两组、盒盖缩进一级。
                st.markdown("盒身")
                st.markdown(_md_table(_band_rows(node.get("bands"))))
                st.markdown("盒盖")
                st.markdown(_md_table(_band_rows(lid.get("bands"))))
            else:
                st.markdown(_md_table(_band_rows(node.get("bands"))))
            st.caption("")

        # ★ 盒盖 / 扇面的环带在 layout 里只记 `motif`、不记 `sample` id
        #   （实测：box.lid 与 fan 的 bands 全部 sample=null）。
        #   出处栏写「—」是**如实**，不是溯源断了 —— 但必须说一句，
        #   否则读者会以为这两件器物的纹样没有出处。
        _miss = [b for k in forms
                 for b in ((layout[k].get("lid") or {}).get("bands")
                           or layout[k].get("bands") or [])
                 if b.get("motif") and not b.get("sample")]
        if _miss:
            st.caption("盒盖 / 扇面的环带在布局数据里只记录纹样名、未记录 sample id，"
                       "故出处栏为「—」；对应母题与授权见 ④ 区溯源卡片。")


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

    # ---------- 六步向导导航（外层信息架构） ----------
    # ★ 只叠加一层「这一步回答什么问题」的叙事：下面 ①–⑥ 各区内部实现一行不动。
    #   状态由 src.wizard 从本次 result 派生；run 事实只取 src.run_source。
    with st.container(key="wizard_nav", border=True):
        st.markdown("##### 六步向导 · 每一步回答什么问题")
        _focus_id = st.radio(
            "查看步骤",
            options=[s.id for s in WIZARD_STEPS],
            format_func=lambda sid: step_by_id(sid).title,
            horizontal=True,
            label_visibility="collapsed",
            key="wizard_focus",
        )
        _focus = step_by_id(_focus_id or WIZARD_STEPS[0].id)
        st.markdown(f"**{_focus.title}**：{_focus.question}")
        st.caption(f"对应下方 {_focus.zone} 区 · 定稿 run 基准：{FINAL_RUN.name}")
        _state_cn = {
            STATE_READY: "本次结果已产出",
            STATE_EMPTY: "尚无结果",
            STATE_OPTIONAL: "可选 · 需手动触发",
        }
        with st.expander("查看 6 步状态（由本次生成结果派生）", expanded=False):
            for _st in derive_states(st.session_state.get("result")):
                st.caption(f"{_st['title']}｜{_state_cn.get(_st['state'], _st['state'])}"
                           f"｜{_st['hint']}")

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
        #   所以这份列表**不是**严格按匹配分排序的。必须把这个机制显式标出来 ——
        #   否则界面上会出现"匹配分 0.45 排在 0.75 前面"，看起来像 bug。
        #
        # ★ 口径（2026-10 统一）：这一列表里显示的是 `m2_retrieve` 的**融合分**
        #   （CLIP 余弦 + 0.15×构成元素重合），**不是**纯余弦相似度，
        #   因此全称「匹配分」——与 M6 溯源卡片同一口径。文案直接取 m6.SCORE_NOTE，
        #   保证界面与卡片不会再各说一套。M7 那一栏是真余弦相似度，仍叫「相似度」。
        st.subheader("② 真实纹样元素检索结果")
        n_pin = sum(1 for h in hits if h.get("slot"))
        if n_pin:
            st.caption(f"共 {len(hits)} 个候选。其中前 {n_pin} 个为**配方指定槽位（边饰 / 角花）的保底命中**"
                       "——它们的绝对匹配分天然偏低，若不保底会被挤出榜单；其余按匹配分排序。")
        else:
            st.caption(f"共 {len(hits)} 个候选（按匹配分排序）")
        st.caption(f"口径：{SCORE_NOTE}")
        # ★ 与 ④ 区双向互指：读者看到 10 条候选、④ 区只有 3 条构件，
        #   若只在 ④ 解释，读完 ② 仍然不知道为什么有 10 条。
        _n_struct = sum(1 for e in (card.get("elements") or [])
                        if e.get("role") in ("center_motif", "border", "corner"))
        st.caption(f"以下为**检索候选**；本方案实际采用其中 {_n_struct} 条作为构件（见 ④ 区）。")
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
                    st.caption(f"匹配分 {h.get('score', 0):.2f}｜{s.get('category', '')}")

        # ---------- ③ 文化校验 ----------
        st.subheader("③ 文化规则校验")
        vs = recipe.get("violations") or []
        # ★ 徽章三要素：**状态词 · 计数 · run id · 时间戳**。
        #   改造前只写一句「未检出文化规则违规」——没有计数、没有 run id、
        #   没有时间戳，读者无法判断这是"本次运行的结果"还是"写死的一句好话"。
        #   （Web 演示版正是硬编码的「校验通过」徽章，而它的 rules 字段是空数组。）
        #   ★ 时间戳唯一来源是 `card.generated_at`：recipe.json 没有 created_at，
        #     且**不能用文件 mtime** —— 拷贝/解压/move 都会改变 mtime。
        _rid = recipe.get("recipe_id") or card.get("recipe_id") or "—"
        _ts = card.get("generated_at") or "—"
        if not vs:
            st.success(f"未检出违规 · 0 条 · {_rid} · {_ts}")
        else:
            _hi = sum(1 for v in vs if v.get("severity") == "high")
            st.warning(f"检出违规 · {len(vs)} 条 · {_rid} · {_ts}"
                       + (f"　（其中 high {_hi} 条）" if _hi else ""))
            painter = {"high": st.error, "medium": st.warning, "low": st.info}
            for v in vs:
                painter.get(v.get("severity"), st.info)(
                    f"[{v.get('rule_id', '')}] {v.get('message', '')}")
                if v.get("source"):
                    st.caption(f"依据：{v['source']}")

        # ---------- ④ 溯源卡片 ----------
        st.subheader("④ 元素级溯源卡片")

        # ★ 3 + 1 分组（结构构件 / 相关参考），理由见 _render_elements 的 docstring。
        #   另外：② 区列了 10 条候选、④ 区只用 3 条做构件，读者一定会问
        #   "为什么 ② 有 10 条、④ 只用 3 条" —— 所以两区必须**双向互指**，
        #   只在一侧解释是不够的（读者可能在 ④ 才第一次见到这两个 0.45）。
        els = card.get("elements") or []
        struct = [e for e in els if e.get("role") in ("center_motif", "border", "corner")]
        refs = [e for e in els if e.get("role") == "reference"]

        if els:
            st.caption(
                f"本方案采用其中 **{len(struct)} 条**作为构件（中心母题 / 边饰 / 角花），"
                f"其余 {len(refs)} 条为相关参考。"
                f"② 区列出的是全部 {len(hits)} 条检索候选（含槽位保底命中），"
                "这里才是**实际进入方案**的构件。"
            )

        png = Path(st.session_state.get("out", "")) / "provenance_card.png"
        if png.exists():
            st.image(str(png), width="stretch")
        else:
            st.caption("（卡片图未生成，以下为文字版）")

        if struct:
            st.markdown("##### 构件 · 按结构角色排列")
            st.caption("分数为匹配分，**不是排序依据** —— 结构角色优先。")
            _render_elements(struct, width=150, strong=True)
            # ★ 显示低分而不解释，比不显示更危险：读者会以为"系统选了个不匹配的元素"。
            st.caption("边饰 / 角花为配方指定的结构槽位（`retrieve` 保底钉入），"
                       "其绝对匹配分天然偏低 —— 这是机制，不是选错。")
        if refs:
            st.markdown("##### 相关参考 · 按匹配分降序")
            _render_elements(refs, width=140, strong=False)

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
        else:
            # ★ 三态之一：本 run 未启用。必须显式写出来，否则读者不知道
            #   是"没做"还是"做了没显示"。
            st.caption(f"状态：本 run 未启用（无 `stylized_*.png`）"
                       f" · {recipe.get('recipe_id') or '—'} · {card.get('generated_at') or '—'}")

        # ---------- ⑥ 文创效果预览（3D，载体层不参与元素级溯源） ----------
        st.divider()
        st.subheader("⑥ 文创效果预览（3D）")

        # ★ 六句声明由 src/disclosure.py 单一真源生成。
        #   改造前这段是硬编码，且**只说了两层**（纹样层 + 载体层），
        #   材质层出处（克利夫兰实物）与授权（CC BY-NC 4.0）在界面上**完全不存在**。
        #   边界句 status=pending（口径待 Mr.G 定）→ 这里跳过不显示，**不摆占位符**。
        _run_dir = Path(st.session_state["out"]) if st.session_state.get("out") else None
        _layout = {}
        if _run_dir and (_run_dir / "preview3d_layout.json").exists():
            try:
                _layout = json.loads(
                    (_run_dir / "preview3d_layout.json").read_text(encoding="utf-8"))
            except Exception:
                _layout = {}
        _ground = (_layout.get("_render") or {}).get("ground_from") or "neutral"

        _lines = [x for x in disclosure.build(recipe, ground_from=_ground)
                  if x["status"] != "pending"]
        _rows = "".join(
            f'<div style="display:flex;gap:8px;margin:3px 0">'
            f'<b style="flex:0 0 68px;color:#2B2318">{x["label"]}</b>'
            f'<span style="color:#6E6656">{x["text"].split("：", 1)[-1]}</span></div>'
            for x in _lines)
        st.markdown(
            f'<div style="background:#FCF9F3;border:1px solid #DED4C0;'
            f'border-left:3px solid #C8102E;border-radius:10px;'
            f'padding:14px 16px;font-size:13px;line-height:1.85;color:#2B2318">{_rows}</div>',
            unsafe_allow_html=True)

        # ★ 三态之二：以 run 目录里是否真有 GLB 为准，不靠 session_state ——
        #   否则刷新页面后状态会"消失"，看起来像没生成过。
        _glb_done = bool(_run_dir and list(_run_dir.glob("pattern_*.glb")))
        st.caption(f"状态：{'已完成' if _glb_done else '本 run 未启用（尚未生成）'}"
                   f" · {recipe.get('recipe_id') or '—'} · {card.get('generated_at') or '—'}")

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
                # ★ 不再在这里重复声明 —— 六句口径统一由 ⑥ 区顶部
                #   src/disclosure.py 渲染。此处硬编码曾是"4 份副本"之一，
                #   多份并存的后果是"页面说一套、导出图说另一套"，且不报错。
                st.caption("溯源口径见本节顶部声明（纹样层 / 材质层 / 载体层 / 预览地子 / 授权）。")

            # ---------- 交互式三维查看器（内嵌 GLB） ----------
            glb = st.session_state.get("glb_info")
            if glb:
                st.markdown("##### 交互式三维预览")
                st.caption("拖拽旋转 · 滚轮缩放 · 右键平移。"
                           "下面嵌入的是**真实的 GLB 模型**（纹样贴图已打包在内）。")
                _embed_viewer(glb, st.session_state.get("p3d_ground", "neutral"),
                              disclosure_lines=_lines)
                _bands_block(_layout)
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