"""明日方舟猜干员插件的纯逻辑核心（不依赖 AstrBot，便于单元测试）。"""

from .compare import compare_operators
from .data import OperatorPool, load_operator_pool
from .errors import ArkGuessError
from .game import GameRegistry, SubmitOutcome
from .models import CompareResult, Game, GuessRecord, Operator
from .render import render_board, render_help, render_new_game

__all__ = [
    "ArkGuessError",
    "CompareResult",
    "Game",
    "GameRegistry",
    "GuessRecord",
    "Operator",
    "OperatorPool",
    "SubmitOutcome",
    "compare_operators",
    "load_operator_pool",
    "render_board",
    "render_help",
    "render_new_game",
]
