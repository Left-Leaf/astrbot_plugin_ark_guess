"""需要 AstrBot 运行环境的冒烟测试：python tests/smoke_main.py

不作为 unittest 用例（文件名不以 test_ 开头），避免纯逻辑测试依赖 AstrBot。
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
from pathlib import Path

PLUGINS_DIR = Path(__file__).resolve().parents[2]
ASTRBOT_ROOT = PLUGINS_DIR.parents[1]
sys.path.insert(0, str(PLUGINS_DIR))
sys.path.insert(0, str(ASTRBOT_ROOT))
# 切到 AstrBot 根目录，避免 AstrBot 把运行产物写进插件 data/
os.chdir(ASTRBOT_ROOT)

module = importlib.import_module("astrbot_plugin_ark_guess.main")
plugin = module.ArkGuessPlugin(object(), {"max_attempts": 8, "render_mode": "text"})

print(f"题库：{len(plugin.pool.operators)} 名干员，版本 {plugin.pool.version}")


async def main() -> None:
    game = plugin.registry.create("smoke-session", answer_id="char_002_amiya")
    print(f"对局：{game.id}")
    outcome = await plugin.registry.submit("smoke-session", "阿米娅")
    print(f"状态：{outcome.game.status}")
    print(module.render_board(outcome.game, plugin.pool))


asyncio.run(main())
