"""The follow-up check of a game (pure): its stored state, which expansions and games of its series are shown, their dates, what is new and the events.

Pure: no database, no network, no clock. «Мои платформы», the country of the stores and today on the owner's clock come
as arguments (spec 4 of stage 6.3), so a change of the settings reads the stored snapshot again without a request and
gives no messages. The snapshot keeps every follow-up whatever its platforms and dates; what is shown is decided here
each time it is read. The reference point (the first check: the stored state is `{}`) only records what is shown.
"""

from collections.abc import Collection, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.tracker import text
from app.tracker.games import NOT_ANNOUNCED, GameDate, GameState, PlatformDates, Release, platform_dates
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.tracker.movie_events import DetectedEvent
from app.tracker.platforms import Platform
from app.tracker.sources.dates import parse_date

_ICON = KINDS[TitleKind.GAME].icon

EXPANSION_ANNOUNCED = "game_expansion_announced"
SEQUEL_ANNOUNCED = "game_sequel_announced"
TYPES = (EXPANSION_ANNOUNCED, SEQUEL_ANNOUNCED)  # the one list of the types of the follow-up check

EARLY_ACCESS_NOTE = " (ранний доступ)"


# --- the stored state -----------------------------------------------------------------------------------------------


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"not the text of {what}: {value!r}")
    return value


@dataclass(frozen=True)
class FollowUp:
    """An expansion or a game of the series as IGDB listed it: its IGDB id, its name (the Russian one when IGDB has
    it), the day of its `first_release_date`, its platforms and release records as `GameState` holds them;
    `standalone` — an expansion played alone (IGDB type 4)."""

    id: str
    name: str
    first: date | None = None
    platforms: tuple[int, ...] = ()
    releases: tuple[Release, ...] = ()
    standalone: bool = False

    @property
    def game(self) -> GameState:
        """Its platforms and dates, read by the rules of `games` (backward compatibility, regions, cancellation)."""
        return GameState(platforms=self.platforms, releases=self.releases)

    def state(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "first": self.first.isoformat() if self.first else None,
            "platforms": list(self.platforms), "releases": [release.state() for release in self.releases],
            "standalone": self.standalone,
        }

    @classmethod
    def from_state(cls, data: Mapping[str, Any]) -> "FollowUp":
        """Strict (rule 9): what the tracker stored; garbage raises ValueError."""
        standalone = data["standalone"]
        if not isinstance(standalone, bool):
            raise ValueError(f"not a mark of a standalone expansion: {standalone!r}")
        return cls(
            id=_text(data["id"], "an IGDB id"),
            name=_text(data["name"], "a name"),
            first=parse_date(data["first"]),
            platforms=tuple(int(number) for number in data["platforms"]),
            releases=tuple(Release.from_state(release) for release in data["releases"]),
            standalone=standalone,
        )


@dataclass(frozen=True)
class FollowUpsSnapshot:
    """What IGDB says now about a game (spec 3.2): the day of its `first_release_date`, the names of its collections,
    its expansions and the games of its series (each once, without the game itself and without its expansions)."""

    own_date: date | None = None
    collections: tuple[str, ...] = ()
    expansions: tuple[FollowUp, ...] = ()
    games: tuple[FollowUp, ...] = ()

    def state(self) -> dict[str, Any]:
        return {
            "own_date": self.own_date.isoformat() if self.own_date else None,
            "collections": list(self.collections),
            "expansions": [follow_up.state() for follow_up in self.expansions],
            "games": [follow_up.state() for follow_up in self.games],
        }

    @classmethod
    def from_state(cls, data: Mapping[str, Any]) -> "FollowUpsSnapshot":
        return cls(
            own_date=parse_date(data["own_date"]),
            collections=tuple(_text(name, "a collection") for name in data["collections"]),
            expansions=tuple(FollowUp.from_state(follow_up) for follow_up in data["expansions"]),
            games=tuple(FollowUp.from_state(follow_up) for follow_up in data["games"]),
        )


