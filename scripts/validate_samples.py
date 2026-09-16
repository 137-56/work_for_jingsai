# scripts/validate_samples.py
"""样本库契约校验（docs/schema.md §1.4 的强制检查）。

任一项不通过 → 打印问题 + 退出码 1，代表"拒绝入库"。
在每次人工改完数据之后、以及建索引之前，都要跑一遍。

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/validate_samples.py
    .venv/Scripts/python.exe scripts/validate_samples.py --strict
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples.json"

# 受控词表 —— 必须与 docs/schema.md §1.3 保持一致
CATEGORIES = {"植物花卉纹", "动物瑞兽纹", "几何锦纹", "云水山石纹",
              "吉祥器物纹", "文字福寿与组合纹", "人物故事纹"}
CARRIERS = {"瓷器", "织锦", "刺绣", "家具", "屏风", "建筑装饰", "建筑彩画",
            "石雕", "木雕", "服饰", "壁画", "漆器", "玉器", "金银器", "剪纸", "民俗装饰"}

REQUIRED = ["id", "name", "category", "dynasty", "carrier", "meaning",
            "occasion", "elements", "source", "source_url", "license", "image_path"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="严格模式：额外要求 phash 非空、clip_vec_index 已回填")
    args = ap.parse_args()

    if not SAMPLES.exists():
        sys.exit(f"[FAIL] 找不到 {SAMPLES}")
    try:
        samples = json.loads(SAMPLES.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"[FAIL] samples.json 不是合法 JSON：{e}")

    problems = []   # (规则编号, 条目 id, 说明)

    # ---- ① id 全局唯一 ----
    dup = [i for i, n in Counter(s.get("id") for s in samples).items() if n > 1]
    if dup:
        problems.append(("①", "-", f"id 重复：{dup}"))

    for s in samples:
        sid = s.get("id", "?")

        # ---- ② 必填字段非空（None / 空串 / 空数组 都算空）----
        for f in REQUIRED:
            v = s.get(f)
            if v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list) and not v):
                problems.append(("②", sid, f"必填字段为空：{f}"))

        # ---- ③ occasion / elements 必须是数组 ----
        for f in ("occasion", "elements"):
            if not isinstance(s.get(f), list):
                problems.append(("③", sid, f"{f} 必须是数组，当前是 {type(s.get(f)).__name__}"))

        # ---- ④ category / carrier 必须在受控词表内 ----
        if s.get("category") not in CATEGORIES:
            problems.append(("④", sid, f"category 不在词表内：{s.get('category')}"))

        carrier = s.get("carrier")
        if not isinstance(carrier, list):        # ← 单独查类型：契约改过 string→string[]，这里最容易漏
            problems.append(("④", sid, f"carrier 必须是数组（契约 string[]），当前是 {type(carrier).__name__}"))
        else:
            for c in carrier:
                if c not in CARRIERS:
                    problems.append(("④", sid, f"carrier 不在词表内：{c}"))

        # ---- ⑤ image_path 指向的文件必须存在 ----
        ip = s.get("image_path")
        if isinstance(ip, str) and ip and not (ROOT / ip).exists():
            problems.append(("⑤", sid, f"图片不存在：{ip}"))

    # ---- strict 追加检查 ----
    if args.strict:
        for s in samples:
            if not s.get("phash"):
                problems.append(("S", s.get("id", "?"), "phash 为空（建库时就该算好）"))
            if s.get("clip_vec_index") is None:
                problems.append(("S", s.get("id", "?"), "clip_vec_index 未回填（需先跑 build_index.py）"))

    # ---- 报告 ----
    print(f"样本数 {len(samples)}｜规则：①id唯一 ②必填非空 ③数组类型 ④受控词表 ⑤图片存在"
          + ("｜S 严格模式" if args.strict else ""))
    if not problems:
        print("\n[PASS] 五项检查全部通过")
        return 0

    print(f"\n[FAIL] 发现 {len(problems)} 处问题：\n")
    for rule, sid, msg in problems:
        print(f"  [{rule}] {sid}  {msg}")
    print("\n按规则统计:", dict(Counter(r for r, _, _ in problems)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
