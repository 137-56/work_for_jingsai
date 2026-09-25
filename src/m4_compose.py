# src/m4_compose.py
"""M4 设计依据板：把「检索到的真实素材 + 配方」拼成一张可视化板。

★ 形态说明（已裁定）：**不是**精细图层合成，而是"设计依据板"——
    素材缩略图（各带出处标签）+ 配方内容 + 底部**组合示意**。
    理由：本作品的卖点是"可信"而不是"好看"。精细图层合成需要素材间的
    对齐与遮罩处理，投入大、质量难保，**却不能增加"可信"**。
    而"依据板 + 组合示意"已经能说清三件事：
      · 每个素材来自哪里（可溯源）
      · 配方如何决定构图（可解释）
      · 组合式合成是怎么拼的（非端到端黑箱）

★ 复用 M6 的字体与换行工具：
    `_font` / `wrap_cjk` 在 B4 已经踩过坑（中文字体必须显式 truetype、
    中文换行不能用 textwrap），这里直接复用，**同一个坑不踩第二遍**。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.m6_provenance import ATTRIBUTION_SHORT, _font, wrap_cjk
from src.utils import CFG

# ---------------------------------------------------------------- 版面常量
BOARD_W = 1680
MARGIN = 50
GAP = 18
COLS = 5
THUMB = 286                 # 缩略图边长
SQUARE = 620                # 组合示意画布边长
LABEL_H = 74                # 每个缩略图下方的文字区高度
SEC_TITLE_H = 46

INK = (43, 35, 24)          # 墨
RED = (200, 16, 46)         # 正红
GOLD = (212, 175, 55)       # 浅金
PAPER = (247, 241, 230)     # 米白
GREY = (122, 114, 100)
LINE = (222, 212, 192)
BAND = (238, 230, 214)
STRIPE = (252, 249, 243)

ROLE_CN = {"center_motif": "中心母题", "border": "边饰",
           "corner": "角花", "reference": "相关参考"}


# ---------------------------------------------------------------- 小工具
def _open(path):
    p = Path(path)
    return Image.open(p).convert("RGB") if p.exists() else None


def _fit(img, w, h):
    """按比例缩放 + 居中裁剪到正好 w×h（不留白、不变形）。"""
    return ImageOps.fit(img, (w, h), method=Image.LANCZOS)


def _role_of(sample, cm, bd, cn):
    """判断这个素材在配方里担什么角色。"""
    name = sample.get("name")
    if name and name == (cm or {}).get("name"):
        return "center_motif"
    if name and name == (bd or {}).get("pattern"):
        return "border"
    if name and name == (cn or {}).get("pattern"):
        return "corner"
    return "reference"


def _kv_block(d, x, y, pairs, fonts, lh=36, label_w=118):
    """画一组「标签：值」，返回结束 y。"""
    for k, v in pairs:
        d.text((x, y), k, font=fonts["h2"], fill=RED)
        for i, ln in enumerate(wrap_cjk(v or "—", fonts["cell"], 470, d)):
            d.text((x + label_w, y + (i * lh) - 2), ln, font=fonts["cell"], fill=INK)
        y += lh
    return y


def _section(d, x, y, title, fonts):
    d.text((x, y), title, font=fonts["title"], fill=INK)
    d.line([x, y + SEC_TITLE_H - 6, BOARD_W - MARGIN, y + SEC_TITLE_H - 6], fill=GOLD, width=2)
    return y + SEC_TITLE_H + 6


def _compose_schematic(bd_items, cn_items, cm_items):
    """按配方位置拼一张**组合示意图**：中心 = 中心母题，周边 = 边饰环绕，四角 = 角花。

    ★ 这是"组合式合成"的最简形态 —— 不做对齐与遮罩，只按位置贴。
    在图上会明确标注"示意图，非成品"，避免误导。
    """
    r_ratio = float(((CFG.get("compose") or {}).get("border_ratio")) or 0.15)
    bw = max(40, int(SQUARE * r_ratio))          # 边框宽度
    inner = SQUARE - 2 * bw

    canvas = Image.new("RGB", (SQUARE, SQUARE), PAPER)

    # 边框：四条边各贴一次（用边饰图，按长度方向拉伸）
    if bd_items:
        b = bd_items[0]
        canvas.paste(_fit(b, SQUARE, bw), (0, 0))
        canvas.paste(_fit(b, SQUARE, bw), (0, SQUARE - bw))
        canvas.paste(_fit(b, bw, SQUARE), (0, 0))
        canvas.paste(_fit(b, bw, SQUARE), (SQUARE - bw, 0))
    else:
        d0 = ImageDraw.Draw(canvas)
        d0.rectangle([0, 0, SQUARE - 1, SQUARE - 1], outline=LINE, width=2)

    # 中心：中心母题
    if cm_items:
        canvas.paste(_fit(cm_items[0], inner, inner), (bw, bw))
    else:
        d0 = ImageDraw.Draw(canvas)
        d0.rectangle([bw, bw, SQUARE - bw, SQUARE - bw], fill=STRIPE, outline=LINE, width=1)

    # 四角：角花
    if cn_items:
        c = _fit(cn_items[0], bw, bw)
        for px, py in [(0, 0), (SQUARE - bw, 0), (0, SQUARE - bw), (SQUARE - bw, SQUARE - bw)]:
            canvas.paste(c, (px, py))

    return canvas, bw


# ---------------------------------------------------------------- 主入口
def compose_board(recipe, hits, out_path, generated_at=None):
    """生成设计依据板。返回 (路径, (宽, 高))。

    generated_at: 生成时间。**recipe 里没有这个字段**——它由 build_card() 写进 card，
                  所以调用方（pipeline.save_all）应把 card["generated_at"] 传进来。
    """
    st = recipe.get("structure") or {}
    cm = st.get("center_motif") or {}
    bd = st.get("border") or {}
    cn = st.get("corner") or {}
    it = recipe.get("intent") or {}
    pal = recipe.get("palette") or {}

    fonts = {"h1": _font(46), "title": _font(30), "h2": _font(24),
             "cell": _font(21), "meta": _font(20), "small": _font(18)}

    # ---- 素材：图片 + 角色 ----
    items = []
    for h in hits or []:
        s = h.get("sample") or {}
        items.append((s, _open(ROOT / s.get("image_path", "")), _role_of(s, cm, bd, cn)))

    cm_items = [im for _, im, r in items if r == "center_motif" and im]
    bd_items = [im for _, im, r in items if r == "border" and im]
    cn_items = [im for _, im, r in items if r == "corner" and im]

    # ---- 量高度 ----
    n = len(items)
    rows = (n + COLS - 1) // COLS if n else 0
    grid_h = rows * (THUMB + LABEL_H) + max(0, rows - 1) * GAP

    y_head = MARGIN
    y_recipe = y_head + 132
    RECIPE_H = 296
    y_grid_t = y_recipe + RECIPE_H + 34
    y_grid = y_grid_t + SEC_TITLE_H + 6
    y_sq_t = y_grid + grid_h + 34
    y_sq = y_sq_t + SEC_TITLE_H + 6
    y_foot = y_sq + SQUARE + 34
    total_h = y_foot + 46 + 34 + MARGIN

    img = Image.new("RGB", (BOARD_W, total_h), PAPER)
    d = ImageDraw.Draw(img)

    # ---- 页眉 ----
    d.rectangle([0, 0, BOARD_W, 8], fill=RED)
    d.text((MARGIN, y_head), "设计依据板", font=fonts["h1"], fill=INK)
    w1 = d.textlength("设计依据板", font=fonts["h1"])
    d.text((MARGIN + w1 + 22, y_head + 18), recipe.get("recipe_id", ""),
           font=fonts["h2"], fill=RED)
    d.text((MARGIN, y_head + 62), f"生成时间：{generated_at or recipe.get('generated_at') or '—'}",
           font=fonts["meta"], fill=GREY)
    d.text((MARGIN, y_head + 92), f"用户需求：{recipe.get('user_request', '')}",
           font=fonts["meta"], fill=GREY)

    # ---- 配方区 ----
    d.rectangle([MARGIN, y_recipe, BOARD_W - MARGIN, y_recipe + RECIPE_H], fill=STRIPE,
                outline=LINE, width=1)
    x1 = MARGIN + 26
    x2 = MARGIN + 800
    yy = y_recipe + 26
    d.text((x1, yy), "① 配方内容", font=fonts["h2"], fill=RED)
    d.text((x2, yy), "② 配色", font=fonts["h2"], fill=RED)
    yy += 42
    _kv_block(d, x1, yy, [
        ("场合", " / ".join(it.get("occasion") or [])),
        ("用途", it.get("purpose")),
        ("寓意", " / ".join(it.get("blessing") or [])),
        ("风格", it.get("style")),
    ], fonts)

    # 右半：结构
    _kv_block(d, x2, yy, [
        ("中心母题", cm.get("name")),
        ("构成元素", " / ".join(cm.get("elements") or [])),
        ("边饰", bd.get("pattern")),
        ("角花", cn.get("pattern")),
        ("对称", st.get("symmetry")),
    ], fonts, label_w=140)

    # 配色色块
    by = y_recipe + RECIPE_H - 74
    bx = x2
    for key, lab in (("primary", "主色"), ("secondary", "辅色")):
        hexv = str(pal.get(key) or "").strip()
        if hexv.startswith("#") and len(hexv) in (4, 7):
            try:
                rgb = tuple(int(hexv[i:i + 2], 16) for i in (1, 3, 5))
            except ValueError:
                rgb = (255, 255, 255)
            d.rectangle([bx, by, bx + 46, by + 34], fill=rgb, outline=LINE)
            d.text((bx + 56, by + 4), f"{lab} {hexv}", font=fonts["cell"], fill=INK)
        else:
            d.text((bx, by + 4), f"{lab} —", font=fonts["cell"], fill=GREY)
        bx += 250
    d.text((x1, by + 4), f"配色依据：{pal.get('scheme_basis') or '—'}",
           font=fonts["cell"], fill=INK)

    # ---- 素材区 ----
    _section(d, MARGIN, y_grid_t, f"③ 检索到的真实素材（{n} 个，按配方槽位与相似度排序）", fonts)
    if not items:
        d.text((MARGIN, y_grid + 10), "（本次未检索到素材）", font=fonts["cell"], fill=GREY)

    for i, (s, im, role) in enumerate(items):
        r, c = divmod(i, COLS)
        x = MARGIN + c * (THUMB + GAP)
        y = y_grid + r * (THUMB + LABEL_H + GAP)
        if im:
            img.paste(_fit(im, THUMB, THUMB), (x, y))
        else:
            d.rectangle([x, y, x + THUMB, y + THUMB], fill=BAND, outline=LINE)
        d.rectangle([x, y, x + THUMB, y + THUMB], outline=LINE, width=1)
        d.text((x, y + THUMB + 8), s.get("name", ""), font=fonts["cell"],
               fill=RED if role != "reference" else INK)
        d.text((x, y + THUMB + 34), f"{ROLE_CN.get(role, '')}｜{s.get('id', '')}",
               font=fonts["small"], fill=GREY)

    # ---- 组合示意 ----
    _section(d, MARGIN, y_sq_t, "④ 组合示意图（按配方位置拼合）", fonts)
    sch, bw = _compose_schematic(bd_items, cn_items, cm_items)
    img.paste(sch, (MARGIN, y_sq))
    d.rectangle([MARGIN, y_sq, MARGIN + SQUARE, y_sq + SQUARE], outline=LINE, width=1)

    tx = MARGIN + SQUARE + 40
    ty = y_sq + 6
    d.text((tx, ty), "构图说明", font=fonts["h2"], fill=RED)
    ty += 42
    notes = [
        f"· 中央为「中心母题」（{cm.get('name') or '—'}）",
        f"· 四周为「边饰」环绕，占边长比例 {(CFG.get('compose') or {}).get('border_ratio', 0.15)}",
        f"· 四角为「角花」（{cn.get('pattern') or '未指定'}）",
        f"· 对称方式：{st.get('symmetry') or '—'}",
        "",
        "⚠️ 本图为组合示意图，用于说明配方各位置如何对应真实素材；",
        "   未做图层级对齐与遮罩处理，不是成品图。",
    ]
    for ln in notes:
        for sub in wrap_cjk(ln, fonts["cell"], BOARD_W - MARGIN - tx, d):
            d.text((tx, ty), sub, font=fonts["cell"],
                   fill=GREY if ln.startswith("⚠️") or ln.startswith("   ") else INK)
            ty += 32

    # ---- 页脚 ----
    d.line([MARGIN, y_foot, BOARD_W - MARGIN, y_foot], fill=LINE, width=1)
    d.text((MARGIN, y_foot + 12),
           "每个素材均来自样本库中的真实条目，出处见编号；素材授权与署名见下。",
           font=fonts["small"], fill=GREY)
    d.text((MARGIN, y_foot + 42), ATTRIBUTION_SHORT, font=fonts["small"], fill=GOLD)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return out_path, img.size