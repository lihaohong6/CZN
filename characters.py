from dataclasses import dataclass
from functools import cache

from utils import load_text


@dataclass
class Character:
    id: int
    name: str

    def __hash__(self) -> int:
        return hash(self.id)


@cache
def parse_characters() -> dict[int, Character]:
    result = {}
    for key, name in load_text("char_base").items():
        prefix, _, id_str = key.partition("@")
        if prefix == "name":
            char_id = int(id_str)
            result[char_id] = Character(id=char_id, name=name)
    return result
