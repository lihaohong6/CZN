from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audio.audio_utils import DEFAULT_EXPORT_ROOT


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
