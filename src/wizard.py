# src/wizard.py
"""六步向导的叙事编排（纯数据 + 状态派生，不含渲染）。

★ 只取「信息架构」这一层（取其精华的边界）
   另一工程的 7 步叙事编排值得借鉴的是「把生成过程拆成可追问的步骤」，
   而不是它的数据、云函数、查看器或配色。本系统 app.py 早已有 ①–⑥ 六个区，
   与「7 步压 6 步」几乎一一对应。因此本模块只做两件事：给 ①–⑥ 建立
   步骤索引，以及为每步写一句「这一步回答什么问题」；绝不重写各区实现。

   7 步 → 6 步的映射：
     p1 输入文化需求   → ① 纹样文化配方（需求落成结构化配方）
     p2 文化配方       → ①（配方 JSON 可展开）
     p3 提示词精化     → 不单独成步：其价值落在「配方 JSON 可展开」，
                          不再开一个会制造「AI 写了什么」幻觉的展示位
     p4 元素溯源卡片   → ② 检索结果 + ④ 元素级溯源卡片
     p5 2D 写实图      → ⑤ AI 风格化（可选，明确标注不可溯源）
     p6 3D 模型        → ⑥ 文创效果预览（含逐环带出处）
     p7 LLM 问答       → **删除**：幻觉入口，且 M5 刻意不进 pipeline，
                          界面不该提供不可审计的「问模型」通道
   另：③ 文化规则校验是本项目独有的一层（另一工程 rules 为空数组），
   必须独立成步 —— 它正是「可校验」立论的载体。

★ 状态来源
   只从 pipeline.run() 的 result 与 src.run_source.FINAL_RUN 派生：
   run id 取 FINAL_RUN.name，不硬编码字面量。本模块不读文件、不调 LLM、
   不渲染、不新增「边界」展示位（boundary 仍 pending，口径须 Mr.G 拍板）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.run_source import FINAL_RUN

# 状态用结构化键表达，避免把三态文案写死在数据层；措辞由渲染层决定。
STATE_READY = "ready"
STATE_EMPTY = "empty"
STATE_OPTIONAL = "optional"

# 可选步骤：需在本区手动触发，不随 pipeline.run() 自动产出。
OPTIONAL_STEPS = frozenset({"s5", "s6"})


@dataclass(frozen=True)
class WizardStep:
    """一步向导的静态信息：编号、标题、追问、对应 app.py 区域。"""

    id: str
    title: str
    question: str
    zone: str


WIZARD_STEPS: tuple[WizardStep, ...] = (
    WizardStep("s1", "① 纹样文化配方", "这句需求被拆成了哪些可校验的槽位？", "①"),
    WizardStep("s2", "② 真实纹样元素检索结果", "候选元素来自库里的哪几条真实样本？", "②"),
    WizardStep("s3", "③ 文化规则校验", "这套配方有没有触犯受控的文化规则？", "③"),
    WizardStep("s4", "④ 元素级溯源卡片", "实际进入方案的构件各自出自哪里？", "④"),
    WizardStep("s5", "⑤ AI 风格化（可选）", "哪些视觉润色不属于可溯源链路？", "⑤"),
    WizardStep("s6", "⑥ 文创效果预览（3D）", "器物每一圈的纹样出处能说清吗？", "⑥"),
)


def step_by_id(step_id: str) -> WizardStep:
    """按 id 取一步；未知 id 回落到第一步（导航 widget 的值始终受控）。"""
    return next((s for s in WIZARD_STEPS if s.id == step_id), WIZARD_STEPS[0])


def current_run_id() -> str:
    """当前展示的定稿 run 标识，取自单一真源，不硬编码。"""
    return FINAL_RUN.name


def derive_states(result: Mapping[str, Any] | None) -> list[dict[str, str]]:
    """从一次生成结果派生 6 步状态。

    Args:
        result: pipeline.run() 的返回（由 app.py 从 session_state 取后传入）；
            None 表示尚未生成。

    Returns:
        每步一条 {id, title, state, hint}；state 取 STATE_READY / STATE_EMPTY
        / STATE_OPTIONAL 三者之一。

    ★ 只依据 result 里的**实际产物键**判断，不读文件时间、不读其它
      session 键、不用写死常量。⑤⑥ 是可选后续步骤，触发与否不在 result
      内，故统一标为 OPTIONAL 并如实说明。
    """
    if not isinstance(result, Mapping) or not result:
        return [
            {"id": s.id, "title": s.title, "state": STATE_EMPTY,
             "hint": "尚无生成结果"}
            for s in WIZARD_STEPS
        ]

    recipe = result.get("recipe") or {}
    card = result.get("card") or {}
    hits = result.get("hits") or []
    evidence = {
        "s1": bool(recipe.get("intent") or recipe.get("structure")),
        "s2": bool(hits),
        "s3": isinstance(recipe.get("violations"), list),
        "s4": bool(card.get("elements")),
    }

    states: list[dict[str, str]] = []
    for step in WIZARD_STEPS:
        if step.id in OPTIONAL_STEPS:
            states.append({"id": step.id, "title": step.title,
                           "state": STATE_OPTIONAL,
                           "hint": "可选项，需在本区手动触发"})
            continue
        ready = evidence.get(step.id, False)
        states.append({
            "id": step.id, "title": step.title,
            "state": STATE_READY if ready else STATE_EMPTY,
            "hint": "本次生成已产出该步产物" if ready else "本次结果缺该步产物",
        })
    return states
