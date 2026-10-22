"""插件数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

GameStatus = Literal["playing", "won", "lost"]


@dataclass(frozen=True, slots=True)
class Operator:
    """题库中的一条干员记录（对应 operators.json）。"""

    id: str
    name: str
    rarity: int
    profession: str
    subclass: str
    faction: str
    faction_hidden: tuple[str, ...]
    race: str
    release_year: int


@dataclass(frozen=True, slots=True)
class Enemy:
    """题库中的一条敌人记录（对应 enemies.json）。"""

    id: str
    name: str
    level: str
    endure: str
    attack: str
    defence: str
    resistance: str
    debut: str
    debut_order: int
    sort_id: int
    enemy_race: str
    attack_type: str
    damage_type: str
    motion: str


@dataclass(frozen=True, slots=True)
class CompareResult:
    """五维判定结果；槽位顺序对应 profile 的维度顺序。

    干员维度固定为 稀有度 / 分支 / 阵营 / 种族 / 实装年份，
    敌人维度固定为 危险等级 / 耐久 / 攻击 / 防御 / 法术抗性 / 实装（额外一位，见 d6）。
    """

    d1: str
    d2: str
    d3: str
    d4: str
    d5: str
    d6: str | None = None

    @property
    def states(self) -> tuple[str, ...]:
        values = (self.d1, self.d2, self.d3, self.d4, self.d5)
        return values if self.d6 is None else values + (self.d6,)

    # 干员语义别名，保持既有调用方可用
    @property
    def rarity(self) -> str:
        return self.d1

    @property
    def subclass(self) -> str:
        return self.d2

    @property
    def faction(self) -> str:
        return self.d3

    @property
    def race(self) -> str:
        return self.d4

    @property
    def release_year(self) -> str:
        return self.d5

    def as_dict(self) -> dict[str, str]:
        return {f"d{index + 1}": state for index, state in enumerate(self.states)}


@dataclass(frozen=True, slots=True)
class GuessRecord:
    """一次猜测的完整记录。"""

    attempt: int
    item_id: str
    item_name: str
    result: CompareResult
    guessed_at: datetime

    # 干员语义别名，保持既有调用方可用
    @property
    def operator_id(self) -> str:
        return self.item_id

    @property
    def operator_name(self) -> str:
        return self.item_name


@dataclass
class Game:
    """一局游戏的完整状态：答案、猜测历史、状态都只属于该实例。"""

    id: str
    answer_id: str
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    status: GameStatus = "playing"
    guesses: list[GuessRecord] = field(default_factory=list)
    finished_at: datetime | None = None

    @property
    def attempts_used(self) -> int:
        return len(self.guesses)

    @property
    def playing(self) -> bool:
        return self.status == "playing"


@dataclass(frozen=True, slots=True)
class SubmitOutcome:
    """一次猜测提交后的结果。"""

    game: Game
    record: GuessRecord
    finished: bool
