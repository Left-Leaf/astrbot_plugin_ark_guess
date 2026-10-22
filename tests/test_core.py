"""纯逻辑单元测试：不依赖 AstrBot，可用标准库 unittest 运行。"""

from __future__ import annotations

import asyncio
import random
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from core.compare import compare_enemies, compare_operators  # noqa: E402
from core.data import OperatorPool, load_operator_pool  # noqa: E402
from core.enemies import EnemyPool, load_enemy_pool  # noqa: E402
from core.errors import (  # noqa: E402
    DuplicateGuessError,
    GameAlreadyActiveError,
    GameNotFoundError,
    InvalidMaxAttemptsError,
    UnknownEnemyError,
    UnknownOperatorError,
)
from core.game import GameRegistry  # noqa: E402
from core.image_card import render_board_image  # noqa: E402
from core.models import Enemy, Operator  # noqa: E402
from core.profiles import ENEMY_PROFILE  # noqa: E402
from core.render import render_board, render_help, render_new_game  # noqa: E402


def make_operator(
    operator_id: str,
    name: str,
    *,
    rarity: int = 6,
    profession: str = "辅助",
    subclass: str = "凝滞师",
    faction: str = "罗德岛",
    hidden: tuple[str, ...] = (),
    race: str = "菲林",
    release_year: int = 2020,
) -> Operator:
    return Operator(
        id=operator_id,
        name=name,
        rarity=rarity,
        profession=profession,
        subclass=subclass,
        faction=faction,
        faction_hidden=hidden,
        race=race,
        release_year=release_year,
    )


def make_pool() -> OperatorPool:
    operators = [
        make_operator("char_a", "甲", faction="罗德岛"),
        make_operator("char_b", "乙", faction="巴别塔", hidden=("罗德岛",)),
        make_operator("char_c", "丙", faction="维多利亚", hidden=("使徒",)),
        make_operator("char_d", "丁", faction="莱茵生命"),
        make_operator("char_e", "戊", faction="企鹅物流"),
        make_operator("char_f", "己", faction="深海猎人"),
    ]
    return OperatorPool.from_records(
        [
            {
                "id": operator.id,
                "name": operator.name,
                "rarity": operator.rarity,
                "profession": operator.profession,
                "subclass": operator.subclass,
                "faction": operator.faction,
                "faction_hidden": list(operator.faction_hidden),
                "race": operator.race,
                "release_year": operator.release_year,
            }
            for operator in operators
        ],
        version="test",
    )


class CompareTests(unittest.TestCase):
    def test_main_faction_overlap_is_correct(self) -> None:
        guess = make_operator("g", "猜", faction="炎-龙门,企鹅物流")
        answer = make_operator("a", "答", faction="炎-龙门,龙门近卫局")
        self.assertEqual(compare_operators(guess, answer).faction, "correct")

    def test_hidden_faction_overlap_is_close(self) -> None:
        guess = make_operator("g", "猜", faction="巴别塔", hidden=("罗德岛",))
        answer = make_operator("a", "答", faction="罗德岛")
        self.assertEqual(compare_operators(guess, answer).faction, "close")

    def test_cross_hidden_match_is_close(self) -> None:
        guess = make_operator("g", "猜", faction="卡西米尔", hidden=("使徒",))
        answer = make_operator("a", "答", faction="使徒")
        self.assertEqual(compare_operators(guess, answer).faction, "close")

    def test_no_overlap_is_wrong(self) -> None:
        guess = make_operator("g", "猜", faction="罗德岛", hidden=("叙拉古",))
        answer = make_operator("a", "答", faction="维多利亚", hidden=("使徒",))
        self.assertEqual(compare_operators(guess, answer).faction, "wrong")

    def test_number_and_subclass_states(self) -> None:
        guess = make_operator("g", "猜", rarity=4, subclass="削弱者", release_year=2019)
        answer = make_operator("a", "答", rarity=6, release_year=2023)
        result = compare_operators(guess, answer)
        self.assertEqual(result.rarity, "higher")
        self.assertEqual(result.release_year, "higher")
        self.assertEqual(result.subclass, "close")


