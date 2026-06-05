from dataclasses import dataclass, field
from functools import cache

from pywikibot import Page
from pywikibot.pagegenerators import PreloadingGenerator

from utils.utils import load_db, load_text, resolve_text_markup
from utils.wiki_utils import save_json_page, s

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
    english_name: str = ""
    rarity: str = ""
    gender: str = ""
    affiliation: str = ""
    class_: str = field(default="")
    attribute: str = ""
    playable: bool = field(default=False)

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

    text = load_text("char_base")
    for entry in load_db("char_base@char_base"):
        char_id = int(entry["id"])
        if char_id not in result:
            continue
        char = result[char_id]
        char.english_name = text.get(f"english_name@{char_id}", "")
        char.rarity = entry.get("rarity", "").removeprefix("RARITY_")
        char.gender = entry.get("gender_type", "").removeprefix("GENDER_").title()
        char.affiliation = entry.get("link_faction_id", "")
        char.playable = entry.get("char_use_playable") == "YES"

    for entry in load_db("char_base@char_combatant"):
        char_id = int(entry["id"])
        if char_id not in result:
            continue
        char = result[char_id]
        char.class_ = entry.get("link_base_class_define_id", "").title()
        char.attribute = entry.get("link_ego_type_id", "").title()

    return result


def combatant_pages(page_suffix: str = "") -> list[Page]:
    pages = [
        Page(s, f"{char.name}{page_suffix}")
        for char in parse_characters().values()
        if char.playable
    ]
    return list(PreloadingGenerator(pages))


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
            k: resolve_text_markup(entry[k]) for k in INFO_FIELDS if k in entry
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
