# src/m6_provenance.py
"""M6 溯源卡片：把检索结果组装成「元素 → 出处 → 寓意 → 授权」的结构化卡片。

这是把"可溯源"从说法变成**看得见的产出物**的地方。
关键点（详细实现指南 6.4）：
  · 出处链接要完整可用，不截断
  · 授权类型如实写（红线相关）
  · 相似度保留两位小数
  · 卡片里不能出现任何机构内部信息

本模块只负责**组装数据**（输出 dict）。渲染 PNG 是后续步骤 —— 管线只需 JSON 就能跑通。
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# 配方里各位置的中文名，给用户看
ROLE_CN = {"center_motif": "中心母题", "border": "边饰", "corner": "角花", "reference": "相关参考"}

# ─────────────────────────────────────────────────────────────────────────────
# ★ 数据来源署名 —— CC BY-NC 4.0 的「署名（BY）」是**强制法律义务**，不得删除或改写。
#   依据：Wényàng 的 LICENSE-CONTENT.md；格式见 文档/数据来源署名规范.md
#   卡片版面小，用压缩版 —— 但「作者名 + 作品名 + 协议名」三样一个都不能省。
# ─────────────────────────────────────────────────────────────────────────────
ATTRIBUTION_SHORT = ("数据来源：BLCaptain（爆裂队长NEXT）《中国传统纹样图鉴 Wényàng》"
                     "· CC BY-NC 4.0（署名 · 非商业）")

ATTRIBUTION_FULL = (
    "纹样图像与文字资料：BLCaptain（爆裂队长NEXT），《中国传统纹样图鉴 Wényàng》，"
    "https://github.com/dososo/chinese-traditional-patterns ，授权协议 CC BY-NC 4.0"
    "（署名 · 非商业性使用）。本项目仅对原始字段做规范化处理，并补充标注「使用场合」"
    "与「构成元素」两项派生字段；纹样图像本身未作修改。"
)

# 卡片里元素的展示顺序。
# 为什么不直接用检索结果的顺序：检索是按相似度排的，而槽位保底项（边饰/角花）
# 分数天然偏低、会被排到很后面甚至挤掉。展示顺序应该按"角色重要性"而不是分数。
ROLE_ORDER = {"center_motif": 0, "border": 1, "corner": 2, "reference": 3}


def _role_of(recipe, sample_name):
    """判断命中的样本对应配方的哪个位置。"""
    st = recipe.get("structure", {}) or {}
    cm = (st.get("center_motif") or {}).get("name")
    if sample_name == cm:
        return "center_motif"
    if sample_name == (st.get("border") or {}).get("pattern"):
        return "border"
    if sample_name == (st.get("corner") or {}).get("pattern"):
        return "corner"
    return "reference"


def build_card(recipe, hits):
    """hits 是 m2_retrieve.retrieve() 的返回值。返回溯源卡片 dict（指南 6.2 结构）。"""
    elements = []
    for h in hits:
        s = h["sample"]
        role = _role_of(recipe, s["name"])
        elements.append({
            "role": role,
            "role_cn": ROLE_CN.get(role, role),
            "element": s["name"],
            "source_id": s["id"],
            "source_name": s["name"],
            "category": s.get("category"),
            "carrier": s.get("carrier"),
            "dynasty": s.get("dynasty"),
            "meaning": s.get("meaning"),
            "source": s.get("source"),
            "source_url": s.get("source_url"),
            "license": s.get("license"),
            "similarity": round(float(h.get("score", 0)), 2),
            "image_path": s.get("image_path"),
        })

    # 按角色排序展示：中心母题 → 边饰 → 角花 → 相关参考
    elements.sort(key=lambda e: ROLE_ORDER.get(e["role"], 9))

    tz = timezone(timedelta(hours=8))
    return {
        "recipe_id": recipe.get("recipe_id", ""),
        "generated_at": datetime.now(tz).isoformat(timespec="seconds"),
        "user_request": recipe.get("user_request", ""),
        "center_motif": ((recipe.get("structure") or {}).get("center_motif") or {}).get("name", ""),
        "elements": elements,
        "note": "每个元素均可回指到样本库中的真实样本；溯源关系在生成时确定，非事后推测。",
        "attribution": ATTRIBUTION_SHORT,     # ★ CC BY-NC 的署名义务，渲染时务必带上
    }


def to_markdown(card):
    """文字版卡片 —— 省事，且 PPT 截图 / 报告附录都能直接用。"""
    L = [f"### 溯源卡片 · {card.get('recipe_id', '')}",
         f"- 需求：{card.get('user_request', '')}",
         f"- 生成时间：{card.get('generated_at', '')}",
         f"- 中心母题：{card.get('center_motif', '')}", "",
         "| 角色 | 元素 | 出处 | 载体 | 寓意 | 授权 | 相似度 |",
         "|---|---|---|---|---|---|---|"]
    for e in card.get("elements", []):
        L.append("| {} | {} | {} | {} | {} | {} | {:.2f} |".format(
            e.get("role_cn", ""), e.get("element", ""), e.get("source_name", ""),
            "/".join(e.get("carrier") or []), (e.get("meaning") or "")[:40],
            e.get("license", ""), e.get("similarity", 0)))
    L += ["", f"> {card.get('note', '')}"]
    # ★ 署名行：CC BY-NC 4.0 强制要求，不能因为"排版不好看"删掉
    L += ["", f"<sub>{card.get('attribution', ATTRIBUTION_SHORT)}</sub>"]
    return "\n".join(L)
