import dataclasses
import enum
import json

from pywikibot import Site, Page

s = Site()


def dump_json(obj):
    class EnhancedJSONEncoder(json.JSONEncoder):
        def default(self, o):
            if dataclasses.is_dataclass(o):
                return dataclasses.asdict(o)
            if isinstance(o, enum.Enum):
                return o.value
            return super().default(o)
    return json.dumps(obj, indent=4, cls=EnhancedJSONEncoder)


def save_json_page(page: Page | str, obj, summary: str = "update json page"):
    if isinstance(page, str):
        page = Page(s, page)
    if page.text != "":
        original_json = json.loads(page.text)
        original = dump_json(original_json)
    else:
        original = ""
    modified = dump_json(obj)
    if original != modified:
        page.text = modified
        page.save(summary=summary)
