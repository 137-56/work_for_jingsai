# src/preview3d.py
"""纹样贴附 3D 预览（甲方案）—— 把组合纹样图贴到器物形态上，出一张「文创效果预览」。

★★ 为什么用自写的光线投射渲染器，而不是 trimesh / pyrender / Blender
    1. **零新依赖**：只用 numpy + Pillow（项目已有）
    2. **纯 CPU**：与本作品"无需 GPU"的主张自洽（报告第三章）
    3. **完全确定性**：同一输入必得同一输出，可复现——这正是本作品的核心主张
    4. 离屏渲染在各平台的坑多（OpenGL/EGL），演示时炸一次就很难看

    做法是**解析求交**，不做通用栅格化：
      · 旋转体（瓶 / 盘）→ 拆成若干**圆台**，每段一个二次方程，取最近命中
      · 长方体（包装盒）→ 光线-平面求交，6 个面取最近
    解析解的好处：快、稳、无三角形接缝。

★★ 溯源口径（必须与报告一致）
    · **纹样层**：来自 M4a 组合纹样图 → 元素级可溯（母题库 Wényàng）
    · **载体层**：3D 形态是**程序化生成的标准几何体**（瓶/盒/盘），
      **不是文物三维模型**，也不由 AI 生成 —— 因此不引入任何新的溯源问题
    对外表述：**「纹样贴附于程序化生成的形态预览」**，
    不得暗示这是真实器物的三维复原。

用法：
    .venv/Scripts/python.exe src/preview3d.py --recipe outputs/<id>
    .venv/Scripts/python.exe src/preview3d.py --pattern 某图.png --out 输出.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 与溯源卡片一致的配色
PAPER = (247, 241, 230)
INK = (43, 35, 24)
GREY = (122, 114, 100)
GOLD = (212, 175, 55)
RED = (200, 16, 46)

# 光照：主光偏左上前方（与相机同侧，才有立体感）+ 补光 + 逆光轮廓
# ★ 三盏灯而不是两盏：只有主光+补光时，器物**背光的一侧会糊成一片死黑**
#   （实测旧版的左缘就是一条又黑又闷的边）。加一盏**逆光**（在物体后方偏上）
#   勾出轮廓，器物才有"从背景里立起来"的分离感。
L_KEY = np.array([-0.48, -0.72, 0.50]); L_KEY /= np.linalg.norm(L_KEY)
L_FILL = np.array([0.62, -0.28, 0.24]); L_FILL /= np.linalg.norm(L_FILL)
L_RIM = np.array([0.30, 0.55, -0.78]); L_RIM /= np.linalg.norm(L_RIM)

# ★ 曝光（整幅亮度乘子）。
#   旧版 shade = 0.36 + 0.70*diff1 + 0.20*diff2，命中区均值只有 96/255 ——
#   实测就是"整体发暗、像隔了层灰玻璃"。原因：0.36 的常量项偏低，
#   且 diff1/diff2 都在 [0,1]，实际取到的值多在中段，乘出来必然偏暗。
#   这里把**常量项提到 0.52**、把主光权重提到 0.78，
#   再补一个 1.06 的整体曝光 —— 命中区均值回到 140 上下（纸色底上不发灰）。
EXPOSURE = 1.06

# ★★ 方盒贴图 atlas 的**几何常量**（唯一真相源）
#    方盒需要两张图：侧面展开图（左半）+ 盒盖图（右上角）。
#    拼 atlas 的地方（render_preview）和用 UV 采样它的地方（_box_hit）
#    必须用同一组数字 —— 否则顶盖会采到空白区，渲染出一个白板
#    （实测踩到：把盖图的 u 宽度当成 0.5，实际只有 0.217）。
#    → 常量提到模块级，两处都引用，不再各写一份。
BOX_LID_U0 = 0.5      # 盖图左边界（= 展开图右边界）
_LID_DU = 0.5         # 盖图宽度（归一化）。由 render_preview 拼 atlas 时**实测回填**
_LID_DV = 0.5         # 盖图高度（归一化）。同上
                      # ★ 必须是"实测回填"而不是"手算写死"：
                      #   盖图实际占 0.217 宽（不是 0.5），手算容易错。
                      #   写死的后果是顶盖 40% 面积采到空白 atlas → 渲染成白板。
                      #   两处（拼图 / 采样）共用同一变量，就不可能再对不上。


# ---------------------------------------------------------------- 基础工具

def _rot(elev_deg, azim_deg):
    """对象旋转矩阵（先绕 Y 轴转方位，再绕 X 轴抬视角）。"""
    a, e = np.radians(azim_deg), np.radians(elev_deg)
    Ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    Rx = np.array([[1, 0, 0], [0, np.cos(e), -np.sin(e)], [0, np.sin(e), np.cos(e)]])
    return Ry @ Rx


def _rays(W, H, fov_deg, cam_dist):
    """生成透视光线。相机在 (0,0,cam_dist) 朝 -z 看，物体置于原点。"""
    aspect = W / H
    xs = (np.arange(W) + 0.5) / W * 2 - 1
    ys = 1 - (np.arange(H) + 0.5) / H * 2
    X, Y = np.meshgrid(xs, ys)
    t = np.tan(np.radians(fov_deg) / 2)
    d = np.stack([X * t * aspect, Y * t, -np.ones_like(X)], -1)
    d /= np.linalg.norm(d, axis=-1, keepdims=True)
    return d.astype(np.float32)


def _bilinear(tex, u, v, wrap_x=True):
    """双线性采样。tex (TH,TW,3) float；u/v 与 image 同形状，(0,0)=左上。"""
    TH, TW, _ = tex.shape
    x = u * TW - 0.5
    y = v * TH - 0.5
    x0 = np.floor(x).astype(np.int64); y0 = np.floor(y).astype(np.int64)
    fx = (x - x0)[..., None]; fy = (y - y0)[..., None]
    if wrap_x:
        x0w = np.mod(x0, TW); x1w = np.mod(x0 + 1, TW)
    else:
        x0w = np.clip(x0, 0, TW - 1); x1w = np.clip(x0 + 1, 0, TW - 1)
    y0c = np.clip(y0, 0, TH - 1); y1c = np.clip(y0 + 1, 0, TH - 1)
    c00 = tex[y0c, x0w]; c01 = tex[y0c, x1w]
    c10 = tex[y1c, x0w]; c11 = tex[y1c, x1w]
    return (c00 * (1 - fx) * (1 - fy) + c01 * fx * (1 - fy)
            + c10 * (1 - fx) * fy + c11 * fx * fy)


# ---------------------------------------------------------------- 求交

def _frustum_t(o, d, y0, y1, r0, r1):
    """光线与圆台侧面求交（旋转体表面，**旋转轴 = Y 轴**）。

    ★★ 轴必须是 Y，不能是 Z。
      我第一版用 z 当轴（因为剖面数据里那列叫 z），但 z 是**相机视线方向**，
      结果瓶子是"躺着朝向镜头"的——渲染出来是个扁球，我们看到的其实是瓶底。
      相机在 z 轴上、y 向上，所以物体的"高"必须沿 y。

    圆台表面：x² + z² = (a + b·y)²，半径随高度线性变化。
    代入 P = o + t·d 得二次方程，取落在 [y0,y1] 内的最近正根。

    ★★ 修过一个除零：
      末行 `tt = (-B ± sq) / (2A + 1e-12)` —— 这里的 `1e-12` 本来是想防 A=0，
      但当 `A` 略小于 0（圆台母线与光线近乎平行）时，`2A + 1e-12` 仍是负数，
      取根后落到 `tt < 0` 被 `good` 滤掉，**结果是对的**；
      真正报的是 NumPy 的 `invalid value encountered in divide` ——
      当 A 恰好是 -5e-13 时 `2A+1e-12` 会在 0 附近，`/0` 产生 inf/nan 并**污染**数组。
      改为**按 A 的符号分路**：A≈0 时退化为线性方程，不再做除法。
    """
    dy = y1 - y0
    if abs(dy) < 1e-9:
        b, a = 0.0, r0
    else:
        b = (r1 - r0) / dy
        a = r0 - b * y0
    A = d[..., 0] ** 2 + d[..., 2] ** 2 - (b * d[..., 1]) ** 2
    B = 2 * (o[0] * d[..., 0] + o[2] * d[..., 2] - (a + b * o[1]) * (b * d[..., 1]))
    C = o[0] ** 2 + o[2] ** 2 - (a + b * o[1]) ** 2
    t_best = np.full(d.shape[:2], np.inf)
    ylo, yhi = min(y0, y1) - 1e-6, max(y0, y1) + 1e-6

    # ---- A ≈ 0：退化为线性方程 B·t + C = 0（柱面/母线与视线平行）----
    lin = np.abs(A) < 1e-9
    if lin.any():
        with np.errstate(divide="ignore", invalid="ignore"):
            t_lin = np.where(np.abs(B) > 1e-12, -C / np.where(np.abs(B) > 1e-12, B, 1.0),
                             np.inf)
        yy = o[1] + t_lin * d[..., 1]
        good = lin & (t_lin > 1e-3) & (yy >= ylo) & (yy <= yhi) & np.isfinite(t_lin)
        t_best = np.where(good, t_lin, t_best)

    # ---- A > 0：正常二次方程 ----
    quad = ~lin
    if quad.any():
        disc = B * B - 4 * A * C
        ok = quad & (disc >= 0)
        if ok.any():
            sq = np.sqrt(np.where(ok, disc, 0.0))
            with np.errstate(divide="ignore", invalid="ignore"):
                den = np.where(np.abs(A) > 1e-12, 2 * A, 1.0)
                for sgn in (1.0, -1.0):
                    tt = (-B + sgn * sq) / den
                    yy = o[1] + tt * d[..., 1]
                    good = ok & (tt > 1e-3) & (yy >= ylo) & (yy <= yhi) & np.isfinite(tt)
                    t_best = np.where(good & (tt < t_best), tt, t_best)
    return t_best


def _disk_t(o, d, yc, rc):
    """光线与水平圆盘（端盖，法线沿 ±Y）求交。"""
    t = (yc - o[1]) / (d[..., 1] + 1e-12)
    px = o[0] + t * d[..., 0]; pz = o[2] + t * d[..., 2]
    good = (t > 1e-3) & (np.hypot(px, pz) <= rc)
    return np.where(good, t, np.inf)


def _revolve_hit(o, d, prof, tile_x=1.0, cap_bottom=None, cap_top=None):
    """旋转体命中（轴 = Y）：遍历各圆台段取最近。返回 (t, n_obj, uv)。

    tile_x：横向重复次数。
      ★★ 这里从 2.0 改成了 **1.0**，是这次美化的关键之一。
        旧版把一张 1024×1024 的**方形**组合图横向绕 2 圈、纵向 0→1 拉满，
        而器物是**瘦高**的 —— 方形贴到瘦高面上必然纵向拉长、横向压扁，
        瓶腹那只蝙蝠被拉成扁的、上下顶到脖子，一眼就看出是"贴上去的"。
        现在 `src/pattern_layout.py` 会先按器型拼一张**展开图**
        （横向 = 环一圈、纵向 = 从底到口），u∈[0,1] 正好绕一圈，
        所以 tile_x 必须是 1.0。
    """
    H, W = d.shape[:2]
    best_t = np.full((H, W), np.inf, np.float32)
    best_n = np.zeros((H, W, 3), np.float32)
    best_uv = np.zeros((H, W, 2), np.float32)

    y = prof[:, 0]; r = prof[:, 1]                    # y = 高度，r = 半径
    seglen = np.hypot(np.diff(y), np.diff(r))
    cum = np.concatenate([[0.0], np.cumsum(seglen)])
    total = max(float(cum[-1]), 1e-9)

    def _update(m, t, n, uv):
        nonlocal best_t, best_n, best_uv
        m = m & (t < best_t)
        if not m.any():
            return
        best_t = np.where(m, t, best_t)
        best_n = np.where(m[..., None], n, best_n)
        best_uv = np.where(m[..., None], uv, best_uv)

    for s in range(len(prof) - 1):
        y0, y1, r0, r1 = y[s], y[s + 1], r[s], r[s + 1]
        t = _frustum_t(o, d, y0, y1, r0, r1)
        m = np.isfinite(t)
        if not m.any():
            continue
        p = o[None, None, :] + t[..., None] * d
        dy = y1 - y0
        b = (r1 - r0) / dy if abs(dy) > 1e-9 else 0.0
        a = r0 - b * y0
        rr = a + b * p[..., 1]
        # ∇F = (2x, −2(a+b·y)b, 2z) → 外法线 ∝ (x, −r·b, z)
        n = np.stack([p[..., 0], -rr * b, p[..., 2]], -1)
        # ★ 未命中处 t=±inf → p=±inf → 这里的除法会算 inf/inf = NaN。
        #   虽然调用方只取 m=isfinite(t) 的像素、NaN 不会污染命中区，
        #   但 RuntimeWarning 会刷满控制台，掩盖真正的告警。
        #   → 显式清 NaN（同上：把非法值归零，靠 mask 筛）。
        n = np.where(np.isfinite(n), n, 0.0)
        n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-9)
        n = np.where(np.isfinite(n), n, 0.0)
        frac = np.clip((p[..., 1] - y0) / (dy if abs(dy) > 1e-9 else 1e-9), 0, 1)
        vv = (cum[s] + frac * seglen[s]) / total
        uu = np.mod(np.arctan2(p[..., 2], p[..., 0]) / (2 * np.pi), 1.0)   # 绕 Y 轴
        # ★ t 在未命中处是 ±inf → p 也是 ±inf → arctan2 给出 NaN。
        #   这里把 uv 收进合法区间并清零 NaN：uv 最终会被 _bilinear 的
        #   `np.where(good, ...)` 筛掉，但 NaN 在 uv 里会**一路带进索引数组**
        #   触发 `invalid value encountered in divide`。实测踩到。
        uv = np.stack([np.clip(uu * tile_x, 0, 1), np.clip(1.0 - vv, 0, 1)], -1)
        uv = np.where(np.isfinite(uv), uv, 0.0)
        _update(m, t, n, uv)

    for cap, sign in ((cap_bottom, -1.0), (cap_top, 1.0)):
        if cap is None:
            continue
        yc, rc = cap
        t = _disk_t(o, d, yc, rc)
        m = np.isfinite(t)
        if not m.any():
            continue
        p = o[None, None, :] + t[..., None] * d
        n = np.zeros_like(p); n[..., 1] = sign
        uv = np.stack([np.clip(p[..., 0] / (2 * rc) + 0.5, 0, 1),
                       np.clip(p[..., 2] / (2 * rc) + 0.5, 0, 1)], -1)
        uv = np.where(np.isfinite(uv), uv, 0.0)
        _update(m, t, n, uv)
    return best_t, best_n, best_uv


def _box_hit(o, d, half):
    """长方体命中（光线-平板求交，6 面取最近）。half 为半边长三元组。"""
    hm = np.array(half, np.float32)
    inv = 1.0 / (d + 1e-12)
    t1 = (-hm - o) * inv
    t2 = (hm - o) * inv
    tmin = np.max(np.minimum(t1, t2), axis=-1)
    tmax = np.min(np.maximum(t1, t2), axis=-1)
    ok = (tmax >= np.maximum(tmin, 1e-3)) & (tmin > 1e-3)
    axis = np.argmax(np.minimum(t1, t2), axis=-1)
    sign = np.take_along_axis(np.sign(np.take_along_axis(d, axis[..., None], -1)),
                              np.zeros((*axis.shape, 1), np.int64), -1)[..., 0]
    t = np.where(ok, tmin, np.inf)
    p = o[None, None, :] + t[..., None] * d
    n = np.zeros_like(p)
    for a in range(3):
        sel = (axis == a)
        # ★ 法线取 -sign(d)：光线沿 +a 前进时命中的是 -a 面，外法线指向 -a。
        #   这里一开始写成了 +sign，导致光照被镜像（形似正确、但光从错误一侧来），
        #   肉眼几乎看不出，是靠下面的法线朝向自检才发现的。
        n[..., a] = np.where(sel, -sign, n[..., a])
    # ★★ 方盒的 UV：**四个侧面各贴一张完整的"面图"，面内线性**。
    #
    #   试过三种，只有这一种对：
    #     ① 每面贴整张 1024² 方图 → 面与面之间纹样断裂，且方形图贴到面上变形（旧版）
    #     ② 四面对分展开图（u∈[k/4,(k+1)/4]）→ 宽度被压 4 倍，一排小蝙蝠
    #     ③ 按 atan2 方位角分摊 → 方角处变化率突变，面内非线性挤压（"两只半、大小不一"）
    #
    #   现在：`pattern_layout` 为方盒单独生成一张**按"一个面"的比例**的图
    #   （宽高比 1.15:1，主画面占中间 74%），四个面**各贴一整张**。
    #   面内 u/v 都是线性 → 零变形；四个面视觉一致 → 像个正经包装盒。
    #
    #   ⚠️ 代价：面与面的棱上纹样不连续。
    #      但对**包装盒**来说这恰恰是对的 —— 真实包装盒就是"一张图印一面"，
    #      没人要求六个面的图案绕圈接得上。而梅瓶不同：瓶子是旋转体，
    #      必须绕一圈连续（所以瓶子走 u∈[0,1] 环一圈的展开图）。
    #   **载体形状不同 → 贴图语义不同**，不能一套逻辑套到底。
    uv = np.zeros_like(p[..., :2])
    for a in range(3):
        sel = (axis == a)
        j = (2 if a == 0 else 1 if a == 1 else 0)
        # ★ 侧面只采样 atlas 的**左半**（u∈[0,0.5]，那里是展开图）；
        #   右半留给盒盖图。所以这里的 u 要先算到 [0,1] 再乘 0.5。
        if a == 2:                                    # ±z 面：u 沿 x
            uu = (p[..., 0] * np.sign(p[..., 2]) / hm[0] + 1.0) * 0.5 * 0.5
        elif a == 0:                                  # ±x 面：u 沿 z
            uu = (p[..., 2] * np.sign(p[..., 0]) / hm[2] + 1.0) * 0.5 * 0.5
        # ★ 侧面：v 沿高度 —— **图案的 v=0 对应盒子的底部**，所以要映射到
        #   盒子的实际 y 范围 [−hy, +hy] 而不是用 `p[...,1]/(2*hm[1])`。
        #   （`hm` 是半边长三元组，局部求交里盒子中心在 y=0，
        #     所以 `0.5 - py/(2*hy)` 正好把 y=+hy → v=0（顶部）、
        #     y=−hy → v=1（底部）。之前这段是对的，保留。）
        if a == 1:
            # 顶/底盖：用**专用的方盒盖图**（见 `pattern_layout.build_box_lid`）。
            # ★ 试过"直接采展开图的边饰带那一条线"→ 把几像素高的带子
            #   横向拉伸铺满整个顶盖，完全糊掉，只剩一片深色。
            #   现在 `render_preview` 会把盖图放在 uv 的 **u∈[0.5,1] × v∈[0.5,1]**
            #   子方块里，这里把顶盖的 (x,z) 线性映射到那个子方块。
            # ★ 盖图在 atlas 里的**实际**子矩形是 u∈[0.5, 0.5+lid_w_frac]、
            #   v∈[0, 0.5]，不是想当然的 [0.5,1]×[0,0.5]。差 0.28 的宽度，
            #   顶盖有 40% 面积采到空白底 → 渲染出来是"白板"。
            #   这里的 lid_w_frac 必须与 `render_preview` 里拼 atlas 的
            #   几何完全一致。常量写死有风险，故由模块级 BOX_LID_FRAC 统一。
            uu = BOX_LID_U0 + (p[..., 0] / hm[0] * 0.5 + 0.5) * _LID_DU
            vv = (p[..., 2] / hm[2] * 0.5 + 0.5) * _LID_DV
            uv[..., 0] = np.where(sel, np.clip(uu, 0, 1), uv[..., 0])
            uv[..., 1] = np.where(sel, np.clip(vv, 0, 1), uv[..., 1])
            continue
        vv = 0.5 - p[..., 1] / (2 * hm[1])
        uv[..., 0] = np.where(sel, np.clip(uu, 0, 1), uv[..., 0])
        uv[..., 1] = np.where(sel, np.clip(vv, 0, 1), uv[..., 1])
    uv = np.where(np.isfinite(uv), uv, 0.0)     # 同上：未命中处 p=±inf → NaN
    return t, n, uv


# ---------------------------------------------------------------- 形态定义

def _pchip(pts, n):
    """Pchip 平滑插值（保单调、不震荡），scipy 可用则用，否则线性兜底。"""
    pts = np.asarray(pts, float)
    h = pts[:, 0]
    grid = np.linspace(h[0], h[-1], n)
    try:
        from scipy.interpolate import PchipInterpolator
        r = PchipInterpolator(h, pts[:, 1])(grid)
    except Exception:
        r = np.interp(grid, h, pts[:, 1])
    return np.stack([grid, np.maximum(r, 1e-4)], -1)


def _normalize(prof, target=1.15, center=True):
    """把剖面归一化：最大尺寸（高 或 直径）缩到 target，并居中。

    ★ 为什么必须有这一步：三种形态若各按自己的坐标写，
      渲染出来**大小差异悬殊**（方盒会比瓶子大一圈），
      并排看就不像"同一配方的三种载体"，而是三个随机物体。
    """
    prof = prof.copy()
    z = prof[:, 0]; r = prof[:, 1]
    height = float(z.max() - z.min())
    dia = float(r.max() * 2)
    s = target / max(height, dia, 1e-9)
    prof[:, 1] = r * s
    prof[:, 0] = z * s
    if center:
        prof[:, 0] -= (prof[:, 0].max() + prof[:, 0].min()) / 2      # 竖向居中
    return prof


def form_vase(scale=1.0):
    """梅瓶：丰肩、束颈、小口。

    ★ 注意：剖面的 z **必须严格单调递增**。
      我第一版在末尾加了"口沿内收"的两点（z 从 1.00 折回 0.985、0.965），
      破坏了单调性 → Pchip 插值直接崩掉，渲染出来是个歪球。
      现在改为**只画外轮廓、到口沿为止**，不再折回做内口。
    """
    ctrl = [(0.00, 0.34), (0.04, 0.38), (0.10, 0.52), (0.18, 0.68), (0.28, 0.82),
            (0.38, 0.93), (0.48, 1.00), (0.58, 0.99), (0.68, 0.92), (0.76, 0.80),
            (0.83, 0.64), (0.89, 0.48), (0.94, 0.38), (0.98, 0.35)]      # ← z 递增
    prof = _pchip(ctrl, 70)
    prof[:, 1] *= 0.30
    prof = _normalize(prof, 1.15)
    return prof, None, (float(prof[0, 0]), float(prof[0, 1]))


def form_box(scale=1.0):
    """包装方盒。

    ★★ 尺寸修正（实测踩到）：原来是 `(0.479, 0.479, 0.575)` —— **竖着**放，
      高 0.958 + 加上近景透视（相机距离 3.35 很近，fov 26°），盒子在
      画框里**顶到底边被裁掉**，而且"高瘦长方体"不像个礼盒。
      → 改成**横放**：x/z 为宽（0.46），y 为高（0.35）。
        盒子的宽高比 6:5 左右接近真实礼盒；同时整体更矮，不再被裁。
    """
    half = (0.46, 0.35, 0.46)
    return None, tuple(v * scale for v in half), None


def form_fan(scale=1.0):
    """团扇：薄圆扇面 + 短柄。

    ★★ 为什么用团扇替掉赏盘（这是一个**取舍**，不是随手换的）
      赏盘是"近平面 + 从中心往外"的结构，而我们的贴图管线是
      "沿高度分层"的带状展开图 —— 两者天然错位。
      改了两轮（径向盘面图 + 圆形羽化遮罩）仍有拉伸与露白，
      根因是**盘的可用视觉面积太小**（高只有 0.211，几乎是一个平面），
      投入产出比不划算。

      团扇好在：
        · **平面方形载体** → 现有方形贴图直接可用，不用任何特殊映射
        · 是**文创里极常见的形式**（扇面、挂屏），比赏盘更贴合礼品场景
        · 有柄 → 仍是个"立体物件"，不是一个飘着的方片

    ★ 几何用**专用求交**（不是旋转体）：
        扇面 = 薄圆柱（两个圆面 + 侧边）
        扇柄 = 细长长方体
      圆盘求交比"用半径很小的圆台拼一个盘"简单得多，也不会出现接缝。
    """
    R = 0.52 * scale          # 扇面半径
    T = 0.022 * scale         # 扇面厚度（薄）
    HL = 0.22 * scale         # 柄长（半长；总长 2·HL。太长会喧宾夺主）
    HW = 0.026 * scale        # 柄半宽
    HT = 0.020 * scale        # 柄半厚
    return {"R": R, "T": T, "HL": HL, "HW": HW, "HT": HT}, None, None


def _fan_hit(o, d, g):
    """团扇求交：薄圆盘（两侧 + 侧边）+ 柄（长方体）。返回 (t, n_obj, uv)。"""
    R, T = g["R"], g["T"]
    HL, HW, HT = g["HL"], g["HW"], g["HT"]
    H, W = d.shape[:2]
    t_best = np.full((H, W), np.inf, np.float32)
    n_best = np.zeros((H, W, 3), np.float32)
    uv_best = np.zeros((H, W, 2), np.float32)

    def _upd(m, t, n, uv):
        nonlocal t_best, n_best, uv_best
        m = m & (t < t_best)
        if not m.any():
            return
        t_best = np.where(m, t, t_best)
        n_best = np.where(m[..., None], n, n_best)
        uv_best = np.where(m[..., None], uv, uv_best)

    # ---- 扇面：两个圆面（法线 ±Z）----
    # 扇面正对相机（法线朝 ±z），纹理按 (x,y) 平面映射
    for sign in (1.0, -1.0):
        t = (sign * T - o[2]) / (d[..., 2] + 1e-12)
        px = o[0] + t * d[..., 0]
        py = o[1] + t * d[..., 1]
        good = (t > 1e-3) & (np.hypot(px, py) <= R)
        n = np.zeros_like(d)
        n[..., 2] = sign
        uv = np.stack([np.clip(px / (2 * R) + 0.5, 0, 1),
                       np.clip(0.5 - py / (2 * R), 0, 1)], -1)
        uv = np.where(np.isfinite(uv), uv, 0.0)
        _upd(good, t, n, uv)

    # ---- 扇面侧边：绕 Z 轴的圆柱面 ----
    A = d[..., 0] ** 2 + d[..., 1] ** 2
    B = 2 * (o[0] * d[..., 0] + o[1] * d[..., 1])
    C = o[0] ** 2 + o[1] ** 2 - R * R
    disc = B * B - 4 * A * C
    ok = disc >= 0
    sq = np.sqrt(np.where(ok, disc, 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        den = np.where(np.abs(A) > 1e-12, 2 * A, 1.0)
        for sgn in (1.0, -1.0):
            tt = (-B + sgn * sq) / den
            pz = o[2] + tt * d[..., 2]
            good = ok & (tt > 1e-3) & (np.abs(pz) <= T) & np.isfinite(tt)
            if not good.any():
                continue
            tf = np.where(good, tt, 0.0)
            px = o[0] + tf * d[..., 0]; py = o[1] + tf * d[..., 1]
            n = np.stack([px, py, np.zeros_like(px)], -1)
            n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-9)
            uv = np.stack([np.mod(np.arctan2(py, px) / (2 * np.pi), 1.0),
                           np.clip(0.5 + pz / (2 * T) * 0.5, 0, 1)], -1)
            uv = np.where(np.isfinite(uv), uv, 0.0)
            _upd(good, tt, n, uv)

    # ---- 柄：长方体（在扇面**下方**，即 -y 方向）----
    # ★ 符号坑（实测踩到，而且渲染出来"看着也还行"，不容易发现）：
    #   柄的局部原点在扇面中心、柄沿 ±y 各延伸 HL。
    #   要让柄**朝下**，平移量必须是 -(R + HL)：这样柄的 y 范围是
    #   [-(R+2HL), -R]，正好从扇面下缘 (-R) 往下伸。
    #   写成 +(R + HL) 的话柄会**朝上**长出去 —— 看起来像"扇子插在地上"。
    o2 = o.copy()
    o2[1] = o[1] - (R + HL)          # 平移到柄的局部坐标（朝下）
    tb, nb, uvb = _box_hit(o2[None, None, :], d, (HW, HL, HT))
    good = np.isfinite(tb)
    if good.any():
        _upd(good, np.where(good, tb, np.inf), nb, uvb)

    return t_best, n_best, uv_best


    prof = _normalize(prof, 1.15)
    # 盘底封盖（在最底处），顶面由 profile 自然收口
    return prof, None, (float(prof[0, 0]), float(prof[0, 1] * 1.02))


FORMS = {
    # name, builder, elev(俯角), flip_normals
    # ★ flip_normals：旋转体的外法线按"实体在轴内侧"来定义（对瓶子是对的）。
    #   若将来加入剖面朝外的形态（如盘类），法线需整体翻转，
    #   否则受光面会跑到背面（渲染出来是一块闷掉的深色）——
    #   这种错误肉眼不易发现，靠 scripts/check_render3d.py 的法线朝向自检才查得出。
    #   当前三形态（vase / box / fan）都取 False。
    "vase":  ("陶瓶（梅瓶）", form_vase, 12.0, False),
    "box":   ("包装方盒", form_box, 16.0, False),
    "fan":   ("团扇", form_fan, 8.0, False),
}


# ---------------------------------------------------------------- 渲染

def render_form(kind, tex, W=760, H=920, fov=26.0, cam=3.35,
                elev=None, azim=30.0, ss=2, tile_x=1.0, use_planar_uv=False):
    """把一个形态渲染成 RGBA（返回 float 数组 HxWx4，A=覆盖率）。"""
    name, builder, elev_def, flip = FORMS[kind]
    if elev is None:
        elev = elev_def
    rw, rh = W * ss, H * ss
    d = _rays(rw, rh, fov, cam)
    R = _rot(elev, azim)
    Rt = R.T
    o = np.array([0.0, 0.0, cam], np.float32)
    o_obj = Rt @ o.astype(np.float32)
    d_obj = (d.reshape(-1, 3) @ Rt.T).reshape(rh, rw, 3)

    prof, half, extra = builder()

    if kind == "fan":
        # 团扇：专用求交（薄圆盘 + 柄），不走旋转体也不走长方体
        t, n_obj, uv = _fan_hit(o_obj, d_obj, prof)
    elif prof is not None:
        cap_b = extra
        t, n_obj, uv = _revolve_hit(o_obj, d_obj, prof, tile_x=tile_x,
                                    cap_bottom=cap_b, cap_top=None)
    else:
        t, n_obj, uv = _box_hit(o_obj, d_obj, half)

    if flip:
        n_obj = -n_obj

    hit = np.isfinite(t)
    if not hit.any():
        return np.zeros((rh, rw, 4), np.float32)

    # ★★ 关键：先把未命中处替换成 0，**再**做任何光照计算。
    #   否则未命中处的 t=inf → p_world=±inf，一旦参与 min()/max() 之类的统计，
    #   就会算出 inf-inf 或 inf/inf = NaN，并顺着数组**污染命中像素**（整图变黑）。
    #   这个坑实测踩过：形状轮廓正确、采样色也正确，但整张图渲成纯黑。
    t_f = np.where(hit, t, 0.0).astype(np.float32)

    n_world = (n_obj.reshape(-1, 3) @ R.T).reshape(rh, rw, 3)
    p_world = o[None, None, :] + t_f[..., None] * d          # d 已是世界方向
    V = o[None, None, :] - p_world
    V /= np.maximum(np.linalg.norm(V, axis=-1, keepdims=True), 1e-9)

    col = _bilinear(tex, uv[..., 0], uv[..., 1],
                    wrap_x=(prof is not None and not use_planar_uv))

    diff1 = np.clip((n_world * L_KEY).sum(-1), 0, 1)
    diff2 = np.clip((n_world * L_FILL).sum(-1), 0, 1)
    # ★ 逆光：**只看面向背光的那一侧**，用 (1 - |n·L|) 的形式让边缘环带亮起来。
    #   直接用 diff 会变成第三盏普通灯，只在正对时亮（那就没轮廓了）。
    rim = np.clip((n_world * L_RIM).sum(-1), 0, 1) ** 3
    half_v = np.clip(n_world * (L_KEY[None, None, :] + V), -1, 1)
    spec = np.clip(half_v.sum(-1), 0, 1) ** 32          # 陶瓷釉面高光

    # 竖向环境遮蔽：越靠下越暗，器物才有"落在台面上"的感觉
    # ★ 统计范围只在**命中像素**内取，别把 0 值（未命中）算进去
    yv_hit = p_world[..., 1][hit]
    lo, hi = float(yv_hit.min()), float(yv_hit.max())
    yv = np.clip((p_world[..., 1] - lo) / max(hi - lo, 1e-9), 0, 1)
    # ★ 旧版这里是 `yv`（越靠上越亮）—— 那其实是"上亮下暗"的**竖直渐变**，
    #   更像打了盏顶灯，不像环境遮蔽。
    #   真正的 AO 是：**凹处 / 根部 / 贴地那一圈**更暗。
    #   这里用 yv^2.5 反相，让变暗集中在**最下面 1/4**，
    #   而不是一路均匀变暗（均匀变暗会让上半截也发灰）。
    ao_v = 0.90 + 0.10 * (yv ** 0.6) - 0.16 * np.clip(1.0 - yv * 4.0, 0, 1)

    shade = (0.52 + 0.78 * diff1 + 0.18 * diff2) * ao_v * EXPOSURE
    shade = np.clip(shade, 0.0, 1.9)

    rgb = col * shade[..., None] + spec[..., None] * 86.0 + rim[..., None] * 26.0
    rgb = np.where(hit[..., None], np.clip(rgb, 0, 255), 0.0)

    out = np.zeros((rh, rw, 4), np.float32)
    out[..., :3] = rgb
    out[..., 3] = np.where(hit, 255.0, 0.0)

    if ss > 1:                                          # 超采样后缩回，边缘更干净
        img = Image.fromarray(out.astype(np.uint8), "RGBA").resize((W, H), Image.LANCZOS)
        return np.asarray(img).astype(np.float32)
    return out


# ---------------------------------------------------------------- 合成

def _composite(objs, labels, title, subtitle, footer, out_path, pad=56):
    """把若干渲染结果并排合成一张预览图（纸色底 + 投影 + 标题）。"""
    from src.m6_provenance import _font

    W = max(o.shape[1] for o in objs)
    Tw = W * len(objs) + pad * (len(objs) + 1)
    TOP, BOT = 208, 176      # BOT 留足两行底注（折行后可能 2 行）
    canvas = Image.new("RGB", (Tw, TOP + objs[0].shape[0] + BOT), PAPER)
    d = ImageDraw.Draw(canvas)

    for i, (arr, lab) in enumerate(zip(objs, labels)):
        x0 = pad + i * (W + pad)
        y0 = TOP
        rgba = Image.fromarray(arr.astype(np.uint8), "RGBA")
        ah = arr.shape[0]; aw = arr.shape[1]
        # 投影：取 alpha 的底部椭圆，模糊后压暗背景
        alpha = Image.fromarray(arr[..., 3].astype(np.uint8), "L")
        sh = Image.new("L", canvas.size, 0)
        band = alpha.crop((0, int(ah * 0.86), aw, ah)).resize((int(aw * 0.92), 40))
        sh.paste(band, (x0 + int(aw * 0.04), y0 + ah - 26))
        sh = sh.filter(ImageFilter.GaussianBlur(16))
        shadow = Image.new("RGB", canvas.size, (198, 186, 166))
        canvas.paste(Image.composite(shadow, canvas, sh.point(lambda v: int(v * 0.42))), (0, 0))
        canvas.paste(rgba, (x0, y0), rgba)
        f = _font(30)
        tw = d.textlength(lab, font=f)
        d.text((x0 + (aw - tw) / 2, y0 + ah + 18), lab, font=f, fill=INK)

    d.text((pad, 44), title, font=_font(58), fill=INK)
    d.text((pad, 126), subtitle, font=_font(30), fill=GREY)
    sep_y = TOP + objs[0].shape[0] + 74
    d.line([pad, sep_y, Tw - pad, sep_y], fill=GOLD, width=3)

    # ★ 底注按画布宽度**自动折行**：启用 AI 地子后底注变成三句，
    #   单行必然超出画布右侧被截断（实测）。这里用「以 ｜ 为分隔的首选断点
    #   + 宽度兜底」两段策略，保证任何长度都能排下。
    ffoot = _font(24)
    maxw = Tw - pad * 2
    segs = [s.strip() for s in footer.split("｜") if s.strip()]
    lines, cur = [], ""
    for seg in segs:
        cand = (cur + "　｜　" + seg) if cur else seg
        if d.textlength(cand, font=ffoot) <= maxw:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            # 单段本身超宽 → 按字符硬断
            while d.textlength(seg, font=ffoot) > maxw:
                k = len(seg)
                while k > 1 and d.textlength(seg[:k], font=ffoot) > maxw:
                    k -= 1
                lines.append(seg[:k])
                seg = seg[k:]
            cur = seg
    if cur:
        lines.append(cur)
    for i, ln in enumerate(lines):
        d.text((pad, sep_y + 14 + i * 32), ln, font=ffoot, fill=GREY)
    canvas.save(out_path, "PNG")
    return canvas.size


# 两档质量（实测耗时，单形态）
#   high：760×920，2× 超采样 → 约 38s／形态（离线出报告图用）
#   fast：560×680，1× 超采样 → 约 4.5s／形态（界面按需预览用）
QUALITY = {"high": (760, 920, 2), "fast": (560, 680, 1)}


def render_preview(pattern_png, out_dir, recipe=None, hits=None, quality="high",
                   style_img=None):
    """渲染三形态并合成。返回 {形态: 路径}。

    ★★ 与旧版的根本差别（这是"美化"的核心，不只是调参数）
      旧版：拿**一张 1024×1024 的方形组合图**，横向绕 2 圈、纵向拉满贴上去。
            方形贴瘦高面 → 必然变形；绕 2 圈 → 蝙蝠被面与面的接缝劈开。

      新版：先调 `src/pattern_layout.build_strip()` 按**器型 + 配方结构**
            拼一张**展开图**（横向 = 环一圈、纵向 = 从底到口），
            每一段用**合适的**素材：口沿/胫部=边饰、腹部=主题纹、底部=角花，
            段与段之间用弦纹过渡。然后 u∈[0,1] 正好绕一圈、v 从底到顶。

      这不是"为了好看耍的花招"，而是**把配方的语义结构
      （center_motif / border / corner）忠实地翻译成器物的装饰结构** ——
      清代瓷器的装饰本来就是这么分层的。立论上反而比旧做法更硬：
      现在能说清"哪一段来自哪一个母题"。

    hits：M2 检索结果。给了才做分区展开图；没给就退化为"整幅贴"
          （保留旧行为，方便拿单张图直接试）。

    style_img：**可选**的 M5 AI 风格化图路径。给了就把它的色彩氛围抽成
          "地子"垫在各分区底下，解决"白底太素"的问题（见 style_ground）。
          不给 = 原来的纯色地子行为。**不影响纹样层的溯源口径**——
          地子只是渲染层，上层语义纹样仍全部来自母题库。
    """
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    W, H, ss = QUALITY[quality]

    tex_cache, meta_all = {}, {}
    use_layout = bool(recipe and hits)

    # 地子：从 AI 风格化图抽氛围（失败/未给 → None，退回纯色）
    ground = None
    ground_meta = {"ground_from": "neutral"}
    if style_img and use_layout:
        try:
            from src.style_ground import make_ground
            ground = make_ground(style_img, size=1024)
            if ground is not None:
                ground_meta = {"ground_from": "ai_stylized",
                               "ground_src": str(style_img)}
        except Exception as e:
            print(f"  ！地子抽取失败（退回纯色）：{type(e).__name__}: {e}")
            ground = None

    if ground is not None:
        print(f"地子方式：AI 风格化提色（{Path(style_img).name}）")

    from src.pattern_layout import use_ground
    _gctx = use_ground(ground)

    print(f"贴图方式：{'分区展开图（按配方结构）' if use_layout else '整幅贴（无检索结果，退化）'}"
          f"　质量档 {quality}（{W}×{H}, {ss}× 超采样）")

    def _tex_for(kind):
        if not use_layout:
            if "raw" not in tex_cache:
                tex_cache["raw"] = np.asarray(
                    Image.open(pattern_png).convert("RGB"), np.float32)
            return tex_cache["raw"]
        if kind not in tex_cache:
            if kind == "fan":
                # ★ 团扇是**圆形平面载体**：贴图是正方形（因为 UV 走 (x,y)
                #   平面映射），但内容**全部按同心圆构造** —— 见 build_fan_face。
                #   （曾用"方图 + 四条直边带"，结果弧边把带子切成四段、
                #     四个角露出方框，像贴了四张邮票。已废弃。）
                from src.pattern_layout import build_fan_face
                face, meta = build_fan_face(recipe, hits, size=1024)
                meta_all[kind] = meta
                tex_cache[kind] = np.asarray(face, np.float32)
            elif kind == "box":
                # ★ 方盒需要**两张**贴图拼在一张 atlas 里：
                #     左半 (u<0.5)：侧面展开图（下边饰 + 主画面 + 上边饰）
                #     右上 (u>0.5, v<0.5)：盒盖图（方框边饰 + 中心主题）
                #   盒盖不能复用侧面展开图的某一段（见 build_box_lid 注释）。
                from src.pattern_layout import build_strip, build_box_lid
                strip, meta = build_strip(recipe, hits, height=1024, kind="box")
                lid, meta_lid = build_box_lid(recipe, hits, size=1024)
                sw, sh = strip.size
                # atlas 底板：有地子时先铺地子（否则露出的角上是死白）
                from src.pattern_layout import ground_tile
                atlas = ground_tile(2 * sw, sh)
                atlas.paste(strip, (0, 0))
                # 盖图等比缩到右半区的一半高度
                lh = sh // 2
                lw = lh                       # 盖图是正方形，等比缩到半高
                atlas.paste(lid.resize((lw, lh), Image.LANCZOS), (sw, 0))
                # ★ 全局写入盖图的实际归一化子矩形，供 _box_hit 的 UV 使用。
                global _LID_DU, _LID_DV
                _LID_DU, _LID_DV = lw / (2 * sw), lh / sh
                meta_all[kind] = {**meta, "lid": meta_lid}
                tex_cache[kind] = np.asarray(atlas, np.float32)
            else:
                from src.pattern_layout import build_strip
                strip, meta = build_strip(recipe, hits, height=1024, kind=kind)
                meta_all[kind] = meta
                tex_cache[kind] = np.asarray(strip, np.float32)
        return tex_cache[kind]

    objs, labels, paths = [], [], {}
    with _gctx:                      # ★ 全程挂着地子，贴图与 atlas 底板都吃它
        for kind in ("vase", "box", "fan"):
            name = FORMS[kind][0]
            print(f"  · {name} …", flush=True)
            arr = render_form(kind, _tex_for(kind), W=W, H=H, ss=ss)
            p = out_dir / f"preview3d_{kind}.png"
            Image.fromarray(arr.astype(np.uint8), "RGBA").save(p)
            paths[kind] = p
            objs.append(arr); labels.append(name)

    sub = "同一配方 × 三种载体形态（按配方结构分区贴附）" if use_layout \
        else "同一配方 × 三种载体形态"
    if recipe:
        cm = (recipe.get("structure", {}).get("center_motif") or {}).get("name")
        bd = (recipe.get("structure", {}).get("border") or {}).get("pattern")
        if cm or bd:
            sub += f"　｜　腹部 {cm or '—'}　边饰 {bd or '—'}"
    triptych = out_dir / "preview3d_triptych.png"
    # ★ 底注必须随"是否启用 AI 地子"而变 —— 这是溯源口径的落地点，
    #   不能让两种模式共用同一句"非 AI 生成"（会失实）。
    if ground is not None:
        foot = ("纹样层：各分区纹样分别来自语义层母题库，元素级可溯　｜　"
                "地子层：取自 AI 风格化图（仅渲染色底，不承载语义）　｜　"
                "载体层：程序化生成的标准几何体，仅作形态预览")
        title_sub = sub + "　｜　底纹经风格化"
    else:
        foot = ("纹样层：各分区纹样分别来自语义层母题库，元素级可溯　｜　"
                "载体层：程序化生成的标准几何体（非文物三维模型、非 AI 生成），仅作形态预览")
        title_sub = sub
    _composite(objs, labels,
               "文创效果预览 · 纹样分区贴附于器物形态",
               title_sub,
               foot,
               triptych)
    paths["triptych"] = triptych
    if meta_all:
        import json as _json
        meta_all["_render"] = ground_meta
        (out_dir / "preview3d_layout.json").write_text(
            _json.dumps(meta_all, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 三联预览 → {triptych}")
    return paths


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", help="输出目录（含 composed_pattern.png）")
    ap.add_argument("--pattern", help="直接指定纹样图")
    ap.add_argument("--out", help="输出目录或文件名")
    ap.add_argument("--quality", default="high", choices=list(QUALITY),
                    help="high 离线出报告图（约 2 分钟）／fast 快速预览（约 15 秒）")
    args = ap.parse_args()

    if args.recipe:
        rd = Path(args.recipe)
        if not rd.is_absolute():
            rd = ROOT / rd
        pat = rd / "composed_pattern.png"
        rec = None
        rj = rd / "recipe.json"
        if rj.exists():
            rec = json.loads(rj.read_text(encoding="utf-8"))
        out_dir = Path(args.out) if args.out else rd
    elif args.pattern:
        pat = Path(args.pattern)
        rec = None
        out_dir = Path(args.out) if args.out else (ROOT / "outputs" / "preview3d")
    else:
        ap.print_help()
        return 1

    if not Path(pat).exists():
        print(f"[FAIL] 纹样图不存在：{pat}（先跑一次管线生成 composed_pattern.png）")
        return 1

    # ★ 有配方就顺带跑一次 M2 检索 —— 分区贴图需要 hits 才能取到各槽位的母题。
    #   （M2 依赖 CLIP 权重，慢；所以只在有配方时做，且失败就退化为整幅贴）
    hits = None
    if rec:
        try:
            from src.m2_retrieve import retrieve
            hits = retrieve(rec, top_k=10)
            print(f"M2 检索 {len(hits)} 条（用于分区取料）")
        except Exception as e:
            print(f"[警告] M2 检索失败，退化为整幅贴：{type(e).__name__}: {e}")
    render_preview(pat, out_dir, rec, hits=hits, quality=args.quality)
    return 0


if __name__ == "__main__":
    sys.exit(main())
