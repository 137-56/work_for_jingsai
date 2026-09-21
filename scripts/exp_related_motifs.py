# scripts/exp_related_motifs.py
"""B2-2 实验：用 `related_motifs`（关联纹样）做检索增强，看指标有没有提升。

★ 这是**探索性实验**，结果好坏都要如实报 —— 不许只报提升的那组。

## 实验设计：3 组配置 × 3 种输入 = 9 格

**配置**
| 代号 | 说明 |
|---|---|
| `base`   | 现有三招（①类别前缀 + ②多查询融合 + ③elements 二次筛选） |
| `expand` | base + **查询扩展**：把该母题的关联纹样也当作查询串 |
| `boost`  | base + **关联加分**：候选若属于该母题的关联纹样，加 `--boost` 分 |

**输入**（模拟信息量不同的三种情形）
| 代号 | 说明 |
|---|---|
| `bare`      | 只有母题名 |
| `name_elem` | 母题名 + elements（= 现有基线口径） |
| `elem_only` | 只有 elements（不给名字） |

## ★ 内建正确性闸门（最重要的一行）

`base` × `name_elem` 这一格**必须复现生产代码的结果**（Top-1 97% / Top-5 100%）。
脚本会调用 `src.m2_retrieve.retrieve()` 跑一遍作对照，**两者不一致就直接报错退出** ——
否则说明本脚本的打分公式与生产代码已经漂移，实验结论全部作废。

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/exp_related_motifs.py --limit 8     # 冒烟：只跑 8 条
    .venv/Scripts/python.exe scripts/exp_related_motifs.py               # 全量 100 条
    .venv/Scripts/python.exe scripts/exp_related_motifs.py --boost 0.10  # 换关联加分权重
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.clip_model import encode_text
from src.m2_retrieve import _load_index, _load_samples, retrieve
from src.utils import CFG

W = float(CFG["clip"].get("rerank_overlap_weight", 0.15))   # ③ 的权重，与生产一致
TOPK = int(CFG["clip"]["top_k"])                            # 生产检索深度


def log(msg):
    print(msg, flush=True)


class Enc:
    """带缓存的文本编码。

    为什么要缓存：本实验会反复编码同一批母题名/元素（9 格之间有大量重复），
    每次都过一次模型在 CPU 上很慢。实测瓶颈就在这儿。
    """

    def __init__(self):
        self._c = {}

    def __call__(self, text):
        v = self._c.get(text)
        if v is None:
            # faiss 要求 float32 且内存连续
            v = np.ascontiguousarray(encode_text(text).numpy().astype("float32"))
            self._c[text] = v
        return v


def build_qs(s, mode, cfg):
    """按「输入模式 + 配置」构造查询串。"""
    name = s["name"]
    cat = s.get("category") or ""
    elems = [e for e in (s.get("elements") or []) if e]

    if mode == "bare":
        qs = [name]
    elif mode == "elem_only":
        qs = list(elems)
    else:                                   # name_elem
        qs = [name] + elems

    # ① 类别前缀 —— 只在给了名字的输入上加（elem_only 加了就等于泄露答案）
    if mode != "elem_only" and name and cat:
        qs = [f"{cat}：{name}"] + qs

    # expand：把关联纹样也当查询串（扩大召回）
    if cfg == "expand":
        qs += [m for m in (s.get("related_motifs") or []) if m]

    seen, out = set(), []
    for q in qs:
        if q and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def scores_for(s, mode, cfg, ctx):
    """返回 {sample_id: 总分}。打分公式与 src/m2_retrieve.py 保持一致。"""
    index, id_order, by_id, related_ids = ctx

    qs = build_qs(s, mode, cfg)
    if not qs:
        return {}

    # 查询侧的元素集合：只有输入里含 elements 时才参与 ③ 的交集加分
    q_elems = set(s.get("elements") or []) if mode != "bare" else set()

    best = {}
    for q in qs:
        D, I = index.search(ctx_enc(q), TOPK)
        for sc, i in zip(D[0], I[0]):
            i = int(i)
            if i < 0:
                continue
            sid = id_order[i]
            v = float(sc)
            if sid not in best or v > best[sid]:
                best[sid] = v

    out = {}
    for sid, sim in best.items():
        cand = by_id.get(sid)
        if not cand:
            continue
        overlap = len(set(cand.get("elements") or []) & q_elems) if q_elems else 0
        total = sim + W * overlap
        if cfg == "boost" and sid in related_ids:
            total += ctx_boost[0]
        out[sid] = total
    return out


# 用模块级变量传编码器与加分权重，避免到处穿参
ctx_enc = None
ctx_boost = [0.05]


def rank_of(sid, sc):
    """该样本在全部候选里的排名（0 = 第一）。"""
    order = sorted(sc.items(), key=lambda kv: (-kv[1], kv[0]))   # 分数降序，id 升序打破平局
    for pos, (i, _) in enumerate(order):
        if i == sid:
            return pos
    return 10 ** 6          # 没进候选（未在 base 检索深度内出现）


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0 = 全量）")
    ap.add_argument("--boost", type=float, default=0.05, help="boost 配置的关联加分权重")
    ap.add_argument("--no-parity", action="store_true", help="跳过与生产代码的一致性校验（不推荐）")
    args = ap.parse_args()

    global ctx_enc
    ctx_enc = Enc()
    ctx_boost[0] = args.boost

    index, id_order = _load_index()
    samples, by_id, by_name = _load_samples()
    if args.limit:
        samples = samples[: args.limit]

    # 关联纹样名 → id（只保留落在本库内的）
    rel_ids = {}
    for s in samples:
        rel_ids[s["id"]] = {by_name[m]["id"] for m in (s.get("related_motifs") or []) if m in by_name}
    ctx = (index, id_order, by_id, rel_ids)

    log(f"样本 {len(samples)} 条｜③权重 W={W}｜boost={args.boost}｜检索深度 TOPK={TOPK}")
    n_rel = sum(len(v) for v in rel_ids.values())
    log(f"关联纹样落库命中 {n_rel} 个（全库口径 524 个关联 / 505 个落库）")
    log("")

    # ───────── ★ 正确性闸门：base × name_elem 必须与生产代码一致 ─────────
    if not args.no_parity:
        log("=== 一致性校验：base × name_elem 应复现生产代码结果 ===")
        prod_top1 = prod_top5 = mine_top1 = mine_top5 = 0
        for s in samples:
            recipe = {"structure": {"center_motif": {"name": s["name"],
                                                     "elements": s.get("elements") or []}}}
            rows = retrieve(recipe, top_k=TOPK)
            order = [r["sample"]["id"] for r in rows]
            if order and order[0] == s["id"]:
                prod_top1 += 1
            if s["id"] in order[:5]:
                prod_top5 += 1
            sc = scores_for(s, "name_elem", "base", ctx)
            rk = rank_of(s["id"], sc)
            if rk == 0:
                mine_top1 += 1
            if rk < 5:
                mine_top5 += 1
        n = len(samples)
        log(f"  生产代码      Top-1 {prod_top1}/{n}   Top-5 {prod_top5}/{n}")
        log(f"  本脚本(base)  Top-1 {mine_top1}/{n}   Top-5 {mine_top5}/{n}")
        if (prod_top1, prod_top5) != (mine_top1, mine_top5):
            log("")
            log("[FAIL] 本脚本与生产代码结果不一致 —— 打分公式已漂移，实验结论不可用。")
            log("       请先排查差异，不要继续看下面的表。")
            return 1
        log("  ✅ 一致，实验有效")
        log("")

    # ───────── 主表 ─────────
    modes = ["bare", "name_elem", "elem_only"]
    cfgs = ["base", "expand", "boost"]
    n = len(samples)
    table = {}

    log("=== 9 格指标（Top-1 / Top-5 命中自身）===")
    log(f"{'输入':<12}{'配置':<10}{'Top-1':>12}{'Top-5':>12}")
    log("-" * 46)
    for mode in modes:
        for cfg in cfgs:
            t1 = t5 = 0
            for s in samples:
                sc = scores_for(s, mode, cfg, ctx)
                rk = rank_of(s["id"], sc)
                if rk == 0:
                    t1 += 1
                if rk < 5:
                    t5 += 1
            table[f"{mode}/{cfg}"] = {"top1": t1 / n, "top5": t5 / n}
            log(f"{mode:<12}{cfg:<10}{t1:>5}/{n} = {t1/n:>5.1%}{t5:>6}/{n} = {t5/n:>5.1%}")
        log("")

    log("=== 增量对比（相对同输入的 base）===")
    for mode in modes:
        b1 = table[f"{mode}/base"]["top1"]
        b5 = table[f"{mode}/base"]["top5"]
        for cfg in ("expand", "boost"):
            d1 = table[f"{mode}/{cfg}"]["top1"] - b1
            d5 = table[f"{mode}/{cfg}"]["top5"] - b5
            mark = "提升" if (d1 > 0 or d5 > 0) else ("无变化" if (d1 == 0 and d5 == 0) else "下降")
            log(f"  {mode:<10} + {cfg:<7} Top-1 {d1:+.1%}   Top-5 {d5:+.1%}   → {mark}")

    log("")
    log("─" * 60)
    log("阅读提示（很重要，别把预期内的结果当成 bug）")
    log("  1. expand 在本机制下**结构性**难有正向效果：")
    log("     打分取「同一候选在各查询上的最高分」，而目标母题已被它自己的查询命中；")
    log("     追加关联纹样作查询，只会把关联纹样也拉进前列来跟目标竞争。")
    log("     → 它下降是**预期内**的，这本身就是一条结论：")
    log("       「关联纹样不适合当查询扩展（在本打分机制下）」")
    log("  2. boost 不改查询、只对关联母题调分，是更合理的用法。")
    log("  3. name_elem 一格已到 100%，属于**饱和**——在那里加什么都看不出差别，")
    log("     要看效果必须看信息更少的 bare 一行。")
    log("─" * 60)

    out = ROOT / "docs" / "exp_related_motifs.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "sample_size": n, "overlap_weight": W, "boost_weight": args.boost,
        "topk": TOPK, "table": table,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log("")
    log(f"[OK] 明细已落 {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
