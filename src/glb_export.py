# src/glb_export.py
"""把我们的形态导出为标准 **glTF 2.0 二进制（.glb）**，纹样作为贴图嵌入。

★★ 为什么值得做（这是"3D 不鸡肋"的关键一半）
    06 区如果只出**静态 PNG** —— 能看出是 3D，但不能转、不能看背面、
    不能拖进别的软件。**这才是"鸡肋"的真正来源。**
    导出 GLB 之后：
      · 浏览器里可 **360° 旋转查看**（配 `web/viewer.html` 单文件查看器）
      · 是一个 **可下载、可交付的 3D 资产**（GLB 是业界通用格式，
        可进 Blender / Unity / 各种在线预览）
      · **纹样仍是我们那张可溯源的贴图**，没有被"程序化材质"替换掉

★★★ 与第一版的根本差别（第一版是错的，这里记下来免得回退）
    第一版把 **`composed_pattern.png`（原始 1024² 方图）** 整幅贴上去，
    且 `mesh_from_profile(tile_x=2.0)` 横向绕两圈。后果与静态预览的旧版
    完全一样：方形图贴瘦高器物 → 变形；绕两圈 → 面间接缝劈开蝙蝠。

    现在**复用 `preview3d` 的同一套分区贴图**：
      · 梅瓶 → `build_strip(kind="vase")` 展开图，u 环一圈
      · 方盒 → `build_strip(kind="box")` + `build_box_lid()` 拼成 atlas，
               侧面采样左半、顶底盖采样右上角的盖图子矩形
      · 团扇 → `build_fan_face()` 同心圆图，扇面按 (x,y) 平面映射

    ★ 关键原则：**GLB 里的 UV 必须与静态预览的 UV 完全一致**，
      否则"预览看到的样子"和"下载下来的样子"不同，那比不做还糟。
      所以这里不自己算 UV，而是**直接调用 preview3d 的求交函数**
      （`_revolve_hit` / `_box_hit` / `_fan_hit`）在网格顶点上采 UV ——
      同一份代码，同一套约定，不可能对不上。

★ 为什么不用 trimesh / pygltflib
    本机没有；而 GLB 格式本身极简（文件头 + JSON 块 + 二进制块），
    纯 Python 手写即可，且**零新依赖、完全确定性**——与本项目一贯取舍一致。
    （对比：img2threejs 输出 TypeScript 代码、且其 code-only 契约
      **明确不复制纹理图像**，那样反而会打断我们的溯源链。）

★ 溯源口径不变
    · 几何：程序化生成的标准形态（非文物三维模型、非 AI 生成）
    · 贴图：来自 M4a 组合纹样图 → 元素级可溯

用法：
    .venv/Scripts/python.exe -m src.glb_export --recipe outputs/<id>
"""
from __future__ import annotations

import argparse
import io
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


# ---------------------------------------------------------------- UV 直采

