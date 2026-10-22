"""加载 operators.json 并提供干员解析（id / 名称 / 唯一模糊匹配）。"""

from __future__ import annotations

import json
import random
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import (
    AmbiguousOperatorError,
    EmptyPoolError,
    InvalidGuessError,
    UnknownOperatorError,
)
from .factions import split_factions
from .models import Operator


@dataclass(frozen=True, slots=True)
class OperatorPool:
    """出题池：只读，可被多个并发对局共享。"""

    version: str
    operators: tuple[Operator, ...]
    by_id: dict[str, Operator]
    by_name: dict[str, list[Operator]]

    @classmethod
    def from_records(cls, records: list[dict[str, Any]], version: str = "unknown") -> OperatorPool:
        operators: list[Operator] = []
        by_id: dict[str, Operator] = {}
        by_name: dict[str, list[Operator]] = {}

        for raw in records:
            operator = _parse_operator(raw)
            if operator.id in by_id:
                continue
            operators.append(operator)
            by_id[operator.id] = operator
            by_name.setdefault(operator.name, []).append(operator)

        if not operators:
            raise EmptyPoolError("题库为空，请检查 operators.json")

        return cls(
            version=version,
            operators=tuple(operators),
            by_id=by_id,
            by_name=by_name,
        )

    def resolve(self, query: str) -> Operator:
        """把用户输入解析为干员：id → 名称精确 → 唯一子串。"""
        text = (query or "").strip()
        compact = "".join(text.split())
        if not compact:
            raise InvalidGuessError("请输入干员名或干员 id")

        if compact in self.by_id:
            return self.by_id[compact]

        for key in (text, compact):
            exact = self.by_name.get(key)
            if exact:
                if len(exact) == 1:
                    return exact[0]
                raise AmbiguousOperatorError(
                    f"「{key}」匹配到多个干员，请输入更完整的名称",
                    [operator.name for operator in exact],
                )

        folded = compact.casefold()
        exact_folded = [
            operator
            for operator in self.operators
            if operator.name.casefold() == folded or operator.id.casefold() == folded
        ]
        if len(exact_folded) == 1:
            return exact_folded[0]
        if len(exact_folded) > 1:
            raise AmbiguousOperatorError(
                f"「{compact}」匹配到多个干员，请输入更完整的名称",
                [operator.name for operator in exact_folded],
            )

        contains: list[Operator] = []
        seen: set[str] = set()
        for operator in self.operators:
            if operator.id in seen:
                continue
            if folded in operator.name.casefold() or folded in operator.id.casefold():
                contains.append(operator)
                seen.add(operator.id)

        if len(contains) == 1:
            return contains[0]
        if not contains:
            raise UnknownOperatorError(f"找不到干员「{compact}」，可输入全名或干员 id")
        raise AmbiguousOperatorError(
            f"「{compact}」匹配到多个干员，请从下列名称中选择",
            [operator.name for operator in contains[:10]],
        )

    def search(self, query: str, limit: int = 10) -> list[Operator]:
        """检索干员名称或 ID；无子串命中时提供轻量错字候选。"""
        compact = "".join((query or "").casefold().split())
        if not compact or len(compact) > 64 or limit <= 0:
            return []

        matches: list[tuple[int, Operator]] = []
        for operator in self.operators:
            name = "".join(operator.name.casefold().split())
            operator_id = operator.id.casefold()
            if name == compact or operator_id == compact:
                rank = 0
            elif name.startswith(compact):
                rank = 1
            elif compact in name:
                rank = 2
            elif compact in operator_id:
                rank = 3
            else:
                continue
            matches.append((rank, operator))

        if matches:
            matches.sort(key=lambda item: (item[0], item[1].name))
            return [operator for _, operator in matches[:limit]]

        max_distance = 1 if len(compact) < 5 else 2
        fuzzy = [
            (distance, operator)
            for operator in self.operators
            if (distance := _edit_distance(compact, "".join(operator.name.casefold().split())))
            <= max_distance
        ]
        fuzzy.sort(key=lambda item: (item[0], item[1].name))
        return [operator for _, operator in fuzzy[:limit]]

    def candidates(
        self,
        min_rarity: int = 1,
        rarities: Collection[int] | None = None,
    ) -> list[Operator]:
        """按最低稀有度和可选稀有度集合过滤后的出题候选。"""
        if rarities is not None and not rarities:
            return []
        return [
            operator
            for operator in self.operators
            if operator.rarity >= min_rarity
            and (rarities is None or operator.rarity in rarities)
        ]

    def random_operator(
        self,
        rng: random.Random | None = None,
        min_rarity: int = 1,
        rarities: Collection[int] | None = None,
    ) -> Operator:
        candidates = self.candidates(min_rarity, rarities)
        if not candidates:
            raise EmptyPoolError("当前稀有度设置下没有可用于出题的干员")
        return (rng or random).choice(candidates)


def _edit_distance(left: str, right: str) -> int:
    """计算 Levenshtein 距离，检索候选规模较小，无需额外依赖。"""
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _parse_operator(raw: dict[str, Any]) -> Operator:
    try:
        operator_id = str(raw["id"]).strip()
        name = str(raw["name"]).strip()
        rarity = int(raw["rarity"])
        profession = str(raw["profession"]).strip()
        subclass = str(raw["subclass"]).strip()
        faction = str(raw.get("faction") or "无").strip() or "无"
        race = str(raw.get("race") or "未知").strip() or "未知"
        release_year = int(raw["release_year"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"operators.json 记录格式错误：{raw!r}") from exc

    hidden_raw = raw.get("faction_hidden") or []
    hidden = (
        split_factions(hidden_raw)
        if isinstance(hidden_raw, str)
        else [str(item).strip() for item in hidden_raw if str(item).strip()]
    )

    if not operator_id or not name:
        raise ValueError(f"operators.json 存在空 id / name：{raw!r}")

    return Operator(
        id=operator_id,
        name=name,
        rarity=rarity,
        profession=profession,
        subclass=subclass,
        faction=faction,
        faction_hidden=tuple(dict.fromkeys(hidden)),
        race=race,
        release_year=release_year,
    )


def load_operator_pool(path: str | Path) -> OperatorPool:
    """从 operators.json 加载题库（支持 {version, operators:[...]} 或裸数组）。"""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"题库文件不存在：{file_path}")
    payload = json.loads(file_path.read_text(encoding="utf-8"))

    if isinstance(payload, dict):
        records = payload.get("operators") or []
        version = str(payload.get("version") or "unknown")
    else:
        records = payload
        version = "unknown"

    if not isinstance(records, list):
        raise ValueError("operators.json 格式错误：operators 必须是数组")
    return OperatorPool.from_records(records, version=version)
