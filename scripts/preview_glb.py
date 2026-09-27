# scripts/preview_glb.py
"""**独立**渲染 .glb 做眼验 —— 不复用 preview3d 的任何代码。

★★ 为什么需要它
    `check_glb_uv.py` 只能验"数值上没越界、没采到空白"，
    但**看不出贴图方向对不对**（上下颠倒、左右镜像、UV 整体错位）。
    而 GLB 一旦贴反，用户下载下来看到的就是错的 —— 偏偏静态预览
    是另一条代码路径，两边不一致时**静态预览完全正常**，掩盖问题。

    所以这里从 .glb 字节流**独立**重建网格与 UV，用一个最朴素的
    z-buffer 光栅化 + 最近邻采样渲染出来，与静态预览并排比对。
    两条完全独立的实现给出同一个画面，才算可信。

用法：
    .venv/Scripts/python.exe scripts/preview_glb.py --dir outputs/<id> [--out out.png]
"""
from __future__ import annotations

import argparse
import io
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_glb_uv import load_glb, read_accessor  # noqa: E402

PAPER = (243, 238, 228)
INK = (58, 52, 44)


def render_glb(path, W=560, H=680, elev_deg=16.0, azim_deg=30.0, cam=3.6,
               fov_deg=26.0, ss=2):
    """z-buffer 光栅化。返回 RGBA 的 np 数组。"""
    j, bin_bytes = load_glb(path)
    prim = j["meshes"][0]["primitives"][0]
    pos = read_accessor(j, bin_bytes, prim["attributes"]["POSITION"])
    nrm = read_accessor(j, bin_bytes, prim["attributes"]["NORMAL"])
    uv = read_accessor(j, bin_bytes, prim["attributes"]["TEXCOORD_0"])
    idx = read_accessor(j, bin_bytes, prim["indices"]).astype(np.int64)

    # --- 内嵌贴图 ---
    img = j["images"][0]
    bv = j["bufferViews"][img["bufferView"]]
    off = bv.get("byteOffset", 0)
    tex = np.asarray(Image.open(
        io.BytesIO(bin_bytes[off: off + bv["byteLength"]])).convert("RGB"),
        np.float32)
    TH, TW = tex.shape[:2]

    # --- 物体 → 世界 旋转（与 preview3d 同约定）---
    a, e = np.radians(azim_deg), np.radians(elev_deg)
    Ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    Rx = np.array([[1, 0, 0], [0, np.cos(e), -np.sin(e)], [0, np.sin(e), np.cos(e)]])
    R = Rx @ Ry
    p_w = pos @ R.T
    n_w = nrm @ R.T

    # --- 相机投影 ---
    rw, rh = W * ss, H * ss
    aspect = rw / rh
    f = 1.0 / np.tan(np.radians(fov_deg) / 2)
    sx, sy = f / aspect, f
    cam_p = p_w - np.array([0.0, 0.0, cam], np.float32)

    zbuf = np.full((rh, rw), np.inf, np.float32)
    cbuf = np.zeros((rh, rw, 3), np.float32)
    dbuf = np.zeros((rh, rw), np.float32)

    # 光照三盏（与 preview3d 同方向，确保对比有意义）
    L_KEY = np.array([-0.48, -0.72, 0.50]); L_KEY /= np.linalg.norm(L_KEY)
    L_FILL = np.array([0.62, -0.28, 0.24]); L_FILL /= np.linalg.norm(L_FILL)
    EXPOSURE = 1.06

    for t in range(0, len(idx), 3):
        i0, i1, i2 = idx[t], idx[t + 1], idx[t + 2]
        P = cam_p[[i0, i1, i2]]
        # 背面剔除（相机在 +z，看 -z 方向）
        N = n_w[[i0, i1, i2]]
        if ((N.sum(0) / 3)[2] > 0.35) and ((P[:, 2].mean()) < 0):
            # 朝向相机且在前方 → 保留；这里走保守策略，不剔除，
            # 靠 z-buffer 决定，避免把双面材质的正面误剔。
            pass
        # 投影
        scr = np.empty((3, 2), np.float32)
        for k in range(3):
            zc = -P[k, 2]
            if zc <= 0.05:
                scr[k] = (1e9, 1e9); continue
            ndc_x = (P[k, 0] * sx) / zc
            ndc_y = (P[k, 1] * sy) / zc
            scr[k, 0] = (ndc_x * 0.5 + 0.5) * rw
            scr[k, 1] = (0.5 - ndc_y * 0.5) * rh
        if (scr > 1e8).any():
            continue

        x0 = max(0, int(np.floor(scr[:, 0].min())))
        x1 = min(rw - 1, int(np.ceil(scr[:, 0].max())))
        y0 = max(0, int(np.floor(scr[:, 1].min())))
        y1 = min(rh - 1, int(np.ceil(scr[:, 1].max())))
        if x1 < x0 or y1 < y0:
            continue

        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5,
                             np.arange(y0, y1 + 1) + 0.5)
        ax, ay = scr[0]; bx, by = scr[1]; cx2, cy2 = scr[2]
        den = (by - cy2) * (ax - cx2) + (cx2 - bx) * (ay - cy2)
        if abs(den) < 1e-12:
            continue
        w0 = ((by - cy2) * (gx - cx2) + (cx2 - bx) * (gy - cy2)) / den
        w1 = ((cy2 - ay) * (gx - cx2) + (ax - cx2) * (gy - cy2)) / den
        w2 = 1.0 - w0 - w1
        m = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not m.any():
            continue

        # 透视正确的 1/z 插值
        invz = np.array([1.0 / max(-P[k, 2], 1e-6) for k in range(3)])
        iz = w0 * invz[0] + w1 * invz[1] + w2 * invz[2]
        zc = 1.0 / np.maximum(iz, 1e-9)

        sub_z = zbuf[y0:y1 + 1, x0:x1 + 1]
        upd = m & (zc < sub_z)
        if not upd.any():
            continue

        # 属性插值（按 1/z 加权）
        U = (w0[..., None] * uv[i0] + w1[..., None] * uv[i1]
             + w2[..., None] * uv[i2])
        # 双线性采样
        fu = np.clip(U[..., 0], 0, 1) * (TW - 1)
        fv = np.clip(U[..., 1], 0, 1) * (TH - 1)
        ix, iy = np.floor(fu).astype(int), np.floor(fv).astype(int)
        ix1, iy1 = np.minimum(ix + 1, TW - 1), np.minimum(iy + 1, TH - 1)
        tx, ty = (fu - ix)[..., None], (fv - iy)[..., None]
        col = (tex[iy, ix] * (1 - tx) * (1 - ty) + tex[iy, ix1] * tx * (1 - ty)
               + tex[iy1, ix] * (1 - tx) * ty + tex[iy1, ix1] * tx * ty)

        Nf = (w0[..., None] * N[0] + w1[..., None] * N[1]
              + w2[..., None] * N[2])
        Nf /= np.maximum(np.linalg.norm(Nf, axis=-1, keepdims=True), 1e-9)
        d1 = np.clip((Nf * L_KEY).sum(-1), 0, 1)
        d2 = np.clip((Nf * L_FILL).sum(-1), 0, 1)
        shade = np.clip((0.52 + 0.78 * d1 + 0.18 * d2) * EXPOSURE, 0, 1.9)
        rgb = np.clip(col * shade[..., None], 0, 255)

        sub_z[upd] = zc[upd]
        cbuf[y0:y1 + 1, x0:x1 + 1][upd] = rgb[upd]
        dbuf[y0:y1 + 1, x0:x1 + 1][upd] = 1.0

    rgba = np.zeros((rh, rw, 4), np.float32)
    rgba[..., :3] = cbuf
    rgba[..., 3] = dbuf * 255
    if ss > 1:
        rgba = np.asarray(Image.fromarray(rgba.astype(np.uint8), "RGBA")
                          .resize((W, H), Image.LANCZOS), np.float32)
    return rgba


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out")
    ap.add_argument("--quality", default="fast")
    args = ap.parse_args()

    d = Path(args.dir)
    if not d.is_absolute():
        d = ROOT / d
    W, H, ss = (560, 680, 1) if args.quality == "fast" else (760, 920, 2)

    objs, labels = [], []
    for kind, name in (("vase", "陶瓶（梅瓶）"), ("box", "包装方盒"),
                       ("fan", "团扇")):
        p = d / f"pattern_{kind}.glb"
        if not p.exists():
            print(f"[跳过] {p} 不存在"); continue
        objs.append(render_glb(p, W=W, H=H, ss=ss,
                               elev_deg={"vase": 12, "box": 16, "fan": 8}[kind]))
        labels.append(name)
    if not objs:
        print("没有可渲染的 GLB"); return 1

    pad, TOP, BOT = 52, 150, 110
    Tw = W * len(objs) + pad * (len(objs) + 1)
    canvas = Image.new("RGB", (Tw, TOP + H + BOT), PAPER)
    dr = ImageDraw.Draw(canvas)
    for i, (arr, lab) in enumerate(zip(objs, labels)):
        x0 = pad + i * (W + pad)
        canvas.paste(Image.fromarray(arr.astype(np.uint8), "RGBA"), (x0, TOP),
                     Image.fromarray(arr.astype(np.uint8), "RGBA"))
        dr.text((x0 + W / 2 - len(lab) * 11, TOP + H + 22), lab, fill=INK)
    dr.text((pad, 52), "GLB 独立自检渲染（从 .glb 字节流重建，不复用预览代码）",
            fill=INK)
    dr.text((pad, 96), "与静态预览比对：两张图应一致 —— 一致才证明导出的 GLB 可用",
            fill=(110, 102, 92))

    out = Path(args.out) if args.out else d / "glb_check_render.png"
    canvas.save(out, "PNG")
    print(f"✅ 独立渲染 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
