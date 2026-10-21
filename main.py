"""AstrBot 明日方舟猜干员插件入口。"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr

from .core import (
    ArkGuessError,
    GameRegistry,
    load_operator_pool,
    render_board,
    render_help,
    render_new_game,
)
from .core.errors import AmbiguousOperatorError, GameAlreadyActiveError

PLUGIN_NAME = "astrbot_plugin_ark_guess"
VERSION = "1.0.2"


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


@register(
    PLUGIN_NAME,
    "Left-Leaf",
    "明日方舟猜干员：五维提示、隐藏势力黄牌、多局并行",
    VERSION,
)
class ArkGuessPlugin(Star):
    """每个会话绑定独立对局，对局之间通过唯一 game id 隔离。"""

    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}

        data_file = Path(__file__).parent / "data" / "operators.json"
        self.pool = load_operator_pool(data_file)
        self.registry = GameRegistry(
            self.pool,
            max_attempts=_as_int(self.config.get("max_attempts"), 8),
            ttl_minutes=_as_int(self.config.get("game_ttl_minutes"), 120),
            min_rarity=_as_int(self.config.get("min_rarity"), 1),
        )

        self._cleanup_task: asyncio.Task | None = None
        logger.info(
            "猜干员插件已加载：题库版本 %s，共 %d 名干员",
            self.pool.version,
            len(self.pool.operators),
        )

    # ------------------------------------------------------------------ 指令

    @filter.command("粥一把", alias={"开始猜干员"})
    async def ark_start(self, event: AstrMessageEvent):
        """开始对局；若当前群已有对局则返回该局进度。"""
        self._ensure_cleanup_task()
        session_key = self._session_key(event)

        try:
            game, created = self.registry.start_or_get(session_key)
            if created:
                yield await self._respond(event, render_new_game(game, self.pool))
            else:
                yield await self._respond(
                    event,
                    f"当前群已有进行中的对局：{game.id}\n"
                    + render_board(game, self.pool),
                )
        except ArkGuessError as exc:
            yield event.plain_result(self._error_text(exc))
        except Exception:
            logger.exception("粥一把指令执行失败")
            yield event.plain_result("插件内部错误，请稍后再试")
        finally:
            event.stop_event()

    @filter.command("猜干员", alias={"猜干员名字"})
    async def ark_guess(self, event: AstrMessageEvent, arg: GreedyStr):
        """猜测干员；必须先通过 /粥一把 开始对局。"""
        self._ensure_cleanup_task()
        query = str(arg).strip()
        if not query:
            yield event.plain_result(
                "用法：/猜干员 <干员名>\n首次游玩请先发送 /粥一把 开始对局。"
            )
            event.stop_event()
            return

        session_key = self._session_key(event)
        try:
            current = self.registry.current_game(session_key)
            if current is None or not current.playing:
                yield event.plain_result(
                    "当前没有进行中的对局，请先发送 /粥一把 创建对局。"
                )
                return
            outcome = await self.registry.submit(session_key, query)
            yield await self._respond(event, render_board(outcome.game, self.pool))
        except ArkGuessError as exc:
            yield event.plain_result(self._error_text(exc))
        except Exception:
            logger.exception("猜干员指令执行失败")
            yield event.plain_result("插件内部错误，请稍后再试")
        finally:
            event.stop_event()

    @filter.command("不猜了", alias={"结束猜干员", "结束对局"})
    async def ark_end(self, event: AstrMessageEvent):
        """结束并删除当前群的对局。"""
        try:
            game = self.registry.close(self._session_key(event))
            if game is None:
                yield event.plain_result("当前没有进行中的对局。")
            else:
                yield event.plain_result(f"已结束对局 {game.id}。")
        finally:
            event.stop_event()

    @filter.command("对局状态", alias={"猜干员状态"})
    async def ark_status(self, event: AstrMessageEvent):
        """查看当前群的对局。"""
        try:
            game = self.registry.current_game(self._session_key(event))
            if game is None:
                yield event.plain_result("当前群没有对局，发送 /粥一把 开始一局。")
            else:
                yield await self._respond(event, render_board(game, self.pool, history=5))
        finally:
            event.stop_event()

    @filter.command("对局统计")
    async def ark_stats(self, event: AstrMessageEvent):
        """查看本进程内的对局数量。"""
        try:
            stats = self.registry.stats()
            yield event.plain_result(
                "本进程对局统计："
                f"总计 {stats['total']} ｜ 进行中 {stats['playing']} ｜ "
                f"获胜 {stats['won']} ｜ 失败 {stats['lost']}"
            )
        finally:
            event.stop_event()

    @filter.command("方舟帮助", alias={"猜干员帮助"})
    async def ark_help(self, event: AstrMessageEvent):
        """查看指令说明。"""
        try:
            yield event.plain_result(render_help())
        finally:
            event.stop_event()

    # -------------------------------------------------------------- 生命周期

    async def terminate(self):
        """插件卸载时停止清理任务。"""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None

    # ---------------------------------------------------------------- 内部

    def _session_key(self, event: AstrMessageEvent) -> str:
        """每个群固定一个对局；私聊则按会话区分。"""
        get_group_id = getattr(event, "get_group_id", None)
        group_id = str(get_group_id() or "") if callable(get_group_id) else ""
        if group_id:
            return f"group:{group_id}"
        return f"private:{event.unified_msg_origin}"

    async def _respond(self, event: AstrMessageEvent, text: str):
        """按配置输出文本或文转图。"""
        if str(self.config.get("render_mode", "text")).lower() == "image":
            try:
                image = await self.text_to_image(text)
                return event.image_result(image)
            except Exception:
                logger.exception("文转图失败，回退为文本输出")
        return event.plain_result(text)

    def _ensure_cleanup_task(self) -> None:
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return
        try:
            self._cleanup_task = asyncio.create_task(
                self._cleanup_loop(), name="astrbot_plugin_ark_guess_cleanup"
            )
        except RuntimeError:
            # 没有运行中的事件循环时跳过，后续指令会再次尝试
            self._cleanup_task = None

    async def _cleanup_loop(self) -> None:
        interval = max(60, _as_int(self.config.get("cleanup_interval_seconds"), 600))
        while True:
            await asyncio.sleep(interval)
            try:
                expired = self.registry.cleanup_expired()
                if expired:
                    logger.info("已回收 %d 个过期对局", len(expired))
            except Exception:
                logger.exception("回收过期对局失败")

    @staticmethod
    def _error_text(exc: ArkGuessError) -> str:
        if isinstance(exc, AmbiguousOperatorError) and exc.candidates:
            return f"⚠️ {exc.message}：\n" + "\n".join(f"- {name}" for name in exc.candidates)
        if isinstance(exc, GameAlreadyActiveError):
            return f"⚠️ {exc.message}\n发送 /粥一把 查看进度，或 /不猜了 结束。"
        return f"⚠️ {exc.message}"
