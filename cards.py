import re
from functools import cache

from characters import parse_characters
from utils import db_root, load_db, load_text, resolve_text_markup
from wiki_utils import save_json_page


@cache
def _find_db_names(suffix: str) -> list[str]:
    return sorted(
        f.stem
        for f in db_root.iterdir()
        if f.name.startswith("card(") and f.name.endswith(f"@{suffix}.json")
    )


def _card_db_names() -> list[str]:
    return _find_db_names("card")


def _skill_eff_db_names() -> list[str]:
    return _find_db_names("skill_eff")


SORT_MAP = {
    "SORT_START": "Start",
    "SORT_UNIQUE": "Unique",
    "SORT_POWER_STRIKE": "Power Strike",
    "SORT_EIDOLON": "Eidolon",
    "SORT_COLLAPSE": "Collapse",
    "SORT_COLLAPSE_SKILL": "Collapse Skill",
    "SORT_PUBLIC": "Public",
    "SORT_SUPPORT": "Support",
    "SORT_MONSTER_COMMON": "Monster",
    "SORT_MONSTER_RARE": "Monster",
    "SORT_MONSTER_UNIQUE": "Monster",
}

VARIANT_ORDER = {"srt": 0, "uni": 1, "eps": 2, "col": 3, "bhc": 4}


def parse_bracket_list(s: str) -> list[str]:
    s = s.strip()
    if not s or s == "[]":
        return []
    inner = s.strip("[]")
    if not inner:
        return []
    return [item.strip() for item in inner.split(",") if item.strip()]


@cache
def load_skill_eff_map() -> dict[str, dict]:
    result = {}
    for db_name in _skill_eff_db_names():
        try:
            entries = load_db(db_name)
        except FileNotFoundError:
            continue
        for entry in entries:
            eid = entry.get("id", "")
            if eid and eid != "none":
                result[eid] = entry
    return result


@cache
def load_all_cards() -> dict[str, dict]:
    result = {}
    for db_name in _card_db_names():
        try:
            entries = load_db(db_name)
        except FileNotFoundError:
            continue
        for entry in entries:
            cid = entry.get("id", "")
            if cid and cid != "none":
                result[cid] = entry
    return result


def resolve_placeholders(
    text: str, skill_eff_ids: list[str], eff_map: dict[str, dict]
) -> str:
    def replacer(match):
        ph = match.group(1)
        m = re.match(r"result_(?:coeff_)?ev_(\d+)$", ph)
        if m:
            idx = int(m.group(1))
            if idx < len(skill_eff_ids):
                eff_id = skill_eff_ids[idx]
                if eff_id in eff_map:
                    return eff_map[eff_id].get("eff_value", match.group(0))
        m = re.match(r"result_ecv_(\d+)$", ph)
        if m:
            idx = int(m.group(1))
            if idx < len(skill_eff_ids):
                eff_id = skill_eff_ids[idx]
                if eff_id in eff_map:
                    return eff_map[eff_id].get("eff_count_value", match.group(0))
        return match.group(0)

    return re.sub(r"#([a-zA-Z_]\w*)#", replacer, text)


@cache
def _discover_card_ids() -> dict[int, list[str]]:
    card_text = load_text("card")
    characters = parse_characters()
    char_ids = set(characters.keys())
    seen: dict[int, set[str]] = {}
    for key in card_text:
        if not key.startswith("name@"):
            continue
        card_id = key[len("name@") :]
        m = re.match(r"c_(\d+)_", card_id)
        if not m:
            continue
        char_id = int(m.group(1))
        if char_id not in char_ids:
            continue
        seen.setdefault(char_id, set()).add(card_id)
    cards_db = load_all_cards()
    for card_id in cards_db:
        m = re.match(r"c_(\d+)_", card_id)
        if not m:
            continue
        char_id = int(m.group(1))
        if char_id not in char_ids:
            continue
        seen.setdefault(char_id, set()).add(card_id)
    return {cid: sorted(ids) for cid, ids in sorted(seen.items())}


def get_char_id(card_id: str) -> int | None:
    m = re.match(r"c_(\d+)_", card_id)
    if m:
        return int(m.group(1))
    return None


def get_base_card_id(card_id: str) -> str:
    return re.sub(r"_(?:pot|rsp\d+|lbk|bhc)$", "", card_id)


