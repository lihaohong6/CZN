import json
import re
from functools import cache
from pathlib import Path
from typing import Any

from story.story_localize import clean_talker, PROTAGONIST_MARKERS, NARRATION_MARKERS
from story.story_types import (
    StoryStep,
    StoryScene,
    StoryElement,
    StoryElementType,
    StoryEpisode,
    SKIP_TEXT_TYPES,
    CHOICE_TEXT_TYPES,
    NAMED_TEXT_TYPE_MAP,
    GENERIC_DIALOGUE_TYPES,
    add_if_present,
)
from upload_utils import UploadRequest
from utils import assets_root, db_root, load_db


_RES_TYPE_EXT: dict[str, str] = {
    "BG": ".png",
    "SPINE_BG": ".png",
    "ILLUST": ".png",
    "FRAME": ".png",
    "CFX_BG": ".png",
    "WEBP": ".webp",
}


def parse_story_step(raw: dict) -> StoryStep:
    slots = {}
    for i in range(1, 6):
        v = raw.get(f"slot_{i}", "")
        if v:
            slots[f"slot_{i}"] = v
    return StoryStep(
        yuna_key=raw.get("yuna_key", ""),
        text_type=raw.get("text_type", ""),
        talker=clean_talker(raw.get("talker", "")),
        name=raw.get("name", ""),
        text_en=raw.get("text_en", ""),
        face=raw.get("face", ""),
        size=raw.get("size", ""),
        background=raw.get("link_list_story_resource_id", ""),
        res_action_type=raw.get("res_action_type", ""),
        slots=slots,
        use_choice=raw.get("use_choice", ""),
        choice=raw.get("choice", ""),
        link_story_choice_id=raw.get("link_story_choice_id", ""),
        opt=raw.get("opt", ""),
    )


@cache
def _load_story_resources() -> dict[str, dict[str, str]]:
    resources: dict[str, dict[str, str]] = {}
    for entry in load_db("list_story_resource@list_story_resource"):
        rid = entry.get("id", "")
        if rid:
            resources[rid] = {
                "filepath": entry.get("filepath", ""),
                "res_type": entry.get("res_type", ""),
            }
    return resources


