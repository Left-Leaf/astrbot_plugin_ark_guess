"""AstrBot 明日方舟猜干员插件入口。"""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .core import (
    ArkGuessError,
    GameRegistry,
    load_operator_pool,
    render_board,
    render_help,
    render_new_game,
)
from .core.errors import AmbiguousOperatorError, GameAlreadyActiveError
from .core.image_card import render_board_image

PLUGIN_NAME = "astrbot_plugin_ark_guess"
VERSION = "1.1.0"


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
    async def ark_start(self, event: AstrMessageEvent, arg: GreedyStr):
        """开始对局；带干员名时立即进行第一次猜测。

        若当前群已有进行中的对局，则只提示已有对局并返回该局进度。
        """
        self._ensure_cleanup_task()
        query = str(arg).strip()
        session_key = self._session_key(event)

        try:
            current = self.registry.current_game(session_key)
            if current is not None and current.playing:
                yield event.plain_result(f"当前群已有进行中的对局：{current.id}")
                yield await self._respond_board(event, current)
                return

            if query:
                # 先校验干员存在，避免无效名称创建出一个空对局
                self.pool.resolve(query)
                self.registry.start_or_get(session_key)
                outcome = await self.registry.submit(session_key, query)
                yield await self._respond_board(event, outcome.game)
            else:
                game, _ = self.registry.start_or_get(session_key)
                yield await self._respond(event, render_new_game(game, self.pool))
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
        session_key = self._session_key(event)

        try:
            current = self.registry.current_game(session_key)
            if current is None or not current.playing:
                yield event.plain_result(
                    "当前没有进行中的对局，请先发送 /粥一把 创建对局。"
                )
                return
            if not query:
                yield event.plain_result("没有输入干员名称。\n用法：/猜干员 <干员名>")
                return
            outcome = await self.registry.submit(session_key, query)
            yield await self._respond_board(event, outcome.game)
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
                yield await self._respond_board(event, game)
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
        """普通提示信息使用文本。"""
        return event.plain_result(text)

    async def _respond_board(self, event: AstrMessageEvent, game):
        """对局结果优先在本地生成 PNG 图片，失败时回退文本表格。"""
        if str(self.config.get("render_mode", "image")).lower() == "image":
            try:
                image_path = await asyncio.to_thread(
                    render_board_image,
                    game,
                    self.pool,
                    self._cards_dir(),
                )
                return event.image_result(str(image_path))
            except Exception:
                logger.exception("本地卡片渲染失败，回退为文本结果")
        return event.plain_result(render_board(game, self.pool))

    def _cards_dir(self) -> Path:
        return Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME / "cards"

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
                self._cleanup_cards()
            except Exception:
                logger.exception("回收过期对局失败")

    def _cleanup_cards(self) -> None:
        """删除一小时前生成的结果图片，避免磁盘堆积。"""
        cards_dir = self._cards_dir()
        if not cards_dir.exists():
            return
        cutoff = time.time() - 3600
        for file in cards_dir.glob("*.png"):
            try:
                if file.stat().st_mtime < cutoff:
                    file.unlink()
            except OSError:
                continue

    @staticmethod
    def _error_text(exc: ArkGuessError) -> str:
        if isinstance(exc, AmbiguousOperatorError) and exc.candidates:
            return f"⚠️ {exc.message}：\n" + "\n".join(f"- {name}" for name in exc.candidates)
        if isinstance(exc, GameAlreadyActiveError):
            return f"⚠️ {exc.message}\n发送 /粥一把 查看进度，或 /不猜了 结束。"
        return f"⚠️ {exc.message}"
