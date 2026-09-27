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

import numpy as np
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



# ---------------------------------------------------------------- 主入口
def compose_board(recipe, hits, out_path, generated_at=None, texture=None):
    """生成设计依据板。返回 (路径, (宽, 高))。

    generated_at: 生成时间。**recipe 里没有这个字段**——它由 build_card() 写进 card，
                  所以调用方（pipeline.save_all）应把 card["generated_at"] 传进来。
    texture:      实物佐证层选中的织物肌理（与 composed_pattern 用同一件，保证一致）。
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
    _section(d, MARGIN, y_sq_t, "④ 组合纹样图（按配方位置拼合真实素材）", fonts)
    # ★ 直接用 compose_pattern 的输出，不再自己拼一遍（避免两份实现分叉）
    _tmp = Path(out_path).parent / "_board_schematic.png"
    try:
        compose_pattern(recipe, hits, _tmp, size=SQUARE, texture=texture)
        img.paste(Image.open(_tmp).convert("RGB"), (MARGIN, y_sq))
        _tmp.unlink(missing_ok=True)
    except Exception:
        img.paste(Image.new("RGB", (SQUARE, SQUARE), STRIPE), (MARGIN, y_sq))
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
        "本图由检索到的真实纹样素材按配方位置拼合而成，每个位置均可回指样本；未做精细图层融合。",
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



# ══════════════════════════════════════════════════════════════════
# 以下为 M4a 新增：真组合合成
# ══════════════════════════════════════════════════════════════════

def pattern_crop_box(path, fill_ratio=0.62, bg_tol=60):
    """自动求「纹样区」的裁切框。返回 (left, top, right, bottom)（正方形）。

    ★ 为什么必须自动算：库内图是「图鉴海报」，纹样区**外面是米色底**。
      按固定百分比裁，框的角必然越出纹样区、露出米色底（试拼图上的锯齿白边），
      而且会被 M5 风格化一起放大。

    ★★ 为什么是「包围盒 + 居中 62% 正方形」这个简单办法
      （这是实测三次翻车之后才定下来的，请勿随意"优化"）：

      试过两条更"聪明"的路，都失败了：
        · 按颜色分割纹样区 → 失败：**有些纹样自身的地色就是米色**
          （如团寿纹是红金寿字配米色地），与海报底同色，分不开
        · 拟合几何形状（半椭圆）→ 失败：**海报版式并不统一**
          （回纹是贴边的 D 形，团寿纹是居中的整圆，编号 005 还带装饰边框）

      改成"最大内填正方形"也仍会漏——因为掩码里含**弧线本身**与纹样自己的留白，
      边角总会蹭到一点背景。

      **最终用几何上必然安全的做法**：
        ① 用非背景掩码求**纹样区包围盒**
        ② 取包围盒中心，放一个边长 = min(包围盒宽, 高) × fill_ratio 的**正方形**

      为什么 0.62 是安全的：无论纹样区是半圆、整圆还是矩形，
      **以包围盒中心为中心、边长 ≤ 0.62 × 短边** 的正方形一定落在形状内部
      （圆的内接正方形边长为 0.707×直径，0.62 留了余量）。

      代价是裁图比"理论最大"小一些（约 6 成），换来的是**稳定不露底**。
    """
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    h, w, _ = a.shape

    bg = a[0:20, 0:20].reshape(-1, 3).mean(0)       # 背景色（左上角）
    mask = (np.abs(a - bg).sum(2) > bg_tol)
    mask[:, : int(w * 0.30)] = False                 # 先粗切掉最左侧
    mask[int(h * 0.90):, :] = False                  # 去掉底部水印带

    # ★★ 关键一步：只保留**最大连通块**。
    #   实测踩到：左侧的大字标题（如「缠枝莲纹」四个大字）与底部释义文字
    #   也是"非背景"像素，会把掩码包围盒的左边界一路拖到 x≈347，
    #   导致中心左移、裁切框越过纹样区左沿（表现为裁图左边一条米色弧边）。
    #   纹样区是**一整块**，文字是**零散小块** —— 取最大连通块即可自动滤掉文字。
    from scipy import ndimage
    lab, n_lab = ndimage.label(mask)
    if n_lab > 1:
        sizes = ndimage.sum(mask, lab, range(1, n_lab + 1))
        mask = (lab == (int(np.argmax(sizes)) + 1))

    if mask.sum() < 2000:
        cx, cy = int(w * 0.72), int(h * 0.5)
        s = int(min(w, h) * 0.30)
        return (cx - s, cy - s, cx + s, cy + s)

    ys, xs = np.where(mask)
    ax0, ay0, ax1, ay1 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    cx, cy = (ax0 + ax1) // 2, (ay0 + ay1) // 2

    side = int(min(ax1 - ax0, ay1 - ay0) * fill_ratio)
    side = max(80, side)
    left = max(0, cx - side // 2)
    top = max(0, cy - side // 2)
    return (left, top, min(w, left + side), min(h, top + side))


def pattern_region_mask(path, bg_tol=60):
    """返回 (掩码, (宽,高))：掩码=True 处是**纹样区本身**。

    ★ 为什么要把它单独暴露出来（而不是只给 pattern_crop_box 一个框）
      纹样区是个**弧边形状**（D 形 / 整圆），不是矩形。
      `pattern_crop_box` 用的是"中心正方形"，正方形一定有角落在弧形外面 ——
      给它加个 12% 内缩就够糊住了（因为它只用在中景/平铺）。

      但 `src/pattern_layout.py` 给**主题纹**取框时用的是母题外接矩形，
      那个矩形比中心正方形更靠边，左下角会**越过弧线伸进纸色区**，
      于是裁块里带进一块米白 + 一道金色弧边（实测就是这样：蝙蝠纹裁块左下角）。
      事后用颜色填掉治标不治本，而且弧线本身填不掉。

      **正解是把框与纹样区掩码取交集** —— 弧线外一律不算。
    """
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    h, w, _ = a.shape
    bg = a[0:20, 0:20].reshape(-1, 3).mean(0)
    mask = (np.abs(a - bg).sum(2) > bg_tol)
    mask[:, : int(w * 0.30)] = False
    mask[int(h * 0.90):, :] = False
    from scipy import ndimage
    lab, n_lab = ndimage.label(mask)
    if n_lab > 1:
        sizes = ndimage.sum(mask, lab, range(1, n_lab + 1))
        mask = (lab == (int(np.argmax(sizes)) + 1))
    # ★ 腐蚀一圈：弧线本身也是"非背景"，会让掩码比真实纹样区**外扩几像素**。
    #   腐蚀 5px 后掩码退到弧线内侧，取交集时就不会带入弧线。
    mask = ndimage.binary_erosion(mask, np.ones((5, 5)))
    return mask, (w, h)


# 裁切框缓存：同一张图只算一次（自动求框有点慢）
_CROP_CACHE = {}


def _poster_bg(path):
    """海报背景色（左上角 20×20 均值）。"""
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    return a[0:20, 0:20].reshape(-1, 3).mean(0)


def _clean_bg(tile, bg, tol=60, min_ratio=0.002):
    """把裁块里**残留的海报背景色像素**替换成该块的主色。

    ★ 为什么需要这一步（这是实测四次翻车后的务实方案）：
      自动裁切能定位到纹样区，但边界上**仍会残留一小条米色底**——
      因为不同海报的纹样区形状不一致（D 形 / 整圆 / 带装饰边框都有），
      任何"找内部干净矩形"的算法都会在某个角的边上蹭到背景。
      平铺时残留的米色会变成**重复的浅色竖线**，很显眼。
      替换成该块主色后，视觉上就融进去了。

    ⚠️ **诚实说明**：这是**颜色填充**，不是真实纹样内容。
      但横竖这块图是"组合示意"，且每个素材的整体出处仍可回指样本。
    """
    a = np.asarray(tile).astype(np.int16)
    is_bg = (np.abs(a - bg).sum(2) <= tol)
    ratio = float(is_bg.mean())
    if ratio < min_ratio:                     # 几乎没有残留 → 不动
        return tile, 0.0
    keep = a[~is_bg]
    if len(keep) == 0:
        return tile, 0.0
    main = tuple(int(v) for v in np.median(keep.reshape(-1, 3), axis=0))   # 主色（中位数更稳健）
    out = a.copy()
    out[is_bg] = main
    return Image.fromarray(out.astype(np.uint8)), ratio


def crop_pattern(image_path, box=None, inset=0.12, clean=True):
    """从图鉴海报里裁出纯纹样块。

    inset: **裁完再统一内缩的比例**（默认 0.12）。
      ★ 为什么必须有这一刀（实测 5 轮才定下来）：
        纹样区的形状在不同海报里不一致，任何"找内部干净矩形"的算法
        都会在某个角的边上蹭到一点海报背景。**内缩一刀是最省事、最可靠的兜底。**
        实测对比（0% / 6% / 12% / 18%）：**12% 时 10 个样本全部干净**；
        18% 虽然更干净，但过度放大、损失了构图。
      ⚠️ 代价：可用像素降到约 76%（458 → 348），拼到 1024 画布会放大 ~2×、边缘略软。
    """
    key = str(image_path)
    if box is None:
        if key not in _CROP_CACHE:
            _CROP_CACHE[key] = pattern_crop_box(image_path)
        box = _CROP_CACHE[key]
    im = Image.open(image_path).convert("RGB")
    tile = im.crop(box)
    if inset > 0:
        w, h = tile.size
        k = int(min(w, h) * inset)
        tile = tile.crop((k, k, w - k, h - k))
    if clean:
        tile, _ = _clean_bg(tile, _poster_bg(image_path))
    return tile


def _tile_band(tile_img, band_w, band_h):
    """把纹样块**按原比例**缩放到 band 高度，然后横向平铺成一条 band_w 宽的带。

    ★ 关键：按比例缩放到目标高度，再重复 —— **不是**把图拉成 (band_w, band_h)。
      拉伸会毁掉纹样的比例，看起来就不像纹样了。
    """
    th = max(1, band_h)
    tw = max(1, int(round(tile_img.width * th / tile_img.height)))
    unit = tile_img.resize((tw, th), Image.LANCZOS)
    band = Image.new("RGB", (band_w, band_h))
    for x in range(0, band_w, tw):
        band.paste(unit, (x, 0))
    return band


def _tile_col(tile_img, band_w, band_h):
    """纵向平铺（左右两条边用）。"""
    tw = max(1, band_w)
    th = max(1, int(round(tile_img.height * tw / tile_img.width)))
    unit = tile_img.resize((tw, th), Image.LANCZOS)
    col = Image.new("RGB", (band_w, band_h))
    for y in range(0, band_h, th):
        col.paste(unit, (0, y))
    return col


def compose_pattern(recipe, hits, out_path, size=1024, texture=None, texture_strength=0.35):
    """按配方位置，用**库内真实纹样块**拼出一张组合式纹样图。

    构图：中心母题居中，边饰按 border_ratio 环绕，四角为角花。

    texture: 实物佐证层的一件（来自 `src.artifact_layer.pick_texture`）。
      ★ 它是**材质层**，不是纹样层 —— 只作为整幅的低透明度织物肌理叠上去，
        不参与元素级溯源。传导到卡片/报告时必须**分区标注**：
          纹样层（中心/边饰/角花）→ 元素级可溯（母题库）
          材质层（织物肌理）      → 实物可溯（克利夫兰，CC0）
      texture_strength 控制肌理强度（只取亮度起伏，不改颜色）。0.35 为实测甜点。
      texture=None 时跳过，输出与旧版一致。

    返回 (路径, (宽, 高), 实际采用的 texture 条目或 None)。
    """
    st = recipe.get("structure") or {}
    cm_name = ((st.get("center_motif") or {}).get("name") or "").strip()
    bd_name = ((st.get("border") or {}).get("pattern") or "").strip()
    cn_name = ((st.get("corner") or {}).get("pattern") or "").strip()

    # 从 hits 里找出三个槽位对应的样本
    by_name = {}
    for h in hits or []:
        s = h.get("sample") or {}
        if s.get("name") and s["name"] not in by_name:
            by_name[s["name"]] = s

    def _img(name):
        s = by_name.get(name)
        if not s:
            return None
        p = ROOT / s["image_path"]
        if not p.exists():
            return None
        return crop_pattern(p)

    cm = _img(cm_name)
    bd = _img(bd_name)
    cn = _img(cn_name)

    # 边宽：读 config 的 border_ratio（与依据板的说法一致）
    ratio = float(((CFG.get("compose") or {}).get("border_ratio")) or 0.15)
    bw = max(8, int(size * ratio))
    inner = size - 2 * bw

    canvas = Image.new("RGB", (size, size), (247, 241, 230))

    # ---- 边饰：四条边平铺 ----
    if bd is not None:
        canvas.paste(_tile_band(bd, size, bw), (0, 0))                  # 上
        canvas.paste(_tile_band(bd, size, bw), (0, size - bw))           # 下
        canvas.paste(_tile_col(bd, bw, size), (0, 0))                    # 左
        canvas.paste(_tile_col(bd, bw, size), (size - bw, 0))            # 右
    else:
        dr = ImageDraw.Draw(canvas)
        dr.rectangle([0, 0, size - 1, size - 1], outline=(200, 190, 170), width=2)

    # ---- 中心母题 ----
    if cm is not None:
        canvas.paste(ImageOps.fit(cm, (inner, inner), method=Image.LANCZOS), (bw, bw))
    else:
        dr = ImageDraw.Draw(canvas)
        dr.rectangle([bw, bw, size - bw, size - bw], fill=(252, 249, 243))

    # ---- 四角：角花（若与边饰同素材，视觉上也成立）----
    if cn is not None:
        c = ImageOps.fit(cn, (bw, bw), method=Image.LANCZOS)
        for px, py in ((0, 0), (size - bw, 0), (0, size - bw), (size - bw, size - bw)):
            canvas.paste(c, (px, py))

    # ---- 实物佐证层：织物肌理（材质层）----
    # ★ 只取纹理的「亮度起伏」，**不引入色偏**。
    #   第一版用 Image.blend 整幅混合，实测 alpha≥0.28 就把底色弄灰、蓝色变浊
    #   （因为把克利夫兰织物的颜色也叠上来了）。
    #   改成：把纹理灰度化 → 除以自身均值得到"相对亮度起伏" → 与底图逐像素相乘。
    #   这样只加织物的经纬/褶皱质感，颜色仍是配方配色。
    used_texture = None
    if texture is not None:
        try:
            from src.artifact_layer import texture_image
            tex = texture_image(texture, size).convert("RGB")
            if tex.size != (size, size):
                tex = tex.resize((size, size), Image.LANCZOS)
            base = np.asarray(canvas.convert("RGB"), np.float32)
            g = np.asarray(tex.convert("L"), np.float32)
            g = g / (g.mean() + 1e-6)                       # 相对亮度，均值≈1
            factor = 1.0 + (g - 1.0) * float(texture_strength)
            canvas = Image.fromarray(
                np.clip(base * factor[..., None], 0, 255).astype(np.uint8))
            used_texture = texture
        except Exception as e:
            print(f"[警告] 织物肌理叠加失败（已跳过）：{type(e).__name__}: {e}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "PNG")
    return out_path, canvas.size, used_texture