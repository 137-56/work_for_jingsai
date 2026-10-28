# src/m3_validate.py
"""M3 文化准确性校验（规则引擎）—— 本项目的核心创新点。

设计要点：
  1. 规则是**显式的**：用户能看懂为什么被拒绝，评审能核查规则是否合理，团队能持续扩充。
     若改用模型判断文化正确性，只是把"不可解释"从生成环节挪到了校验环节。
  2. 规则库**独立于代码**：新增/修改规则只改 rules/culture_rules.json，不动这里一行代码。
  3. **四种约束类型全部支持**：
       forbidden_terms    禁止出现某些词       （场合—意象冲突、纹样等级）
       required_evidence  要求某字段有依据     （谐音可推导）
       domain_check       取值须在允许域内     （色彩规程、纹样等级）
       dependency         字段间依赖关系       （载体—密度）
  4. 每个检查器统一返回**命中词列表**，建议词一律由 validate() 从 action.suggestions 取
     —— 避免"检查器给一个建议、规则表给另一个建议"的不一致。

规则格式见 docs/schema.md §2；判定口径见 详细实现指南 §3.5（那段要抄进报告）。
"""
from typing import Any, Dict, List, Optional

# 告警输出顺序。与 config.yaml 的 validate.severity_order 保持一致；
# pipeline 调用时可显式传入该配置值。
SEVERITY_ORDER = ["high", "medium", "low"]


# ---------------------------------------------------------------- 基础工具
def get_by_path(obj: Any, path: str) -> Any:
    """按 'intent.occasion' 这样的点分路径取值，取不到返回 None。"""
    cur = obj
    for p in path.split("."):
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return None
    return cur


def as_list(v: Any) -> List[Any]:
    """统一成 list：None → []，标量 → [标量]，list 原样返回。"""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def render_message(tpl: str, **kw: Any) -> str:
    """填充 action.message。缺占位符时**不能抛异常**——一条规则写错，整个校验层就崩了。"""
    try:
        return tpl.format(**kw)
    except (KeyError, IndexError, ValueError):
        return tpl


# ---------------------------------------------------------------- trigger 求值
def eval_condition(recipe: Dict[str, Any], cond: Dict[str, Any]) -> bool:
    """求值单个 trigger 条件。

    ★★ 为什么每个键都要 `.get()`（2026-10 修，后果比崩溃更糟）
      规则库是**手写 JSON**，漏键是常态。原来 `cond["op"]` 直接下标取值，
      漏写一个 op 就抛 KeyError —— 而这个 KeyError 会**冒到 validate() 外面**，
      被 pipeline.run() 的 try/except 接住 → `violations` 置空 →
      **25 条规则全部静默失效，界面照常出图，只是再没有任何文化校验**。
      这跟本模块自己的口径（见 validate() 里"未知 type → 记 low 告警、绝不让管线崩"）
      完全自相矛盾：一个坏的 constraint.type 会降级，一个漏写的 op 却让整层消失。

      所以：**缺键一律降级为"该条件不成立"**，绝不抛异常。
      · 缺 field  → 取不到值 → False
      · 缺 op     → False（与"未知 op"同一处理）
      · 缺 value  → False（没有比较对象的条件无法判定，不能当空串处理 ——
        `"" in str(val)` 恒为真，会把规则误判成"命中"）

    ★ 但"降级"不等于"静默"：`validate()` 里的 `structure_problem()` 会先做一遍
      结构检查，缺键的规则**留一条 `[规则格式异常]` 告警**再跳过 ——
      否则这条规则会永远不生效且无人知晓（见 `structure_problem` 上方说明）。
      本函数这里是**第二道防线**：即使结构检查漏掉了某种畸形，
      求值本身也不许抛。
    """
    field = cond.get("field")
    val = get_by_path(recipe, field) if field else None
    if val is None:
        return False
    op = cond.get("op")
    if not op or "value" not in cond:
        return False
    if op == "intersect":
        return bool(set(as_list(val)) & set(as_list(cond.get("value"))))
    if op == "contains":
        return str(cond.get("value")) in str(val)
    if op == "equals":
        return str(val) == str(cond.get("value"))
    return False


