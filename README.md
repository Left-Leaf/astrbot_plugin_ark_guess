# astrbot_plugin_ark_guess

AstrBot 的《明日方舟》猜干员插件。基于 PRTS 干员数据（434 名干员），每局独立 `game id`，支持多局并行、跨会话加入对局。

## 指令

| 指令 | 说明 |
| --- | --- |
| `/猜干员` | 开始新对局 |
| `/猜干员 <干员名 / 干员 id>` | 猜测；没有进行中的对局时会自动开新局 |
| `/对局状态` | 查看当前对局（最近 5 次猜测） |
| `/结束猜干员` | 结束并删除当前对局 |
| `/加入对局 <对局 id>` | 加入其他会话创建的对局（支持 id 后缀） |
| `/对局统计` | 查看本进程内对局数量 |
| `/方舟帮助` | 指令说明 |

## 判定规则

每局按五个维度给出提示：

- 稀有度、实装年份：`🟩` 正确；`⬜⬆️` 答案更高 / 更晚；`⬜⬇️` 答案更低 / 更早
- 职业（分支）：`🟩` 职业与分支均一致；`🟨` 同职业不同分支；`⬜` 职业不同
- 阵营：所属势力有交集 → `🟩`；仅隐藏势力交叉命中 → `🟨`；否则 `⬜`
- 种族：相等 → `🟩`，否则 `⬜`

阵营数据来自 PRTS `chara_data.ingameFaction`（所属势力）与 `hiddenFaction`（隐藏势力），多个势力以逗号分隔。

## 配置

`_conf_schema.json` 支持：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `max_attempts` | 8 | 每局最大猜测次数 |
| `game_ttl_minutes` | 120 | 空闲对局回收时间（分钟），`<=0` 不回收 |
| `cleanup_interval_seconds` | 600 | 过期检查间隔（秒） |
| `group_shared` | true | 群聊整群共享一局；关闭后每人一局 |
| `min_rarity` | 1 | 出题池最低稀有度 |
| `render_mode` | text | `text` 文本，`image` 使用 AstrBot 文转图 |

## 并发与实例隔离

- 每个会话（`event.unified_msg_origin`）绑定一个独立对局；
- 每局拥有 `game_<random>` 唯一 id，答案、猜测历史、状态只保存在该实例内；
- 同一对局的提交由 `asyncio.Lock` 串行化，并发猜测不会丢失或覆盖；
- 不同对局使用不同锁，可同时推进；
- 对局默认保存在进程内存中，插件重载 / AstrBot 重启会丢失；空闲对局按 TTL 自动回收。

## 数据更新

题库由 `E:\project\Arknights` 的 Node 数据管线生成：

```powershell
cd E:\project\Arknights
npm run fetch
Copy-Item .\data\operators.json E:\project\AstrBot\data\plugins\astrbot_plugin_ark_guess\data\operators.json -Force
```

然后在 AstrBot WebUI 的插件页重载插件。`operators.json` 中包含 `version`，插件启动日志会打印当前题库版本与干员数量。

## 开发与测试

纯逻辑测试（不依赖 AstrBot）：

```powershell
cd E:\project\AstrBot\data\plugins\astrbot_plugin_ark_guess
E:\project\AstrBot\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

AstrBot 环境冒烟测试：

```powershell
E:\project\AstrBot\.venv\Scripts\python.exe tests\smoke_main.py
```
