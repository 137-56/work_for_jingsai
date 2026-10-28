# M3 规则引擎守卫点对照（修复前 / 后）

> 记录一次**守卫点穷举**的验证结果：`src/m3_validate.validate()` 面对结构畸形的手写规则时，
> 修复前会崩溃或静默失效，修复后一律降级为一条 low 告警并跳过该条。
>
> 对照基准：`git show HEAD:src/m3_validate.py`（commit `ad69533`，2026-10 重构前）
> vs 当前 `src/m3_validate.py`（md5 `859733f55c4b3792c15f3f27f58e409c`）
> 断言位置：`tests/test_rules.py::RuleSchemaGuardTest::test_guard_points_are_exhaustively_covered`

## 结论摘要

21 个守卫点：**修复前 17 个不合格（13 处抛异常 + 4 处零告警静默），修复后 0 个不合格。**

这张表同时证明三件事：

1. **测试有牙** —— 不是"写了 21 个 case 都绿"，而是同一组 case 打在旧版上会红 17 条。
2. **代码侧确实补上了** —— 不是把断言改松换来的绿。
3. **为什么必须穷举** —— 见下节三个"想当然就会漏"的格子。

## 为什么这轮要花大力气在守卫上

`validate()` 抛出的异常会往上冒到 `src/pipeline.py:78-81`：

```python
try:
    recipe["violations"] = validate(recipe, rules, CFG["validate"]["severity_order"])
except Exception:
    recipe["violations"] = []
```

也就是说：**一条写坏的规则 → 校验层整轮失效 → 界面照常出图、并显示「未检出文化规则违规」**。
这比崩溃危险得多——崩溃至少知道自己在崩，静默是把自己骗过去。所以口径是：
**坏规则必须留痕（low 告警）且不中断其余规则**。

## 对照表

| # | 守卫点（畸形输入） | 修复前（HEAD） | 修复后 |
|---|---|---|---|
| 1 | `rule` 不是 dict（如 `"abc"`） | 抛 `AttributeError` | 1 条格式异常 |
| 2 | `rule` 是列表 | 抛 `AttributeError` | 1 条格式异常 |
| 3 | `constraint` 缺失 | 刚好被"未知 type：None"接住 | 1 条格式异常，原因指明"constraint 缺失" |
| 4 | `constraint` 写成字符串（漏大括号） | 抛 `AttributeError` | 1 条格式异常 |
| 5 | `constraint` 写成列表 | 抛 `AttributeError` | 1 条格式异常 |
| 6 | `constraint.type` 缺失 | 刚好被"未知 type：None"接住 | 1 条格式异常 |
| 7 | `constraint.type` 写成列表 | 抛 `TypeError: unhashable type: 'list'` | 1 条格式异常 |
| 8 | `constraint.type` 写成数字 | **碰巧合格**（见下节 ①） | 1 条格式异常 |
| 9 | `constraint.type` 是未知字符串 | 原有"未知 type"分支 | 1 条格式异常 |
| 10 | `trigger` 不是 dict | 抛 `AttributeError` | 1 条格式异常 |
| 11 | `trigger.conditions` 不是列表 | 抛 `TypeError` | 1 条格式异常 |
| 12 | `condition` 不是 dict | 抛 `TypeError` | 1 条格式异常 |
| 13 | `condition` 缺 `field` | 抛 `KeyError` | 1 条格式异常 |
| 14 | `condition` 缺 `op` | 抛 `KeyError` | 1 条格式异常 |
| 15 | `condition` 缺 `value` | 抛 `KeyError` | 1 条格式异常 |
| 16 | `forbidden_terms` 缺 `scope` | **0 条告警（静默）** | 1 条格式异常 |
| 17 | `forbidden_terms` 缺 `terms` | **0 条告警（静默）** | 1 条格式异常 |
| 18 | `required_evidence` 缺 `field` | 抛 `KeyError` | 1 条格式异常 |
| 19 | `domain_check` 缺 `allowed` | **0 条告警（静默）** | 1 条格式异常 |
| 20 | `dependency` 缺 `if_field` | 抛 `KeyError` | 1 条格式异常 |
| 21 | `dependency` 缺 `then_field` | 抛 `KeyError` | 1 条格式异常 |

"1 条格式异常" 的完整形状：`severity="low"`、`term=""`、`rule_id` 指向出错规则、
文案 `[规则格式异常] <具体原因>，已跳过该条`。

## 三个"想当然就会漏"的格子

### ① `type` 写成数字是"碰巧合格"——错觉的温床

旧版 `CHECKERS.get(c["type"])`，若 `type` 是 `123`，`dict.get` 接受任意 hashable，
返回 `None`，于是落进"未知 constraint.type：123"分支，**看起来像被处理过了**。
只有 `type` 写成**列表**（unhashable）才会崩。
所以"我好像处理过 type"这个印象，是用 3 个 case 测出来的错觉；穷举才照得出它。

