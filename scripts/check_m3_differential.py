# scripts/check_m3_differential.py
"""M3 规则引擎 · 差分回归（黄金快照）—— 证明"重构没改判定"。

★★ 为什么需要它
    `tests/test_rules.py` 的 50 例是**手写断言**：它能证明"这 47+3 个具体场景对"，
    但证不了"其余 500 个配方也一字未变"。m3_validate 做防御性重构（`.get()`、
    逐条 try/except、rule_schema_error）时，最危险的正是**悄悄改变了某条判定**——
    手写用例很难覆盖 25 条规则 × 多种字段组合的全部触发面。

    所以这里把**引擎输出本身**固化成黄金快照：516 个配方（500 个由真实样本派生
    + 16 个定向边界）各跑一遍，逐条比对 (rule_id, severity, term, message)。
    任何一条告警变了、多了、少了、顺序变了，都会被抓出来。

★★ 为什么默认不用 git（评审必须能复跑）
    提交包里没有 `.git`，`git show HEAD:...` 必然失败。所以默认模式是
    **当前引擎 vs data/m3_golden.json**，零外部依赖、零环境假设。
    `--against-git` 只是开发者本机的可选模式（有 git 才有用）。

★★ 两条退出码口径（别混）
      0 = 与快照一致
      1 = 引擎行为变了（真回归，必须红）
      2 = 基线数据变了（rules/samples 的 sha256 对不上）——**不是回归**
    第 2 条是关键：将来新增一条规则，516 个配方会大面积报红。若把它当回归报，
    人会开始无视这个检查——那比没有检查更糟。所以快照头记两个输入文件的
    sha256，对不上就明确提示"先 --update-golden"，并且**不打印**成引擎差异。

★★ 防止"洗快照"
    `--update-golden` 会打印改了多少条、改在哪些 rule_id；review 时必须看这段输出，
    否则拿重刷快照把回归抹平，这个脚本就白写了。

用法：
    .venv/Scripts/python.exe scripts/check_m3_differential.py
    .venv/Scripts/python.exe scripts/check_m3_differential.py --update-golden
    .venv/Scripts/python.exe scripts/check_m3_differential.py --against-git
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RULES_PATH = ROOT / "rules" / "culture_rules.json"
SAMPLES_PATH = ROOT / "data" / "samples.json"
GOLDEN_PATH = ROOT / "data" / "m3_golden.json"

GOLDEN_VERSION = 1
EXIT_OK, EXIT_REGRESSION, EXIT_BASELINE_DRIFT, EXIT_ENV = 0, 1, 2, 3


# ---------------------------------------------------------------- 配方集
def _recipe(occasion, name, elements, blessing="连年有余",
            primary="#C8102E", secondary="#D4AF37", scheme="传统点染配色"):
    """一个"字段齐全"的配方骨架；定向用例只改它关心的那几项。"""
    return {
        "intent": {"occasion": [occasion], "purpose": "礼品包装",
                   "style": "传统窗花", "blessing": blessing},
        "structure": {"center_motif": {"name": name, "elements": elements},
                      "symmetry": "四轴对称"},
        "palette": {"primary": primary, "secondary": secondary, "scheme_basis": scheme},
    }


def _drop(recipe, path):
    """按点分路径删掉一个键（造"字段缺失"类配方用）。"""
    cur = recipe
    parts = path.split(".")
    for p in parts[:-1]:
        cur = cur[p]
    cur.pop(parts[-1], None)
    return recipe


def build_recipes(samples):
    """500 个样本派生配方 + 20 个定向配方，**覆盖全部 25 条规则**。

    ★ 为什么要两层：
      · 样本派生层用真实母题/元素，代表"正常输入"——它们几乎不产生告警，
        作用是把"合法配方不该被误报"钉死。
      · 定向层才是触发面的保障：每条规则至少有一份配方打到它。
        只靠样本层的话，实测只有 17/25 条规则被触发（R002/R003/R004/R008/
        R012/R016/R017/R019 完全打不到），那样的快照漏掉三分之一的规则。
    ★ 必须**确定性**：顺序、内容都不能随运行变化，否则快照每天都变。
    """
    occasions = ["婚庆", "寿诞", "祭祀", "日常陈设"]
    recipes = []
    for s in sorted(samples, key=lambda x: x["id"]):
        own = (s.get("occasion") or ["节庆通用"])[0]
        for occ in [own] + occasions:
            recipes.append(_recipe(occ, s["name"], s["elements"]))

    # —— 定向层：每个 id 后面注明它主要打到的规则（脚本会自检覆盖 25/25）——
    r16 = _recipe("春节", "缠枝莲纹", ["莲花"])
    r16["structure"]["border"] = {"pattern": "卷草纹"}                  # 有边饰、无宽度比例
    r17 = _recipe("春节", "缠枝莲纹", ["莲花"])
    r17["structure"]["corner"] = {"pattern": "回纹"}                    # 有角花、无边饰

    recipes += [
        {},                                                             # 全空配方
        _recipe("婚庆", "菊花纹", ["菊花"]),                              # R001
        _recipe("婚庆", "孤雁", ["寒鸦"]),                                # R002
        _recipe("寿诞", "挽联", ["松鹤"], blessing="挽联"),                # R003
        _recipe("开业", "枯枝", ["败叶"]),                                # R004
        _recipe("祭祀", "莲瓣纹", ["莲瓣"], blessing="贺喜"),              # R005
        _recipe("春节", "缠枝莲纹", ["莲花"], blessing="福"),              # R006（单字寓意）
        _recipe("春节", "缠枝莲纹", []),                                  # R007 + R018
        _drop(_recipe("春节", "缠枝莲纹", ["莲花"]), "palette.scheme_basis"),   # R008
        _drop(_recipe("春节", "缠枝莲纹", ["莲花"]), "intent.purpose"),         # R009 + R020
        _drop(_recipe("春节", "缠枝莲纹", ["莲花"]), "intent.style"),           # R010
        _recipe("日常陈设", "龙纹", ["祥云"]),                             # R011
        _recipe("开业", "龙纹", ["祥云"]),                                 # R012
        _recipe("春节", "缠枝莲纹", ["莲花"], primary="#FFD200"),           # R013（明黄）
        _recipe("春节", "五爪龙纹", ["五爪"]),                             # R014
        _recipe("日常陈设", "补子", ["官补"]),                             # R015
        r16,                                                            # R016
        r17,                                                            # R017
        _drop(_recipe("春节", "缠枝莲纹", ["莲花"]), "structure.symmetry"),     # R019
        _recipe("春节", "缠枝莲纹", ["莲花"], primary="#123456"),           # R021（离色板）
        _recipe("春节", "缠枝莲纹", ["莲花"], secondary="#123456"),         # R022
        _recipe("春节", "缠枝莲纹", ["莲花"], scheme="荧光赛博撞色"),         # R023
        _recipe("清明", "莲瓣纹", ["莲瓣"]),                               # R024（词表外）
        _recipe("春节", "缠枝莲纹", ["莲花"], primary="#FFFFFF"),           # R025（纯白）
        _recipe("婚庆", "龙纹", ["五爪", "正龙"]),                         # 高/中档并存
    ]
    return recipes


def rule_coverage(runs):
    """返回 (已触发的 rule_id 集合, 未触发的 rule_id 列表) —— 覆盖度自检用。"""
    hit = {t[0] for run in runs for t in run}
    missing = sorted({r["id"] for r in RULES} - hit)
    return hit, missing



# ---------------------------------------------------------------- 工具
def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def recipe_hash(recipe):
    """配方的短指纹（16 位十六进制），**每 4 位插一个 `-`**。

    ★ 为什么带减号（2026-10，红线扫描撞出来的）
      旧的纯 hex 指纹里，字母之间夹着一段连续数字；把字母剔掉之后，那段数字
      恰好是 **11 位、以 1 开头** → 撞上手机号正则，`scripts/redline_check.py`
      报"疑似手机号"。纯属 hex 数字片段的巧合，不是真实号码。

      ★ 修法是**改数据的表示**，不是给扫描器加排除项：
        `vendor/static` 那种排除是"固定依赖改不得"；
        而 `m3_golden.json` 是我们自己生成的，**能改就不该排除** ——
        加了排除，将来这里真出现手机号也会被漏掉。
      每 4 位插 `-` 后，最长连续数字段只有 4 位，永不匹配 11 位手机号。

      ⚠️ 写注释时也**不要复述**具体的指纹与那 11 位数字 ——
         复述一遍就等于在源码里又放了一个手机号，扫描器照样报（本文件就踩过）。

      ★ 只改**表示**，不改算法：比较仍是字符串相等，快照可比性不受影响。
        `--update-golden` 写盘与读取比对**都走这一个函数**，所以新旧快照格式一致，
        不会出现"只在读取端格式化、写盘端还是老的"那种对不上的情况。
    """
    blob = json.dumps(recipe, ensure_ascii=False, sort_keys=True)
    h = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return "-".join(h[i:i + 4] for i in range(0, len(h), 4))


def run_engine(validate_fn, recipes):
    """跑一遍全部配方，返回 [[(rule_id, severity, term, message), ...], ...]。"""
    out = []
    for r in recipes:
        out.append([(a["rule_id"], a["severity"], a["term"], a["message"])
                    for a in validate_fn(r, RULES)])
    return out


def load_engine(path, name):
    """从任意 .py 文件加载 validate()——用于 --against-git 的基线版本。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.validate


