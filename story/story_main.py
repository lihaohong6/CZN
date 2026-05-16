from story.story_parser import (
    get_main_episodes,
    get_story_scenes,
    get_event_episodes,
    extract_episode_name,
    extract_display_title,
)
from story.story_types import StoryEpisode
from story.story_wikitext import episode_to_wikitext, chapter_overview_wikitext


def _group_by_act(episodes: list[StoryEpisode]) -> dict[int, list[StoryEpisode]]:
    by_act: dict[int, list[StoryEpisode]] = {}
    for ep in episodes:
        by_act.setdefault(ep.act, []).append(ep)
    return by_act


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
                    act=1,
                    chapter=chapter.chapter,
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
            chapter_data.append((chapter.act, main_eps, sub_eps))

        overview = chapter_overview_wikitext(season_name, chapter_data)
        save_wikitext_page(f"{season_name}/Story", overview, summary="update event story overview")
        process_uploads(all_uploads)


def save_main_story():
    from wiki_utils import save_wikitext_page

    episodes = get_main_episodes()
    by_act = _group_by_act(episodes)

    for act, part_eps in sorted(by_act.items()):
        chapter_map: dict[int, tuple[list[StoryEpisode], list[StoryEpisode]]] = {}
        for ep in part_eps:
            if ep.chapter not in chapter_map:
                chapter_map[ep.chapter] = ([], [])
            is_main = any(sid.startswith("main_") for sid in ep.scene_ids)
            (chapter_map[ep.chapter][0] if is_main else chapter_map[ep.chapter][1]).append(ep)

        chapter_tuples: list[tuple[int, list[StoryEpisode], list[StoryEpisode]]] = [
            (chapter_num, *chapter_map[chapter_num]) for chapter_num in sorted(chapter_map)
        ]

        overview = chapter_overview_wikitext(act, chapter_tuples)
        save_wikitext_page(f"Story/Act {act}", overview, summary="update story overview")

        for ep in part_eps:
            wt = episode_to_wikitext(ep)
            save_wikitext_page(f"Story/Act {act}/{ep.name}", wt, summary="update story page")


def main():
    # save_event_story()
    save_main_story()


if __name__ == "__main__":
    main()
