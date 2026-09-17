# scripts/auto_annotate.py
"""批量标注：用 Qwen 为还没有 occasion 的样本生成「适用场合」+ 规范化「构成元素」。

为什么需要它：30 条手工标注要 1.5 小时，70 条要 3.5 小时，300 条不可能。
《执行任务拆解》Step 6 明确允许这条路（"可用大模型批量生成，但必须人工抽检 30%"）。

⚠️ 三条硬规矩：
  1. 输出**不直接写回 samples.json**，先落 data/annotate_pending.json —— 后面还有人工抽检这一关
  2. **支持断点续跑**：已标注过的条目跳过（70 次 API 调用，中途失败不该重来）
  3. prompt 里必须给死 9 个场合词表 + elements 清洗规则 —— 不给约束它就会编

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/auto_annotate.py --limit 3   # 先试 3 条，看质量
    .venv/Scripts/python.exe scripts/auto_annotate.py             # 跑全部未标注的
    .venv/Scripts/python.exe scripts/auto_annotate.py --redo      # 连已标注的重做
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dashscope
from dashscope import Generation

from src.m1_intent import extract_json      # ★ 复用 JSON 提取，别重写一份（两边会漂移）
from src.utils import CFG
from scripts.wenyang_to_samples import DEFAULT_SRC as WENYANG_SRC   # 数据源根目录

SAMPLES = ROOT / "data" / "samples.json"
PENDING = ROOT / "data" / "annotate_pending.json"

OCCASIONS = ["春节", "婚庆", "寿诞", "开业", "乔迁", "节庆通用", "日常陈设", "祭祀", "文人雅玩"]

SYSTEM_PROMPT = """你是中国传统纹样文化专家。请为下面这条纹样标注两项信息，然后只输出 JSON。

【任务 1】判断它适用的场合（occasion）
只能从以下 9 个词里选，可多选（通常 1–3 个）：
春节 / 婚庆 / 寿诞 / 开业 / 乔迁 / 节庆通用 / 日常陈设 / 祭祀 / 文人雅玩

判断依据：
- 富贵、繁荣、昌盛、圆满          → 开业、乔迁
- 福、吉、寿、喜                  → 春节、寿诞
- 清雅、雅致、文人、君子、品格     → 文人雅玩、日常陈设
- 庄严、神圣、肃穆、礼制           → 祭祀
- 连绵、生生不息、繁盛             → 节庆通用
- 姻缘、多子                      → 婚庆

注意：「节庆通用」表示各类节庆场合都适用；如果已经给了具体节庆（春节/婚庆/寿诞），就不要再加「节庆通用」。

【任务 2】清洗视觉关键词，得到「构成元素」elements
规则：
- 只保留**能被画出来的具体物象名词**（莲花、卷草、竹叶、麒麟、祥云…）
- 剔除以下四类：
    · 颜色词：墨绿、朱砂、青绿白描、淡黄墨线…
    · 构图词：对称、留白、圆形构图、疏密…
    · 风格词：玉雕感、唐风、古朴、典雅…
    · 工艺词：粗线条、鎏金、点染…
- **去掉修饰语，只留物象本体**：「盛开牡丹」→「牡丹」、「层叠花瓣」→「花瓣」、「藤草卷曲」→「藤草」、「花叶交织」→「花叶」
- 每项 **2–6 个字**；单字的要补成常用词（「鹿」→「仙鹿」、「鹤」→「仙鹤」、「扇」→「扇子」、「剑」→「宝剑」）
- 同一纹样内不要语义重复（别同时出现「藤蔓」和「连续藤蔓」）
- 保留 2–5 项
- **只清洗，不新增**：输出的每一项都必须来自上面给出的「原始视觉关键词」，只做规范化写法。
  不得加入关键词里没有的东西（反例：鹿纹的关键词里没有「仙鹤」，就不要凭空补一个）
- 关键词若超过 5 项，则按"主干物象优先"保留 5 项；少于 2 项则保留全部

【输出格式】只输出 JSON，不要任何解释、不要 markdown 代码块：
{
  "occasion": ["春节", "节庆通用"],
  "elements": ["莲花", "卷草", "藤蔓"],
  "reason": "一句话说明你为什么选这些场合（供人工复核用）"
}"""


def render_prompt(s):
    return f"""纹样名：{s['name']}
类别：{s['category']}
描述：{s.get('summary', '')}
库内寓意：{s.get('meaning', '')}
现有载体：{'、'.join(s.get('carrier') or [])}
原始视觉关键词（需要你清洗）：{'、'.join(s.get('_raw_keywords') or [])}

