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

# 光照：主光偏左上前方（与相机同侧，才有立体感）+ 补光 + 环境
L_KEY = np.array([-0.48, -0.72, 0.50]); L_KEY /= np.linalg.norm(L_KEY)
L_FILL = np.array([0.62, -0.28, 0.24]); L_FILL /= np.linalg.norm(L_FILL)


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
    disc = B * B - 4 * A * C
    ok = disc >= 0
    sq = np.sqrt(np.where(ok, disc, 0.0))
    t_best = np.full(d.shape[:2], np.inf)
    ylo, yhi = min(y0, y1) - 1e-6, max(y0, y1) + 1e-6
    for sgn in (1.0, -1.0):
        tt = (-B + sgn * sq) / (2 * A + 1e-12)
        yy = o[1] + tt * d[..., 1]
        good = ok & (tt > 1e-3) & (yy >= ylo) & (yy <= yhi)
        t_best = np.where(good & (tt < t_best), tt, t_best)
    return t_best


def _disk_t(o, d, yc, rc):
    """光线与水平圆盘（端盖，法线沿 ±Y）求交。"""
    t = (yc - o[1]) / (d[..., 1] + 1e-12)
    px = o[0] + t * d[..., 0]; pz = o[2] + t * d[..., 2]
    good = (t > 1e-3) & (np.hypot(px, pz) <= rc)
    return np.where(good, t, np.inf)


def _revolve_hit(o, d, prof, tile_x=2.0, cap_bottom=None, cap_top=None):
    """旋转体命中（轴 = Y）：遍历各圆台段取最近。返回 (t, n_obj, uv)。"""
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
        n /= np.maximum(np.linalg.norm(n, axis=-1, keepdims=True), 1e-9)
        frac = np.clip((p[..., 1] - y0) / (dy if abs(dy) > 1e-9 else 1e-9), 0, 1)
        vv = (cum[s] + frac * seglen[s]) / total
        uu = np.mod(np.arctan2(p[..., 2], p[..., 0]) / (2 * np.pi), 1.0)   # 绕 Y 轴
        _update(m, t, n, np.stack([uu * tile_x, 1.0 - vv], -1))

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
        uv = np.stack([p[..., 0] / (2 * rc) + 0.5, p[..., 2] / (2 * rc) + 0.5], -1)
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
    # 各面用平面投影做 UV：正面(±z)用 (x,y)，±x 用 (y,z)，±y 用 (x,z)
    uv = np.zeros_like(p[..., :2])
    for a in range(3):
        sel = (axis == a)
        i, j = ((1, 2) if a == 0 else (0, 2) if a == 1 else (0, 1))
        uv[..., 0] = np.where(sel, p[..., i] / (2 * hm[i]) + 0.5, uv[..., 0])
        uv[..., 1] = np.where(sel, 0.5 - p[..., j] / (2 * hm[j]), uv[..., 1])
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
    """包装方盒（略高）。"""
    half = (0.479, 0.479, 0.575)                 # 归一化后最大边长 ≈1.15
    return None, tuple(v * scale for v in half), None


def form_plate(scale=1.0):
    """浅盘 / 赏盘：盘心到底、盘壁上扬、口沿外撇。

    ★ 同样必须保证 z 单调递增（第一版这里也折回了，同样是错的）。
      从盘底中心往外画到口沿：z 递增、r 递增。
    """
    ctrl = [(0.00, 0.00), (0.012, 0.10), (0.030, 0.22), (0.055, 0.34),
            (0.090, 0.45), (0.130, 0.53), (0.175, 0.575), (0.220, 0.60)]
    prof = _pchip(ctrl, 60)
    prof = _normalize(prof, 1.15)
    # 盘底封盖（在最底处），顶面由 profile 自然收口
    return prof, None, (float(prof[0, 0]), float(prof[0, 1] * 1.02))


FORMS = {
    # name, builder, elev(俯角), flip_normals
    # ★ flip_normals：旋转体的外法线按"实体在轴内侧"来定义（对瓶子是对的）。
    #   但赏盘的剖面是从盘心向外画到口沿、**实体在下方**，所以法线要整体翻转，
    #   否则受光面会跑到背面去（渲染出来是一块闷掉的深色）。
    #   这个错误肉眼不容易发现，靠 scripts 里的法线朝向自检才能查出来。
    "vase":  ("陶瓶（梅瓶）", form_vase, 12.0, False),
    "box":   ("包装方盒", form_box, 16.0, False),
    "plate": ("赏盘", form_plate, 34.0, True),
}


