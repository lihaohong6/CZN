from functools import cache

from characters import parse_characters
from item import parse_items
from utils.utils import load_db
from utils.wiki_utils import save_json_page


@cache
def parse_favourite_gifts() -> dict[int, list[str]]:
    slot_to_item = {
        entry["id"]: entry["link_item_id"]
        for entry in load_db("favorite_gift_collection@favorite_gift_collection")
    }
    item_names = {str(item.id): item.name for item in parse_items().values()}
    characters = parse_characters()
    result = {}
    for entry in load_db("favorite_gift_collection@favorite_gift_collection_set"):
        char_id = int(entry["link_char_base_id"])
        if char_id not in characters:
            continue
        slot_ids = entry["link_favorite_gift_collection_id"].strip("[]").split(",")
        gifts = [item_names[slot_to_item[s]] for s in slot_ids]
        result[char_id] = gifts
    return result


def save_favourite_gifts():
    data = parse_favourite_gifts()
    characters = parse_characters()
    obj = {characters[cid].name: gifts for cid, gifts in data.items()}
    save_json_page(
        "Module:FavouriteGifts/data.json", obj, summary="update favourite gifts"
    )


def main():
    save_favourite_gifts()


if __name__ == "__main__":
    main()
