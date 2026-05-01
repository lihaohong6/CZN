from dataclasses import dataclass, field
from functools import cache

from characters import parse_characters
from utils import load_text
from wiki_utils import save_json_page


@dataclass
class EgoManifestationLevel:
    level: int
    title: str
    sub_title: str
    desc: str


@dataclass
class EgoManifestation:
    char_id: int
    levels: list[EgoManifestationLevel] = field(default_factory=list)


@cache
def parse_ego_manifestations() -> dict[int, EgoManifestation]:
    data = load_text("combatant_limit_break")

    titles = {}
    sub_titles = {}
    for key, val in data.items():
        if key.startswith("title@limit_"):
            titles[int(key.removeprefix("title@limit_"))] = val
        elif key.startswith("sub_title@limit_") and not key.startswith("sub_title@limit_ref"):
            level_str = key.removeprefix("sub_title@limit_")
            if level_str.isdigit():
                sub_titles[int(level_str)] = val

    result: dict[int, EgoManifestation] = {}
    for key, desc in data.items():
        if not key.startswith("desc@limit_"):
            continue
        char_id_str, _, level_str = key.removeprefix("desc@limit_").rpartition("_")
        char_id, level = int(char_id_str), int(level_str)
        result.setdefault(char_id, EgoManifestation(char_id=char_id))
        result[char_id].levels.append(EgoManifestationLevel(
            level=level,
            title=titles.get(level, ""),
            sub_title=sub_titles.get(level, ""),
            desc=desc,
        ))

    for ego in result.values():
        ego.levels.sort(key=lambda lvl: lvl.level)

    return result


def save_ego_manifestations():
    characters = parse_characters()
    ego_data = parse_ego_manifestations()
    obj = {}
    for char_id, ego in ego_data.items():
        if char_id not in characters:
            continue
        obj[characters[char_id].name] = ego.levels
    save_json_page("Module:EgoManifestation/data.json", obj, summary="update ego manifestations")