class DataTests(unittest.TestCase):
    def test_bundled_dataset_loads(self) -> None:
        pool = load_operator_pool(PLUGIN_ROOT / "data" / "operators.json")
        self.assertGreater(len(pool.operators), 400)
        self.assertTrue(pool.version)

    def test_resolve_by_name_and_id(self) -> None:
        pool = load_operator_pool(PLUGIN_ROOT / "data" / "operators.json")
        self.assertEqual(pool.resolve("阿米娅").id, "char_002_amiya")
        self.assertEqual(pool.resolve("char_002_amiya").name, "阿米娅")

    def test_unique_substring_and_ambiguity(self) -> None:
        pool = make_pool()
        self.assertEqual(pool.resolve("甲").id, "char_a")
        with self.assertRaises(UnknownOperatorError):
            pool.resolve("不存在的干员")

    def test_search_finds_name_substrings(self) -> None:
        pool = make_pool()
        self.assertEqual([operator.name for operator in pool.search("乙")], ["乙"])

    def test_search_suggests_typo_candidates(self) -> None:
        pool = make_pool()
        self.assertEqual([operator.name for operator in pool.search("甲甲")], ["甲"])

    def test_search_empty_query_returns_no_results(self) -> None:
        self.assertEqual(make_pool().search("   "), [])


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_instances_are_isolated(self) -> None:
        registry = GameRegistry(make_pool(), max_attempts=3)
        game_a = registry.create("session-a", answer_id="char_a")
        game_b = registry.create("session-b", answer_id="char_b")

        await registry.submit("session-a", "char_a")
        self.assertEqual(registry.get_game(game_a.id).status, "won")  # type: ignore[union-attr]
        self.assertEqual(registry.get_game(game_b.id).status, "playing")  # type: ignore[union-attr]
        self.assertEqual(len(registry.get_game(game_b.id).guesses), 0)  # type: ignore[union-attr]

    async def test_concurrent_guesses_are_serialized(self) -> None:
        registry = GameRegistry(make_pool(), max_attempts=5)
        game = registry.create("s", answer_id="char_a")

        outcomes = await asyncio.gather(
            *(registry.submit("s", name) for name in ["乙", "丙", "丁", "戊", "己"])
        )

        self.assertEqual(sorted(item.record.attempt for item in outcomes), [1, 2, 3, 4, 5])
        self.assertEqual(len(game.guesses), 5)
        self.assertEqual(game.status, "lost")

    async def test_duplicate_concurrent_guess(self) -> None:
        registry = GameRegistry(make_pool())
        registry.create("s", answer_id="char_a")

        results = await asyncio.gather(
            registry.submit("s", "乙"),
            registry.submit("s", "乙"),
            return_exceptions=True,
        )
        errors = [item for item in results if isinstance(item, Exception)]
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], DuplicateGuessError)
        self.assertEqual(len(registry.get_game(registry.current_game("s").id).guesses), 1)  # type: ignore[union-attr]

    async def test_join_by_suffix(self) -> None:
        registry = GameRegistry(make_pool())
        game = registry.create("owner", answer_id="char_a")
        suffix = game.id[-6:]
        joined = registry.join("guest", suffix)
        self.assertEqual(joined.id, game.id)
        outcome = await registry.submit("guest", "乙")
        self.assertEqual(outcome.record.attempt, 1)

    def test_second_game_in_same_session_is_rejected(self) -> None:
        registry = GameRegistry(make_pool())
        registry.create("s", answer_id="char_a")
        with self.assertRaises(GameAlreadyActiveError):
            registry.create("s", answer_id="char_b")

    def test_invalid_attempt_limits_are_rejected(self) -> None:
        registry = GameRegistry(make_pool())
        for attempts in (0, -2):
            with self.subTest(attempts=attempts), self.assertRaises(InvalidMaxAttemptsError):
                registry.create(f"s{attempts}", answer_id="char_a", max_attempts=attempts)

    async def test_unlimited_attempts_never_lose(self) -> None:
        registry = GameRegistry(make_pool(), max_attempts=1)
        game = registry.create("s", answer_id="char_a", max_attempts=-1)
        for name in ["乙", "丙", "丁", "戊", "己"]:
            outcome = await registry.submit("s", name)
            self.assertTrue(outcome.game.playing)
        self.assertEqual(game.status, "playing")
        self.assertEqual(len(game.guesses), 5)

    def test_rarity_pool_limits_answer(self) -> None:
        pool = OperatorPool.from_records(
            [
                {
                    "id": "char_4",
                    "name": "四星",
                    "rarity": 4,
                    "profession": "辅助",
                    "subclass": "凝滞师",
                    "faction": "罗德岛",
                    "faction_hidden": [],
                    "race": "菲林",
                    "release_year": 2020,
                },
                {
                    "id": "char_6",
                    "name": "六星",
                    "rarity": 6,
                    "profession": "辅助",
                    "subclass": "凝滞师",
                    "faction": "罗德岛",
                    "faction_hidden": [],
                    "race": "菲林",
                    "release_year": 2021,
                },
            ],
            version="test",
        )
        registry = GameRegistry(pool)
        game = registry.create("s", max_attempts=-1, rarities=(4,))
        self.assertEqual(game.max_attempts, -1)
        self.assertEqual(pool.by_id[game.answer_id].rarity, 4)

    def test_start_or_get_returns_existing_game(self) -> None:
        registry = GameRegistry(make_pool())
        first, created = registry.start_or_get("group:1", answer_id="char_a")
        self.assertTrue(created)

        second, created_again = registry.start_or_get("group:1")
        self.assertFalse(created_again)
        self.assertEqual(second.id, first.id)

        other, other_created = registry.start_or_get("group:2")
        self.assertTrue(other_created)
        self.assertNotEqual(other.id, first.id)

    def test_restart_after_close_creates_new_game(self) -> None:
        registry = GameRegistry(make_pool())
        first, _ = registry.start_or_get("group:1", answer_id="char_a")
        registry.close("group:1")
        second, created = registry.start_or_get("group:1", answer_id="char_b")
        self.assertTrue(created)
        self.assertNotEqual(second.id, first.id)

    async def test_submit_without_game_raises(self) -> None:
        registry = GameRegistry(make_pool())
        with self.assertRaises(GameNotFoundError):
            await registry.submit("group:1", "甲")

    def test_expired_games_are_recycled(self) -> None:
        clock = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        registry = GameRegistry(make_pool(), ttl_minutes=1, now=lambda: clock[0])
        game = registry.create("s", answer_id="char_a")
        clock[0] += timedelta(minutes=2)

        expired = registry.cleanup_expired()
        self.assertIn(game.id, expired)
        with self.assertRaises(GameNotFoundError):
            asyncio.run(registry.submit("s", "乙"))

    def test_stats(self) -> None:
        registry = GameRegistry(make_pool())
        registry.create("a", answer_id="char_a")
        registry.create("b", answer_id="char_b")
        self.assertEqual(registry.stats(), {"total": 2, "playing": 2, "won": 0, "lost": 0})


