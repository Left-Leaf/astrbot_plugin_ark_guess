"""按群保存的难度设置：答案稀有度池与最大猜测次数。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

RARITIES = (1, 2, 3, 4, 5, 6)
RARITY_TRIGGER = "角色池设置"
ATTEMPTS_TRIGGER = "猜测次数"
VIEW_TRIGGER = "本群难度"
RESET_TRIGGER = "重置难度"
_VIEW_TRIGGERS = frozenset({VIEW_TRIGGER})


@dataclass(frozen=True, slots=True)
class GroupSettings:
    """一个群的难度配置；max_attempts 为 -1 时表示不限次数。"""

    rarities: tuple[int, ...]
    max_attempts: int


def validate_settings(settings: GroupSettings) -> str | None:
    if not settings.rarities:
        return "请至少选择一个答案稀有度。"
    if any(rarity not in RARITIES for rarity in settings.rarities):
        return "稀有度必须是 1-6 的整数。"
    if settings.max_attempts == 0 or settings.max_attempts < -1:
        return "最大猜测次数必须是正整数，或 -1（不限次数）。"
    return None


def normalize_command_text(text: str | None) -> str:
    """允许指令带或不带前导斜杠。"""
    value = (text or "").strip()
    return value[1:].strip() if value.startswith("/") else value


def parse_rarity_pool(args: str) -> tuple[int, ...]:
    """解析“123456”“1256”“136”形式的稀有度数字串。"""
    digits = args.strip()
    if not digits or any(character not in "123456" for character in digits):
        raise ValueError("用法：角色池设置 123456（只填 1-6，可任意组合）")
    return tuple(sorted({int(character) for character in digits}))


def parse_attempt_limit(args: str) -> int:
    """解析猜测次数：正整数或 -1（不限）。"""
    text = args.strip()
    if not re.fullmatch(r"-?\d+", text):
        raise ValueError("用法：猜测次数 8；-1 表示不限次数")
    attempts = int(text)
    if attempts == 0 or attempts < -1:
        raise ValueError("最大猜测次数必须是正整数，或 -1（不限次数）。")
    return attempts


def is_difficulty_text(text: str | None) -> bool:
    """判断是否为难度相关指令，供群聊过滤器使用；必须带前导斜杠。"""
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return False
    value = normalize_command_text(raw)
    return (
        value in _VIEW_TRIGGERS
        or value in {RARITY_TRIGGER, ATTEMPTS_TRIGGER, RESET_TRIGGER}
        or value.startswith(f"{RARITY_TRIGGER} ")
        or value.startswith(f"{ATTEMPTS_TRIGGER} ")
    )


class GroupSettingsStore:
    """把每个群的设置持久化到 plugin_data 下的 JSON 文件。"""

    def __init__(self, path: str | Path, defaults: GroupSettings) -> None:
        self._path = Path(path)
        self._defaults = defaults
        self._groups: dict[str, GroupSettings] = {}
        self._load()

    @property
    def defaults(self) -> GroupSettings:
        return self._defaults

    def get(self, session_key: str) -> GroupSettings:
        return self._groups.get(session_key, self._defaults)

    def has(self, session_key: str) -> bool:
        return session_key in self._groups

    def set(self, session_key: str, settings: GroupSettings) -> None:
        invalid = validate_settings(settings)
        if invalid:
            raise ValueError(invalid)
        self._groups[session_key] = settings
        self._save()

    def clear(self, session_key: str) -> bool:
        if session_key not in self._groups:
            return False
        del self._groups[session_key]
        self._save()
        return True

    def _load(self) -> None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        groups = payload.get("groups") if isinstance(payload, dict) else None
        if not isinstance(groups, dict):
            return
        for session_key, raw in groups.items():
            if not isinstance(raw, dict):
                continue
            try:
                settings = GroupSettings(
                    rarities=tuple(
                        sorted(
                            {
                                int(rarity)
                                for rarity in raw.get("rarities", [])
                                if int(rarity) in RARITIES
                            }
                        )
                    ),
                    max_attempts=int(raw.get("maxAttempts", self._defaults.max_attempts)),
                )
            except (TypeError, ValueError):
                continue
            if validate_settings(settings) is None:
                self._groups[str(session_key)] = settings

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "groups": {
                session_key: {
                    "rarities": list(settings.rarities),
                    "maxAttempts": settings.max_attempts,
                }
                for session_key, settings in self._groups.items()
            },
        }
        temp_path = self._path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self._path)
