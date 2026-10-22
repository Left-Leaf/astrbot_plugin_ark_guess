"""AstrBot 明日方舟猜干员插件入口。"""

from __future__ import annotations

import asyncio
import base64
import time
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.event.filter import CustomFilter, EventMessageType
from astrbot.api.star import Context, Star, register
from astrbot.core.message.components import At, Plain
from astrbot.core.star.filter.command import GreedyStr
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .core import (
    ArkGuessError,
    GameRegistry,
    load_operator_pool,
    render_board,
    render_help,
)
from .core.errors import AmbiguousOperatorError, GameAlreadyActiveError
from .core.image_card import render_board_image
from .core.settings import (
    ATTEMPTS_TRIGGER,
    RARITY_TRIGGER,
    RESET_TRIGGER,
    VIEW_TRIGGER,
    GroupSettings,
    GroupSettingsStore,
    is_difficulty_text,
    normalize_command_text,
    parse_attempt_limit,
    parse_rarity_pool,
)

PLUGIN_NAME = "astrbot_plugin_ark_guess"
VERSION = "1.4.0"
BARE_START_ALIASES = frozenset({"玛一把", "粥一把"})
MALYANAR_START_TRIGGER = "玛一把"
MALYANAR_NAME = "玛恩纳"
QUICK_GUESS_START_TRIGGER = "粥一把"
MAIN_START_TRIGGER = "猜干员"
END_TRIGGER = "不猜了"


def _plain_message_text(event: AstrMessageEvent) -> str | None:
    messages = event.get_messages()
    if not messages or not all(isinstance(message, Plain) for message in messages):
        return None
    return "".join(message.text for message in messages).strip()


def _mentioned_text(event: AstrMessageEvent) -> str | None:
    mentioned = False
    text: list[str] = []
    for message in event.get_messages():
        if isinstance(message, At):
            if str(message.qq) != str(event.get_self_id()):
                return None
            mentioned = True
        elif isinstance(message, Plain):
            text.append(message.text)
        else:
            return None
    query = "".join(text).strip()
    return query if mentioned and query else None


def _command_argument(text: str | None, command: str) -> str | None:
    if text == command:
        return ""
    if text and text.startswith(command) and len(text) > len(command):
        if text[len(command)].isspace():
            return text[len(command) :].strip()
    return None


