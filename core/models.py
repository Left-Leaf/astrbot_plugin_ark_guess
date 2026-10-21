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
class CompareResult:
    """五维判定结果。"""

    rarity: str
    subclass: str
    faction: str
    race: str
    release_year: str

    def as_dict(self) -> dict[str, str]:
        return {
            "rarity": self.rarity,
            "subclass": self.subclass,
            "faction": self.faction,
            "race": self.race,
            "release_year": self.release_year,
        }


@dataclass(frozen=True, slots=True)
class GuessRecord:
    """一次猜测的完整记录。"""

    attempt: int
    operator_id: str
    operator_name: str
    result: CompareResult
    guessed_at: datetime


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
