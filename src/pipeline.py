# src/pipeline.py
"""端到端管线：一句需求 → 配方 → 检索 → 校验 → 溯源卡片。

原则（详细实现指南 8.2）：**任何单点失败都不应导致整条管线中断。**
演示时崩一次，印象分就没了。所以每一步都 try/except，失败就降级并记录，不往上抛。
"""
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.m1_intent import parse_intent
from src.m2_retrieve import retrieve
from src.m3_validate import validate
from src.m6_provenance import build_card, to_markdown
from src.utils import CFG


def gen_recipe_id(user_request):
    tz = timezone(timedelta(hours=8))
    return f"R{datetime.now(tz).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"


def load_rules():
    p = Path(CFG["paths"]["rules"])
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[警告] 规则库读不了（{e}），本次跳过文化校验")
        return []


def run(user_request, top_k=None):
    result = {"user_request": user_request, "errors": []}

    # ---- M1 意图解析 ----
    try:
        recipe = parse_intent(user_request)
    except Exception as e:
        result["errors"].append(f"M1 失败：{type(e).__name__}: {e}")
        recipe = {"intent": {}, "structure": {"center_motif": {}}, "palette": {},
                  "user_request": user_request, "parsed_by": "error"}
    recipe["recipe_id"] = gen_recipe_id(user_request)

    # ---- M2 元素检索 ----
    hits = []
    try:
        hits = retrieve(recipe, top_k=top_k)
        recipe["provenance"] = [h["sample"]["id"] for h in hits]
    except Exception as e:
        result["errors"].append(f"M2 失败：{type(e).__name__}: {e}")

    # ---- M3 文化校验 ----
    try:
        recipe["violations"] = validate(recipe, load_rules(),
                                        CFG["validate"]["severity_order"])
    except Exception as e:
        result["errors"].append(f"M3 失败：{type(e).__name__}: {e}")
        recipe["violations"] = []

    # ---- M6 溯源卡片 ----
    try:
        card = build_card(recipe, hits)
    except Exception as e:
        result["errors"].append(f"M6 失败：{type(e).__name__}: {e}")
        card = {"elements": []}

    result.update({"recipe": recipe, "hits": hits, "card": card})
    return result


def save_all(result):
    out = Path(CFG["paths"]["outputs"]) / result["recipe"]["recipe_id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "recipe.json").write_text(
        json.dumps(result["recipe"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "card.json").write_text(
        json.dumps(result["card"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "card.md").write_text(to_markdown(result["card"]), encoding="utf-8")
    return out


def main():
    req = " ".join(sys.argv[1:]) or "做一个有吉祥寓意的窗花，用于春节礼品包装"
    print(f"[1/4] 解析需求：{req}")
    r = run(req)
    print(f"[2/4] 配方：parsed_by={r['recipe'].get('parsed_by')} "
          f"母题={((r['recipe'].get('structure') or {}).get('center_motif') or {}).get('name')}")
    print(f"[3/4] 检索 {len(r['hits'])} 条；文化校验 {len(r['recipe']['violations'])} 条告警")
    print(f"[4/4] 溯源卡片 {len(r['card']['elements'])} 个元素")
    out = save_all(r)
    print(f"\n结果已保存 → {out}")
    for v in r["recipe"]["violations"]:
        print(f"  [{v['severity']}] {v['message']}")
    if r["errors"]:
        print("\n[降级记录]")
        for e in r["errors"]:
            print("  -", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
