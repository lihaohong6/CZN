from __future__ import annotations

import argparse
import filecmp
import json
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audio.audio_utils import (
    DEFAULT_EXPORT_ROOT,
    DEFAULT_LANGS,
    DEFAULT_PARTNER_EXPORT_ROOT,
    TITLE_LANGS,
    TRANSLATION_LANGS,
    combatant_names,
    is_suffixed_lobby_enter_variant,
    load_text_full_by_lang,
    partner_names,
    partner_voice_line_title,
    resolve_voice_line_text,
    resolve_partner_voice_line_text,
    unique_wav_path,
    validate_vgmstream,
    voice_event_to_line_key,
    voice_line_text_id,
    voice_line_suffix,
    voice_line_title,
    voice_line_title_alias,
)
from audio.voice_lines import VoiceLine, VoiceLineExport, save_voice_lines_json
from utils.utils import sound_root


def export_combatant_voice_lines(
    export_root: Path = DEFAULT_EXPORT_ROOT,
    langs: tuple[str, ...] = DEFAULT_LANGS,
    combatant_ids: set[int] | None = None,
    overwrite: bool = False,
) -> VoiceLineExport:
    return export_voice_lines("combatants", export_root, langs, combatant_ids, overwrite)


def export_partner_voice_lines(
    export_root: Path = DEFAULT_PARTNER_EXPORT_ROOT,
    langs: tuple[str, ...] = DEFAULT_LANGS,
    partner_ids: set[int] | None = None,
    overwrite: bool = False,
) -> VoiceLineExport:
    return export_voice_lines("partners", export_root, langs, partner_ids, overwrite)


def export_voice_lines(
    kind: str,
    export_root: Path,
    langs: tuple[str, ...],
    character_ids: set[int] | None,
    overwrite: bool,
) -> VoiceLineExport:
    validate_vgmstream("vgmstream-cli")

    export_root.mkdir(parents=True, exist_ok=True)
    character_names = partner_names() if kind == "partners" else combatant_names()
    if character_ids is not None:
        character_names = {
            character_id: name
            for character_id, name in character_names.items()
            if character_id in character_ids
        }

    text_by_lang = {lang: load_text_full_by_lang(lang) for lang in langs}
    translation_text_by_lang = {
        lang: load_text_full_by_lang(lang)
        for lang in TRANSLATION_LANGS
    }
    exact_voice_text_ids = set().union(
        *(text_by_id.keys() for text_by_id in text_by_lang.values()),
        *(text_by_id.keys() for text_by_id in translation_text_by_lang.values()),
    )
    title_text_by_lang = {
        lang: load_text_full_by_lang(lang)
        for lang in TITLE_LANGS
    }
    lines_by_key: dict[tuple[int, str], VoiceLine] = {}
    banks_exported: Counter[str] = Counter()

    for combatant_id, character_name in sorted(character_names.items()):
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
                exact_voice_text_ids=exact_voice_text_ids,
                title_text_by_lang=title_text_by_lang,
                overwrite=overwrite,
                kind=kind,
            )
            for bank_line in bank_lines:
                if "_emotion_" in bank_line.line_key:
                    continue
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
    lines = consolidate_voice_line_duplicates(lines)
    export = VoiceLineExport(
        generated_at=datetime.now(UTC).isoformat(),
        sound_root=str(sound_root),
        lines=lines,
        summary=build_summary(lines, banks_exported, kind),
    )
    save_voice_lines_json(export_root / "voice_lines.json", export)
    return export


TITLE_SOURCE_PRIORITY = {"game_exact": 0, "alias": 1, "game_generic": 2, "guessed": 3}


def consolidate_voice_line_duplicates(lines: list[VoiceLine]) -> list[VoiceLine]:
    groups: dict[tuple[int, str], list[VoiceLine]] = defaultdict(list)
    for line in lines:
        groups[(line.combatant_id, canonical_voice_line_suffix(line))].append(line)

    result: list[VoiceLine] = []
    for group in groups.values():
        clusters: list[VoiceLine] = []
        for line in sorted(group, key=voice_line_primary_sort_key):
            for primary in clusters:
                if compatible_voice_lines(primary, line):
                    merge_duplicate_voice_line(primary, line)
                    break
            else:
                clusters.append(line)
        result.extend(clusters)

    return sorted(result, key=lambda line: (line.combatant_id, line.line_key))


def canonical_voice_line_suffix(line: VoiceLine) -> str:
    suffix = voice_line_suffix(line.line_key)
    return voice_line_title_alias(suffix) or suffix


def voice_line_primary_sort_key(line: VoiceLine) -> tuple[int, int, int, str]:
    suffix = voice_line_suffix(line.line_key)
    canonical_suffix = canonical_voice_line_suffix(line)
    return (
        0 if suffix == canonical_suffix else 1,
        -len(line.wav_path),
        TITLE_SOURCE_PRIORITY.get(line.title_source, 99),
        line.line_key,
    )


