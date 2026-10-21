"""生成一张示例卡片 HTML，便于本地预览样式（非自动化测试）。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))

from core.data import load_operator_pool  # noqa: E402
from core.game import GameRegistry  # noqa: E402
from core.image_card import render_board_image  # noqa: E402


async def main() -> None:
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

    output = render_board_image(game, pool, Path(__file__).parent)
    print(output)


asyncio.run(main())
