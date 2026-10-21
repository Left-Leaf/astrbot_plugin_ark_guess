"""势力列表拆分与交集判断（与 TS 数据层逻辑保持一致）。"""

from __future__ import annotations

import re

_FACTION_SEPARATORS = re.compile(r"[,，;；、]")


def split_factions(value: str | None) -> list[str]:
    """拆分 PRTS 势力字符串，去空、去重并保持原顺序。"""
    if not value:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for part in _FACTION_SEPARATORS.split(value):
        item = part.strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def faction_set(value: str | None) -> set[str]:
    return set(split_factions(value))


def has_faction_overlap(left: set[str], right: set[str]) -> bool:
    """判断两个势力集合是否有交集（小集合优先遍历）。"""
    if len(left) > len(right):
        left, right = right, left
    return any(item in right for item in left)