class RenderTests(unittest.TestCase):
    def test_render_board_contains_symbols(self) -> None:
        registry = GameRegistry(make_pool())
        game = registry.create("s", answer_id="char_a")
        self.assertIn("🟩", render_new_game(game, registry.pool))
        self.assertIn("查干员", render_help())

    def test_hidden_match_renders_yellow(self) -> None:
        registry = GameRegistry(make_pool())
        game = registry.create("s", answer_id="char_a")
        asyncio.run(registry.submit("s", "乙"))
        text = render_board(game, registry.pool)
        self.assertIn("🟨", text)
        self.assertIn("隐藏：罗德岛", text)
        self.assertIn("辅助/凝滞师", text)


class ImageRenderTests(unittest.TestCase):
    def test_image_card_is_created_with_tone_colors(self) -> None:
        registry = GameRegistry(make_pool())
        game = registry.create("s", answer_id="char_a")
        asyncio.run(registry.submit("s", "乙"))

        with tempfile.TemporaryDirectory() as tmp:
            path = render_board_image(game, registry.pool, tmp)
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 0)

            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertGreater(image.width, 800)
                self.assertGreater(image.height, 200)
                pixels = image.convert("RGB").getcolors(maxcolors=image.width * image.height)
                colors = [color for _, color in pixels or []]
                self.assertTrue(
                    any(r > 200 and g > 150 and b < 80 for r, g, b in colors),
                    "应包含黄色部分命中色块",
                )
                self.assertTrue(
                    any(g > 150 and r < 100 and b < 140 for r, g, b in colors),
                    "应包含绿色正确色块",
                )

    def test_image_card_marks_direction_and_wrong(self) -> None:
        pool = OperatorPool.from_records(
            [
                {
                    "id": "char_ans",
                    "name": "答案",
                    "rarity": 6,
                    "profession": "辅助",
                    "subclass": "凝滞师",
                    "faction": "罗德岛",
                    "faction_hidden": [],
                    "race": "菲林",
                    "release_year": 2023,
                },
                {
                    "id": "char_guess",
                    "name": "猜测",
                    "rarity": 4,
                    "profession": "辅助",
                    "subclass": "凝滞师",
                    "faction": "维多利亚",
                    "faction_hidden": [],
                    "race": "龙",
                    "release_year": 2019,
                },
            ],
            version="test",
        )
        registry = GameRegistry(pool)
        game = registry.create("s", answer_id="char_ans")
        asyncio.run(registry.submit("s", "char_guess"))

        with tempfile.TemporaryDirectory() as tmp:
            path = render_board_image(game, pool, tmp)
            with Image.open(path) as image:
                pixels = image.convert("RGB").getcolors(maxcolors=image.width * image.height)
                colors = [color for _, color in pixels or []]
                self.assertTrue(
                    any(b > 180 and r < 100 for r, g, b in colors),
                    "数值方向提示应使用蓝色",
                )
                self.assertTrue(
                    any(r > 180 and g < 120 and b < 120 for r, g, b in colors),
                    "错误项应使用红色",
                )

    def test_image_handles_empty_and_long_text(self) -> None:
        pool = OperatorPool.from_records(
            [
                {
                    "id": "char_long",
                    "name": "名字非常非常长的测试干员名称",
                    "rarity": 6,
                    "profession": "辅助",
                    "subclass": "凝滞师",
                    "faction": "罗德岛,罗德岛-精英干员,巴别塔",
                    "faction_hidden": ["雷姆必拓", "巴别塔"],
                    "race": "卡特斯/奇美拉",
                    "release_year": 2020,
                }
            ]
        )
        registry = GameRegistry(pool)
        game = registry.create("s", answer_id="char_long")

        with tempfile.TemporaryDirectory() as tmp:
            empty_path = render_board_image(game, pool, tmp)
            self.assertTrue(empty_path.is_file())

            asyncio.run(registry.submit("s", "char_long"))
            played_path = render_board_image(game, pool, tmp)
            self.assertTrue(played_path.is_file())


