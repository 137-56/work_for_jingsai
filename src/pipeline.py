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


def run(user_request, top_k=None, on_step=None):
    """端到端管线。

    on_step: 可选回调（B7 界面用）。每进入一个环节就调一次，用于分步显示进度。
             ★ 回调里抛异常**不能影响主管线** —— 报告进度是锦上添花，不是关键路径。
    """
    def _step(msg):
        if on_step is not None:
            try:
                on_step(msg)
            except Exception:
                pass          # 界面出问题不能拖垮管线

    result = {"user_request": user_request, "errors": []}

    # ---- M1 意图解析 ----
    _step("① 解析需求 →《纹样文化配方》")
    try:
        recipe = parse_intent(user_request)
    except Exception as e:
        result["errors"].append(f"M1 失败：{type(e).__name__}: {e}")
        recipe = {"intent": {}, "structure": {"center_motif": {}}, "palette": {},
                  "user_request": user_request, "parsed_by": "error"}
    recipe["recipe_id"] = gen_recipe_id(user_request)

    # ---- M2 元素检索 ----
    _step("② 从样本库检索真实纹样元素")
    hits = []
    try:
        hits = retrieve(recipe, top_k=top_k)
        recipe["provenance"] = [h["sample"]["id"] for h in hits]
    except Exception as e:
        result["errors"].append(f"M2 失败：{type(e).__name__}: {e}")

    # ---- M3 文化校验 ----
    rules = load_rules()                     # ★ 只读一次，别在 _step 里再读一遍
    _step(f"③ 文化规则校验（{len(rules)} 条规则）")
    try:
        recipe["violations"] = validate(recipe, rules, CFG["validate"]["severity_order"])
    except Exception as e:
        result["errors"].append(f"M3 失败：{type(e).__name__}: {e}")
        recipe["violations"] = []

    # ---- 实物佐证层：挑一件织物肌理（材质层） ----
    # ★ 必须在 build_card 之前挑：卡片要**分区标注**（纹样层 vs 材质层），
    #   而卡片是依据 recipe 组建的 → 信息必须先写进 recipe。
    # ★ 它只作整幅低透明度肌理，**不参与元素级溯源**（克利夫兰数据无文化语义字段）。
    _step("＋ 选取实物织物肌理（实物佐证层）")
    texture_item = None
    try:
        from src.artifact_layer import pick_texture, desc_era
        texture_item, tex_d = pick_texture(recipe)
        if texture_item:
            recipe["texture_layer"] = {
                "source": "Cleveland Museum of Art (Open Access)",
                "accession_number": texture_item.get("accession_number"),
                "era": desc_era(texture_item),
                "creation_date": texture_item.get("creation_date"),
                "license": texture_item.get("license"),
                "color_distance": round(tex_d, 1) if tex_d is not None else None,
                "role": "材质层（织物肌理）",
                "note": "★ 不参与元素级溯源 —— 纹样层（中心/边饰/角花）来自母题库，可元素级溯源；"
                        "材质层来自实物佐证层，仅实物可溯。两者不得混称 100% 可溯源。",
            }
            print(f"  织物肌理 → {texture_item.get('accession_number')}"
                  f"（{recipe['texture_layer']['era']}）｜色距 {tex_d:.1f}")
    except Exception as e:
        result["errors"].append(f"实物佐证层选材失败：{type(e).__name__}: {e}")
        print(f"  [警告] 实物佐证层选材失败（已跳过）：{type(e).__name__}: {e}")

    # ---- M6 溯源卡片 ----
    _step("④ 组装元素级溯源卡片")
    try:
        card = build_card(recipe, hits)
    except Exception as e:
        result["errors"].append(f"M6 失败：{type(e).__name__}: {e}")
        card = {"elements": []}

    _step("完成")
    result.update({"recipe": recipe, "hits": hits, "card": card,
                   "_texture": texture_item})     # 下划线开头 = 内部用，不落盘
    return result


def save_all(result):
    out = Path(CFG["paths"]["outputs"]) / result["recipe"]["recipe_id"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "recipe.json").write_text(
        json.dumps(result["recipe"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "card.json").write_text(
        json.dumps(result["card"], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "card.md").write_text(to_markdown(result["card"]), encoding="utf-8")
    # ---- B4 新增：溯源卡片出图 ----
    # ★ 必须 try/except：管线原则是"任何单点失败都不中断"，演示时崩一次印象分就没了
    try:
        from src.m6_provenance import render_card_png
        png, size = render_card_png(result["card"], out / "provenance_card.png")
        print(f"溯源卡片图 → {png}  尺寸 {size}")
    except Exception as e:
        result["errors"].append(f"M6 出图失败：{type(e).__name__}: {e}")
        print(f"[警告] 溯源卡片出图失败：{type(e).__name__}: {e}")
    # ---- B5 新增：设计依据板 ----
    # ★ 与组合纹样图共用同一件织物肌理（在 run() 里挑的），保证两处一致
    tex = result.get("_texture")
    try:
        from src.m4_compose import compose_board
        bd, bsize = compose_board(result["recipe"], result["hits"],
                                  out / "design_board.png",
                                  generated_at=result["card"].get("generated_at"),
                                  texture=tex)
        print(f"设计依据板 → {bd}  尺寸 {bsize}")
    except Exception as e:
        result["errors"].append(f"M4 失败：{type(e).__name__}: {e}")
        print(f"[警告] 设计依据板生成失败：{type(e).__name__}: {e}")

    # ---- M4a 新增：真组合合成 ----
    try:
        from src.m4_compose import compose_pattern
        pat, psize, used_tex = compose_pattern(result["recipe"], result["hits"],
                                               out / "composed_pattern.png",
                                               texture=tex)
        extra = f"（含织物肌理 {used_tex.get('accession_number')}）" if used_tex else ""
        print(f"组合纹样图 → {pat}  尺寸 {psize}{extra}")
    except Exception as e:
        result["errors"].append(f"M4a 失败：{type(e).__name__}: {e}")
        print(f"[警告] 组合纹样图生成失败：{type(e).__name__}: {e}")
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
