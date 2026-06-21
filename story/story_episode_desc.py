from dataclasses import dataclass
from functools import cache

from utils.utils import load_text
from utils.wiki_utils import save_json_page

@dataclass
class EpisodeDescription:
    id: int
    name: str
    desc: str

@cache
def parse_episodedescriptions() -> dict[str, EpisodeDescription]:
    result = {}
    episodedesc_text = load_text("story_map_node")
    for key, name in episodedesc_text.items():
        prefix, _, id_str = key.partition("@")
        if prefix == "name":
            episode_id = id_str
            desc = episodedesc_text.get(f'desc@{id_str}')
            result[name] = EpisodeDescription(id=episode_id, name=name, desc=desc)
    return result

def save_episodedescriptions_info():
    info_data = parse_episodedescriptions()
    save_json_page("Module:EpisodeDescription/data.json", info_data)

def main():
    save_episodedescriptions_info()

if __name__ == "__main__":
    main()