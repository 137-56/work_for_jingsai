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

★★ 「有效率」到底量的是哪块面积（2026-10 修，必须看这段）

    最初这一项是**整张 atlas** 的空白像素占比。方盒因此常年虚高报忧：
    方盒 atlas = 2356×1024，左半是侧面展开图（1178×1024），
    右上角贴 512×512 的盖图，**剩下 39% 的面积根本没有 UV 采样到**
    （右半的 666×512 与 1178×512 两块是纯填充底）。
    实测：atlas 空白 56% 里，有 **39 个百分点来自这块"死区"**，
    跟纹样贴得好不好毫无关系 —— 于是"整图有效率"永远上不了 61%，
    阈值也就只能定在很低的 35%，方盒主画面真留白一大片时（44%）照样放行，
    自检形同虚设。

    所以改成按 **UV 实际采样到的面积** 算：
      把每个三角的 UV 光栅化成掩膜，只在掩膜内统计空白比例。
    这正是本脚本开头写的目的（① "顶点全采到 atlas 空白区 → 渲染成一块白板"）——
    没被采样的像素就算全白，画面也不会白，不该算进分母。

    ★ 两个数都打印：`采样区` 是判据，`全图` 保留以便观察 atlas 打包效率。
      两者差距大 = atlas 里有大片死区（打包不经济，但不影响画面）。

★ 阈值按形态给（0.35 这个统一阈值对宽扁的方盒没有约束力）

    | kind | 阈值 | 理由 |
    |---|---|---|
    | box  | 0.80 | ★ 正向理由（见下）——主画面必须满幅，允许的偏差只有弦纹占位
    |      |      | 实测：主画面 n=1（左右各留白 41%）→ 0.72；n=2（铺满）→ 0.86
    | vase | 0.35 | 展开图本身就是画面区，正常 96%；留 0.35 只拦"整块糊白"的硬故障
    | fan  | 0.35 | 同上（扇面为圆，四角天然不落位，故不宜定高） |

    ★★ box = 0.80 的**正向**依据（评审会问"为什么不是 75% / 85%"，别只给反向理由）
      box 的采样区只由两块构成，且两块都是**画面区**、都要求满幅：
        ① 侧面展开图 —— 下边饰 9% + 弦纹 4% + 主画面 74% + 弦纹 4% + 上边饰 9%
        ② 盒盖图 —— 边框 20% + 中心主题 80%
      主画面（74%）与主题（80%）必须被纹样填满；**允许留白的只有弦纹占位**
      （两道弦纹合计 8%，且弦纹本身不是留白，是刻意的分隔细线）。
      也就是说：设计上可接受的空白上限 ≈ 个位数个百分点。
      实测满幅状态 86%（短缺的 14 个点来自：母题是正方形、主画面区是 1.55:1，
      完整且不拉伸时上下必然各余一点，见 `pattern_layout._center_band` 的推导）。
      → 0.80 落在"86% 的良品"与"72% 的坏品"之间，取的是**下限，不是质量目标**。
        真正的质量目标是 86% 那一档；0.80 只用来拦住"退回到大面积留白"。

    ★ 换口径后不能沿用 0.60：旧口径（整张 atlas）下 60% 已经是方盒**理论天花板
      61%**，0.60 等于永远放行；新口径下 0.60 连 n=1 的坏状态（0.72）都拦不住
      —— 那才是"自检形同虚设"。

★★ 方盒每个面左右竖棱处**各有半个母题** —— 这是设计结果，不是缺陷（别去"修"）

    方盒 4 个侧面**每个面都独立映射整条 strip**（u∈[0,0.5] × v∈[0,1]，
    见 `glb_export.vertex_uv` 的 ±Z/±X 分支）。主画面 n=2 铺满后，
    每个面的左、右竖棱处各挂半个母题，4 条棱共 4 处切口；
    且相邻两面各自从 u=0 起算，所以**两半不严格可拼**
    （QA 实测：跨接缝列差 19.63，面内中位 3.94，差 4~5 倍）。

    这是"**一张图印一面**"这条设计（B8 文档铁律 1）的固有结果 ——
    盒子本来就是四个独立画面，不是绕一圈的连续画卷；
    要让接缝处严丝合缝，就得让每个面只采 strip 的 1/4 段（= 改成连续画卷，
    违反铁律 1），或把主画面区改大（覆盖率掉到 74%，撞上面 0.80 的下限）。
    两条都比"棱上有半只蝠"更糟（已推演评估）。

    ★ 因此：**不要以"修 bug"的名义改动 UV 或 `_center_band` 的 n**。
      正确做法是口径上说清楚（真实包装盒四面本就是独立印刷面）。

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


def texture_blank_map(j, bin_bytes):
    """解出内嵌 PNG，返回 (尺寸, 空白掩膜 bool[H,W])。

    "空白" = 接近 atlas 的填充底色 (247,241,230)（容差 30，即每通道约 10）。
    """
    img = j["images"][0]
    bv = j["bufferViews"][img["bufferView"]]
    off = bv.get("byteOffset", 0)
    data = bin_bytes[off: off + bv["byteLength"]]
    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    arr = np.asarray(im, np.int16)
    blank = (np.abs(arr - np.array([247, 241, 230])).sum(-1) < 30)
    return im.size, blank


def _grid_size(W, H, max_dim=512):
    """统计网格尺寸：长边不超过 max_dim，保持贴图长宽比。"""
    k = min(1.0, float(max_dim) / float(max(W, H)))
    return max(8, int(round(W * k))), max(8, int(round(H * k)))


def _downsample_blank(blank, gw, gh):
    """把全分辨率空白掩膜压成 (gh,gw) 的**空白占比**浮点图（BOX 滤波 = 面积平均）。"""
    from PIL import Image
    small = Image.fromarray(blank.astype(np.uint8) * 255, "L").resize(
        (gw, gh), Image.BOX)
    return np.asarray(small, np.float32) / 255.0


