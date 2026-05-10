from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from upload_utils import UploadRequest


class StoryElementType(Enum):
    BACKGROUND = "background"
    CHAPTER = "chapter"
    LOCATION = "location"
    NARRATION = "narration"
    CAPTION = "caption"
    ENDING = "ending"
    DIALOGUE = "dialogue"
    PROTAGONIST = "protagonist"
    MONOLOGUE = "monologue"
    CHOICE = "choice"
    COUNSELING = "counseling"


@dataclass
class StoryElement:
    type: StoryElementType
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class StoryStep:
    yuna_key: str
    text_type: str
    talker: str
    name: str
    text_en: str
    face: str
    size: str
    background: str
    res_action_type: str
    slots: dict[str, str]
    use_choice: str
    choice: str
    link_story_choice_id: str
    opt: str


@dataclass
class StoryScene:
    scene_id: str
    title: str
    location: str
    elements: list[StoryElement] = field(default_factory=list)
    uploads: list[UploadRequest] = field(default_factory=list)


@dataclass
class StoryEpisode:
    part: int
    episode_key: str
    name: str
    display_title: str
    scene_ids: list[str]


SKIP_TEXT_TYPES = {"EMPTY", "CLEAR", "FIRST_SKILL_UI", "UNI_RECEIVE"}

CHOICE_TEXT_TYPES = {
    "CHOICE",
    "SCORE_CHOICE",
    "SCORE_CHOICE_L",
    "SCORE_CHOICE_R",
    "CHAT_CHOICE1",
    "CHAT_CHOICE2",
}

NAMED_TEXT_TYPE_MAP = {
    "CHAPTER": StoryElementType.CHAPTER,
    "LOCATION": StoryElementType.LOCATION,
    "NARRATION": StoryElementType.NARRATION,
    "CAPTION": StoryElementType.CAPTION,
    "ENDING": StoryElementType.ENDING,
    "MONO": StoryElementType.MONOLOGUE,
    "COUNSELING": StoryElementType.COUNSELING,
}

GENERIC_DIALOGUE_TYPES = {"", "DIALOGUE", "empty", " EMPTY", "\u3000", "디아나"}


def add_if_present(args: dict[str, Any], key: str, value: Any):
    if value and value != {}:
        args[key] = value
