"""插件业务异常：统一带 code，便于指令层映射为用户提示。"""

from __future__ import annotations


class ArkGuessError(Exception):
    """插件业务异常基类。"""

    code = "ERROR"

    def __init__(self, message: str, **details: object) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class InvalidGuessError(ArkGuessError):
    code = "INVALID_GUESS"


class GameNotFoundError(ArkGuessError):
    code = "GAME_NOT_FOUND"


class GameFinishedError(ArkGuessError):
    code = "GAME_FINISHED"


class GameAlreadyActiveError(ArkGuessError):
    code = "GAME_ALREADY_ACTIVE"


class DuplicateGuessError(ArkGuessError):
    code = "DUPLICATE_GUESS"


class UnknownOperatorError(ArkGuessError):
    code = "UNKNOWN_OPERATOR"


class AmbiguousOperatorError(ArkGuessError):
    code = "AMBIGUOUS_OPERATOR"

    def __init__(self, message: str, candidates: list[str] | None = None) -> None:
        super().__init__(message, candidates=candidates or [])
        self.candidates = candidates or []


class UnknownEnemyError(ArkGuessError):
    code = "UNKNOWN_ENEMY"


class AmbiguousEnemyError(ArkGuessError):
    code = "AMBIGUOUS_ENEMY"

    def __init__(self, message: str, candidates: list[str] | None = None) -> None:
        super().__init__(message, candidates=candidates or [])
        self.candidates = candidates or []


class InvalidMaxAttemptsError(ArkGuessError):
    code = "INVALID_MAX_ATTEMPTS"


class EmptyPoolError(ArkGuessError):
    code = "EMPTY_POOL"
