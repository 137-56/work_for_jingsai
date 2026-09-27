# scripts/check_glb_uv.py
"""GLB 自检：把 GLB 里的顶点/UV 独立解出来，验证 UV 落在**应该**的区域。

★★ 为什么必须自检（实测教训）
    GLB 是二进制，"看起来导出成功"完全不代表 UV 对。
    已知会错的两种方式，肉眼都看不出来：
      ① 顶点全采到 atlas 空白区 → 渲染成一块白板
         （方盒顶盖曾因为把盖图宽度当成 0.5、实际只有 0.217，真踩到）
      ② UV 越界 [0,1] → 采样溢出到 atlas 另一半（串色）

    这个脚本**不复用导出代码**，而是从 .glb 字节里重新解析
    accessor / bufferView，独立算一遍 UV 的统计量，与预期比对。

用法：
    .venv/Scripts/python.exe scripts/check_glb_uv.py --dir outputs/<id>
"""
from __future__ import annotations

import argparse
import io
import json
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

CT = {5126: ("f", 4), 5125: ("I", 4), 5123: ("H", 2), 5121: ("B", 1)}
NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def load_glb(path):
    """解析 GLB，返回 (gltf_dict, bin_bytes)。"""
    b = Path(path).read_bytes()
    magic, ver, total = struct.unpack_from("<III", b, 0)
    if magic != GLB_MAGIC:
        raise ValueError(f"{path}: magic 不是 glTF")
    if total != len(b):
        raise ValueError(f"{path}: 声明长度 {total} != 实际 {len(b)}")
    off, chunks = 12, {}
    while off < total:
        clen, ctype = struct.unpack_from("<II", b, off)
        chunks[ctype] = b[off + 8: off + 8 + clen]
        off += 8 + clen
    j = json.loads(chunks[CHUNK_JSON].decode("utf-8"))
    return j, chunks.get(CHUNK_BIN, b"")


def read_accessor(j, bin_bytes, idx):
    """把 accessor 解成 numpy 数组 —— 完全按规范从 bufferView 算偏移。"""
    a = j["accessors"][idx]
    bv = j["bufferViews"][a["bufferView"]]
    fmt, size = CT[a["componentType"]]
    n = NC[a["type"]]
    stride = bv.get("byteStride") or size * n
    base = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    count = a["count"]
    out = np.empty((count, n) if n > 1 else count, dtype=np.float32)
    for i in range(count):
        vals = struct.unpack_from("<" + fmt * n, bin_bytes, base + i * stride)
        out[i] = vals if n > 1 else vals[0]
    return out


def texture_pixel_stats(j, bin_bytes):
    """解出内嵌 PNG，返回 (尺寸, 非空白像素占比的粗估计)。"""
    img = j["images"][0]
    bv = j["bufferViews"][img["bufferView"]]
    off = bv.get("byteOffset", 0)
    data = bin_bytes[off: off + bv["byteLength"]]
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    arr = np.asarray(im, np.int16)
    # "空白" = 接近 atlas 的填充底色 (247,241,230)
    blank = (np.abs(arr - np.array([247, 241, 230])).sum(-1) < 30)
    return im.size, 1.0 - float(blank.mean())


def check_one(path, expect_kind):
    j, bin_bytes = load_glb(path)
    prim = j["meshes"][0]["primitives"][0]
    pos = read_accessor(j, bin_bytes, prim["attributes"]["POSITION"])
    uv = read_accessor(j, bin_bytes, prim["attributes"]["TEXCOORD_0"])
    idx = read_accessor(j, bin_bytes, prim["indices"])

    problems = []
    # ① 顶点数 / 索引数一致
    if len(pos) != len(uv):
        problems.append(f"顶点 {len(pos)} 与 UV {len(uv)} 数量不符")
    # ② UV 越界
    if uv.min() < -1e-5 or uv.max() > 1 + 1e-5:
        problems.append(f"UV 越界：[{uv.min():.4f}, {uv.max():.4f}]")
    # ③ 索引越界
    if idx.size and (idx.max() >= len(pos) or idx.min() < 0):
        problems.append(f"索引越界：max={idx.max()} 顶点数={len(pos)}")
    # ④ 索引能凑成三角
    if idx.size % 3:
        problems.append(f"索引数 {idx.size} 不是 3 的倍数")

    tex_size, fill = texture_pixel_stats(j, bin_bytes)
    if fill < 0.35:
        problems.append(f"贴图非空白像素只有 {fill:.0%}（疑似大面积填充底）")

    return {
        "kind": expect_kind, "verts": len(pos), "tris": int(idx.size // 3),
        "uv_min": uv.min(0).tolist(), "uv_max": uv.max(0).tolist(),
        "tex": tex_size, "fill": fill,
        "raw_bytes": Path(path).stat().st_size,
        "problems": problems,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="含 pattern_*.glb 的目录")
    args = ap.parse_args()

    d = Path(args.dir)
    if not d.is_absolute():
        d = ROOT / d
    ok_all = True
    print(f"GLB 独立自检：{d}\n")
    for kind in ("vase", "box", "fan"):
        p = d / f"pattern_{kind}.glb"
        if not p.exists():
            print(f"  ❌ {kind:<6} 文件不存在：{p}"); ok_all = False; continue
        r = check_one(p, kind)
        mark = "✅" if not r["problems"] else "❌"
        print(f"  {mark} {kind:<6} 顶点 {r['verts']:>6}  三角 {r['tris']:>6}  "
              f"UV u[{r['uv_min'][0]:.3f},{r['uv_max'][0]:.3f}] "
              f"v[{r['uv_min'][1]:.3f},{r['uv_max'][1]:.3f}]  "
              f"贴图 {r['tex'][0]}×{r['tex'][1]}（有效 {r['fill']:.0%}）")
        for q in r["problems"]:
            print(f"        · {q}")
        ok_all = ok_all and not r["problems"]
    print(f"\n{'全部通过' if ok_all else '存在问题'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
