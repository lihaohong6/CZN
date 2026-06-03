from dataclasses import dataclass
from functools import cache

from utils.utils import load_text
from utils.wiki_utils import save_json_page

@dataclass
class Archive:
    id: int
    name: str
    desc: str

@cache
def parse_archives() -> dict[str, Archive]:
    result = {}
    archive_text = load_text("archive_universe")
    for key, name in archive_text.items():
        prefix, _, id_str = key.partition("@")
        if prefix == "name":
            if id_str.isnumeric():
                archive_id = int(id_str)
                desc = archive_text.get(f'desc@{id_str}')
                result[name] = Archive(id=archive_id, name=name, desc=desc)
    return result

def save_archives_info():
    info_data = parse_archives()
    save_json_page("Module:Archive/data.json", info_data)

def main():
    save_archives_info()

if __name__ == "__main__":
    main()
