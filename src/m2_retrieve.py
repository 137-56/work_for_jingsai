# src/m2_retrieve.py
"""M2 元素检索：纹样配方 → Top-K 真实样本及出处。

检索链路上有三招（详细实现指南 2.5），缺一个效果都会明显变差：
  ① 类别前缀     查询写成「植物花卉纹：缠枝莲纹」，而不是光写「缠枝莲纹」
                 —— 传统纹样之间风格太像，光给母题名区分度不够
  ② 多查询融合   母题名 + 各 elements 分别检索，同一候选取最高分
  ③ 二次筛选重排 候选样本的 elements 与查询有交集则加分

为什么 ③ 是关键：Step 3 实测「缠枝莲纹 0.4352 vs 回纹 0.4162」——正样本只领先 0.019，
纯靠 CLIP 相似度排序很不可靠。elements 交集提供**语义层的硬约束**，与视觉相似度互补。
"""
import json
import sys
from functools import lru_cache
from pathlib import Path

import faiss
import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.clip_model import encode_text
from src.utils import CFG

INDEX_DIR = Path(CFG["paths"]["index"])
NPZ = INDEX_DIR / "clip_vectors.npz"
FAISS = INDEX_DIR / "faiss.index"
SAMPLES = Path(CFG["paths"]["samples"])

# ③ 的加分权重：每命中一个 elements 加多少分。
# 0 = 关闭二次筛选；调大能压住 CLIP 的噪声，调太大又会盖掉视觉相似度。
# 可在 config.yaml 的 clip 段加 rerank_overlap_weight 覆盖。
DEFAULT_OVERLAP_WEIGHT = 0.15


@lru_cache(maxsize=1)
def _load_index():
    if not FAISS.exists() or not NPZ.exists():
        raise FileNotFoundError(f"索引不存在：{FAISS} / {NPZ}\n请先跑 scripts/build_index.py")
    index = faiss.read_index(str(FAISS))
    data = np.load(NPZ, allow_pickle=False)
    return index, [str(x) for x in data["id_order"]]


@lru_cache(maxsize=1)
def _load_samples():
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    return samples, {s["id"]: s for s in samples}, {s["name"]: s for s in samples}


def build_queries(recipe, by_name):
    """从配方里抽出查询串。第一串带类别前缀（第 ① 招）。"""
    st = recipe.get("structure", {}) or {}
    cm = st.get("center_motif", {}) or {}
    name = cm.get("name") or ""

    queries = []
    cat = (by_name.get(name) or {}).get("category", "")
    if name:
        queries.append(f"{cat}：{name}" if cat else name)     # ① 类别前缀
        queries.append(name)                                  # 裸母题名也留一条
    queries.extend([e for e in (cm.get("elements") or []) if e])

    border = (st.get("border") or {}).get("pattern")
    corner = (st.get("corner") or {}).get("pattern")
    queries.extend([q for q in (border, corner) if q])

    seen, out = set(), []                                     # 去重保序
    for q in queries:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def retrieve(recipe, top_k=None, debug=False):
    """配方 → Top-K 样本。每条结果带 name / source / license（验收要求）。"""
    index, id_order = _load_index()
    _, by_id, by_name = _load_samples()
    k = top_k or CFG["clip"]["top_k"]
    w = CFG["clip"].get("rerank_overlap_weight", DEFAULT_OVERLAP_WEIGHT)

    queries = build_queries(recipe, by_name)
    if not queries:
        return []

    # ---- ② 多查询融合：同一个 sample 取最高分 ----
    best = {}                                                 # sid -> (score, 命中它的 query)
    for q in queries:
        vec = encode_text(q).numpy().astype("float32")        # (1,512)，已 L2 归一化
        D, I = index.search(vec, k)
        for score, i in zip(D[0], I[0]):
            if i < 0:
                continue
            sid = id_order[i]
            s = float(score)
            if sid not in best or s > best[sid][0]:
                best[sid] = (s, q)

    # ---- ③ 二次筛选重排：elements 有交集就加分 ----
    q_elems = set(((recipe.get("structure", {}) or {}).get("center_motif", {}) or {}).get("elements") or [])
    rows = []
    for sid, (sim, q) in best.items():
        s = by_id.get(sid)
        if not s:
            continue
        overlap = len(set(s.get("elements") or []) & q_elems) if q_elems else 0
        row = {
            "sample": s,
            "score": round(sim + w * overlap, 4),
            "name": s.get("name"),
            "source": s.get("source"),
            "license": s.get("license"),
        }
        if debug:
            row.update({"clip_similarity": round(sim, 4),
                        "element_overlap": overlap, "matched_by": q})
        rows.append(row)

    rows.sort(key=lambda r: -r["score"])

    # ---- ★ 槽位保底：border / corner 的命中必须出现在结果里 ----
    # 为什么必须单独处理：边饰/角花的相似度天然低于中心母题相关项，
    # 在"多查询融合后取总榜前 K"的机制下会被挤掉
    # （实测：卷草纹对自己 0.4189，而当时总榜第 10 名是 0.4251 —— 就差 0.006）。
    # 一旦被挤掉，溯源卡片里就永远缺边饰和角花，
    # 而"配方的每个槽位都可溯源"正是本作品的核心卖点。
    st = recipe.get("structure", {}) or {}
    pinned = set()
    for slot in ("border", "corner"):
        pat = str((st.get(slot) or {}).get("pattern") or "").strip()
        if not pat:
            continue
        for r in rows:
            if r["sample"]["name"] == pat:
                r["slot"] = slot                      # 打标记，调试时能看清它为什么在榜上
                pinned.add(r["sample"]["id"])
                break

    head = [r for r in rows if r["sample"]["id"] in pinned]
    tail = [r for r in rows if r["sample"]["id"] not in pinned]
    return (head + tail)[:k]