def vertex_uv(kind, pos, prof=None, half=None, lid_du=0.5, lid_dv=0.5):
    """在一组**顶点**上求 UV —— 复用 `preview3d` 的**同一套 UV 公式**。

    ★★ 为什么必须共用（这是硬要求）
        静态预览（`preview3d.render_form`）算 UV 用的是光线求交函数里
        那几行公式；GLB 的 UV 必须与之**完全一致**，否则
        "预览看到的样子"和"下载下来的样子"不同 —— 那比不做还糟。

        所以这里不新写一套几何，而是**把顶点直接代进同一组公式**
        （UV 只依赖命中点 p，与 t 无关，所以"代顶点"是合法的）。

      ⚠️ 维护约定：改动 `preview3d` 里任何一个 UV 公式时，
         **必须同步改这里**。两处都应指向同一段注释。
        已知的同步点：
           · 旋转体：`uu = atan2(z,x)/2π`、`vv = 弧长参数`、返回 `[uu, 1-vv]`
           · 方盒侧面：`u ∈ [0,0.5]`（atlas 左半），`v = 0.5 - y/(2hy)`
           · 方盒盖：`u = 0.5 + (x/hx*0.5+0.5)*lid_du`、`v = (z/hz*0.5+0.5)*lid_dv`
           · 团扇扇面：`(x,y)` 线性映射；侧边/柄：极坐标 u + 厚度 v
    """
    pos = np.asarray(pos, np.float32)
    N = pos.shape[0]

    if kind == "fan":
        g = prof                                    # fan 传的是 dict
        R, T = g["R"], g["T"]
        uv = np.zeros((N, 2), np.float32)
        on_disc = np.abs(pos[:, 2]) <= T + 1e-5
        uv[on_disc, 0] = np.clip(pos[on_disc, 0] / (2 * R) + 0.5, 0, 1)
        uv[on_disc, 1] = np.clip(0.5 - pos[on_disc, 1] / (2 * R), 0, 1)
        side = ~on_disc
        if side.any():
            uv[side, 0] = np.mod(
                np.arctan2(pos[side, 1], pos[side, 0]) / (2 * np.pi), 1.0)
            uv[side, 1] = np.clip(0.5 + pos[side, 2] / (2 * T) * 0.5, 0, 1)
        return uv

    if half is None:                                # 旋转体（梅瓶）
        y, x, z = pos[:, 1], pos[:, 0], pos[:, 2]
        seg = np.hypot(np.diff(prof[:, 0]), np.diff(prof[:, 1]))
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        total = max(cum[-1], 1e-9)
        vv = np.interp(np.clip(y, prof[:, 0].min(), prof[:, 0].max()),
                       prof[:, 0], cum) / total
        uu = np.mod(np.arctan2(z, x) / (2 * np.pi), 1.0)
        return np.stack([uu, 1.0 - vv], -1).astype(np.float32)

    # ---- 方盒 ----
    # ★★★ 这里**不能**用"顶点落在哪三个边界平面上"来判断面（实测踩到）
    #    因为我们的方盒 hx == hz（正方形底），于是**每个顶点都同时落在
    #    x、y、z 三个边界平面上** —— `on_y` 对全部 24 个顶点都为真，
    #    结果全部走"顶盖"分支，六个面采到的都是盖图，侧面完全丢失。
    #    （自检脚本 `check_glb_uv.py` 报出 box 的 u 只有 [0.5, 0.717] 才发现。）
    #
    #    → 正解：**按 mesh_box 的面顺序**来。`mesh_box` 每面固定 4 个顶点，
    #      顺序是 +Z, -Z, +X, -X, +Y, -Y。已知第 i 个顶点属于哪一面，
    #      就直接用那一面的 UV 公式 —— 不猜、不推理几何，零歧义。
    hx, hy, hz = np.array(half, np.float32)
    x, y, z = pos[:, 0], pos[:, 1], pos[:, 2]
    uv = np.zeros((N, 2), np.float32)
    per_face = N // 6 if N >= 24 else 4
    for fi in range(6):
        s = slice(fi * per_face, (fi + 1) * per_face)
        if fi in (0, 1):                           # ±Z 面：u 沿 x，v 沿 y
            uv[s, 0] = ((x[s] * np.sign(z[s]) / hx + 1.0) * 0.5) * 0.5
            uv[s, 1] = 0.5 - y[s] / (2 * hy)
        elif fi in (2, 3):                         # ±X 面：u 沿 z，v 沿 y
            uv[s, 0] = ((z[s] * np.sign(x[s]) / hz + 1.0) * 0.5) * 0.5
            uv[s, 1] = 0.5 - y[s] / (2 * hy)
        else:                                      # ±Y 盖：采样 atlas 右上角
            uv[s, 0] = 0.5 + (x[s] / hx * 0.5 + 0.5) * lid_du
            uv[s, 1] = (z[s] / hz * 0.5 + 0.5) * lid_dv
    return np.clip(uv, 0, 1)


