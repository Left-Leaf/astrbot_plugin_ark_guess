"""需要 AstrBot 运行环境的冒烟测试：python tests/smoke_main.py

不作为 unittest 用例（文件名不以 test_ 开头），避免纯逻辑测试依赖 AstrBot。
"""

from __future__ import annotations

import asyncio
import importlib
import os
import sys
import tempfile
from pathlib import Path

PLUGINS_DIR = Path(__file__).resolve().parents[2]
ASTRBOT_ROOT = PLUGINS_DIR.parents[1]
sys.path.insert(0, str(PLUGINS_DIR))
sys.path.insert(0, str(ASTRBOT_ROOT))
from astrbot.core.message.components import At, Plain  # noqa: E402

# 切到 AstrBot 根目录，避免 AstrBot 把运行产物写进插件 data/
os.chdir(ASTRBOT_ROOT)

module = importlib.import_module("astrbot_plugin_ark_guess.main")
plugin = module.ArkGuessPlugin(object(), {"max_attempts": 8, "render_mode": "text"})

print(
    f"题库：{len(plugin.operator_pool.operators)} 名干员，"
    f"{len(plugin.enemy_pool.enemies)} 名敌人"
)

OPERATOR_REGISTRY = plugin.registries[module.POOL_OPERATOR]
ENEMY_REGISTRY = plugin.registries[module.POOL_ENEMY]

# 用临时目录存放本群设置，避免污染真实 plugin_data
_TMP_DIR = tempfile.TemporaryDirectory()
plugin.group_settings = module.GroupSettingsStore(
    Path(_TMP_DIR.name) / "group_settings.json",
    plugin.group_settings.defaults,
)


class FakeResult:
    def __init__(self) -> None:
        self.image = ""

    def base64_image(self, payload: str) -> FakeResult:
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
    if isinstance(result, str):
        print(result)
    elif isinstance(result, dict):
        print(result.get("text") or result.get("path"))
    else:
        print(f"<image base64: {len(result.image)} chars>")  # type: ignore[attr-defined]


def only_text(results: list[object]) -> str:
    return "\n".join(
        str(item.get("text", "")) for item in results if isinstance(item, dict)
    )


