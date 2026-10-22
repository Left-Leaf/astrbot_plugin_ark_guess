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
from astrbot.core.message.components import At, Plain

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
        self.self_id = "bot"
        self.messages: list[object] = []
        self.message_str = ""

    def set_plain(self, text: str) -> None:
        self.message_str = text
        self.messages = [Plain(text=text)]

    def set_mention(self, text: str) -> None:
        self.message_str = text
        self.messages = [At(qq=self.self_id), Plain(text=text)]

    def get_group_id(self) -> str:
        return self.group_id

    def get_self_id(self) -> str:
        return self.self_id

    def get_messages(self) -> list[object]:
        return self.messages

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
    trigger_filter = module._GameTriggerFilter()

    event.set_plain("大家准备猜干员了")
    if trigger_filter.filter(event, None):
        raise AssertionError("普通聊天不应触发裸指令处理器")

    print("\n--- 猜干员（裸文本不应触发）---")
    event.set_plain("猜干员")
    if trigger_filter.filter(event, None):
        raise AssertionError("主指令必须@机器人")
    for result in await collect(plugin.group_game_trigger(event)):
        show(result)
    if plugin.registry.current_game(plugin._session_key(event)) is not None:
        raise AssertionError("裸文本猜干员不应开局")

    print("\n--- @机器人 猜干员（开局）---")
    event.set_mention("猜干员")
    for result in await collect(plugin.group_game_trigger(event)):
        show(result)

    game = plugin.registry.current_game(plugin._session_key(event))
    if game is None or game.guesses:
        raise AssertionError("裸指令开局不应提交猜测")

    print("\n--- @机器人 阿米娅（提交猜测）---")
    event.set_mention("阿米娅")
    for result in await collect(plugin.group_game_trigger(event)):
        show(result)
    if len(game.guesses) != 1:
        raise AssertionError("@机器人+干员名应提交一次猜测")

    print("\n--- 玛一把（已有对局别名）---")
    event.set_plain("玛一把")
    for result in await collect(plugin.group_game_trigger(event)):
        show(result)

    print("\n--- @机器人 粥一把（已有对局别名）---")
    event.set_mention("粥一把")
    for result in await collect(plugin.group_game_trigger(event)):
        show(result)

    print("\n--- @机器人 不猜了（结束对局）---")
    event.set_mention("不猜了")
    for result in await collect(plugin.group_game_trigger(event)):
        show(result)
    if plugin.registry.current_game(plugin._session_key(event)) is not None:
        raise AssertionError("@机器人+不猜了应结束对局")

    print("\n--- 不猜了（无对局应静默）---")
    event.set_plain("不猜了")
    if await collect(plugin.group_game_trigger(event)):
        raise AssertionError("无对局时不猜了应静默")
    event.set_mention("不猜了")
    if await collect(plugin.group_game_trigger(event)):
        raise AssertionError("无对局时@机器人+不猜了应静默")

    print("\n--- 玛一把（裸别名重新开局）---")
    event.set_plain("玛一把")
    for result in await collect(plugin.group_game_trigger(event)):
        show(result)
    game = plugin.registry.current_game(plugin._session_key(event))
    if game is None or len(game.guesses) != 1 or game.guesses[0].operator_name != "玛恩纳":
        raise AssertionError("裸发玛一把应以玛恩纳作为第一次猜测")

    event.set_plain("不猜了")
    await collect(plugin.group_game_trigger(event))

    print("\n--- @机器人 玛一把（提及别名开局）---")
    event.set_mention("玛一把")
    for result in await collect(plugin.group_game_trigger(event)):
        show(result)
    game = plugin.registry.current_game(plugin._session_key(event))
    if game is None or len(game.guesses) != 1 or game.guesses[0].operator_name != "玛恩纳":
        raise AssertionError("@机器人+玛一把应以玛恩纳作为第一次猜测")
    event.set_plain("不猜了")
    await collect(plugin.group_game_trigger(event))

    print("\n--- 粥一把（裸别名重新开局）---")
    event.set_plain("粥一把")
    for result in await collect(plugin.group_game_trigger(event)):
        show(result)

    await plugin.terminate()


asyncio.run(main())
