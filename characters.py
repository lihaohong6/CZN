from dataclasses import dataclass
from functools import cache

from utils import load_db, load_text
from wiki_utils import save_json_page

INFO_FIELDS = {
    "background_text",
    "specialty",
    "birth_day",
    "birth_month",
    "hospitalization_reason",
    "race_type",
    "custom_category",
    "custom_text",
    "cv_en",
    "cv_ja",
    "cv_ko",
    "cv_zhs",
}


@dataclass
class Character:
    id: int
    name: str

    def __hash__(self) -> int:
        return hash(self.id)


@cache
def parse_characters() -> dict[int, Character]:
    result = {}
    for key, name in load_text("char_base").items():
        prefix, _, id_str = key.partition("@")
        if prefix == "name":
            char_id = int(id_str)
            result[char_id] = Character(id=char_id, name=name)
    return result


@cache
def parse_character_info() -> dict[int, dict]:
    characters = parse_characters()
    db_data = load_db("combatant_info@combatant_info")
    result = {}
    for entry in db_data:
        char_id = int(entry["id"].removesuffix("_info"))
        if char_id not in characters:
            continue
        result[char_id] = {"id": char_id, "name": characters[char_id].name} | {
            k: entry[k] for k in INFO_FIELDS if k in entry
        }
    return result


def save_character_info():
    info_data = parse_character_info()
    obj = {info["name"]: info for info in info_data.values()}
    save_json_page(
        "Module:CharacterInfo/data.json", obj, summary="update character info"
    )


def main():
    save_character_info()


if __name__ == "__main__":
    main()