def compatible_voice_lines(primary: VoiceLine, other: VoiceLine) -> bool:
    overlapping_langs = set(primary.wav_path) & set(other.wav_path)
    if not overlapping_langs:
        return True
    return all(same_voice_audio(primary, other, lang) for lang in overlapping_langs)


def same_voice_audio(first: VoiceLine, second: VoiceLine, lang: str) -> bool:
    first_bank = first.bank_file.get(lang)
    second_bank = second.bank_file.get(lang)
    first_stream = first.stream_index.get(lang)
    second_stream = second.stream_index.get(lang)
    if (
        first_bank
        and second_bank
        and first_bank == second_bank
        and first_stream is not None
        and first_stream == second_stream
    ):
        return True

    first_path = Path(first.wav_path.get(lang, ""))
    second_path = Path(second.wav_path.get(lang, ""))
    if not first_path.exists() or not second_path.exists():
        return False
    return filecmp.cmp(first_path, second_path, shallow=False)


def merge_duplicate_voice_line(primary: VoiceLine, other: VoiceLine) -> None:
    for lang, wav_path in other.wav_path.items():
        if lang not in primary.wav_path:
            if lang in other.bank_file:
                primary.bank_file[lang] = other.bank_file[lang]
            if lang in other.stream_index:
                primary.stream_index[lang] = other.stream_index[lang]
            primary.wav_path[lang] = wav_path
            if lang in other.transcript:
                primary.transcript[lang] = other.transcript[lang]
            continue

        if other.transcript.get(lang) and not primary.transcript.get(lang):
            primary.transcript[lang] = other.transcript[lang]

    for lang, text in other.translation.items():
        if text and not primary.translation.get(lang):
            primary.translation[lang] = text


def should_skip_unmapped_lobby_enter_variant(
    line_key: str,
    exact_voice_text_ids: set[str],
) -> bool:
    if not is_suffixed_lobby_enter_variant(line_key):
        return False
    return voice_line_text_id(line_key) not in exact_voice_text_ids


def export_bank(
    bank_path: Path,
    combatant_id: int,
    character_name: str,
    lang: str,
    export_root: Path,
    transcript_text: dict[str, str],
    translation_text_by_lang: dict[str, dict[str, str]],
    exact_voice_text_ids: set[str],
    title_text_by_lang: dict[str, dict[str, str]],
    overwrite: bool,
    kind: str = "combatants",
) -> list[VoiceLine]:
    first_meta = read_stream_metadata(bank_path, 1)
    stream_total = int(first_meta["streamInfo"]["total"])
    bank_lines: list[VoiceLine] = []
    used_paths: set[Path] = set()
    text_resolver = (
        resolve_partner_voice_line_text
        if kind == "partners"
        else resolve_voice_line_text
    )
    title_resolver = partner_voice_line_title if kind == "partners" else voice_line_title

    for stream_index in range(1, stream_total + 1):
        meta = first_meta if stream_index == 1 else read_stream_metadata(
            bank_path, stream_index
        )
        stream_info = meta["streamInfo"]
        voice_event = stream_info.get("name") or f"sound_{stream_index}"
        line_key = voice_event_to_line_key(voice_event, combatant_id)
        if kind == "combatants" and should_skip_unmapped_lobby_enter_variant(
            line_key, exact_voice_text_ids
        ):
            continue

        transcript = text_resolver(line_key, transcript_text)
        title, title_source = title_resolver(line_key, title_text_by_lang)
        translation = {
            translation_lang: text_resolver(line_key, translation_text)
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
            decode_stream(bank_path, stream_index, wav_path)

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


def read_stream_metadata(bank_path: Path, stream_index: int) -> dict[str, Any]:
    result = subprocess.run(
        [
            "vgmstream-cli",
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
) -> None:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "vgmstream-cli",
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


def build_summary(
    lines: list[VoiceLine],
    banks_exported: Counter[str],
    character_key: str = "combatants",
) -> dict[str, Any]:
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
        character_key: len(combatant_ids),
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export voice lines from FMOD banks.")
    parser.add_argument(
        "--kind",
        choices=("combatants", "partners", "both"),
        default="both",
        help="Character type to export.",
    )
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--langs", default=",".join(DEFAULT_LANGS))
    parser.add_argument("--ids", default="", help="Comma-separated character IDs to export.")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    langs = tuple(lang.strip() for lang in args.langs.split(",") if lang.strip())
    combatant_ids = {
        int(id_.strip())
        for id_ in args.ids.split(",")
        if id_.strip()
    } or None
    if args.kind in ("partners", "both"):
        export = export_partner_voice_lines(
            export_root=args.output_root or DEFAULT_PARTNER_EXPORT_ROOT,
            langs=langs,
            partner_ids=combatant_ids,
            overwrite=args.overwrite,
        )
        print(json.dumps(export.summary, ensure_ascii=False, indent=2))
    if args.kind in ("combatants", "both"):
        export = export_combatant_voice_lines(
            export_root=args.output_root or DEFAULT_EXPORT_ROOT,
            langs=langs,
            combatant_ids=combatant_ids,
            overwrite=args.overwrite,
        )
        print(json.dumps(export.summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
