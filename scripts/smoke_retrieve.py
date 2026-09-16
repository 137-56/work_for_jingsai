# scripts/smoke_retrieve.py
"""A5 自测：拿样本库里的母题去检索，看 Top-1 是不是它自己。

这是最朴素的检索自洽性测试 —— 如果连"检索自己"都排不到第一，那检索别人更没戏。

用法（在工程根目录 work/ 下执行）：
    .venv/Scripts/python.exe scripts/smoke_retrieve.py
    .venv/Scripts/python.exe scripts/smoke_retrieve.py 缠枝莲纹 饕餮纹 竹叶纹
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.m2_retrieve import build_queries, retrieve, _load_samples

DEFAULT_CASES = ["缠枝莲纹", "饕餮纹", "竹叶纹", "蝙蝠纹", "夔龙纹"]


def main() -> int:
    _, _, by_name = _load_samples()
    cases = sys.argv[1:] or DEFAULT_CASES
    hit = 0

    for name in cases:
        s = by_name.get(name)
        if not s:
            print(f"\n### {name} —— 不在样本库里，跳过")
            continue
        recipe = {                                       # 模拟 M1 的输出
            "intent": {"occasion": s["occasion"][:1], "purpose": "测试"},
            "structure": {"center_motif": {"name": name, "elements": s["elements"]}},
        }
        print(f"\n### {name}  (category={s['category']}, elements={s['elements']})")
        print(f"    查询串: {build_queries(recipe, by_name)}")
        rows = retrieve(recipe, top_k=5, debug=True)
        for i, r in enumerate(rows, 1):
            mark = "  ← 自身 ✅" if r["name"] == name else ""
            print(f"    {i}. {r['name']:<8} 综合={r['score']:.4f} "
                  f"CLIP={r['clip_similarity']:.4f} 交集={r['element_overlap']} "
                  f"│ 命中「{r['matched_by']}」{mark}")

        ok = bool(rows) and rows[0]["name"] == name
        hit += ok
        print(f"    Top-1 {'✅' if ok else '❌ 不是自身'}")

    print(f"\n=== Top-1 命中自身：{hit} / {len(cases)} ===")
    return 0 if hit == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