def eval_trigger(recipe: Dict[str, Any], trigger: Dict[str, Any]) -> bool:
    results = [eval_condition(recipe, c) for c in trigger.get("conditions", [])]
    if not results:
        return False
    return all(results) if trigger.get("op", "any") == "all" else any(results)


# ---------------------------------------------------------------- 四种检查器
def check_forbidden_terms(recipe: Dict[str, Any], constraint: Dict[str, Any]) -> List[str]:
    """forbidden_terms：禁止出现某些词。aliases 做同义映射，采用双向包含。
    返回命中的**规范词**（即 rule 里 terms 的写法），这样 action.suggestions 才查得到。"""
    hits: List[str] = []
    aliases = constraint.get("aliases", {})
    for scope in constraint.get("scope", []):
        for v in as_list(get_by_path(recipe, scope)):
            norm = aliases.get(str(v), str(v))
            if len(norm) < 2:                   # ★ 单字词不参与匹配，避免误报
                continue
            for t in constraint.get("terms", []):
                if len(t) < 2:
                    continue
                if (t in norm or norm in t) and t not in hits:   # 双向包含，容忍"莲纹"/"莲花"
                    hits.append(t)
    return hits


def check_required_evidence(recipe: Dict[str, Any], constraint: Dict[str, Any]) -> List[str]:
    """required_evidence：要求某字段有依据。
    该字段必须存在且非空；每一项都要是一个像样的词条——单字项（如「福」）视为没给出依据。
    字段整个为空时返回字段路径本身，告警里能直接看出是哪个字段空着。

    ★ 漏写 constraint.field → 返回 []（这条规则查不了就不查），不抛 KeyError。"""
    field = constraint.get("field")
    if not field:
        return []
    items = [str(x).strip() for x in as_list(get_by_path(recipe, field)) if str(x).strip()]
    if not items:
        return [field]
    return [x for x in items if len(x) < 2]


def check_domain_check(recipe: Dict[str, Any], constraint: Dict[str, Any]) -> List[str]:
    """domain_check：取值须在允许域内。列表逐项校验，比对忽略大小写。返回越界值列表。

    ★ 漏写 constraint.field → 返回 []，不抛 KeyError。"""
    field = constraint.get("field")
    if not field:
        return []
    allowed = {str(x).upper() for x in constraint.get("allowed", [])}
    return [str(v).strip()
            for v in as_list(get_by_path(recipe, field))
            if str(v).strip() and str(v).strip().upper() not in allowed]


def check_dependency(recipe: Dict[str, Any], constraint: Dict[str, Any]) -> List[str]:
    """dependency：if_field 有值时，then_field 必须有值。返回**缺失的那个字段路径**。

    ★★ 两个键都必须 `.get()`（2026-10 修）：漏写 then_field 原来抛 KeyError，
      与 `eval_condition` 漏 op 是同一类事故 —— 一条规则写错，
      `validate()` 整轮中断，25 条规则全部静默失效。
      缺键时返回 []（前置/后置字段都没指定，这条依赖无从判断，跳过）。
      ★ 不能退化成 `[str(get("then_field", ""))]` —— 那会产出一条 term 为空的
        无意义告警，比不报还容易误导。
    """
    if_field = constraint.get("if_field")
    then_field = constraint.get("then_field")
    if not if_field or not then_field:
        return []
    if not get_by_path(recipe, if_field):
        return []
    if get_by_path(recipe, then_field):
        return []
    return [str(then_field)]


CHECKERS = {
    "forbidden_terms":   check_forbidden_terms,
    "required_evidence": check_required_evidence,
    "domain_check":      check_domain_check,
    "dependency":        check_dependency,
}


