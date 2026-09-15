# scripts/merge_report.py
"""把 docs/report/ 下的分片按固定顺序合并成一份完整报告，并做两项体检：
  1) 缺章检测 —— 少了哪个分片一眼看出
  2) 残留标记检测 —— 【待填】/【内部提示】/🚩 之类没清干净的内容

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/merge_report.py
    .venv/Scripts/python.exe scripts/merge_report.py --dir docs/report --out dist/技术报告.md

退出码：0 = 齐全且无残留；1 = 有缺章或有残留（别忽略这个信号）
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 报告分片的固定顺序（与《执行任务拆解》§4.3 一致）
ORDER = [
    "00-cover",          # 封面（含团队名称/编号、作品名称、日期）
    "01-overview",       # 一、作品概述
    "02-requirements",   # 二、需求分析
    "03-ai-tech",        # 三、AI 技术工具选择与运用
    "04-implementation", # 四、项目实施
    "05-results",        # 五、应用成效
    "06-conclusion",     # 六、总结与展望
    "07-appendix",       # 七、附录
]

# 提交前必须清干净的内部标记
TBD = re.compile(r"【待填】|【内部提示】|【TODO】|🚩|【内部】")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="docs/report", help="分片所在目录")
    ap.add_argument("--out", default="dist/技术报告.md", help="合并输出文件")
    args = ap.parse_args()

    src = ROOT / args.dir
    out = ROOT / args.out
    if not src.is_dir():
        sys.exit(f"[FAIL] 分片目录不存在：{src}\n       请先建 docs/report/ 并写入 00-cover.md ~ 07-appendix.md")

    parts, missing = [], []
    for name in ORDER:
        p = src / f"{name}.md"
        if p.exists():
            parts.append(p.read_text(encoding="utf-8").rstrip())
        else:
            missing.append(name)

    # ---- 体检一：缺章 ----
    if missing:
        print(f"[警告] 缺 {len(missing)} / {len(ORDER)} 个章节，合并结果不完整：")
        for m in missing:
            print(f"        - {m}.md")
    else:
        print(f"[OK] {len(ORDER)} 个章节齐全")

    text = "\n\n---\n\n".join(parts)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"[OK] 合并完成：{out.relative_to(ROOT)}  （{len(text)} 字符 / {len(text.splitlines())} 行）")

    # ---- 体检二：残留标记 ----
    hits = [(i, ln.strip()[:90]) for i, ln in enumerate(text.splitlines(), 1) if TBD.search(ln)]
    if hits:
        print(f"\n[警告] 仍有 {len(hits)} 处待处理标记，提交前必须清掉：")
        for i, ln in hits[:20]:
            print(f"        行 {i}: {ln}")
        if len(hits) > 20:
            print(f"        ... 另有 {len(hits) - 20} 处未列出")
    else:
        print("[OK] 无残留待处理标记")

    bad = bool(missing) or bool(hits)
    print("\n" + ("[FAIL] 体检不通过 —— 修完再看一次" if bad else "[PASS] 体检通过，可以进入下一步"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