def uv_footprint(uv, idx, gw, gh):
    """把 UV 三角形光栅化成 (gh,gw) 布尔掩膜：True = 贴图这块**会被采到**。

    ★ v 的方向：**v=0 对应贴图第 0 行（顶部）**。
      这是 glTF 规范的约定（"The origin of the UV coordinates (0,0) corresponds
      to the upper left corner of a texture image"），本项目的导出也照此：
      方盒侧面 `v = 0.5 - y/(2hy)` → y=+hy（盒顶）落在 v=0 = 图顶；
      盖图贴在 atlas 的**上**半（y=0..512）→ 采到的正是 v∈[0,0.5]。
      ⚠️ 这里若写成 `(1-v)`（当成 v 朝上），网格会上下颠倒：
        方盒的盖图掩膜会落到 atlas 下半的死区上 —— 实测有效率从 72% 掉到 54%，
        是本次改脚本时真踩到一次，靠这一行注释记住。
    所以网格坐标 y = v·gh，x = u·gw。
    """
    m = np.zeros((gh, gw), bool)
    if uv is None or len(uv) == 0:
        return m
    tri_idx = np.asarray(idx).reshape(-1, 3).astype(np.int64)
    if tri_idx.size == 0:
        return m
    uv = np.asarray(uv, np.float64)
    P = np.stack([uv[:, 0] * gw - 0.5, uv[:, 1] * gh - 0.5], 1)
    T = P[tri_idx]                                  # (T,3,2)
    for t in T:
        x0 = max(0, int(np.floor(t[:, 0].min())))
        x1 = min(gw - 1, int(np.ceil(t[:, 0].max())))
        y0 = max(0, int(np.floor(t[:, 1].min())))
        y1 = min(gh - 1, int(np.ceil(t[:, 1].max())))
        if x1 < x0 or y1 < y0:
            continue
        (ax, ay), (bx, by), (cx, cy) = t
        det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(det) < 1e-12:                        # 退化三角，跳过
            continue
        X, Y = np.meshgrid(np.arange(x0, x1 + 1, dtype=np.float64),
                           np.arange(y0, y1 + 1, dtype=np.float64))
        l1 = ((by - cy) * (X - cx) + (cx - bx) * (Y - cy)) / det
        l2 = ((cy - ay) * (X - cx) + (ax - cx) * (Y - cy)) / det
        l3 = 1.0 - l1 - l2
        inside = (l1 >= -1e-4) & (l2 >= -1e-4) & (l3 >= -1e-4)
        m[y0:y1 + 1, x0:x1 + 1] |= inside
    return m


# 各形态的采样区有效率下限（理由见文件头 docstring 的表格）
# ★ 0.80 是**下限**、不是质量目标：设计上主画面必须满幅，允许留白的只有弦纹占位；
#   良品实测 86%，0.80 只用来拦住"退回大面积留白"（n=1 → 72%）。
FILL_MIN = {"box": 0.80, "vase": 0.35, "fan": 0.35}
FILL_MIN_DEFAULT = 0.35


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

    # ⑤ 采样区有效率（见文件头：只在 UV 真正采到的面积上统计）
    tex_size, blank = texture_blank_map(j, bin_bytes)
    gw, gh = _grid_size(tex_size[0], tex_size[1])
    bfrac = _downsample_blank(blank, gw, gh)
    mask = uv_footprint(uv, idx, gw, gh)
    fill_whole = 1.0 - float(bfrac.mean())
    covered = float(mask.mean())
    if covered < 1e-3:
        problems.append("UV 采样区为空（掩膜覆盖率≈0），无法评估贴图有效性")
        fill_uv = fill_whole
    else:
        fill_uv = 1.0 - float(bfrac[mask].mean())

    thr = FILL_MIN.get(expect_kind, FILL_MIN_DEFAULT)
    if fill_uv < thr:
        problems.append(
            f"采样区有效像素只有 {fill_uv:.0%}（阈值 ≥{thr:.0%}）—— 疑似主画面留白过大")

    return {
        "kind": expect_kind, "verts": len(pos), "tris": int(idx.size // 3),
        "uv_min": uv.min(0).tolist(), "uv_max": uv.max(0).tolist(),
        "tex": tex_size, "fill": fill_uv, "fill_whole": fill_whole,
        "covered": covered, "thr": thr,
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
    print(f"GLB 独立自检：{d}")
    print("（有效率按 **UV 实际采样到的面积** 统计；全图值为参考，含 atlas 未采样的死区）\n")
    for kind in ("vase", "box", "fan"):
        p = d / f"pattern_{kind}.glb"
        if not p.exists():
            print(f"  ❌ {kind:<6} 文件不存在：{p}"); ok_all = False; continue
        r = check_one(p, kind)
        mark = "✅" if not r["problems"] else "❌"
        print(f"  {mark} {kind:<6} 顶点 {r['verts']:>6}  三角 {r['tris']:>6}  "
              f"UV u[{r['uv_min'][0]:.3f},{r['uv_max'][0]:.3f}] "
              f"v[{r['uv_min'][1]:.3f},{r['uv_max'][1]:.3f}]  "
              f"贴图 {r['tex'][0]}×{r['tex'][1]}")
        print(f"       采样区有效 {r['fill']:.0%}（阈值 ≥{r['thr']:.0%}）"
              f"｜采样覆盖率 {r['covered']:.0%}｜全图有效 {r['fill_whole']:.0%}")
        for q in r["problems"]:
            print(f"        · {q}")
        ok_all = ok_all and not r["problems"]
    print(f"\n{'全部通过' if ok_all else '存在问题'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
