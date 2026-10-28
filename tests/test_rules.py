# tests/test_rules.py
"""M3 文化准确性校验引擎（src/m3_validate.py）的单元测试。

被测对象是纯函数：不加载模型、不调 API，因此可以做真正的单元测试。
测试分三层：
  1. 基础工具与 trigger 求值 —— 逐条锁定判定口径（含边界：缺失字段、单字词、大小写）。
  2. 四个检查器 —— 各自正反例，重点是「单字词不参与匹配」这类防误报逻辑。
  3. validate 主流程 —— 用**真实**规则库 rules/culture_rules.json 跑通，
     并验证排序、未知 type 兜底、真实违规配方能被拦下、合法配方不产生误报。

运行：python -m unittest tests.test_rules -v
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:                      # 允许从任意工作目录运行
    sys.path.insert(0, str(ROOT))

from src.m3_validate import (                      # noqa: E402
    CHECKERS,
    SEVERITY_ORDER,
    as_list,
    check_dependency,
    check_domain_check,
    check_forbidden_terms,
    check_required_evidence,
    eval_condition,
    eval_trigger,
    get_by_path,
    render_message,
    validate,
)

RULES_PATH = ROOT / "rules" / "culture_rules.json"
SAMPLES_PATH = ROOT / "data" / "samples.json"


def load_rules():
    with RULES_PATH.open(encoding="utf-8") as f:
        return json.load(f)


RULES = load_rules()

# 违规配方：婚庆 + 菊花纹。
#   - occasion「婚庆」在受控词表内，故只应触发 R001，不应顺带触发 R024。
#   - 母题名「菊花纹」与 elements「菊花」均取自 data/samples.json（WENYANG-004），
#     且确实命中 R001 的 terms（"菊花" 是 "菊花纹" 的子串）。
WEDDING_CHRYSANTHEMUM = {
    "intent": {"occasion": ["婚庆"], "purpose": "礼品包装",
               "style": "传统窗花", "blessing": "百年好合"},
    "structure": {"center_motif": {"name": "菊花纹", "elements": ["菊花"]},
                  "symmetry": "二轴对称"},
    "palette": {"primary": "#C8102E", "secondary": "#D4AF37",
                "scheme_basis": "传统点染配色"},
}

# 合法配方：春节 + 缠枝莲纹（WENYANG-001），字段完整。
# 所有 25 条规则要么 trigger 不成立，要么检查器返回空 —— 应零告警。
VALID_RECIPE = {
    "intent": {"occasion": ["春节"], "purpose": "礼品包装",
               "style": "传统窗花", "blessing": "连年有余"},
    "structure": {"center_motif": {"name": "缠枝莲纹",
                                   "elements": ["莲花", "卷草", "藤蔓"]},
                  "border": {"pattern": "卷草纹", "width_ratio": 0.15},
                  "corner": {"pattern": "回纹"},
                  "symmetry": "四轴对称"},
    "palette": {"primary": "#C8102E", "secondary": "#D4AF37",
                "scheme_basis": "传统点染配色"},
}


class PathHelperTest(unittest.TestCase):
    """get_by_path / as_list / render_message 三个基础工具。"""

    def test_get_by_path_walks_nested_dicts(self):
        recipe = {"intent": {"occasion": ["婚庆"]},
                  "structure": {"center_motif": {"name": "菊花纹"}}}
        self.assertEqual(get_by_path(recipe, "structure.center_motif.name"), "菊花纹")
        self.assertEqual(get_by_path(recipe, "intent.occasion"), ["婚庆"])

    def test_get_by_path_returns_none_for_missing_branch(self):
        # 分支缺失、中间节点是 list、空路径，都不能抛异常，统一给 None
        recipe = {"intent": {"occasion": ["婚庆"]}}
        self.assertIsNone(get_by_path(recipe, "structure.center_motif.name"))
        self.assertIsNone(get_by_path(recipe, "intent.occasion.0"))
        self.assertIsNone(get_by_path(recipe, ""))

    def test_as_list_normalizes_none_scalar_and_list(self):
        self.assertEqual(as_list(None), [])
        self.assertEqual(as_list("婚庆"), ["婚庆"])
        self.assertEqual(as_list(["婚庆", "寿诞"]), ["婚庆", "寿诞"])
        self.assertEqual(as_list(0), [0])

    def test_render_message_survives_missing_placeholder(self):
        # 一条规则写错占位符，不能让整个校验层崩掉
        self.assertEqual(render_message("不宜「{term}」", term="菊花"), "不宜「菊花」")
        self.assertEqual(render_message("不宜「{unknown}」", term="菊花"), "不宜「{unknown}」")


class TriggerEvalTest(unittest.TestCase):
    """eval_condition 的三种 op 与 eval_trigger 的 any/all。"""

    def test_intersect_matches_when_value_shares_a_member(self):
        recipe = {"intent": {"occasion": ["婚庆", "寿诞"]}}
        cond = {"field": "intent.occasion", "op": "intersect", "value": ["婚庆"]}
        self.assertTrue(eval_condition(recipe, cond))

    def test_intersect_requires_exact_member_not_substring(self):
        # 「春节」不应被「婚庆」的 intersect 命中（区别于 contains）
        recipe = {"intent": {"occasion": ["春节"]}}
        cond = {"field": "intent.occasion", "op": "intersect", "value": ["婚庆"]}
        self.assertFalse(eval_condition(recipe, cond))

    def test_contains_empty_needle_is_true_when_field_present(self):
        # R009/R014 依赖这条口径：value="" 时只要字段有值就算命中
        recipe = {"intent": {"occasion": ["春节"]}}
        cond = {"field": "intent.occasion", "op": "contains", "value": ""}
        self.assertTrue(eval_condition(recipe, cond))

    def test_contains_is_false_when_field_missing(self):
        # 字段缺失时必须先被 None 挡住，否则 "" in "None" 会误命中所有规则
        cond = {"field": "palette.scheme_basis", "op": "contains", "value": ""}
        self.assertFalse(eval_condition({}, cond))

    def test_equals_compares_stringified_scalars(self):
        cond = {"field": "intent.occasion", "op": "equals", "value": "婚庆"}
        self.assertTrue(eval_condition({"intent": {"occasion": "婚庆"}}, cond))

    def test_equals_does_not_flatten_list_field(self):
        # 已知口径：equals 不做 list 展平，["婚庆"] 的字符串形式不等于 "婚庆"
        cond = {"field": "intent.occasion", "op": "equals", "value": "婚庆"}
        self.assertFalse(eval_condition({"intent": {"occasion": ["婚庆"]}}, cond))

    def test_unknown_op_is_false_not_exception(self):
        cond = {"field": "intent.occasion", "op": "regex", "value": "婚"}
        self.assertFalse(eval_condition({"intent": {"occasion": ["婚庆"]}}, cond))

    def test_trigger_without_conditions_is_false(self):
        self.assertFalse(eval_trigger({"intent": {"occasion": ["婚庆"]}}, {}))

    def test_trigger_any_needs_only_one_condition(self):
        trigger = {"op": "any", "conditions": [
            {"field": "intent.occasion", "op": "intersect", "value": ["婚庆"]},
            {"field": "intent.style", "op": "equals", "value": "传统窗花"},
        ]}
        recipe = {"intent": {"occasion": ["婚庆"]}}
        self.assertTrue(eval_trigger(recipe, trigger))

    def test_trigger_all_requires_every_condition(self):
        # 同一组 conditions，op=all 时缺一条就该失败
        trigger = {"op": "all", "conditions": [
            {"field": "intent.occasion", "op": "intersect", "value": ["婚庆"]},
            {"field": "intent.style", "op": "equals", "value": "传统窗花"},
        ]}
        recipe = {"intent": {"occasion": ["婚庆"]}}
        self.assertFalse(eval_trigger(recipe, trigger))
        recipe["intent"]["style"] = "传统窗花"
        self.assertTrue(eval_trigger(recipe, trigger))


class ForbiddenTermsTest(unittest.TestCase):
    """check_forbidden_terms：命中、不命中、aliases 映射、单字词防误报、去重。"""

    def test_hits_real_rule_term_via_bidirectional_containment(self):
        # 「菊花」是「菊花纹」的子串 —— 双向包含容错，返回规则里的规范词
        recipe = {"structure": {"center_motif": {"name": "菊花纹"}}}
        constraint = {"scope": ["structure.center_motif.name"],
                      "terms": ["菊花", "白菊", "挽联"]}
        self.assertEqual(check_forbidden_terms(recipe, constraint), ["菊花"])

    def test_returns_empty_when_no_term_matches(self):
        recipe = {"structure": {"center_motif": {"name": "缠枝莲纹"}}}
        constraint = {"scope": ["structure.center_motif.name"],
                      "terms": ["菊花", "白菊", "挽联"]}
        self.assertEqual(check_forbidden_terms(recipe, constraint), [])

    def test_aliases_map_short_synonym_to_canonical_term(self):
        # aliases 的意义：配方里写的是别名，告警必须回落到规则表的规范词，
        # 否则 action.suggestions 查不到建议
        recipe = {"m": {"name": "菊"}}
        constraint = {"scope": ["m.name"], "terms": ["菊花"], "aliases": {"菊": "菊花"}}
        self.assertEqual(check_forbidden_terms(recipe, constraint), ["菊花"])

    def test_aliases_map_variant_wording_to_canonical_term(self):
        recipe = {"m": {"name": "白菊纹"}}
        constraint = {"scope": ["m.name"], "terms": ["白菊"], "aliases": {"白菊纹": "白菊"}}
        self.assertEqual(check_forbidden_terms(recipe, constraint), ["白菊"])

    def test_single_char_value_is_never_matched(self):
        # ★ 防误报关键：单字取值整条跳过，否则「菊」会命中「菊花」造成大量误报
        recipe = {"structure": {"center_motif": {"name": "菊"}}}
        constraint = {"scope": ["structure.center_motif.name"], "terms": ["菊花"]}
        self.assertEqual(check_forbidden_terms(recipe, constraint), [])

    def test_single_char_term_is_never_matched(self):
        # 规则本身写了单字 term 时也不参与匹配（避免「花」命中一切花卉母题）
        recipe = {"structure": {"center_motif": {"name": "莲花"}}}
        constraint = {"scope": ["structure.center_motif.name"], "terms": ["花"]}
        self.assertEqual(check_forbidden_terms(recipe, constraint), [])

    def test_same_term_in_two_scopes_is_reported_once(self):
        recipe = {"structure": {"center_motif": {"name": "菊花纹", "elements": ["菊花"]}}}
        constraint = {"scope": ["structure.center_motif.name",
                                "structure.center_motif.elements"],
                      "terms": ["菊花"]}
        self.assertEqual(check_forbidden_terms(recipe, constraint), ["菊花"])

    def test_missing_scope_field_yields_no_hit(self):
        constraint = {"scope": ["structure.border.pattern"], "terms": ["卷草纹"]}
        self.assertEqual(check_forbidden_terms({}, constraint), [])


class RequiredEvidenceTest(unittest.TestCase):
    """check_required_evidence：空字段返回字段路径；单字项视为无依据。"""

    def test_empty_field_returns_field_path(self):
        constraint = {"field": "intent.blessing"}
        self.assertEqual(check_required_evidence({"intent": {"blessing": []}}, constraint),
                         ["intent.blessing"])

    def test_missing_field_returns_field_path(self):
        constraint = {"field": "structure.center_motif.elements"}
        self.assertEqual(check_required_evidence({}, constraint),
                         ["structure.center_motif.elements"])

    def test_whitespace_only_value_counts_as_missing(self):
        constraint = {"field": "intent.blessing"}
        self.assertEqual(check_required_evidence({"intent": {"blessing": "   "}}, constraint),
                         ["intent.blessing"])

    def test_single_char_item_is_reported_as_unevidenced(self):
        # 「福」这种单字不构成可推导的寓意，返回值是那个不合格词条本身
        constraint = {"field": "intent.blessing"}
        self.assertEqual(check_required_evidence({"intent": {"blessing": "福"}}, constraint),
                         ["福"])

    def test_complete_items_pass(self):
        constraint = {"field": "intent.blessing"}
        recipe = {"intent": {"blessing": ["五福临门", "连年有余"]}}
        self.assertEqual(check_required_evidence(recipe, constraint), [])


class DomainCheckTest(unittest.TestCase):
    """check_domain_check：越界值、大小写不敏感、空值忽略。"""

    def test_out_of_range_value_is_returned(self):
        constraint = {"field": "palette.primary", "allowed": ["#C8102E", "#D4AF37"]}
        self.assertEqual(
            check_domain_check({"palette": {"primary": "#123456"}}, constraint), ["#123456"])

    def test_value_in_domain_passes(self):
        constraint = {"field": "intent.occasion", "allowed": ["春节", "婚庆", "寿诞"]}
        self.assertEqual(check_domain_check({"intent": {"occasion": ["婚庆"]}}, constraint), [])

    def test_comparison_is_case_insensitive(self):
        constraint = {"field": "palette.primary", "allowed": ["#C8102E"]}
        self.assertEqual(check_domain_check({"palette": {"primary": "#c8102e"}}, constraint), [])

    def test_empty_and_missing_values_are_ignored(self):
        # 空值交给 required_evidence 规则处理，domain_check 不重复告警
        constraint = {"field": "palette.primary", "allowed": ["#C8102E"]}
        self.assertEqual(check_domain_check({"palette": {"primary": ""}}, constraint), [])
        self.assertEqual(check_domain_check({}, constraint), [])

    def test_list_field_is_checked_item_by_item(self):
        constraint = {"field": "intent.occasion", "allowed": ["春节", "婚庆"]}
        recipe = {"intent": {"occasion": ["婚庆", "情人节"]}}
        self.assertEqual(check_domain_check(recipe, constraint), ["情人节"])


class DependencyTest(unittest.TestCase):
    """check_dependency：if_field 有值而 then_field 缺失 → 返回字段路径。"""

    def test_missing_then_field_returns_its_path(self):
        constraint = {"if_field": "structure.border.pattern",
                      "then_field": "structure.border.width_ratio"}
        recipe = {"structure": {"border": {"pattern": "卷草纹"}}}
        self.assertEqual(check_dependency(recipe, constraint), ["structure.border.width_ratio"])

    def test_both_present_yields_nothing(self):
        constraint = {"if_field": "structure.border.pattern",
                      "then_field": "structure.border.width_ratio"}
        recipe = {"structure": {"border": {"pattern": "卷草纹", "width_ratio": 0.15}}}
        self.assertEqual(check_dependency(recipe, constraint), [])

    def test_if_field_absent_yields_nothing(self):
        constraint = {"if_field": "intent.blessing",
                      "then_field": "structure.center_motif.elements"}
        self.assertEqual(check_dependency({}, constraint), [])


class ValidateFlowTest(unittest.TestCase):
    """validate 主流程，全部使用真实规则库。"""

    def test_real_rules_produce_wellformed_alerts(self):
        alerts = validate(WEDDING_CHRYSANTHEMUM, RULES)
        self.assertIsInstance(alerts, list)
        self.assertTrue(alerts)
        for a in alerts:
            self.assertEqual(
                set(a), {"rule_id", "name", "severity", "source", "term", "message"})
            self.assertTrue(a["rule_id"])
            self.assertTrue(a["source"], "每条告警都必须带依据，否则不可审计")
            self.assertIn(a["severity"], SEVERITY_ORDER)

    def test_wedding_chrysanthemum_triggers_r001(self):
        alerts = validate(WEDDING_CHRYSANTHEMUM, RULES)
        hits = [a for a in alerts if a["rule_id"] == "R001"]
        self.assertEqual(len(hits), 1, "婚庆 + 菊花纹 应且仅应命中一次 R001")
        alert = hits[0]
        self.assertEqual(alert["severity"], "high")
        self.assertEqual(alert["term"], "菊花")
        self.assertIn("菊花", alert["message"])
        # 建议词来自 action.suggestions，验证检查器与建议表是连通的
        self.assertIn("牡丹", alert["message"])

    def test_valid_recipe_has_no_high_alerts(self):
        alerts = validate(VALID_RECIPE, RULES)
        highs = [a for a in alerts if a["severity"] == "high"]
        self.assertEqual(highs, [], "合法配方不应产生 high 级告警")

    def test_valid_recipe_has_no_alerts_at_all(self):
        # 防误报回归：合法配方若被任何规则误判，都说明 trigger 或检查器口径过宽
        alerts = validate(VALID_RECIPE, RULES)
        self.assertEqual(
            alerts, [],
            "合法配方出现误报：" + ", ".join(f"{a['rule_id']}({a['severity']})" for a in alerts))

    def test_unknown_constraint_type_warns_low_instead_of_crashing(self):
        rules = [{
            "id": "R999", "name": "格式异常规则", "severity": "high", "source": "测试用例",
            "trigger": {"op": "any", "conditions": [
                {"field": "intent.occasion", "op": "contains", "value": ""}]},
            "constraint": {"type": "no_such_checker"},
            "action": {"message": "{term}", "suggestions": {}},
        }]
        alerts = validate({"intent": {"occasion": ["春节"]}}, rules)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["rule_id"], "R999")
        self.assertEqual(alerts[0]["severity"], "low")
        self.assertEqual(alerts[0]["term"], "")
        self.assertIn("no_such_checker", alerts[0]["message"])

    def test_alerts_are_sorted_high_medium_low(self):
        # 故意构造跨三档的配方：R001(high) / R006,R007,R021(medium) / R008..R020(low)
        recipe = {"intent": {"occasion": ["婚庆"]},
                  "structure": {"center_motif": {"name": "菊花纹"},
                                "symmetry": "二轴对称"},
                  "palette": {"primary": "#123456"}}
        alerts = validate(recipe, RULES)
        severities = [a["severity"] for a in alerts]
        self.assertEqual(set(severities), {"high", "medium", "low"}, severities)
        ranks = [SEVERITY_ORDER.index(s) for s in severities]
        self.assertEqual(ranks, sorted(ranks), f"告警未按 severity 排序：{severities}")
        self.assertEqual(alerts[0]["severity"], "high")
        self.assertEqual(alerts[-1]["severity"], "low")

    def test_custom_severity_order_is_respected(self):
        recipe = {"intent": {"occasion": ["婚庆"]},
                  "structure": {"center_motif": {"name": "菊花纹"}},
                  "palette": {"primary": "#123456"}}
        alerts = validate(recipe, RULES, severity_order=["low", "medium", "high"])
        self.assertEqual(alerts[0]["severity"], "low")
        self.assertEqual(alerts[-1]["severity"], "high")


class RuleLibraryTest(unittest.TestCase):
    """规则库结构断言 —— 规则是数据，数据坏了引擎再对也没用。"""

    def test_has_25_rules_with_unique_ids(self):
        self.assertEqual(len(RULES), 25)
        ids = [r["id"] for r in RULES]
        self.assertEqual(len(set(ids)), 25, "存在重复的规则 id")

    def test_every_rule_has_required_keys(self):
        required = {"id", "name", "severity", "trigger", "constraint", "action", "source"}
        for r in RULES:
            missing = required - set(r)
            self.assertEqual(missing, set(), f"{r.get('id')} 缺少键 {missing}")
            self.assertIn("type", r["constraint"], f"{r['id']} 的 constraint 缺 type")
            self.assertIn("conditions", r["trigger"], f"{r['id']} 的 trigger 缺 conditions")
            self.assertIn(r["severity"], SEVERITY_ORDER, f"{r['id']} 的 severity 非法")

    def test_all_constraint_types_have_a_checker(self):
        used = {r["constraint"]["type"] for r in RULES}
        self.assertEqual(used, {"forbidden_terms", "required_evidence",
                                "domain_check", "dependency"})
        self.assertTrue(used.issubset(set(CHECKERS)),
                        f"缺少检查器：{used - set(CHECKERS)}")

    def test_every_rule_source_is_non_empty(self):
        # 规则可审计是本项目的核心立论，source 为空等于无法核查
        for r in RULES:
            self.assertTrue(r["source"].strip(), f"{r['id']} 的 source 为空")


class FixtureDataTest(unittest.TestCase):
    """校验测试样本本身是真实的 —— 防止用例随数据变动而静默失真。"""

    def test_fixture_motifs_exist_in_samples(self):
        with SAMPLES_PATH.open(encoding="utf-8") as f:
            samples = json.load(f)
        by_name = {s["name"]: s for s in samples}
        self.assertIn("缠枝莲纹", by_name)
        self.assertIn("菊花纹", by_name)
        self.assertIn("菊花", by_name["菊花纹"]["elements"],
                      "违规配方里的「菊花」须与样本库构成元素一致")


class RuleSchemaGuardTest(unittest.TestCase):
    """坏规则的隔离性与留痕：一条规则写错，不能拖死整轮，也不能静默消失。

    ★ 两条失败路径必须严格区分（口径由 team-lead 定死，别混）：
      · **结构不合法**（漏键 / constraint 不是 dict / rule 不是 dict）
        → `[规则格式异常] <原因>，已跳过该条`，severity=low、term=""
      · **结构合法但运行期抛异常**（terms 里放数字、aliases 写 null）
        → `[规则执行异常] …`，severity=low、term=""

    为什么这条重要：`app.py` 在 violations 为空时显示「未检出文化规则违规」。
    一条写坏的规则若既不报错也不留痕，界面就会**确信地宣布没有违规**
    —— 这比崩溃危险，崩溃至少知道自己在崩。
    """

    RECIPE = {"intent": {"occasion": ["婚庆"]},
              "structure": {"center_motif": {"name": "菊花纹", "elements": ["菊花"]}}}

    @staticmethod
    def _rule(rule_id, **override):
        """构造一条默认必命的规则（婚庆 + 菊花纹 → 命中「菊花」）。"""
        rule = {
            "id": rule_id, "name": f"用例{rule_id}", "severity": "high", "source": "QA 自造",
            "trigger": {"op": "any", "conditions": [
                {"field": "intent.occasion", "op": "intersect", "value": ["婚庆"]}]},
            "constraint": {"type": "forbidden_terms",
                           "scope": ["structure.center_motif.name"], "terms": ["菊花"]},
            "action": {"message": "命中「{term}」→{suggestion}",
                       "suggestions": {"菊花": "牡丹"}},
        }
        rule.update(override)
        return rule

    def _validate_no_raise(self, rules):
        """validate() 绝不能抛 —— 抛出即整轮失效（pipeline 会清空 violations）。"""
        try:
            return validate(self.RECIPE, rules)
        except Exception as e:                       # noqa: BLE001 —— 这里就是要抓住
            self.fail(f"validate() 不应抛异常，实际抛出 {type(e).__name__}: {e}")

    def _assert_format_alert(self, alert):
        """共享断言：结构异常告警的形状与文案模板。"""
        self.assertEqual(alert["severity"], "low")
        self.assertEqual(alert["term"], "")
        msg = alert["message"]
        self.assertTrue(msg.startswith("[规则格式异常]"), f"文案前缀不符：{msg}")
        self.assertIn("已跳过该条", msg, f"文案缺少兜底说明：{msg}")
        reason = msg[len("[规则格式异常]"):].split("，已跳过该条")[0].strip()
        self.assertTrue(reason, f"文案没有指出具体原因：{msg}")

    def test_bad_rules_do_not_block_good_ones(self):
        """T1 必命中 + T2 漏 op + T3 漏 then_field + T4 漏 field → 4 条告警且不抛。"""
        rules = [
            self._rule("T1"),
            # T2：condition 漏写 op
            self._rule("T2", trigger={"op": "any", "conditions": [
                {"field": "intent.occasion", "value": ["婚庆"]}]}),
            # T3：dependency 漏写 then_field
            self._rule("T3", constraint={"type": "dependency",
                                         "if_field": "intent.occasion"}),
            # T4：required_evidence 漏写 field
            self._rule("T4", constraint={"type": "required_evidence"}),
        ]
        alerts = self._validate_no_raise(rules)

        self.assertEqual(len(alerts), 4,
                         f"应为 T1 一条 high + T2/T3/T4 各一条 low，实际："
                         f"{[(a['rule_id'], a['severity']) for a in alerts]}")
        by_id = {a["rule_id"]: a for a in alerts}

        self.assertEqual(by_id["T1"]["severity"], "high")
        self.assertEqual(by_id["T1"]["term"], "菊花", "T1 必须照常命中，不能被坏规则拖死")
        self.assertIn("牡丹", by_id["T1"]["message"], "T1 的建议词仍应来自 action.suggestions")

        for rule_id in ("T2", "T3", "T4"):
            self.assertIn(rule_id, by_id, f"{rule_id} 结构不合法，必须留一条告警，不能静默")
            self._assert_format_alert(by_id[rule_id])

    def test_guard_points_are_exhaustively_covered(self):
        """**守卫点穷举**：每新增一个属性访问，就要在这里加一条对应的畸形输入。

        ★ 这条纪律比测试本身值钱："想不全"就是"没想清守卫边界"。
          上一版只写了 3 个 case，正好漏掉 `constraint.type` 非字符串 ——
          它和 `constraint` 非 dict 是**两处不同的属性访问**，两边都以为对方管了。

        ★ 断言口径：**不抛异常 + 恰好 1 条告警 + low + term="" + 以「…异常」开头
          + 含「已跳过该条」+ 原因段非空**。前缀按**实现的实际路由**断言：
          结构写错走 `[规则格式异常]`；跑起来才抛走 `[规则执行异常]`。
          两条路径都合格，但都必须留痕 —— 静默失效是这里唯一不可接受的结果。
        """
        trig = {"op": "any", "conditions": [
            {"field": "intent.occasion", "op": "intersect", "value": ["婚庆"]}]}
        action = {"message": "m {term}", "suggestions": {}}

        def rule(**override):
            r = {"id": "X1", "name": "守卫用例", "severity": "high", "source": "QA 自造",
                 "trigger": trig, "constraint": {"type": "forbidden_terms",
                                                 "scope": ["structure.center_motif.name"],
                                                 "terms": ["菊花"]},
                 "action": action}
            r.update(override)
            return r

        fmt = "[规则格式异常]"
        exc = "[规则执行异常]"
        cases = [
            # —— 规则项本身 ——
            ("rule 不是 dict", "abc", fmt),
            ("rule 是列表", ["abc"], fmt),
            # —— constraint 容器 ——
            ("constraint 缺失", {k: v for k, v in rule().items() if k != "constraint"}, fmt),
            ("constraint 写成字符串", rule(constraint="forbidden_terms"), fmt),
            ("constraint 写成列表", rule(constraint=["forbidden_terms"]), fmt),
            # —— constraint.type（★ 上一版漏掉的那格）——
            ("constraint.type 缺失", rule(constraint={"scope": ["a"], "terms": ["菊花"]}), fmt),
            ("constraint.type 写成列表",
             rule(constraint={"type": ["forbidden_terms"], "scope": ["a"],
                              "terms": ["菊花"]}), fmt),
            ("constraint.type 写成数字",
             rule(constraint={"type": 123, "scope": ["a"], "terms": ["菊花"]}), fmt),
            ("constraint.type 是未知字符串", rule(constraint={"type": "no_such_checker"}), fmt),
            # —— trigger / conditions ——
            ("trigger 不是 dict", rule(trigger="oops"), fmt),
            ("trigger.conditions 不是列表",
             rule(trigger={"op": "any", "conditions": "x"}), fmt),
            ("condition 不是 dict", rule(trigger={"op": "any", "conditions": ["x"]}), fmt),
            ("condition 缺 field", rule(trigger={"op": "any", "conditions": [
                {"op": "intersect", "value": ["婚庆"]}]}), fmt),
            ("condition 缺 op", rule(trigger={"op": "any", "conditions": [
                {"field": "intent.occasion", "value": ["婚庆"]}]}), fmt),
            ("condition 缺 value", rule(trigger={"op": "any", "conditions": [
                {"field": "intent.occasion", "op": "intersect"}]}), fmt),
            # —— 四种约束类型各自的必需键 ——
            ("forbidden_terms 缺 scope",
             rule(constraint={"type": "forbidden_terms", "terms": ["菊花"]}), fmt),
            ("forbidden_terms 缺 terms",
             rule(constraint={"type": "forbidden_terms",
                              "scope": ["structure.center_motif.name"]}), fmt),
            ("required_evidence 缺 field", rule(constraint={"type": "required_evidence"}), fmt),
            ("domain_check 缺 allowed",
             rule(constraint={"type": "domain_check", "field": "palette.primary"}), fmt),
            ("dependency 缺 if_field",
             rule(constraint={"type": "dependency", "then_field": "structure.symmetry"}), fmt),
            ("dependency 缺 then_field",
             rule(constraint={"type": "dependency", "if_field": "intent.occasion"}), fmt),
        ]
        self.assertGreaterEqual(len(cases), 21, "守卫点至少 21 个，少一个都算漏")

        for label, bad_rule, prefix in cases:
            with self.subTest(case=label):
                alerts = self._validate_no_raise([bad_rule])
                self.assertEqual(len(alerts), 1,
                                 f"{label}：应恰好 1 条留痕告警，实际 "
                                 f"{[(a['rule_id'], a['severity']) for a in alerts]}")
                alert = alerts[0]
                self.assertEqual(alert["severity"], "low", f"{label}：severity 应为 low")
                self.assertEqual(alert["term"], "", f"{label}：term 应为空")
                self.assertIsInstance(alert["rule_id"], str, f"{label}：rule_id 应是字符串")
                msg = alert["message"]
                self.assertTrue(msg.startswith(prefix), f"{label}：文案前缀不符：{msg}")
                self.assertIn("已跳过该条", msg, f"{label}：文案缺兜底说明：{msg}")
                reason = msg[len(prefix):].split("，已跳过该条")[0].strip()
                self.assertTrue(reason, f"{label}：文案没指出具体原因：{msg}")
                if isinstance(bad_rule, dict):
                    self.assertEqual(alert["rule_id"], bad_rule["id"],
                                     f"{label}：告警应能定位到出错的规则")

    def test_runtime_exceptions_keep_execution_alert(self):
        """terms 放数字 / aliases 写 null → 走 `[规则执行异常]`，与格式异常是两条路径。"""
        rules = [
            # 结构合法（type/scope/terms 都在），但 terms 里混了非字符串 → 检查器抛 TypeError
            self._rule("T8", constraint={"type": "forbidden_terms",
                                         "scope": ["structure.center_motif.name"],
                                         "terms": [123]}),
            # aliases 写成 null → 检查器 .get() 抛 AttributeError
            self._rule("T9", constraint={"type": "forbidden_terms",
                                         "scope": ["structure.center_motif.name"],
                                         "terms": ["菊花"], "aliases": None}),
        ]
        alerts = self._validate_no_raise(rules)

        self.assertEqual(len(alerts), 2,
                         f"两条都应在运行期抛异常并各留一条告警，实际 {alerts}")
        by_id = {a["rule_id"]: a for a in alerts}
        for rule_id in ("T8", "T9"):
            self.assertIn(rule_id, by_id)
            alert = by_id[rule_id]
            self.assertEqual(alert["severity"], "low")
            self.assertEqual(alert["term"], "")
            self.assertIn("规则执行异常", alert["message"])
            # ★ 与格式异常必须可区分：这条是"跑起来才错的"，不是"结构写错的"
            self.assertNotIn("规则格式异常", alert["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
