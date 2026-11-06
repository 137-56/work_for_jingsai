# src/ai_texture.py
"""方案 1 · AI 图作 3D 贴图源（批次 1 核心，默认档）。

★★ 只换**图像素**，不换 atlas 几何与 UV 公式
    3D 三铁律在本模块里的落点：
      ① 布局几何匹配载体几何 —— fan 是圆形平面载体，故走**同心圆**布局；
         方盒是「四个独立面 + 顶盖」，故走 **atlas（左半 strip + 右上 lid）**；
         梅瓶是旋转体，故走 **strip（横向环一圈）**。
      ② 展开图宽高比严格按 `pattern_layout.STRIP_ASPECT`：
         1024² 方图先**等比裁切**到该比例，再 LANCZOS 重采样到
         `(round(height * ar), height)`。绝不整幅贴满（旧做法会错位 / 拉伸）。
      ③ `glb_export.vertex_uv()` 与 `preview3d` 光线求交的 UV 公式继续一致 ——
         本模块产出的图**尺寸与既有分区贴附完全相同**，所以 UV 一处都不用改。

★ 未登记形态**明确抛 KeyError**
    取 `STRIP_ASPECT[kind]` 一律用下标，禁 `.get(kind, 默认值)` 静默兜底。
    静默兜底会让新形态悄悄用上梅瓶的比例，页面不报错但纹样被拉伸。

★ 溯源口径
    AI 图恒 `traceable=False`；界面常驻「AI 生成 · 不可溯源」标注。
    AI 产物只落 `outputs/ai/<run>/`，不写定稿 run、不进提交包主线。

用法：
    from src.ai_texture import select_source, fit_to_strip, fit_box_atlas
    src = select_source("ai_texture", style_img, None, recipe)
    im = fit_to_strip(src.path, "vase", height=1024)
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Union

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ImageInput = Union[str, Path, Image.Image]


class MissingAITexture(FileNotFoundError):
    """AI 档未找到可用 AI 图时抛出；调用方须**显式提示并降级**，不得静默。"""


@dataclass(frozen=True)
class TextureSource:
    """本次 3D 预览采用的图源（不可变，可直接存 session_state）。

    Attributes:
        path: 图源文件路径；traceable 档可能为空串（分区贴附不直接读整图）。
        size: 图源 (宽, 高)；路径不可读时为 (0, 0)。
        sha256: 图源字节的 sha256；路径不可读时为空串。
        origin: 图源登记信息。AI 档优先取 M5 输出侧登记的 texture_origin。
        traceable: 是否可溯源。AI 两档恒为 False。
    """

    path: str
    size: tuple[int, int]
    sha256: str
    origin: str
    traceable: bool


# ---------------------------------------------------------------- 图源选择

def _route_value(route: Any) -> str:
    """接受路线字符串或 RouteState，统一取回 route 值。"""
    from src.ai_routes import RouteState

    if isinstance(route, RouteState):
        return route.route
    return str(route)


def _sha256_of(path: Path) -> str:
    """逐字节读文件算 sha256（不缓存，图源可能刚落盘）。"""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _m5_origin(style_img: Path, recipe: dict | None) -> str:
    """取 M5 输出侧登记的图源信息，供 `TextureSource.origin` 使用。

    `src/m5_stylize.py` 会在 `stylize.json` 的每条结果里写 `texture_origin`；
    这里按文件名匹配取出。读不到就按**文件类别**如实标注，不编造来源。
    """
    reg = (recipe or {}).get("texture_origin")
    if isinstance(reg, str) and reg.strip():
        return reg.strip()
    meta = style_img.parent / "stylize.json"
    if meta.is_file():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        for item in (data.get("results") or []):
            if not isinstance(item, dict):
                continue
            if Path(str(item.get("file") or "")).name == style_img.name:
                origin = item.get("texture_origin")
                if isinstance(origin, str) and origin.strip():
                    return origin.strip()
    return "m5_stylize/stylized_*.png（AI 风格化输出，不可溯源）"


def _composed_source(recipe: dict | None) -> TextureSource:
    """traceable 档：图源是既有「分区贴附」链路（composed_pattern.png 语义层）。

    该链路不直接读整张合成图，而是由 `pattern_layout` 按配方槽位分别取母题，
    所以这里只是把「图源身份」登记清楚；路径可读时顺便记下字节与哈希。
    """
    origin = "pattern_layout/分区贴附（composed_pattern 语义层 · 元素级可溯源）"
    recipe = recipe or {}
    rid = str(recipe.get("recipe_id") or "").strip()
    candidate = ROOT / "outputs" / rid / "composed_pattern.png" if rid else None
    if candidate is not None and candidate.is_file():
        with Image.open(candidate) as im:
            size = tuple(im.size)
        return TextureSource(path=str(candidate), size=(int(size[0]), int(size[1])),
                             sha256=_sha256_of(candidate), origin=origin,
                             traceable=True)
    return TextureSource(path="", size=(0, 0), sha256="", origin=origin,
                         traceable=True)


def select_source(route: Any, style_img: ImageInput | None,
                  ai_png: ImageInput | None, recipe: dict | None) -> TextureSource:
    """按路线选择 3D 贴图图源。

    Args:
        route: 路线字符串或 `RouteState`。
        style_img: M5 风格化图路径（可选）。
        ai_png: 另外指定的 AI 图路径（可选，优先级高于 style_img）。
        recipe: 配方 dict，用于定位 composed_pattern 与读取图源登记。

    Returns:
        TextureSource。AI 两档恒 `traceable=False`；traceable 档恒 True。

    Raises:
        RouteValidationError: route 未登记。
        MissingAITexture: AI 档下没有任何可用 AI 图（调用方须显式提示并降级）。
    """
    from src.ai_routes import AI_ROUTES, ROUTES, ROUTE_TRACEABLE

    r = _route_value(route)
    if r not in ROUTES:
        from src.ai_routes import RouteValidationError
        raise RouteValidationError(f"select_source 收到未登记路线：{r!r}")
    if r == ROUTE_TRACEABLE:
        return _composed_source(recipe)

    for cand in (ai_png, style_img):
        if cand is None:
            continue
        if isinstance(cand, Image.Image):
            # 内存图：无磁盘路径，按「外部 AI 图」如实登记。
            return TextureSource(
                path="", size=(int(cand.width), int(cand.height)), sha256="",
                origin="ai_texture/内存图（AI 生成 · 不可溯源）",
                traceable=False)
        p = Path(cand)
        if not p.is_file():
            continue
        with Image.open(p) as im:
            size = (int(im.width), int(im.height))
        origin = (_m5_origin(p, recipe)
                  if p.name.startswith("stylized_")
                  else "ai_texture/外部 AI 图（AI 生成 · 不可溯源）")
        return TextureSource(path=str(p), size=size, sha256=_sha256_of(p),
                             origin=origin, traceable=False)

    raise MissingAITexture(
        "AI 路线未找到可用 AI 图（stylized_*.png 或外部 ai_png）。"
        "调用方须给出明确提示并降级到可溯源分区贴附，不得静默继续。")


# ---------------------------------------------------------------- 展开图适配

def _load_rgb(src: ImageInput) -> Image.Image:
    """把路径 / Image 统一成 RGB 图像。"""
    if isinstance(src, Image.Image):
        return src.convert("RGB")
    p = Path(src)
    if not p.is_file():
        raise MissingAITexture(f"AI 图不存在：{p}")
    with Image.open(p) as im:
        return im.convert("RGB")


def _crop_to_aspect(img: Image.Image, ar: float) -> Image.Image:
    """按目标宽高比做**中心等比裁切**（cover），不做任何拉伸。"""
    iw, ih = img.size
    if iw <= 0 or ih <= 0:
        raise ValueError("AI 图尺寸非法（宽或高为 0）")
    if iw / ih > ar:
        nw, nh = max(1, int(round(ih * ar))), ih
    else:
        nw, nh = iw, max(1, int(round(iw / ar)))
    nw, nh = min(nw, iw), min(nh, ih)
    left, top = (iw - nw) // 2, (ih - nh) // 2
    return img.crop((left, top, left + nw, top + nh))


def fit_to_strip(src: ImageInput, kind: str, height: int = 1024) -> Image.Image:
    """把 1024² 方图适配成某形态的 3D 贴图（**只换像素，不换几何**）。

    步骤：
      ① 从 `STRIP_ASPECT[kind]` 取该形态的展开图宽高比（未登记 → KeyError）；
      ② 按该比例对源图做中心等比裁切；
      ③ LANCZOS 重采样到 `(round(height * ar), height)`；
      ④ fan 额外按**同心圆**布局重排（圆形平面载体，UV 是 (x,y) 平面映射）。

    Args:
        src: AI 图路径或 PIL.Image。
        kind: 形态键，必须登记在 STRIP_ASPECT。
        height: 贴图高度，默认 1024。

    Returns:
        RGB 图像，宽严格等于 `round(height * STRIP_ASPECT[kind])`。

    Raises:
        KeyError: kind 未登记（**禁止静默兜底**）。
        MissingAITexture: 图源路径不存在。
    """
    from src.pattern_layout import STRIP_ASPECT, strip_size

    if int(height) <= 0:
        raise ValueError("height 必须为正整数")
    if kind not in STRIP_ASPECT:
        # 明确抛 KeyError：未登记形态绝不静默套用别的形态比例。
        raise KeyError(
            f"形态 {kind!r} 未登记在 STRIP_ASPECT；已登记：{sorted(STRIP_ASPECT)}")
    width, h = strip_size(kind, int(height))      # 同一真源，比例与尺寸绝不漂移

    img = _load_rgb(src)
    cropped = _crop_to_aspect(img, width / h)
    fitted = cropped.resize((width, h), Image.LANCZOS)
    if kind == "fan":
        return _concentric_face(fitted, h)
    return fitted


def _concentric_face(square: Image.Image, size: int) -> Image.Image:
    """圆形平面载体的**同心圆**布局：外圈环带 + 中心主题圆 + 一道同心弦纹。

    ★ 为什么不能把方图直接铺满：扇面的 UV 是 (x,y) 平面映射、只采样圆内，
      方图的四条直边带会被弧边切成四段、四角露出方框（历史实测结论）。
      这里所有内容都按同心圆构造，圆外填地色（反正 UV 不采样圆外）。

    ★ 几何约定与 `pattern_layout.build_fan_face` 一致：
      外圈环带 r∈[(1-ring_ratio)·R, R]、中心主题圆 r = core_ratio·R/2。
      本函数不改动 `build_fan_face` 的任何定义，只是为 AI 图源提供等价布局。
    """
    from src.pattern_layout import current_ground

    ring_ratio, core_ratio = 0.30, 0.56
    ground_rgb = current_ground()[1]
    s = int(size)
    base = Image.new("RGB", (s, s), tuple(ground_rgb))
    cx = cy = (s - 1) / 2.0
    r_out = s / 2.0
    r_in = r_out * (1.0 - ring_ratio)
    r_core = s * core_ratio / 2.0

    # ① 外圈环带：整幅 AI 图铺满后用「环形 mask」裁切，环外 alpha=0。
    ring = Image.new("L", (s, s), 0)
    dr = ImageDraw.Draw(ring)
    dr.ellipse([0, 0, s - 1, s - 1], fill=255)
    dr.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], fill=0)
    ring = ring.filter(ImageFilter.GaussianBlur(max(1.0, s / 380)))
    base.paste(square.resize((s, s), Image.LANCZOS), (0, 0), ring)

    # ② 中心主题圆：AI 图圆形放置（外溢部分被 ① 的环带盖住）。
    d = max(2, int(2 * r_core))
    core = square.resize((d, d), Image.LANCZOS)
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, d - 1, d - 1], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(max(1.0, s / 380)))
    base.paste(core, (int(cx - r_core), int(cy - r_core)), mask)

    # ③ 同心弦纹：只留一道（边饰带内缘往里一点），避免主题圆外缘白晕。
    r_rule = r_in * 0.955
    ImageDraw.Draw(base).ellipse(
        [cx - r_rule, cy - r_rule, cx + r_rule, cy + r_rule],
        outline=(226, 215, 196), width=max(2, s // 200))
    return base


def fit_box_atlas(src: ImageInput, height: int = 1024) -> tuple[Image.Image,
                                                                 tuple[float, float]]:
    """方盒 atlas：**左半 strip + 右上 lid**，几何与既有分区贴附逐像素一致。

    返回 (atlas, lid_frac)。`lid_frac` 是盖图在 atlas 里的归一化子矩形
    `(du, dv)`，与 `preview3d._box_hit` / `glb_export.vertex_uv` 的 UV 同源：
      · 侧面采样 u∈[0, 0.5]（左半 strip）
      · 顶底盖采样 u∈[0.5, 0.5+du]、v∈[0, dv]（右上盖图）

    ★ 绝不能把 AI 图整幅贴成 atlas —— 那样盖图会采到 strip 的像素，
      且宽高比与「一个面」的 1.15 不符。
    """
    from src.pattern_layout import ground_tile, strip_size

    sw, sh = strip_size("box", int(height))
    strip = fit_to_strip(src, "box", height=int(height))
    atlas = ground_tile(2 * sw, sh)
    atlas.paste(strip, (0, 0))
    lh = sh // 2
    lw = lh                                   # 盖图是正方形，等比缩到半高
    lid = fit_to_strip(src, "fan", height=lh)  # 方形盖图（同心圆布局，UV 同源）
    atlas.paste(lid.resize((lw, lh), Image.LANCZOS), (sw, 0))
    return atlas, (lw / (2 * sw), lh / sh)
