import json
from functools import cache
from pathlib import Path

text_root = Path("vendor/text")


@cache
def load_text(name: str) -> dict[str, str]:
    return json.loads((text_root / f"{name}.json").read_text(encoding="utf-8"))
