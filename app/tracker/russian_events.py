"""The events of Russian in games (pure): the texts, the keys, the payloads, the samples of «Тестовое событие» and `TYPES`.

Spec 5.8 of stage 9.1b. Pure: no database, no network, no clock. What appeared is decided by `russian.appeared`, the
reference point by `russian.is_reference`; here the parts become a message. Each event is its own message (no folding),
a line each in a summary and in «Недавно». The official event: «🎮 В «Stray» появился русский текст», «… появилась
русская озвучка», «… появились русский текст и озвучка», with « (ПК)» at the end by the rule of the line (official
data from Steam, the owner plays on another platform too). Its key is `moved_key("game:<id>:russian:official:<parts>",
previous_look)`: found again after a failed store — dropped; a real later appearance — told. `TYPES` is the one list of
the types (the buttons read it: «📄 Карточка» and «🛒 Открыть в Steam» when the payload has `steam_id`).
"""

from datetime import datetime
from typing import Any

from app.tracker.dedup import moved_key
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.tracker.movie_events import DetectedEvent
from app.tracker.russian import PC_MARK, Support, parts_key

_ICON = KINDS[TitleKind.GAME].icon

OFFICIAL = "game_russian_official"
TYPES = (OFFICIAL,)  # the one list of the types of the events of Russian


def official_text(name: str, parts: Support, pc: bool) -> str:
    """«🎮 В «Stray» появился русский текст»; voice — «появилась русская озвучка»; both — «появились русский текст и
    озвучка»; « (ПК)» at the end when `pc`."""
    if parts.text and parts.voice:
        what = "появились русский текст и озвучка"
    elif parts.text:
        what = "появился русский текст"
    else:
        what = "появилась русская озвучка"
    text = f"{_ICON} В «{name}» {what}"
    return f"{text} {PC_MARK}" if pc else text


def official_payload(name: str, parts: Support, source: str, steam_id: str | None, pc: bool) -> dict[str, Any]:
    """`{"text", "name", "parts", "source", "steam_id", "pc"}` of an official event."""
    return {
        "text": official_text(name, parts, pc), "name": name, "parts": parts_key(parts), "source": source,
        "steam_id": steam_id, "pc": pc,
    }


def official_event(
    title_id: int, name: str, parts: Support, source: str, steam_id: str | None, pc: bool, previous_look: datetime
) -> DetectedEvent:
    """The event of the official parts that appeared; `previous_look` — the moment of the stored look it compares with."""
    data = official_payload(name, parts, source, steam_id, pc)
    key = moved_key(f"game:{title_id}:russian:official:{parts_key(parts)}", previous_look)
    return DetectedEvent(OFFICIAL, key, data.pop("text"), data)


# --- «Тестовое событие» ---------------------------------------------------------------------------------------------

_SAMPLE_GAME = ("Hollow Knight: Silksong", "1030300")  # the button of the sample opens the page of a real game


def _sample_official() -> tuple[str, dict[str, Any]]:
    name, steam_id = _SAMPLE_GAME
    return OFFICIAL, official_payload(name, Support(False, True), "steam", steam_id, False)


# (id, menu label, the events of the sample: type and payload each) — events of the real type, so the button works
TEST_SAMPLES: list[tuple[str, str, Any]] = [
    ("game-russian", "Игра: появился русский язык", lambda: [_sample_official()]),
]
