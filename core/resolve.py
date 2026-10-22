"""干员 / 敌人题库共用的名称解析与检索逻辑。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, TypeVar


class NamedItem(Protocol):
    """题库条目至少包含 id 与 name。"""

    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...


ItemT = TypeVar("ItemT", bound=NamedItem)
ErrorFactory = Callable[..., Exception]


def resolve_item(
    items: Sequence[ItemT],
    by_id: Mapping[str, ItemT],
    by_name: Mapping[str, Sequence[ItemT]],
    query: str,
    *,
    kind: str,
    unknown_error: ErrorFactory,
    ambiguous_error: ErrorFactory,
    invalid_error: ErrorFactory,
) -> ItemT:
    """把用户输入解析为条目：id → 名称精确 → 唯一子串。"""
    text = (query or "").strip()
    compact = "".join(text.split())
    if not compact:
        raise invalid_error(f"请输入{kind}名或{kind} id")

    if compact in by_id:
        return by_id[compact]

    for key in (text, compact):
        exact = by_name.get(key)
        if exact:
            if len(exact) == 1:
                return exact[0]
            raise ambiguous_error(
                f"「{key}」匹配到多个{kind}，请输入更完整的名称",
                [item.name for item in exact],
            )

    folded = compact.casefold()
    exact_folded = [
        item
        for item in items
        if item.name.casefold() == folded or item.id.casefold() == folded
    ]
    if len(exact_folded) == 1:
        return exact_folded[0]
    if len(exact_folded) > 1:
        raise ambiguous_error(
            f"「{compact}」匹配到多个{kind}，请输入更完整的名称",
            [item.name for item in exact_folded],
        )

    contains: list[ItemT] = []
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            continue
        if folded in item.name.casefold() or folded in item.id.casefold():
            contains.append(item)
            seen.add(item.id)

    if len(contains) == 1:
        return contains[0]
    if not contains:
        raise unknown_error(f"找不到{kind}「{compact}」，可输入全名或{kind} id")
    raise ambiguous_error(
        f"「{compact}」匹配到多个{kind}，请从下列名称中选择",
        [item.name for item in contains[:10]],
    )


def search_items(items: Sequence[ItemT], query: str, limit: int = 10) -> list[ItemT]:
    """检索名称或 ID；无子串命中时提供轻量错字候选。"""
    compact = "".join((query or "").casefold().split())
    if not compact or len(compact) > 64 or limit <= 0:
        return []

    matches: list[tuple[int, ItemT]] = []
    for item in items:
        name = "".join(item.name.casefold().split())
        item_id = item.id.casefold()
        if name == compact or item_id == compact:
            rank = 0
        elif name.startswith(compact):
            rank = 1
        elif compact in name:
            rank = 2
        elif compact in item_id:
            rank = 3
        else:
            continue
        matches.append((rank, item))

    if matches:
        matches.sort(key=lambda entry: (entry[0], entry[1].name))
        return [item for _, item in matches[:limit]]

    max_distance = 1 if len(compact) < 5 else 2
    fuzzy = [
        (distance, item)
        for item in items
        if (distance := _edit_distance(compact, "".join(item.name.casefold().split())))
        <= max_distance
    ]
    fuzzy.sort(key=lambda entry: (entry[0], entry[1].name))
    return [item for _, item in fuzzy[:limit]]


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
