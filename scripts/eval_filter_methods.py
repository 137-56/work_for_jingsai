"""评估几种「内容筛选」方法 —— 用人工标注的 20 张当标准答案。

★ 这是选方法时的**证据脚本**：结论已写进 scripts/filter_cleveland.py 的文件头，
  但请保留本脚本 —— 将来若有人质疑「为什么不用 CLIP」，跑一遍就能复现结论。

标注来源：小W 肉眼看过 `文档/试验_克利夫兰303件_样张20.png` 后逐格判定。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PIL import Image

DATA = ROOT / "data" / "artifacts_cle"

# 人工标注（按 accession_number）—— 我肉眼判的
GOOD = {"1954.70.dd", "1954.70.ll", "1985.32", "1916.1336", "1920.1603",
        "1934.202.3", "1948.69", "1916.1343", "1920.1545", "1920.1619",
        "1926.537", "1916.1387", "1943.92.a"}
BAD = {"1954.70.qq", "1954.70.u", "1992.112", "1992.349", "1989.11.d",
       "1920.1950.3", "1920.1944"}

idx = {a["accession_number"]: a for a in json.loads((DATA / "index.json").read_text(encoding="utf-8"))}
labels = [(acc, 1) for acc in GOOD] + [(acc, 0) for acc in BAD]
print(f"标注集：{len(GOOD)} 好 + {len(BAD)} 坏 = {len(labels)} 张\n")


def img_stats(acc):
    """方案 D：纯图像统计（不依赖模型）。"""
    p = DATA / "images" / idx[acc]["image_filename"]
    im = Image.open(p).convert("RGB")
    a = np.asarray(im).astype(np.float32)
    g = np.asarray(im.convert("L")).astype(np.float32)

    # 边缘密度：Sobel 梯度幅值的均值
    gy = np.abs(np.diff(g, axis=0)).mean()
    gx = np.abs(np.diff(g, axis=1)).mean()
    edge = (gx + gy) / 2

    # 颜色离散度：每通道 std 的平均
    color_std = a.reshape(-1, 3).std(0).mean()

    # 局部对比度：分成 8×8 块，块内 std 的中位数
    h, w = g.shape
    bh, bw = h // 8, w // 8
    blocks = [g[i*bh:(i+1)*bh, j*bw:(j+1)*bw] for i in range(8) for j in range(8)]
    local = float(np.median([b.std() for b in blocks]))

    # 饱和度
    mx = a.max(2); mn = a.min(2)
    sat = float(np.mean((mx - mn) / np.maximum(mx, 1e-6)))
    return {"edge": edge, "color_std": color_std, "local_std": local, "sat": sat}


print("=== 方案 D：图像统计（按类别平均）===")
gv, bv = [], []
for acc, y in labels:
    s = img_stats(acc)
    (gv if y else bv).append(s)
for k in ["edge", "color_std", "local_std", "sat"]:
    g = [s[k] for s in gv]; b = [s[k] for s in bv]
    # 分离度：均值差 / 合并标准差
    pooled = np.sqrt((np.var(g) + np.var(b)) / 2 + 1e-9)
    d = (np.mean(g) - np.mean(b)) / pooled
    print(f"  {k:<11} 好 {np.mean(g):>8.2f}  坏 {np.mean(b):>8.2f}  分离度 d={d:>6.2f}"
          + ("  ← 有区分力" if abs(d) > 0.8 else ""))
    if k == "edge":
        allvals = sorted(((img_stats(a)["edge"], a, y) for a, y in labels))
        print("    逐张 edge（低→高）:", " ".join(
            f"{a.split('.')[-1][:4]}{'G' if y else 'B'}:{v:.1f}" for v, a, y in allvals))

print()
print("=== 方案 C：与母题库 100 个母题名的最大相似度 ===")
try:
    from src.clip_model import encode_images, encode_text
    idxc = json.loads((ROOT / "data" / "index" / "meta.json").read_text(encoding="utf-8")) \
        if (ROOT / "data" / "index" / "meta.json").exists() else None
    names = [a["name"] for a in json.loads((ROOT / "data" / "samples.json").read_text(encoding="utf-8"))]
    tv = encode_text(names).numpy().astype("float32")
    paths = [str(DATA / "images" / idx[a]["image_filename"]) for a, _ in labels]
    iv, ok, bad = encode_images(paths)
    sim = iv @ tv.T
    mx = sim.max(1)
    print(f"  母题名 {len(names)} 个；相似度最大值：")
    for (acc, y), v in zip(labels, mx):
        print(f"    {'G' if y else 'B'} {acc:<12} max={v:.4f}  {names[int(sim[labels.index((acc,y))].argmax())]}")
except Exception as e:
    print("  ❌ 失败:", type(e).__name__, e)
