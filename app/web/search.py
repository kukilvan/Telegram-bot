"""The search: the page with the switch of the kind, the suggestions as the owner types (a fragment for HTMX, or the
whole page without it), and adding a suggestion to the list, which leads to its card. The source is asked only from
the second letter on; HTMX waits for a pause in typing and drops a request that a newer one made stale."""

import logging
from typing import NamedTuple
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request, Response

from app.tracker.core import SourceFailed, SourceNotConfigured, TitleNotFound, Tracker, UnknownTitle
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.web import pages
from app.web.posters import LIST_SIZE

MIN_QUERY = 2  # a shorter query does not reach the source
MAX_QUERY = 100  # a longer one is cut
MAX_SUGGESTIONS = 10
DEFAULT_KIND = TitleKind.MOVIE  # the kind of the very first search
# a source without its keys in `.env`: only games have one (IGDB)
NOT_CONNECTED = "Игры не подключены: в файле настроек запуска (.env) нет ключей IGDB — IGDB_CLIENT_ID и IGDB_CLIENT_SECRET"
KIND_KEY = "search_kind"  # the kind of the last search, in the session

TYPE_MORE = "Наберите хотя бы две буквы"
ADDED = "Добавлено в список"
MARK_SEASONS = "Отметьте сезоны, которые уже посмотрели"
ALREADY = "Этот тайтл уже в списке"

router = APIRouter()


class Choice(NamedTuple):
    """A kind of the switch."""

    value: str
    label: str
    checked: bool


class Row(NamedTuple):
    """A suggestion as the page shows it."""

    kind: str
    external_id: str
    name: str
    original_name: str
    year: int | None
    poster: str | None
    icon: str
    card: str | None  # the card of the title when it is in the list already


def _kind_of(raw: str | None) -> TitleKind | None:
    try:
        return TitleKind(raw)
    except ValueError:
        return None


def _remembered(request: Request) -> TitleKind:
    return _kind_of(request.session.get(KIND_KEY)) or DEFAULT_KIND


def _nothing(query: str) -> str:
    return f"Ничего не нашлось по запросу «{query}». Попробуйте другое название или другой тип"


def _search_address(request: Request, kind: TitleKind, query: str = "") -> str:
    params = {"kind": kind.value, **({"q": query} if query else {})}
    return f"{request.app.url_path_for('search')}?{urlencode(params)}"


async def _found(request: Request, kind: TitleKind | None, raw_query: str) -> dict[str, object]:
    """What the place of the suggestions shows for the query: nothing, a hint, the rows, or a line about what went wrong
    (the source is named; the exact cause goes to the log)."""
    query = raw_query.strip()[:MAX_QUERY].strip()
    shown: dict[str, object] = {"query": query, "hint": "", "error": False, "rows": []}
    if kind is None:
        return {**shown, "hint": pages.NO_SUCH_KIND, "error": True}
    if not query:
        return shown
    if len(query) < MIN_QUERY:
        return {**shown, "hint": TYPE_MORE}
    try:
        suggestions = await pages.tracker_of(request).search(kind, query)
    except KeyError:  # a kind the core has no source for
        logging.warning("web search: no source for %s", kind)
        return {**shown, "hint": pages.NO_SUCH_KIND, "error": True}
    except SourceNotConfigured:  # no mistake of a press: the launch settings lack the keys
        return {**shown, "hint": NOT_CONNECTED}
    except SourceFailed as exc:
        return {**shown, "hint": pages.report_source_failure(kind, exc, "search"), "error": True}
    if not suggestions:
        return {**shown, "hint": _nothing(query)}
    rows = [
        Row(
            kind.value, s.external_id, s.name, s.original_name, s.year, s.poster_path, KINDS[kind].icon,
            None if s.title_id is None else str(request.app.url_path_for("card", title_id=s.title_id)),
        )
        for s in suggestions[:MAX_SUGGESTIONS]
    ]
    return {**shown, "rows": rows}


def _switch(chosen: TitleKind) -> list[Choice]:
    return [Choice(kind.value, KINDS[kind].label, kind == chosen) for kind in TitleKind]


def _note(kind: TitleKind | None) -> str:
    return KINDS[kind].search_note if kind is not None else ""


def _shared(request: Request) -> dict[str, object]:
    return {
        "size": LIST_SIZE,
        "add_address": str(request.app.url_path_for("add_title")),
        "suggestions_address": str(request.app.url_path_for("search_suggestions")),
    }


@router.get("/search", name="search")
@pages.guarded
async def search_page(request: Request, kind: str = "", q: str = "") -> Response:
    """The page; with `q` it comes with the suggestions already (Enter without HTMX sends the form here). `?kind=` wins
    over the remembered kind, an unknown one counts as none."""
    chosen = _kind_of(kind) or _remembered(request)
    if q.strip():
        request.session[KIND_KEY] = chosen.value
    return await pages.page(
        request, "search.html", current=str(request.app.url_path_for("search")), choices=_switch(chosen),
        note=_note(chosen), oob=False, **_shared(request), **await _found(request, chosen, q),
    )


@router.get("/search/suggestions", name="search_suggestions")
@pages.guarded
async def suggestions(request: Request, kind: str = "", q: str = "") -> Response:
    """The place of the suggestions, for HTMX; the line under the switch comes with it (out of band), since the kind may
    have changed."""
    chosen = _kind_of(kind)
    if chosen is not None:
        request.session[KIND_KEY] = chosen.value
    return pages.fragment(
        request, "suggestions.html", note=_note(chosen), oob=True, **_shared(request), **await _found(request, chosen, q)
    )


@router.post("/titles", name="add_title")
@pages.guarded
async def add(request: Request, kind: str = Form(""), external_id: str = Form(""), q: str = Form("")) -> Response:
    """«Добавить»: on to the card of the title with a line about it. What went wrong is said in the place of the button
    (without HTMX: on the search page it came from)."""
    chosen = _kind_of(kind)
    if chosen is None:
        return await _refused(request, _search_address(request, _remembered(request), q), pages.NO_SUCH_KIND)
    back = _search_address(request, chosen, q)
    tracker = pages.tracker_of(request)
    try:
        result = await tracker.add_title(chosen, external_id)
    except KeyError:  # a kind the core has no source for
        return await _refused(request, back, pages.NO_SUCH_KIND)
    except TitleNotFound:
        return await _refused(request, back, pages.not_found(chosen))
    except SourceNotConfigured:
        return await _refused(request, back, NOT_CONNECTED)
    except SourceFailed as exc:
        return await _refused(request, back, pages.report_source_failure(chosen, exc, "add"))
    pages.notify(request, await _added(tracker, result.title_id) if result.created else ALREADY)
    return pages.go(request, str(request.app.url_path_for("card", title_id=result.title_id)))


async def _added(tracker: Tracker, title_id: int) -> str:
    """«Добавлено в список», and the request to mark the seasons when the title has any that can be marked."""
    try:
        seasons = await tracker.watchable_seasons(title_id)
    except UnknownTitle:  # deleted at once somewhere else: the card will say so
        seasons = []
    return f"{ADDED}. {MARK_SEASONS}" if seasons else ADDED


async def _refused(request: Request, back: str, text: str) -> Response:
    logging.info("web add: %s", text)
    if not pages.is_htmx(request):
        pages.notify(request, text)
    return await pages.answer(request, back, lambda: _refusal(request, text))


async def _refusal(request: Request, text: str) -> Response:
    return pages.fragment(request, "failed.html", text=text)
