"""对局维度档案：把干员 / 敌人的差异收敛到同一套渲染接口。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .models import CompareResult, Enemy, Operator


@dataclass(frozen=True, slots=True)
class Cell:
    """一个维度格子的展示内容。"""

    text: str
    state: str
    sub: str = ""


@dataclass(frozen=True, slots=True)
class GameProfile:
    """一套题库对应的维度定义与文案。"""

    kind: str
    title: str
    item_label: str
    labels: tuple[str, ...]
    weights: tuple[float, ...]
    start_command: str
    search_command: str
    cells: Callable[[object, CompareResult], tuple[Cell, ...]]
    answer_line: Callable[[object], str]

    def __post_init__(self) -> None:
        if len(self.labels) != len(self.weights):
            raise ValueError("labels 与 weights 数量必须一致")


def _operator_cells(item: object, result: CompareResult) -> tuple[Cell, ...]:
    operator: Operator = item  # type: ignore[assignment]
    hidden_sub = ""
    if result.d3 == "close" and operator.faction_hidden:
        hidden_sub = "隐藏：" + "、".join(operator.faction_hidden)
    return (
        Cell(str(operator.rarity), result.d1),
        Cell(f"{operator.profession}/{operator.subclass}", result.d2),
        Cell(operator.faction.replace(",", "、"), result.d3, hidden_sub),
        Cell(operator.race, result.d4),
        Cell(
            str(operator.release_year),
            result.d5,
            operator.debut,
        ),
    )


def _operator_answer(operator: object) -> str:
    item: Operator = operator  # type: ignore[assignment]
    return (
        f"{item.name}（{item.rarity}★ {item.profession}/{item.subclass}"
        f"，{item.faction}）"
    )


def _enemy_cells(item: object, result: CompareResult) -> tuple[Cell, ...]:
    enemy: Enemy = item  # type: ignore[assignment]
    return (
        Cell(enemy.level, result.d1),
        Cell(enemy.endure, result.d2),
        Cell(enemy.attack, result.d3),
        Cell(enemy.defence, result.d4),
        Cell(enemy.resistance, result.d5),
        Cell(enemy.debut, result.d6 or "wrong"),
    )


def _enemy_answer(enemy: object) -> str:
    item: Enemy = enemy  # type: ignore[assignment]
    return (
        f"{item.name}（{item.level} · {item.attack_type}/{item.damage_type}"
        f" · {item.debut}）"
    )


OPERATOR_PROFILE = GameProfile(
    kind="operator",
    title="猜干员",
    item_label="干员",
    labels=("稀有度", "职业 / 分支", "阵营", "种族", "实装"),
    weights=(0.9, 1.15, 1.1, 0.9, 1.45),
    start_command="猜干员",
    search_command="查干员",
    cells=_operator_cells,
    answer_line=_operator_answer,
)

ENEMY_PROFILE = GameProfile(
    kind="enemy",
    title="猜敌人",
    item_label="敌人",
    labels=("危险等级", "耐久", "攻击", "防御", "法术抗性", "实装"),
    weights=(0.9, 0.8, 0.8, 0.8, 0.9, 1.8),
    start_command="猜敌人",
    search_command="查敌人",
    cells=_enemy_cells,
    answer_line=_enemy_answer,
)

PROFILES: dict[str, GameProfile] = {
    OPERATOR_PROFILE.kind: OPERATOR_PROFILE,
    ENEMY_PROFILE.kind: ENEMY_PROFILE,
}