def make_enemy(
    enemy_id: str,
    name: str,
    *,
    level: str = "普通",
    endure: str = "B",
    attack: str = "B",
    defence: str = "B",
    resistance: str = "B",
    debut: str = "初始",
    debut_order: int = 0,
    sort_id: int = 1,
) -> Enemy:
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
        enemy_race="感染生物",
        attack_type="近战",
        damage_type="物理",
        motion="地面",
    )


def enemy_record(enemy: Enemy) -> dict[str, object]:
    return {
        "id": enemy.id,
        "name": enemy.name,
        "level": enemy.level,
        "endure": enemy.endure,
        "attack": enemy.attack,
        "defence": enemy.defence,
        "resistance": enemy.resistance,
        "debut": enemy.debut,
        "debut_order": enemy.debut_order,
        "sort_id": enemy.sort_id,
        "enemy_race": enemy.enemy_race,
        "attack_type": enemy.attack_type,
        "damage_type": enemy.damage_type,
        "motion": enemy.motion,
    }


def make_enemy_pool() -> EnemyPool:
    enemies = [
        make_enemy("enemy_a", "源石虫", endure="E", attack="E", defence="E"),
        make_enemy(
            "enemy_b",
            "源石虫·α",
            level="精英",
            endure="D",
            attack="C",
            defence="B",
            resistance="A",
            debut="骑兵与猎人",
            debut_order=1,
            sort_id=20,
        ),
        make_enemy(
            "enemy_c",
            "霜星",
            level="领袖",
            endure="S",
            attack="A",
            defence="D",
            resistance="S",
            debut="主线第五章",
            debut_order=2,
            sort_id=80,
        ),
    ]
    return EnemyPool.from_records([enemy_record(enemy) for enemy in enemies], version="test")


