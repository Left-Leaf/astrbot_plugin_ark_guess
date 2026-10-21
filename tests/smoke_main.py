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
plugin = module.ArkGuessPlugin(object(), {"max_attempts": 8, "render_mode": "image"})

print(f"题库：{len(plugin.pool.operators)} 名干员，版本 {plugin.pool.version}")


class FakeResult:
    def __init__(self) -> None:
        self.image = ""

    def base64_image(self, payload: str) -> "FakeResult":
        self.image = payload
        return self


class FakeEvent:
    """只实现指令层用到的事件接口。"""

    def __init__(self, group_id: str = "1") -> None:
        self.group_id = group_id
        self.unified_msg_origin = f"test:GroupMessage:{group_id}"

    def get_group_id(self) -> str:
        return self.group_id

    def plain_result(self, text: str) -> dict[str, str]:
        return {"type": "text", "text": text}

    def image_result(self, path: str) -> dict[str, str]:
        return {"type": "image", "path": str(path)}

    def make_result(self) -> FakeResult:
        return FakeResult()

    def stop_event(self) -> None:
        pass


async def collect(generator) -> list[object]:
    return [item async for item in generator]


def show(result: object) -> None:
    if isinstance(result, dict):
        print(result.get("text") or result.get("path"))
    else:
        print(f"<image base64: {len(result.image)} chars>")  # type: ignore[attr-defined]


async def main() -> None:
    event = FakeEvent()

    print("\n--- /粥一把 阿米娅（开局并立即猜一次）---")
    for result in await collect(plugin.ark_start(event, "阿米娅")):
        show(result)

    print("\n--- /粥一把（已有对局）---")
    for result in await collect(plugin.ark_start(event, "")):
        show(result)

    print("\n--- /粥一把 凯尔希（已有对局，不应新增猜测）---")
    for result in await collect(plugin.ark_start(event, "凯尔希")):
        show(result)

    print("\n--- /不猜了 ---")
    for result in await collect(plugin.ark_end(event)):
        show(result)

    print("\n--- /粥一把（结束后重新开局）---")
    for result in await collect(plugin.ark_start(event, "")):
        show(result)

    await plugin.terminate()


asyncio.run(main())
