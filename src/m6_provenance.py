# src/m6_provenance.py
"""M6 溯源卡片：把检索结果组装成「元素 → 出处 → 寓意 → 授权」的结构化卡片。

这是把"可溯源"从说法变成**看得见的产出物**的地方。
关键点（详细实现指南 6.4）：
  · 出处链接要完整可用，不截断
  · 授权类型如实写（红线相关）
  · 相似度保留两位小数
  · 卡片里不能出现任何机构内部信息

本模块只负责**组装数据**（输出 dict）。渲染 PNG 是后续步骤 —— 管线只需 JSON 就能跑通。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 配方里各位置的中文名，给用户看
ROLE_CN = {"center_motif": "中心母题", "border": "边饰", "corner": "角花", "reference": "相关参考"}

# ─────────────────────────────────────────────────────────────────────────────
# ★ 数据来源署名 —— CC BY-NC 4.0 的「署名（BY）」是**强制法律义务**，不得删除或改写。
#   依据：Wényàng 的 LICENSE-CONTENT.md；格式见 文档/数据来源署名规范.md
#   卡片版面小，用压缩版 —— 但「作者名 + 作品名 + 协议名」三样一个都不能省。
# ─────────────────────────────────────────────────────────────────────────────
ATTRIBUTION_SHORT = ("数据来源：BLCaptain（爆裂队长NEXT）《中国传统纹样图鉴 Wényàng》"
                     "· CC BY-NC 4.0（署名 · 非商业）")

ATTRIBUTION_FULL = (
    "纹样图像与文字资料：BLCaptain（爆裂队长NEXT），《中国传统纹样图鉴 Wényàng》，"
    "https://github.com/dososo/chinese-traditional-patterns ，授权协议 CC BY-NC 4.0"
    "（署名 · 非商业性使用）。本项目仅对原始字段做规范化处理，并补充标注「使用场合」"
    "与「构成元素」两项派生字段；纹样图像本身未作修改。"
)

# 卡片里元素的展示顺序。
# 为什么不直接用检索结果的顺序：检索是按相似度排的，而槽位保底项（边饰/角花）
# 分数天然偏低、会被排到很后面甚至挤掉。展示顺序应该按"角色重要性"而不是分数。
ROLE_ORDER = {"center_motif": 0, "border": 1, "corner": 2, "reference": 3}


def _role_of(recipe, sample_name):
    """判断命中的样本对应配方的哪个位置。"""
    st = recipe.get("structure", {}) or {}
    cm = (st.get("center_motif") or {}).get("name")
    if sample_name == cm:
        return "center_motif"
    if sample_name == (st.get("border") or {}).get("pattern"):
        return "border"
    if sample_name == (st.get("corner") or {}).get("pattern"):
        return "corner"
    return "reference"


def build_card(recipe, hits):
    """hits 是 m2_retrieve.retrieve() 的返回值。返回溯源卡片 dict（指南 6.2 结构）。"""
    elements = []
    for h in hits:
        s = h["sample"]
        role = _role_of(recipe, s["name"])
        elements.append({
            "role": role,
            "role_cn": ROLE_CN.get(role, role),
            "element": s["name"],
            "source_id": s["id"],
            "source_name": s["name"],
            "category": s.get("category"),
            "carrier": s.get("carrier"),
            "dynasty": s.get("dynasty"),
            "meaning": s.get("meaning"),
            "source": s.get("source"),
            "source_url": s.get("source_url"),
            "license": s.get("license"),
            "similarity": round(float(h.get("score", 0)), 2),
            "image_path": s.get("image_path"),
        })

    # 按角色排序展示：中心母题 → 边饰 → 角花 → 相关参考
    elements.sort(key=lambda e: ROLE_ORDER.get(e["role"], 9))

    tz = timezone(timedelta(hours=8))
    return {
        "recipe_id": recipe.get("recipe_id", ""),
        "generated_at": datetime.now(tz).isoformat(timespec="seconds"),
        "user_request": recipe.get("user_request", ""),
        "center_motif": ((recipe.get("structure") or {}).get("center_motif") or {}).get("name", ""),
        "elements": elements,
        "note": "每个元素均可回指到样本库中的真实样本；溯源关系在生成时确定，非事后推测。",
        "attribution": ATTRIBUTION_SHORT,     # ★ CC BY-NC 的署名义务，渲染时务必带上
    }


def to_markdown(card):
    """文字版卡片 —— 省事，且 PPT 截图 / 报告附录都能直接用。"""
    L = [f"### 溯源卡片 · {card.get('recipe_id', '')}",
         f"- 需求：{card.get('user_request', '')}",
         f"- 生成时间：{card.get('generated_at', '')}",
         f"- 中心母题：{card.get('center_motif', '')}", "",
         "| 角色 | 元素 | 出处 | 载体 | 寓意 | 授权 | 相似度 |",
         "|---|---|---|---|---|---|---|"]
    for e in card.get("elements", []):
        L.append("| {} | {} | {} | {} | {} | {} | {:.2f} |".format(
            e.get("role_cn", ""), e.get("element", ""), e.get("source_name", ""),
            "/".join(e.get("carrier") or []), (e.get("meaning") or "")[:40],
            e.get("license", ""), e.get("similarity", 0)))
    L += ["", f"> {card.get('note', '')}"]
    # ★ 署名行：CC BY-NC 4.0 强制要求，不能因为"排版不好看"删掉
    L += ["", f"<sub>{card.get('attribution', ATTRIBUTION_SHORT)}</sub>"]
    return "\n".join(L)

# ══════════════════════════════════════════════════════════════════
# 以下为 B4 新增：把卡片渲染成 PNG
# ══════════════════════════════════════════════════════════════════

# ★★ 中文字体必须用 ImageFont.truetype **显式加载**。
#    PIL 的默认字体渲染中文 = 一片方块，**而且不报任何错**。
#    所以这里找不到字体时**直接抛异常**，绝不静默降级 —— 宁可报错也不要出方块图。
FONT_CANDIDATES = [
    r"C:/Windows/Fonts/msyh.ttc",      # 微软雅黑（本机实测存在，首选）
    r"C:/Windows/Fonts/simhei.ttf",    # 黑体
    r"C:/Windows/Fonts/simsun.ttc",    # 宋体
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",   # Linux 兜底
]

INK = (43, 35, 24)            # 墨 #2B2318
RED = (200, 16, 46)           # 正红 #C8102E
GOLD = (212, 175, 55)         # 浅金 #D4AF37
PAPER = (247, 241, 230)       # 米白 #F7F1E6
GREY = (122, 114, 100)
LINE = (222, 212, 192)
BAND = (238, 230, 214)
STRIPE = (252, 249, 243)

CARD_W = 2000                 # 画布宽（实测 2000×~1440，比例适合放 PPT）
MARGIN = 50
PAD = 14
LH = 34                       # 中文行距（22px 字号 × 1.55）

# 列定义：(列名, x, 宽)
COLS = [
    ("角色",    50,  130),
    ("元素",   180,  120),
    ("出处",   300,  120),
    ("载体",   420,  380),
    ("寓意",   800,  480),
    ("授权",  1280,  430),
    ("相似度", 1710,  140),
]
KEYS = ["role", "element", "source", "carrier", "meaning", "license", "sim"]

# 中文排版：这些标点**不允许出现在行首**（避头标点）
NO_LINE_START = set("。，、；：！？）〕」』】…—·%")


@lru_cache(maxsize=None)
def _font(size):
    """取中文字体。找不到就抛异常 —— 见 FONT_CANDIDATES 上方的说明。"""
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    raise RuntimeError(
        f"找不到可用中文字体，已试：{FONT_CANDIDATES}\n"
        "中文必须用 ImageFont.truetype 显式加载；用默认字体会渲染成方块且不报错。")


def wrap_cjk(text, font, max_w, draw):
    """按字符测量换行（中文没空格，textwrap 用不了）。

    同时处理**避头标点**：句号、逗号等不允许出现在行首
    （否则会出现「……装饰韵律」+ 单独一行「。」这种难看排版）。
    做法是把它强行留在上一行，允许该行轻微溢出（即"标点悬挂"）。
    """
    lines, cur = [], ""
    for ch in str(text or ""):
        if ch == "\n":
            lines.append(cur); cur = ""
            continue
        if cur and draw.textlength(cur + ch, font=font) > max_w:
            if ch in NO_LINE_START:        # 避头标点：不折行，留在本行
                cur += ch
                continue
            lines.append(cur); cur = ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines or [""]


def wrap_tokens(text, font, max_w, draw, sep=" / "):
    """按分隔符**逐项**换行 —— 用于「载体」这类列表拼接的字段。

    为什么不能按字符断：「服饰 / 瓷器 / … / 木雕 / 屏风」按字符断会产生
    「…石雕 / 木」+「雕 / 屏风」—— 把「木雕」拆成两行。按项断则保证每个载体名完整。
    """
    parts = [p for p in str(text or "").split(sep) if p]
    lines, cur = [], ""
    for p in parts:
        piece = p if not cur else sep + p
        if cur and draw.textlength(cur + piece, font=font) > max_w:
            lines.append(cur); cur = p
        else:
            cur += piece
    if cur:
        lines.append(cur)
    return lines or [""]


def _card_row(el):
    """把卡片里的一个元素摊平成"一行七列"的文字。"""
    return {
        "role": el.get("role_cn") or "",
        "element": el.get("element") or "",
        "source": el.get("source_name") or "",
        "carrier": " / ".join(el.get("carrier") or []),
        "meaning": el.get("meaning") or "",
        "license": el.get("license") or "",
        "sim": f"{float(el.get('similarity') or 0):.2f}",
    }


def render_card_png(card, out_path):
    """把溯源卡片渲染成 PNG。返回 (路径, (宽, 高))。

    为什么分两遍画：10 个元素的「寓意」「载体」长短不一，换行后行数不同，
    **总高必须动态算**（写死高度会裁切内容或留大片空白）。
    所以第一遍只测量、算总高；第二遍才建画布正式绘制。
    """
    fonts = {"title": _font(46), "meta": _font(22),
             "head": _font(24), "cell": _font(22), "foot": _font(19)}
    f_cell = fonts["cell"]

    # ---------- 第一遍：只测量，算总高 ----------
    scratch = Image.new("RGB", (CARD_W, 10), PAPER)
    sd = ImageDraw.Draw(scratch)
    packed = []
    for el in (card.get("elements") or []):
        r = _card_row(el)
        cells, n_lines = {}, 1
        for key, (label, x, w) in zip(KEYS, COLS):
            # 载体按项断行；其余是连续中文，按字符断行 + 避头标点
            fn = wrap_tokens if key == "carrier" else wrap_cjk
            lines = fn(r[key], f_cell, w - PAD, sd)
            cells[key] = lines
            n_lines = max(n_lines, len(lines))
        packed.append((cells, n_lines))

    y_table = MARGIN + 138 + 30 + 46
    h_rows = sum(n * LH + PAD * 2 for _, n in packed)
    y_foot = y_table + h_rows + 26
    total_h = y_foot + 40 + 34 + 30 + MARGIN

    # ---------- 第二遍：正式绘制 ----------
    img = Image.new("RGB", (CARD_W, total_h), PAPER)
    d = ImageDraw.Draw(img)

    # 页眉
    d.rectangle([0, 0, CARD_W, 8], fill=RED)
    d.text((MARGIN, MARGIN), "溯源卡片", font=fonts["title"], fill=INK)
    w_title = d.textlength("溯源卡片", font=fonts["title"])
    d.text((MARGIN + w_title + 24, MARGIN + 18), card.get("recipe_id", ""),
           font=fonts["head"], fill=RED)
    d.text((MARGIN, MARGIN + 64), f"生成时间：{card.get('generated_at', '')}",
           font=fonts["meta"], fill=GREY)
    d.text((MARGIN, MARGIN + 96), f"需求：{card.get('user_request', '')}",
           font=fonts["meta"], fill=GREY)
    d.line([MARGIN, MARGIN + 138, CARD_W - MARGIN, MARGIN + 138], fill=GOLD, width=2)

    # 表头行
    d.rectangle([MARGIN, y_table, CARD_W - MARGIN, y_table + 46], fill=BAND)
    for label, x, w in COLS:
        d.text((x + PAD // 2, y_table + 11), label, font=fonts["head"], fill=INK)

    # 元素行（隔行浅底 + 分隔线）
    yy = y_table + 46
    for i, (cells, n_lines) in enumerate(packed):
        h = n_lines * LH + PAD * 2
        if i % 2 == 0:
            d.rectangle([MARGIN, yy, CARD_W - MARGIN, yy + h], fill=STRIPE)
        for key, (label, x, w) in zip(KEYS, COLS):
            for k, ln in enumerate(cells[key]):
                d.text((x + PAD // 2, yy + PAD + k * LH), ln, font=f_cell,
                       fill=(RED if key == "role" else INK))
        d.line([MARGIN, yy + h, CARD_W - MARGIN, yy + h], fill=LINE, width=1)
        yy += h

    # 页脚：说明 + ★ 署名（CC BY-NC 的强制义务，卡片也必须带）
    d.text((MARGIN, y_foot), card.get("note", ""), font=fonts["foot"], fill=GREY)
    d.text((MARGIN, y_foot + 34),
           card.get("attribution") or ATTRIBUTION_SHORT,
           font=fonts["foot"], fill=GOLD)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path, img.size