# ---------------------------------------------------------------- 渲染

def render_form(kind, tex, W=760, H=920, fov=26.0, cam=3.35,
                elev=None, azim=30.0, ss=2, tile_x=2.0, use_planar_uv=False):
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

    if prof is not None:
        # 旋转体：底盖用 extra；赏盘盘心处半径为 0，不需要盖
        cap_b = extra if kind != "plate" else None
        t, n_obj, uv = _revolve_hit(o_obj, d_obj, prof, tile_x=tile_x,
                                    cap_bottom=cap_b, cap_top=None)
        if use_planar_uv:                       # 赏盘：盘面是水平面(x–z)，用平面投影像"印上去的"
            tf = np.where(np.isfinite(t), t, 0.0)
            p = o_obj[None, None, :] + tf[..., None] * d_obj
            rr = float(prof[:, 1].max())
            uv = np.stack([p[..., 0] / (2 * rr) + 0.5, p[..., 2] / (2 * rr) + 0.5], -1)
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
    half_v = np.clip(n_world * (L_KEY[None, None, :] + V), -1, 1)
    spec = np.clip(half_v.sum(-1), 0, 1) ** 32          # 陶瓷釉面高光

    shade = 0.36 + 0.70 * diff1 + 0.20 * diff2
    # 竖向环境遮蔽：越靠下越暗，器物才有"落在台面上"的感觉
    # ★ 统计范围只在**命中像素**内取，别把 0 值（未命中）算进去
    yv_hit = p_world[..., 1][hit]
    lo, hi = float(yv_hit.min()), float(yv_hit.max())
    yv = (p_world[..., 1] - lo) / max(hi - lo, 1e-9)
    yv = np.clip(yv, 0, 1)
    shade = shade * (0.82 + 0.18 * yv)

    rgb = col * shade[..., None] + spec[..., None] * 78.0
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
    TOP, BOT = 208, 150
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
    d.line([pad, TOP + objs[0].shape[0] + 74, Tw - pad, TOP + objs[0].shape[0] + 74],
           fill=GOLD, width=3)
    d.text((pad, TOP + objs[0].shape[0] + 88), footer, font=_font(24), fill=GREY)
    canvas.save(out_path, "PNG")
    return canvas.size


# 两档质量（实测耗时，单形态）
#   high：760×920，2× 超采样 → 约 38s／形态（离线出报告图用）
#   fast：560×680，1× 超采样 → 约 4.5s／形态（界面按需预览用）
QUALITY = {"high": (760, 920, 2), "fast": (560, 680, 1)}


def render_preview(pattern_png, out_dir, recipe=None, quality="high"):
    """渲染三形态并合成。返回 {形态: 路径}。"""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    W, H, ss = QUALITY[quality]
    tex = np.asarray(Image.open(pattern_png).convert("RGB"), np.float32)
    print(f"纹样图 {tex.shape[1]}×{tex.shape[0]}　质量档 {quality}（{W}×{H}, {ss}× 超采样）")

    objs, labels, paths = [], [], {}
    for kind in ("vase", "box", "plate"):
        name = FORMS[kind][0]
        print(f"  · {name} …", flush=True)
        arr = render_form(kind, tex, W=W, H=H, ss=ss,
                          use_planar_uv=(kind == "plate"))
        p = out_dir / f"preview3d_{kind}.png"
        Image.fromarray(arr.astype(np.uint8), "RGBA").save(p)
        paths[kind] = p
        objs.append(arr); labels.append(name)

    sub = "同一配方 × 三种载体形态"
    if recipe:
        cm = (recipe.get("structure", {}).get("center_motif") or {}).get("name")
        bd = (recipe.get("structure", {}).get("border") or {}).get("pattern")
        if cm or bd:
            sub += f"　｜　中心 {cm or '—'}　边饰 {bd or '—'}"
    triptych = out_dir / "preview3d_triptych.png"
    _composite(objs, labels,
               "文创效果预览 · 纹样贴附于器物形态",
               sub,
               "纹样层：来自语义层母题库，元素级可溯　｜　"
               "载体层：程序化生成的标准几何体（非文物三维模型、非 AI 生成），仅作形态预览",
               triptych)
    paths["triptych"] = triptych
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
    render_preview(pat, out_dir, rec, quality=args.quality)
    return 0


if __name__ == "__main__":
    sys.exit(main())