@dataclass(frozen=True)
class FollowUps:
    """The stored state of the check (snapshot of source `igdb_follow_ups`): the last snapshot and `known` — the ids
    ever shown by this game's check. No snapshot: not checked yet (stored as `{}`), the next check is the reference
    point."""

    snapshot: FollowUpsSnapshot | None = None
    known: frozenset[str] = field(default_factory=frozenset)

    @property
    def checked(self) -> bool:
        return self.snapshot is not None

    def state(self) -> dict[str, Any]:
        if self.snapshot is None:
            return {}
        return {**self.snapshot.state(), "known": sorted(self.known, key=_id_order)}

    @classmethod
    def from_state(cls, data: Any) -> "FollowUps":
        """Strict (rule 9): `{}` is «not checked yet»; a missing key, a wrong type or garbage raises ValueError."""
        if not isinstance(data, Mapping):
            raise ValueError(f"not the state of a follow-up check: {data!r}")
        if not data:
            return NOT_CHECKED
        try:
            known = data["known"]
            if not isinstance(known, list):
                raise ValueError(f"not a list of known ids: {known!r}")
            return cls(FollowUpsSnapshot.from_state(data), frozenset(_text(id_, "an IGDB id") for id_ in known))
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(f"a spoiled state of a follow-up check: {error!r}") from error


NOT_CHECKED = FollowUps()


def _id_order(id_: str) -> tuple[int, str]:
    """IGDB ids as numbers: «900» before «13166»."""
    return (len(id_), id_)


# --- what is shown (spec 4) -----------------------------------------------------------------------------------------


def _dates_on_mine(follow_up: FollowUp, mine: Collection[Platform], country: str) -> Iterator[PlatformDates]:
    """The dates of the follow-up on each platform of «Мои платформы» it is on (backward compatibility included) and
    not cancelled there."""
    for platform in mine:
        dates = platform_dates(follow_up.game, platform, country)
        if dates is not None and not dates.cancelled:
            yield dates


def on_my_platforms(follow_up: FollowUp, mine: Collection[Platform], country: str) -> bool:
    """On a platform of «Мои платформы» and not cancelled there (spec 4.1)."""
    return next(_dates_on_mine(follow_up, mine, country), None) is not None


def came_out_before(follow_up: FollowUp, own_date: date | None, today: date) -> bool:
    """Came out before the game (spec 4.3): on its day or earlier; when the game is not out, by today. A follow-up
    without `first` never did. A year-only date compares as IGDB stores it, its 31 December."""
    if follow_up.first is None:
        return False
    return follow_up.first <= (own_date if own_date is not None else today)


@dataclass(frozen=True)
class FollowUpDate:
    """What «Выход:» says of a follow-up (spec 4.4): a date, and whether it is the early access."""

    date: GameDate = NOT_ANNOUNCED
    early: bool = False

    @property
    def label(self) -> str:
        """«21 июня 2024», «2027», «6 мая 2024 (ранний доступ)», «дата не объявлена»."""
        return self.date.label + (EARLY_ACCESS_NOTE if self.early else "")


def _ends_first(game_date: GameDate) -> tuple[date, bool]:
    """The date that ends earlier first (KI-39: a day of 2027 is earlier than «2027»); on a tie the exact one."""
    return (game_date.end, not game_date.exact)


def follow_up_date(follow_up: FollowUp, mine: Collection[Platform], country: str) -> FollowUpDate:
    """The announced full release on «Мои платформы» that ends earliest; else such an early access; else «дата не
    объявлена». Cancelled platforms give nothing."""
    full: list[GameDate] = []
    early: list[GameDate] = []
    for dates in _dates_on_mine(follow_up, mine, country):
        if dates.full is not None and dates.full.date.announced:
            full.append(dates.full.date)
        if dates.early is not None and dates.early.date.announced:
            early.append(dates.early.date)
    if full:
        return FollowUpDate(min(full, key=_ends_first))
    if early:
        return FollowUpDate(min(early, key=_ends_first), early=True)
    return FollowUpDate()


def _ordered(items: Iterable[FollowUp], mine: Collection[Platform], country: str) -> list[FollowUp]:
    """By the date that ends earlier, «дата не объявлена» last; equal dates by name, then by id (spec 4.5)."""

    def order(follow_up: FollowUp) -> tuple[Any, ...]:
        end = follow_up_date(follow_up, mine, country).date.end
        return (end is None, end or date.max, text.key(follow_up.name), _id_order(follow_up.id))

    return sorted(items, key=order)


def expansions_shown(snapshot: FollowUpsSnapshot, mine: Collection[Platform], country: str) -> list[FollowUp]:
    """The expansions on my platforms, and the ones announced without any platform or release record (spec 4.2)."""
    return _ordered(
        (
            follow_up for follow_up in snapshot.expansions
            if on_my_platforms(follow_up, mine, country) or (not follow_up.platforms and not follow_up.releases)
        ),
        mine,
        country,
    )


