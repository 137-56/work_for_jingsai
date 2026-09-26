# scripts/check_render3d.py
"""3D 预览渲染的**法线朝向自检** —— 一个很隐蔽、但必须常跑的门卫。

★ 为什么需要这个脚本
    渲染器里的法线一旦朝向反了，画面**看起来仍然是 3D 的**（明暗关系依旧存在），
    只是**光从错误的一侧来**。肉眼几乎发现不了，尤其在器物形态上。
    本项目的渲染器有两处容易反：
      ① 长方体的面法线（光线方向与法线符号）
      ② 旋转体的外法线（取决于"实体在轴内侧还是下方"——瓶对、盘不对）
    实测就是这样：方盒与赏盘的法线都反了，但渲染图乍看正常。

★ 判据
    对**凸**物体从外部观察，可见点的外法线必然朝向相机：
        dot(法线, 指向相机的向量) > 0
    若该比例很低（例如 <20%），说明法线朝向反了。

用法：
    .venv/Scripts/python.exe scripts/check_render3d.py
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.preview3d as P


def check(kind, W=160, H=200, cam=3.35, fov=26.0, azim=30.0):
    name, builder, elev_def, flip = P.FORMS[kind]
    prof, half, extra = builder()
    d = P._rays(W, H, fov, cam)
    R = P._rot(elev_def, azim); Rt = R.T
    o = np.array([0.0, 0.0, cam], np.float32)
    o_obj = Rt @ o.astype(np.float32)
    d_obj = (d.reshape(-1, 3) @ Rt.T).reshape(H, W, 3)

    if prof is not None:
        cap_b = extra if kind != "plate" else None
        t, n_obj, _ = P._revolve_hit(o_obj, d_obj, prof, cap_bottom=cap_b, cap_top=None)
    else:
        t, n_obj, _ = P._box_hit(o_obj, d_obj, half)
    if flip:
        n_obj = -n_obj

    hit = np.isfinite(t)
    if not hit.any():
        return None
    tf = np.where(hit, t, 0.0)
    p = o[None, None, :] + tf[..., None] * d
    V = o[None, None, :] - p
    V /= np.maximum(np.linalg.norm(V, axis=-1, keepdims=True), 1e-9)
    n_world = (n_obj.reshape(-1, 3) @ R.T).reshape(H, W, 3)
    dot = (n_world * V).sum(-1)[hit]
    return float(dot.mean()), float((dot > 0).mean())


def main():
    print("=" * 62)
    print("3D 渲染 · 法线朝向自检（可见点的 dot(法线, 指向相机) 应为正）")
    print("=" * 62)
    bad = []
    for kind in P.FORMS:
        name = P.FORMS[kind][0]
        r = check(kind)
        if r is None:
            print(f"  {name:<12} ⚠️ 无命中像素，无法判定")
            bad.append(kind)
            continue
        mean, pos = r
        ok = pos >= 0.6                      # 凸体应绝大多数为正
        print(f"  {name:<12} dot 均值 {mean:+.3f}｜朝向占比 {pos*100:5.1f}%"
              + ("   ✅" if ok else "   ❌ 法线朝向反了"))
        if not ok:
            bad.append(kind)

    # NaN 自检（另一个实测踩过的坑：未命中处 t=inf 污染整图，渲成纯黑）
    print("-" * 62)
    print("NaN / 全黑自检（未命中处不得污染命中像素）")
    tex = np.full((64, 64, 3), 200.0, np.float32)
    nan_bad = []
    for kind in P.FORMS:
        a = P.render_form(kind, tex, W=120, H=150, ss=1,
                          use_planar_uv=(kind == "plate"))
        hit = a[..., 3] > 0
        nan = int(np.isnan(a[..., :3]).sum())
        mean = float(a[..., :3][hit].mean()) if hit.any() else 0.0
        ok = nan == 0 and mean > 20
        print(f"  {P.FORMS[kind][0]:<12} NaN {nan:>5}｜命中区均值 {mean:6.1f}"
              + ("   ✅" if ok else "   ❌ 可能被 inf 污染"))
        if not ok:
            nan_bad.append(kind)

    print("=" * 62)
    if bad or nan_bad:
        print(f"[FAIL] 法线问题: {bad or '无'}｜NaN 问题: {nan_bad or '无'}")
        return 1
    print("[PASS] 三形态法线朝向正确，无 NaN 污染")
    return 0


if __name__ == "__main__":
    sys.exit(main())