# ---------------------------------------------------------------- 结构守卫
#
# ★★ 为什么要有"结构守卫"，而不是只靠 `.get()` 静默降级（2026-10）
#
#   只做 `.get()` + "取值失败 → 条件不成立"，坏规则会**彻底静默**：
#   `eval_condition` 直接 return False、检查器直接 return [] —— 连一条告警都没有，
#   而 `app.py` 在 violations 为空时会打印「未检出文化规则违规」。
#   于是一条写坏的规则能让界面**信心十足地宣布没有违规**。崩了至少知道，静默是把骗自己写进产品里。
#
#   所以分两条**可区分**的路径，都是 low、都不中断整轮循环：
#     结构写错        → `[规则格式异常] …，已跳过该条`（`rule_schema_error` 负责）
#     跑起来才抛异常  → `[规则执行异常] …，已跳过该条`（try/except 负责）
#
# ★★ 必需键清单**只有一份实现**（`rule_schema_error`）。
#   `scripts/check_rules.py` 已改为 import 本函数，不再自己维护一套 ——
#   分工：静态脚本 = 提交前拦（还能查 id 唯一性/分类分布等 lint）；
#        运行期 = 兜底留痕（规则库可能被程序改写或在别处加载）。
#   项目历史上栽过"两套实现必然发散"，这次不重复。
_TRIGGER_OPS = ("intersect", "contains", "equals")

# 各约束类型的必需键 → 期望类型（与 docs/schema.md §2 一致）
_CONSTRAINT_SPEC = {
    "forbidden_terms":   {"scope": list, "terms": list},
    "required_evidence": {"field": str},
    "domain_check":      {"field": str, "allowed": list},
    "dependency":        {"if_field": str, "then_field": str},
}


def format_alert(rule: Any, reason: str) -> Dict[str, Any]:
    """构造一条「规则格式异常」告警（low、term 空、带 rule_id，便于直接定位规则）。

    ★ 文案格式是对外契约（QA 用例按它切分原因文本）：
      以 `[规则格式异常]` 开头、以 `，已跳过该条` 结尾、中间是具体原因。
    """
    r = rule if isinstance(rule, dict) else {}
    return {
        "rule_id": r.get("id", "?"), "name": r.get("name", ""),
        "severity": "low", "source": r.get("source", ""), "term": "",
        "message": f"[规则格式异常] {reason}，已跳过该条",
    }


def rule_schema_error(rule: Any) -> Optional[str]:
    """检查一条规则的结构是否合法，返回**第一处**问题的中文描述；None = 结构合法。

    ★ 调用位置：必须在 `validate()` 里、**在任何 `c.get(...)` / `CHECKERS.get(...)`
      之前**。`constraint` 写成字符串时 `c.get` 本身抛 AttributeError；
      `type` 写成列表时 `CHECKERS.get([...])` 抛 `TypeError: unhashable type` ——
      两类异常都发生在查表处，晚一步调用照样崩。

    ★ `value` 只要求**键存在**，不要求非空：R009/R014/R024 三条规则正是靠
      `"value": ""` 工作的，要求非空会废掉它们。
    """
    if not isinstance(rule, dict):
        return f"规则项不是对象（{type(rule).__name__}）"

    trig = rule.get("trigger")
    if not isinstance(trig, dict):
        return f"trigger 缺失或不是对象（{type(trig).__name__}）"
    conds = trig.get("conditions")
    if not isinstance(conds, list) or not conds:
        return "trigger.conditions 缺失或为空"
    for i, c in enumerate(conds):
        if not isinstance(c, dict):
            return f"trigger.conditions[{i}] 不是对象"
        if not isinstance(c.get("field"), str) or not c.get("field"):
            return f"trigger.conditions[{i}] 的 field 缺失或不是字符串"
        op = c.get("op")
        if not isinstance(op, str) or not op:
            return f"trigger.conditions[{i}] 的 op 缺失或不是字符串"
        if op not in _TRIGGER_OPS:
            return f"trigger.conditions[{i}] 的 op 非法：{op}"
        if "value" not in c:
            return f"trigger.conditions[{i}] 缺 value"

    cst = rule.get("constraint")
    if not isinstance(cst, dict):
        return f"constraint 缺失或不是对象（{type(cst).__name__}）"
    ctype = cst.get("type")
    if not isinstance(ctype, str) or not ctype:
        return f"constraint.type 缺失或不是字符串（{type(ctype).__name__}）"
    if ctype not in CHECKERS:
        return f"未知 constraint.type：{ctype}"
    for k, ty in _CONSTRAINT_SPEC[ctype].items():
        if not isinstance(cst.get(k), ty):
            return f"constraint.{k} 缺失或类型不对（{ctype} 需要 {ty.__name__}）"

    action = rule.get("action")
    if not isinstance(action, dict):
        return f"action 缺失或不是对象（{type(action).__name__}）"
    if not isinstance(action.get("message"), str):
        return "action.message 缺失或不是字符串"
    return None


