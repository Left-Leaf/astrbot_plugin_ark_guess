"""消息渲染：文本表格 + 色块表情（可交给 AstrBot 转图片）。"""

from __future__ import annotations

from typing import Protocol

from .models import Game, GuessRecord
from .profiles import ENEMY_PROFILE, OPERATOR_PROFILE, Cell, GameProfile

GREEN = "🟩"
YELLOW = "🟨"
GREY = "⬜"
UP = "⬆️"
DOWN = "⬇️"

_SEPARATOR = " ｜ "


class HasItems(Protocol):
    @property
    def items(self) -> tuple: ...

    @property
    def by_id(self) -> dict: ...


def _cell_text(cell: Cell) -> str:
    tone = {"correct": GREEN, "close": YELLOW}.get(cell.state, GREY)
    arrow = UP if cell.state == "higher" else DOWN if cell.state == "lower" else ""
    text = cell.text
    if cell.sub:
        text = f"{text}（{cell.sub}）"
    return f"{text} {tone}{arrow}"


def render_guess(
    record: GuessRecord,
    item: object,
    profile: GameProfile = OPERATOR_PROFILE,
) -> str:
    """把一次猜测渲染成两行文本。"""
    cells = profile.cells(item, record.result)
    line = _SEPARATOR.join(
        f"{label} {_cell_text(cell)}"
        for label, cell in zip(profile.labels, cells, strict=True)
    )
    name = getattr(item, "name", record.item_name)
    return f"第 {record.attempt} 次：{name}\n{line}"


def _limit_text(limit: int) -> str:
    return "不限" if limit == -1 else str(limit)


def _answer_line(game: Game, pool: HasItems, profile: GameProfile) -> str:
    answer = pool.by_id.get(game.answer_id)
    if answer is None:
        return f"答案：{game.answer_id}"
    return f"答案：{profile.answer_line(answer)}"


def render_board(
    game: Game,
    pool: HasItems,
    profile: GameProfile = OPERATOR_PROFILE,
    history: int = 3,
) -> str:
    """渲染当前对局（默认只展示最近几次猜测，避免消息过长）。"""
    lines = [
        f"{profile.title} ｜ 对局 {game.id} ｜ 已猜 "
        f"{len(game.guesses)}/{_limit_text(game.max_attempts)}"
    ]

    records = game.guesses[-history:] if history > 0 else game.guesses
    for record in records:
        item = pool.by_id.get(record.item_id)
        if item is not None:
            lines.append(render_guess(record, item, profile))

    if game.status == "won":
        lines.append(f"🎉 猜中了！{_answer_line(game, pool, profile)}")
    elif game.status == "lost":
        lines.append(f"❌ 次数用尽。{_answer_line(game, pool, profile)}")
    elif game.max_attempts == -1:
        lines.append(f"次数不限，艾特机器人并发送{profile.item_label}名继续")
    else:
        lines.append(
            f"还剩 {game.max_attempts - len(game.guesses)} 次机会，"
            f"艾特机器人并发送{profile.item_label}名继续"
        )

    return "\n".join(lines)


def render_new_game(
    game: Game,
    pool: HasItems,
    profile: GameProfile = OPERATOR_PROFILE,
) -> str:
    """新对局开场提示。"""
    pool_hint = f"{len(pool.items)} 名{profile.item_label}"
    attempts_text = "次数不限" if game.max_attempts == -1 else f"共 {game.max_attempts} 次机会"
    return (
        f"🎮 新对局已创建：{game.id}（{profile.title}）\n"
        f"本群{attempts_text}，从 {pool_hint} 中猜出答案。\n"
        f"艾特机器人并发送{profile.item_label}名进行猜测；输入 不猜了 结束本局。\n"
        "图例：🟩 正确 ｜ 🟨 部分命中 ｜ ⬜ 错误 ｜ ⬆️ 答案更高/更晚 ｜ ⬇️ 答案更低/更早"
    )


def render_help(prefix: str = "/") -> str:
    return (
        "📖 明日方舟猜干员 / 猜敌人（每群一局）\n"
        f"切换题库：{prefix}更换干员池 ｜ {prefix}更换敌人池（必须带 /）\n\n"
        "—— 干员池 ——\n"
        "@机器人 猜干员 <干员名>    开局并猜测该干员\n"
        "玛一把                       以玛恩纳作首猜开局，可裸发或@机器人\n"
        "粥一把 <干员名>             可裸发或@机器人开局并猜测\n"
        f"{prefix}查干员 <关键词>    检索干员资料，不影响对局\n"
        f"{prefix}角色池设置 <数字串>  例：{prefix}角色池设置 1256（只填 1-6）\n\n"
        "—— 敌人池 ——\n"
        "@机器人 猜敌人 <敌人名>    开局并猜测该敌人\n"
        f"{prefix}查敌人 <关键词>    检索敌人资料，不影响对局\n"
        "维度：危险等级 / 耐久 / 攻击 / 防御 / 法术抗性 / 实装\n\n"
        "—— 通用 ——\n"
        "@机器人 <名称>            提交猜测（需先开始对局）\n"
        f"{prefix}猜测次数 <次数>     例：{prefix}猜测次数 8；-1 表示不限\n"
        f"{prefix}本群难度             查看本群难度与当前题库\n"
        f"{prefix}重置难度             恢复默认难度\n"
        "不猜了                      结束当前对局（无对局时静默）\n"
        f"{prefix}对局状态           查看当前对局\n"
        f"{prefix}对局统计           查看本进程对局数量\n"
        f"{prefix}方舟帮助           查看本说明\n\n"
        "判定：干员为 稀有度 / 分支 / 阵营 / 种族 / 实装年份；\n"
        "敌人为 危险等级 / 四级强度评级 / 登场活动。\n"
        "🟨 表示部分命中（同职业不同分支、隐藏势力交叉）。"
    )


__all__ = [
    "ENEMY_PROFILE",
    "OPERATOR_PROFILE",
    "render_board",
    "render_guess",
    "render_help",
    "render_new_game",
]
