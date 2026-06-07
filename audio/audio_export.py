from __future__ import annotations

import argparse
import dataclasses
import json
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

from utils.utils import assets_root, load_db, load_text, sound_root


DEFAULT_EXPORT_ROOT = Path("exports/voice_lines/combatants")
DEFAULT_LANGS = ("ja", "ko")
TRANSLATION_LANGS = ("en",)
TITLE_LANGS = ("en",)


@dataclass
class VoiceLine:
    combatant_id: int
    character_name: str
    line_key: str
    title: dict[str, str] = field(default_factory=dict)
    title_source: str = ""
    bank_file: dict[str, str] = field(default_factory=dict)
    stream_index: dict[str, int] = field(default_factory=dict)
    wav_path: dict[str, str] = field(default_factory=dict)
    transcript: dict[str, str] = field(default_factory=dict)
    translation: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VoiceLine":
        lang = str(data["lang"]) if "lang" in data else ""
        return cls(
            combatant_id=int(data["combatant_id"]),
            character_name=str(data["character_name"]),
            line_key=str(data["line_key"]),
            title=coerce_lang_dict(data.get("title", {}), "", str),
            title_source=str(data.get("title_source", "")),
            bank_file=coerce_lang_dict(data.get("bank_file", {}), lang, str),
            stream_index=coerce_lang_dict(data.get("stream_index", {}), lang, int),
            wav_path=coerce_lang_dict(data.get("wav_path", {}), lang, str),
            transcript=coerce_lang_dict(data.get("transcript", {}), lang, str),
            translation=coerce_lang_dict(data.get("translation", {}), "", str),
        )

    def merge(self, other: "VoiceLine") -> None:
        if (
            self.combatant_id != other.combatant_id
            or self.character_name != other.character_name
            or self.line_key != other.line_key
        ):
            raise ValueError(f"Cannot merge different voice lines: {self} vs {other}")

        self.bank_file.update(other.bank_file)
        self.stream_index.update(other.stream_index)
        self.wav_path.update(other.wav_path)
        self.transcript.update(other.transcript)
        self.translation.update(other.translation)
        self.title.update(other.title)
        self.title_source = self.title_source or other.title_source


@dataclass
class VoiceLineExport:
    generated_at: str
    sound_root: str
    lines: list[VoiceLine] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VoiceLineExport":
        return cls(
            generated_at=str(data["generated_at"]),
            sound_root=str(data["sound_root"]),
            lines=[VoiceLine.from_dict(line) for line in data.get("lines", [])],
            summary=dict(data.get("summary", {})),
        )


