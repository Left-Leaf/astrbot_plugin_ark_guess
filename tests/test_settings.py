"""按群难度设置与参数解析测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from core.settings import (  # noqa: E402
    GroupSettings,
    GroupSettingsStore,
    is_difficulty_text,
    parse_attempt_limit,
    parse_rarity_pool,
)


class ParseSettingsTests(unittest.TestCase):
    def test_parses_rarity_digits(self) -> None:
        self.assertEqual(parse_rarity_pool("123456"), (1, 2, 3, 4, 5, 6))
        self.assertEqual(parse_rarity_pool("1256"), (1, 2, 5, 6))
        self.assertEqual(parse_rarity_pool("136"), (1, 3, 6))
        self.assertEqual(parse_rarity_pool("66"), (6,))

    def test_parses_attempt_limits(self) -> None:
        self.assertEqual(parse_attempt_limit("-1"), -1)
        self.assertEqual(parse_attempt_limit("8"), 8)
        self.assertEqual(parse_attempt_limit("10"), 10)

    def test_rejects_invalid_values(self) -> None:
        for value in ("", "0", "7", "12a"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_rarity_pool(value)
        for value in ("", "0", "-2", "abc", "1.5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_attempt_limit(value)

    def test_detects_difficulty_commands(self) -> None:
        self.assertTrue(is_difficulty_text("/角色池设置 1256"))
        self.assertTrue(is_difficulty_text("/猜测次数 8"))
        self.assertTrue(is_difficulty_text("/本群难度"))
        self.assertTrue(is_difficulty_text("/重置难度"))
        self.assertTrue(is_difficulty_text("/更换干员池"))
        self.assertTrue(is_difficulty_text("/更换敌人池"))
        self.assertFalse(is_difficulty_text("角色池设置 1256"))
        self.assertFalse(is_difficulty_text("猜测次数 8"))
        self.assertFalse(is_difficulty_text("本群难度"))
        self.assertFalse(is_difficulty_text("更换干员池"))
        self.assertFalse(is_difficulty_text("更换敌人池"))
        self.assertFalse(is_difficulty_text("/角色池设置很高"))
        self.assertFalse(is_difficulty_text(None))


class SettingsStoreTests(unittest.TestCase):
    def test_persists_and_clears_group_settings(self) -> None:
        defaults = GroupSettings(rarities=(1, 2, 3, 4, 5, 6), max_attempts=8)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "group_settings.json"
            store = GroupSettingsStore(path, defaults)
            self.assertEqual(store.get("group:1"), defaults)
            self.assertEqual(store.get("group:1").pool, "operator")
            store.set(
                "group:1",
                GroupSettings(rarities=(6,), max_attempts=-1, pool="enemy"),
            )

            reloaded = GroupSettingsStore(path, defaults)
            self.assertTrue(reloaded.has("group:1"))
            self.assertEqual(reloaded.get("group:1").rarities, (6,))
            self.assertEqual(reloaded.get("group:1").max_attempts, -1)
            self.assertEqual(reloaded.get("group:1").pool, "enemy")

            self.assertTrue(reloaded.clear("group:1"))
            self.assertFalse(reloaded.has("group:1"))
            self.assertEqual(reloaded.get("group:1"), defaults)
            self.assertEqual(reloaded.get("group:1").pool, "operator")


if __name__ == "__main__":
    unittest.main()
