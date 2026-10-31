"""The feed, the main page after the sign-in: «Скоро» (what comes out in the next two weeks, by days), «Позже» (the nearest
date of the titles that have nothing in those days) and «Недавно» (the events of the last week, with «Посмотрел» and
«Следить»). The core decides what is shown and which buttons a row has (`Tracker.feed()`); the page only words it.
Every press asks the core and answers with the whole feed fresh (HTMX puts it in the place of the old one; a plain form
gets a redirect to `/`). The feed is read when the page opens: nothing refreshes it. Rules: 3.5 and 3.6 of the spec of
part 5.3."""

from collections.abc import Callable
from datetime import date, timedelta
from typing import NamedTuple

from fastapi import APIRouter, Form, Request, Response

from app.tracker.cards import format_date, format_weekday_date
from app.tracker.core import Feed, FeedDay, RecentRow, UnknownTitle, UpcomingRow
from app.tracker.kinds import KINDS
from app.web import pages
from app.web.posters import LIST_SIZE

NOTHING_SOON = "В ближайшие 14 дней ничего не выходит"
NOTHING_RECENT = "За неделю ничего не случилось"
EMPTY_LIST = "В списке пока ничего нет."

router = APIRouter()
refreshing = pages.guarded_with_refresh("feed")  # an unexpected error on the feed ends in «Обновить»


class Follow(NamedTuple):
    """«Следить» under an announced sequel, or «В списке» when the list has it already."""

    listed: str | None  # the card of the sequel
    kind: str  # what the form sends
    sequel_id: str


class Line(NamedTuple):
    """A row: the poster and the text lead to the card; the time, the button or the link are at the right."""

    address: str  # the card
    poster: str | None
    icon: str
    name: str  # «Скоро» and «Позже»: the title; empty in «Недавно» (the text of the event names it)
    text: str  # what comes out, or the first line of the message
    details: tuple[str, ...]  # the other lines of the message, smaller
    when: str  # «в 18:00» in «Скоро»; the whole date in «Позже» (or the approximate one); empty: nothing to say
    watched: str  # the address of «Посмотрел»; empty: no button
    follow: Follow | None


class Day(NamedTuple):
    label: str
    lines: list[Line]


def _soon_label(day: date, today: date) -> str:
    """«Сегодня», «Завтра», then «пт, 31 окт»."""
    if day == today:
        return "Сегодня"
    return "Завтра" if day == today + timedelta(days=1) else format_weekday_date(day)


def _recent_label(day: date, today: date) -> str:
    """«Сегодня», «Вчера», then «пт, 24 окт»."""
    if day == today:
        return "Сегодня"
    return "Вчера" if day == today - timedelta(days=1) else format_weekday_date(day)


def _card(request: Request, title_id: int) -> str:
    return str(request.app.url_path_for("card", title_id=title_id))


def _coming(request: Request, row: UpcomingRow, *, date_too: bool = False) -> Line:
    """A row of «Скоро» (the hour of an anime at the right) or of «Позже» (`date_too`: the whole date there, or the
    approximate one: «4 квартал 2026»)."""
    title = row.title
    if date_too:
        when = row.when or format_date(row.day)
    else:
        when = "" if row.at is None else f"в {row.at:%H:%M}"
    return Line(_card(request, title.id), title.poster_path, KINDS[title.kind].icon, title.name, row.text, (), when, "", None)


def _happened(request: Request, row: RecentRow) -> Line:
    title = row.title
    watched = str(request.app.url_path_for("feed_watched", title_id=title.id)) if row.watched else ""
    follow = None
    if row.follow is not None:
        offer = row.follow
        listed = None if offer.title_id is None else _card(request, offer.title_id)
        follow = Follow(listed, offer.kind.value, offer.sequel_id)
    return Line(_card(request, title.id), title.poster_path, KINDS[title.kind].icon, "", row.headline, row.details, "", watched, follow)


def _days[Row](
    days: tuple[FeedDay[Row], ...], label: Callable[[date, date], str], make: Callable[[Request, Row], Line],
    request: Request, today: date,
) -> list[Day]:
    return [Day(label(day.day, today), [make(request, row) for row in day.rows]) for day in days]


def _view(request: Request, feed: Feed, notice: str = "") -> dict[str, object]:
    """What the feed template shows, in the words of the page. Nothing in the template compares a kind or a status: the
    core has decided what each row shows and which buttons it has."""
    return {
        "feed_notice": notice,
        "empty_list": not feed.has_titles,
        "empty_text": EMPTY_LIST,
        "nothing_soon": NOTHING_SOON,
        "nothing_recent": NOTHING_RECENT,
        "soon": _days(feed.upcoming, _soon_label, _coming, request, feed.today),
        "later": [_coming(request, row, date_too=True) for row in feed.later],
        "recent": _days(feed.recent, _recent_label, _happened, request, feed.today),
        "size": LIST_SIZE,
        "search_address": str(request.app.url_path_for("search")),
        "sequels_address": str(request.app.url_path_for("feed_sequels")),
    }


async def _fresh(request: Request, notice: str = "") -> Response:
    """The feed as it is in the database now: the block `#feed`, with a line on top when something went wrong."""
    feed = await pages.tracker_of(request).feed()
    return pages.fragment(request, "feed_body.html", **_view(request, feed, notice))


async def _pressed(request: Request, notice: str) -> Response:
    """The answer to a press: the fresh feed, with `notice` on top. Without HTMX the line crosses to the page."""
    if notice and not pages.is_htmx(request):
        pages.notify(request, notice)
    return await pages.answer(request, str(request.app.url_path_for("feed")), lambda: _fresh(request, notice))


@router.get("/", name="feed")
@refreshing
async def show_feed(request: Request) -> Response:
    feed = await pages.tracker_of(request).feed()
    return await pages.page(request, "feed.html", current=str(request.app.url_path_for("feed")), **_view(request, feed))


@router.post("/feed/titles/{title_id:int}/watched", name="feed_watched")
@refreshing
async def mark_watched(request: Request, title_id: int) -> Response:
    """«Посмотрел» under an event of a film that is wanted. A film that is watched already (in another tab) changes
    nothing: the fresh feed just has no button."""
    notice = ""
    try:
        if not pages.is_id(title_id):
            raise UnknownTitle(title_id)
        await pages.tracker_of(request).mark_watched(title_id)
    except UnknownTitle:
        notice = pages.TITLE_GONE
    return await _pressed(request, notice)


@router.post("/feed/sequels", name="feed_sequels")
@refreshing
async def follow_sequel(request: Request, kind: str = Form(""), sequel_id: str = Form("")) -> Response:
    """«Следить» under an announced sequel: the sequel joins the list, and its row now says «В списке». What went wrong
    is a line on top of the fresh feed."""
    notice = await pages.try_follow_sequel(request, kind, sequel_id)
    return await _pressed(request, notice)
