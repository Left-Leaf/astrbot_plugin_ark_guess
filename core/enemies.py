"""加载 enemies.json 并提供敌人解析（id / 名称 / 唯一模糊匹配）。"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import (
    AmbiguousEnemyError,
    EmptyPoolError,
    InvalidGuessError,
    UnknownEnemyError,
)
from .models import Enemy
from .resolve import resolve_item, search_items


@dataclass(frozen=True, slots=True)
class EnemyPool:
    """敌人出题池：只读，可被多个并发对局共享。"""

    version: str
    enemies: tuple[Enemy, ...]
    by_id: dict[str, Enemy]
    by_name: dict[str, list[Enemy]]

    @property
    def items(self) -> tuple[Enemy, ...]:
        return self.enemies

    @classmethod
    def from_records(
        cls, records: list[dict[str, Any]], version: str = "unknown"
    ) -> EnemyPool:
        enemies: list[Enemy] = []
        by_id: dict[str, Enemy] = {}
        by_name: dict[str, list[Enemy]] = {}

        for raw in records:
            enemy = _parse_enemy(raw)
            if enemy.id in by_id:
                continue
            enemies.append(enemy)
            by_id[enemy.id] = enemy
            by_name.setdefault(enemy.name, []).append(enemy)

        if not enemies:
            raise EmptyPoolError("题库为空，请检查 enemies.json")

        return cls(
            version=version,
            enemies=tuple(enemies),
            by_id=by_id,
            by_name=by_name,
        )

    def resolve(self, query: str) -> Enemy:
        """把用户输入解析为敌人：id → 名称精确 → 唯一子串。"""
        return resolve_item(
            self.enemies,
            self.by_id,
            self.by_name,
            query,
            kind="敌人",
            unknown_error=UnknownEnemyError,
            ambiguous_error=AmbiguousEnemyError,
            invalid_error=InvalidGuessError,
        )

    def search(self, query: str, limit: int = 10) -> list[Enemy]:
        """检索敌人名称或 ID；无子串命中时提供轻量错字候选。"""
        return search_items(self.enemies, query, limit)

    def random_enemy(self, rng: random.Random | None = None) -> Enemy:
        return (rng or random).choice(self.enemies)

    def random_item(
        self,
        rng: random.Random | None = None,
        min_rarity: int = 1,
        rarities: object = None,
    ) -> Enemy:
        """统一的出题入口；敌人没有稀有度，忽略稀有度参数。"""
        return self.random_enemy(rng)


def _parse_enemy(raw: dict[str, Any]) -> Enemy:
    try:
        enemy_id = str(raw["id"]).strip()
        name = str(raw["name"]).strip()
        level = str(raw["level"]).strip()
        endure = str(raw["endure"]).strip()
        attack = str(raw["attack"]).strip()
        defence = str(raw["defence"]).strip()
        resistance = str(raw["resistance"]).strip()
        debut = str(raw.get("debut") or "未知").strip() or "未知"
        debut_order = int(raw.get("debut_order", 0))
        sort_id = int(raw["sort_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"enemies.json 记录格式错误：{raw!r}") from exc

    if not enemy_id or not name:
        raise ValueError(f"enemies.json 存在空 id / name：{raw!r}")

    return Enemy(
        id=enemy_id,
        name=name,
        level=level,
        endure=endure,
        attack=attack,
        defence=defence,
        resistance=resistance,
        debut=debut,
        debut_order=debut_order,
        sort_id=sort_id,
        enemy_race=str(raw.get("enemy_race") or "未知").strip() or "未知",
        attack_type=str(raw.get("attack_type") or "未知").strip() or "未知",
        damage_type=str(raw.get("damage_type") or "未知").strip() or "未知",
        motion=str(raw.get("motion") or "未知").strip() or "未知",
    )


def load_enemy_pool(path: str | Path) -> EnemyPool:
    """从 enemies.json 加载题库（支持 {version, enemies:[...]} 或裸数组）。"""
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"题库文件不存在：{file_path}")
    payload = json.loads(file_path.read_text(encoding="utf-8"))

    if isinstance(payload, dict):
        records = payload.get("enemies") or []
        version = str(payload.get("version") or "unknown")
    else:
        records = payload
        version = "unknown"

    if not isinstance(records, list):
        raise ValueError("enemies.json 格式错误：enemies 必须是数组")
    return EnemyPool.from_records(records, version=version)
