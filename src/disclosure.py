# -*- coding: utf-8 -*-
"""溯源声明 —— 界面与 3D 查看器共用的**唯一真源**。

★ 为什么要有这个模块（2026-10-28 实测）
  「纹样层 / 材质层 / 载体层 / 预览地子 / 授权 / 边界」六句声明原先分散在
  **4 处硬编码**：`app.py`、`preview3d.py`（两串，一个带括号一个不带）、
  `web/viewer.html`、以及 `static/viewer/` 的运行时副本。
  实测其中**三句在界面上根本不存在**：材质层、授权、边界。
  硬编码多份的后果不是报错，而是「页面说一套、导出图说另一套」——静默失效。

★ 为什么不能只写"两层"
  这里有**三层 + 一个开关**，不是一个笼统的"载体层"：
    纹样层    来自母题库，元素级可溯
    材质层    克利夫兰实物织物肌理，仅实物可溯（不参与元素级溯源）
    载体层    程序化几何体，非文物三维模型、非 AI 生成
    （开关）  预览地子 ground_from = neutral | ai_stylized，只影响 3D 背景
  漏掉材质层 → 界面上不声明实物出处；漏掉载体层 → 读者会以为器物是文物扫描的。

★ 边界句为什么是空的
  `handover §10` 明确：母题库本身是 AI 辅助再设计，「你溯源溯到哪里」的
  **回答口径须由 Mr.G 确认，AI 不得自行编造**。因此 `boundary` 默认空串，
  渲染端**跳过不显示**（而不是显示占位符），由 `audit` 报 WARN。
  —— 宁可少一句，不可多一句编的。

★ 批次 1：分层结构（**不写立论文案**）
    L0 既有三层（纹样层 / 材质层 / 载体层）与授权、边界；
    L1 新增 `key:"route"` 的路线分层条目，只标「当前走哪条路线」这一事实；
    L2 `_ground_line` 增 `ai_texture` 分支**接入位** —— 本批不代拟说辞，
      沿用中性底色结构位，改口位置留给 L1。
  ★ 载体层「非 AI 生成」改为**按 route 取参的结构位**：本批所有已登记路线
    都取同一个既有词，绝不新增文案、绝不代拟边界射程；将来按路线改口只需
    改 `_CARRIER_SEGMENT` 这张表，不动句子结构。
  ★ boundary 的第 6 句仍保持 `status="pending"`、`text` 空串；
    `render_text` 跳过 pending 的规则一行未改。
"""
from __future__ import annotations

from src.ai_routes import (
    AI_DISCLOSURE_LABEL, ROUTE_AI_GENERATED, ROUTE_AI_TEXTURE,
    ROUTE_TRACEABLE, ROUTES,
)

# 与 m4_compose.compose_pattern(texture_strength=0.35) 保持一致。
# ★ 它是**缩放系数**，不是幅度上限：factor = 1 + (g-1)*0.35，
#   上界随 255/mean 浮动。实测本 run 素材 mean L=126.3 → factor 0.758~1.357
#   → 实际亮度 -24.2% ~ +35.7%。所以对外**不许**写「±35%」或「至多 ±35%」。
TEXTURE_COEF = 0.35

_ERA_CN = {
    "Qing dynasty": "清",
    "Ming dynasty": "明",
    "Song dynasty": "宋",
    "Tang dynasty": "唐",
    "Yuan dynasty": "元",
}

_MUSEUM_CN = {
    "Cleveland Museum of Art (Open Access)": "克利夫兰艺术博物馆",
    "Cleveland Museum of Art": "克利夫兰艺术博物馆",
    "The Metropolitan Museum of Art": "大都会艺术博物馆",
}


def _material_line(tl: dict) -> tuple[str, str]:
    """材质层：返回 (状态, 文案)。状态 ∈ ok / empty。"""
    if not tl or not tl.get("accession_number"):
        return "empty", "材质层：本 run 未启用。"

    museum = _MUSEUM_CN.get(tl.get("source", ""), tl.get("source") or "馆藏机构")
    era_en = tl.get("era") or ""
    era = _ERA_CN.get(era_en, era_en)
    date = tl.get("creation_date") or ""
    acc = tl.get("accession_number")
    lic = "CC0 公有领域" if "CC0" in (tl.get("license") or "") else (tl.get("license") or "")

    span = " ".join(x for x in (era, date) if x)
    head = f"材质层：织物肌理取自{museum}藏（馆藏号 {acc}，{span}，{lic}）" if span \
        else f"材质层：织物肌理取自{museum}藏（馆藏号 {acc}，{lic}）"
    tail = (f"；按 {TEXTURE_COEF} 系数缩放其相对亮度偏差，不改变任何颜色"
            " —— 仅实物可溯，不参与元素级溯源。")
    return "ok", head + tail


