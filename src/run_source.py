# src/run_source.py
"""定稿 run 的单一真源（第二批「6 步向导」的前置模块）。

★ 当前状态：**本批暂时无人调用是预期状态**。
   本模块为第二批「6 步向导」准备，届时向导各步只通过下面四个访问器读取
   定稿 run 的产物，不再各自硬编码 run 目录、也不再取「最新」目录。
   在此之前没有调用方，属于正常的「先落真源、后接调用」状态。

★ 为什么必须有单一真源
   outputs/ 下有多个历史 run；一旦各处按「取最新」或各自写死目录去读，
   演示页、导出卡片、3D 查看器就会各自指向不同 run —— 页面照常打开、
   不报错，但「展示的图」和「材料里的图」不是同一件东西（静默失效）。

★ 契约
   * FINAL_RUN 由仓库根绝对定位，不依赖当前工作目录；
   * 文件缺失时**明确抛异常**：不静默 fallback 到别的 run、不取「最新」；
   * 四个访问器只读，返回解析后的数据，不写盘、不持有可变全局状态。

定稿 run 实有 14 文件：card.json / card.md / recipe.json /
composed_pattern.png / design_board.png / provenance_card.png /
pattern_box.glb / pattern_fan.glb / pattern_vase.glb /
preview3d_box.png / preview3d_fan.png / preview3d_vase.png /
preview3d_triptych.png / preview3d_layout.json。
本模块只读取其中三个 JSON，外加仓库根的 data/samples.json。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# 定稿 run 的 run id 字面量全仓 .py 仅此一处；
# scripts/check_merge_contract.py 会以「代码字符串常量恰好 1 处」断言它。
FINAL_RUN = ROOT / Path("outputs/R20261028160834-1A63")

_CARD = FINAL_RUN / "card.json"
_RECIPE = FINAL_RUN / "recipe.json"
_LAYOUT = FINAL_RUN / "preview3d_layout.json"
_SAMPLES = ROOT / "data" / "samples.json"


def _load_json(path: Path) -> Any:
    """读取一个 JSON 文件；缺失或非法时明确抛异常，绝不静默降级。

    Args:
        path: 待读取的绝对路径。

    Returns:
        解析后的 JSON 对象（dict 或 list）。

    Raises:
        FileNotFoundError: 文件不存在。此处刻意不 fallback 到别的 run、
            也不扫描 outputs/ 取「最新」，否则会把静默失效藏起来。
        json.JSONDecodeError: 文件内容不是合法 JSON。
        OSError: 读取失败（权限 / 编码等）。
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"定稿 run 缺少必需文件：{path}（不 fallback 到其他 run，"
            "请检查 FINAL_RUN 是否指向定稿产物）")
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_card() -> Any:
    """定稿 run 的 card.json（溯源卡片元数据）。只读。"""
    return _load_json(_CARD)


def load_recipe() -> Any:
    """定稿 run 的 recipe.json（配方）。只读。"""
    return _load_json(_RECIPE)


def load_layout() -> Any:
    """定稿 run 的 preview3d_layout.json（3D 预览版面）。只读。"""
    return _load_json(_LAYOUT)


def load_samples() -> Any:
    """样本库 data/samples.json（100 条母题，位于仓库根 data/ 而非 run 目录）。只读。"""
    return _load_json(_SAMPLES)
