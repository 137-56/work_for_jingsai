# scripts/calibrate_m7.py
"""M7 阈值标定实验：正负例集 → 阈值—准确率曲线 → 选定阈值。

★ 为什么必须有这一步：
    阈值照抄没有意义。本项目教训（`SELF_REF` 判据误报 25/29、关联纹样清单手抄出错）
    都指向同一件事：**判据必须先在真数据上跑一遍再定稿。**
    报告里的"关键技术"要的就是这条**标定曲线**，不是拍脑袋的一个数。

★ 正负例集设计（比对池刻意不同，别改）：
    正例 = 库内图的轻微改动变体（库外新图） vs **完整库（含原图）**  → 正确答案：相似
    负例 = 库内原图本身                     vs **跨门类子集**          → 正确答案：不相似
    负例若也去比完整库，原图会与自己距离 0 / 相似度 1.0，FPR 恒为 100%，曲线毫无意义。

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/calibrate_m7.py
    .venv/Scripts/python.exe scripts/calibrate_m7.py --n 30
"""
import argparse
import io
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")                       # 无显示环境，直接存图
import matplotlib.pyplot as plt
import imagehash
from PIL import Image, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.clip_model import encode_image
from src.m7_copyright import _library, _phash
from src.utils import CFG

# ★★ 中文图表必须显式指定中文字体，否则轴标签全是方块 —— 与 B4 同一个坑。
matplotlib.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
matplotlib.rcParams["axes.unicode_minus"] = False

TMP = ROOT / "outputs" / "_m7_calib_tmp"


def _jpeg(img, q=60):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=q)
    buf.seek(0)
    return Image.open(buf).convert("RGB").copy()     # copy 让它脱离 buf 生命周期


def variants(img):
    """4 种轻微改动 —— 模拟"改吧改吧就说是自己的"这类近似侵权。"""
    w, h = img.size
    b = max(4, int(min(w, h) * 0.05))
    return [
        ("rotate4",  img.rotate(4, resample=Image.BICUBIC, fillcolor=(255, 255, 255))),
        ("bright12", ImageEnhance.Brightness(img).enhance(1.12)),
        ("border5",  ImageOps.expand(img, border=b, fill=(255, 255, 255))),
        ("jpeg60",   _jpeg(img, 60)),
    ]


def collect(n_src):
    """返回 (pos, neg)。每项是 {"h": 结构距离, "s": 语义相似度}。"""
    samples, by_id, vecs, id_order = _library()
    idx_of = {sid: i for i, sid in enumerate(id_order)}
    src = samples[:n_src]
    TMP.mkdir(parents=True, exist_ok=True)

    pos, neg = [], []
    for k, s in enumerate(src, 1):
        p = ROOT / s["image_path"]
        if not p.exists():
            continue
        img = Image.open(p).convert("RGB")

        # ---- 正例：4 个变体，各与完整库比 ----
        for tag, v in variants(img):
            vp = TMP / f"{s['id']}_{tag}.jpg"
            v.convert("RGB").save(vp, "JPEG", quality=92)
            vh = _phash(v)
            vv = encode_image(str(vp)).numpy().astype("float32")
            dh = min(int(vh - imagehash.hex_to_hash(x["phash"]))
                     for x in samples if x.get("phash"))
            sim = max(float(vv[0] @ vecs[i]) for i in range(len(id_order)))
            pos.append({"h": dh, "s": sim})

        # ---- 负例：原图本身，只与跨门类比 ----
        qh = imagehash.hex_to_hash(s["phash"])
        qi = idx_of[s["id"]]
        cats = [x for x in samples if x.get("category") != s.get("category") and x.get("phash")]
        if cats:
            dh = min(int(qh - imagehash.hex_to_hash(x["phash"])) for x in cats)
            sim = max(float(vecs[qi] @ vecs[idx_of[x["id"]]]) for x in cats)
            neg.append({"h": dh, "s": sim})

        if k % 10 == 0:
            print(f"  已处理 {k}/{len(src)} 张源图 …", flush=True)

    return pos, neg


def sweep(pos, neg, kind):
    """返回 [(阈值, TPR, FPR)]。phash 越小越严；clip 越大越严。"""
    out = []
    ts = list(range(0, 25)) if kind == "phash" else [round(0.70 + i * 0.005, 3) for i in range(61)]
    for t in ts:
        if kind == "phash":
            tpr = sum(1 for x in pos if x["h"] <= t) / len(pos)
            fpr = sum(1 for x in neg if x["h"] <= t) / len(neg)
        else:
            tpr = sum(1 for x in pos if x["s"] >= t) / len(pos)
            fpr = sum(1 for x in neg if x["s"] >= t) / len(neg)
        out.append((t, tpr, fpr))
    return out


