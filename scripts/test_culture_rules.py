# scripts/test_culture_rules.py
"""B3 验收：文化规则库的**检出率**与**误报率**。

★ 这个脚本的重点不是"能不能检出违规"，而是**"在真实配方上会不会误报"**。
   检出违规很容易（把词表写宽就行）；难的是**在真实数据上零误报**。
   本项目的教训（`SELF_REF` 判据误报 25/29、关联纹样清单手抄出错）都指向同一件事：
   **判据必须先在真数据上跑一遍，再定稿。**

测试集构成：
  · 负例（真实配方）—— `outputs/` 下管线真实产出的 recipe.json，**要求零告警**
  · 正例（构造违规）—— 五类各 1 个，**要求对应规则必须触发**

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/test_culture_rules.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.m3_validate import validate

RULES = ROOT / "rules" / "culture_rules.json"
OUTPUTS = ROOT / "outputs"


def base_recipe(rid, **over):
    """一个字段齐全的合规配方，逐用例按需覆盖。"""
    r = {
        "recipe_id": rid,
        "user_request": "测试用例",
        "schema_version": "1.0",
        "intent": {"occasion": ["节庆通用"], "purpose": "礼品包装",
                   "blessing": ["吉祥如意"], "style": "传统纹样"},
        "structure": {
            "center_motif": {"name": "缠枝莲纹", "elements": ["莲花", "卷草"], "confidence": 1.0},
            "border": {"pattern": "卷草纹", "width_ratio": 0.15},
            "corner": {"pattern": ""},
            "symmetry": "四轴对称",
        },
        "palette": {"primary": "#C8102E", "secondary": "#F2A900", "scheme_basis": "传统点染配色"},
    }
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(r.get(k), dict):
            r[k].update(v)
        else:
            r[k] = v
    return r


def deep_update(d, u):
    for k, v in u.items():
        d[k] = deep_update(d[k], v) if isinstance(v, dict) and isinstance(d.get(k), dict) else v
    return d


def _border_without_width(rid):
    """只有边饰、**没有宽度比例** —— 用来测 R016 的依赖检查。"""
    r = base_recipe(rid)
    r["structure"]["border"] = {"pattern": "卷草纹"}
    return r


# 五类各 1 个正例：期望**指定规则**必须触发
POSITIVES = [
    ("R001 婚庆禁哀悼意象",
     base_recipe("T-P01", intent={"occasion": ["婚庆"]},
                 structure={"center_motif": {"name": "菊花纹", "elements": ["菊花", "卷草"]}}),
     "R001"),
    ("R006 寓意须为完整词条",
     base_recipe("T-P02", intent={"blessing": ["福"]}),
     "R006"),
    ("R011 龙纹不得用于日常陈设",
     base_recipe("T-P03", intent={"occasion": ["日常陈设"]},
                 structure={"center_motif": {"name": "龙纹", "elements": ["龙", "云"]}}),
     "R011"),
    ("R016 有边饰须有宽度比例", _border_without_width("T-P04"), "R016"),
    ("R021 主色须落在传统色板内",
     base_recipe("T-P05", palette={"primary": "#FF00FF"}),
     "R021"),
]


def main() -> int:
    if not RULES.exists():
        sys.exit(f"[FAIL] 找不到 {RULES}")
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    print(f"规则 {len(rules)} 条\n")

    n_fail = 0

    # ---------- 负例：真实配方必须零告警 ----------
    print("=" * 62)
    print("负例：管线真实产出的配方（要求零告警）")
    print("=" * 62)
    real = sorted(OUTPUTS.glob("*/recipe.json"))
    if not real:
        print("  [警告] outputs/ 下没有真实配方 —— 误报无法验证！请先跑一次管线。")
        n_fail += 1
    fps = 0
    for p in real:
        rec = json.loads(p.read_text(encoding="utf-8"))
        alerts = validate(rec, rules)
        tag = "✅ 无告警" if not alerts else f"❌ {len(alerts)} 条告警（误报）"
        print(f"  {p.parent.name}  {tag}")
        for a in alerts:
            fps += 1
            print(f"       [{a['rule_id']}] {a['name']}  命中「{a['term']}」")
            print(f"              {a['message']}")
    n_neg = len(real)
    print(f"\n  误报：{fps} 处 / {n_neg} 个真实配方", "✅" if fps == 0 else "❌")

    # ---------- 正例：指定规则必须触发 ----------
    print()
    print("=" * 62)
    print("正例：构造违规（要求指定规则触发）")
    print("=" * 62)
    n_hit = 0
    for label, rec, want in POSITIVES:
        alerts = validate(rec, rules)
        got = {a["rule_id"] for a in alerts}
        ok = want in got
        n_hit += ok
        print(f"  {label:<28} {'✅' if ok else '❌'} 触发规则 {sorted(got) or '（无）'}")
        if not ok:
            print(f"       期望 {want} 触发，实际未触发")
        for a in alerts:
            if a["rule_id"] == want:
                print(f"       → {a['message']}")
    n_pos = len(POSITIVES)
    print(f"\n  检出：{n_hit}/{n_pos}")

    # ---------- 汇总 ----------
    print()
    print("=" * 62)
    det = n_hit / n_pos if n_pos else 0.0
    fpr = fps / n_neg if n_neg else 0.0
    print(f"  检出率   {n_hit}/{n_pos} = {det:.0%}")
    print(f"  误报率   {fps}/{n_neg} = {fpr:.0%}")
    print("=" * 62)
    if fps == 0 and n_hit == n_pos:
        print("\n[PASS] 规则库验收通过：全检出、零误报")
        return 0
    print("\n[FAIL] 未达标 —— 见上方明细")
    return 1


if __name__ == "__main__":
    sys.exit(main())
