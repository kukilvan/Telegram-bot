"""The rows of the feed (`Tracker.feed()`): what comes out in the next days, what comes later, and what happened in the
last week. Pure functions, no database: `feed` reads what they need and hands it over.

What comes out is cut into pieces, one per thing on a day («Сезон 2, серии 5–8», «Премьера в кино»); the pieces of one
title on one day make its row, joined by «; ». A day is the source's date as it is, except for a kind whose source gives
the exact moment (`KINDS[…].local_times`, anime): there it is the day on the owner's clock, and the row gets the hour.

What happened is the log of events with the texts of the bot's messages; episodes of one season found on one day are
folded into one line by the rule of the summary (`delivery.fold`). Which buttons a row of an event has is decided here,
so the page compares neither kinds nor statuses.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any

from app.tracker import delivery
from app.tracker.actions import FOLLOW, WATCHED, event_actions
from app.tracker.cards import local_moment, name_key, season_label
from app.tracker.models import TitleKind, TitleStatus
from app.tracker.seasons import Part, Season

UPCOMING_DAYS = 14  # «Скоро»: today and the 13 days after it
RECENT_DAYS = 7  # «Недавно»: today and the 6 days before it

THEATRICAL = "Премьера в кино"
DIGITAL = "Цифровой релиз"
BOTH = "Премьера в кино и цифровой релиз"


@dataclass(frozen=True)
class FeedTitle:
    """The title a row is about: what the row shows of it and where it leads."""

    id: int
    kind: TitleKind
    name: str
    poster_path: str | None = None


@dataclass(frozen=True)
class UpcomingRow:
    """One title on one day: everything it has then, «Сезон 2, серия 8; Сезон 3 — премьера»."""

    title: FeedTitle
    day: date
    text: str
    at: time | None = None  # on the owner's clock, where the source gives the moment (anime); None: the day only


@dataclass(frozen=True)
class SequelOffer:
    """«Следить» under a sequel announcement: the sequel, and its title when the list has it already («В списке»)."""

    kind: TitleKind
    sequel_id: str
    title_id: int | None


@dataclass(frozen=True)
class RecentRow:
    """One event of the log (or several episodes folded into one), with the text of the bot's message."""

    title: FeedTitle
    headline: str  # the first line of the message
    details: tuple[str, ...]  # the other lines, smaller
    at: datetime  # when it was found, on the owner's clock (naive); a folded row: the latest of its events
    watched: bool = False  # «Посмотрел»: an event of a movie that is still «Хочу»
    follow: SequelOffer | None = None


@dataclass(frozen=True)
class FeedDay:
    day: date
    rows: tuple[Any, ...]  # `UpcomingRow` in «Скоро», `RecentRow` in «Недавно»


@dataclass(frozen=True)
class Feed:
    upcoming: tuple[FeedDay, ...]  # «Скоро»: from today on, only the days that have something
    later: tuple[UpcomingRow, ...]  # «Позже»: the nearest date of each title that has nothing in «Скоро»
    recent: tuple[FeedDay, ...]  # «Недавно»: from today back, only the days that have something
    has_titles: bool  # the list holds at least one title
    today: date  # the date on the owner's clock the days are counted from («Сегодня», «Завтра», «Вчера»)


@dataclass(frozen=True)
class Piece:
    """One thing that comes out on a day; the pieces of a title on a day make its row."""

    title: FeedTitle
    day: date
    at: time | None
    order: tuple[int, ...]  # where it stands in its row
    text: str


@dataclass(frozen=True)
class FeedEvent:
    """An event of the log as the feed reads it: with its title and the title's status now."""

    id: int
    type: str
    title: FeedTitle
    status: TitleStatus
    text: str
    data: Mapping[str, Any]
    at: datetime  # found, on the owner's clock (naive)


# --- what comes out ---------------------------------------------------------------------------------


def day_of(moment: datetime, tz: tzinfo | None) -> tuple[date, time | None]:
    """The day of a moment and its hour. Without a time zone (the source gives a day) the stored date as it is; with
    one, the owner's day and hour, unless the moment is exactly midnight UTC: the source knew only the day (KI-28)."""
    if tz is None or moment.time() == time(0):
        return moment.date(), None
    local = local_moment(moment, tz)
    return local.date(), local.time()


def _numbers(numbers: Sequence[int]) -> str:
    return f"серии {delivery.episode_ranges(numbers)}" if len(numbers) > 1 else f"серия {numbers[0]}"


def _part_text(season: int, part: Part, first_of_season: int, numbers: list[int]) -> str:
    """«Сезон 2, серия 5», «Сезон 3 — премьера, серии 1–8», «Сезон 3, часть 2 — премьера»."""
    if numbers[0] == first_of_season:
        premiere = f"{season_label(season)} — премьера"
    elif part.split and part.number > 1 and numbers[0] == min(part.numbers):
        premiere = f"{season_label(season, part.number)} — премьера"
    else:
        return f"{season_label(season)}, {_numbers(numbers)}"
    return premiere if len(numbers) == 1 else f"{premiere}, {_numbers(numbers)}"


def season_pieces(
    title: FeedTitle, seasons: Iterable[Season], gap: timedelta, tz: tzinfo | None, today: date
) -> list[Piece]:
    """The dated episodes of a series or an anime from today on: one piece per part of a season and day. The parts are
    the card's: given entries of an anime, cuts by the owner's break for a series."""
    pieces = []
    for season in seasons:
        if not season.episodes:
            continue
        first = min(e.number for e in season.episodes)
        for part in season.parts(gap):
            days: dict[date, list[tuple[int, time | None]]] = {}
            for episode in part.episodes:
                if episode.air_at is None:
                    continue
                day, at = day_of(episode.air_at, tz)
                if day >= today:
                    days.setdefault(day, []).append((episode.number, at))
            for day, episodes in days.items():
                numbers = sorted(number for number, _ in episodes)
                hours = [at for _, at in episodes if at is not None]
                text = _part_text(season.number, part, first, numbers)
                pieces.append(Piece(title, day, min(hours) if hours else None, (season.number, numbers[0]), text))
    return pieces


