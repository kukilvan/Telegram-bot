"""The archive: the titles with a final status («Просмотрено», «Бросил») with a search by name, a filter by kind, by genre
and by status, and an order (links, so «Назад» and bookmarks work). Everything lives in the address (`q`, `kind`, `genre`,
`status`, `order`); a value nobody knows counts as none. Rules: 5.2 and 5.4 of the spec of part 5.3."""

from dataclasses import dataclass, replace
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Response

from app.tracker.cards import STATUS_LABELS, titles_word
from app.tracker.core import ListOrder
from app.tracker.models import ARCHIVE_STATUSES, TitleKind, TitleStatus
from app.web import pages
from app.web.filters import (
    NOTHING_FOUND, archive_has_titles, empty_phrase, kind_links, linker, order_choices, parse_choice, results_answer,
)
from app.web.posters import LIST_SIZE
from app.web.title_rows import Link, clean_query, rows

ARCHIVE_EMPTY = "В архиве пока ничего нет. Сюда попадает просмотренное и брошенное"

ORDERS = (  # the links of the row of orders; the first one is the default
    ("По оценке", ListOrder.SCORE),
    ("Сначала недавние", ListOrder.ARCHIVED),
    ("По названию", ListOrder.NAME),
)
ARCHIVE_ORDER = [status for status in TitleStatus if status in ARCHIVE_STATUSES]  # the order of the row of statuses

router = APIRouter()


@dataclass(frozen=True)
class Filters:
    """What the address asks of the archive. `status` is None (the whole archive) or the value of an archive status."""

    query: str = ""
    kind: TitleKind | None = None
    genre: str | None = None
    status: TitleStatus | None = None
    order: ListOrder = ListOrder.SCORE

    @staticmethod
    def parse(q: str = "", kind: str = "", genre: str = "", status: str = "", order: str = "") -> "Filters":
        return Filters(
            clean_query(q), parse_choice(TitleKind, kind), genre.strip() or None,
            parse_choice(TitleStatus, status, allowed=ARCHIVE_STATUSES),
            parse_choice(ListOrder, order, allowed=order_choices(ORDERS), default=ListOrder.SCORE),
        )

    def statuses(self) -> frozenset[TitleStatus]:
        return frozenset({self.status}) if self.status is not None else ARCHIVE_STATUSES

    @property
    def unfiltered(self) -> bool:
        return self.kind is None and self.genre is None and self.status is None

    def params(self, *, with_query: bool = True) -> dict[str, str]:
        """What stands in the address: only what differs from the default."""
        shown: dict[str, str] = {}
        if with_query and self.query:
            shown["q"] = self.query
        if self.kind is not None:
            shown["kind"] = self.kind.value
        if self.genre is not None:
            shown["genre"] = self.genre
        if self.status is not None:
            shown["status"] = self.status.value
        if self.order != ListOrder.SCORE:
            shown["order"] = self.order.value
        return shown


def _address(request: Request, filters: Filters) -> str:
    params = filters.params()
    base = str(request.app.url_path_for("archive"))
    return f"{base}?{urlencode(params)}" if params else base


def _filter_links(request: Request, filters: Filters, genres: list[str]) -> tuple[list[Link], ...]:
    """The four rows of links. Each link is the address of the archive with one thing changed."""

    link = linker(lambda changed: _address(request, changed))
    kinds = kind_links(filters.kind, lambda kind: _address(request, replace(filters, kind=kind)))
    genre_links = [link("Все жанры", replace(filters, genre=None), filters.genre is None)]
    genre_links += [link(genre, replace(filters, genre=genre), filters.genre == genre) for genre in genres]
    statuses = [link("Весь архив", replace(filters, status=None), filters.status is None)]
    statuses += [link(STATUS_LABELS[s], replace(filters, status=s), filters.status == s) for s in ARCHIVE_ORDER]
    orders = [link(label, replace(filters, order=order), filters.order == order) for label, order in ORDERS]
    return kinds, genre_links, statuses, orders


async def _view(request: Request, filters: Filters) -> tuple[str, dict[str, object]]:
    """The address of the archive with this query and what the page and the fragment of the results show: the links,
    the rows or the sentence that stands for them."""
    tracker = pages.tracker_of(request)
    # the genres are those of the archive under the kind and the status, not under the search or under the genre itself
    genres = await tracker.genres(filters.kind, filters.statuses())
    if filters.genre is not None and filters.genre not in genres:
        filters = replace(filters, genre=None)  # a bookmark of a genre the archive no longer has: no filter
    titles = await tracker.list_titles(
        filters.kind, filters.statuses(), filters.order, filters.query or None, filters.genre
    )
    empty = ""
    if not titles:
        empty = await empty_phrase(
            query=filters.query, unfiltered=filters.unfiltered,
            anything=lambda: archive_has_titles(tracker), nothing_at_all=ARCHIVE_EMPTY,
        )
    kinds, genre_links, statuses, orders = _filter_links(request, filters, genres)
    return _address(request, filters), {
        "kinds": kinds, "genres": genre_links, "statuses": statuses, "orders": orders,
        "rows": rows(request, titles), "size": LIST_SIZE, "empty": empty, "query": filters.query,
        "shown": f"Показано {len(titles)} {titles_word(len(titles))}",
        "searched": empty == NOTHING_FOUND, "archive_empty": empty == ARCHIVE_EMPTY,
        "reset_address": str(request.app.url_path_for("archive")),
        "reset_query_address": _address(request, replace(filters, query="")),
    }


@router.get("/archive", name="archive")
@pages.guarded
async def show_archive(
    request: Request, q: str = "", kind: str = "", genre: str = "", status: str = "", order: str = ""
) -> Response:
    filters = Filters.parse(q, kind, genre, status, order)
    _, view = await _view(request, filters)
    return await pages.page(
        request, "archive.html", current=str(request.app.url_path_for("archive")),
        results_address=str(request.app.url_path_for("archive_results")), form_address=str(request.app.url_path_for("archive")),
        form_hidden=filters.params(with_query=False), **view,
    )


@router.get("/archive/results", name="archive_results")
@pages.guarded
async def results(
    request: Request, q: str = "", kind: str = "", genre: str = "", status: str = "", order: str = ""
) -> Response:
    """The part of the page under the search field, for the search as the letters come. The address of the page with
    this query goes to the browser (`HX-Push-Url`), so «Назад» and a bookmark keep it."""
    filters = Filters.parse(q, kind, genre, status, order)
    return await results_answer(
        request, "archive_results.html", _address(request, filters), lambda: _view(request, filters)
    )