def diff_runs(old, new):
    """逐配方比对，返回差异列表：[(idx, kind, detail), ...]。

    差异分三类，必须分清楚 —— 只报"集合变了"会把"文案改了一个字"显示成
    "少 [('R001','菊花')]｜多 [('R001','菊花')]"，看着像没差异，实际是回归。
    """
    diffs = []
    if len(old) != len(new):
        return [(-1, "配方数不同", f"{len(old)} → {len(new)}")]
    for i, (a, b) in enumerate(zip(old, new)):
        if a == b:
            continue
        ka = collections.Counter((x[0], x[1], x[2]) for x in a)
        kb = collections.Counter((x[0], x[1], x[2]) for x in b)
        if ka != kb:
            gone = list((ka - kb).elements())
            added = list((kb - ka).elements())
            parts = ([f"少 {gone}"] if gone else []) + ([f"多 {added}"] if added else [])
            diffs.append((i, "告警增减", "｜".join(parts)))
            continue
        ma = {x[:3]: x[3] for x in a}
        mb = {x[:3]: x[3] for x in b}
        text = [(k, ma[k], mb[k]) for k in ma if ma[k] != mb[k]]
        if text:
            k, before, after = text[0]
            diffs.append((i, "文案变了",
                          f"{k[0]}「{k[2]}」：{before[:46]}… → {after[:46]}…"))
        else:
            diffs.append((i, "告警顺序变了",
                          f"{[x[0] for x in a]} → {[x[0] for x in b]}"))
    return diffs


