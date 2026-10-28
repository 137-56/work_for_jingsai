# scripts/check_rules.py
"""规则库结构校验 —— B3 最容易翻车的地方，必须先有这个脚本再写规则。

为什么必须有它：**规则写错的后果全是静默的。**
  · 路径写错      → `get_by_path` 返回 None → 条件恒假 → **该规则永不触发**（不报错）
  · terms 写单字  → 引擎 `len(t) < 2` 直接跳过 → **该词永不匹配**（不报错）
  · severity 写错 → 排序时被丢到末尾，但不影响运行（不报错）
  · ty 写错       → 引擎会输出"[规则格式异常] 未知 constraint.type"（这个会报，但混在一堆告警里）
  · constraint 缺字段 / condition 漏 op、value
                  → ★ 2026-10 起：引擎**不再崩**，该条规则失效并留一条 low 告警
                    （`m3_validate` 已全部改用 `.get()` + 逐条 `try/except` 兜底）。
                    但仍然**必须由本脚本拦下** —— "不崩"只保证其余 24 条规则还活着，
                    这条规则本身已经悄悄不生效了，等于白写。

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

# ★★ 必需键清单**不在这里维护**（2026-10 统一）
#   原来本脚本自己有一份 CONSTRAINT_FIELDS，"四种约束类型 → 必需字段"，
#   而运行期 `m3_validate` 也有自己的一套 —— 两份必然会发散（项目栽过）。
#   现在改成 **import `m3_validate.rule_schema_error()`**，本脚本只负责
#   "提交前拦"：它比运行期多查 id 唯一性、分类分布、路径真实性、terms 字数、
#   色板一致性等 lint 项；而"规则结构对不对"这个判定只有一份实现。
from src.m3_validate import rule_schema_error, validate    # noqa: E402


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

MIN_TERM_LEN = 2          # 引擎硬规则：单字词不参与匹配


def _ctype_of(r):
    """安全取 constraint.type —— 规则可能是脏的（constraint 写成 str/list），
    汇总统计不该被一条坏规则搞崩（结构问题由 ⓪ 的 rule_schema_error 负责报）。"""
    if not isinstance(r, dict):
        return "(非对象)"
    c = r.get("constraint")
    return c.get("type") if isinstance(c, dict) else "(非法 constraint)"


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
        # ---- ⓪ ★ 结构契约（与运行期同一份实现：src/m3_validate.rule_schema_error）----
        #   这一项是"提交前拦"，比运行期多一层意义：运行期只保证"不崩 + 留痕"，
        #   但坏规则在运行期已经等于白写了，必须在这里拦下并说清原因。
        err = rule_schema_error(r)
        if err:
            problems.append(f"⓪ {r.get('id', '?') if isinstance(r, dict) else '?'} 结构不合契约：{err}")
        if not isinstance(r, dict):
            continue
        rid = r.get("id", "?")
        # 形状都不对（constraint/trigger 不是对象）时，后面 ②–⑫ 的 lint 全部依赖
        # dict 形状，硬跑会二次崩溃（实测 `constraint` 写成字符串就 AttributeError）。
        # 结构问题已由 ⓪ 记录，这里只是别把 lint 自己搞崩。
        if not isinstance(r.get("constraint"), dict) or not isinstance(r.get("trigger"), dict):
            continue

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

        # ---- ⑥ trigger 结构（仅本脚本才查的 lint 项；op/conditions 的存在性
        #      与合法性已由 ⓪ 的 rule_schema_error 统一负责，这里不重复）----
        trig = r.get("trigger") or {}
        if trig.get("op", "any") not in ("any", "all"):
            problems.append(f"⑥ {rid} trigger.op 非法：{trig.get('op')}")
        conds = trig.get("conditions") or []
        for c in conds:
            if c.get("op") == "intersect" and not isinstance(c.get("value"), list):
                problems.append(f"⑥ {rid} intersect 的 value 必须是数组，当前 {type(c.get('value')).__name__}")

        # ---- ⑦ constraint 类型（合法性已由 ⓪ 负责，这里只取 type 供后续 lint 用）----
        cons = r.get("constraint") or {}
        ctype = cons.get("type")

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
    print("\n约束类型分布：", dict(Counter(_ctype_of(r) for r in rules)))

    # ---- ⑭ ★ 引擎冒烟（2 行，专挡"半重构落盘"）----
    # 教训（2026-10，QA 撞到）：改 m3_validate 的过程中曾落盘过一个中间态
    # （`NameError: structure_problem`），当时**每一次** validate() 都抛，
    # 而 pipeline 是 try/except + `violations = []` → 界面照常出图、文化校验全失效。
    #
    # ★ 断言的是什么、不是什么：这里验的是「**引擎本身**能不能跑通、会不会多吐
    #   业务告警」，与「规则库写得对不对」是两件事。所以必须先滤掉
    #   `[规则格式异常]` / `[规则执行异常]` 这两类**结构/运行期**告警 ——
    #   它们是引擎按契约给出的正确输出，规则库坏掉时本来就会出现。
    #   不滤的话会误报成"引擎坏了"（QA 实测：坏规则库 → ⓪ 报对了，⑭ 却诬告引擎）。
    try:
        smoke = validate({}, rules)
    except Exception as e:                          # noqa: BLE001
        problems.append(f"⑭ 引擎冒烟失败：validate() 在真实规则库上抛 "
                        f"{type(e).__name__}: {e} —— 校验层此刻是失效的")
    else:
        is_infra = lambda a: str(a.get("message", "")).startswith(   # noqa: E731
            ("[规则格式异常]", "[规则执行异常]"))
        infra = [a for a in smoke if is_infra(a)]
        real = [a for a in smoke if not is_infra(a)]
        if real:
            problems.append(f"⑭ 引擎冒烟失败：空配方本应 0 条业务告警，实得 {len(real)} 条"
                            f"（{', '.join(str(a.get('rule_id')) for a in real[:3])}）")
        elif infra:
            print(f"引擎冒烟：validate(空配方) → 0 条业务告警 ✅"
                  f"（另有 {len(infra)} 条规则自身结构/运行期异常，见 ⓪ 类问题）")
        else:
            print("引擎冒烟：validate(空配方) → 0 条告警 ✅")

    if not problems:
        print("\n[PASS] 规则库结构校验通过")
        return 0
    print(f"\n[FAIL] 发现 {len(problems)} 处问题：\n")
    for x in problems:
        print("  " + x)
    return 1


if __name__ == "__main__":
    sys.exit(main())
