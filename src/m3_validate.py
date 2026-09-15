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
    val = get_by_path(recipe, cond["field"])
    if val is None:
        return False
    op = cond["op"]
    if op == "intersect":
        return bool(set(as_list(val)) & set(as_list(cond["value"])))
    if op == "contains":
        return cond["value"] in str(val)
    if op == "equals":
        return str(val) == str(cond["value"])
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
    字段整个为空时返回字段路径本身，告警里能直接看出是哪个字段空着。"""
    field = constraint["field"]
    items = [str(x).strip() for x in as_list(get_by_path(recipe, field)) if str(x).strip()]
    if not items:
        return [field]
    return [x for x in items if len(x) < 2]


def check_domain_check(recipe: Dict[str, Any], constraint: Dict[str, Any]) -> List[str]:
    """domain_check：取值须在允许域内。列表逐项校验，比对忽略大小写。返回越界值列表。"""
    allowed = {str(x).upper() for x in constraint.get("allowed", [])}
    return [str(v).strip()
            for v in as_list(get_by_path(recipe, constraint["field"]))
            if str(v).strip() and str(v).strip().upper() not in allowed]


def check_dependency(recipe: Dict[str, Any], constraint: Dict[str, Any]) -> List[str]:
    """dependency：if_field 有值时，then_field 必须有值。返回**缺失的那个字段路径**。"""
    if not get_by_path(recipe, constraint["if_field"]):
        return []
    if get_by_path(recipe, constraint["then_field"]):
        return []
    return [str(constraint.get("then_field", ""))]


CHECKERS = {
    "forbidden_terms":   check_forbidden_terms,
    "required_evidence": check_required_evidence,
    "domain_check":      check_domain_check,
    "dependency":        check_dependency,
}


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
        c = r.get("constraint", {})
        checker = CHECKERS.get(c.get("type"))
        if checker is None:                     # 未知 type → 留痕并跳过，绝不让管线崩掉
            alerts.append({
                "rule_id": r.get("id", "?"), "name": r.get("name", ""),
                "severity": "low", "source": r.get("source", ""), "term": "",
                "message": f"[规则格式异常] 未知 constraint.type：{c.get('type')}",
            })
            continue
        if not eval_trigger(recipe, r.get("trigger", {})):
            continue

        action = r.get("action", {})
        suggestions = action.get("suggestions", {})
        tpl = action.get("message", "")
        for term in checker(recipe, c):
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
