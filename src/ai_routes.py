# src/ai_routes.py
"""3D 能力改造 · **路线单一真源**（批次 1）。

★ 为什么必须有这一处
    改造前「当前走哪条路线」散落在界面单选、声明文案、查看器 URL、几何兜底里，
    各自用字面量判断。一旦某处漏改，页面照常打开、不报错，但「展示的口径」
    与「实际用的图」不是同一条路线 —— 静默失效。
    故把**枚举、默认档、AI 档集合、边界状态、界面标注、标签**全部集中在此，
    下游只 import 常量，不再自写字面量集合。

★ 三条不变量（由 `RouteState.validate()` 断言，禁止下游绕过）
    ① route 必须来自 ROUTES，未登记值明确抛错，不静默兜底；
    ② 两档 AI 路线恒 `traceable=False`、`boundary_status="pending"`；
    ③ 边界句的口径待人工确认，**AI 不得自行编造说辞**，故恒为 pending。

★ 本批范围
    ① ai_texture：AI 图作 3D 贴图源 —— 完整可用（src/ai_texture.py）。
    ② ai_generated：图转 3D —— 仅接口骨架（src/ai_mesh.py），不接外部服务。
    ③ traceable：既有可溯源分区贴附 —— 行为保持不变，作为对照档。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# ---------------------------------------------------------------- 路线枚举
ROUTE_AI_TEXTURE: Final[str] = "ai_texture"
ROUTE_TRACEABLE: Final[str] = "traceable"
ROUTE_AI_GENERATED: Final[str] = "ai_generated"

# 界面单选顺序：默认档必须是第一项（Streamlit radio 默认选第一项）。
ROUTE_ORDER: Final[tuple[str, ...]] = (
    ROUTE_AI_TEXTURE,
    ROUTE_TRACEABLE,
    ROUTE_AI_GENERATED,
)
ROUTES: Final[frozenset[str]] = frozenset(ROUTE_ORDER)
AI_ROUTES: Final[frozenset[str]] = frozenset(
    (ROUTE_AI_TEXTURE, ROUTE_AI_GENERATED))
DEFAULT_ROUTE: Final[str] = ROUTE_AI_TEXTURE

# ---------------------------------------------------------------- 状态常量
BOUNDARY_PENDING: Final[str] = "pending"
AI_DISCLOSURE_LABEL: Final[str] = "AI 生成 · 不可溯源"

# 地子取值域。viewer 的 ?ground= 契约只认 "ai" / 缺省；
# disclosure 的 ground_from 认 "neutral" / "ai_stylized"；
# "ai_texture" 是 L2 接入位的值，viewer 不认识的参数会自然忽略。
GROUND_NEUTRAL: Final[str] = "neutral"
GROUND_AI_STYLIZED: Final[str] = "ai_stylized"
GROUND_AI: Final[str] = "ai"
GROUND_AI_TEXTURE: Final[str] = "ai_texture"
GROUND_VALUES: Final[frozenset[str]] = frozenset(
    (GROUND_NEUTRAL, GROUND_AI_STYLIZED, GROUND_AI, GROUND_AI_TEXTURE))

# 界面标签（含档位说明；不写任何立论射程、端点、费用或授权结论）。
ROUTE_LABELS: Final[dict[str, str]] = {
    ROUTE_AI_TEXTURE: "① AI 图作 3D 贴图源（默认）",
    ROUTE_TRACEABLE: "② 可溯源分区贴附（母题库 · 对照档）",
    ROUTE_AI_GENERATED: "③ 图转 3D（接口骨架 · 本批未接入服务）",
}


class RouteValidationError(ValueError):
    """路线状态违反不变量时抛出。调用方不得捕获后静默降级。"""


def is_ai_route(route: str) -> bool:
    """该路线是否属于 AI 产物档（AI 产物恒不可溯源）。"""
    return route in AI_ROUTES


@dataclass(frozen=True)
class RouteState:
    """一次 3D 预览的路线状态（不可变，便于在 session_state 中保存）。

    Attributes:
        route: 路线枚举值，取自 ROUTES。
        ground: 地子 / 查看器契约值，取自 GROUND_VALUES。
        source: 本次实际采用的图源路径（无图源时为空串）。
        form: 关联的载体形态标识（本批形态集未扩展，留空或单形态名）。
        traceable: 是否可溯源。AI 两档恒为 False。
        boundary_status: 边界句状态。恒为 pending，不得由 AI 改写。
    """

    route: str = DEFAULT_ROUTE
    ground: str = GROUND_NEUTRAL
    source: str = ""
    form: str = ""
    traceable: bool = False
    boundary_status: str = BOUNDARY_PENDING

    @classmethod
    def for_route(cls, route: str, *, ground: str = GROUND_NEUTRAL,
                  source: str = "", form: str = "") -> "RouteState":
        """按路线构造一个**合法**状态，避免调用方手工填错不变量。

        Args:
            route: 路线枚举值。
            ground: 地子 / 查看器契约值。
            source: 实际采用的图源路径。
            form: 载体形态标识。

        Returns:
            已按路线设定好 traceable / boundary_status 的 RouteState。

        Raises:
            RouteValidationError: route 未登记。
        """
        if route not in ROUTES:
            raise RouteValidationError(
                f"未登记的路线 {route!r}；可用路线：{sorted(ROUTES)}")
        state = cls(
            route=route,
            ground=ground,
            source=source,
            form=form,
            traceable=(route == ROUTE_TRACEABLE),
            boundary_status=BOUNDARY_PENDING,
        )
        state.validate()
        return state

    def validate(self) -> None:
        """断言路线不变量；任一不满足即抛 `RouteValidationError`。

        ★ 为什么显式断言而不是「构造时自动纠正」：
          自动纠正会把非法状态变成看似合法的状态，错误被吞掉；
          明确抛错才能在上游暴露。
        """
        if self.route not in ROUTES:
            raise RouteValidationError(
                f"route 未在 ROUTES 登记：{self.route!r}")
        if self.ground not in GROUND_VALUES:
            raise RouteValidationError(
                f"ground 未在 GROUND_VALUES 登记：{self.ground!r}")
        if not isinstance(self.source, str) or not isinstance(self.form, str):
            raise RouteValidationError("source / form 必须是字符串")
        if is_ai_route(self.route):
            if self.traceable is not False:
                raise RouteValidationError(
                    f"AI 档 {self.route} 的 traceable 必须恒为 False")
            if self.boundary_status != BOUNDARY_PENDING:
                raise RouteValidationError(
                    f"AI 档 {self.route} 的 boundary_status 必须恒为 pending")
        elif self.route == ROUTE_TRACEABLE:
            if self.traceable is not True:
                raise RouteValidationError(
                    "traceable 档的 traceable 必须为 True")
            if self.boundary_status != BOUNDARY_PENDING:
                raise RouteValidationError(
                    "traceable 档的 boundary_status 必须恒为 pending")
