# scripts/filter_cleveland.py
"""给克利夫兰 303 件打「纹理丰富度」分，用于筛出能当纹样素材的那部分。

★★ 方法选择过程（这是实测得出的，别凭直觉改回 CLIP）

先试了两次语义方法，**都失败**：
  ① **Chinese-CLIP 零样本四分类**（"有连续纹样的织物"/"素色织物"/"服饰"/"绘画"）
     → 71% 判成"绘画"，明显错；**置信余量中位仅 0.0119**，222/303 低于 0.02。
       等于在瞎猜。中文短句提示词对这个区分太细。
  ② **对母题库 100 个母题名取最大相似度**（"像不像某个纹样"）
     → 好的图 0.4235–0.4824，坏的图 0.4248–0.4550，**完全重叠，零区分力**。

改用**图像统计**（20 张人工标注集上测的分离度 d = |均值差| / 合并标准差）：
  · `edge`（相邻像素梯度均值，即边缘密度）  d = **1.38** ✅
  · `local_std`（8×8 分块内灰度 std 的中位数）d = **1.47** ✅ 最好
  · `color_std` / `sat`                     d ≈ 0.5  ❌ 太弱

**为什么统计量反而赢**：我们要判断的"有没有纹样"，
本质是**纹理细节密度**问题，不是语义问题。CLIP 擅长语义，这里用不上。

★★ 但**不自动定阈值**
    20 张标注集太小，不足以定一个可靠的分界点。
    所以本脚本只做**排序**（枯燥的部分），并输出按分数排好的样张，
    **由人眼定阈值**（判断的部分）。这比假自动可靠。

用法：
    .venv/Scripts/python.exe scripts/filter_cleveland.py            # 打分 + 出样张
    .venv/Scripts/python.exe scripts/filter_cleveland.py --cut 14.0 # 按指定阈值标记可用
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.m6_provenance import _font

DATA = ROOT / "data" / "artifacts_cle"
OUT = DATA / "quality.json"


def texture_score(path):
    """纹理丰富度 = edge（边缘密度）+ local_std（局部对比度）。两者都是越大越像纹样。"""
    im = Image.open(path).convert("RGB")
    g = np.asarray(im.convert("L")).astype(np.float32)
    edge = (np.abs(np.diff(g, axis=0)).mean() + np.abs(np.diff(g, axis=1)).mean()) / 2

    h, w = g.shape
    bh, bw = max(1, h // 8), max(1, w // 8)
    blocks = [g[i * bh:(i + 1) * bh, j * bw:(j + 1) * bw]
              for i in range(8) for j in range(8)]
    local = float(np.median([b.std() for b in blocks]))
    return float(edge), local


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cut", type=float, default=None,
                    help="纹理分的阈值；给定则据此写 usable 标记")
    args = ap.parse_args()

    idx = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    print(f"给 {len(idx)} 件打纹理分…\n")

    rows = []
    for a in idx:
        e, l = texture_score(DATA / "images" / a["image_filename"])
        rows.append({"id": str(a["id"]), "acc": a["accession_number"],
                     "title": (a.get("title") or "")[:44],
                     "date": a.get("creation_date") or "",
                     "culture": (a.get("culture") or [""])[0] if isinstance(a.get("culture"), list)
                                else str(a.get("culture") or ""),
                     "edge": round(e, 2), "local_std": round(l, 2)})

    # 组合分：两个指标都标准化后相加（避免量纲差异）
    e = np.array([r["edge"] for r in rows]); l = np.array([r["local_std"] for r in rows])
    z = lambda v: (v - v.mean()) / (v.std() + 1e-9)
    score = z(e) + z(l)
    for r, s in zip(rows, score):
        r["texture_score"] = round(float(s), 3)
    rows.sort(key=lambda r: -r["texture_score"])

    cut = args.cut
    if cut is None:
        # 没给阈值就先用中位数占位（**只是占位，不是结论**）
        cut = float(np.median(score))
    for r in rows:
        r["usable_as_pattern"] = r["texture_score"] >= cut
        r["cut_used"] = round(float(cut), 3)
    OUT.write_text(json.dumps({r["id"]: r for r in rows}, ensure_ascii=False, indent=2),
                   encoding="utf-8")

    n_use = sum(1 for r in rows if r["usable_as_pattern"])
    print("=" * 64)
    print(f"纹理分分布：最高 {rows[0]['texture_score']:.2f} / 最低 {rows[-1]['texture_score']:.2f}")
    print(f"当前阈值 {cut:.2f} → 标记可用 {n_use} / {len(rows)} 件")
    print(f"落盘 → {OUT}")
    if args.cut is None:
        print("\n⚠️ 上面的阈值只是**占位（中位数）**，不是结论 —— 请先看样张再定。")

    # 按分数排好的样张：人眼定阈值用
    byid = {str(a["id"]): a for a in idx}
    make_sheets(rows, byid)
    return 0


def make_sheets(rows, byid, cols=10, per_page=50, W=150):
    """按纹理分从高到低出样张，每页 50 张，页内标序号与分数。

    ★ 页码即排名：看样张时能直接读出"第几名开始变差"，从而定阈值。
    """
    pages = [list(enumerate(rows))[i:i + per_page] for i in range(0, len(rows), per_page)]
    for page in pages:
        rws = (len(page) + cols - 1) // cols
        sheet = Image.new("RGB", (W * cols, (W + 22) * rws), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        f = _font(12)
        for k, (gi, r) in enumerate(page):
            rr, cc = divmod(k, cols)
            x, y = cc * W, rr * (W + 22)
            a = byid[r["id"]]
            im = Image.open(DATA / "images" / a["image_filename"]).convert("RGB")
            sheet.paste(im.resize((W, W), Image.LANCZOS), (x, y + 20))
            col = (0, 130, 0) if r["usable_as_pattern"] else (180, 40, 40)
            d.text((x + 2, y + 3), f"#{gi + 1} {r['texture_score']:.1f}", font=f, fill=col)
        out = DATA / f"_rank_{pages.index(page) + 1}.png"
        sheet.save(out)
        print(f"  样张 → {out.name}   （#{page[0][0] + 1} – #{page[-1][0] + 1}，"
              f"分 {page[0][1]['texture_score']:.2f} → {page[-1][1]['texture_score']:.2f}）")


if __name__ == "__main__":
    sys.exit(main())
