"""维度比对：干员五维 / 敌人六维。"""

from __future__ import annotations

from .factions import faction_set, has_faction_overlap
from .models import CompareResult, Enemy, Operator

LEVEL_RANK = {"普通": 1, "精英": 2, "领袖": 3}
GRADE_RANK = {
    "E": 1,
    "D": 2,
    "C": 3,
    "B": 4,
    "B+": 5,
    "A": 6,
    "A+": 7,
    "S": 8,
    "S+": 9,
    "SS": 10,
}


def _compare_number(guess: int, answer: int) -> str:
    if guess == answer:
        return "correct"
    return "higher" if guess < answer else "lower"


def _compare_grade(guess: str, answer: str) -> str:
    guess_rank = GRADE_RANK.get(guess.strip().upper())
    answer_rank = GRADE_RANK.get(answer.strip().upper())
    if guess_rank is None or answer_rank is None:
        return "correct" if guess.strip() == answer.strip() else "wrong"
    return _compare_number(guess_rank, answer_rank)


def _compare_level(guess: str, answer: str) -> str:
    guess_rank = LEVEL_RANK.get(guess.strip())
    answer_rank = LEVEL_RANK.get(answer.strip())
    if guess_rank is None or answer_rank is None:
        return "correct" if guess.strip() == answer.strip() else "wrong"
    return _compare_number(guess_rank, answer_rank)


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

    # 实装：登场活动一致 → correct（绿）；仅年份一致 → close（黄）；否则给年份方向
    year_state = _compare_number(guess.release_year, answer.release_year)
    guess_debut = guess.debut.strip()
    answer_debut = answer.debut.strip()
    if guess_debut and answer_debut and guess_debut == answer_debut:
        release_state = "correct"
    elif year_state == "correct":
        release_state = "close"
    else:
        release_state = year_state

    return CompareResult(
        d1=_compare_number(guess.rarity, answer.rarity),
        d2=subclass,
        d3=faction,
        d4=race,
        d5=release_state,
    )


def compare_enemies(guess: Enemy, answer: Enemy) -> CompareResult:
    """比对猜测敌人与答案敌人，返回六维状态。

    - 危险等级 / 耐久 / 攻击 / 防御 / 法术抗性：correct | higher | lower
    - 实装：同登场活动 → correct；否则按活动先后给出 higher / lower
      （higher 表示答案更晚实装）
    """
    if guess.debut.strip() == answer.debut.strip():
        debut = "correct"
    else:
        debut = _compare_number(guess.debut_order, answer.debut_order)

    return CompareResult(
        d1=_compare_level(guess.level, answer.level),
        d2=_compare_grade(guess.endure, answer.endure),
        d3=_compare_grade(guess.attack, answer.attack),
        d4=_compare_grade(guess.defence, answer.defence),
        d5=_compare_grade(guess.resistance, answer.resistance),
        d6=debut,
    )
