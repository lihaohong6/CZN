import json
import re
from dataclasses import dataclass
from collections import defaultdict
from functools import cache

from utils.utils import load_text
from utils.utils import db_root, load_db, resolve_text_markup


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


def parse_bracket_list(s: str) -> list[str]:
    s = s.strip()
    if not s or s == "[]":
        return []
    inner = s.strip("[]")
    if not inner:
        return []
    return [item.strip() for item in inner.split(",") if item.strip()]


def maybe_int(value):
    try:
        return int(value)
    except TypeError:
        return value
    except ValueError:
        return value


def clean_skill_text(text: str) -> str:
    text = re.sub(r"\$([^$]*?)(?:#\d+)?\$", r"\1", text)
    text = re.sub(r"</>", "", text)
    return re.sub(r"</?(?!br\b)[^>]+>", "", text, flags=re.IGNORECASE)


def resolve_placeholders(
    text: str, skill_eff_ids: list[str], eff_map: dict[str, dict]
) -> str:
    def get_eff_value(idx: int, key: str, fallback: str) -> str:
        if idx < len(skill_eff_ids):
            eff = eff_map.get(skill_eff_ids[idx])
            if eff:
                return eff.get(key, fallback)
        return fallback

    def replacer(match):
        ph = match.group(1)
        m = re.match(
            r"result_(?:coeff_)?(?:pct_off_)?ev_(\d+)$|"
            r"result_coeff_pct_off_ev_(\d+)$|"
            r"result_damage(?:_pct_off)?_(\d+)$",
            ph,
        )
        if m:
            idx = int(next(group for group in m.groups() if group is not None))
            return get_eff_value(idx, "eff_value", match.group(0))
        m = re.match(r"result_ecv_(\d+)$", ph)
        if m:
            return get_eff_value(int(m.group(1)), "eff_count_value", match.group(0))
        return match.group(0)

    return re.sub(r"#([a-zA-Z_]\w*)#", replacer, text)


@cache
def load_partner_base_map() -> dict[int, dict]:
    result = {}
    for entry in load_db("partner_base@char_partner"):
        try:
            partner_id = int(entry["id"])
        except KeyError:
            continue
        except TypeError:
            continue
        except ValueError:
            continue
        result[partner_id] = entry
    return result


@cache
def load_partner_card_map() -> dict[str, dict]:
    result = {}
    raw_entries = json.loads(
        (db_root / "card(partner)@card.json").read_text(encoding="utf-8")
    )
    raw_by_id = {entry.get("id", ""): entry for entry in raw_entries}
    for entry in load_db("card(partner)@card"):
        card_id = entry.get("id", "")
        if card_id and card_id != "none":
            entry["raw_card_category"] = raw_by_id.get(card_id, {}).get(
                "card_category", entry.get("card_category", "")
            )
            result[card_id] = entry
    return result


@cache
def load_partner_card_skill_eff_map() -> dict[str, dict]:
    result = {}
    for entry in load_db("card(partner)@skill_eff"):
        eff_id = entry.get("id", "")
        if eff_id and eff_id != "none":
            result[eff_id] = entry
    return result


def _partner_passive_db_names(suffix: str) -> list[str]:
    return sorted(
        f.stem
        for f in db_root.iterdir()
        if f.name.startswith("partner_passive") and f.name.endswith(f"@{suffix}.json")
    )


@cache
def load_partner_passive_groups() -> dict[str, list[dict]]:
    result = defaultdict(dict)
    for db_name in _partner_passive_db_names("partner_passive"):
        for entry in load_db(db_name):
            group = entry.get("group", "")
            passive_id = entry.get("id", "")
            if group and passive_id and passive_id != "none":
                result[group][passive_id] = entry
    return {group: list(entries.values()) for group, entries in result.items()}


@cache
def load_partner_passive_cs_map() -> dict[str, dict]:
    result = {}
    for db_name in _partner_passive_db_names("cs"):
        for entry in load_db(db_name):
            cs_id = entry.get("id", "")
            if cs_id and cs_id != "none":
                result[cs_id] = entry
    return result


@cache
def load_partner_passive_skill_eff_map() -> dict[str, dict]:
    result = {}
    for db_name in _partner_passive_db_names("skill_eff"):
        for entry in load_db(db_name):
            eff_id = entry.get("id", "")
            if eff_id and eff_id != "none":
                result[eff_id] = entry
    return result


def parse_partner_ego_skill(base_entry: dict) -> dict | None:
    card_id = base_entry.get("link_card_id", "")
    card = load_partner_card_map().get(card_id)
    if not card:
        return None

    skill_eff_ids = parse_bracket_list(card.get("link_skill_eff_id", "[]"))
    desc = clean_skill_text(
        resolve_placeholders(
            card.get("desc", ""), skill_eff_ids, load_partner_card_skill_eff_map()
        )
    )

    return {
        "id": card["id"],
        "name": clean_skill_text(card.get("name", "")),
        "cost": maybe_int(card.get("cost", "")),
        "category": card.get("raw_card_category", card.get("card_category", "")),
        "desc": desc,
    }


def _passive_skill_eff_ids(passive_entry: dict) -> list[str]:
    result = parse_bracket_list(passive_entry.get("link_skill_eff_id", "[]"))
    cs_map = load_partner_passive_cs_map()
    for cs_id in parse_bracket_list(passive_entry.get("link_cs_id", "[]")):
        cs = cs_map.get(cs_id)
        if cs:
            result.extend(parse_bracket_list(cs.get("link_skill_eff_id", "[]")))
    return result


def _passive_sort_value(value):
    if isinstance(value, int):
        return (0, value)
    return (1, str(value))


def parse_partner_passive_skills(base_entry: dict) -> list[dict]:
    group = base_entry.get("link_partner_passive_group", "")
    passives = []
    for entry in load_partner_passive_groups().get(group, []):
        skill_eff_ids = _passive_skill_eff_ids(entry)
        desc = entry.get("outgame_description") or entry.get("description", "")
        desc = clean_skill_text(
            resolve_placeholders(
                desc, skill_eff_ids, load_partner_passive_skill_eff_map()
            )
        )
        passives.append(
            {
                "id": entry["id"],
                "class": maybe_int(entry.get("class", "")),
                "level": maybe_int(entry.get("level", "")),
                "name": clean_skill_text(entry.get("name", "")),
                "desc": desc,
            }
        )

    return sorted(
        passives,
        key=lambda passive: (
            _passive_sort_value(passive["class"]),
            _passive_sort_value(passive["level"]),
            passive["id"],
        ),
    )


@cache
def parse_partners() -> dict[int, Partner]:
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
        base_entry = load_partner_base_map().get(char_id)
        if base_entry:
            ego_skill = parse_partner_ego_skill(base_entry)
            if ego_skill:
                result[char_id]["ego_skill"] = ego_skill
            result[char_id]["passive_skills"] = parse_partner_passive_skills(base_entry)
    return result


def save_partner_info():
    from utils.wiki_utils import save_json_page

    info_data = parse_partner_info()
    obj = {info["name"]: info for info in info_data.values()}
    save_json_page("Module:PartnerInfo/data.json", obj, summary="update partner info")


def main():
    save_partner_info()


if __name__ == "__main__":
    main()
