"""生成干员 / 敌人示例卡片，便于本地预览样式（非自动化测试）。

用法：python tests/preview_card.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from core.compare import compare_enemies  # noqa: E402
from core.data import load_operator_pool  # noqa: E402
from core.enemies import load_enemy_pool  # noqa: E402
from core.game import GameRegistry  # noqa: E402
from core.image_card import render_board_image  # noqa: E402
from core.profiles import ENEMY_PROFILE, OPERATOR_PROFILE  # noqa: E402

OUTPUT_DIR = Path(__file__).parent / "preview"


async def preview_operator() -> Path:
    pool = load_operator_pool(PLUGIN_ROOT / "data" / "operators.json")
    registry = GameRegistry(pool, max_attempts=8)
    game = registry.create("preview", answer_id="char_002_amiya")
    for operator_id in [
        "char_291_aglina",
        "char_1035_wisdel",
        "char_010_chen",
        "char_002_amiya",
    ]:
        await registry.submit("preview", operator_id)
    return render_board_image(game, pool, OUTPUT_DIR, OPERATOR_PROFILE)


async def preview_enemy() -> Path:
    pool = load_enemy_pool(PLUGIN_ROOT / "data" / "enemies.json")
    registry = GameRegistry(pool, comparator=compare_enemies, item_label="敌人")
    game = registry.create("preview_enemy", answer_id=pool.resolve("霜星，“冬痕”").id)
    for name in ["源石虫", "源石虫·α", "大鲍勃", "弑君者", "霜星，“冬痕”"]:
        await registry.submit("preview_enemy", name)
    return render_board_image(game, pool, OUTPUT_DIR, ENEMY_PROFILE)


async def main() -> None:
    print(await preview_operator())
    print(await preview_enemy())


asyncio.run(main())
