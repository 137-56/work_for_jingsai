# scripts/check_metrics.py
"""B8 验收：报告 / PPT / 作品简介 三处取数一致性。

★ 为什么必须有这个脚本：
    "三处取数完全一致"靠人眼是核不住的 —— 报告近 5 万字、PPT 几十页、简介若干段，
    任何一处手改过一个数字就会悄悄漂移。**这种事一次都扛不住**：
    评委一旦发现同一指标在两处对不上，整份材料的可信度就打折。

两种检查：
  ① 百分比溯源：把每份材料里的所有百分比数字抓出来，标出哪些在 metrics.json
     里**找不到出处** → 找不到的不一定是错的（可能是"抽样 30%"这类描述性数字），
     但**必须逐个人工确认**
  ② 核心指标覆盖：`docs/metrics.json` 的 `headline_metrics.items` **逐项**在各份
     材料里找到没有 → 输出覆盖表 + 缺失明细

★★ 这个脚本**不保证材料完整**（2026-10 补，QA 分歧 4）
    原来第 ② 段只有一张覆盖表，既不读 metrics.json（指标名是源码里硬编码的 6 条，
    而 metrics.json 实际有 8 条，含"检出率（结构层）/（语义层）"这类括号细分），
    也**不影响退出码** —— 于是 `纹初迹现.pptx` 里 6 项核心指标一个都没有，
    脚本照样 `[PASS]`。拿它当"材料齐了"的证据会被打脸。

    现在：清单改为**从 metrics.json 读**（单一事实来源，不再硬编码），
    并给出"每份材料缺哪几项"的明细。
    默认仍然 **PASS / 退出码 0**（现状 PPT 确实还没写指标，直接变红等于 CI 常红，
    报警疲劳比不报警更糟）；加 `--strict` 才把"核心指标有缺失"判为退出码 1，
    供材料补齐后当硬门槛用。

    ★ 无论哪种模式，本检查只验证**可溯源性**与**覆盖率**，
      **不代表材料完整、也不代表指标取值正确**。

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/check_metrics.py
    .venv/Scripts/python.exe scripts/check_metrics.py --docs-dir ../文档
    .venv/Scripts/python.exe scripts/check_metrics.py --strict      # 缺指标 → 退出码 1
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PCT = re.compile(r"\d+(?:\.\d+)?%")

# ★ 兜底清单：只有 metrics.json 缺 `headline_metrics.items` 时才会用到。
#   正常路径是**读 metrics.json**，不要靠改这里来加指标 —— 那是单一事实来源。
FALLBACK_KEY_METRICS = [
    "元素溯源覆盖率", "元素溯源准确率", "文化规则检出率", "检索 Top-5 命中率",
    "版权预警检出率", "版权预警误报率",
]


def headline_keys(metrics) -> list:
    """核心指标清单 —— 从 `metrics.json` 的 `headline_metrics.items` 取键名。"""
    try:
        items = metrics["headline_metrics"]["items"]
        keys = [str(k) for k in items]
        if keys:
            return keys
    except (KeyError, TypeError):
        pass
    return list(FALLBACK_KEY_METRICS)


def name_variants(key: str) -> list:
    """一个指标在材料里可能的写法（全名 + 去括号基名）。

    ★ 为什么要退化到基名：metrics.json 的键带括号细分
      （「版权预警检出率（结构层）」/「（语义层）」、「误报率（跨门类）」/「（同门类）」），
      而材料里常只写基名「版权预警检出率 49.2%」。只做全名匹配会**误报缺失**。
      反过来，材料只写基名时，两个细分项都算命中 —— 这是有意的宽松，
      宁可少报缺失，也不要拿一堆假缺失去打扰人。
    """
    out = [key]
    for sep in ("（", "("):
        if sep in key:
            base = key.split(sep)[0].strip()
            if base and base not in out:
                out.append(base)
    return out


def metric_hit(key: str, text: str) -> bool:
    return any(v in text for v in name_variants(key))


def md_text(p):
    return p.read_text(encoding="utf-8", errors="ignore")


def pptx_text(p):
    """把 pptx 里所有可见文字抓出来（含表格与备注）。"""
    try:
        from pptx import Presentation
    except ImportError:
        return None
    out = []
    try:
        prs = Presentation(str(p))
        for slide in prs.slides:
            for sh in slide.shapes:
                if sh.has_text_frame:
                    out.append(sh.text_frame.text)
                if getattr(sh, "has_table", False):
                    for row in sh.table.rows:
                        for c in row.cells:
                            out.append(c.text)
            if slide.has_notes_slide:
                out.append(slide.notes_slide.notes_text_frame.text)
    except Exception as e:
        return f"[读取失败: {type(e).__name__}: {e}]"
    return "\n".join(out)


def collect_allowed(obj, acc):
    """从 metrics.json 里收集"可溯源"的百分比写法。"""
    if isinstance(obj, dict):
        for v in obj.values():
            collect_allowed(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            collect_allowed(v, acc)
    elif isinstance(obj, str):
        for m in PCT.findall(obj):
            acc.add(m)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        # ★ 取绝对值：增量类的值在 metrics.json 里是负数（如 -0.40），
        #   而报告里写的是"−40.0%"——正则抓出来的数字不含负号。不取绝对值会误判成"无法溯源"。
        x = abs(obj) * 100
        if 0 <= x <= 1000:
            # ★ 生成多种写法：报告里可能写 "59%"、"59.0%"、"59.00%"
            #   只生成 "59%" 会把 "59.0%" 误判成"无法溯源"（我第一版就踩了这个）。
            acc.add(f"{x:g}%")
            acc.add(f"{x:.1f}%")
            acc.add(f"{x:.2f}%")
            for r in (1, 2):
                acc.add(f"{round(x, r):g}%")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs-dir", default=str(ROOT.parent / "文档"))
    ap.add_argument("--strict", action="store_true",
                    help="核心指标若在任何一份材料中缺失 → 退出码 1（默认只提示，不阻断）")
    args = ap.parse_args()
    docs_dir = Path(args.docs_dir)

    mj = ROOT / "docs" / "metrics.json"
    metrics = json.loads(mj.read_text(encoding="utf-8"))

    allowed = set()
    collect_allowed(metrics, allowed)
    print(f"metrics.json 可溯源百分比写法：{len(allowed)} 种")

    # ---- 收集材料 ----
    sources = []
    for name in ("技术报告初稿.md", "作品名称与简介.md"):
        p = docs_dir / name
        if p.exists():
            sources.append((name, md_text(p), "当前口径"))
    for p in sorted(docs_dir.glob("*.pptx")):
        t = pptx_text(p)
        if t is None:
            print(f"[跳过] {p.name}：未安装 python-pptx")
            continue
        tag = "当前口径" if "纹初迹现" in t else "⚠️ 疑似方案A口径（待 D 阶段重做）"
        sources.append((p.name, t, tag))

    if not sources:
        print(f"[FAIL] 在 {docs_dir} 下没找到任何待检材料")
        return 1

    # ---- ① 百分比溯源 ----
    print()
    print("=" * 74)
    print("① 各材料中的百分比 —— 是否都能在 metrics.json 找到出处")
    print("=" * 74)
    total_orphan = 0
    for name, text, tag in sources:
        found = sorted(set(PCT.findall(text)), key=lambda s: float(s[:-1]))
        orphan = [x for x in found if x not in allowed]
        total_orphan += len(orphan)
        print(f"\n  【{name}】{tag}")
        print(f"    共 {len(found)} 种百分比｜可溯源 {len(found) - len(orphan)}｜**待确认 {len(orphan)}**")
        if orphan:
            print(f"    待确认：{orphan}")
            print("    ↑ 不一定是错的（可能是描述性数字），但必须逐个确认来源")

    # ---- ② 核心指标覆盖 ----
    print()
    print("=" * 74)
    print("② 核心指标在各材料中的覆盖情况")
    print("=" * 74)
    keys = headline_keys(metrics)
    print(f"  清单来源：docs/metrics.json → headline_metrics.items（{len(keys)} 项）")
    head = f"  {'指标':<26}"
    for name, _, _ in sources:
        head += f"{name[:12]:<14}"
    print(head)
    missing = []                      # [(材料名, 指标, 显示名)]
    for key in keys:
        line = f"  {key:<26}"
        for name, text, _ in sources:
            hit = metric_hit(key, text)
            line += f"{('✅' if hit else '❌'):<14}"
            if not hit:
                missing.append((name, key))
        print(line)

    # 覆盖小计（按材料）+ 缺失明细
    print()
    for name, text, _ in sources:
        got = sum(1 for k in keys if metric_hit(k, text))
        flag = "✅" if got == len(keys) else ("缺 %d 项" % (len(keys) - got))
        print(f"  {name}：{got}/{len(keys)}　{flag}")
    if missing:
        print("\n  缺失明细（按材料归并）：")
        for name, _, _ in sources:
            lost = [k for n, k in missing if n == name]
            if lost:
                print(f"    【{name}】缺 {len(lost)} 项：{'、'.join(lost)}")

    print()
    print("  ⚠️ 本检查只验证『百分比可溯源』与『核心指标覆盖率』，"
          "**不代表材料完整、也不代表指标取值正确**。")

    print()
    print("=" * 74)
    if total_orphan:
        print(f"[注意] {total_orphan} 处百分比待人工确认（见上）—— 逐条判完即可，不一定是错")
    if missing:
        if args.strict:
            print(f"[FAIL --strict] 核心指标缺失 {len(missing)} 处（见上）—— "
                  "材料尚未补齐，--strict 视为不通过")
            return 1
        print(f"[注意] 核心指标缺失 {len(missing)} 处（见上）—— 材料尚未写全；"
              "加 --strict 可把此项变为不通过")
    if not total_orphan and not missing:
        print("[PASS] 所有百分比均可溯源，且核心指标已覆盖全部材料")
        return 0
    if not total_orphan:
        print("[PASS] 溯源检查通过（覆盖率缺口见上，默认不阻断）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
