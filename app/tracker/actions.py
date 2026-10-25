"""Buttons under a message or a card. The core decides which ones; the bot turns them into Telegram buttons."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.tracker import movie_events, sequel_events
from app.tracker.cards import TitleCard
from app.tracker.models import STATUS_WANT

WATCHED = "watched"  # arg: title id
FOLLOW = "follow"  # arg: "<kind>:<id of the sequel in its source>" (an old button: the id of the «sequel announced» event)
SEASONS = "seasons"  # arg: title id; opens the choice of watched seasons
CARD = "card"  # arg: title id; shows the title's card (stands in for «Открыть» until there is a web app)
DELETE = "delete"  # arg: title id; asks for confirmation, then removes the title with everything that belongs to it

_WATCHED_LABEL = "✅ Посмотрел"
_FOLLOW_LABEL = "👀 Следить"
_SEASONS_LABEL = "📺 Просмотренные сезоны"
_CARD_LABEL = "📄 Карточка"
_DELETE_LABEL = "🗑 Удалить"

_MOVIE_EVENTS = frozenset(
    {movie_events.DATE_ANNOUNCED, movie_events.DATE_MOVED, movie_events.RELEASED, movie_events.DIGITAL}
)


@dataclass(frozen=True)
class Action:
    label: str
    name: str  # WATCHED | FOLLOW | SEASONS | CARD | DELETE
    arg: int | str  # «Следить» carries text: "<kind>:<id in the source>"


def event_actions(
    event_type: str, event_id: int, title_id: int | None, data: Mapping[str, Any] | None = None
) -> list[Action]:
    """Buttons under the message of an event. Test events have none. A sequel announcement offers «Следить» only:
    its title is the film already watched, whose card says nothing new. The button names the sequel itself, so it
    works whether or not the announcement (or the film) is still in the database; an event that does not say
    which sequel it is about (a test sample) falls back to its own number."""
    if event_type == sequel_events.SEQUEL_ANNOUNCED:
        data = data or {}
        kind, sequel_id = data.get("kind"), data.get("sequel_id")
        return [Action(_FOLLOW_LABEL, FOLLOW, f"{kind}:{sequel_id}" if kind and sequel_id else event_id)]
    if title_id is None:
        return []
    actions = [Action(_WATCHED_LABEL, WATCHED, title_id)] if event_type in _MOVIE_EVENTS else []
    return [*actions, Action(_CARD_LABEL, CARD, title_id)]


def card_actions(card: TitleCard) -> list[Action]:
    """Buttons under a title's card: «Посмотрел» until the movie is watched, the watched seasons of a series or an anime,
    and «Удалить» for any title."""
    delete = Action(_DELETE_LABEL, DELETE, card.id)
    if card.kind in ("series", "anime"):
        has_seasons = card.seasons is not None and (card.seasons.current or card.seasons.announced)
        return [Action(_SEASONS_LABEL, SEASONS, card.id), delete] if has_seasons else [delete]
    return [Action(_WATCHED_LABEL, WATCHED, card.id), delete] if card.status == STATUS_WANT else [delete]
