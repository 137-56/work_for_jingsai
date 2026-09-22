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

## ★ 这个字段"该测什么"——一条设计教训

关联纹样对**「自检索 Top-1」这个指标结构性无正向作用**：
  · `expand` 把关联母题变成查询串 → 它们被检索出来，跟目标竞争
  · `boost`  给关联母题的分数加分 → 同样是抬高竞争者
两条路都只是让目标的相对排名变差。**所以 9 格里出现"下降/无变化"是预期内的，不是 bug。**
（注：脚本第一版有个 bug —— 把 `sid in rel_ids`（字典）当成"属于该母题的关联集合"，
  条件恒为真，等于给所有候选加同一常数，排序不变，指标显示"无变化"。
  已修为 `sid in my_rel`。）

因此本脚本**额外测两个与该字段价值对齐的指标**（复用 base 的检索结果，不引入新机制）：
  1. **近邻关联率** —— 前 5 名里有多少落在该母题的关联纹样内（可解释性的量化证据）
  2. **同族混淆核验** —— 那 5 条排不到第 1 的，第 1 名是不是它的关联纹样

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


# 用模块级变量传编码器与加分权重，避免到处穿参
ctx_enc = None
ctx_boost = [0.05]


def scores_for(s, mode, cfg, ctx):
    """返回 {sample_id: 总分}。打分公式与 src/m2_retrieve.py 保持一致。"""
    index, id_order, by_id, rel_ids = ctx

    qs = build_qs(s, mode, cfg)
    if not qs:
        return {}

    # 查询侧的元素集合：只有输入里含 elements 时才参与 ③ 的交集加分
    q_elems = set(s.get("elements") or []) if mode != "bare" else set()

    # ★★ 当前母题**自己**的关联纹样集合。
    #   这里绝不能写成 `if sid in rel_ids` —— rel_ids 是 {样本id: {关联id集合}} 的字典，
    #   而每个样本 id 都是它的键，条件会**恒为真**，等于给每个候选都加同一个常数，
    #   排序完全不变，指标看起来就是"无变化"。
    #   这个 bug 曾静默产出一个假结论（boost 全为 +0.0%），且冒烟测不出来（--limit 时
    #   字典的键不全，加分反而不均匀，表现得像是有效果）。改这里务必小心。
    my_rel = rel_ids.get(s["id"], set())

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
        if cfg == "boost" and sid in my_rel:
            total += ctx_boost[0]
        out[sid] = total
    return out


def ranked_ids(s, mode, cfg, ctx):
    """按总分降序的样本 id 列表（平局按 id 升序，保证可复现）。"""
    sc = scores_for(s, mode, cfg, ctx)
    return [sid for sid, _ in sorted(sc.items(), key=lambda kv: (-kv[1], kv[0]))]