def save_voice_lines_json(path: Path, export: VoiceLineExport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(export.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_voice_lines_json(path: Path = DEFAULT_EXPORT_ROOT / "voice_lines.json") -> VoiceLineExport:
    return VoiceLineExport.from_dict(json.loads(path.read_text(encoding="utf-8")))


def export_combatant_voice_lines(
    export_root: Path = DEFAULT_EXPORT_ROOT,
    langs: tuple[str, ...] = DEFAULT_LANGS,
    combatant_ids: set[int] | None = None,
    overwrite: bool = False,
    vgmstream_cli: str = "vgmstream-cli",
) -> VoiceLineExport:
    validate_vgmstream(vgmstream_cli)

    export_root.mkdir(parents=True, exist_ok=True)
    combatants = combatant_names()
    if combatant_ids is not None:
        combatants = {
            combatant_id: name
            for combatant_id, name in combatants.items()
            if combatant_id in combatant_ids
        }

    text_by_lang = {lang: load_text_full_by_lang(lang) for lang in langs}
    translation_text_by_lang = {
        lang: load_text_full_by_lang(lang)
        for lang in TRANSLATION_LANGS
    }
    title_text_by_lang = {
        lang: load_text_full_by_lang(lang)
        for lang in TITLE_LANGS
    }
    lines_by_key: dict[tuple[int, str], VoiceLine] = {}
    banks_exported: Counter[str] = Counter()

    for combatant_id, character_name in sorted(combatants.items()):
        for lang in langs:
            bank_path = sound_root / f"{combatant_id}_voc_{lang}.bank"
            if not bank_path.exists():
                continue

            bank_lines = export_bank(
                bank_path=bank_path,
                combatant_id=combatant_id,
                character_name=character_name,
                lang=lang,
                export_root=export_root,
                transcript_text=text_by_lang.get(lang, {}),
                translation_text_by_lang=translation_text_by_lang,
                title_text_by_lang=title_text_by_lang,
                overwrite=overwrite,
                vgmstream_cli=vgmstream_cli,
            )
            for bank_line in bank_lines:
                line_key = (bank_line.combatant_id, bank_line.line_key)
                if line_key in lines_by_key:
                    lines_by_key[line_key].merge(bank_line)
                else:
                    lines_by_key[line_key] = bank_line
            banks_exported[lang] += 1

    lines = sorted(
        lines_by_key.values(),
        key=lambda line: (line.combatant_id, line.line_key),
    )
    export = VoiceLineExport(
        generated_at=datetime.now(UTC).isoformat(),
        sound_root=str(sound_root),
        lines=lines,
        summary=build_summary(lines, banks_exported),
    )
    save_voice_lines_json(export_root / "voice_lines.json", export)
    return export


def export_bank(
    bank_path: Path,
    combatant_id: int,
    character_name: str,
    lang: str,
    export_root: Path,
    transcript_text: dict[str, str],
    translation_text_by_lang: dict[str, dict[str, str]],
    title_text_by_lang: dict[str, dict[str, str]],
    overwrite: bool,
    vgmstream_cli: str,
) -> list[VoiceLine]:
    first_meta = read_stream_metadata(bank_path, 1, vgmstream_cli)
    stream_total = int(first_meta["streamInfo"]["total"])
    bank_lines: list[VoiceLine] = []
    used_paths: set[Path] = set()

    for stream_index in range(1, stream_total + 1):
        meta = first_meta if stream_index == 1 else read_stream_metadata(
            bank_path, stream_index, vgmstream_cli
        )
        stream_info = meta["streamInfo"]
        voice_event = stream_info.get("name") or f"sound_{stream_index}"
        line_key = voice_event_to_line_key(voice_event, combatant_id)
        text_id = voice_line_text_id(line_key)
        transcript = transcript_text.get(text_id, "")
        title, title_source = voice_line_title(line_key, title_text_by_lang)
        translation = {
            translation_lang: translation_text.get(text_id, "")
            for translation_lang, translation_text in translation_text_by_lang.items()
        }

        wav_path = unique_wav_path(
            export_root=export_root,
            combatant_id=combatant_id,
            character_name=character_name,
            lang=lang,
            voice_event=voice_event,
            stream_index=stream_index,
            used_paths=used_paths,
        )
        used_paths.add(wav_path)

        if overwrite or not wav_path.exists():
            decode_stream(bank_path, stream_index, wav_path, vgmstream_cli)

        bank_lines.append(
            VoiceLine(
                combatant_id=combatant_id,
                character_name=character_name,
                line_key=line_key,
                title=title,
                title_source=title_source,
                bank_file={lang: bank_path.name},
                stream_index={lang: stream_index},
                wav_path={lang: wav_path.as_posix()},
                transcript={lang: transcript},
                translation=translation,
            )
        )

    return bank_lines


def read_stream_metadata(bank_path: Path, stream_index: int, vgmstream_cli: str) -> dict[str, Any]:
    result = subprocess.run(
        [
            vgmstream_cli,
            "-I",
            "-m",
            "-s",
            str(stream_index),
            str(bank_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def decode_stream(
    bank_path: Path,
    stream_index: int,
    wav_path: Path,
    vgmstream_cli: str,
) -> None:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            vgmstream_cli,
            "-i",
            "-s",
            str(stream_index),
            "-o",
            str(wav_path),
            str(bank_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def build_summary(lines: list[VoiceLine], banks_exported: Counter[str]) -> dict[str, Any]:
    lines_by_lang: Counter[str] = Counter()
    transcript_by_lang: Counter[str] = Counter()
    translation_by_lang: Counter[str] = Counter()
    title_by_lang: Counter[str] = Counter()
    title_sources: Counter[str] = Counter()
    languages_by_line = Counter()
    for line in lines:
        langs = set(line.wav_path)
        languages_by_line[len(langs)] += 1
        for lang in langs:
            lines_by_lang[lang] += 1
            if line.transcript.get(lang):
                transcript_by_lang[lang] += 1
        for lang, translation in line.translation.items():
            if translation:
                translation_by_lang[lang] += 1
        for lang, title in line.title.items():
            if title:
                title_by_lang[lang] += 1
        title_sources[line.title_source or "unknown"] += 1

    combatant_ids = {line.combatant_id for line in lines}
    return {
        "combatants": len(combatant_ids),
        "banks_by_lang": dict(sorted(banks_exported.items())),
        "lines": len(lines),
        "audio_files": sum(lines_by_lang.values()),
        "lines_by_lang": dict(sorted(lines_by_lang.items())),
        "transcribed_lines_by_lang": dict(sorted(transcript_by_lang.items())),
        "missing_transcripts_by_lang": {
            lang: lines_by_lang[lang] - transcript_by_lang[lang]
            for lang in sorted(lines_by_lang)
        },
        "translated_lines_by_lang": dict(sorted(translation_by_lang.items())),
        "missing_translations_by_lang": {
            lang: len(lines) - translation_by_lang[lang]
            for lang in TRANSLATION_LANGS
        },
        "titled_lines_by_lang": dict(sorted(title_by_lang.items())),
        "missing_titles_by_lang": {
            lang: len(lines) - title_by_lang[lang]
            for lang in TITLE_LANGS
        },
        "title_sources": dict(sorted(title_sources.items())),
        "lines_by_language_count": {
            str(language_count): count
            for language_count, count in sorted(languages_by_line.items())
        },
    }


def coerce_lang_dict(
    value: Any,
    fallback_lang: str,
    coercer: type[str] | type[int] | type[float],
) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(lang): coercer(item) for lang, item in value.items()}
    if fallback_lang:
        return {fallback_lang: coercer(value)}
    return {}


def unique_wav_path(
    export_root: Path,
    combatant_id: int,
    character_name: str,
    lang: str,
    voice_event: str,
    stream_index: int,
    used_paths: set[Path],
) -> Path:
    character_dir = f"{combatant_id}_{sanitize_path_component(character_name)}"
    stem = sanitize_path_component(voice_event)
    path = export_root / character_dir / lang / f"{stem}.wav"
    if path not in used_paths:
        return path
    return export_root / character_dir / lang / f"{stem}_{stream_index}.wav"


def voice_event_to_line_key(voice_event: str, combatant_id: int) -> str:
    prefix = f"vo_{combatant_id}_"
    if voice_event.startswith(prefix):
        return f"{combatant_id}_{voice_event.removeprefix(prefix)}"
    if voice_event.startswith("vo_"):
        return voice_event.removeprefix("vo_")
    return voice_event


def voice_line_text_id(line_key: str) -> str:
    return f"combatant_voice@voice_text@{line_key}"


def voice_line_title(
    line_key: str,
    title_text_by_lang: dict[str, dict[str, str]],
) -> tuple[dict[str, str], str]:
    combatant_voice = combatant_voice_info_by_id().get(line_key)
    if combatant_voice is not None:
        title = str(combatant_voice.get("name", ""))
        if title and title != "none":
            return {"en": title}, "game_exact"

    english_titles = title_text_by_lang.get("en", {})
    title_key, source = voice_line_title_key(line_key, english_titles)
    if title_key:
        titles = {
            lang: text_by_id[title_key]
            for lang, text_by_id in title_text_by_lang.items()
            if title_key in text_by_id
        }
        if titles:
            return titles, source

    return {"en": guess_voice_line_title(voice_line_suffix(line_key))}, "guessed"


def voice_line_title_key(line_key: str, english_titles: dict[str, str]) -> tuple[str, str]:
    suffix = voice_line_suffix(line_key)
    title_key = f"combatant_voice_{suffix}"
    if title_key in english_titles:
        return title_key, "game_generic"

    alias = voice_line_title_alias(suffix)
    if alias:
        title_key = f"combatant_voice_{alias}"
        if title_key in english_titles:
            return title_key, "alias"

    return "", ""


def voice_line_suffix(line_key: str) -> str:
    match = re.match(r"^\d+_(.+)$", line_key)
    return match.group(1) if match else line_key


def voice_line_title_alias(suffix: str) -> str:
    alias = {
        "battle_idle_01": "idle_01",
        "battle_idle_02": "idle_02",
        "cut_in_01": "skill_cutin_01",
        "dmg_01": "hit_01",
        "dmg_02": "hit_01",
        "failure_01": "stage_fail_01",
        "fatal_end_01": "death_collapse_01",
        "lobby_touch_01": "touch_01",
        "lobby_touch_02": "touch_02",
        "sp_01": "skill_special_01",
        "ug": "skill_ug_01",
        "ug_01": "skill_ug_01",
        "ug_b": "skill_ug_01",
        "ug2": "skill_ug_02",
        "ug_02": "skill_ug_02",
        "ux": "skill_ux_01",
        "ux1": "skill_ux_01",
        "ux_01": "skill_ux_01",
        "ux_1": "skill_ux_01",
        "ux_2": "skill_ux_01",
        "ux_3": "skill_ux_01",
        "ux_02": "card_08",
    }
    if suffix in alias:
        return alias[suffix]

    if suffix.startswith("ug "):
        return "skill_ug_01"

    match = re.match(r"^u([1-6])(?:_b|_2)?$", suffix)
    if match:
        number = int(match.group(1))
        if number <= 4:
            return f"skill_u{number}_01"
        if number == 5:
            return "skill_ug_01"
        return "skill_ug_02"

    match = re.match(r"^skill_u([1-4])_01(?:_b)?$", suffix)
    if match:
        return f"skill_u{match.group(1)}_01"

    match = re.match(r"^skill_(cutin|special)_01(?:_[abc]|_01)?$", suffix)
    if match:
        return f"skill_{match.group(1)}_01"

    match = re.match(r"^skill_02(?:-01|_b)$", suffix)
    if match:
        return "skill_02"

    match = re.match(r"^small_talk_(\d{2})_(?:0[12])$", suffix)
    if match:
        return f"small_talk_{match.group(1)}"

    match = re.match(r"^touch_(\d{2})_b$", suffix)
    if match:
        return f"touch_{match.group(1)}"

    match = re.match(r"^lobby_enter_01(?:_[1b])?$", suffix)
    if match:
        return "lobby_enter_01"

    match = re.match(r"^collapse_(0[1-3])_[bcd]$", suffix)
    if match:
        return f"collapse_{match.group(1)}"

    return ""


def guess_voice_line_title(suffix: str) -> str:
    cleaned = re.sub(r"\s+-\s+.*$", "", suffix)
    cleaned = re.sub(r"\s*\([^)]*\)", "", cleaned).strip("_ ")

    exact = {
        "add_01": "Additional Voice",
        "lose_01": "Defeat",
        "ready_01": "Ready",
        "sense_back_01": "Homescreen Return",
        "sense_birth_01": "Birthday Greetings",
        "sense_christmas_01": "Christmas Greetings",
        "sense_christmas_01_01": "Christmas Greetings",
        "sense_halloween_01": "Halloween Greetings",
        "sense_newyear_01": "New Year's Greetings",
        "sense_vallentine_01": "Valentine's Day Greetings",
        "sense_vallentine_01_b": "Valentine's Day Greetings",
        "talk_sp_01": "Special Chatter",
        "title": "Title Call",
        "title_ALT02": "Title Call 2",
        "worry_01": "Worry",
    }
    if cleaned in exact:
        return exact[cleaned]

    patterns = [
        (r"^attack_(\d+)$", "Attack {n}"),
        (r"^begin_(\d+)$", "Start {n}"),
        (r"^break_(\d+)$", "Break {n}"),
        (r"^cheer_(\d+)$", "Cheer {n}"),
        (r"^clear_(\d+)$", "Clear {n}"),
        (r"^collapse_attack_?(\d+)(?:_\d+)?$", "Mental Breakdown Attack {n}"),
        (r"^collapse_attack_voice_(\d+)$", "Mental Breakdown Attack {n}"),
        (r"^death_collapse_attack_(\d+)$", "Mental Breakdown Death Attack {n}"),
        (r"^collapse_idle_?(\d+)$", "Mental Breakdown Standby {n}"),
        (r"^collapse_(\d+)$", "Mental Breakdown {n}"),
        (r"^crisis_(\d+)$", "Crisis {n}"),
        (r"^critical_(\d+)$", "Critical {n}"),
        (r"^emotion(?:_voice)?_(\d+)$", "Emotion {n}"),
        (r"^enter_(\d+)(?:_(\d+))?$", "Entry {n}{suffix}"),
        (r"^friendship_moment_(\d+)(?:-(\d+))?$", "Friendship Moment {n}{suffix}"),
        (r"^grade_(\d+)$", "Grade Up {n}"),
        (r"^idle_(\d+)$", "Battle Standby {n}"),
        (r"^over_(\d+)$", "Over {n}"),
        (r"^panic1_voice_(\d+)$", "Mental Breakdown {n}"),
        (r"^pair_ux_(\d+)$", "Pair Ultimate {n}"),
        (r"^pv_(\d+)$", "Promotional Voice {n}"),
        (r"^sense_hello_(\d+)(?:[-_](\d+)|_b)?$", "Homescreen Greeting {n}{suffix}"),
        (r"^skill_(\d+)$", "Skill {n}"),
        (r"^skill_u(\d+)_01(?:_b)?$", "Skill {n}"),
        (r"^skill_ug_(\d+)$", "Skill {n}"),
        (r"^skill_ux_(\d+)$", "Skill {n}"),
        (r"^small_talk_(\d+)$", "Chatter {n}"),
        (r"^stage_enter_(\d+)$", "Mission Start {n}"),
        (r"^stage_success_(\d+)(?:_b)?$", "Mission Clear {n}"),
        (r"^story_moment_(\d+)(?:_b)?$", "Perk {n}"),
        (r"^title_(\d+|[abc])$", "Title Call {n}"),
        (r"^town_enter_default_(\d+)$", "Town Entry {n}"),
        (r"^town_policy_enter_(\d+)$", "Town Policy Entry {n}"),
        (r"^tutorial_(\d+)$", "Tutorial {n}"),
        (r"^u(\d+)(?:_b|_2)?$", "Skill {n}"),
        (r"^ug_?(\d+)?$", "Skill {n}"),
        (r"^ux(?:_?(\d+))?$", "Skill {n}"),
        (r"^warning_(\d+)$", "Warning {n}"),
    ]
    for pattern, template in patterns:
        match = re.match(pattern, cleaned)
        if match:
            number = match.group(1) or "1"
            suffix_number = match.group(2) if len(match.groups()) > 1 else ""
            suffix_text = f".{suffix_number}" if suffix_number else ""
            return template.format(n=int(number) if number.isdigit() else number.upper(), suffix=suffix_text)

    return humanize_voice_line_suffix(cleaned)


def humanize_voice_line_suffix(suffix: str) -> str:
    words = re.sub(r"[_-]+", " ", suffix).strip()
    return words.title() if words else "Unknown Voice Line"


def sanitize_path_component(value: str) -> str:
    value = re.sub(r"[^\w.-]+", "_", value.strip(), flags=re.ASCII)
    value = value.strip("._")
    return value or "unknown"


def validate_vgmstream(vgmstream_cli: str) -> None:
    if shutil.which(vgmstream_cli) is None:
        raise RuntimeError(f"{vgmstream_cli!r} was not found in PATH")


@cache
def combatant_names() -> dict[int, str]:
    names = load_text("char_base")
    result: dict[int, str] = {}
    for entry in load_db("char_base@char_combatant"):
        combatant_id = int(entry["id"])
        result[combatant_id] = names.get(f"name@{combatant_id}", str(combatant_id))
    return result


@cache
def combatant_voice_info_by_id() -> dict[str, dict[str, Any]]:
    return {str(entry["id"]): entry for entry in load_db("combatant_info@combatant_voice")}


@cache
def load_text_full_by_lang(lang: str) -> dict[str, str]:
    path = assets_root / "text" / lang / "text.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {entry["id"]: entry["text"] for entry in raw}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export combatant voice lines from FMOD banks.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_EXPORT_ROOT)
    parser.add_argument("--langs", default=",".join(DEFAULT_LANGS))
    parser.add_argument("--ids", default="", help="Comma-separated combatant IDs to export.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--vgmstream-cli", default="vgmstream-cli")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    langs = tuple(lang.strip() for lang in args.langs.split(",") if lang.strip())
    combatant_ids = {
        int(id_.strip())
        for id_ in args.ids.split(",")
        if id_.strip()
    } or None
    export = export_combatant_voice_lines(
        export_root=args.output_root,
        langs=langs,
        combatant_ids=combatant_ids,
        overwrite=args.overwrite,
        vgmstream_cli=args.vgmstream_cli,
    )
    print(json.dumps(export.summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