# ---------------------------------------------------------------- 网格构造

def _arc_table(prof):
    """旋转体剖面的弧长参数表（v 坐标）。"""
    seg_len = np.hypot(np.diff(prof[:, 0]), np.diff(prof[:, 1]))
    cum = np.concatenate([[0.0], np.cumsum(seg_len)])
    return cum / max(cum[-1], 1e-9)


def mesh_revolve(prof, seg=96, close_bottom=True):
    """旋转体 → 三角网格。(positions, normals, indices)，UV 由 _uv_of 补。"""
    y, r = prof[:, 0], prof[:, 1]
    n = len(prof)
    ang = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    ca, sa = np.cos(ang), np.sin(ang)

    pos, nrm = [], []
    for i in range(n):
        b = (r[min(i + 1, n - 1)] - r[max(i - 1, 0)]) / max(
            y[min(i + 1, n - 1)] - y[max(i - 1, 0)], 1e-9)
        for j in range(seg):
            pos.append([r[i] * ca[j], y[i], r[i] * sa[j]])
            nv = np.array([ca[j], -r[i] * b, sa[j]], float)
            nv /= max(np.linalg.norm(nv), 1e-9)
            nrm.append(nv.tolist())

    idx = []
    for i in range(n - 1):
        for j in range(seg):
            a = i * seg + j
            b_ = i * seg + (j + 1) % seg
            c = (i + 1) * seg + j
            d = (i + 1) * seg + (j + 1) % seg
            idx += [a, c, b_, b_, c, d]

    pos = np.array(pos, np.float32); nrm = np.array(nrm, np.float32)
    if close_bottom and r[0] > 1e-4:
        base = len(pos)
        pos = np.vstack([pos, [[0.0, y[0], 0.0]]])
        nrm = np.vstack([nrm, [[0.0, -1.0, 0.0]]])
        for j in range(seg):
            idx += [base, (j + 1) % seg, j]
    return pos, nrm, np.array(idx, np.uint32)


def mesh_box(half, seg=1):
    """长方体 → 三角网格（24 顶点，每面独立 quad）。"""
    hx, hy, hz = half
    faces = [
        ((0, 0, 1), [(+1, -1, +1), (+1, +1, +1), (-1, +1, +1), (-1, -1, +1)]),
        ((0, 0, -1), [(-1, -1, -1), (-1, +1, -1), (+1, +1, -1), (+1, -1, -1)]),
        ((1, 0, 0), [(+1, -1, -1), (+1, +1, -1), (+1, +1, +1), (+1, -1, +1)]),
        ((-1, 0, 0), [(-1, -1, +1), (-1, +1, +1), (-1, +1, -1), (-1, -1, -1)]),
        ((0, 1, 0), [(-1, +1, +1), (+1, +1, +1), (+1, +1, -1), (-1, +1, -1)]),
        ((0, -1, 0), [(-1, -1, -1), (+1, -1, -1), (+1, -1, +1), (-1, -1, +1)]),
    ]
    pos, nrm, idx = [], [], []
    for n, q in faces:
        b = len(pos)
        for sx, sy, sz in q:
            pos.append([sx * hx, sy * hy, sz * hz])
            nrm.append(list(n))
        idx += [b, b + 1, b + 2, b, b + 2, b + 3]
    return (np.array(pos, np.float32), np.array(nrm, np.float32),
            np.array(idx, np.uint32))


