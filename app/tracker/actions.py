"""Buttons under a message or a card: the core decides which ones, the bot turns them into Telegram buttons.

A button with an address (`Action.url`) is a link: it opens the page itself (the game in Steam). `FOLLOW_TYPES` is the one
list of the event types that offer «Следить»: a movie sequel, an expansion, a game of the series."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.tracker import follow_ups, movie_events, price_events, sequel_events
from app.tracker.cards import TitleCard
from app.tracker.kinds import KINDS, is_seasonal
from app.tracker.models import TitleStatus
from app.tracker.platforms import steam_url

WATCHED = "watched"  # arg: title id
FOLLOW = "follow"  # arg: "<kind>:<id of the sequel in its source>" (an old button: the id of the «sequel announced» event)
SEASONS = "seasons"  # arg: title id; opens the choice of watched seasons
CARD = "card"  # arg: title id; shows the title's card (stands in for «Открыть» until there is a web app)
DELETE = "delete"  # arg: title id; asks for confirmation, then removes the title with everything that belongs to it
STEAM = "steam"  # arg: the Steam number; a link to the page of the game in Steam, never pressed through the bot

_WATCHED_LABEL = "✅ Посмотрел"
_FOLLOW_LABEL = "👀 Следить"
_SEASONS_LABEL = "📺 Просмотренные сезоны"
_CARD_LABEL = "📄 Карточка"
_DELETE_LABEL = "🗑 Удалить"
STEAM_LABEL = "🛒 Открыть в Steam"
FOLDED_STEAM_LABEL = "🛒 Steam"  # under the folded discounts, one a game: «🛒 Steam: Hades II»

# The one list of the event types with «Следить»: the movie sequel and the two announcements of a game. Every place that
# decides "has a follow button" reads it; none compares a single type.
FOLLOW_TYPES = (sequel_events.SEQUEL_ANNOUNCED, *follow_ups.TYPES)

_MOVIE_EVENTS = frozenset(
    {movie_events.DATE_ANNOUNCED, movie_events.DATE_MOVED, movie_events.RELEASED, movie_events.DIGITAL}
)


@dataclass(frozen=True)
class Action:
    label: str
    name: str  # WATCHED | FOLLOW | SEASONS | CARD | DELETE | STEAM
    arg: int | str  # «Следить» carries text: "<kind>:<id in the source>"
    url: str | None = None  # a link: the button opens this address instead of calling the bot


def steam_action(steam_id: str, label: str = STEAM_LABEL) -> Action:
    """The link to the page of the game in Steam."""
    return Action(label, STEAM, steam_id, steam_url(steam_id))


def event_actions(
    event_type: str, event_id: int, title_id: int | None, data: Mapping[str, Any] | None = None
) -> list[Action]:
    """Buttons under the message of an event. Test events have none. An announcement (`FOLLOW_TYPES`) offers «Следить»:
    a movie sequel alone (its title is the film already watched, whose card says nothing new), an expansion or a game
    of the series with «Карточка» of the checked game. The button names the announced title itself, so it works whether
    or not the announcement (or the game it came from) is still in the database; an event that does not say which
    title it is about falls back to its own number. An event of Steam has «Карточка» and «🛒 Открыть в Steam»; its
    sample, only the link."""
    if event_type in FOLLOW_TYPES:
        data = data or {}
        kind, external_id = data.get("kind"), data.get("sequel_id")  # the keys of a stored announcement keep their names
        follow = Action(_FOLLOW_LABEL, FOLLOW, f"{kind}:{external_id}" if kind and external_id else event_id)
        card = [Action(_CARD_LABEL, CARD, title_id)] if event_type in follow_ups.TYPES and title_id is not None else []
        return [follow, *card]
    if event_type in price_events.TYPES:
        # an event of Steam: the card and the page in Steam; a sample has no title, only the page
        steam_id = (data or {}).get("steam_id")
        card = [Action(_CARD_LABEL, CARD, title_id)] if title_id is not None else []
        return card + ([steam_action(str(steam_id))] if steam_id else [])
    if title_id is None:
        return []
    actions = [Action(_WATCHED_LABEL, WATCHED, title_id)] if event_type in _MOVIE_EVENTS else []
    return [*actions, Action(_CARD_LABEL, CARD, title_id)]


def card_actions(card: TitleCard) -> list[Action]:
    """Buttons under a title's card: «Посмотрел» until the movie is watched, the watched seasons of a series or an anime,
    and «Удалить» for any title; a kind whose statuses change only on the web (a game) has «Удалить» alone."""
    delete = Action(_DELETE_LABEL, DELETE, card.id)
    if KINDS[card.kind].web_only:
        return [delete]
    if is_seasonal(card.kind):
        has_seasons = card.seasons is not None and (card.seasons.current or card.seasons.announced)
        return [Action(_SEASONS_LABEL, SEASONS, card.id), delete] if has_seasons else [delete]
    return [Action(_WATCHED_LABEL, WATCHED, card.id), delete] if card.status == TitleStatus.WANT else [delete]
