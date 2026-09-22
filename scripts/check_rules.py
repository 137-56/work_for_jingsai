# scripts/check_rules.py
"""规则库结构校验 —— B3 最容易翻车的地方，必须先有这个脚本再写规则。

为什么必须有它：**规则写错的后果全是静默的。**
  · 路径写错      → `get_by_path` 返回 None → 条件恒假 → **该规则永不触发**（不报错）
  · terms 写单字  → 引擎 `len(t) < 2` 直接跳过 → **该词永不匹配**（不报错）
  · severity 写错 → 排序时被丢到末尾，但不影响运行（不报错）
  · ty 写错       → 引擎会输出"[规则格式异常] 未知 constraint.type"（这个会报，但混在一堆告警里）
  · constraint 缺字段 → 检查器抛 KeyError → **整个校验层崩掉**

这几类错误只能靠本脚本在写完之后立刻拦下。**先跑它，再跑 validate()。**

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/check_rules.py
    .venv/Scripts/python.exe scripts/check_rules.py --rules rules/culture_rules.json
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils import CFG

# ---------------------------------------------------------------- 契约常量
SEVERITIES = {"high", "medium", "low"}

# 四种约束类型 → 必须提供的额外字段
CONSTRAINT_FIELDS = {
    "forbidden_terms":   ["scope", "terms"],
    "required_evidence": ["field"],
    "domain_check":      ["field", "allowed"],
    "dependency":        ["if_field", "then_field"],
}

# 五类分类（契约 §2.6 的目标分类；每类目标 5 条、至少 4 条）
# 注：第 5 类由契约的「色彩规程」扩为「色彩与取值域规程」——因为 domain_check 同时承载
#     色彩色域与场合取值域两类检查，而契约原定义只有色彩一项，取名过窄。
CATEGORIES = ["场合-意象冲突", "寓意与要素完整性", "纹样等级与僭越", "结构依赖", "色彩与取值域规程"]

# ★ 配方里**真实存在**的路径（契约 §3.2）。规则里出现任何此表之外的路径 = 永不触发。
#   注意：不含 provenance / violations —— 它们是数组，而 get_by_path 不支持数组索引，
#   规则里写 provenance.carrier 之类会静默返回 None。
RECIPE_PATHS = {
    "recipe_id", "user_request", "schema_version",
    "intent.occasion", "intent.purpose", "intent.blessing", "intent.style",
    "structure.center_motif.name", "structure.center_motif.elements",
    "structure.center_motif.confidence",
    "structure.border.pattern", "structure.border.width_ratio",
    "structure.corner.pattern",
    "structure.symmetry",
    "palette.primary", "palette.secondary", "palette.scheme_basis",
}

TRIGGER_OPS = {"intersect", "contains", "equals"}
MIN_TERM_LEN = 2          # 引擎硬规则：单字词不参与匹配


def paths_of_rule(r):
    """取出该规则里所有"应当在配方上取值的路径"。"""
    out = []
    for c in (r.get("trigger") or {}).get("conditions", []) or []:
        if c.get("field"):
            out.append(("trigger.conditions[].field", c["field"]))
    cons = r.get("constraint") or {}
    t = cons.get("type")
    if t == "forbidden_terms":
        for s in cons.get("scope", []) or []:
            out.append(("constraint.scope[]", s))
    elif t in ("required_evidence", "domain_check"):
        if cons.get("field"):
            out.append(("constraint.field", cons["field"]))
    elif t == "dependency":
        for k in ("if_field", "then_field"):
            if cons.get(k):
                out.append((f"constraint.{k}", cons[k]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", default=str(ROOT / "rules" / "culture_rules.json"))
    args = ap.parse_args()

    p = Path(args.rules)
    if not p.exists():
        sys.exit(f"[FAIL] 找不到规则文件：{p}")
    try:
        rules = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"[FAIL] 不是合法 JSON：{e}")
    if not isinstance(rules, list):
        sys.exit("[FAIL] 顶层必须是数组")

    palette = {str(x.get("hex", "")).upper() for x in (CFG.get("traditional_palette") or [])}
    problems = []

    # ---- ① id 唯一 ----
    ids = [r.get("id") for r in rules]
    for i, n in Counter(ids).items():
        if n > 1:
            problems.append(f"① id 重复：{i}")

    for r in rules:
        rid = r.get("id", "?")

        # ---- ② 必备字段 ----
        for f in ("id", "name", "version", "severity", "source", "trigger", "constraint", "action"):
            if not r.get(f):
                problems.append(f"② {rid} 缺字段：{f}")
        if not re.fullmatch(r"R\d{3}", str(rid)):
            problems.append(f"② {rid} id 格式应为 R\\d{{3}}")

        # ---- ③ severity ----
        if r.get("severity") not in SEVERITIES:
            problems.append(f"③ {rid} severity 非法：{r.get('severity')}（只能 high/medium/low）")

        # ---- ④ source 非空 ----
        if not str(r.get("source", "")).strip():
            problems.append(f"④ {rid} source 为空 —— 依据不得为空，这是可审计性的体现")

        # ---- ⑤ category ----
        if r.get("category") not in CATEGORIES:
            problems.append(f"⑤ {rid} category 非法：{r.get('category')!r}")

        # ---- ⑥ trigger 结构 ----
        trig = r.get("trigger") or {}
        if trig.get("op", "any") not in ("any", "all"):
            problems.append(f"⑥ {rid} trigger.op 非法：{trig.get('op')}")
        conds = trig.get("conditions") or []
        if not conds:
            problems.append(f"⑥ {rid} trigger.conditions 为空 —— 引擎会直接返回 False，规则永不触发")
        for c in conds:
            if c.get("op") not in TRIGGER_OPS:
                problems.append(f"⑥ {rid} condition.op 非法：{c.get('op')}")
            if c.get("op") == "intersect" and not isinstance(c.get("value"), list):
                problems.append(f"⑥ {rid} intersect 的 value 必须是数组，当前 {type(c.get('value')).__name__}")

        # ---- ⑦ constraint 类型与必需字段 ----
        cons = r.get("constraint") or {}
        ctype = cons.get("type")
        if ctype not in CONSTRAINT_FIELDS:
            problems.append(f"⑦ {rid} constraint.type 非法：{ctype!r}")
        else:
            for f in CONSTRAINT_FIELDS[ctype]:
                if f not in cons:
                    problems.append(f"⑦ {rid} type={ctype} 缺必需字段：{f}")

        # ---- ⑧ ★ terms 每项必须 ≥2 字（单字会被引擎静默忽略）----
        if ctype == "forbidden_terms":
            for t in cons.get("terms", []) or []:
                if len(str(t)) < MIN_TERM_LEN:
                    problems.append(f"⑧ {rid} terms 含单字「{t}」—— 引擎会跳过它，永不匹配")

        # ---- ⑨ ★ 路径真实性 ----
        for where, path in paths_of_rule(r):
            if path not in RECIPE_PATHS:
                problems.append(f"⑨ {rid} 路径不存在于配方：{where} = {path!r} → 该规则永不触发")

        # ---- ⑩ action.message 可填充 ----
        tpl = (r.get("action") or {}).get("message", "")
        try:
            tpl.format(term="X", suggestion="Y")
        except (KeyError, IndexError, ValueError) as e:
            problems.append(f"⑩ {rid} action.message 无法用 term/suggestion 填充：{e}")

        # ---- ⑪ 色彩规程的 allowed 必须与 config.yaml 色板一致 ----
        if ctype == "domain_check" and cons.get("field") in ("palette.primary", "palette.secondary"):
            got = {str(x).upper() for x in cons.get("allowed", [])}
            if got != palette:
                miss = sorted(palette - got)
                extra = sorted(got - palette)
                problems.append(
                    f"⑪ {rid} allowed 与 config.yaml 的 traditional_palette 不一致"
                    f"（缺 {miss}；多 {extra}）")

        # ---- ⑫ ★ trigger 不得用 recipe_id 之类的标识字段当"恒真开关" ----
        # 教训：R016–R020 最初写成 `recipe_id contains "R"` 想表达"无条件触发"，
        # 结果测试配方 id 是 "T-P04"（不含 R）→ 条件恒假 → **规则压根没被求值**。
        # 靠标识符里有没有某个字母来控制规则是否生效，既脆弱又没有语义。
        # 需要"恒定触发"时，正确写法是对**语义字段**用 `contains ""`（即"该字段存在时"）。
        for c in (r.get("trigger") or {}).get("conditions", []) or []:
            if c.get("field") in ("recipe_id", "schema_version"):
                problems.append(
                    f"⑫ {rid} trigger 用了标识字段 {c['field']!r} —— 标识符里没有语义，"
                    f"当开关会因取值不同而静默失效。请改用语义字段 + `contains \"\"`")

        # ---- ⑬ domain_check 的 suggestion 取不到（引擎按命中值查表，而越界值无法穷举）----
        # 教训：R021 最初把建议写成 suggestions={"palette.primary": "..."}，但引擎查的是
        # suggestions[命中值]（如 "#FF00FF"）→ 永远查不到 → 落到兜底文案「传统吉祥纹样」。
        # 故 domain_check 类规则的建议文案必须直接写进 message，不能依赖 {suggestion}。
        ctype_ = (r.get("constraint") or {}).get("type")
        if ctype_ == "domain_check" and "{suggestion}" in tpl:
            problems.append(
                f"⑬ {rid} domain_check 的 message 用了 {{suggestion}} —— 该类型按命中值查表，"
                f"而越界值无法穷举，永远落到兜底文案。请把建议直接写进 message")

    # ---- 报告 ----
    print(f"规则 {len(rules)} 条｜解析出 {len(set(ids))} 个唯一 id｜色板 {len(palette)} 色")
    dist = Counter(r.get("category", "(无)") for r in rules)
    print("\n分类分布：")
    for c in CATEGORIES:
        print(f"  {c:<16} {dist.get(c, 0)} 条  {'（目标 5，至少 4）' if dist.get(c, 0) < 4 else ''}")
    for k, v in dist.items():
        if k not in CATEGORIES:
            print(f"  [未知类] {k}  {v} 条")
    print("\n约束类型分布：", dict(Counter((r.get('constraint') or {}).get('type') for r in rules)))

    if not problems:
        print("\n[PASS] 规则库结构校验通过")
        return 0
    print(f"\n[FAIL] 发现 {len(problems)} 处问题：\n")
    for x in problems:
        print("  " + x)
    return 1


if __name__ == "__main__":
    sys.exit(main())