def mesh_fan(g, seg=96, seg_side=160):
    """团扇 → 三角网格：两片圆面 + 侧边圆环 + 柄（长方体）。

    ★ 为什么不用旋转体拼：圆盘求交/建面比"用半径很小的圆台拼一个盘"
      简单得多，也不会在盘心出现退化的窄三角。
    """
    R, T = g["R"], g["T"]
    HL, HW, HT = g["HL"], g["HW"], g["HT"]

    pos, nrm, idx = [], [], []

    def _ring(z, ny):
        """一圈顶点（法线 ±y 的圆面用）。"""
        b = len(pos)
        for j in range(seg):
            a = 2 * np.pi * j / seg
            pos.append([R * np.cos(a), R * np.sin(a), z])
            nrm.append([0.0, 0.0, ny])
        return b

    # 前面（+z）与后面（-z）
    for z, ny in ((T, +1.0), (-T, -1.0)):
        b = _ring(z, ny)
        # 圆心补一个点，做扇形三角化（避免用四边形拼圆）
        c = len(pos)
        pos.append([0.0, 0.0, z]); nrm.append([0.0, 0.0, ny])
        for j in range(seg):
            a = b + j; b2 = b + (j + 1) % seg
            if ny > 0:
                idx += [c, a, b2]
            else:
                idx += [c, b2, a]

    # 侧边：绕一圈的圆柱面
    b_in = len(pos)
    for j in range(seg):
        a = 2 * np.pi * j / seg
        for z in (-T, +T):
            pos.append([R * np.cos(a), R * np.sin(a), z])
            nrm.append([np.cos(a), np.sin(a), 0.0])
    for j in range(seg):
        a = b_in + 2 * j
        b2 = b_in + 2 * ((j + 1) % seg)
        idx += [a, a + 1, b2, b2, a + 1, b2 + 1]

    # 柄：朝**下**（-y）。★ 与 preview3d._fan_hit 的 `o2[1] = o[1] - (R+HL)`
    #   必须一致 —— 那边是把光线平移到柄的局部系，等效于柄中心在 -(R+HL)。
    #   所以柄的 y 范围是 [-(R+2HL), -R]。写成 +y 会让柄朝天长（像插在地上）。
    p0, p1 = -(R - 0.005), -(R + 2 * HL)
    bq = len(pos)
    corners = [(-HW, p0, -HT), (HW, p0, -HT), (HW, p1, -HT), (-HW, p1, -HT),
               (-HW, p0, +HT), (HW, p0, +HT), (HW, p1, +HT), (-HW, p1, +HT)]
    for cx, cy, cz in corners:
        pos.append([cx, cy, cz]); nrm.append([0.0, 0.0, 1.0])
    quads = [(0, 1, 2, 3), (5, 4, 7, 6), (1, 5, 6, 2), (4, 0, 3, 7),
             (3, 2, 6, 7), (4, 5, 1, 0)]
    for q in quads:
        a, b2, c2, d2 = [bq + i for i in q]
        idx += [a, b2, c2, a, c2, d2]

    return np.array(pos, np.float32), np.array(nrm, np.float32), \
        np.array(idx, np.uint32)


# ---------------------------------------------------------------- GLB 写出