class _GameTriggerFilter(CustomFilter):
    def filter(self, event: AstrMessageEvent, cfg) -> bool:
        plain_text = _plain_message_text(event)
        if (
            plain_text in BARE_START_ALIASES
            or _command_argument(plain_text, QUICK_GUESS_START_TRIGGER) is not None
            or plain_text == END_TRIGGER
            or is_difficulty_text(plain_text)
        ):
            return True
        return _mentioned_text(event) is not None


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
        min_rarity = min(6, max(1, _as_int(self.config.get("min_rarity"), 1)))
        default_attempts = _as_int(self.config.get("max_attempts"), 8)
        if default_attempts == 0 or default_attempts < -1:
            default_attempts = 8
        self.registry = GameRegistry(
            self.pool,
            max_attempts=default_attempts,
            ttl_minutes=_as_int(self.config.get("game_ttl_minutes"), 120),
            min_rarity=min_rarity,
        )
        self.group_settings = GroupSettingsStore(
            self._group_settings_path(),
            GroupSettings(
                rarities=tuple(range(min_rarity, 7)),
                max_attempts=default_attempts,
            ),
        )

        self._cleanup_task: asyncio.Task | None = None
        logger.info(
            "猜干员插件 v%s 已加载：题库版本 %s，共 %d 名干员，render_mode=%s",
            VERSION,
            self.pool.version,
            len(self.pool.operators),
            self._render_mode(),
        )

    # ------------------------------------------------------------------ 指令

    @filter.event_message_type(EventMessageType.GROUP_MESSAGE)
    @filter.custom_filter(_GameTriggerFilter)
    async def group_game_trigger(self, event: AstrMessageEvent):
        """仅处理明确的群聊裸指令和 @机器人猜测。"""
        plain_text = _plain_message_text(event)
        mentioned_text = _mentioned_text(event)
        command_text = normalize_command_text(
            plain_text if plain_text is not None else mentioned_text
        )
        session_key = self._session_key(event)
        mentioned_main_guess = _command_argument(mentioned_text, MAIN_START_TRIGGER)
        mentioned_quick_guess = _command_argument(mentioned_text, QUICK_GUESS_START_TRIGGER)
        bare_quick_guess = _command_argument(plain_text, QUICK_GUESS_START_TRIGGER)
        main_start = mentioned_main_guess is not None
        quick_start = (
            plain_text == QUICK_GUESS_START_TRIGGER
            or mentioned_text == QUICK_GUESS_START_TRIGGER
            or bare_quick_guess is not None
            or mentioned_quick_guess is not None
        )

        if (
            plain_text in BARE_START_ALIASES
            or mentioned_text == MALYANAR_START_TRIGGER
            or main_start
            or quick_start
        ):
            starts_with_mlynar = (
                plain_text == MALYANAR_START_TRIGGER
                or mentioned_text == MALYANAR_START_TRIGGER
            )
            guess_name = (
                MALYANAR_NAME
                if starts_with_mlynar
                else mentioned_main_guess
                if main_start
                else mentioned_quick_guess
                if mentioned_quick_guess is not None
                else bare_quick_guess
            )
            self._ensure_cleanup_task()
            try:
                if not guess_name:
                    yield event.plain_result(
                        "开局需要干员名称。请发送 @机器人 猜干员 <干员名> "
                        "或 粥一把 <干员名>。"
                    )
                    event.stop_event()
                    return
                current = self.registry.current_game(session_key)
                if current is not None and current.playing:
                    yield event.plain_result(f"当前群已有进行中的对局：{current.id}")
                    yield await self._respond_board(event, current)
                    return
                self.pool.resolve(guess_name)
                settings = self.group_settings.get(session_key)
                self.registry.start_or_get(
                    session_key,
                    max_attempts=settings.max_attempts,
                    rarities=settings.rarities,
                )
                outcome = await self.registry.submit(session_key, guess_name)
                yield await self._respond_board(event, outcome.game)
            except ArkGuessError as exc:
                yield event.plain_result(self._error_text(exc))
            except Exception:
                logger.exception("开始猜干员对局失败")
                yield event.plain_result("插件内部错误，请稍后再试")
            finally:
                event.stop_event()
            return

        if plain_text == END_TRIGGER or mentioned_text == END_TRIGGER:
            game = self.registry.close(session_key)
            if game is not None:
                yield event.plain_result(f"已结束对局 {game.id}。")
            event.stop_event()
            return

        if command_text == VIEW_TRIGGER:
            yield event.plain_result(self._difficulty_text(session_key))
            event.stop_event()
            return

        if command_text == RARITY_TRIGGER:
            settings = self.group_settings.get(session_key)
            yield event.plain_result(
                "⚙️ 本群角色池\n"
                f"答案稀有度：{self._rarity_text(settings)}\n"
                "修改：角色池设置 1256（只填 1-6，可任意组合）"
            )
            event.stop_event()
            return

        if command_text == ATTEMPTS_TRIGGER:
            settings = self.group_settings.get(session_key)
            yield event.plain_result(
                "⚙️ 本群猜测次数\n"
                f"最大猜测次数：{self._attempts_text(settings)}\n"
                "修改：猜测次数 8；-1 表示不限次数"
            )
            event.stop_event()
            return

        if command_text == RESET_TRIGGER:
            cleared = self.group_settings.clear(session_key)
            yield event.plain_result(
                "✅ 已恢复本群默认难度。" if cleared else "当前已是默认难度。"
            )
            event.stop_event()
            return

        if command_text.startswith(f"{RARITY_TRIGGER} "):
            args = command_text[len(RARITY_TRIGGER) :].strip()
            try:
                rarities = parse_rarity_pool(args)
            except ValueError as exc:
                yield event.plain_result(f"⚠️ {exc}")
                event.stop_event()
                return
            current = self.group_settings.get(session_key)
            self.group_settings.set(session_key, replace(current, rarities=rarities))
            yield event.plain_result(
                "✅ 本群角色池已更新（下一局生效）\n"
                f"答案稀有度：{self._rarity_text(self.group_settings.get(session_key))}"
            )
            event.stop_event()
            return

        if command_text.startswith(f"{ATTEMPTS_TRIGGER} "):
            args = command_text[len(ATTEMPTS_TRIGGER) :].strip()
            try:
                attempts = parse_attempt_limit(args)
            except ValueError as exc:
                yield event.plain_result(f"⚠️ {exc}")
                event.stop_event()
                return
            current = self.group_settings.get(session_key)
            self.group_settings.set(
                session_key, replace(current, max_attempts=attempts)
            )
            yield event.plain_result(
                "✅ 本群猜测次数已更新（下一局生效）\n"
                f"最大猜测次数：{self._attempts_text(self.group_settings.get(session_key))}"
            )
            event.stop_event()
            return

        query = mentioned_text
        current = self.registry.current_game(session_key)
        if query is None or current is None or not current.playing:
            return

        self._ensure_cleanup_task()
        try:
            outcome = await self.registry.submit(session_key, query)
            yield await self._respond_board(event, outcome.game)
        except ArkGuessError as exc:
            yield event.plain_result(self._error_text(exc))
        except Exception:
            logger.exception("@机器人猜干员失败")
            yield event.plain_result("插件内部错误，请稍后再试")
        finally:
            event.stop_event()

    @filter.command("查干员", alias={"干员查询", "干员检索"})
    async def ark_search(self, event: AstrMessageEvent, arg: GreedyStr):
        """只检索干员资料，不创建对局或消耗猜测次数。"""
        query = str(arg).strip()
        try:
            if not query:
                yield event.plain_result("请输入检索关键词。用法：/查干员 <关键词>")
                return

            matches = self.pool.search(query, limit=11)
            if not matches:
                yield event.plain_result(f"没有找到与「{query}」相近的干员。")
                return

            yield event.plain_result("\n".join(operator.name for operator in matches[:10]))
        finally:
            event.stop_event()

    @filter.command("对局状态", alias={"猜干员状态"})
    async def ark_status(self, event: AstrMessageEvent):
        """查看当前群的对局。"""
        try:
            game = self.registry.current_game(self._session_key(event))
            if game is None:
                yield event.plain_result("当前群没有对局，艾特机器人并发送 猜干员 开始一局。")
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
        if self._render_mode() == "image":
            try:
                image_path = await asyncio.to_thread(
                    render_board_image,
                    game,
                    self.pool,
                    self._cards_dir(),
                )
                payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
                logger.info(
                    "已生成猜干员卡片：%s（%d bytes）",
                    image_path,
                    image_path.stat().st_size,
                )
                # 使用 base64 发送，避免协议端无法访问 AstrBot 本地文件路径
                return event.make_result().base64_image(payload)
            except Exception:
                logger.exception("本地卡片渲染失败，回退为文本结果")
        return event.plain_result(render_board(game, self.pool))

    def _render_mode(self) -> str:
        """未配置或配置为空时默认使用图片；只有明确 text 才走文本。"""
        value = self.config.get("render_mode")
        mode = str(value).strip().lower() if value is not None else ""
        return "text" if mode == "text" else "image"

    def _cards_dir(self) -> Path:
        return Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME / "cards"

    def _group_settings_path(self) -> Path:
        return (
            Path(get_astrbot_data_path())
            / "plugin_data"
            / PLUGIN_NAME
            / "group_settings.json"
        )

    @staticmethod
    def _rarity_text(settings: GroupSettings) -> str:
        return "、".join(f"{rarity}★" for rarity in settings.rarities)

    @staticmethod
    def _attempts_text(settings: GroupSettings) -> str:
        return "不限" if settings.max_attempts == -1 else f"{settings.max_attempts} 次"

    def _difficulty_text(self, session_key: str) -> str:
        settings = self.group_settings.get(session_key)
        source = "本群自定义" if self.group_settings.has(session_key) else "默认"
        return (
            f"⚙️ 本群难度（{source}）\n"
            f"答案稀有度：{self._rarity_text(settings)}\n"
            f"最大猜测次数：{self._attempts_text(settings)}\n"
            "修改：角色池设置 1256；猜测次数 8；-1 表示不限"
        )

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
            return f"⚠️ {exc.message}"
        return f"⚠️ {exc.message}"
