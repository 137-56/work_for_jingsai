# scripts/apply_annotation.py
"""把人工确认过的标注结果（data/annotate_pending.json）合并回 data/samples.json。

⚠️ **只合并 occasion 和 elements 两个字段，其余字段一律不动。**
⚠️ 合并前会先做一遍合法性检查，有问题就拒绝写盘 —— 不让脏数据进库。

前置：
    1. 先跑 scripts/review_annotation.py 生成清单
    2. 人工核对清单；要改的条目直接编辑 data/annotate_pending.json
    3. **自动标注失败的那几条，也按同样格式手工补进 annotate_pending.json**，
       本脚本会一并合并（否则它们会一直留着 occasion 为空）

字段格式（annotate_pending.json 里每条）：
    {
      "occasion": ["春节", "节庆通用"],
      "elements": ["莲花", "卷草", "藤蔓"],
      "reason": "一句话说明依据"
    }

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/apply_annotation.py --dry-run   # 先看会改什么
    .venv/Scripts/python.exe scripts/apply_annotation.py             # 真正写回
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SAMPLES = ROOT / "data" / "samples.json"
PENDING = ROOT / "data" / "annotate_pending.json"
BACKUP = ROOT / "data" / "samples.json.applyannotation.bak"   # 以 .bak 结尾，会被 .gitignore 忽略

OCCASIONS = {"春节", "婚庆", "寿诞", "开业", "乔迁", "节庆通用", "日常陈设", "祭祀", "文人雅玩"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只打印会改什么，不写盘")
    ap.add_argument("--only", nargs="*", default=None, help="只合并这些 id")
    args = ap.parse_args()

    if not PENDING.exists():
        sys.exit(f"[FAIL] 找不到 {PENDING}，请先跑 scripts/auto_annotate.py")

    samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    pending = json.loads(PENDING.read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in samples}

    target = {sid: p for sid, p in pending.items()
              if (not args.only) or (sid in args.only)}
    if not target:
        sys.exit("[FAIL] 没有要合并的条目")

    # ---------- 合并前合法性检查 ----------
    bad = []
    for sid, p in target.items():
        if sid not in by_id:
            bad.append((sid, "样本库里没有这个 id"))
            continue
        occ = p.get("occasion") or []
        els = p.get("elements") or []
        if not occ:
            bad.append((sid, "occasion 为空"))
        off = [o for o in occ if o not in OCCASIONS]
        if off:
            bad.append((sid, f"occasion 越界：{off}"))
        if not els:
            bad.append((sid, "elements 为空"))
        oob = [e for e in els if not (2 <= len(e) <= 6)]
        if oob:
            bad.append((sid, f"elements 长度越界（要 2–6 字）：{oob}"))

    if bad:
        print(f"[FAIL] 合并前检查发现 {len(bad)} 处问题，**没有写盘**：\n")
        for sid, why in bad:
            print(f"  - {sid}：{why}")
        print("\n请在 data/annotate_pending.json 里改掉这些，再重跑")
        return 1
    print(f"[OK] 合并前检查通过（{len(target)} 条）")

    # ---------- 算出会改什么 ----------
    changes = []
    for sid, p in target.items():
        s = by_id[sid]
        if s.get("occasion") != p["occasion"] or s.get("elements") != p["elements"]:
            changes.append((sid, s["name"], s.get("occasion"), p["occasion"],
                            s.get("elements"), p["elements"]))

    print(f"\n本次会改动 {len(changes)} 条：\n")
    for sid, name, o0, o1, e0, e1 in changes[:15]:
        print(f"  {sid} {name}")
        print(f"      occasion  {o0}  →  {o1}")
        print(f"      elements  {e0}  →  {e1}")
    if len(changes) > 15:
        print(f"  ... 另有 {len(changes) - 15} 条")

    # ---------- 合并后仍为空的条目 ----------
    still_empty = [s["id"] for s in samples
                   if not s.get("occasion") and s["id"] not in target]
    if still_empty:
        print(f"\n[注意] 合并后仍有 {len(still_empty)} 条 occasion 为空：")
        print(f"       {', '.join(still_empty)}")
        print("       这几条是自动标注失败的（源关键词里没有物象，清洗后为空）。")
        print("       请按同样格式手工补进 data/annotate_pending.json，再重跑本脚本。")

    if args.dry_run:
        print("\n[dry-run] 未写盘")
        return 0

    # ---------- 写盘前体检：carrier 必须在受控词表内 ----------
    # 为什么在这里查：本脚本改的是 occasion/elements，但写出的是**整个 samples.json**，
    # 内存里任何一处脏数据都会被一起写出去。实测曾出现过 elements 里的词跑进 carrier 的情况
    # （WENYANG-037 的「飘带」），写完才被 validate_samples 发现。在这里挡一道更便宜。
    from scripts.validate_samples import CARRIERS
    bad_carrier = [(s["id"], s["name"], c)
                   for s in samples for c in (s.get("carrier") or []) if c not in CARRIERS]
    if bad_carrier:
        print(f"\n[FAIL] 写盘前体检发现 {len(bad_carrier)} 处 carrier 越界，**没有写盘**：\n")
        for sid, name, c in bad_carrier:
            print(f"  - {sid} {name}：'{c}' 不在词表内")
        print("\n先把 samples.json 里这些词清掉再重跑")
        return 1
    print("\n[OK] 写盘前体检通过（carrier 全在受控词表内）")

    # ---------- 写回 ----------
    for sid, _name, _o0, _o1, _e0, _e1 in changes:
        by_id[sid]["occasion"] = target[sid]["occasion"]
        by_id[sid]["elements"] = target[sid]["elements"]

    shutil.copy2(SAMPLES, BACKUP)
    SAMPLES.write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[OK] 已写回 {SAMPLES.relative_to(ROOT)}（备份为 {BACKUP.name}）")
    print("[下一步] 跑 .venv/Scripts/python.exe scripts/validate_samples.py 确认契约校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