class EnemyCompareTests(unittest.TestCase):
    def test_grade_order_and_direction(self) -> None:
        guess = make_enemy("g", "g", endure="B", attack="B+", defence="A", resistance="SS")
        answer = make_enemy("a", "a", endure="B+", attack="B", defence="A+", resistance="S")
        result = compare_enemies(guess, answer)
        self.assertEqual(result.d2, "higher")
        self.assertEqual(result.d3, "lower")
        self.assertEqual(result.d4, "higher")
        self.assertEqual(result.d5, "lower")

    def test_equal_grades_are_correct(self) -> None:
        guess = make_enemy("g", "g", endure="A+", attack="S", defence="C", resistance="D")
        result = compare_enemies(guess, guess)
        self.assertEqual(result.states, ("correct",) * 6)

    def test_level_order(self) -> None:
        guess = make_enemy("g", "g", level="普通")
        elite = make_enemy("e", "e", level="精英")
        boss = make_enemy("b", "b", level="领袖")
        self.assertEqual(compare_enemies(guess, elite).d1, "higher")
        self.assertEqual(compare_enemies(guess, boss).d1, "higher")
        self.assertEqual(compare_enemies(boss, guess).d1, "lower")
        self.assertEqual(compare_enemies(elite, elite).d1, "correct")

    def test_debut_uses_activity_order(self) -> None:
        early = make_enemy("e", "e", debut="初始", debut_order=0)
        late = make_enemy("l", "l", debut="长夜临光", debut_order=9)
        self.assertEqual(compare_enemies(early, late).d6, "higher")
        self.assertEqual(compare_enemies(late, early).d6, "lower")
        self.assertEqual(compare_enemies(early, early).d6, "correct")

    def test_same_debut_is_correct_even_with_different_sort_id(self) -> None:
        first = make_enemy("f", "f", debut="将进酒", debut_order=30, sort_id=383)
        second = make_enemy("s", "s", debut="将进酒", debut_order=30, sort_id=416)
        self.assertEqual(compare_enemies(first, second).d6, "correct")


