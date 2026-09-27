# src/style_ground.py
"""把 M5 的 **AI 风格化图** 转成 3D 贴图可用的"地子"（底纹/底色）。

════════════════════════════════════════════════════════════════════
为什么需要这个模块
════════════════════════════════════════════════════════════════════
3D 的分区贴图（`pattern_layout`）原来统一用一块**纯色**当地子
（`NEUTRAL = (247, 241, 230)`）。效果上："纹样是对的，但整体很素" ——
白底占比太大（方盒四周、团扇扇面、梅瓶肩颈），像贴纸而不像器物。

AI 风格化图（M5 输出）里其实**已经有**合适的色彩氛围与釉面质感，
但它是一张**整幅构图**，直接拿去平铺会花掉（它自己上面也有纹样）。

∴ 本模块只做一件事：**从 AI 图里抽取"氛围"，丢掉"内容"**，
产出一张低对比、带细腻肌理的地子图，交给 `pattern_layout` 当地色用。

════════════════════════════════════════════════════════════════════
★ 溯源口径（重要，不要绕过）
════════════════════════════════════════════════════════════════════
本模块产出的只是**贴图的底层色/肌理**，它上面**不承载任何语义**：
  · 语义纹样（中心主题 / 边饰 / 角花）依然来自语义层母题库 —— 元素级可溯。
  · 地子来自 AI 风格化图 —— 属于**渲染层**，不参与元素级溯源。
∴ 启用本模块时，界面/卡片必须补一句"贴面经风格化渲染"。
   不可把两种情况都说成"100% 原始可溯"。

★ 判据（口径一致性）：`meta["ground_from"]` 会标明地子来源，
  供上层写溯源声明时区分处理。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageEnhance

ROOT = Path(__file__).resolve().parent.parent

# 默认地子（= pattern_layout.NEUTRAL），作为风格化失败时的兜底
FALLBACK = (247, 241, 230)


_W = np.array([0.299, 0.587, 0.114], np.float32)


def _auto_level_lum(a: np.ndarray, lo_q: float = 2.0, hi_q: float = 98.0):
    """把亮度线性拉到 [0,1]，避免 AI 图的极端明暗直接进贴图。

    ★ 入参必须是 **0~255 量纲**，返回也是 0~255 量纲（保持量纲不变是本函数
      的契约）。曾经这里返回 0~1 量纲、调用方又按 255 量纲继续运算，
      结果地子整张变成近乎纯黑（mean≈2.4）—— 量纲必须显式约定。
    """
    lum = a @ _W
    lo, hi = np.percentile(lum, [lo_q, hi_q])
    if hi - lo < 1e-6:
        return a
    # 拉到 [0,1] 后乘回 255，量纲守恒
    return (a - lo) * (255.0 / (hi - lo))


def make_ground(style_img, size=1024, tone=0.86, sat=0.22, blur=0.030,
                grain=5.0, seed=20260927):
    """从 AI 风格化图抽一层"低饱和、低对比、带细腻肌理"的地子。

    参数
    ----
    style_img : str | Path | Image.Image
        M5 的风格化图。读不到 / 为空时返回 None（由调用方兜底纯色）。
    size      : 输出边长（正方形，贴图按需缩放）。
    tone      : 目标明度（0~1）。越大地子越亮、纹样越跳。瓷面建议 0.82~0.90。
        ★ 实测：>0.92 会重新变"素"，<0.78 会抢主题纹的视觉。
    sat       : 保留的饱和度比例（0~1）。0.2 左右只剩"暖白/米青"的倾向。
        ★ 这是**关键**：不降饱和的话，AI 图的红绿会跟纹样撞色，画面很脏。
    blur      : 高斯模糊半径（相对 size 的比例）。要大到看不出内容，
        小到还留得住大面积色块 —— 0.03 左右是两个目的的交点。
    grain     : 叠加的细颗粒强度（0~255）。给"纸/釉"一点手感，
        纯模糊的地子会显得塑料。
    """
    if style_img is None:
        return None
    try:
        if isinstance(style_img, (str, Path)):
            p = Path(style_img)
            if not p.exists():
                return None
            im = Image.open(p).convert("RGB")
        else:
            im = style_img.convert("RGB")
    except Exception:
        return None

    # ① 缩到工作尺寸（先缩再模糊，省时间，也让模糊尺度与 size 绑定）
    work = im.resize((size // 4, size // 4), Image.LANCZOS)

    # ② 降饱和：把 AI 图的配色压成"只有色温倾向"的灰调
    work = ImageEnhance.Color(work).enhance(max(0.0, float(sat)))

    # ③ 强模糊：丢掉内容，只留大面积色块
    work = work.filter(ImageFilter.GaussianBlur(max(0.6, blur * (size // 4))))

    # ④ 提亮到目标明度（全程 0~255 量纲）
    a = np.asarray(work, np.float32)
    a = _auto_level_lum(a)
    lum = float((a @ _W).mean())
    if lum > 1e-6:
        a = a * (float(tone) * 255.0 / lum)

    # ⑤ 压对比：地子必须"退后"，不能让它的明暗起伏跟纹样抢
    m = a.mean()
    a = m + (a - m) * 0.34

    # ⑥ 细颗粒
    if grain > 0:
        rng = np.random.default_rng(seed)
        n = rng.normal(0.0, float(grain), a.shape).astype(np.float32)
        a = a + n

    a = np.clip(a, 0, 255).astype(np.uint8)
    g = Image.fromarray(a, "RGB").resize((size, size), Image.LANCZOS)

    # ⑦ 最后一层极轻的模糊，抹掉颗粒的硬边（保留手感但不刺）
    g = g.filter(ImageFilter.GaussianBlur(0.6))
    return g


def ground_rgb(style_img, **kw):
    """只要地子的**主色**（给 `_band` 等没有整图位置的地方用）。"""
    g = make_ground(style_img, size=256, **kw)
    if g is None:
        return FALLBACK
    a = np.asarray(g, np.float32).reshape(-1, 3).mean(0)
    return tuple(int(round(v)) for v in a)


def tile_ground(ground, w, h):
    """把正方形地子按需铺成 (w,h) 的底图（真·平铺，边缘自带虚化的无缝感）。"""
    if ground is None:
        return Image.new("RGB", (w, h), FALLBACK)
    g = ground.convert("RGB")
    if g.size != (w, h):
        g = g.resize((max(8, w), max(8, h)), Image.LANCZOS)
    return g