def rank_of(sid, order):
    """该样本在候选列表里的排名（0 = 第一）。未进候选返回一个大数。"""
    try:
        return order.index(sid)
    except ValueError:
        return 10 ** 6


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
            rk = rank_of(s["id"], ranked_ids(s, "name_elem", "base", ctx))
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
                rk = rank_of(s["id"], ranked_ids(s, mode, cfg, ctx))
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

    # ───────── 近邻关联率：量化「排序可解释性」─────────
    # 为什么必须单独测这个：上面 9 格测的是"自检索 Top-1"，而关联纹样在**设计上**
    # 就不是为提升它服务的 —— expand 把关联母题变成查询、boost 给关联母题加分，
    # 两条路都是**抬高竞争者**，对 Top-1 结构性无益。
    # 它真正的价值在另外两处：① 结果列表的「相关参考」槽位 ② 解释近邻为什么合理。
    # 本指标测后者，且**复用 base 已有的检索结果**，不引入任何额外机制。
    sample_ids = {x["id"] for x in samples}      # noqa: F841 （保留备查）
    n_with_rel = hit_any = near_total = hit_total = 0
    for s in samples:
        my_rel = rel_ids.get(s["id"], set())
        if not my_rel:
            continue
        n_with_rel += 1
        order = ranked_ids(s, "name_elem", "base", ctx)
        near = [sid for sid in order[:5] if sid != s["id"]]
        near_total += len(near)
        h = sum(1 for sid in near if sid in my_rel)
        hit_total += h
        if h:
            hit_any += 1
    rate_slot = hit_total / near_total if near_total else 0.0
    rate_motif = hit_any / n_with_rel if n_with_rel else 0.0

    log("=== 近邻关联率（量化「排序可解释性」）===")
    log("  对每条母题取检索结果第 2–5 名，看是否落在该母题的关联纹样里")
    log(f"  有关联纹样的母题        {n_with_rel} 条")
    log(f"  前 5 名中属关联纹样的槽位 {hit_total}/{near_total} = {rate_slot:.1%}")
    log(f"  至少一个关联纹样进前 5 的母题 {hit_any}/{n_with_rel} = {rate_motif:.1%}")
    log("  → 越高，越能说「排序的近邻在语义上合理」——这是可解释性的量化证据")
    log("")

    # ───────── B2-3：未排到第 1 的条目，第 1 名是不是它的关联纹样 ─────────
    # ★ 清单**必须从结果算出来，不能硬编码条目号**。
    #   脚本第一版硬编码了 B1-4 时期记录的 5 条（045/060/061/062/092），
    #   实测发现 061 祥云纹、062 如意云纹 在本口径下**其实排到了第 1**（第 1 名就是自己），
    #   硬编码的清单与真实"未命中集合"对不上，表格会误导。
    log("=== 未命中第 1 的条目核验（B2-3 报告素材）===")
    misses = [s for s in samples
              if rank_of(s["id"], ranked_ids(s, "name_elem", "base", ctx)) != 0]
    log(f"  base × name_elem 下未排第 1 的共 {len(misses)} 条")
    log(f"{'条目':<13}{'母题':<10}{'检索第 1 名':<12}{'是它的关联纹样？'}")
    log("-" * 56)
    b23 = []
    for s in misses:
        order = ranked_ids(s, "name_elem", "base", ctx)
        first = order[0] if order else None
        fname = by_id[first]["name"] if first else "(无)"
        ok = fname in set(s.get("related_motifs") or [])
        b23.append({"id": s["id"], "name": s["name"], "top1": fname, "is_related": bool(ok)})
        log(f"{s['id']:<13}{s['name']:<10}{fname:<12}{'是 ✅' if ok else '否'}")
    n_ok = sum(1 for x in b23 if x["is_related"])
    if b23:
        log(f"  → {n_ok}/{len(b23)} 条的「第 1 名」是该母题的关联纹样（源数据有据可查）")
    log("")

    log("─" * 60)
    log("阅读提示（很重要，别把预期内的结果当成 bug）")
    log("  1. expand 与 boost 在本机制下**结构性**都难有正向效果，原因不同：")
    log("     · expand：把关联纹样当查询串 → 关联母题被检索出来，跟目标竞争")
    log("     · boost ：给关联母题的分数加分 → 同样是抬高竞争者")
    log("     两者都只会让目标的相对排名变差。这是**预期内**的，本身就是结论：")
    log("     「关联纹样对『自检索 Top-1』无正向作用」")
    log("  2. 那它有什么价值？看上面的「近邻关联率」与 B2-3 核验 ——")
    log("     它的价值在**可解释性**与**结果列表的相关参考**，不在提升 Top-1。")
    log("  3. name_elem 接近饱和（97% / 100%），在那里加什么都看不出差别；")
    log("     要看区分度必须看信息更少的 bare 一行。")
    log("─" * 60)

    out = ROOT / "docs" / "exp_related_motifs.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "sample_size": n, "overlap_weight": W, "boost_weight": args.boost,
        "topk": TOPK, "table": table,
        "neighbor_related": {
            "motifs_with_related": n_with_rel,
            "slot_rate": round(rate_slot, 4),
            "motif_any_rate": round(rate_motif, 4),
        },
        "confusable_check": b23,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    log("")
    log(f"[OK] 明细已落 {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
