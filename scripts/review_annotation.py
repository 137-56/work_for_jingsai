# scripts/review_annotation.py
"""B1-3 人工抽检辅助：把 LLM 的标注结果整理成一份可读清单，供人工逐条核对。

⚠️ **它只读、只生成 Markdown，不改任何数据。** 理由：
    抽检是"看"，合并是"写"，中间必须隔着人的判断。
    工具直接改数据 = 把判断权交给脚本，出了问题没有第二道闸。

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/review_annotation.py             # 随机抽 30%
    .venv/Scripts/python.exe scripts/review_annotation.py --all       # 全部列出来
    .venv/Scripts/python.exe scripts/review_annotation.py --ratio 0.5 # 抽 50%

产出：docs/review_pending.md
"""
import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.wenyang_to_samples import DEFAULT_SRC as WENYANG_SRC

SAMPLES = ROOT / "data" / "samples.json"
PENDING = ROOT / "data" / "annotate_pending.json"
OUT_MD = ROOT / "docs" / "review_pending.md"

FLAG_CN = {
    "ELEMENTS_EMPTY": "元素为空",
    "SINGLE_ELEMENT": "只有 1 个元素（几何/云水类纹样的正常特征，看一眼即可）",
    "NO_REASON": "缺 reason",
    "UNMATCHED": "有元素在源关键词里找不到对应（疑似编造）★重点",
}


def load_all():
    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    pending = json.loads(PENDING.read_text(encoding="utf-8")) if PENDING.exists() else {}
    src = json.loads((WENYANG_SRC / "data" / "patterns.json").read_text(encoding="utf-8"))
    return samples, pending, {f"WENYANG-{r['id']}": r for r in src}


