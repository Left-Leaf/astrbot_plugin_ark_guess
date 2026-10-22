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
from .resolve import resolve_item, search_items


@dataclass(frozen=True, slots=True)
class OperatorPool:
    """出题池：只读，可被多个并发对局共享。"""

    version: str
    operators: tuple[Operator, ...]
    by_id: dict[str, Operator]
    by_name: dict[str, list[Operator]]

    @property
    def items(self) -> tuple[Operator, ...]:
        return self.operators

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
        return resolve_item(
            self.operators,
            self.by_id,
            self.by_name,
            query,
            kind="干员",
            unknown_error=UnknownOperatorError,
            ambiguous_error=AmbiguousOperatorError,
            invalid_error=InvalidGuessError,
        )

    def search(self, query: str, limit: int = 10) -> list[Operator]:
        """检索干员名称或 ID；无子串命中时提供轻量错字候选。"""
        return search_items(self.operators, query, limit)

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

    def random_item(
        self,
        rng: random.Random | None = None,
        min_rarity: int = 1,
        rarities: Collection[int] | None = None,
    ) -> Operator:
        """统一的出题入口，供 GameRegistry 无差别调用。"""
        return self.random_operator(rng, min_rarity, rarities)


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
        debut = str(raw.get("debut") or "").strip()
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
        debut=debut,
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
