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
            "石雕", "木雕", "服饰", "壁画", "漆器", "玉器", "金银器", "剪纸", "民俗装饰",
            # 扩库时新增（源数据后半段实际出现的传统载体）
            "青铜器", "陶器", "砖雕", "年画", "书画", "文房器物", "宗教法器", "首饰",
            # 兜底：源数据确实没给传统载体时用它，比留空诚实
            "不详"}

REQUIRED = ["id", "name", "category", "carrier", "meaning",
            "occasion", "elements", "source", "source_url", "license", "image_path"]
# 注：`dynasty` 于 2026-09-18 由必备降为可选 —— 源数据 0/100 含朝代信息，
#     且母题本身跨朝代（缠枝莲唐至清、回纹商周至清），填一个具体朝代反而是错的。
#     全库统一保留「不详」作为诚实标记。详见 docs/schema.md §1.2 的说明。

OCCASIONS = {"春节", "婚庆", "寿诞", "开业", "乔迁", "节庆通用", "日常陈设", "祭祀", "文人雅玩"}



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

        # ---- ⑥ occasion 每个取值必须在场合词表内，且不能被分隔符粘在一起 ----
        for o in s.get("occasion") or []:
            if not isinstance(o, str):
                problems.append(("⑥", sid, f"occasion 元素必须是字符串：{o!r}"))
            elif o not in OCCASIONS:
                problems.append(("⑥", sid,
                                 f"occasion 不在场合词表内：{o!r}"
                                 f"（多个值要拆成数组元素，不能用「、」拼接）"))

        # ---- ⑦ elements 每项 2–6 字（契约 §1.2）----
        for k in s.get("elements") or []:
            if not isinstance(k, str) or not (2 <= len(k) <= 6):
                problems.append(("⑦", sid, f"elements 项违反「2–6 字」：{k!r}"))

        # ---- ⑧ name 2–8 字、meaning 20–60 字（契约 §1.2）----
        if not (2 <= len(s.get("name", "")) <= 8):
            problems.append(("⑧", sid, f"name 违反「2–8 字」：{s.get('name')!r}"))
        if not (20 <= len(s.get("meaning", "")) <= 60):
            problems.append(("⑧", sid, f"meaning 违反「20–60 字」（当前 {len(s.get('meaning',''))} 字）"))

        # ---- ⑨ related_motifs：数组、每项 2–8 字、**不含自身** ----
        #      自指会让检索"必然命中自己"，是虚高 Top-5 指标的经典来源（B1-3 踩过同类的坑）
        if "related_motifs" in s:
            rm = s.get("related_motifs")
            if not isinstance(rm, list):
                problems.append(("⑨", sid, f"related_motifs 必须是数组，当前是 {type(rm).__name__}"))
            else:
                for x in rm:
                    if not isinstance(x, str) or not (2 <= len(x) <= 8):
                        problems.append(("⑨", sid, f"related_motifs 项违反「2–8 字」：{x!r}"))
                    elif x == s.get("name"):
                        problems.append(("⑨", sid, f"related_motifs 含自身（自指）：{x!r}"))

        # ---- ⑩ palette：每项必须是 {colors: 非空字符串数组, style: 字符串} ----
        if "palette" in s:
            pal = s.get("palette")
            if not isinstance(pal, list):
                problems.append(("⑩", sid, f"palette 必须是数组，当前是 {type(pal).__name__}"))
            else:
                for p in pal:
                    if not isinstance(p, dict):
                        problems.append(("⑩", sid, f"palette 项必须是对象：{p!r}"))
                        continue
                    cols = p.get("colors")
                    if not isinstance(cols, list) or not cols:
                        problems.append(("⑩", sid, f"palette 项缺 colors：{p!r}"))
                    elif not all(isinstance(c, str) and c.strip() for c in cols):
                        problems.append(("⑩", sid, f"palette.colors 含空值：{cols!r}"))
                    if not isinstance(p.get("style", ""), str):
                        problems.append(("⑩", sid, f"palette.style 必须是字符串：{p.get('style')!r}"))



    # ---- strict 追加检查 ----
    if args.strict:
        for s in samples:
            if not s.get("phash"):
                problems.append(("S", s.get("id", "?"), "phash 为空（建库时就该算好）"))
            if s.get("clip_vec_index") is None:
                problems.append(("S", s.get("id", "?"), "clip_vec_index 未回填（需先跑 build_index.py）"))

    # ---- 报告 ----
    print(f"样本数 {len(samples)}｜规则：①id唯一 ②必填非空 ③数组类型 ④受控词表 ⑤图片存在 ⑥场合取值 "
          f"⑦elements ⑧name/meaning ⑨关联纹样 ⑩色彩建议"
          + ("｜S 严格模式" if args.strict else ""))
    if not problems:
        print("\n[PASS] 全部检查通过")     # 原为「五项检查全部通过」
        return 0

    print(f"\n[FAIL] 发现 {len(problems)} 处问题：\n")
    for rule, sid, msg in problems:
        print(f"  [{rule}] {sid}  {msg}")
    print("\n按规则统计:", dict(Counter(r for r, _, _ in problems)))
    return 1


if __name__ == "__main__":
    sys.exit(main())