def print_coverage(runs):
    """打印规则触发覆盖度 —— 防止快照"看起来很大、其实只覆盖三分之一规则"。"""
    hit, missing = rule_coverage(runs)
    total = len({r["id"] for r in RULES})
    tail = f"｜⚠ 未触发：{', '.join(missing)}（该规则的任何改动都抓不到）" if missing else ""
    print(f"  规则覆盖 {len(hit)}/{total}{tail}")


def print_diffs(diffs, recipes, limit=12):
    for idx, kind, detail in diffs[:limit]:
        head = "配方集整体" if idx < 0 else f"#{idx} {recipe_hash(recipes[idx])}"
        print(f"    · {head}  {kind}：{detail}")
    if len(diffs) > limit:
        print(f"    …… 其余 {len(diffs) - limit} 条差异略")


# ---------------------------------------------------------------- 快照读写
def build_golden(recipes, runs):
    return {
        "meta": {
            "version": GOLDEN_VERSION,
            "recipe_count": len(recipes),
            "alert_count": sum(len(x) for x in runs),
            "rules_sha256": sha256_of(RULES_PATH),
            "samples_sha256": sha256_of(SAMPLES_PATH),
            "note": "由 check_m3_differential.py --update-golden 生成；"
                    "rules/samples 任一变动需重新生成",
        },
        "cases": [{"recipe_hash": recipe_hash(r),
                   "alerts": [list(t) for t in run]}
                  for r, run in zip(recipes, runs)],
    }


def check_baseline(golden):
    """校验快照的输入基线是否还成立。返回问题描述或 None。"""
    meta = golden.get("meta", {})
    problems = []
    if meta.get("rules_sha256") != sha256_of(RULES_PATH):
        problems.append("rules/culture_rules.json 已变")
    if meta.get("samples_sha256") != sha256_of(SAMPLES_PATH):
        problems.append("data/samples.json 已变")
    return "；".join(problems) or None


# ---------------------------------------------------------------- 三个模式
def cmd_check(recipes):
    if not GOLDEN_PATH.exists():
        print(f"[缺少快照] {GOLDEN_PATH} 不存在 —— 先跑 --update-golden")
        return EXIT_ENV
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    drift = check_baseline(golden)
    if drift:
        print("=" * 74)
        print("[基线数据已变，请先 --update-golden]")
        print(f"  {drift}")
        print("  ★ 这不是引擎回归：规则库或样本库改了，快照的期望值自然过期。")
        print("  ★ 确认改动是有意的之后，跑一次 --update-golden 并 review 它的输出。")
        print("=" * 74)
        return EXIT_BASELINE_DRIFT

    cases = golden["cases"]
    if len(cases) != len(recipes):
        print(f"[配方集已变] 快照 {len(cases)} 个，当前 {len(recipes)} 个 —— 需 --update-golden")
        return EXIT_BASELINE_DRIFT
    for i, (case, r) in enumerate(zip(cases, recipes)):
        if case["recipe_hash"] != recipe_hash(r):
            print(f"[配方集已变] #{i} 内容与快照不符 —— 需 --update-golden")
            return EXIT_BASELINE_DRIFT

    expected = [[tuple(t) for t in c["alerts"]] for c in cases]
    actual = run_engine(VALIDATE, recipes)
    diffs = diff_runs(expected, actual)

    print(f"配方 {len(recipes)} 个｜快照告警 {golden['meta']['alert_count']} 条"
          f"｜当前告警 {sum(len(x) for x in actual)} 条")
    print_coverage(actual)
    if not diffs:
        print("[PASS] 与黄金快照逐条一致（rule_id/severity/term/message 全同）")
        return EXIT_OK
    print(f"[FAIL] 发现 {len(diffs)} 处与快照不一致：")
    print_diffs(diffs, recipes)
    return EXIT_REGRESSION


