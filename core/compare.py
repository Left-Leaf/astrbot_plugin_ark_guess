"""五维比对：稀有度 / 分支 / 阵营 / 种族 / 实装年份。"""

from __future__ import annotations

from .factions import faction_set, has_faction_overlap
from .models import CompareResult, Operator


def _compare_number(guess: int, answer: int) -> str:
    if guess == answer:
        return "correct"
    return "higher" if guess < answer else "lower"


def compare_operators(guess: Operator, answer: Operator) -> CompareResult:
    """比对猜测干员与答案干员，返回五维状态。

    - 稀有度 / 实装时间：correct | higher | lower
    - 职业（分支）：correct（职业+分支均同）| close（同职业不同分支）| wrong
    - 阵营：所属势力有交集 → correct；仅隐藏势力交叉命中 → close；否则 wrong
    - 种族：字符串相等 → correct，否则 wrong
    """
    guess_profession = guess.profession.strip()
    answer_profession = answer.profession.strip()
    guess_subclass = guess.subclass.strip()
    answer_subclass = answer.subclass.strip()

    if guess_profession != answer_profession:
        subclass = "wrong"
    elif guess_subclass == answer_subclass:
        subclass = "correct"
    else:
        subclass = "close"

    guess_main = faction_set(guess.faction)
    answer_main = faction_set(answer.faction)
    guess_all = guess_main | {item.strip() for item in guess.faction_hidden if item.strip()}
    answer_all = answer_main | {item.strip() for item in answer.faction_hidden if item.strip()}

    if has_faction_overlap(guess_main, answer_main):
        faction = "correct"
    elif has_faction_overlap(guess_all, answer_all):
        faction = "close"
    else:
        faction = "wrong"

    race = "correct" if guess.race.strip() == answer.race.strip() else "wrong"

    return CompareResult(
        rarity=_compare_number(guess.rarity, answer.rarity),
        subclass=subclass,
        faction=faction,
        race=race,
        release_year=_compare_number(guess.release_year, answer.release_year),
    )