def movie_pieces(title: FeedTitle, theatrical: date | None, digital: date | None, today: date) -> list[Piece]:
    """The two dates of a film from today on; one piece when they fall on one day."""
    if theatrical is not None and theatrical == digital and theatrical >= today:
        return [Piece(title, theatrical, None, (0, 0), BOTH)]
    dates = ((theatrical, THEATRICAL), (digital, DIGITAL))
    return [Piece(title, day, None, (0, index), text) for index, (day, text) in enumerate(dates) if day and day >= today]


def franchise_pieces(title: FeedTitle, movies: Iterable[tuple[str, date]], today: date) -> list[Piece]:
    """The films of an anime franchise that are not out yet, by their dates from today on: «Фильм «Магическая битва 0»»."""
    return [Piece(title, day, None, (0, 0), f"Фильм «{name}»") for name, day in movies if day >= today]


def _rows(pieces: Iterable[Piece]) -> list[UpcomingRow]:
    """One row per title and day, its pieces in order."""
    grouped: dict[tuple[int, date], list[Piece]] = {}
    for piece in pieces:
        grouped.setdefault((piece.title.id, piece.day), []).append(piece)
    rows = []
    for members in grouped.values():
        members.sort(key=lambda p: p.order)
        hours = [p.at for p in members if p.at is not None]
        first = members[0]
        rows.append(UpcomingRow(first.title, first.day, "; ".join(p.text for p in members), min(hours) if hours else None))
    return rows


def _in_day(row: UpcomingRow) -> tuple[Any, ...]:
    """Rows without an hour first, by name (as «По названию» of the list), then the ones with an hour, by the hour."""
    return (row.at is not None, row.at or time(0), name_key(row.title.name), row.title.id)


def upcoming(pieces: Iterable[Piece], today: date) -> tuple[tuple[FeedDay, ...], tuple[UpcomingRow, ...]]:
    """(«Скоро», «Позже»). «Скоро» holds the days from today to today + 13 that have something; «Позже» the nearest day
    after them of each title that has nothing in «Скоро», by date, then by name."""
    last = today + timedelta(days=UPCOMING_DAYS - 1)
    rows = _rows(pieces)
    soon = [row for row in rows if row.day <= last]
    days: dict[date, list[UpcomingRow]] = {}
    for row in soon:
        days.setdefault(row.day, []).append(row)
    near = {row.title.id for row in soon}
    later: dict[int, UpcomingRow] = {}
    for row in rows:
        if row.day > last and row.title.id not in near:
            if row.title.id not in later or row.day < later[row.title.id].day:
                later[row.title.id] = row
    return (
        tuple(FeedDay(day, tuple(sorted(days[day], key=_in_day))) for day in sorted(days)),
        tuple(sorted(later.values(), key=lambda r: (r.day, name_key(r.title.name), r.title.id))),
    )


# --- what happened ----------------------------------------------------------------------------------


def sequel_of(data: Mapping[str, Any]) -> tuple[TitleKind, str] | None:
    """The sequel a «Следить» names: its kind and id in the source. None: an announcement of the old format (or one of
    a kind the core does not know), which offers no button."""
    kind, sequel_id = data.get("kind"), data.get("sequel_id")
    if not kind or not sequel_id:
        return None
    try:
        return TitleKind(kind), str(sequel_id)
    except ValueError:
        return None


def _recent_row(unit: delivery.Unit, events: Mapping[int, FeedEvent], listed: Mapping[tuple[TitleKind, str], int]) -> RecentRow:
    latest = events[unit.members[0].event_id]  # the events come latest first, and a folded unit stands at its first one
    headline, *details = unit.text.split("\n")
    watched, follow = False, None
    single = unit.single
    if single is not None:
        names = {action.name for action in event_actions(single.type, single.event_id, single.title_id, single.data)}
        watched = WATCHED in names and latest.status == TitleStatus.WANT
        sequel = sequel_of(single.data) if FOLLOW in names else None
        follow = SequelOffer(sequel[0], sequel[1], listed.get(sequel)) if sequel else None
    return RecentRow(latest.title, headline, tuple(d for d in details if d), latest.at, watched, follow)


def recent(events: Iterable[FeedEvent], today: date, listed: Mapping[tuple[TitleKind, str], int]) -> tuple[FeedDay, ...]:
    """«Недавно»: the days from today back to today − 6 that have something, the latest first; in a day the latest event
    first. Episodes of one season of a title found on one day are one row, as in the summary. `listed` gives the title
    of a sequel the list has already."""
    first = today - timedelta(days=RECENT_DAYS - 1)
    days: dict[date, list[FeedEvent]] = {}
    for event in events:
        if first <= event.at.date() <= today:
            days.setdefault(event.at.date(), []).append(event)
    result = []
    for day in sorted(days, reverse=True):
        members = sorted(days[day], key=lambda e: (e.at, e.id), reverse=True)
        by_id = {e.id: e for e in members}
        pending = [delivery.Pending(e.id, e.id, e.type, e.title.id, e.text, dict(e.data), e.at) for e in members]
        rows = tuple(_recent_row(unit, by_id, listed) for unit in delivery.fold(pending, episodes=True))
        result.append(FeedDay(day, rows))
    return tuple(result)
