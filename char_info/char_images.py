from char_info.characters import parse_characters
from utils.upload_utils import process_uploads, UploadRequest
from utils.utils import assets_root, load_db
from story.story_parser import get_story_scenes
from story.story_types import StoryElementType


def save_story_faces():
    actor_map: dict[str, tuple[str, str]] = {}
    for entry in load_db("actor@actor"):
        pm = entry.get("portrait_mini", "")
        if not pm or pm == "NONE":
            continue
        actor_map[entry["id"]] = (entry.get("name", ""), pm)

    scenes = get_story_scenes()
    seen_names: set[str] = set()
    uploads: list[UploadRequest] = []

    for scene in scenes.values():
        for elem in scene.elements:
            if elem.type not in (StoryElementType.DIALOGUE, StoryElementType.MONOLOGUE):
                continue
            talker = elem.args.get("talker", "")
            if talker not in actor_map:
                continue
            eng_name, portrait_mini = actor_map[talker]
            if not eng_name or eng_name in seen_names:
                continue
            source = assets_root / f"face/character/{portrait_mini}.png"
            if not source.exists():
                continue
            seen_names.add(eng_name)
            uploads.append(UploadRequest(
                source=source,
                target=f"Profile_{eng_name}.png",
                text="{{FairUse}}\n[[Category:Character profile pictures]]",
                summary="upload character profile picture",
            ))

    process_uploads(uploads)


def save_collapse_illustrations():
    chars = parse_characters()
    collapse_dir = assets_root / "collapse/collapse_illustration"
    uploads: list[UploadRequest] = []
    for i in (1, 2):
        for char_id, info in chars.items():
            source = collapse_dir / f"collapse_{char_id}_0{i}.png"
            if not source.exists():
                continue
            uploads.append(UploadRequest(
                source=source,
                target=f"{info.name} Collapse {i}.png",
                text="{{FairUse}}\n[[Category:Collapse illustrations]]",
                summary="upload collapse illustration",
            ))

    process_uploads(uploads)


def save_combatant_portraits():
    chars = parse_characters()
    portrait_dir = assets_root / "face/character"
    uploads: list[UploadRequest] = []
    for char_id, info in chars.items():
        source = portrait_dir / f"portrait_character_{char_id}.png"
        if not source.exists():
            continue
        uploads.append(UploadRequest(
            source=source,
            target=f"{info.name} Portrait.png",
            text="{{FairUse}}\n[[Category:Character portraits]]",
            summary="upload combatant portrait",
        ))

    process_uploads(uploads)


def upload_character_images():
    save_story_faces()
    save_collapse_illustrations()
    save_combatant_portraits()


def main():
    upload_character_images()


if __name__ == "__main__":
    main()
