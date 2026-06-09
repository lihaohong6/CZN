"""Upload exported combatant voice lines to the wiki."""

from __future__ import annotations

import argparse
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from audio.audio_utils import (
    DEFAULT_OGG_ROOT,
    DEFAULT_VOICE_LINES_JSON,
    VOICE_OGG_BITRATE,
    VOICE_UPLOAD_LANGS,
    voice_line_suffix,
)
from audio.voice_lines import VoiceLine, VoiceLineExport, load_voice_lines_json
from char_info.characters import combatant_pages
from utils.upload_utils import UploadRequest, process_uploads
from utils.wiki_utils import save_wikitext_page


def wav_to_ogg(wav_path: Path, ogg_path: Path) -> Path:
    ogg_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(wav_path),
            "-c:a",
            "libopus",
            "-b:a",
            VOICE_OGG_BITRATE,
            "-y",
            str(ogg_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return ogg_path


def voice_line_file_name(line: VoiceLine, lang: str) -> str:
    character_name = wiki_file_component(line.character_name)
    suffix = wiki_file_component(voice_line_suffix(line.line_key))
    return f"Vo_{character_name}_{suffix}_{lang}.ogg"


def wiki_file_component(value: str) -> str:
    result: list[str] = []
    for char in value.strip().replace(" ", "_"):
        if char.isascii() and (char.isalnum() or char in "_.-"):
            result.append(char)
        elif char == "\t":
            result.append("_")
        elif not char.isascii():
            result.append(f"u{ord(char):04x}")
        else:
            result.append("_")
    return "".join(result) or "unknown"


def voice_line_ogg_path(line: VoiceLine, lang: str, ogg_root: Path = DEFAULT_OGG_ROOT) -> Path:
    return ogg_root / voice_line_file_name(line, lang)


def filter_voice_lines(
    export: VoiceLineExport,
    combatant_ids: set[int] | None = None,
) -> list[VoiceLine]:
    lines = export.lines
    if combatant_ids is not None:
        lines = [line for line in lines if line.combatant_id in combatant_ids]
    return sorted(lines, key=lambda line: (line.combatant_id, line.line_key))


def convert_voice_line_files(
    export: VoiceLineExport,
    combatant_ids: set[int] | None = None,
    overwrite: bool = False,
    ogg_root: Path = DEFAULT_OGG_ROOT,
) -> dict[tuple[str, str], Path]:
    result: dict[tuple[str, str], Path] = {}
    for line in filter_voice_lines(export, combatant_ids):
        for lang in VOICE_UPLOAD_LANGS:
            wav_name = line.wav_path.get(lang, "")
            if not wav_name:
                continue
            wav_path = Path(wav_name)
            if not wav_path.exists():
                continue
            ogg_path = voice_line_ogg_path(line, lang, ogg_root)
            if overwrite or not ogg_path.exists():
                wav_to_ogg(wav_path, ogg_path)
            result[(line.line_key, lang)] = ogg_path
    return result


def build_voice_line_uploads(
    export: VoiceLineExport,
    combatant_ids: set[int] | None = None,
    ogg_root: Path = DEFAULT_OGG_ROOT,
) -> list[UploadRequest]:
    requests: list[UploadRequest] = []
    seen_targets: set[str] = set()
    for line in filter_voice_lines(export, combatant_ids):
        for lang in VOICE_UPLOAD_LANGS:
            if lang not in line.wav_path:
                continue
            ogg_path = voice_line_ogg_path(line, lang, ogg_root)
            if not ogg_path.exists():
                continue
            target = voice_line_file_name(line, lang)
            if target in seen_targets:
                continue
            seen_targets.add(target)
            requests.append(
                UploadRequest(
                    source=ogg_path,
                    target=target,
                    text=(
                        "{{FairUse}}\n"
                        f"[[Category:{line.character_name} voice lines]]"
                    ),
                    summary="upload voice lines",
                )
            )
    return requests


def upload_voice_line_files(
    export: VoiceLineExport,
    combatant_ids: set[int] | None = None,
    force: bool = False,
    overwrite_ogg: bool = False,
) -> None:
    convert_voice_line_files(export, combatant_ids=combatant_ids, overwrite=overwrite_ogg)
    process_uploads(build_voice_line_uploads(export, combatant_ids=combatant_ids), force=force)


def build_voice_page_text(lines: list[VoiceLine]) -> str:
    sections: dict[str, list[VoiceLine]] = defaultdict(list)
    for line in sorted(lines, key=lambda item: item.line_key):
        sections[voice_line_section(line)].append(line)

    result = ["{{VoiceTop}}", ""]
    for section_name in ("Homescreen", "Combat", "Story and Special"):
        section_lines = sections.get(section_name, [])
        if not section_lines:
            continue
        result.append(f"=={section_name}==")
        for line in section_lines:
            result.append(voice_line_template(line))
        result.append("")
    result.append("{{VoiceBottom}}")
    return "\n".join(result)


def create_voice_line_audio_pages(
    export: VoiceLineExport,
    combatant_ids: set[int] | None = None,
) -> None:
    lines_by_combatant: dict[int, list[VoiceLine]] = defaultdict(list)
    for line in filter_voice_lines(export, combatant_ids):
        lines_by_combatant[line.combatant_id].append(line)

    page_by_title = {
        page.title(with_ns=False): page
        for page in combatant_pages("/voice")
    }
    for combatant_id, lines in sorted(lines_by_combatant.items()):
        if not lines:
            continue
        page_title = f"{lines[0].character_name}/voice"
        page = page_by_title.get(page_title)
        if page is None:
            continue
        save_wikitext_page(
            page,
            build_voice_page_text(lines),
            summary="update voice lines page",
        )


def voice_line_template(line: VoiceLine) -> str:
    fields = {
        "key": line.line_key,
        "title": line.title.get("en", ""),
        "file_ja": voice_line_file_name(line, "ja") if "ja" in line.wav_path else "",
        "file_ko": voice_line_file_name(line, "ko") if "ko" in line.wav_path else "",
        "text_ja": line.transcript.get("ja", ""),
        "text_ko": line.transcript.get("ko", ""),
        "text_en": line.translation.get("en", ""),
    }
    args = "|".join(
        f"{key}={escape_template_value(value)}"
        for key, value in fields.items()
    )
    return "{{AudioRow|" + args + "}}"


def escape_template_value(value: str) -> str:
    return (
        str(value)
        .replace("|", "{{!}}")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br/>")
    )


def voice_line_section(line: VoiceLine) -> str:
    suffix = voice_line_suffix(line.line_key).lower()
    if re.match(
        r"^(battle_idle|attack|begin|break|buff|clear|collapse|crisis|critical|"
        r"death|death_collapse|defense|dmg|enter|failure|fatal|fatal_end|hit|"
        r"idle|lose|over|panic|pair_ux|ready|skill|sp|stage|u\d|ug|ux|warning)",
        suffix,
    ):
        return "Combat"
    if re.match(
        r"^(lobby|sense|small_talk|talk|title|touch|emotion|worry)",
        suffix,
    ):
        return "Homescreen"
    return "Story and Special"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload combatant voice lines to the wiki.")
    parser.add_argument("--ids", default="", help="Comma-separated combatant IDs to process.")
    return parser.parse_args()


def parse_combatant_ids(value: str) -> set[int] | None:
    return {
        int(id_.strip())
        for id_ in value.split(",")
        if id_.strip()
    } or None


def main() -> None:
    args = parse_args()
    combatant_ids = parse_combatant_ids(args.ids)
    export = load_voice_lines_json(DEFAULT_VOICE_LINES_JSON)

    # Comment out either line when only one wiki action is needed.
    upload_voice_line_files(export, combatant_ids=combatant_ids)
    create_voice_line_audio_pages(export, combatant_ids=combatant_ids)


if __name__ == "__main__":
    main()