# 中性底色句（L2 结构位复用，避免两处各写一份）。
_GROUND_LINE_NEUTRAL = ("预览地子：中性底色（ground_from = neutral），仅影响 3D 背景，"
                        "不属上述三层。")

# 载体层「非 AI 生成」片段：按 route 取参的**结构位**。
# ★ 本批所有已登记路线都取同一个既有词，绝不新增立论文案。
_CARRIER_SEGMENT = {
    ROUTE_TRACEABLE: "非 AI 生成",
    ROUTE_AI_TEXTURE: "非 AI 生成",
    ROUTE_AI_GENERATED: "非 AI 生成",
}

# L1 路线分层条目：只标「当前走哪条路线」这一事实，不写边界射程。
_ROUTE_LINE = {
    ROUTE_TRACEABLE: ("路线：可溯源分区贴附（traceable）—— 各分区纹样来自"
                      "语义层母题库，元素级可溯源。"),
    ROUTE_AI_TEXTURE: (f"路线：AI 图作 3D 贴图源（ai_texture）—— 贴图取自 AI 图，"
                       f"{AI_DISCLOSURE_LABEL}。"),
    ROUTE_AI_GENERATED: (f"路线：图转 3D 接口骨架（ai_generated）—— "
                         f"{AI_DISCLOSURE_LABEL}。"),
}


def _ground_line(ground_from: str, route: str = ROUTE_TRACEABLE) -> str:
    """L2 预览地子行。`ai_texture` 是**接入位**，本批不代拟说辞。"""
    if ground_from == "ai_stylized":
        return ("预览地子：底纹取自 AI 风格化图（M5 输出），仅作渲染色底、不承载语义"
                "（3D 背景开关项，不属上述三层）。")
    if ground_from == "ai_texture":
        # ★ 接入位：口径由 L1 的 route 条目承担；这里只做「route 已登记」
        #   的显式检查（未登记抛 KeyError，不静默兜底），文案沿用中性结构位。
        _ = _ROUTE_LINE[route]
        return _GROUND_LINE_NEUTRAL
    return _GROUND_LINE_NEUTRAL


def build(recipe: dict | None,
          ground_from: str = "neutral",
          boundary: str = "",
          forms: str = "梅瓶 / 方盒 / 团扇",
          route: str = ROUTE_TRACEABLE) -> list[dict]:
    """生成声明（既有六句 + 批次 1 的 L1 路线分层条目）。

    返回 [{key, label, text, status, layer?}]，status ∈ ok / empty / pending。
    ★ pending 的条目渲染端应**跳过**（不显示占位符）——见模块 docstring 末段。
    ★ route 默认取可溯源档：不改任何既有调用方的口径；界面按当前路线显式传参。
    """
    from src.ai_routes import RouteValidationError

    if route not in ROUTES:
        raise RouteValidationError(f"disclosure.build 收到未登记路线：{route!r}")
    recipe = recipe or {}
    tl = recipe.get("texture_layer") or {}
    m_status, m_text = _material_line(tl)
    carrier_segment = _CARRIER_SEGMENT[route]     # 未登记 → KeyError，不静默兜底

    lines = [
        {"key": "motif", "label": "纹样层", "layer": "L0", "status": "ok",
         "text": "纹样层：各分区纹样分别来自语义层母题库（100 条），元素级可溯源。"},

        {"key": "material", "label": "材质层", "layer": "L0",
         "status": m_status, "text": m_text},

        {"key": "carrier", "label": "载体层", "layer": "L0", "status": "ok",
         "text": f"载体层：程序化生成的标准几何体（{forms}）—— 非文物三维模型、"
                 f"{carrier_segment}；仅作形态示意，不代表任何具体器物的真实形制。"},

        {"key": "ground", "label": "预览地子", "layer": "L2", "status": "ok",
         "text": _ground_line(ground_from, route)},

        {"key": "attribution", "label": "授权", "layer": "L0", "status": "ok",
         # ★ 不写「代码 MIT」：仓库根没有 LICENSE 文件，写了就是空头承诺。
         #   是否开源涉及赛事版权归属与独家性，须 Mr.G 定，不能先声明。
         "text": "授权：纹样层图像与文字 CC BY-NC 4.0（署名 · 限非商业）；"
                 "材质层实物图 CC0。"},

        {"key": "boundary", "label": "边界", "status": "pending" if not boundary else "ok",
         "text": boundary},

        # ---- 批次 1 追加：L1 路线分层（不新增任何 boundary 文案）----
        {"key": "route", "label": "路线", "layer": "L1", "status": "ok",
         "text": _ROUTE_LINE[route]},
    ]
    return lines


def render_text(recipe: dict | None, ground_from: str = "neutral",
                boundary: str = "") -> str:
    """纯文本版（查看器 / 卡片 / 报告复用），跳过 pending。"""
    return "\n".join(x["text"] for x in build(recipe, ground_from, boundary)
                     if x["status"] != "pending")
