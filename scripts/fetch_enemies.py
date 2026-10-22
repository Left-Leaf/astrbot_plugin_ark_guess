"""从 PRTS 抓取并规范化敌人题库。

数据来源：
1. `敌人一览/数据` 页面（JSON 数组）：名称、危险等级、四维评级（耐久 / 攻击 /
   防御 / 法术抗性）、攻击方式、伤害类型、行动方式等。
2. 每个敌人页面的 `登场活动` 字段：用于「实装」维度（只展示活动名）。
   `debut_order` 由同一活动内最小 sortId 排序得到，作为时间先后提示。

输出字段：id / name / level / attack_type / damage_type / motion / endure /
attack / defence / resistance / enemy_race / debut / debut_order / sort_id / link
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

API_URL = "https://prts.wiki/api.php"
PAGE_TITLE = "敌人一览/数据"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "enemies.json"
USER_AGENT = "astrbot-plugin-ark-guess/1.1"

LEVEL_RANK = {"普通": 1, "精英": 2, "领袖": 3}
GRADE_RANK = {
    "E": 1,
    "D": 2,
    "C": 3,
    "B": 4,
    "B+": 5,
    "A": 6,
    "A+": 7,
    "S": 8,
    "S+": 9,
    "SS": 10,
}
GRADE_FIELDS = ("endure", "attack", "defence", "resistance")
UNKNOWN_DEBUT = "未知"
BATCH_SIZE = 50
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u2060"), None)


def _clean(value: object) -> str:
    text = str(value or "").translate(_ZERO_WIDTH)
    return re.sub(r"\s+", "", text)


def _api(params: dict[str, str]) -> dict:
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(
        API_URL,
        data=data,
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _fetch_page_content() -> tuple[list[dict[str, object]], str]:
    payload = _api(
        {
            "action": "query",
            "format": "json",
            "titles": PAGE_TITLE,
            "prop": "revisions",
            "rvslots": "main",
            "rvprop": "content|timestamp",
            "rvlimit": "1",
        }
    )
    page = next(iter(payload["query"]["pages"].values()))
    revision = page["revisions"][0]
    content = revision["slots"]["main"]["*"]
    return json.loads(content), revision["timestamp"]


def _fetch_debuts(names: list[str]) -> dict[str, str]:
    """批量读取敌人页面的 `登场活动` 字段。

    敌人与干员同名时，敌人数据实际位于「名称(敌方)」页面，因此两个标题
    都会查询，后续优先取「(敌方)」页面的结果。
    """
    titles: list[str] = []
    for name in names:
        titles.extend((name, f"{name}(敌方)"))
    titles = list(dict.fromkeys(titles))

    debuts: dict[str, str] = {}
    for start in range(0, len(titles), BATCH_SIZE):
        chunk = titles[start : start + BATCH_SIZE]
        payload: dict = {}
        for attempt in range(3):
            try:
                payload = _api(
                    {
                        "action": "query",
                        "format": "json",
                        "titles": "|".join(chunk),
                        "prop": "revisions",
                        "rvslots": "main",
                        "rvprop": "content",
                        "redirects": "1",
                    }
                )
                break
            except Exception:  # noqa: BLE001 - 网络抖动时重试
                if attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        query = payload.get("query", {})
        reverse = {
            str(entry.get("to")): str(entry.get("from"))
            for entry in [*query.get("redirects", []), *query.get("normalized", [])]
        }
        for page in query.get("pages", {}).values():
            revisions = page.get("revisions") or []
            if not revisions:
                continue
            title = str(page.get("title") or "")
            origin = reverse.get(title, title)
            text = revisions[0]["slots"]["main"]["*"]
            found = re.findall(r"\|登场活动=([^\n|}]+)", text)
            if found:
                debuts[origin] = _clean(found[0]) or UNKNOWN_DEBUT
        time.sleep(0.2)
    return debuts


def normalize(raw: dict[str, object], sort_id: int) -> dict[str, object] | None:
    name = _clean(raw.get("name"))
    level = _clean(raw.get("enemyLevel"))
    grades = {field: _clean(raw.get(field)).upper() for field in GRADE_FIELDS}

    if not name or level not in LEVEL_RANK:
        return None
    if any(grade not in GRADE_RANK for grade in grades.values()):
        return None

    enemy_index = _clean(raw.get("enemyIndex"))
    return {
        "id": f"enemy_{sort_id:04d}_{enemy_index}",
        "name": name,
        "level": level,
        "attack_type": _clean(raw.get("attackType")),
        "damage_type": _clean(raw.get("damageType")),
        "motion": _clean(raw.get("motion")),
        "endure": grades["endure"],
        "attack": grades["attack"],
        "defence": grades["defence"],
        "resistance": grades["resistance"],
        "enemy_race": _clean(raw.get("enemyRace")),
        "sort_id": sort_id,
        "link": _clean(raw.get("enemyLink")) or name,
    }


def main() -> None:
    raw_records, timestamp = _fetch_page_content()
    enemies: list[dict[str, object]] = []
    seen_names: set[str] = set()
    seen_ids: set[str] = set()
    skipped = 0
    duplicates = 0

    for raw in raw_records:
        if not isinstance(raw, dict):
            continue
        name = _clean(raw.get("name"))
        if name in seen_names:
            duplicates += 1
            continue
        sort_id = int(raw.get("sortId") or len(enemies) + 1)
        record = normalize(raw, sort_id)
        if record is None:
            skipped += 1
            continue
        if record["id"] in seen_ids:
            record["id"] = f"{record['id']}_{sort_id}"
        seen_names.add(name)
        seen_ids.add(str(record["id"]))
        enemies.append(record)

    enemies.sort(key=lambda item: int(item["sort_id"]))
    debuts = _fetch_debuts([str(item["name"]) for item in enemies])

    for item in enemies:
        name = str(item["name"])
        item["debut"] = (
            debuts.get(f"{name}(敌方)") or debuts.get(name) or UNKNOWN_DEBUT
        )

    # 用同一活动的首个 sortId 作为活动先后顺序，供方向提示使用
    first_sort: dict[str, int] = {}
    for item in enemies:
        debut = str(item["debut"])
        sort_id = int(item["sort_id"])
        if debut not in first_sort or sort_id < first_sort[debut]:
            first_sort[debut] = sort_id
    order = {
        debut: index
        for index, (debut, _) in enumerate(
            sorted(first_sort.items(), key=lambda entry: entry[1])
        )
    }
    for item in enemies:
        item["debut_order"] = order[str(item["debut"])]

    payload = {
        "version": timestamp[:10].replace("-", ""),
        "source": f"https://prts.wiki/w/{urllib.parse.quote(PAGE_TITLE)}",
        "fetched_at": timestamp,
        "enemies": enemies,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    counts: dict[str, int] = {}
    for item in enemies:
        debut = str(item["debut"])
        counts[debut] = counts.get(debut, 0) + 1
    print(
        f"fetched={len(raw_records)} kept={len(enemies)} "
        f"duplicates={duplicates} skipped={skipped} "
        f"debuts={len(counts)} -> {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
