# scripts/fix_carriers.py
"""一次性修正：用新的 carrier / applications 拆分逻辑，重跑 samples.json 里指定范围的条目。

为什么需要它：
    `wenyang_to_samples.py` 的载体提取逻辑是后来才修好的（支持多行列表格式、加了别名
    归并与白名单过滤、新增 applications 字段）。已有的 70 条是用旧逻辑写的，需要重跑；
    而**前 30 条虽然也是旧逻辑，但已人工校验过**，重跑反而可能引入变化 ——
    所以默认只处理 031 及之后的条目。

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/fix_carriers.py --dry-run   # 只看会改什么
    .venv/Scripts/python.exe scripts/fix_carriers.py             # 真正写入
    .venv/Scripts/python.exe scripts/fix_carriers.py --from 001  # 连前 30 条一起重跑

⚠️ 复用 `wenyang_to_samples.py` 里的函数，不在这里重写一份 —— 否则两边逻辑会漂移。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.wenyang_to_samples import (  # noqa: E402
    DEFAULT_SRC, read_carriers, split_carriers,
)

SAMPLES = ROOT / "data" / "samples.json"
BACKUP = ROOT / "data" / "samples.json.fixcarriers.bak"   # 以 .bak 结尾，会被 .gitignore 忽略


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="from_id", default="031",
                    help="起始编号（默认 031，即前 30 条不动）")
    ap.add_argument("--src", default=str(DEFAULT_SRC), help="Wényàng 仓库根目录")
    ap.add_argument("--dry-run", action="store_true", help="只打印会改什么，不写盘")
    args = ap.parse_args()

    src_root = Path(args.src)
    patterns = json.loads((src_root / "data" / "patterns.json").read_text(encoding="utf-8"))
    by_num = {r["id"]: r for r in patterns}

    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    changed, unknown = [], []

    for s in samples:
        num = s["id"].split("-")[-1]
        if num < args.from_id:
            continue
        r = by_num.get(num)
        if not r:
            print(f"[警告] 数据源里找不到 {num}，跳过")
            continue

        carriers, apps = split_carriers(read_carriers(src_root / r["detail_page"]))
        if carriers != s.get("carrier") or apps != s.get("applications", []):
            changed.append((s["id"], s.get("carrier"), carriers, apps))
            s["carrier"] = carriers
            s["applications"] = apps
        if carriers == ["不详"]:
            unknown.append(s["id"])

    print(f"扫描 {len(samples)} 条，范围内改动 {len(changed)} 条（编号 >= {args.from_id}）\n")
    for sid, old, new, apps in changed[:15]:
        print(f"  {sid}")
        print(f"     carrier      {old}  →  {new}")
        print(f"     applications →  {apps}")
    if len(changed) > 15:
        print(f"  ... 另有 {len(changed) - 15} 条，见写盘后的 samples.json")

    if unknown:
        print(f"\n[提醒] carrier 落到「不详」的有 {len(unknown)} 条："
              f"{', '.join(unknown[:10])}" + (" ..." if len(unknown) > 10 else ""))
        print("       「不详」是契约允许的兜底值，但值得抽查几条 —— 真有载体的话应该人工补上")

    if args.dry_run:
        print("\n[dry-run] 未写盘")
        return 0

    shutil.copy2(SAMPLES, BACKUP)
    SAMPLES.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] 已写回 {SAMPLES.relative_to(ROOT)}（备份为 {BACKUP.name}）")
    print("[下一步] 跑 .venv/Scripts/python.exe scripts/validate_samples.py 确认 ④ 类错误清零")
    return 0


if __name__ == "__main__":
    sys.exit(main())