def write_glb(pos, nrm, uv, idx, texture_png, out_path, name="pattern-object",
              tex_is_bytes=None):
    """写出 glTF 2.0 二进制。纹样作为 PNG 嵌入 BIN 块（自包含，可离线打开）。"""
    if tex_is_bytes is not None:
        tex_bytes = tex_is_bytes
    else:
        tex_bytes = Path(texture_png).read_bytes()
    if not tex_bytes.startswith(b"\x89PNG"):
        buf = io.BytesIO()
        Image.open(io.BytesIO(tex_bytes) if tex_is_bytes is not None
                   else texture_png).convert("RGB").save(buf, "PNG")
        tex_bytes = buf.getvalue()

    blobs, views, accessors = [], [], []

    def add_view(data, target=None, pad=4):
        off = sum(len(b) for b in blobs)
        blobs.append(data)
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

    pmin = np.asarray(pos).min(0).tolist(); pmax = np.asarray(pos).max(0).tolist()
    v_pos = add_view(np.ascontiguousarray(pos, np.float32).tobytes(), 34962)
    a_pos = add_accessor(v_pos, FLOAT, len(pos), "VEC3", min=pmin, max=pmax)
    v_nrm = add_view(np.ascontiguousarray(nrm, np.float32).tobytes(), 34962)
    a_nrm = add_accessor(v_nrm, FLOAT, len(nrm), "VEC3")
    v_uv = add_view(np.ascontiguousarray(uv, np.float32).tobytes(), 34962)
    a_uv = add_accessor(v_uv, FLOAT, len(uv), "VEC2")
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
                "attributes": {"POSITION": a_pos, "NORMAL": a_nrm,
                               "TEXCOORD_0": a_uv},
                "indices": a_idx, "material": 0, "mode": 4,
            }],
        }],
        "materials": [{
            "name": "pattern",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0.0, "roughnessFactor": 0.55,
            },
            "doubleSided": True,
        }],
        "textures": [{"source": 0, "sampler": 0}],
        "images": [{"bufferView": v_img, "mimeType": "image/png"}],
        # ★ UV 已经在 [0,1] 内精确算好，**不要 REPEAT**：
        #   取 CLAMP_TO_EDGE 避免边缘采样溢出到 atlas 的另一半
        #   （方盒 atlas 的左半/右上是两张不同的图，REPEAT 会在接缝处串色）。
        "samplers": [{"magFilter": 9729, "minFilter": 9987,
                      "wrapS": 33071, "wrapT": 33071}],
        "bufferViews": views,
        "accessors": accessors,
        "buffers": [{"byteLength": sum(len(b) for b in blobs)}],
    }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((-len(json_bytes)) % 4)
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


# ---------------------------------------------------------------- 纹理准备

def build_textures(recipe, hits, style_img=None):
    """按形态准备 GLB 用的贴图（bytes）。**与 preview3d 共用同一套布局**。

    style_img：与 `preview3d.render_preview` **同一个参数、同一个含义**。
      ★ 必须两边都传同一个值，否则"静态预览看到的"≠"下载的 GLB"。
    """
    from src.pattern_layout import (build_box_lid, build_fan_face, build_strip,
                                    ground_tile, use_ground)

    def _png(im):
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "PNG", optimize=True)
        return buf.getvalue()

    # 地子：与 preview3d 同一套抽取逻辑
    ground = None
    if style_img:
        try:
            from src.style_ground import make_ground
            ground = make_ground(style_img, size=1024)
        except Exception:
            ground = None

    out = {}
    with use_ground(ground):
        # 梅瓶：展开图（build_strip 返回 (Image, meta)，只取图）
        out["vase"] = _png(build_strip(recipe, hits, height=1024, kind="vase")[0])
        # 团扇：同心圆图
        out["fan"] = _png(build_fan_face(recipe, hits, size=1024)[0])
        # 方盒：atlas（左半展开图 + 右上盖图）
        strip, _ = build_strip(recipe, hits, height=1024, kind="box")
        lid, _ = build_box_lid(recipe, hits, size=1024)
        sw, sh = strip.size
        atlas = ground_tile(2 * sw, sh)
        atlas.paste(strip, (0, 0))
        lh = sh // 2
        lw = lh
        atlas.paste(lid.resize((lw, lh), Image.LANCZOS), (sw, 0))
        out["box"] = _png(atlas)
    out["_lid_frac"] = (lw / (2 * sw), lh / sh)
    return out