# ---------------------------------------------------------------- 主入口
def validate(recipe: Dict[str, Any], rules: List[Dict[str, Any]],
             severity_order: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """对配方逐条求值，返回告警列表（按 severity 排序）。

    每个检查器统一返回**命中词列表**，主循环只负责遍历与组装告警
    —— 新增一种约束类型 = 写一个检查器 + 在 CHECKERS 里加一行。
    """
    order = severity_order or SEVERITY_ORDER
    alerts: List[Dict[str, Any]] = []

    for r in rules:
        # ★★ 第一件事就是**整条规则的结构检查**，且必须在任何 `c.get(...)` /
        #   `CHECKERS.get(...)` 之前：`constraint` 写成字符串时 `c.get` 直接抛
        #   AttributeError；`type` 写成列表时 `CHECKERS.get([...])` 抛
        #   TypeError: unhashable type —— 两类都发生在查表处，晚一步调用照样崩。
        #   结构有问题 → 留一条 low 告警（不再静默），其余规则照常跑。
        err = rule_schema_error(r)
        if err:
            alerts.append(format_alert(r, err))
            continue

        # ★★ 此处能"直取"，是 `rule_schema_error` 的不变量，**不是**假设：
        #   · constraint 必是 dict（否则上面已 continue）
        #   · constraint.type 必是非空 str（`isinstance(ctype, str)` 在
        #     `rule_schema_error` 里，且它排在 `CHECKERS[...]` **之前**）
        #   ⚠️ 维护约定：谁要把 schema 检查挪到查表之后，`CHECKERS[["x"]]` 会立刻
        #      抛 TypeError: unhashable type —— 那是"整层校验静默失效"的入口，
        #      动这段顺序前先看 `rule_schema_error` 的注释。
        c = r["constraint"]
        ctype = c["type"]
        checker = CHECKERS[ctype]

        # ★★ 逐条兜底（2026-10）：结构合法但**跑起来**才抛异常（数据脏、实现缺陷）
        #   → 记一条 `[规则执行异常]` 并继续，绝不中断整轮循环。
        #   异常一旦冒出 validate()，pipeline.run() 的 try/except 会把 violations 置空，
        #   于是 25 条规则全部静默失效、界面照常出图 —— 那才是最坏的失败模式。
        try:
            fired = eval_trigger(recipe, r.get("trigger", {}))
        except Exception as e:                  # noqa: BLE001 —— 兜底必须全捕获
            alerts.append({
                "rule_id": r.get("id", "?"), "name": r.get("name", ""),
                "severity": "low", "source": r.get("source", ""), "term": "",
                "message": f"[规则执行异常] trigger 求值失败（{type(e).__name__}: {e}），已跳过该条",
            })
            continue
        if not fired:
            continue

        action = r.get("action", {})
        suggestions = action.get("suggestions", {}) if isinstance(action, dict) else {}
        tpl = action.get("message", "") if isinstance(action, dict) else ""
        try:
            terms = list(checker(recipe, c))
        except Exception as e:                  # noqa: BLE001
            alerts.append({
                "rule_id": r.get("id", "?"), "name": r.get("name", ""),
                "severity": "low", "source": r.get("source", ""), "term": "",
                "message": (f"[规则执行异常] 检查器 {ctype} 求值失败"
                            f"（{type(e).__name__}: {e}），已跳过该条"),
            })
            continue
        for term in terms:
            alerts.append({
                "rule_id": r.get("id", ""),
                "name": r.get("name", ""),
                "severity": r.get("severity", "low"),
                "source": r.get("source", ""),       # ★ 每条告警都带依据，保证可审计
                "term": term,
                "message": render_message(
                    tpl, term=term,
                    suggestion=suggestions.get(term, "传统吉祥纹样"),
                ),
            })

    alerts.sort(key=lambda a: order.index(a["severity"])
                if a["severity"] in order else len(order))
    return alerts
