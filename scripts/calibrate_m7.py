# scripts/calibrate_m7.py
"""M7 阈值标定与诊断（B6 + B6b）。

★ 为什么必须有标定这一步：
    阈值照抄没有意义。本项目教训（`SELF_REF` 判据误报 25/29、关联纹样清单手抄出错）
    都指向同一件事：**判据必须先在真数据上跑一遍再定稿。**
    报告里的"关键技术"要的就是这条**标定曲线**，不是拍脑袋的一个数。

★ 正负例集设计（比对池刻意不同，别改）：
    正例 = 库内图的轻微改动变体（库外新图） vs **完整库（含原图）**  → 正确答案：相似
    负例 = 库内原图本身                     vs **跨门类子集**          → 正确答案：不相似
    负例若也去比完整库，原图会与自己距离 0 / 相似度 1.0，FPR 恒为 100%，曲线毫无意义。

    ⚠️ 同门类纹样（如菱格纹与方胜纹）本来就相似，对它们报警**不算误报**，
       所以主曲线只用跨门类负例。**同门类单独作为一档**在 B6b 诊断里报告。

★ B6b 诊断（本版新增）：
    1. 按**改动类型**拆解检出率 —— 回答"phash 的 49% 到底丢在哪"
    2. 负例**分两档**（跨门类 / 同门类）—— 量化 CLIP 对同门类区分力弱带来的误报风险
    ⚠️ 诊断**固定在 config.yaml 已定的工作点上**，不重新选点 —— 否则两次跑的"最优阈值"
       不一致，反而说不清。

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

# 改动类型的中文名（出图和报告用）
TAG_CN = {
    "rotate4": "旋转 4°",
    "bright12": "亮度 ×1.12",
    "border5": "白边 5%",
    "jpeg60": "JPEG q60",
}


def _jpeg(img, q=60):
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=q)
    buf.seek(0)
    return Image.open(buf).convert("RGB").copy()     # copy 让它脱离 buf 生命周期


def variants(img):
    """4 种轻微改动 —— 模拟"改吧改吧就说是自己的"这类近似侵权。

    刻意覆盖两类不同的规避手法：
      · 色彩/编码类（亮度、JPEG）—— 不改变像素几何位置，DCT 符号可能不变
      · 几何类（旋转、加边）    —— 重采样会打乱 DCT 网格
    这两类的表现差异，正是 B6b 要测出来的东西。
    """
    w, h = img.size
    b = max(4, int(min(w, h) * 0.05))
    return [
        ("rotate4",  img.rotate(4, resample=Image.BICUBIC, fillcolor=(255, 255, 255))),
        ("bright12", ImageEnhance.Brightness(img).enhance(1.12)),
        ("border5",  ImageOps.expand(img, border=b, fill=(255, 255, 255))),
        ("jpeg60",   _jpeg(img, 60)),
    ]


def collect(n_src):
    """返回 (pos, neg_cross, neg_same)。
    pos 每项 {"h","s","tag"}；neg 每项 {"h","s"}。"""
    samples, by_id, vecs, id_order = _library()
    idx_of = {sid: i for i, sid in enumerate(id_order)}
    src = samples[:n_src]
    TMP.mkdir(parents=True, exist_ok=True)

    pos, neg_cross, neg_same = [], [], []
    for k, s in enumerate(src, 1):
        p = ROOT / s["image_path"]
        if not p.exists():
            continue
        img = Image.open(p).convert("RGB")

        # ---------- 正例：4 个变体，各与**完整库**比 ----------
        for tag, v in variants(img):
            vp = TMP / f"{s['id']}_{tag}.jpg"
            v.convert("RGB").save(vp, "JPEG", quality=92)
            vh = _phash(v)
            vv = encode_image(str(vp)).numpy().astype("float32")
            dh = min(int(vh - imagehash.hex_to_hash(x["phash"]))
                     for x in samples if x.get("phash"))
            sim = max(float(vv[0] @ vecs[i]) for i in range(len(id_order)))
            pos.append({"h": dh, "s": sim, "tag": tag})     # ★ B6b：记录改动类型

        # ---------- 负例 A：跨门类（主曲线用） ----------
        qh = imagehash.hex_to_hash(s["phash"])
        qi = idx_of[s["id"]]
        cross = [x for x in samples
                 if x.get("category") != s.get("category") and x.get("phash")]
        if cross:
            dh = min(int(qh - imagehash.hex_to_hash(x["phash"])) for x in cross)
            sim = max(float(vecs[qi] @ vecs[idx_of[x["id"]]]) for x in cross)
            neg_cross.append({"h": dh, "s": sim})

        # ---------- 负例 B：同门类（★ B6b 新增）----------
        same = [x for x in samples
                if x.get("category") == s.get("category")
                and x["id"] != s["id"] and x.get("phash")]
        if same:
            dh = min(int(qh - imagehash.hex_to_hash(x["phash"])) for x in same)
            sim = max(float(vecs[qi] @ vecs[idx_of[x["id"]]]) for x in same)
            neg_same.append({"h": dh, "s": sim})

        if k % 10 == 0:
            print(f"  已处理 {k}/{len(src)} 张源图 …", flush=True)

    return pos, neg_cross, neg_same


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


def rate(items, kind, t):
    """在给定阈值下，items 中被判为"相似"的比例。"""
    if not items:
        return float("nan")
    if kind == "phash":
        return sum(1 for x in items if x["h"] <= t) / len(items)
    return sum(1 for x in items if x["s"] >= t) / len(items)


def median(vals):
    if not vals:
        return float("nan")
    vs = sorted(vals)
    n = len(vs)
    return vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2


def plot(curve, chosen, kind, out_png, label):
    ts = [c[0] for c in curve]
    tpr = [c[1] for c in curve]
    fpr = [c[2] for c in curve]
    fig, ax = plt.subplots(figsize=(9, 5.6), dpi=140)
    ax.plot(ts, tpr, color="#C8102E", lw=2.2, label="TPR 正例检出率")
    ax.plot(ts, fpr, color="#1B4B8F", lw=2.2, label="FPR 误报率")
    ax.axvline(chosen[0], color="#D4AF37", ls="--", lw=2, label=f"选定阈值 {chosen[0]}")
    ax.scatter([chosen[0]], [chosen[1]], color="#C8102E", zorder=5, s=42)
    ax.scatter([chosen[0]], [chosen[2]], color="#1B4B8F", zorder=5, s=42)
    ax.set_xlabel(label)
    ax.set_ylabel("比例")
    ax.set_ylim(-0.03, 1.06)
    ax.grid(alpha=0.25, ls=":")
    ax.legend(loc="center right", frameon=False)
    ax.set_title(f"M7 阈值标定 · {kind.upper()}\n"
                 f"选定 {chosen[0]}：检出率 {chosen[1]:.1%}，误报率 {chosen[2]:.1%}", fontsize=12)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_png, facecolor="white")
    plt.close(fig)


def plot_by_transform(tags, ph_rate, cl_rate, out_png, ph_t, cl_t):
    """★ B6b：按改动类型拆解检出率（分组柱状）。"""
    x = list(range(len(tags)))
    w = 0.38
    fig, ax = plt.subplots(figsize=(9.5, 5.4), dpi=140)
    ax.bar([i - w / 2 for i in x], ph_rate, w, color="#1B4B8F",
           label=f"结构层 phash（阈值 {ph_t:g}）")
    ax.bar([i + w / 2 for i in x], cl_rate, w, color="#C8102E",
           label=f"语义层 CLIP（阈值 {cl_t:g}）")
    for i, v in enumerate(ph_rate):
        ax.text(i - w / 2, (0 if v != v else v) + 0.02, f"{v:.0%}" if v == v else "n/a",
                ha="center", fontsize=10, color="#1B4B8F")
    for i, v in enumerate(cl_rate):
        ax.text(i + w / 2, (0 if v != v else v) + 0.02, f"{v:.0%}" if v == v else "n/a",
                ha="center", fontsize=10, color="#C8102E")
    ax.set_xticks(x)
    ax.set_xticklabels(tags)
    ax.set_ylabel("检出率")
    ax.set_ylim(0, 1.16)
    ax.grid(axis="y", alpha=0.25, ls=":")
    ax.legend(frameon=False, loc="upper right")
    ax.set_title("M7 按改动类型拆解 —— 结构层 vs 语义层对各类规避手法的稳健性", fontsize=12)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_png, facecolor="white")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30, help="取前 N 张库内图做源（正例 ×4，负例 ×1）")
    args = ap.parse_args()

    ph_t = float(CFG["copyright"]["phash_threshold"])
    cl_t = float(CFG["copyright"]["clip_sim_threshold"])

    print(f"[1/5] 构造正负例集（源图 {args.n} 张）…")
    pos, neg_cross, neg_same = collect(args.n)
    print(f"      正例 {len(pos)}（改动变体）｜负例-跨门类 {len(neg_cross)}｜负例-同门类 {len(neg_same)}")

    print("[2/5] 扫阈值（重画标定曲线）…")
    c_ph = sweep(pos, neg_cross, "phash")
    c_cl = sweep(pos, neg_cross, "clip")
    b_ph = best_point(c_ph)
    b_cl = best_point(c_cl)

    print("[3/5] 画标定曲线 …")
    docs = ROOT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    plot(c_ph, b_ph, "phash", docs / "fig_m7_phash_calibration.png", "感知哈希距离阈值（越小越严）")
    plot(c_cl, b_cl, "clip", docs / "fig_m7_clip_calibration.png", "CLIP 余弦相似度阈值（越大越严）")

    # ================= B6b 诊断（固定工作点，不重新选点）=================
    print("[4/5] B6b 诊断：按改动类型拆解 + 同门类误报档 …")
    tags = [t for t in TAG_CN if any(p["tag"] == t for p in pos)]
    by_tf = {}
    print()
    print("=" * 72)
    print(f"  按改动类型拆解（工作点：phash ≤{ph_t:g} / clip ≥{cl_t:g}）")
    print("=" * 72)
    print(f"  {'改动类型':<14}{'n':>4}{'phash检出':>12}{'clip检出':>11}"
          f"{'phash距离中位':>14}{'距离=0比例':>12}")
    for t in tags:
        sub = [p for p in pos if p["tag"] == t]
        hp = rate(sub, "phash", ph_t)
        hc = rate(sub, "clip", cl_t)
        md = median([p["h"] for p in sub])
        z = sum(1 for p in sub if p["h"] == 0) / len(sub)
        by_tf[t] = {"n": len(sub), "phash_rate": round(hp, 4), "clip_rate": round(hc, 4),
                    "phash_median_dist": md, "zero_dist_ratio": round(z, 4)}
        print(f"  {TAG_CN[t]:<14}{len(sub):>4}{hp:>12.1%}{hc:>11.1%}{md:>14.1f}{z:>12.1%}")

    plot_by_transform([TAG_CN[t] for t in tags],
                      [by_tf[t]["phash_rate"] for t in tags],
                      [by_tf[t]["clip_rate"] for t in tags],
                      docs / "fig_m7_by_transform.png", ph_t, cl_t)

    print()
    print("=" * 72)
    print(f"  负例分档误报（工作点：phash ≤{ph_t:g} / clip ≥{cl_t:g}）")
    print("=" * 72)
    print(f"  {'档位':<16}{'n':>4}{'phash误报':>13}{'clip误报':>12}{'合并误报':>12}")
    tiers = {}
    for name, items in (("跨门类", neg_cross), ("同门类", neg_same)):
        if not items:
            continue
        fp_ph = rate(items, "phash", ph_t)
        fp_cl = rate(items, "clip", cl_t)
        fp_or = sum(1 for x in items if x["h"] <= ph_t or x["s"] >= cl_t) / len(items)
        tiers[name] = {"n": len(items), "phash_fpr": round(fp_ph, 4),
                       "clip_fpr": round(fp_cl, 4), "combined_fpr": round(fp_or, 4)}
        print(f"  {name:<16}{len(items):>4}{fp_ph:>13.1%}{fp_cl:>12.1%}{fp_or:>12.1%}")

    print()
    print("[5/5] 落盘 …")
    out = {
        "positives": len(pos), "negatives_cross": len(neg_cross),
        "negatives_same": len(neg_same), "sources": args.n,
        "working_point": {"phash_threshold": ph_t, "clip_threshold": cl_t},
        "phash": {"threshold": b_ph[0], "tpr": round(b_ph[1], 4), "fpr": round(b_ph[2], 4),
                  "curve": [{"t": t, "tpr": round(a, 4), "fpr": round(b, 4)} for t, a, b in c_ph]},
        "clip": {"threshold": b_cl[0], "tpr": round(b_cl[1], 4), "fpr": round(b_cl[2], 4),
                 "curve": [{"t": t, "tpr": round(a, 4), "fpr": round(b, 4)} for t, a, b in c_cl]},
        "by_transform": by_tf,                       # ★ B6b
        "negatives_by_tier": tiers,                  # ★ B6b
        "method": "正例=库内图 4 种轻微改动（旋转4°/亮度×1.12/白边5%/JPEG q60），比完整库；"
                  "负例=库内原图，分跨门类与同门类两档。选点准则 Youden J = TPR − FPR 最大。"
                  "B6b 诊断固定在工作点上，不重新选点。",
    }
    (docs / "m7_calibration.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    for f in TMP.glob("*.jpg"):
        f.unlink()
    TMP.rmdir()

    print(f"  曲线 → docs/fig_m7_phash_calibration.png")
    print(f"        → docs/fig_m7_clip_calibration.png")
    print(f"        → docs/fig_m7_by_transform.png   ← ★ B6b 新增")
    print(f"  明细 → docs/m7_calibration.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())