"""明日方舟猜干员 / 猜敌人插件的纯逻辑核心（不依赖 AstrBot，便于单元测试）。"""

from .compare import compare_enemies, compare_operators
from .data import OperatorPool, load_operator_pool
from .enemies import EnemyPool, load_enemy_pool
from .errors import ArkGuessError
from .game import GameRegistry, SubmitOutcome
from .models import (
    CompareResult,
    Enemy,
    Game,
    GuessRecord,
    Operator,
)
from .profiles import ENEMY_PROFILE, OPERATOR_PROFILE, PROFILES, Cell, GameProfile
from .render import render_board, render_help, render_new_game

__all__ = [
    "ArkGuessError",
    "Cell",
    "CompareResult",
    "ENEMY_PROFILE",
    "Enemy",
    "EnemyPool",
    "Game",
    "GameProfile",
    "GameRegistry",
    "GuessRecord",
    "OPERATOR_PROFILE",
    "Operator",
    "OperatorPool",
    "PROFILES",
    "SubmitOutcome",
    "compare_enemies",
    "compare_operators",
    "load_enemy_pool",
    "load_operator_pool",
    "render_board",
    "render_help",
    "render_new_game",
]
