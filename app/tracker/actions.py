"""Buttons under a message or a card. The core decides which ones; the bot turns them into Telegram buttons."""

from dataclasses import dataclass

from app.tracker import movie_events, sequel_events
from app.tracker.cards import TitleCard
from app.tracker.models import STATUS_WANT

WATCHED = "watched"  # arg: title id
FOLLOW = "follow"  # arg: id of the «sequel announced» event

_WATCHED_LABEL = "✅ Посмотрел"
_FOLLOW_LABEL = "👀 Следить"

_MOVIE_EVENTS = frozenset(
    {movie_events.DATE_ANNOUNCED, movie_events.DATE_MOVED, movie_events.RELEASED, movie_events.DIGITAL}
)


@dataclass(frozen=True)
class Action:
    label: str
    name: str  # WATCHED | FOLLOW
    arg: int


def event_actions(event_type: str, event_id: int, title_id: int | None) -> list[Action]:
    """Buttons under the message of an event. Test events have none."""
    if event_type in _MOVIE_EVENTS and title_id is not None:
        return [Action(_WATCHED_LABEL, WATCHED, title_id)]
    if event_type == sequel_events.SEQUEL_ANNOUNCED:
        return [Action(_FOLLOW_LABEL, FOLLOW, event_id)]
    return []


def card_actions(card: TitleCard) -> list[Action]:
    """Buttons under a title's card: «Посмотрел» until the movie is watched."""
    return [Action(_WATCHED_LABEL, WATCHED, card.id)] if card.status == STATUS_WANT else []
