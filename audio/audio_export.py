from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audio.audio_utils import (
    DEFAULT_EXPORT_ROOT,
    DEFAULT_LANGS,
    TITLE_LANGS,
    TRANSLATION_LANGS,
    combatant_names,
    load_text_full_by_lang,
    unique_wav_path,
    validate_vgmstream,
    voice_event_to_line_key,
    voice_line_text_id,
    voice_line_title,
)
from audio.voice_lines import VoiceLine, VoiceLineExport, save_voice_lines_json
from utils.utils import sound_root


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
