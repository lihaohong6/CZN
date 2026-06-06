import json
from functools import cache

from char_info.characters import parse_characters
from story.story_localize import clean_talker, localize_name
from utils.utils import load_db, resolve_text_markup
from utils.wiki_utils import save_json_page


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _split_choice_text(text: str) -> tuple[str, str]:
    label, sep, desc = text.partition("<br>")
    if not sep:
        return resolve_text_markup(label), ""
    return resolve_text_markup(label), resolve_text_markup(desc)


def _choice_side(text_type: str) -> str:
    if text_type.endswith("_L"):
        return "L"
    if text_type.endswith("_R"):
        return "R"
    return ""


def _line_type(text_type: str, talker: str) -> str:
    if text_type == "CAPTION":
        return "caption"
    if text_type:
        return text_type.lower()
    if talker:
        return "dialogue"
    return "narration"


def _script_line(node: dict) -> dict | None:
    text = node.get("text_en", "")
    if not text:
        return None

    talker = clean_talker(node.get("talker", ""))
    line = {
        "id": node.get("yuna_key", ""),
        "type": _line_type(node.get("text_type", ""), talker),
        "text": resolve_text_markup(text),
    }
    if talker:
        line["talker"] = localize_name(talker)
    return line


@cache
def _load_story_choice_archive_contents() -> dict[str, str]:
    return {
        entry["id"]: entry.get("link_counseling_archive_contents_id", "")
        for entry in load_db("counseling_story_choice@story_choice")
    }


@cache
def _load_counseling_stories() -> dict[str, dict]:
    story_choice_contents = _load_story_choice_archive_contents()
    result: dict[str, dict] = {}

    for story in load_db("story_counseling_260429@story"):
        story_id = story.get("id", "")
        if not story_id:
            continue
        nodes = json.loads(story.get("info", "[]"))
        first_choices: dict[str, dict] = {}
        followups: dict[str, list[dict]] = {}
        scripts: dict[str, list[dict]] = {}

        for node in nodes:
            story_choice_id = node.get("link_story_choice_id", "")
            choice_id = node.get("choice", "")
            if not choice_id:
                line = _script_line(node)
                if line is not None:
                    scripts.setdefault(node.get("use_choice", ""), []).append(line)
                continue
            if not story_choice_id:
                continue

            label, desc = _split_choice_text(node.get("text_en", ""))
            choice_data = {
                "id": choice_id,
                "story_choice_id": story_choice_id,
                "archive_content_id": story_choice_contents.get(story_choice_id, ""),
                "label": label,
                "text": desc,
                "side": _choice_side(node.get("text_type", "")),
                "score": _to_int(node.get("opt")),
            }

            parent_choice = node.get("use_choice", "")
            if parent_choice:
                followups.setdefault(parent_choice, []).append(choice_data)
            else:
                first_choices[choice_id] = choice_data

        choices = []
        for choice_id in sorted(first_choices, key=_to_int):
            choice = first_choices[choice_id]
            nested_followups = []
            for followup in sorted(
                followups.get(choice_id, []), key=lambda c: _to_int(c["id"])
            ):
                nested_followups.append(
                    followup
                    | {
                        "state": choice["score"] + followup["score"],
                        "script": scripts.get(followup["id"], []),
                    }
                )
            choices.append(
                choice
                | {
                    "script": scripts.get(choice_id, []),
                    "followups": nested_followups,
                }
            )

        if choices or scripts:
            result[story_id] = {
                "script": scripts.get("", []),
                "choices": choices,
            }

    return result


@cache
def _load_counseling_results() -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {}
    for entry in load_db("counseling_result@counseling_result"):
        char_id = _to_int(entry.get("link_char_base_id"))
        if not char_id:
            continue
        result.setdefault(char_id, []).append(
            {
                "id": entry.get("id", ""),
                "stability_point": _to_int(entry.get("stability_point")),
                "patient_condition": resolve_text_markup(
                    entry.get("patient_condition", "")
                ),
                "counseling_log": resolve_text_markup(entry.get("counseling_log", "")),
                "reward_friendship": _to_int(entry.get("reward_friendship")),
            }
        )

    for rows in result.values():
        rows.sort(key=lambda row: row["stability_point"])
    return result


@cache
def _load_counseling_endings() -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {}
    for entry in load_db("story_content_counseling@story_component_counseling"):
        component_id = entry.get("id", "")
        if "_end_" not in component_id:
            continue
        _, _, char_part = component_id.partition("story_compo_")
        char_id_str, _, ending_id = char_part.partition("_end_")
        char_id = _to_int(char_id_str)
        if not char_id:
            continue
        result.setdefault(char_id, []).append(
            {
                "id": ending_id,
                "story_id": entry.get("link_story_id", ""),
                "stability_min": _to_int(entry.get("stability_min")),
                "stability_max": _to_int(entry.get("stability_max")),
            }
        )

    for rows in result.values():
        rows.sort(key=lambda row: (row["stability_min"], row["stability_max"]))
    return result


@cache
def _load_diagnoses() -> dict[int, str]:
    result = {}
    for entry in load_db("combatant_info@combatant_info"):
        entry_id = entry.get("id", "")
        if not entry_id.endswith("_info"):
            continue
        char_id = _to_int(entry_id.removesuffix("_info"))
        if not char_id:
            continue
        result[char_id] = resolve_text_markup(entry.get("hospitalization_reason", ""))
    return result


@cache
def parse_counseling() -> dict[int, dict]:
    characters = parse_characters()
    playable_ids = {char_id for char_id, char in characters.items() if char.playable}
    diagnoses = _load_diagnoses()
    stories = _load_counseling_stories()
    results = _load_counseling_results()
    endings = _load_counseling_endings()

    data: dict[int, dict] = {}
    for entry in load_db("counseling_archive@counseling_archive"):
        char_id = _to_int(entry.get("id", "").split("_", 1)[0])
        if char_id not in playable_ids:
            continue

        story_id = entry.get("link_story_id", "")
        story = stories.get(story_id, {})
        session = {
            "id": entry.get("id", ""),
            "story_id": story_id,
            "title": resolve_text_markup(entry.get("title", "")),
            "desc": resolve_text_markup(entry.get("desc", "")),
            "script": story.get("script", []),
            "choices": story.get("choices", []),
        }

        char_data = data.setdefault(
            char_id,
            {
                "id": char_id,
                "diagnosis": diagnoses.get(char_id, ""),
                "sessions": [],
                "results": results.get(char_id, []),
                "endings": endings.get(char_id, []),
            },
        )
        char_data["sessions"].append(session)

    for char_data in data.values():
        char_data["sessions"].sort(
            key=lambda session: _to_int(session["id"].split("_", 1)[1])
        )

    return dict(sorted(data.items()))


def save_counseling():
    characters = parse_characters()
    counseling_data = parse_counseling()
    for char_id in sorted(counseling_data):
        char_name = characters[char_id].name
        save_json_page(
            f"Module:Counseling/{char_name}.json",
            counseling_data[char_id],
            summary=f"update {char_name} counseling data",
        )


def main():
    save_counseling()


if __name__ == "__main__":
    main()