def sequels_shown(
    snapshot: FollowUpsSnapshot, mine: Collection[Platform], country: str, today: date
) -> list[FollowUp]:
    """The games of the series on my platforms that did not come out before the game (spec 4.3)."""
    return _ordered(
        (
            follow_up for follow_up in snapshot.games
            if on_my_platforms(follow_up, mine, country) and not came_out_before(follow_up, snapshot.own_date, today)
        ),
        mine,
        country,
    )


def _shown_ids(snapshot: FollowUpsSnapshot, mine: Collection[Platform], country: str, today: date) -> set[str]:
    shown = expansions_shown(snapshot, mine, country) + sequels_shown(snapshot, mine, country, today)
    return {follow_up.id for follow_up in shown}


# --- texts (spec 6.2, 6.3) ------------------------------------------------------------------------------------------


def expansion_text(name: str, game: str, when: FollowUpDate) -> str:
    return f"{_ICON} Анонсировано дополнение: {name}\nДополнение к игре «{game}»\nВыход: {when.label}"


def sequel_text(name: str, game: str, when: FollowUpDate) -> str:
    return f"{_ICON} Анонсирована новая игра серии: {name}\nПродолжение игры «{game}»\nВыход: {when.label}"


def follow_up_key(igdb_id: str) -> str:
    """One key per announced game, whichever game of the list found it, for both types (spec 5.5)."""
    return f"game:follow_up:{igdb_id}"


def _event(event_type: str, follow_up: FollowUp, game: str, when: FollowUpDate) -> DetectedEvent:
    message = expansion_text if event_type == EXPANSION_ANNOUNCED else sequel_text
    # the keys of the movie sequel announcement: the Feed, the summary and «Следить» read them (spec 6.3)
    data = {
        "kind": TitleKind.GAME.value, "sequel_id": follow_up.id, "sequel_title": follow_up.name, "date": when.date.text,
    }
    return DetectedEvent(event_type, follow_up_key(follow_up.id), message(follow_up.name, game, when), data)


# --- what is new (spec 5.4) -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    """The state to store and the events to queue (expansions first, each list in the order of 4.5)."""

    state: FollowUps
    events: tuple[DetectedEvent, ...] = ()


def check(
    previous: FollowUps,
    now: FollowUpsSnapshot,
    game: str,
    mine: Collection[Platform],
    country: str,
    today: date,
    listed: Collection[str] = (),
) -> CheckResult:
    """What the new snapshot `now` of the game named `game` (in the list) brings after the stored state `previous`.

    The reference point gives no events and fills `known`. Otherwise a follow-up shown now is announced when its id is
    not in `known`, the previous snapshot read with today's settings and date did not show it, and it is not in the
    list (`listed`: the IGDB ids of the games of the list). The new `known` adds every id shown now."""
    expansions = expansions_shown(now, mine, country)
    sequels = sequels_shown(now, mine, country, today)
    shown = {follow_up.id for follow_up in expansions + sequels}
    state = FollowUps(now, previous.known | shown)
    if previous.snapshot is None:
        return CheckResult(state)
    seen = previous.known | _shown_ids(previous.snapshot, mine, country, today) | set(listed)
    events = [
        _event(event_type, follow_up, game, follow_up_date(follow_up, mine, country))
        for event_type, items in ((EXPANSION_ANNOUNCED, expansions), (SEQUEL_ANNOUNCED, sequels))
        for follow_up in items
        if follow_up.id not in seen
    ]
    return CheckResult(state, tuple(events))


# --- «Тестовое событие» (spec 6.6) ----------------------------------------------------------------------------------

_SAMPLE_GAME = "Ведьмак 3: Дикая охота"

# (id, menu label, message text) of the sample events: text only, no buttons (`test_samples` registers them after those of
# the games)
TEST_SAMPLES: list[tuple[str, str, str]] = [
    (
        "game-expansion",
        "Игра: анонсировано дополнение",
        expansion_text("Ведьмак 3: Дикая Охота — Баллады прошлого", _SAMPLE_GAME, FollowUpDate(GameDate(year=2027))),
    ),
    (
        "game-sequel",
        "Игра: новая игра серии",
        sequel_text("The Witcher IV", _SAMPLE_GAME, FollowUpDate(GameDate(year=2028))),
    ),
]