def step_to_elements(
    step: StoryStep, resources: dict[str, dict[str, str]]
) -> list[StoryElement]:
    elements: list[StoryElement] = []
    tt = step.text_type

    if step.background and step.res_action_type not in ("OFF", "REP_ONLY_OFF"):
        res = resources.get(step.background, {})
        filepath = res.get("filepath", "")
        res_type = res.get("res_type", "")
        ext = _RES_TYPE_EXT.get(res_type)
        bg_args: dict[str, Any] = {
            "name": step.background,
            "path": filepath,
            "res_type": res_type,
        }
        add_if_present(bg_args, "action", step.res_action_type)
        candidate = assets_root / f"{filepath}{ext}"
        if not candidate.exists():
            pass
            # print(f"Warning: {candidate} not found")
        else:
            bg_args["source"] = candidate
            elements.append(
                StoryElement(type=StoryElementType.BACKGROUND, args=bg_args)
            )

    if tt in SKIP_TEXT_TYPES:
        return elements

    if tt in CHOICE_TEXT_TYPES:
        choice_args: dict[str, Any] = {"variant": tt}
        add_if_present(choice_args, "talker", step.talker)
        add_if_present(choice_args, "text", step.text_en)
        add_if_present(choice_args, "choice", step.choice)
        add_if_present(choice_args, "link_story_choice_id", step.link_story_choice_id)
        add_if_present(choice_args, "opt", step.opt)
        add_if_present(choice_args, "slots", step.slots)
        add_if_present(choice_args, "yuna_key", step.yuna_key)
        elements.append(StoryElement(type=StoryElementType.CHOICE, args=choice_args))
        return elements

    if tt in NAMED_TEXT_TYPE_MAP:
        elem_type = NAMED_TEXT_TYPE_MAP[tt]
        text_args: dict[str, Any] = {}
        if elem_type == StoryElementType.COUNSELING:
            add_if_present(text_args, "slots", step.slots)
            add_if_present(text_args, "yuna_key", step.yuna_key)
        elif elem_type == StoryElementType.MONOLOGUE:
            add_if_present(text_args, "talker", step.talker)
            add_if_present(text_args, "text", step.text_en)
            add_if_present(text_args, "face", step.face)
            add_if_present(text_args, "size", step.size)
            add_if_present(text_args, "slots", step.slots)
            add_if_present(text_args, "yuna_key", step.yuna_key)
        else:
            add_if_present(text_args, "text", step.text_en)
            add_if_present(text_args, "yuna_key", step.yuna_key)
        elements.append(StoryElement(type=elem_type, args=text_args))
        return elements

    if tt in GENERIC_DIALOGUE_TYPES:
        if not step.text_en and not step.talker:
            return elements

        if step.talker in PROTAGONIST_MARKERS:
            protag_args: dict[str, Any] = {}
            add_if_present(protag_args, "text", step.text_en)
            add_if_present(protag_args, "face", step.face)
            add_if_present(protag_args, "size", step.size)
            add_if_present(protag_args, "slots", step.slots)
            add_if_present(protag_args, "yuna_key", step.yuna_key)
            elements.append(
                StoryElement(type=StoryElementType.PROTAGONIST, args=protag_args)
            )
        elif step.talker in NARRATION_MARKERS:
            narr_args: dict[str, Any] = {}
            add_if_present(narr_args, "text", step.text_en)
            add_if_present(narr_args, "yuna_key", step.yuna_key)
            elements.append(
                StoryElement(type=StoryElementType.NARRATION, args=narr_args)
            )
        elif step.talker:
            dial_args: dict[str, Any] = {}
            add_if_present(dial_args, "talker", step.talker)
            add_if_present(dial_args, "text", step.text_en)
            add_if_present(dial_args, "face", step.face)
            add_if_present(dial_args, "size", step.size)
            add_if_present(dial_args, "slots", step.slots)
            add_if_present(dial_args, "yuna_key", step.yuna_key)
            elements.append(
                StoryElement(type=StoryElementType.DIALOGUE, args=dial_args)
            )
        else:
            narr_args: dict[str, Any] = {}
            add_if_present(narr_args, "text", step.text_en)
            add_if_present(narr_args, "yuna_key", step.yuna_key)
            elements.append(
                StoryElement(type=StoryElementType.NARRATION, args=narr_args)
            )
        return elements

    return elements


def parse_story_scene(entry: dict, resources: dict[str, dict[str, str]]) -> StoryScene:
    scene_id = entry["id"]
    raw_steps = json.loads(entry["info"])
    title = ""
    location = ""
    elements: list[StoryElement] = []

    for raw in raw_steps:
        step = parse_story_step(raw)
        if step.text_type == "CHAPTER" and not title:
            title = step.text_en
        if step.text_type == "LOCATION" and not location:
            location = step.text_en
        elements.extend(step_to_elements(step, resources))

    deduped: list[StoryElement] = []
    last_bg_name: str | None = None
    for elem in elements:
        if elem.type == StoryElementType.BACKGROUND:
            name = elem.args.get("name", "")
            if name == last_bg_name:
                continue
            last_bg_name = name
        else:
            last_bg_name = None
        deduped.append(elem)

    seen_bg: set[str] = set()
    uploads: list[UploadRequest] = []
    for elem in deduped:
        if elem.type != StoryElementType.BACKGROUND:
            continue
        name = elem.args.get("name", "")
        if name in seen_bg:
            continue
        seen_bg.add(name)
        source: Path | None = elem.args.get("source")
        if source is None:
            continue
        uploads.append(UploadRequest(
            source=source,
            target=source.name,
            text="",
            summary="upload story background",
        ))

    return StoryScene(
        scene_id=scene_id, title=title, location=location,
        elements=deduped, uploads=uploads,
    )


