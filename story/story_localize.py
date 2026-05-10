import re
from functools import cache

from utils import load_text


PROTAGONIST_MARKERS = {
    "{주인공}",
    "{주인공)",
    "{{주인공}}",
    "({주인공})",
    "(주인공)",
    "주인공",
}

NARRATION_MARKERS = {"(나레이션)", "(3인칭)", "나레이션"}

NAME_OVERRIDES: dict[str, str] = {
    "3인칭": "3rd Person",
    "나레이션": "Narration",
    "나르쟈 신규": "Narja",
    "남자의 환영": "Male Phantom",
    "여자의 환영": "Female Phantom",
    "어린 티아나": "Young Tiana",
    "어린 티페라": "Young Tiphera",
    "폐기된 레플리카": "Scrapped Replica",
    "레반의 수하": "Revan's Subordinate",
    "십자회 오퍼레이터": "Crusader Operator",
    "행인 1": "Pedestrian 1",
    "행인 2": "Pedestrian 2",
    "크레이그)": "Craig",
    "{주인공": "{주인공}",
}

_SUFFIX_RE = re.compile(r"^(.+?)[\s]*([A-Z\d])$")
_SUFFIX_NORM_RE = re.compile(r"^(.+?)[\s]*([a-z\d])$")


def clean_talker(talker: str) -> str:
    return talker.removesuffix("//연출용")


@cache
def build_name_map() -> dict[str, str]:
    actor = load_text("actor")
    return {
        key.removeprefix("name@"): val
        for key, val in actor.items()
        if key.startswith("name@")
    }


def localize_part(name: str, name_map: dict[str, str]) -> str:
    stripped = name.strip()
    if not stripped:
        return stripped
    if stripped in NAME_OVERRIDES:
        return NAME_OVERRIDES[stripped]
    if stripped in name_map:
        return name_map[stripped]
    norm = stripped[0].upper() + stripped[1:] if stripped else stripped
    if norm in name_map:
        return name_map[norm]
    if stripped.startswith("(") and stripped.endswith(")"):
        inner = stripped[1:-1]
        localized = localize_part(inner, name_map)
        if localized != inner:
            return f"({localized})"
    if stripped.startswith("(") and not stripped.endswith(")"):
        inner = stripped[1:]
        localized = localize_part(inner, name_map)
        if localized != inner:
            return f"({localized}"
    m = _SUFFIX_RE.match(stripped)
    if m:
        base, suffix_letter = m.group(1), m.group(2)
        for joiner in [" ", ""]:
            norm_key = f"{base}{joiner}{suffix_letter.lower()}"
            if norm_key in name_map:
                return name_map[norm_key]
        if base in name_map:
            return f"{name_map[base]} {suffix_letter}"
    m2 = _SUFFIX_NORM_RE.match(stripped)
    if m2:
        base, suffix_letter = m2.group(1), m2.group(2)
        for joiner in [" ", ""]:
            norm_key = f"{base}{joiner}{suffix_letter}"
            if norm_key in name_map:
                return name_map[norm_key]
        if base in name_map:
            return f"{name_map[base]} {suffix_letter.upper()}"
    return stripped


def localize_name(talker: str) -> str:
    if not talker:
        return talker
    if talker in PROTAGONIST_MARKERS:
        return talker
    name_map = build_name_map()
    base = talker.split("//")[0]
    parts = base.split("|")
    return "|".join(localize_part(p, name_map) for p in parts)
