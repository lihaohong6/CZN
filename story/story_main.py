from story.story_parser import (
    get_main_episodes,
    get_story_scenes,
    get_event_episodes,
    extract_episode_name,
    extract_display_title,
)
from story.story_types import StoryEpisode
from story.story_wikitext import episode_to_wikitext, part_overview_wikitext, event_overview_wikitext


def _group_by_part(episodes: list[StoryEpisode]) -> dict[int, list[StoryEpisode]]:
    by_part: dict[int, list[StoryEpisode]] = {}
    for ep in episodes:
        by_part.setdefault(ep.part, []).append(ep)
    return by_part


def save_story_episodes(count: int = 5):
    from upload_utils import process_uploads
    from wiki_utils import save_wikitext_page

    episodes = get_main_episodes()[:count]
    scenes = get_story_scenes()

    all_uploads = []

    for ep in episodes:
        wt = episode_to_wikitext(ep)
        save_wikitext_page(f"Story/{ep.name}", wt, summary="update story page")
        for sid in ep.scene_ids:
            scene = scenes.get(sid)
            if scene is not None:
                all_uploads.extend(scene.uploads)

    process_uploads(all_uploads)


def save_event_story():
    from upload_utils import process_uploads
    from wiki_utils import save_wikitext_page

    scenes = get_story_scenes()

    for group in get_event_episodes()[2:]:
        season_name = group.display_title
        for sep in (" – ", " - "):
            if sep in season_name:
                season_name = season_name.split(sep, 1)[1].strip()
                break

        all_uploads = []
        chapter_data: list[tuple[int, list[StoryEpisode], list[StoryEpisode]]] = []

        for chapter in group.chapters:
            main_eps: list[StoryEpisode] = []
            sub_eps: list[StoryEpisode] = []
            for sid in chapter.scene_ids:
                scene = scenes.get(sid)
                if scene is None:
                    continue
                raw_title = scene.title
                name = extract_episode_name(raw_title) if raw_title else sid
                display = extract_display_title(raw_title) if raw_title else sid
                ep = StoryEpisode(
                    part=chapter.part,
                    episode_key=sid,
                    name=name,
                    display_title=display,
                    scene_ids=[sid],
                )
                wt = episode_to_wikitext(ep)
                save_wikitext_page(f"{season_name}/Story/{name}", wt, summary="update event story page")
                all_uploads.extend(scene.uploads)
                if sid.startswith("main_"):
                    main_eps.append(ep)
                else:
                    sub_eps.append(ep)
            chapter_data.append((chapter.part, main_eps, sub_eps))

        overview = event_overview_wikitext(season_name, chapter_data)
        save_wikitext_page(f"{season_name}/Story", overview, summary="update event story overview")
        process_uploads(all_uploads)


def save_story():
    from wiki_utils import save_wikitext_page

    episodes = get_main_episodes()
    by_part = _group_by_part(episodes)

    for part, part_eps in sorted(by_part.items()):
        overview = part_overview_wikitext(part, part_eps)
        save_wikitext_page(
            f"Story/Part {part}", overview, summary="update story overview"
        )

    for ep in episodes:
        wt = episode_to_wikitext(ep)
        save_wikitext_page(f"Story/{ep.name}", wt, summary="update story page")


def main():
    episodes = get_main_episodes()
    print(f"Found {len(episodes)} episodes")
    for ep in episodes:
        print(
            f"  Part {ep.part} {ep.episode_key}: "
            f"{ep.display_title!r} -> Story/{ep.name} ({len(ep.scene_ids)} scenes)"
        )
    print()

    by_part = _group_by_part(episodes)

    for part in sorted(by_part):
        print(part_overview_wikitext(part, by_part[part]))
        print()

    ep = episodes[0]
    print(f"--- First few lines of Story/{ep.name} ---")
    wt = episode_to_wikitext(ep)
    for line in wt.split("\n")[:20]:
        print(line)


if __name__ == "__main__":
    save_event_story()
