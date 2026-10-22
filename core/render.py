"""消息渲染：文本表格 + 色块表情（可交给 AstrBot 转图片）。"""

from __future__ import annotations

from .data import OperatorPool
from .models import Game, GuessRecord, Operator

GREEN = "🟩"
YELLOW = "🟨"
GREY = "⬜"
UP = "⬆️"
DOWN = "⬇️"

_SEPARATOR = " ｜ "


def _number_cell(value: int, state: str) -> str:
    if state == "correct":
        return f"{value} {GREEN}"
    arrow = UP if state == "higher" else DOWN
    return f"{value} {GREY}{arrow}"


def _subclass_cell(profession: str, subclass: str, state: str) -> str:
    tone = {"correct": GREEN, "close": YELLOW}.get(state, GREY)
    return f"{profession}/{subclass} {tone}"


def _faction_cell(operator: Operator, state: str) -> str:
    tone = {"correct": GREEN, "close": YELLOW}.get(state, GREY)
    text = operator.faction.replace(",", "、")
    if state == "close" and operator.faction_hidden:
        text += f"（隐藏：{'、'.join(operator.faction_hidden)}）"
    return f"{text} {tone}"


def _race_cell(race: str, state: str) -> str:
    tone = GREEN if state == "correct" else GREY
    return f"{race} {tone}"


def render_guess(record: GuessRecord, operator: Operator) -> str:
    """把一次猜测渲染成两行文本。"""
    result = record.result
    line = _SEPARATOR.join(
        [
            f"稀有度 {_number_cell(operator.rarity, result.rarity)}",
            f"职业/分支 {_subclass_cell(operator.profession, operator.subclass, result.subclass)}",
            f"阵营 {_faction_cell(operator, result.faction)}",
            f"种族 {_race_cell(operator.race, result.race)}",
            f"实装 {_number_cell(operator.release_year, result.release_year)}",
        ]
    )
    return f"第 {record.attempt} 次：{operator.name}\n{line}"


def _answer_line(game: Game, pool: OperatorPool) -> str:
    answer = pool.by_id.get(game.answer_id)
    if answer is None:
        return f"答案：{game.answer_id}"
    return (
        f"答案：{answer.name}（{answer.rarity}★ {answer.profession}/{answer.subclass}"
        f"，{answer.faction}）"
    )


def render_board(game: Game, pool: OperatorPool, history: int = 3) -> str:
    """渲染当前对局（默认只展示最近几次猜测，避免消息过长）。"""
    lines = [f"对局 {game.id} ｜ 已猜 {len(game.guesses)}/{game.max_attempts}"]

    records = game.guesses[-history:] if history > 0 else game.guesses
    for record in records:
        operator = pool.by_id.get(record.operator_id)
        if operator is not None:
            lines.append(render_guess(record, operator))

    if game.status == "won":
        lines.append(f"🎉 猜中了！{_answer_line(game, pool)}")
    elif game.status == "lost":
        lines.append(f"❌ 次数用尽。{_answer_line(game, pool)}")
    else:
        lines.append(
            f"还剩 {game.max_attempts - len(game.guesses)} 次机会，艾特机器人并发送干员名继续"
        )

    return "\n".join(lines)


def render_new_game(game: Game, pool: OperatorPool) -> str:
    """新对局开场提示。"""
    answer = pool.by_id.get(game.answer_id)
    pool_hint = f"{len(pool.operators)} 名干员" if answer else "题库"
    return (
        f"🎮 新对局已创建：{game.id}\n"
        f"本群共 {game.max_attempts} 次机会，从 {pool_hint} 中猜出答案。\n"
        "艾特机器人并发送干员名进行猜测；输入 不猜了 结束本局。\n"
        "图例：🟩 正确 ｜ 🟨 隐藏势力命中 ｜ ⬜ 错误 ｜ ⬆️ 答案更高/更晚 ｜ ⬇️ 答案更低/更早"
    )


def render_help(prefix: str = "/") -> str:
    return (
        "📖 明日方舟猜干员（每群一局）\n"
        "@机器人 猜干员 <干员名>    开局并猜测该干员\n"
        "玛一把                       以玛恩纳作首猜开局，可裸发或@机器人\n"
        "粥一把 <干员名>             可裸发或@机器人开局并猜测\n"
        "@机器人 <干员名>            提交猜测（需先开始对局）\n"
        f"{prefix}查干员 <关键词>    检索干员资料，不影响对局\n"
        "不猜了                      结束当前对局（无对局时静默）\n"
        f"{prefix}对局状态           查看当前对局\n"
        f"{prefix}对局统计           查看本进程对局数量\n"
        f"{prefix}方舟帮助           查看本说明\n\n"
        "判定：稀有度 / 分支 / 阵营 / 种族 / 实装年份。\n"
        "阵营仅隐藏势力命中时显示 🟨。"
    )
