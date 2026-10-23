"""AstrBot 明日方舟猜干员 / 猜敌人插件入口。"""

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
    compare_enemies,
    load_enemy_pool,
    load_operator_pool,
    render_board,
    render_help,
)
from .core.errors import GameAlreadyActiveError
from .core.image_card import render_board_image
from .core.profiles import PROFILES
from .core.settings import (
    ATTEMPTS_TRIGGER,
    POOL_ENEMY,
    POOL_OPERATOR,
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
VERSION = "1.7.0"
MALYANAR_START_TRIGGER = "玛一把"
MALYANAR_NAME = "玛恩纳"
BARE_START_ALIASES = frozenset({MALYANAR_START_TRIGGER})
MAIN_START_TRIGGER = "猜干员"
ENEMY_START_TRIGGER = "猜敌人"
END_TRIGGER = "不猜了"

_POOL_LABELS = {POOL_OPERATOR: "干员", POOL_ENEMY: "敌人"}


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
    "明日方舟猜干员 / 猜敌人：多维度提示、站点式卡片、双题库并行",
    VERSION,
)
class ArkGuessPlugin(Star):
    """每个会话绑定独立对局，干员池与敌人池各自独立。"""

    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context)
        self.config = config or {}

        data_dir = Path(__file__).parent / "data"
        self.operator_pool = load_operator_pool(data_dir / "operators.json")
        self.enemy_pool = load_enemy_pool(data_dir / "enemies.json")

        min_rarity = min(6, max(1, _as_int(self.config.get("min_rarity"), 1)))
        default_attempts = _as_int(self.config.get("max_attempts"), 8)
        if default_attempts == 0 or default_attempts < -1:
            default_attempts = 8
        ttl_minutes = _as_int(self.config.get("game_ttl_minutes"), 120)

        self.registries: dict[str, GameRegistry] = {
            POOL_OPERATOR: GameRegistry(
                self.operator_pool,
                max_attempts=default_attempts,
                ttl_minutes=ttl_minutes,
                min_rarity=min_rarity,
                item_label="干员",
                start_command=MAIN_START_TRIGGER,
            ),
            POOL_ENEMY: GameRegistry(
                self.enemy_pool,
                max_attempts=default_attempts,
                ttl_minutes=ttl_minutes,
                comparator=compare_enemies,
                item_label="敌人",
                start_command=ENEMY_START_TRIGGER,
            ),
        }
        self.group_settings = GroupSettingsStore(
            self._group_settings_path(),
            GroupSettings(
                rarities=tuple(range(min_rarity, 7)),
                max_attempts=default_attempts,
            ),
        )

        self._cleanup_task: asyncio.Task | None = None
        logger.info(
            "猜干员 / 猜敌人插件 v%s 已加载：干员 %d 名（%s），敌人 %d 名（%s），render_mode=%s",
            VERSION,
            len(self.operator_pool.operators),
            self.operator_pool.version,
            len(self.enemy_pool.enemies),
            self.enemy_pool.version,
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
        settings = self.group_settings.get(session_key)

        mentioned_main_guess = _command_argument(mentioned_text, MAIN_START_TRIGGER)
        mentioned_enemy_guess = _command_argument(mentioned_text, ENEMY_START_TRIGGER)
        starts_with_mlynar = (
            plain_text == MALYANAR_START_TRIGGER
            or mentioned_text == MALYANAR_START_TRIGGER
        )

        start_pool: str | None = None
        guess_name: str | None = None
        if starts_with_mlynar:
            start_pool, guess_name = POOL_OPERATOR, MALYANAR_NAME
        elif mentioned_main_guess is not None:
            start_pool, guess_name = POOL_OPERATOR, mentioned_main_guess
        elif mentioned_enemy_guess is not None:
            start_pool, guess_name = POOL_ENEMY, mentioned_enemy_guess

        if start_pool is not None:
            self._ensure_cleanup_task()
            try:
                if not guess_name:
                    yield event.plain_result(self._missing_name_text(start_pool))
                    return
                registry = self.registries[start_pool]
                current = registry.current_game(session_key)
                if current is not None and current.playing:
                    yield event.plain_result(f"当前群已有进行中的对局：{current.id}")
                    yield await self._respond_board(event, current, start_pool)
                    return
                registry.pool.resolve(guess_name)
                registry.start_or_get(
                    session_key,
                    max_attempts=settings.max_attempts,
                    rarities=settings.rarities,
                )
                outcome = await registry.submit(session_key, guess_name)
                yield await self._respond_board(event, outcome.game, start_pool)
            except ArkGuessError as exc:
                yield event.plain_result(self._error_text(exc))
            except Exception:
                logger.exception("开始对局失败")
                yield event.plain_result("插件内部错误，请稍后再试")
            finally:
                event.stop_event()
            return

        if plain_text == END_TRIGGER or mentioned_text == END_TRIGGER:
            closed: list[str] = []
            for pool, label in _POOL_LABELS.items():
                game = self.registries[pool].close(session_key)
                if game is not None:
                    closed.append(f"{label}对局 {game.id}")
            if closed:
                yield event.plain_result("已结束" + "、".join(closed) + "。")
            event.stop_event()
            return

        if command_text == VIEW_TRIGGER:
            yield event.plain_result(self._difficulty_text(session_key))
            event.stop_event()
            return

        if command_text == RARITY_TRIGGER:
            yield event.plain_result(
                "⚙️ 本群干员池稀有度（仅干员池生效）\n"
                f"答案稀有度：{self._rarity_text(settings)}\n"
                "修改：干员池稀有度 1256（只填 1-6，可任意组合）"
            )
            event.stop_event()
            return

        if command_text == ATTEMPTS_TRIGGER:
            yield event.plain_result(
                "⚙️ 本群猜测次数（干员 / 敌人共用）\n"
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
            self.group_settings.set(session_key, replace(settings, rarities=rarities))
            yield event.plain_result(
                "✅ 本群干员池稀有度已更新（下一局生效）\n"
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
            self.group_settings.set(session_key, replace(settings, max_attempts=attempts))
            yield event.plain_result(
                "✅ 本群猜测次数已更新（下一局生效）\n"
                f"最大猜测次数：{self._attempts_text(self.group_settings.get(session_key))}"
            )
            event.stop_event()
            return

        query = mentioned_text
        if query is None:
            return
        active_pools = [
            pool
            for pool in _POOL_LABELS
            if (game := self.registries[pool].current_game(session_key)) is not None
            and game.playing
        ]
        if not active_pools:
            return
        if len(active_pools) > 1:
            matched = [pool for pool in active_pools if self._can_resolve(pool, query)]
            if len(matched) != 1:
                yield event.plain_result(
                    f"⚠️ 本群同时有干员与敌人对局，无法判断「{query}」属于哪个题库。\n"
                    "发送 不猜了 结束对局后重新开局；也可先用 /查干员、/查敌人 确认名称。"
                )
                event.stop_event()
                return
            active_pools = matched

        pool = active_pools[0]
        registry = self.registries[pool]
        self._ensure_cleanup_task()
        try:
            outcome = await registry.submit(session_key, query)
            yield await self._respond_board(event, outcome.game, pool)
        except ArkGuessError as exc:
            yield event.plain_result(self._error_text(exc))
        except Exception:
            logger.exception("@机器人猜%s失败", _POOL_LABELS[pool])
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
            matches = self.operator_pool.search(query, limit=11)
            if not matches:
                yield event.plain_result(f"没有找到与「{query}」相近的干员。")
                return
            yield event.plain_result("\n".join(operator.name for operator in matches[:10]))
        finally:
            event.stop_event()

    @filter.command("查敌人", alias={"敌人查询", "敌人检索"})
    async def ark_search_enemy(self, event: AstrMessageEvent, arg: GreedyStr):
        """只检索敌人资料，不创建对局或消耗猜测次数。"""
        query = str(arg).strip()
        try:
            if not query:
                yield event.plain_result("请输入检索关键词。用法：/查敌人 <关键词>")
                return
            matches = self.enemy_pool.search(query, limit=11)
            if not matches:
                yield event.plain_result(f"没有找到与「{query}」相近的敌人。")
                return
            yield event.plain_result("\n".join(enemy.name for enemy in matches[:10]))
        finally:
            event.stop_event()

    @filter.command("对局状态", alias={"猜干员状态", "猜敌人状态"})
    async def ark_status(self, event: AstrMessageEvent):
        """查看当前群的对局（干员 / 敌人可能同时存在）。"""
        try:
            session_key = self._session_key(event)
            games = [
                (pool, game)
                for pool in _POOL_LABELS
                if (game := self.registries[pool].current_game(session_key)) is not None
            ]
            if not games:
                yield event.plain_result(self._no_game_text())
                return
            for pool, game in games:
                yield await self._respond_board(event, game, pool)
        finally:
            event.stop_event()

    @filter.command("对局统计")
    async def ark_stats(self, event: AstrMessageEvent):
        """查看本进程内的对局数量。"""
        try:
            operator_stats = self.registries[POOL_OPERATOR].stats()
            enemy_stats = self.registries[POOL_ENEMY].stats()
            yield event.plain_result(
                "本进程对局统计：\n"
                f"干员池 总计 {operator_stats['total']} ｜ "
                f"进行中 {operator_stats['playing']} ｜ "
                f"获胜 {operator_stats['won']} ｜ 失败 {operator_stats['lost']}\n"
                f"敌人池 总计 {enemy_stats['total']} ｜ "
                f"进行中 {enemy_stats['playing']} ｜ "
                f"获胜 {enemy_stats['won']} ｜ 失败 {enemy_stats['lost']}"
            )
        finally:
            event.stop_event()

    @filter.command("方舟帮助", alias={"猜干员帮助", "猜敌人帮助"})
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

    async def _respond_board(self, event: AstrMessageEvent, game, pool: str):
        """对局结果优先在本地生成 PNG 图片，失败时回退文本表格。"""
        registry = self.registries[pool]
        profile = PROFILES[pool]
        if self._render_mode() == "image":
            try:
                image_path = await asyncio.to_thread(
                    render_board_image,
                    game,
                    registry.pool,
                    self._cards_dir(),
                    profile,
                )
                payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
                logger.info(
                    "已生成%s卡片：%s（%d bytes）",
                    profile.title,
                    image_path,
                    image_path.stat().st_size,
                )
                # 使用 base64 发送，避免协议端无法访问 AstrBot 本地文件路径
                return event.make_result().base64_image(payload)
            except Exception:
                logger.exception("本地卡片渲染失败，回退为文本结果")
        return event.plain_result(render_board(game, registry.pool, profile))

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
    def _missing_name_text(pool: str) -> str:
        if pool == POOL_OPERATOR:
            return "开局需要干员名称。请发送 @机器人 猜干员 <干员名>，或发送 玛一把。"
        return "开局需要敌人名称。请发送 @机器人 猜敌人 <敌人名>。"

    @staticmethod
    def _no_game_text() -> str:
        return (
            "当前群没有对局。\n"
            "干员：@机器人 猜干员 <干员名>（或 玛一把）\n"
            "敌人：@机器人 猜敌人 <敌人名>"
        )

    def _can_resolve(self, pool: str, text: str) -> bool:
        """判断名称能否在该题库中解析，用于两个池同时进行时分流猜测。"""
        try:
            self.registries[pool].pool.resolve(text)
        except ArkGuessError:
            return False
        return True

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
            f"⚙️ 本群设置（{source}）\n"
            f"答案稀有度：{self._rarity_text(settings)}（仅干员池生效）\n"
            f"最大猜测次数：{self._attempts_text(settings)}（干员 / 敌人共用）\n"
            "修改：/干员池稀有度 1256；/猜测次数 8（-1 不限）"
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
                expired: list[str] = []
                for pool, registry in self.registries.items():
                    expired.extend(registry.cleanup_expired())
                    logger.debug("%s 池回收完成", _POOL_LABELS[pool])
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
        candidates = getattr(exc, "candidates", None)
        if candidates:
            return f"⚠️ {exc.message}：\n" + "\n".join(f"- {name}" for name in candidates)
        if isinstance(exc, GameAlreadyActiveError):
            return f"⚠️ {exc.message}"
        return f"⚠️ {exc.message}"
