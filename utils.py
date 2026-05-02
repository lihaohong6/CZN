import json
from functools import cache
from pathlib import Path

text_root = Path("vendor/text")
db_root = Path("vendor/assets/db")


@cache
def load_text(name: str) -> dict[str, str]:
    return json.loads((text_root / f"{name}.json").read_text(encoding="utf-8"))


@cache
def load_text_full() -> dict[str, str]:
    raw = json.loads(
        Path("vendor/assets/text/en/text.json").read_text(encoding="utf-8")
    )
    return {entry["id"]: entry["text"] for entry in raw}


@cache
def load_db(name: str) -> list[dict]:
    text = load_text_full()
    raw = json.loads((db_root / f"{name}.json").read_text(encoding="utf-8"))
    result = []
    for entry in raw:
        resolved = {}
        for key, value in entry.items():
            if isinstance(value, str) and value in text:
                resolved[key] = text[value]
            elif isinstance(value, str) and value.lower() in text:
                resolved[key] = text[value.lower()]
            else:
                resolved[key] = value
        result.append(resolved)
    return result