def cmd_update(recipes):
    runs = run_engine(VALIDATE, recipes)
    new_golden = build_golden(recipes, runs)
    had_old = GOLDEN_PATH.exists()
    old_cases = {}
    if had_old:
        old = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        old_cases = {c["recipe_hash"]: c["alerts"] for c in old.get("cases", [])}

    changed = []
    for case in new_golden["cases"]:
        before = old_cases.get(case["recipe_hash"])
        if before != case["alerts"]:
            changed.append(case)

    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(
        json.dumps(new_golden, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    where = GOLDEN_PATH.relative_to(ROOT) if GOLDEN_PATH.is_relative_to(ROOT) else GOLDEN_PATH
    print(f"快照已写入：{where}（{GOLDEN_PATH.stat().st_size // 1024} KB）")
    print(f"  配方 {len(recipes)} 个｜告警 {new_golden['meta']['alert_count']} 条")
    print_coverage(runs)
    if not had_old:
        print("  首次生成（无旧快照可比对）")
    else:
        print(f"  与旧快照相比：变更 {len(changed)} 个配方")
        if changed:
            # ★ 这段必须 review：用它洗回归就白做了
            ids = sorted({t[0] for c in changed for t in c["alerts"]})
            print(f"  涉及 rule_id：{', '.join(ids) if ids else '（告警变为空）'}")
            for case in changed[:10]:
                print(f"    · {case['recipe_hash']}：{len(case['alerts'])} 条告警")
    return EXIT_OK


def cmd_against_git(recipes):
    """开发者可选：HEAD 版 vs 当前版。提交包里没有 .git，评审用不到这个模式。"""
    try:
        src = subprocess.run(["git", "show", "HEAD:src/m3_validate.py"],
                             cwd=ROOT, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"[环境不足] 取不到 HEAD 版本（{type(e).__name__}）——"
              f"该模式只在本机 git 仓库里可用")
        return EXIT_ENV

    with tempfile.TemporaryDirectory() as td:
        base_py = Path(td) / "m3_head.py"
        base_py.write_bytes(src)
        old_validate = load_engine(base_py, "m3_head")
        a = run_engine(old_validate, recipes)
    b = run_engine(VALIDATE, recipes)

    diffs = diff_runs(a, b)
    print(f"配方 {len(recipes)} 个")
    print(f"  A（git HEAD 版）告警 {sum(len(x) for x in a)} 条")
    print(f"  B（当前工作区）告警 {sum(len(x) for x in b)} 条")
    print(f"  差异 {len(diffs)} 处")
    print_coverage(b)
    if not diffs:
        print("[PASS] 两版逐条一致 —— 重构没有改变任何判定")
        return EXIT_OK
    print("[FAIL] 两版行为不同（要么是修 bug，要么是真回归，逐条看）：")
    print_diffs(diffs, recipes)
    return EXIT_REGRESSION


def main():
    global GOLDEN_PATH
    ap = argparse.ArgumentParser(description="M3 规则引擎差分回归（黄金快照）")
    ap.add_argument("--update-golden", action="store_true", help="重生成快照（务必 review 输出）")
    ap.add_argument("--against-git", action="store_true", help="与 git HEAD 版对比（开发者可选）")
    ap.add_argument("--golden", help="指定快照路径（默认 data/m3_golden.json，自测用）")
    args = ap.parse_args()
    if args.golden:
        p = Path(args.golden)
        GOLDEN_PATH = p if p.is_absolute() else (ROOT / p)

    recipes = build_recipes(json.loads(SAMPLES_PATH.read_text(encoding="utf-8")))
    if args.update_golden:
        return cmd_update(recipes)
    if args.against_git:
        return cmd_against_git(recipes)
    return cmd_check(recipes)


RULES = json.loads(RULES_PATH.read_text(encoding="utf-8"))
VALIDATE = load_engine(ROOT / "src" / "m3_validate.py", "m3_current")

if __name__ == "__main__":
    sys.exit(main())