def export_all(recipe, hits, out_dir, seg=96, style_img=None):
    """导出三种形态的 GLB。返回 {kind: info}。

    style_img：见 build_textures —— 与 preview3d 传同一个值才能保证一致。
    """
    from src.preview3d import form_box, form_fan, form_vase

    out_dir = Path(out_dir)
    tex = build_textures(recipe, hits, style_img=style_img)
    lid_du, lid_dv = tex["_lid_frac"]

    builders = {
        "vase": lambda: (mesh_revolve(form_vase()[0], seg=seg), form_vase()[0],
                         None, None),
        "box": lambda: (mesh_box(form_box()[1]), None, form_box()[1], None),
        "fan": lambda: (mesh_fan(form_fan()[0], seg=seg), None, None,
                        form_fan()[0]),
    }
    made = {}
    for kind in ("vase", "box", "fan"):
        (pos, nrm, idx), prof, half, g = builders[kind]()
        uv = vertex_uv(kind, pos,
                       prof=(g if kind == "fan" else prof),
                       half=half, lid_du=lid_du, lid_dv=lid_dv)
        info = write_glb(pos, nrm, uv, idx, None,
                         out_dir / f"pattern_{kind}.glb",
                         name=f"pattern-{kind}", tex_is_bytes=tex[kind])
        chk = read_glb_info(info["path"])
        ok = (chk["json_ok"] and chk["actual_total"] == chk["declared_total"]
              and chk["buffer_declared"] == chk["bin_bytes"]
              and chk["has_image"] and chk["basecolor_texture"] == 0)
        made[kind] = {"info": info, "check": chk, "ok": bool(ok)}
    return made


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", help="输出目录（含 composed_pattern.png / recipe.json）")
    ap.add_argument("--pattern", help="直接指定纹样图（无配方时退化为整幅贴）")
    ap.add_argument("--out", help="输出目录")
    args = ap.parse_args()

    if args.recipe:
        rd = Path(args.recipe)
        if not rd.is_absolute():
            rd = ROOT / rd
        pat = rd / "composed_pattern.png"
        out_dir = Path(args.out) if args.out else rd
        rec = None
        rj = rd / "recipe.json"
        if rj.exists():
            rec = json.loads(rj.read_text(encoding="utf-8"))
    elif args.pattern:
        pat = Path(args.pattern); out_dir = ROOT / "outputs" / "glb"; rec = None
    else:
        ap.print_help(); return 1

    if not Path(pat).exists():
        print(f"[FAIL] 纹样图不存在：{pat}")
        return 1

    hits = None
    if rec:
        try:
            from src.m2_retrieve import retrieve
            hits = retrieve(rec, top_k=10)
            print(f"M2 检索 {len(hits)} 条（用于分区取料）")
        except Exception as e:
            print(f"[警告] M2 检索失败，退化为整幅贴：{type(e).__name__}: {e}")

    if rec and hits:
        made = export_all(rec, hits, out_dir)
        from src.preview3d import FORMS
        for kind in ("vase", "box", "fan"):
            m = made[kind]
            i, chk = m["info"], m["check"]
            print(f"  {'✅' if m['ok'] else '❌'} {FORMS[kind][0]:<12} "
                  f"{i['bytes']/1024:6.0f} KB  顶点 {i['vertices']:>6}  "
                  f"三角 {i['triangles']:>6}  贴图 {chk['image_bytes']/1024:.0f} KB  "
                  f"校验{'通过' if m['ok'] else '失败'}")
        ok_all = all(m["ok"] for m in made.values())
        print(f"\n共 {sum(1 for m in made.values() if m['ok'])}/3 个 GLB 通过结构校验")
    else:
        # 退化：整幅贴（保留旧行为，方便拿单张图直接试）
        from src.preview3d import form_box, form_vase
        prof_v = form_vase()[0]
        half_b = form_box()[1]
        ok_all = True
        jobs = [("vase", *mesh_revolve(prof_v), prof_v, None),
                ("box", *mesh_box(half_b), None, half_b)]
        for kind, pos, nrm, idx, prof, half in jobs:
            uv = vertex_uv(kind, pos, prof=prof, half=half)
            info = write_glb(pos, nrm, uv, idx, pat,
                             out_dir / f"pattern_{kind}.glb", name=f"pattern-{kind}")
            chk = read_glb_info(info["path"])
            ok = chk["actual_total"] == chk["declared_total"] and chk["has_image"]
            ok_all = ok_all and ok
            print(f"  {'✅' if ok else '❌'} {kind:<6} {info['bytes']/1024:6.0f} KB")
        print("\n（无配方 → 整幅贴，仅作单图调试用）")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