VARIANT_RE = re.compile(
    r"c_\d+_(?:srt|uni|eps|cre|col\d*|lbk|bhc)\d*(?:_(?:pot|rsp\d+|lbk|bhc|mut\d+))?$"
)


def card_sort_key(card_id: str):
    m = re.match(
        r"c_\d+_(srt|uni|eps|col|bhc|cre|lbk)(\d*)(?:_(pot|rsp\d+|lbk|bhc|mut\d+))?$",
        card_id,
    )
    if m:
        variant = m.group(1)
        num_str = m.group(2)
        num = int(num_str) if num_str else 0
        sub = m.group(3) or ""
        sub_order = 0
        if sub == "pot":
            sub_order = 1
        elif sub.startswith("rsp"):
            rsp_num = int(sub[3:]) if len(sub) > 3 else 0
            sub_order = 10 + rsp_num
        elif sub == "lbk":
            sub_order = 50
        elif sub == "bhc":
            sub_order = 51
        elif sub.startswith("mut"):
            sub_order = 60 + (int(sub[3:]) if len(sub) > 3 else 0)
        variant_order = {**VARIANT_ORDER, "cre": 1.5, "lbk": 5}
        return (variant_order.get(variant, 99), num, sub_order)
    return (99, 0, 0)


@cache
def parse_cards() -> dict[int, list[dict]]:
    characters = parse_characters()
    cards_db = load_all_cards()
    eff_map = load_skill_eff_map()
    card_text = load_text("card")
    discovered = _discover_card_ids()

    result: dict[int, list[dict]] = {}

    for char_id, card_ids in discovered.items():
        for card_id in card_ids:
            entry = cards_db.get(card_id)

            name = ""
            if entry:
                name = entry.get("name", "")
            if not name or name == "none" or name.startswith("card@"):
                name = card_text.get(f"name@{card_id}", "")
                if not name:
                    base_id = get_base_card_id(card_id)
                    name = card_text.get(f"name@{base_id}", name)

            desc = ""
            if entry:
                desc = entry.get("desc", "")
            if not desc or desc == "none" or desc.startswith("card@"):
                desc = card_text.get(f"desc@{card_id}", "")

            desc_outgame = card_text.get(f"desc_outgame@{card_id}", "")

            skill_eff_ids = []
            if entry:
                raw_eff_ids = entry.get("link_skill_eff_id", "[]")
                if isinstance(raw_eff_ids, str):
                    skill_eff_ids = parse_bracket_list(raw_eff_ids)

            resolved_desc = (
                resolve_placeholders(desc, skill_eff_ids, eff_map) if desc else ""
            )
            resolved_desc = resolve_text_markup(resolved_desc)

            resolved_desc_outgame = ""
            if desc_outgame:
                resolved_desc_outgame = resolve_text_markup(
                    resolve_placeholders(desc_outgame, skill_eff_ids, eff_map)
                )

            card_data: dict = {"id": card_id, "name": name, "desc": resolved_desc}

            if entry:
                cost = entry.get("cost", "")
                try:
                    cost = int(cost)
                except ValueError, TypeError:
                    pass
                card_data["cost"] = cost
                card_data["rarity"] = entry.get("rarity", "")
                card_data["category"] = entry.get("card_category", "")
                sort_raw = entry.get("sort", "")
                card_data["sort"] = SORT_MAP.get(sort_raw, sort_raw)
                effects = []
                for eff_id in skill_eff_ids:
                    if eff_id in eff_map:
                        eff = eff_map[eff_id]
                        effects.append(
                            {
                                "id": eff_id,
                                "type": eff.get("eff", ""),
                                "value": eff.get("eff_value", ""),
                                "count_value": eff.get("eff_count_value", ""),
                            }
                        )
                card_data["effects"] = effects

            if resolved_desc_outgame:
                card_data["desc_outgame"] = resolved_desc_outgame

            result.setdefault(char_id, []).append(card_data)

    for char_id in result:
        result[char_id].sort(key=lambda c: card_sort_key(c["id"]))

    return result


def save_cards():
    characters = parse_characters()
    cards_data = parse_cards()
    obj = {}
    for char_id in sorted(cards_data):
        if char_id in characters:
            name = characters[char_id].name
            obj[name] = cards_data[char_id]

    save_json_page(
        "Module:Cards/data.json",
        obj,
        summary="update card data",
    )


def main():
    save_cards()


if __name__ == "__main__":
    main()
