# src/glb_export.py
"""把我们的形态导出为标准 **glTF 2.0 二进制（.glb）**，纹样作为贴图嵌入。

★★ 为什么值得做（也是"让 3D 不鸡肋"的关键）
    现在 06 区出的是**静态 PNG**——看得出来是 3D，但不能转、不能看背面、
    不能拖进别的软件。**这才是"鸡肋"的真正来源。**
    导出 GLB 之后：
      · 浏览器里可 **360° 旋转查看**（配一个单文件 Three.js 查看器）
      · 是一个 **可下载、可交付的 3D 资产**（GLB 是业界通用格式，可进 Blender/Unity）
      · **纹样仍然是我们那张可溯源的贴图**，没有被"程序化材质"替换掉

★ 为什么不用 trimesh / pygltflib
    本机没有；而 GLB 格式本身极简（文件头 + JSON 块 + 二进制块），
    纯 Python 手写即可，且**零新依赖、完全确定性**——与本项目的一贯取舍一致。
    （对比：img2threejs 输出的是 TypeScript 代码、且其 code-only 契约
      **明确不复制纹理图像**，那样反而会打断我们的溯源链。）

★ 溯源口径不变
    · 几何：程序化生成的标准形态（非文物三维模型）
    · 贴图：来自 M4a 组合纹样图 → 元素级可溯

用法：
    .venv/Scripts/python.exe -m src.glb_export --recipe outputs/<id>
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# glTF 常量
GLB_MAGIC = 0x46546C67          # 'glTF'
CHUNK_JSON = 0x4E4F534A         # 'JSON'
CHUNK_BIN = 0x004E4942          # 'BIN\0'
FLOAT, UINT, USHORT = 5126, 5125, 5123


# ---------------------------------------------------------------- 网格构造

def mesh_from_profile(prof, seg=72, tile_x=2.0, close_bottom=True):
    """旋转体 → 三角网格。prof 为 (y, r) 数组（y = 高度，r = 半径，绕 Y 轴旋转）。

    返回 (positions, normals, uvs, indices)，均为 numpy 数组。
    """
    y = prof[:, 0]; r = prof[:, 1]
    n = len(prof)
    # 弧长参数化 → v 坐标
    seg_len = np.hypot(np.diff(y), np.diff(r))
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    v_par = cum / max(cum[-1], 1e-9)

    ang = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    ca, sa = np.cos(ang), np.sin(ang)

    pos, nrm, uv = [], [], []
    for i in range(n):
        for j in range(seg):
            pos.append([r[i] * ca[j], y[i], r[i] * sa[j]])
            # 外法线：∇F ∝ (x, -r·b, z)，b = dr/dy（与前向渲染器保持同一约定）
            b = (r[min(i + 1, n - 1)] - r[max(i - 1, 0)]) / max(
                y[min(i + 1, n - 1)] - y[max(i - 1, 0)], 1e-9)
            nv = np.array([ca[j], -r[i] * b, sa[j]], float)
            nv /= max(np.linalg.norm(nv), 1e-9)
            nrm.append(nv.tolist())
            # glTF 的 v 原点在左上，与图片一致；这里让 v=0 对应轮廓起点（底部）
            uv.append([ang[j] / (2 * np.pi) * tile_x, 1.0 - v_par[i]])

    idx = []
    for i in range(n - 1):
        for j in range(seg):
            a = i * seg + j
            b_ = i * seg + (j + 1) % seg
            c = (i + 1) * seg + j
            d = (i + 1) * seg + (j + 1) % seg
            idx += [a, c, b_, b_, c, d]

    pos = np.array(pos, np.float32); nrm = np.array(nrm, np.float32)
    uv = np.array(uv, np.float32)

    if close_bottom and r[0] > 1e-4:
        base = len(pos)
        pos = np.vstack([pos, [[0.0, y[0], 0.0]]])
        nrm = np.vstack([nrm, [[0.0, -1.0, 0.0]]])
        uv = np.vstack([uv, [[0.5, 0.5]]])
        for j in range(seg):
            a = j; b_ = (j + 1) % seg
            idx += [base, b_, a]              # 朝下的底盖
    return pos, nrm, uv, np.array(idx, np.uint32)


def mesh_box(half):
    """长方体 → 三角网格（24 顶点，每面独立 UV，纹样整幅贴到每个面）。"""
    hx, hy, hz = half
    faces = [
        ((0, 0, 1), [(+1, -1, +1), (+1, +1, +1), (-1, +1, +1), (-1, -1, +1)]),   # +Z
        ((0, 0, -1), [(-1, -1, -1), (-1, +1, -1), (+1, +1, -1), (+1, -1, -1)]),  # -Z
        ((1, 0, 0), [(+1, -1, -1), (+1, +1, -1), (+1, +1, +1), (+1, -1, +1)]),   # +X
        ((-1, 0, 0), [(-1, -1, +1), (-1, +1, +1), (-1, +1, -1), (-1, -1, -1)]),  # -X
        ((0, 1, 0), [(-1, +1, +1), (+1, +1, +1), (+1, +1, -1), (-1, +1, -1)]),   # +Y
        ((0, -1, 0), [(-1, -1, -1), (+1, -1, -1), (+1, -1, +1), (-1, -1, +1)]),  # -Y
    ]
    pos, nrm, uv, idx = [], [], [], []
    quad_uv = [(0, 1), (1, 1), (1, 0), (0, 0)]      # 与 glTF 的左上原点一致
    for ni, (n, q) in enumerate(faces):
        b = len(pos)
        for vi, (sx, sy, sz) in enumerate(q):
            pos.append([sx * hx, sy * hy, sz * hz])
            nrm.append(list(n))
            uv.append(list(quad_uv[vi]))
        idx += [b, b + 1, b + 2, b, b + 2, b + 3]
    return (np.array(pos, np.float32), np.array(nrm, np.float32),
            np.array(uv, np.float32), np.array(idx, np.uint32))


# ---------------------------------------------------------------- GLB 写出

def write_glb(pos, nrm, uv, idx, texture_png, out_path, name="pattern-object"):
    """写出 glTF 2.0 二进制。纹样作为 PNG 嵌入 BIN 块（自包含，可离线打开）。"""
    tex_bytes = Path(texture_png).read_bytes()
    if not tex_bytes.startswith(b"\x89PNG"):
        # glTF 内置图片支持 png/jpeg；非 PNG 就先转一下
        import io
        buf = io.BytesIO()
        Image.open(texture_png).convert("RGB").save(buf, "PNG")
        tex_bytes = buf.getvalue()

    def pack(arr, fmt, target=None):
        a = np.ascontiguousarray(arr)
        if target is not None:
            a = a.astype(target)
        return a.tobytes()

    blobs, views, accessors = [], [], []

    def add_view(data, target=None, pad=4):
        off = sum(len(b) for b in blobs)
        blobs.append(data)
        # 4 字节对齐（glTF 要求）
        pad_n = (-len(data)) % pad
        if pad_n:
            blobs.append(b"\x00" * pad_n)
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data),
                      **({"target": target} if target else {})})
        return len(views) - 1

    def add_accessor(view, comp_type, count, type_, **extra):
        accessors.append({"bufferView": view, "componentType": comp_type,
                          "count": int(count), "type": type_, **extra})
        return len(accessors) - 1

    # POSITION 需要 min/max（glTF 规范要求）
    pmin = np.asarray(pos).min(0).tolist(); pmax = np.asarray(pos).max(0).tolist()
    v_pos = add_view(pack(pos, "f", np.float32), 34962)
    a_pos = add_accessor(v_pos, FLOAT, len(pos), "VEC3", min=pmin, max=pmax)
    v_nrm = add_view(pack(nrm, "f", np.float32), 34962)
    a_nrm = add_accessor(v_nrm, FLOAT, len(nrm), "VEC3")
    v_uv = add_view(pack(uv, "f", np.float32), 34962)
    a_uv = add_accessor(v_uv, FLOAT, len(uv), "VEC2")
    # 索引：顶点数 < 65536 可用 ushort，省一半体积
    if len(pos) < 65536:
        idx_data = np.asarray(idx).astype(np.uint16).tobytes()
        idx_ctype = USHORT
    else:
        idx_data = np.asarray(idx).astype(np.uint32).tobytes()
        idx_ctype = UINT
    v_idx = add_view(idx_data, 34963)
    a_idx = add_accessor(v_idx, idx_ctype, len(idx), "SCALAR")
    v_img = add_view(tex_bytes)

    gltf = {
        "asset": {"version": "2.0", "generator": "纹初迹现 · 组合纹样 3D 导出"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": name}],
        "meshes": [{
            "name": name,
            "primitives": [{
                "attributes": {"POSITION": a_pos, "NORMAL": a_nrm, "TEXCOORD_0": a_uv},
                "indices": a_idx, "material": 0, "mode": 4,
            }],
        }],
        "materials": [{
            "name": "pattern",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0.0, "roughnessFactor": 0.55,
            },
            "doubleSided": False,
        }],
        "textures": [{"source": 0, "sampler": 0}],
        "images": [{"bufferView": v_img, "mimeType": "image/png"}],
        # 纹样要环绕重复，所以 x 方向用 REPEAT
        "samplers": [{"magFilter": 9729, "minFilter": 9987,
                      "wrapS": 10497, "wrapT": 33071}],
        "bufferViews": views,
        "accessors": accessors,
        "buffers": [{"byteLength": sum(len(b) for b in blobs)}],
    }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((-len(json_bytes)) % 4)          # JSON 块也须 4 字节对齐
    bin_bytes = b"".join(blobs)

    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    out = bytearray()
    out += struct.pack("<III", GLB_MAGIC, 2, total)
    out += struct.pack("<II", len(json_bytes), CHUNK_JSON) + json_bytes
    out += struct.pack("<II", len(bin_bytes), CHUNK_BIN) + bin_bytes

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(out))
    return {"path": str(out_path), "bytes": total,
            "vertices": int(len(pos)), "triangles": int(len(idx) // 3)}


def read_glb_info(path):
    """回读 GLB 做结构校验（确保写出来的文件是合法可解析的）。"""
    b = Path(path).read_bytes()
    magic, ver, total = struct.unpack_from("<III", b, 0)
    assert magic == GLB_MAGIC, "magic 不对"
    off, chunks = 12, {}
    while off < total:
        clen, ctype = struct.unpack_from("<II", b, off)
        chunks[ctype] = b[off + 8: off + 8 + clen]
        off += 8 + clen
    j = json.loads(chunks[CHUNK_JSON].decode("utf-8"))
    bin_len = len(chunks.get(CHUNK_BIN, b""))
    return {
        "version": ver, "declared_total": total, "actual_total": len(b),
        "json_ok": True, "bin_bytes": bin_len,
        "buffer_declared": j["buffers"][0]["byteLength"],
        "views": len(j["bufferViews"]), "accessors": len(j["accessors"]),
        "vertices": j["accessors"][0]["count"],
        "indices": j["accessors"][3]["count"],
        "has_image": bool(j["images"]) and j["images"][0].get("mimeType"),
        "image_bytes": j["bufferViews"][j["images"][0]["bufferView"]]["byteLength"],
        "basecolor_texture": j["materials"][0]["pbrMetallicRoughness"]
                              .get("baseColorTexture", {}).get("index"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", help="输出目录（含 composed_pattern.png）")
    ap.add_argument("--pattern", help="直接指定纹样图")
    args = ap.parse_args()

    from src.preview3d import FORMS, _normalize  # 复用同一套形态定义

    if args.recipe:
        rd = Path(args.recipe)
        if not rd.is_absolute():
            rd = ROOT / rd
        pat = rd / "composed_pattern.png"
        out_dir = rd
    elif args.pattern:
        pat = Path(args.pattern); out_dir = ROOT / "outputs" / "glb"
    else:
        ap.print_help(); return 1

    print(f"纹样贴图：{pat}")
    made = []
    for kind in ("vase", "box", "plate"):
        name, builder, elev, flip = FORMS[kind]
        prof, half, extra = builder()
        if prof is not None:
            pos, nrm, uv, idx = mesh_from_profile(prof, seg=72, tile_x=2.0)
        else:
            pos, nrm, uv, idx = mesh_box(half)
        info = write_glb(pos, nrm, uv, idx, pat, out_dir / f"pattern_{kind}.glb",
                         name=f"pattern-{kind}")
        chk = read_glb_info(info["path"])
        ok = (chk["json_ok"] and chk["actual_total"] == chk["declared_total"]
              and chk["buffer_declared"] == chk["bin_bytes"]
              and chk["has_image"] and chk["basecolor_texture"] == 0)
        made.append((kind, info, chk, ok))
        print(f"  {'✅' if ok else '❌'} {name:<10} {info['bytes']/1024:6.0f} KB  "
              f"顶点 {info['vertices']:>6}  三角 {info['triangles']:>6}  "
              f"贴图 {chk['image_bytes']/1024:.0f} KB  校验{'通过' if ok else '失败'}")
    print(f"\n共 {sum(1 for _,_,_,o in made if o)}/{len(made)} 个 GLB 通过结构校验")
    return 0 if all(o for _, _, _, o in made) else 1


if __name__ == "__main__":
    sys.exit(main())