def classify(s, p, src_rec):
    """返回 (疑点标签, 对不上的元素, 被丢弃的源词)。都为空 = 没发现问题。

    三个方向都要看，缺一个就会漏：
      · **输出里有、源里没有的** → unmatched，疑似编造
      · **源里有、输出里没有的** → dropped，疑似过度清洗（如「飘带」被当成噪声丢掉）
      · 元素为空 / 只有 1 项 / 缺 reason

    为什么用「汉字是否有交集」而不是字符串相等：清洗本来就该改写法
      （源「松枝」→ 输出「松树」共享「松」，算对得上；
        输出「仙鹤」在源「梅花鹿/灵芝/松树/山石」里找不到任何含「鹤」的词 → 会被抓出来）

    ⚠️ dropped 只作为**信息**列出，不当作"错误" ——
       因为源里的颜色词/构图词本来就该丢掉。让人来判断，机器不替人下结论。
    """
    flags = []
    els = p.get("elements") or []
    raw = (src_rec or {}).get("visual_keywords") or []

    if not els:
        flags.append("ELEMENTS_EMPTY")
    if len(els) == 1:
        flags.append("SINGLE_ELEMENT")
    if not (p.get("reason") or "").strip():
        flags.append("NO_REASON")

    unmatched = [e for e in els if raw and not any(set(e) & set(r) for r in raw)]
    if unmatched:
        flags.append("UNMATCHED")

    dropped = [r for r in raw if els and not any(set(r) & set(e) for e in els)]
    return flags, unmatched, dropped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ratio", type=float, default=0.3, help="随机抽样比例（默认 0.3）")
    ap.add_argument("--all", action="store_true", help="列出全部条目")
    ap.add_argument("--seed", type=int, default=20260918, help="随机种子（固定住，结果可复现）")
    args = ap.parse_args()

    samples, pending, src_by_id = load_all()
    by_id = {s["id"]: s for s in samples}

    todo = [s for s in samples if not s.get("occasion")]
    failed = [s["id"] for s in todo if s["id"] not in pending]
    done = [(sid, p) for sid, p in pending.items() if sid in by_id]

    flagged, unmatched_map, dropped_map = {}, {}, {}
    for sid, p in done:
        flags, unmatched, dropped = classify(by_id[sid], p, src_by_id.get(sid))
        if flags:
            flagged[sid] = flags
        if unmatched:
            unmatched_map[sid] = unmatched
        if dropped:
            dropped_map[sid] = dropped

    random.seed(args.seed)
    if args.all:
        picked = [sid for sid, _ in done]
    else:
        n = max(1, int(len(done) * args.ratio))
        picked = list(flagged)                                        # 疑点条目必看
        rest = [sid for sid, _ in done if sid not in flagged]
        picked += random.sample(rest, min(n, len(rest)))
        picked = list(dict.fromkeys(picked))

    L = ["# 标注抽检清单（B1-3）\n",
         f"> 由 `scripts/review_annotation.py` 生成 ｜ 样本 {len(samples)} 条 ｜ "
         f"已自动标注 {len(done)} 条 ｜ 本次抽检 {len(picked)} 条\n",
         "## 怎么用\n",
         "1. 逐条看下面的表：**源关键词**是数据源原文，**模型输出**是 LLM 清洗后的结果",
         "2. 判断两件事：① 丢弃的词里有没有**不该丢的物象** ② 输出的词里有没有**源数据里没有的（编造）**",
         "3. 要改的条目 → 直接编辑 `data/annotate_pending.json`（JSON 好改）",
         "4. 改完跑 `.venv/Scripts/python.exe scripts/apply_annotation.py --dry-run` 看你改了什么，"
         "确认后去掉 `--dry-run` 合并进 `samples.json`\n",
         "## 一、总体统计\n",
         f"- 自动标注成功：**{len(done)}** 条",
         f"- 自动标注失败：**{len(failed)}** 条" + (f" —— {', '.join(failed)}" if failed else "（无）"),
         f"- 有疑点：**{len(flagged)}** 条"]

    cnt = Counter(f for fl in flagged.values() for f in fl)
    for k, v in cnt.most_common():
        L.append(f"    - {FLAG_CN[k]}：{v} 条")
    L.append("- occasion 分布：" + "、".join(
        f"{k}={v}" for k, v in Counter(o for _, p in done for o in p["occasion"]).most_common()))
    L.append("")

    if failed:
        L.append("## 二、失败条目（**必须人工补**）\n")
        L.append("> 失败原因是：该条的「视觉关键词」全是风格/构图描述，没有物象，清洗后为空。")
        L.append("> 补 elements 时，**依据必须来自源数据自己的 summary**，不是凭空联想。\n")
        for sid in failed:
            s = by_id[sid]
            raw = (src_by_id.get(sid) or {}).get("visual_keywords") or []
            L.append(f"### {sid} {s['name']}\n")
            L.append(f"- 源关键词：{raw}")
            L.append(f"- 库内寓意：{s['meaning']}")
            L.append(f"- 现有 elements：{s['elements']}")
            L.append("")

    L.append(f"## 三、抽检明细（{len(picked)} 条）\n")
    L.append("> **重点看最后两列**：`源里被丢弃的词` —— 有没有把**物象**当成噪声丢掉"
             "（如「飘带」）；`源里没有的输出词` —— 有没有**编造**。\n")
    L.append("| # | ID | 纹样名 | 源关键词 | 模型 elements | occasion | 源里被丢弃的词 | 源里没有的输出词 |")
    L.append("|---|---|---|---|---|---|---|---|")
    for i, sid in enumerate(picked, 1):
        s, p = by_id[sid], pending[sid]
        raw = (src_by_id.get(sid) or {}).get("visual_keywords") or []
        L.append(f"| {i} | {sid} | {s['name']} | {'、'.join(raw)} | "
                 f"{'、'.join(p['elements'])} | {'/'.join(p['occasion'])} | "
                 f"{'、'.join(dropped_map.get(sid, [])) or '—'} | "
                 f"{'、'.join(unmatched_map.get(sid, [])) or '—'} |")
    L.append("")

    L.append("## 四、疑点条目的依据（reason 原文）\n")
    for sid, fl in sorted(flagged.items()):
        note = ""
        if sid in unmatched_map:
            note += f" ｜ **源里没有的输出词：{unmatched_map[sid]}**"
        if sid in dropped_map:
            note += f" ｜ 源里被丢弃：{dropped_map[sid]}"
        L.append(f"- **{sid} {by_id[sid]['name']}**（{'、'.join(FLAG_CN[f] for f in fl)}）{note}")
        L.append(f"  - reason：{pending[sid].get('reason', '（空）')}")
    L.append("")

    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(L), encoding="utf-8")

    print(f"已自动标注 {len(done)} 条｜失败 {len(failed)} 条｜有疑点 {len(flagged)} 条｜本次抽检 {len(picked)} 条")
    print(f"[OK] 清单已生成 → {OUT_MD.relative_to(ROOT)}")
    if failed:
        print(f"[注意] {len(failed)} 条失败需要人工补：{', '.join(failed)}")
    print("\n[下一步] 打开上面那份 md 逐条看；要改的条目直接编辑 data/annotate_pending.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