def best_point(curve):
    """Youden J = TPR - FPR 最大处。"""
    return max(curve, key=lambda x: (x[1] - x[2], x[1]))


def plot(curve, chosen, kind, out_png, label):
    ts = [c[0] for c in curve]
    tpr = [c[1] for c in curve]
    fpr = [c[2] for c in curve]
    fig, ax = plt.subplots(figsize=(9, 5.6), dpi=140)
    ax.plot(ts, tpr, color="#C8102E", lw=2.2, label="TPR 正例检出率")
    ax.plot(ts, fpr, color="#1B4B8F", lw=2.2, label="FPR 误报率")
    ax.axvline(chosen[0], color="#D4AF37", ls="--", lw=2,
               label=f"选定阈值 {chosen[0]}")
    ax.scatter([chosen[0]], [chosen[1]], color="#C8102E", zorder=5, s=42)
    ax.scatter([chosen[0]], [chosen[2]], color="#1B4B8F", zorder=5, s=42)
    ax.set_xlabel(label)
    ax.set_ylabel("比例")
    ax.set_ylim(-0.03, 1.06)
    ax.grid(alpha=0.25, ls=":")
    ax.legend(loc="center right", frameon=False)
    ax.set_title(f"M7 阈值标定 · {kind.upper()}\n"
                 f"选定 {chosen[0]}：检出率 {chosen[1]:.1%}，误报率 {chosen[2]:.1%}",
                 fontsize=12)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_png, facecolor="white")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30, help="取前 N 张库内图做源（正例 ×4，负例 ×1）")
    args = ap.parse_args()

    print(f"[1/4] 构造正负例集（源图 {args.n} 张）…")
    pos, neg = collect(args.n)
    print(f"      正例 {len(pos)} 个（改动变体）｜负例 {len(neg)} 个（跨门类）")

    print("[2/4] 扫阈值 …")
    c_ph = sweep(pos, neg, "phash")
    c_cl = sweep(pos, neg, "clip")
    b_ph = best_point(c_ph)
    b_cl = best_point(c_cl)

    print("[3/4] 画曲线 …")
    docs = ROOT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    plot(c_ph, b_ph, "phash", docs / "fig_m7_phash_calibration.png", "感知哈希距离阈值（越小越严）")
    plot(c_cl, b_cl, "clip", docs / "fig_m7_clip_calibration.png", "CLIP 余弦相似度阈值（越大越严）")

    print("[4/4] 落盘 …")
    out = {
        "positives": len(pos), "negatives": len(neg), "sources": args.n,
        "phash": {"threshold": b_ph[0], "tpr": round(b_ph[1], 4), "fpr": round(b_ph[2], 4),
                  "curve": [{"t": t, "tpr": round(a, 4), "fpr": round(b, 4)} for t, a, b in c_ph]},
        "clip": {"threshold": b_cl[0], "tpr": round(b_cl[1], 4), "fpr": round(b_cl[2], 4),
                 "curve": [{"t": t, "tpr": round(a, 4), "fpr": round(b, 4)} for t, a, b in c_cl]},
        "method": "正例=库内图 4 种轻微改动（旋转4°/亮度1.12/白边5%/JPEG q60），比完整库；"
                  "负例=库内原图，只比跨门类子集。选点准则 Youden J = TPR - FPR 最大。",
    }
    (docs / "m7_calibration.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # 清理临时图
    for f in TMP.glob("*.jpg"):
        f.unlink()
    TMP.rmdir()

    print()
    print("=" * 58)
    print(f"  结构层 phash  选定阈值 {b_ph[0]:<3}  检出率 {b_ph[1]:.1%}  误报率 {b_ph[2]:.1%}")
    print(f"  语义层 clip   选定阈值 {b_cl[0]:<6} 检出率 {b_cl[1]:.1%}  误报率 {b_cl[2]:.1%}")
    print("=" * 58)
    print(f"  曲线 → docs/fig_m7_phash_calibration.png")
    print(f"        → docs/fig_m7_clip_calibration.png")
    print(f"  明细 → docs/m7_calibration.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())