@cache
def _find_story_db_names() -> list[str]:
    return sorted(
        f.stem
        for f in db_root.iterdir()
        if f.name.startswith("story_")
        and f.name.endswith("@story.json")
        and not f.name.startswith("story_dev@")
    )


@cache
def get_story_scenes() -> dict[str, StoryScene]:
    resources = _load_story_resources()
    result: dict[str, StoryScene] = {}
    for db_name in _find_story_db_names():
        raw = json.loads((db_root / f"{db_name}.json").read_text(encoding="utf-8"))
        for entry in raw:
            scene = parse_story_scene(entry, resources)
            result[scene.scene_id] = scene
    return result


def _natural_sort_key(s: str) -> list:
    parts = re.split(r"(\d+)", s)
    return [int(p) if p.isdigit() else p for p in parts]


def _extract_episode_name(title: str) -> str:
    title = title.strip()
    for sep in ("<br><br>", " - "):
        if sep in title:
            return title.split(sep, 1)[1].strip()
    return title


def _extract_display_title(title: str) -> str:
    title = title.strip()
    if "<br><br>" in title:
        prefix, name = title.split("<br><br>", 1)
        if prefix == "PROLOGUE":
            return f"Prologue: {name}"
        return f"{prefix}: {name}"
    if " - " in title:
        prefix, name = title.split(" - ", 1)
        return f"{prefix}: {name}"
    return title


_SCENE_ID_KEY_RE = re.compile(r"^main_part(\d+)_(ch\w+?)(?:_\w+)?$")


@cache
def get_main_episodes() -> list[StoryEpisode]:
    scenes = get_story_scenes()

    groups: dict[str, dict] = {}
    for sid in sorted(scenes, key=lambda s: _natural_sort_key(s)):
        if not sid.startswith("main_"):
            continue
        m = _SCENE_ID_KEY_RE.match(sid)
        if not m:
            continue
        part = int(m.group(1))
        ep_key = m.group(2)

        group_id = f"part{part}_{ep_key}"
        if group_id not in groups:
            groups[group_id] = {"part": part, "ep_key": ep_key, "scene_ids": []}

        scene = scenes[sid]
        if scene.title and "title" not in groups[group_id]:
            groups[group_id]["title"] = scene.title
        groups[group_id]["scene_ids"].append(sid)

    sorted_keys = sorted(groups.keys())

    merge_targets: dict[str, str | None] = {}
    last_titled: str | None = None
    for gk in sorted_keys:
        if "title" in groups[gk]:
            last_titled = gk
        elif last_titled is not None:
            same_part = groups[gk]["part"] == groups[last_titled]["part"]
            if same_part:
                merge_targets[gk] = last_titled
                continue
        merge_targets[gk] = None

    merged: dict[str, dict] = {}
    for gk in sorted_keys:
        target = merge_targets.get(gk)
        if target is not None:
            merged[target]["scene_ids"].extend(groups[gk]["scene_ids"])
        else:
            merged[gk] = groups[gk]

    name_counts: dict[str, int] = {}
    for gk in sorted(merged.keys()):
        g = merged[gk]
        name = _extract_episode_name(g.get("title", gk))
        name_counts[name] = name_counts.get(name, 0) + 1

    episodes: list[StoryEpisode] = []
    for gk in sorted(merged.keys(), key=lambda k: _natural_sort_key(k)):
        g = merged[gk]
        raw_title = g.get("title", "")
        name = _extract_episode_name(raw_title) if raw_title else gk
        display = _extract_display_title(raw_title) if raw_title else gk

        if name_counts.get(name, 0) > 1:
            name = f"{name} (Part {g['part']})"
            if "Episode" in display or "Prologue" in display or "Epilogue" in display:
                display = f"{display} (Part {g['part']})"

        episodes.append(
            StoryEpisode(
                part=g["part"],
                episode_key=g["ep_key"],
                name=name,
                display_title=display,
                scene_ids=g["scene_ids"],
            )
        )

    return episodes