class EnemyDataTests(unittest.TestCase):
    def test_bundled_dataset_loads(self) -> None:
        pool = load_enemy_pool(PLUGIN_ROOT / "data" / "enemies.json")
        self.assertGreater(len(pool.enemies), 1500)
        self.assertTrue(pool.version)
        enemy = pool.resolve("源石虫")
        self.assertTrue(enemy.debut)
        self.assertIn(enemy.level, {"普通", "精英", "领袖"})

    def test_resolve_by_id_and_ambiguity(self) -> None:
        pool = make_enemy_pool()
        self.assertEqual(pool.resolve("源石虫").id, "enemy_a")
        self.assertEqual(pool.resolve("enemy_b").name, "源石虫·α")
        with self.assertRaises(UnknownEnemyError):
            pool.resolve("不存在的敌人")

    def test_search_finds_enemy_names(self) -> None:
        pool = make_enemy_pool()
        self.assertEqual([enemy.name for enemy in pool.search("霜星")], ["霜星"])
        self.assertEqual(pool.search("   "), [])

    def test_random_item_ignores_rarity_filters(self) -> None:
        pool = make_enemy_pool()
        picked = pool.random_item(random.Random(0), 6, (6,))
        self.assertIn(picked.id, {"enemy_a", "enemy_b", "enemy_c"})


class EnemyRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_uses_enemy_comparator(self) -> None:
        registry = GameRegistry(
            make_enemy_pool(),
            comparator=compare_enemies,
            item_label="敌人",
            start_command="猜敌人",
        )
        game = registry.create("s", answer_id="enemy_c")
        outcome = await registry.submit("s", "源石虫")
        self.assertEqual(outcome.record.item_id, "enemy_a")
        self.assertEqual(outcome.record.result.d1, "higher")
        self.assertEqual(len(outcome.record.result.states), 6)
        self.assertTrue(game.playing)

    async def test_duplicate_enemy_guess(self) -> None:
        registry = GameRegistry(make_enemy_pool(), comparator=compare_enemies)
        registry.create("s", answer_id="enemy_c")
        await registry.submit("s", "源石虫")
        with self.assertRaises(DuplicateGuessError):
            await registry.submit("s", "源石虫")


class EnemyRenderTests(unittest.TestCase):
    def test_text_board_has_six_dimensions(self) -> None:
        registry = GameRegistry(
            make_enemy_pool(), comparator=compare_enemies, item_label="敌人"
        )
        game = registry.create("s", answer_id="enemy_c")
        asyncio.run(registry.submit("s", "源石虫"))
        text = render_board(game, registry.pool, ENEMY_PROFILE)
        for label in ("危险等级", "耐久", "攻击", "防御", "法术抗性", "实装"):
            self.assertIn(label, text)
        self.assertIn("猜敌人", text)

    def test_new_game_and_help_mention_enemy_pool(self) -> None:
        registry = GameRegistry(
            make_enemy_pool(), comparator=compare_enemies, item_label="敌人"
        )
        game = registry.create("s", answer_id="enemy_c")
        self.assertIn("名敌人", render_new_game(game, registry.pool, ENEMY_PROFILE))
        help_text = render_help()
        self.assertIn("更换敌人池", help_text)
        self.assertIn("猜敌人", help_text)

    def test_image_card_renders_six_columns(self) -> None:
        registry = GameRegistry(
            make_enemy_pool(), comparator=compare_enemies, item_label="敌人"
        )
        game = registry.create("s", answer_id="enemy_c")
        asyncio.run(registry.submit("s", "源石虫"))

        with tempfile.TemporaryDirectory() as tmp:
            path = render_board_image(game, registry.pool, tmp, ENEMY_PROFILE)
            self.assertTrue(path.is_file())
            with Image.open(path) as image:
                self.assertEqual(image.format, "PNG")
                self.assertGreater(image.width, 800)
                pixels = image.convert("RGB").getcolors(maxcolors=image.width * image.height)
                colors = [color for _, color in pixels or []]
                self.assertTrue(
                    any(b > 180 and r < 100 for r, g, b in colors),
                    "等级 / 评级方向提示应使用蓝色",
                )


if __name__ == "__main__":
    unittest.main()
