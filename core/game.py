"""对局注册表：多局并行、每局唯一 id、实例级 asyncio 锁。"""

from __future__ import annotations

import asyncio
import random
import secrets
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .compare import compare_operators
from .errors import (
    ArkGuessError,
    DuplicateGuessError,
    GameAlreadyActiveError,
    GameFinishedError,
    GameNotFoundError,
    InvalidMaxAttemptsError,
)
from .models import CompareResult, Game, GuessRecord, SubmitOutcome


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GameRegistry:
    """管理所有游戏实例。

    并发模型：
    - 不同会话（session_key）绑定不同的 game id，状态完全独立；
    - 同一个 game id 的提交通过 asyncio.Lock 串行化，避免并发猜测互相覆盖；
    - 不同 game id 使用不同锁，互不阻塞。
    """

    def __init__(
        self,
        pool,
        *,
        max_attempts: int = 8,
        ttl_minutes: int = 120,
        min_rarity: int = 1,
        rng: random.Random | None = None,
        now: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
        comparator: Callable[[Any, Any], CompareResult] = compare_operators,
        item_label: str = "干员",
        start_command: str = "猜干员",
    ) -> None:
        self._pool = pool
        self._default_max_attempts = max_attempts
        self._ttl_seconds = max(0, ttl_minutes) * 60
        self._min_rarity = min_rarity
        self._rng = rng or random.Random()
        self._now = now or _utcnow
        self._id_factory = id_factory or (lambda: f"game_{secrets.token_urlsafe(6)}")
        self._comparator = comparator
        self._item_label = item_label
        self._start_command = start_command

        self._games: dict[str, Game] = {}
        self._active: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def pool(self):
        return self._pool

    def current_game(self, session_key: str) -> Game | None:
        """读取会话当前绑定的对局（可能已结束）。"""
        game_id = self._active.get(session_key)
        if not game_id:
            return None
        game = self._games.get(game_id)
        if game is None:
            self._active.pop(session_key, None)
        return game

    def get_game(self, game_id: str) -> Game | None:
        return self._games.get(game_id)

    def start_or_get(
        self,
        session_key: str,
        *,
        answer_id: str | None = None,
        max_attempts: int | None = None,
        rarities: tuple[int, ...] | None = None,
    ) -> tuple[Game, bool]:
        """开始对局；若该群已有进行中的对局则直接返回。

        Returns:
            (game, created)：created 为 True 表示本次新建。
        """
        existing = self.current_game(session_key)
        if existing is not None and existing.playing:
            return existing, False
        return (
            self.create(
                session_key,
                answer_id=answer_id,
                max_attempts=max_attempts,
                rarities=rarities,
            ),
            True,
        )

    def create(
        self,
        session_key: str,
        *,
        answer_id: str | None = None,
        max_attempts: int | None = None,
        rarities: tuple[int, ...] | None = None,
    ) -> Game:
        """为会话创建新对局；答案固定保存在该实例内。"""
        attempts = self._default_max_attempts if max_attempts is None else max_attempts
        if not isinstance(attempts, int) or attempts == 0 or attempts < -1:
            raise InvalidMaxAttemptsError(
                f"maxAttempts 必须为正整数或 -1（不限次数），收到：{attempts}"
            )

        existing = self.current_game(session_key)
        if existing is not None and existing.playing:
            raise GameAlreadyActiveError(
                f"当前已有进行中的对局：{existing.id}，输入 {self._start_command} 查看进度，"
                "或输入 不猜了 结束",
                game_id=existing.id,
            )

        if answer_id:
            answer = self._pool.by_id.get(answer_id)
            if answer is None:
                raise ArkGuessError(f"答案{self._item_label}不在题库中：{answer_id}")
        else:
            answer = self._pool.random_item(self._rng, self._min_rarity, rarities)

        timestamp = self._now()
        game = Game(
            id=self._new_game_id(),
            answer_id=answer.id,
            max_attempts=attempts,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self._games[game.id] = game
        self._active[session_key] = game.id
        self._locks[game.id] = asyncio.Lock()
        return game

    async def submit(self, session_key: str, query: str) -> SubmitOutcome:
        """提交一次猜测；同一对局内严格串行。"""
        game_id = self._active.get(session_key)
        if not game_id:
            raise GameNotFoundError(
                f"当前没有进行中的对局，请先输入 {self._start_command} 开始对局"
            )

        lock = self._locks.get(game_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[game_id] = lock

        async with lock:
            game = self._games.get(game_id)
            if game is None:
                self._active.pop(session_key, None)
                raise GameNotFoundError(
                    f"当前没有进行中的对局，请先输入 {self._start_command} 开始对局"
                )
            if not game.playing:
                raise GameFinishedError(
                    f"对局 {game.id} 已结束（{game.status}），"
                    f"输入 {self._start_command} 开始新对局",
                    game_id=game.id,
                )

            guess = self._pool.resolve(query)
            if any(record.item_id == guess.id for record in game.guesses):
                raise DuplicateGuessError(f"「{guess.name}」已经猜过了", item_id=guess.id)

            answer = self._pool.by_id.get(game.answer_id)
            if answer is None:
                raise ArkGuessError(f"答案{self._item_label}不在题库中：{game.answer_id}")

            timestamp = self._now()
            result = self._comparator(guess, answer)
            record = GuessRecord(
                attempt=len(game.guesses) + 1,
                item_id=guess.id,
                item_name=guess.name,
                result=result,
                guessed_at=timestamp,
            )
            game.guesses.append(record)
            game.updated_at = timestamp

            # 胜负严格以 id 为准：维度全部相同但 id 不同不算猜中
            if guess.id == game.answer_id:
                game.status = "won"
                game.finished_at = timestamp
            elif game.max_attempts > 0 and len(game.guesses) >= game.max_attempts:
                game.status = "lost"
                game.finished_at = timestamp

            return SubmitOutcome(game=game, record=record, finished=not game.playing)

    def join(self, session_key: str, game_id: str) -> Game:
        """保留内部方法：把会话绑定到已有对局（当前指令层未开放跨群加入）。"""
        existing = self.current_game(session_key)
        if existing is not None and existing.playing and existing.id != game_id:
            raise GameAlreadyActiveError(
                f"当前已有进行中的对局：{existing.id}，输入 不猜了 结束当前对局",
                game_id=existing.id,
            )

        game = self._games.get(game_id)
        if game is None:
            matches = [item for item in self._games.values() if item.id.endswith(game_id)]
            if len(matches) == 1:
                game = matches[0]
            elif len(matches) > 1:
                raise GameNotFoundError("对局 id 后缀匹配到多个对局，请提供完整 id")
            else:
                raise GameNotFoundError(f"找不到对局：{game_id}")
        if not game.playing:
            raise GameFinishedError(f"对局 {game.id} 已结束（{game.status}）", game_id=game.id)

        self._active[session_key] = game.id
        return game

    def close(self, session_key: str) -> Game | None:
        """结束并删除会话当前对局。"""
        game_id = self._active.pop(session_key, None)
        if not game_id:
            return None
        self._locks.pop(game_id, None)
        return self._games.pop(game_id, None)

    def cleanup_expired(self) -> list[str]:
        """回收超时未活动的对局，返回被回收的 id。"""
        if self._ttl_seconds <= 0:
            return []
        now = self._now()
        expired: list[str] = []
        for game_id, game in list(self._games.items()):
            if (now - game.updated_at).total_seconds() >= self._ttl_seconds:
                expired.append(game_id)
                self._games.pop(game_id, None)
                self._locks.pop(game_id, None)
        if expired:
            expired_set = set(expired)
            for session_key, game_id in list(self._active.items()):
                if game_id in expired_set:
                    self._active.pop(session_key, None)
        return expired

    def stats(self) -> dict[str, int]:
        games = list(self._games.values())
        return {
            "total": len(games),
            "playing": sum(1 for game in games if game.status == "playing"),
            "won": sum(1 for game in games if game.status == "won"),
            "lost": sum(1 for game in games if game.status == "lost"),
        }

    def _new_game_id(self) -> str:
        for _ in range(10):
            candidate = self._id_factory()
            if candidate not in self._games:
                return candidate
        raise RuntimeError("生成游戏实例 id 失败：连续冲突")
