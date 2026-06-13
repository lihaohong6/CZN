import json
from dataclasses import dataclass
from functools import cache

from utils.utils import load_text
from utils.utils import load_db, resolve_text_markup
from utils.wiki_utils import save_json_page

@dataclass
class Partner:
    id: int
    name: str

INFO_FIELDS = {
    "background_text",
    "specialty",
    "birth_day",
    "birth_month",
    "race_type",
    "specialty",
    "passive",
    "ego_skill",
    "cv_en",
    "cv_ja",
    "cv_ko",
    "cv_zhs",
}

@cache
def parse_partners() -> dict[str, Partner]:
    result = {}
    for key, name in load_text("char_base").items():
        prefix, _, id_str = key.partition("@")
        if prefix == "name":
            partner_id = int(id_str)
            result[partner_id] = Partner(id=partner_id, name=name)

    # partner_text = load_text("char_base")
    # for key, name in partner_text.items():
    #     prefix, _, id_str = key.partition("@")
    #     if prefix == "name":
    #         if id_str.isnumeric():
    #             partner_id = int(id_str).removesuffix("_info")
    #             desc = partner_text.get(f'background_text@{id_str}').removesuffix("_info")
    #             result[name] = Partner(id=partner_id, name=name, desc=desc)
                
    return result

@cache
def parse_partner_info() -> dict[int, dict]:
    partners = parse_partners()
    db_data = load_db("supporter_info@supporter_info")
    result = {}
    for entry in db_data:
        char_id = int(entry["id"].removesuffix("_info"))
        if char_id not in partners:
            continue
        result[char_id] = {"id": char_id, "name": partners[char_id].name} | {
            k: resolve_text_markup(entry[k]) for k in INFO_FIELDS if k in entry
        }
    return result

def save_partner_info():
    info_data = parse_partner_info()
    obj = {info["name"]: info for info in info_data.values()}
    save_json_page(
        "Module:PartnerInfo/data.json", obj, summary="update partner info"
    )

def main():
    save_partner_info()

if __name__ == "__main__":
    main()