async def main() -> None:
    event = FakeEvent()
    trigger_filter = module._GameTriggerFilter()
    session_key = plugin._session_key(event)

    event.set_plain("大家准备猜干员了")
    if trigger_filter.filter(event, None):
        raise AssertionError("普通聊天不应触发裸指令处理器")

    event.set_plain("干员池稀有度 6")
    if trigger_filter.filter(event, None):
        raise AssertionError("难度设置指令必须带斜杠")
    event.set_plain("/干员池稀有度 6")
    if not trigger_filter.filter(event, None):
        raise AssertionError("带斜杠的干员池稀有度应触发")

    event.set_plain("/更换敌人池")
    if trigger_filter.filter(event, None):
        raise AssertionError("已移除的切换题库指令不应触发")

    print("\n--- 猜干员（裸文本不应触发）---")
    event.set_plain("猜干员")
    if trigger_filter.filter(event, None):
        raise AssertionError("主指令必须@机器人")

    print("\n--- @机器人 猜干员（缺名字，不应开局）---")
    event.set_mention("猜干员")
    text = only_text(await collect(plugin.group_game_trigger(event)))
    show(text)
    if OPERATOR_REGISTRY.current_game(session_key) is not None:
        raise AssertionError("猜干员缺少参数时不应开局")

    print("\n--- @机器人 猜干员 阿米娅（带参开局）---")
    event.set_mention("猜干员 阿米娅")
    show(only_text(await collect(plugin.group_game_trigger(event))))
    game = OPERATOR_REGISTRY.current_game(session_key)
    if game is None or len(game.guesses) != 1 or game.guesses[0].operator_name != "阿米娅":
        raise AssertionError("猜干员带参应以指定干员作为首猜")

    print("\n--- @机器人 能天使（提交第二次猜测）---")
    event.set_mention("能天使")
    show(only_text(await collect(plugin.group_game_trigger(event))))
    if len(game.guesses) != 2:
        raise AssertionError("@机器人+干员名应追加一次猜测")

    print("\n--- 玛一把（已有对局别名）---")
    event.set_plain("玛一把")
    show(only_text(await collect(plugin.group_game_trigger(event))))

    print("\n--- @机器人 不猜了（结束对局）---")
    event.set_mention("不猜了")
    show(only_text(await collect(plugin.group_game_trigger(event))))
    if OPERATOR_REGISTRY.current_game(session_key) is not None:
        raise AssertionError("@机器人+不猜了应结束对局")

    print("\n--- 不猜了（无对局应静默）---")
    event.set_plain("不猜了")
    if await collect(plugin.group_game_trigger(event)):
        raise AssertionError("无对局时不猜了应静默")

    print("\n--- 玛一把（裸别名重新开局）---")
    event.set_plain("玛一把")
    show(only_text(await collect(plugin.group_game_trigger(event))))
    game = OPERATOR_REGISTRY.current_game(session_key)
    if game is None or len(game.guesses) != 1 or game.guesses[0].operator_name != "玛恩纳":
        raise AssertionError("裸发玛一把应以玛恩纳作为第一次猜测")

    event.set_plain("不猜了")
    await collect(plugin.group_game_trigger(event))

    print("\n--- 粥一把（已移除，应不触发）---")
    event.set_plain("粥一把 阿米娅")
    if await collect(plugin.group_game_trigger(event)):
        raise AssertionError("粥一把 已移除，不应有任何回复")

    print("\n--- /更换敌人池（已移除，应不触发）---")
    event.set_plain("/更换敌人池")
    if await collect(plugin.group_game_trigger(event)):
        raise AssertionError("更换题库指令已移除，不应有任何回复")

    print("\n--- 干员池与敌人池并行 ---")
    event.set_mention("猜干员 阿米娅")
    show(only_text(await collect(plugin.group_game_trigger(event))))
    event.set_mention("猜敌人 源石虫")
    show(only_text(await collect(plugin.group_game_trigger(event))))
    if OPERATOR_REGISTRY.current_game(session_key) is None:
        raise AssertionError("敌人开局不应影响干员对局")
    if ENEMY_REGISTRY.current_game(session_key) is None:
        raise AssertionError("干员对局存在时应能开敌人对局")

    print("\n--- 双对局下 @机器人 源石虫·α（应进入敌人池）---")
    event.set_mention("源石虫·α")
    text = only_text(await collect(plugin.group_game_trigger(event)))
    show(text)
    if "危险等级" not in text:
        raise AssertionError("双对局下应把敌人名分流到敌人池")

    print("\n--- 双对局下 @机器人 能天使（应进入干员池）---")
    event.set_mention("能天使")
    text = only_text(await collect(plugin.group_game_trigger(event)))
    show(text)
    if "暴击" in text or "分支" not in text:
        raise AssertionError("双对局下应把干员名分流到干员池")

    print("\n--- 不猜了（应同时结束两个对局）---")
    event.set_plain("不猜了")
    text = only_text(await collect(plugin.group_game_trigger(event)))
    show(text)
    if OPERATOR_REGISTRY.current_game(session_key) is not None:
        raise AssertionError("不猜了应结束干员对局")
    if ENEMY_REGISTRY.current_game(session_key) is not None:
        raise AssertionError("不猜了应结束敌人对局")

    print("\n--- 难度设置与查询 ---")
    for command in ("/干员池稀有度 6", "/猜测次数 -1", "/本群难度", "/重置难度"):
        event.set_plain(command)
        print(f"> {command}")
        show(only_text(await collect(plugin.group_game_trigger(event))))

    print("\n--- 猜干员 阿米娅（应用本群难度）---")
    event.set_mention("猜干员 阿米娅")
    show(only_text(await collect(plugin.group_game_trigger(event))))
    game = OPERATOR_REGISTRY.current_game(session_key)
    if game is None or game.max_attempts != 8:
        raise AssertionError("重置后应回到默认猜测次数")
    answer = plugin.operator_pool.by_id[game.answer_id]
    if answer.rarity < 1:
raise AssertionError("干员池稀有度异常")

    event.set_plain("不猜了")
    await collect(plugin.group_game_trigger(event))

    print("\n冒烟测试通过")


asyncio.run(main())
