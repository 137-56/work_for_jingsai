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
"""
from __future__ import annotations

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


def _ground_line(ground_from: str) -> str:
    if ground_from == "ai_stylized":
        return ("预览地子：底纹取自 AI 风格化图（M5 输出），仅作渲染色底、不承载语义"
                "（3D 背景开关项，不属上述三层）。")
    return ("预览地子：中性底色（ground_from = neutral），仅影响 3D 背景，"
            "不属上述三层。")


def build(recipe: dict | None,
          ground_from: str = "neutral",
          boundary: str = "",
          forms: str = "梅瓶 / 方盒 / 团扇") -> list[dict]:
    """生成六句声明。

    返回 [{key, label, text, status}]，status ∈ ok / empty / pending。
    ★ pending 的条目渲染端应**跳过**（不显示占位符）——见模块 docstring 末段。
    """
    recipe = recipe or {}
    tl = recipe.get("texture_layer") or {}
    m_status, m_text = _material_line(tl)

    lines = [
        {"key": "motif", "label": "纹样层", "status": "ok",
         "text": "纹样层：各分区纹样分别来自语义层母题库（100 条），元素级可溯源。"},

        {"key": "material", "label": "材质层", "status": m_status, "text": m_text},

        {"key": "carrier", "label": "载体层", "status": "ok",
         "text": f"载体层：程序化生成的标准几何体（{forms}）—— 非文物三维模型、"
                 "非 AI 生成；仅作形态示意，不代表任何具体器物的真实形制。"},

        {"key": "ground", "label": "预览地子", "status": "ok",
         "text": _ground_line(ground_from)},

        {"key": "attribution", "label": "授权", "status": "ok",
         # ★ 不写「代码 MIT」：仓库根没有 LICENSE 文件，写了就是空头承诺。
         #   是否开源涉及赛事版权归属与独家性，须 Mr.G 定，不能先声明。
         "text": "授权：纹样层图像与文字 CC BY-NC 4.0（署名 · 限非商业）；"
                 "材质层实物图 CC0。"},

        {"key": "boundary", "label": "边界", "status": "pending" if not boundary else "ok",
         "text": boundary},
    ]
    return lines


def render_text(recipe: dict | None, ground_from: str = "neutral",
                boundary: str = "") -> str:
    """纯文本版（查看器 / 卡片 / 报告复用），跳过 pending。"""
    return "\n".join(x["text"] for x in build(recipe, ground_from, boundary)
                     if x["status"] != "pending")