请标注。"""


def annotate_one(s, raw_keywords=None):
    """返回 {"occasion": [...], "elements": [...], "reason": "..."}，失败返回 None。

    ★ raw_keywords 必须传！它是数据源里的原始 visual_keywords。
      不传的话 LLM 只能靠纹样名猜 —— 实测过：鹿纹（源含 梅花鹿/灵芝/松树/山石）
      被猜成 ['仙鹿','松树','仙鹤','灵芝']，**凭空多出一个源数据里不存在的「仙鹤」**。
    """
    cfg = CFG["llm"]
    dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    payload = dict(s)
    payload["_raw_keywords"] = raw_keywords or []

    for attempt in range(1, cfg["max_retries"] + 1):
        try:
            resp = Generation.call(
                model=cfg["model"],
                messages=[{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": render_prompt(payload)}],
                temperature=cfg["temperature"],
                result_format="message",
                timeout=cfg["timeout"],
            )
            if resp.status_code != 200:
                print(f"\n    第 {attempt} 次失败：status={resp.status_code} {getattr(resp, 'message', '')}")
                continue
            raw = resp.output.choices[0].message.content
            out = extract_json(raw)

            occ = [o for o in (out.get("occasion") or []) if o in OCCASIONS]
            els = [str(e).strip() for e in (out.get("elements") or [])
                   if 2 <= len(str(e).strip()) <= 6]
            if not occ or not els:
                raise ValueError(f"结果不合法 occ={occ} els={els}")
            return {"occasion": occ, "elements": els, "reason": out.get("reason", ""),
                    "parsed_by": "llm"}
        except Exception as e:
            print(f"\n    第 {attempt} 次失败：{type(e).__name__}: {e}")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0 = 全部）")
    ap.add_argument("--redo", action="store_true", help="连已有结果的也重做")
    args = ap.parse_args()

    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))

    # ★ 从数据源取原始 visual_keywords —— samples.json 里只存了清洗后的 elements，
    #    原始关键词必须回数据源拿。不传的话 LLM 只能靠纹样名猜（会编出源数据里没有的元素）。
    src_patterns = json.loads((WENYANG_SRC / "data" / "patterns.json").read_text(encoding="utf-8"))
    kw_by_id = {f"WENYANG-{r['id']}": r.get("visual_keywords", []) for r in src_patterns}

    pending = {}
    if PENDING.exists():
        try:
            pending = json.loads(PENDING.read_text(encoding="utf-8"))
        except Exception:
            pending = {}

    todo = [s for s in samples if not s.get("occasion")]
    if not args.redo:
        todo = [s for s in todo if s["id"] not in pending]
    if args.limit:
        todo = todo[: args.limit]

    total_empty = len([s for s in samples if not s.get("occasion")])
    print(f"样本 {len(samples)} 条｜occasion 为空 {total_empty} 条｜"
          f"已有标注结果 {len(pending)} 条｜本次要跑 {len(todo)} 条\n")
    if not todo:
        print("[OK] 没有需要处理的条目")
        return 0

    ok = fail = 0
    failed_ids = []
    for i, s in enumerate(todo, 1):
        print(f"  [{i}/{len(todo)}] {s['id']} {s['name']:<8}", end=" ", flush=True)
        r = annotate_one(s, kw_by_id.get(s["id"], []))
        if r:
            pending[s["id"]] = r
            ok += 1
            print(f"✅ {r['occasion']}｜{r['elements']}")
        else:
            fail += 1
            failed_ids.append(s["id"])
            print("❌ 失败")
        # 每 5 条落一次盘 —— 中途崩掉不会全丢
        if i % 5 == 0 or i == len(todo):
            PENDING.write_text(json.dumps(pending, ensure_ascii=False, indent=2),
                               encoding="utf-8")

    print(f"\n=== 本次：成功 {ok}｜失败 {fail}｜累计已有结果 {len(pending)} 条 ===")
    if failed_ids:
        print(f"\n[注意] 失败条目（**需要人工补，不要忽略**）：")
        for sid in failed_ids:
            print(f"        - {sid}")
        print("       常见原因：该条的「视觉关键词」全是风格 / 构图描述，没有物象 → 清洗后为空。")
        print("       处置：在 B1-3 抽检时按源数据的 summary 人工补 elements ——")
        print("             依据必须来自源数据原文（如「岁寒三友纹」的描述明写松竹梅），不是凭空联想。")
    print(f"[OK] 结果落在 {PENDING.relative_to(ROOT)}（**尚未写回 samples.json**）")
    print("\n[下一步] 跑 B1-3 人工抽检：scripts/review_annotation.py")
    print("         抽检通过后再把结果合并回 samples.json —— 这一步不能省")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