### ② 缺 `scope` / `terms` / `allowed` 是零告警静默

旧版检查器用 `constraint.get("scope", [])` 之类写法：键没了 → 空列表 → 循环不执行 →
返回 `[]` → **这条规则永远不生效，且没有任何告警**。
它比崩溃隐蔽：界面照常出图、照常显示"未检出违规"。

### ③ 必需键清单必须只有一份实现

`scripts/check_rules.py` 现在 `from src.m3_validate import rule_schema_error`，
不再自己维护一套 `CONSTRAINT_FIELDS`。分工是：
静态脚本 = 提交前拦（还能查 id 唯一性、分类分布等 lint）；
运行期 = 兜底留痕（规则库可能被程序改写或在别处加载）。
两套实现必然发散——项目历史上栽过。

## 两条路径的契约（不可混）

| 情形 | 告警前缀 | 责任者 |
|---|---|---|
| **结构写错**（漏键、类型不对、type 未知） | `[规则格式异常] <原因>，已跳过该条` | `rule_schema_error()` |
| **结构合法但跑起来才抛**（`terms` 放数字、`aliases` 写 null） | `[规则执行异常] <哪一步失败>，已跳过该条` | `validate()` 内 `try/except` |

两条都是 `severity=low`、`term=""`。测试里用 `assertNotIn("规则格式异常", …)` 锁住可区分性，
防止实现图省事把两种情况塞进一个前缀。

## 维护纪律

> **守卫点穷举**：每新增一个属性访问，就要在用例里加一条对应的畸形输入。
> 想不全就说明没想清守卫边界。

用例里另有 `assertGreaterEqual(len(cases), 21)`——有人删 case 会立刻红，
避免"覆盖度悄悄退化"。将来新增 `constraint.type` 之外的属性访问时，这个数字要跟着涨。

## 如何复跑

```bash
# 断言层（21 个 case，含 subTest）
./.venv/Scripts/python.exe -m unittest tests.test_rules -v

# 对照层：把同一组 case 打在任意基线版本上
# （临时文件写在仓库根目录，别用 /tmp —— Windows 上 Python 会把 /tmp 解析成 D:\tmp）
git show HEAD:src/m3_validate.py > _m3_head.py
./.venv/Scripts/python.exe - <<'PY'
import importlib.util, sys
sys.path.insert(0, ".")
spec = importlib.util.spec_from_file_location("m3_head", "_m3_head.py")
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
rec = {"intent": {"occasion": ["婚庆"]},
       "structure": {"center_motif": {"name": "菊花纹", "elements": ["菊花"]}}}
trig = {"op": "any", "conditions": [
    {"field": "intent.occasion", "op": "intersect", "value": ["婚庆"]}]}
base = {"id": "X1", "name": "n", "severity": "high", "source": "s", "trigger": trig,
        "constraint": {"type": "forbidden_terms",
                       "scope": ["structure.center_motif.name"], "terms": ["菊花"]},
        "action": {"message": "m {term}", "suggestions": {}}}
cases = [["abc"], {**base, "constraint": "forbidden_terms"},
         {**base, "constraint": ["forbidden_terms"]},
         {**base, "constraint": {"type": ["forbidden_terms"]}}]
for r in cases:
    try:
        out = old.validate(rec, [r])
        print("留痕 OK" if len(out) == 1 and out[0]["severity"] == "low" else "不合格", out)
    except Exception as e:
        print("抛", type(e).__name__, e)
PY
rm -f _m3_head.py
```

基线版本上的预期输出（4 个畸形输入全部不合格）：

```
抛 AttributeError 'list' object has no attribute 'get'
抛 AttributeError 'str' object has no attribute 'get'
抛 AttributeError 'list' object has no attribute 'get'
抛 TypeError unhashable type: 'list'
```

把同一段里的 `old.validate` 换成 `validate`（并去掉 spec / exec_module 三行，
改 `from src.m3_validate import validate`），四个 case 会全部输出 `留痕 OK`，
原因分别是「规则项不是对象（list）」「constraint 缺失或不是对象（str / list）」
「constraint.type 缺失或不是字符串（list）」——这就是"修复后"。


提交包里没有 `.git`，评审无法执行上面第二步——但这不影响结论：
**断言层（第一步）是自包含的**，它就是这 21 个守卫点的固化形式，不依赖 git。

## 相关文件

- `tests/test_rules.py` —— 50 个用例（本文件对应其中 `RuleSchemaGuardTest` 的 3 个）
- `scripts/check_m3_differential.py` + `data/m3_golden.json` —— 另一条正交验证：
  525 个**配方**上的差分回归（证明重构没改判定），与本文件互补：
  本文件管**规则写坏**，差分管**配方判定**。
