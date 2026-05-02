import json
import os


def split_text_json():
    src = "vendor/assets/text/en/text.json"
    out_dir = "vendor/text"

    with open(src, encoding="utf-8") as f:
        entries = json.load(f)

    buckets: dict[str, dict[str, str]] = {}
    for entry in entries:
        id_ = entry["id"]
        if "@" in id_:
            prefix, _, key = id_.partition("@")
        else:
            prefix, key = "_default", id_
        buckets.setdefault(prefix, {})[key] = entry["text"]

    os.makedirs(out_dir, exist_ok=True)
    for prefix, data in buckets.items():
        with open(os.path.join(out_dir, f"{prefix}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    split_text_json()
