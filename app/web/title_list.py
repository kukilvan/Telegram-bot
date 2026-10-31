"""The list: the rows with a search by name, a filter by kind and by status and an order (links, so «Назад» and bookmarks
work), the mode of choosing, in which several titles are deleted at once after a question on the page. The filters live
in the address (`kind`, `status`, `order`, and `q` for the search); a value nobody knows counts as none. The mode is
`select=1`. Rules: section 5 of the spec of part 5.2 and 5.2, 5.5 of the spec of part 5.3."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request, Response

from app.tracker.cards import STATUS_LABELS, titles_word
from app.tracker.core import ListOrder, UnknownTitle
from app.tracker.models import ARCHIVE_STATUSES, TitleKind, TitleStatus
from app.web import pages
from app.web.filters import (
    NOTHING_FOUND, empty_phrase, kind_links, linker, list_has_titles, order_choices, parse_choice, results_answer,
)
from app.web.posters import LIST_SIZE
from app.web.title_rows import Link, clean_query, rows

ALL_STATUSES = "all"  # the value of `status` for the whole list, the archive included
MAX_NAMES = 10  # the names a question or a line names; the rest is «и ещё N»
SELECT = "1"  # the value of `select`
ORDERS = (("Сначала новые", ListOrder.ADDED), ("По названию", ListOrder.NAME))  # the order of the list; the first is the default

EMPTY_LIST = "В списке пока ничего нет."
ALL_GONE = "Этих тайтлов уже нет в списке"

router = APIRouter()


@dataclass(frozen=True)
class Filters:
    """What the address asks of the list. `status` is None (no archive), `ALL_STATUSES` or the value of a status."""

    kind: TitleKind | None = None
    status: str | None = None
    order: ListOrder = ListOrder.ADDED
    query: str = ""

    @staticmethod
    def parse(kind: str = "", status: str = "", order: str = "", q: str = "") -> "Filters":
        chosen = parse_choice(TitleStatus, status)
        chosen_status = ALL_STATUSES if status == ALL_STATUSES else (None if chosen is None else chosen.value)
        # the order of the archive («По оценке», «Сначала недавние») is no order of the list: it counts as none
        chosen_order = parse_choice(ListOrder, order, allowed=order_choices(ORDERS), default=ListOrder.ADDED)
        return Filters(parse_choice(TitleKind, kind), chosen_status, chosen_order, clean_query(q))

    def statuses(self) -> frozenset[TitleStatus] | None:
        """The set the core is asked for; None: every status."""
        if self.status is None:
            return frozenset(TitleStatus) - ARCHIVE_STATUSES
        if self.status == ALL_STATUSES:
            return None
        return frozenset({TitleStatus(self.status)})

    @property
    def unfiltered(self) -> bool:
        return self.kind is None and self.status == ALL_STATUSES

    def params(self, *, with_query: bool = True) -> dict[str, str]:
        """What stands in the address: only what differs from the default."""
        shown: dict[str, str] = {}
        if self.kind is not None:
            shown["kind"] = self.kind.value
        if self.status is not None:
            shown["status"] = self.status
        if self.order != ListOrder.ADDED:
            shown["order"] = self.order.value
        if with_query and self.query:
            shown["q"] = self.query
        return shown


def _address(request: Request, filters: Filters, *, select: bool = False) -> str:
    params = filters.params()
    if select:
        params["select"] = SELECT
    base = str(request.app.url_path_for("list"))
    return f"{base}?{urlencode(params)}" if params else base


def _filter_links(request: Request, filters: Filters) -> tuple[list[Link], list[Link], list[Link]]:
    """The three rows of links. Each link is the address of the list with one thing changed; choosing leaves the mode
    of choosing (what was ticked would not fit the new rows)."""

    link = linker(lambda changed: _address(request, changed))
    kinds = kind_links(filters.kind, lambda kind: _address(request, replace(filters, kind=kind)))
    statuses = [link("Без архива", replace(filters, status=None), filters.status is None)]
    statuses += [link(STATUS_LABELS[s], replace(filters, status=s.value), filters.status == s.value) for s in TitleStatus]
    statuses.append(link("Весь список", replace(filters, status=ALL_STATUSES), filters.status == ALL_STATUSES))
    orders = [link(label, replace(filters, order=order), filters.order == order) for label, order in ORDERS]
    return kinds, statuses, orders


def _ids(raw: Sequence[str]) -> list[int]:
    """The numbers of a request, each once, in the order given; whatever is not a number of ours is left out."""
    found: list[int] = []
    for text in raw:
        text = text.strip()
        if text.isascii() and text.isdigit() and len(text) <= pages.MAX_ID_DIGITS and int(text) not in found:
            found.append(int(text))
    return found


def _quoted(names: Sequence[str], room: int | None = None) -> str:
    """«Дюна», «Пацаны» и ещё 2: up to `MAX_NAMES` names and, when a `room` (in letters) is given, as many as fit."""
    shown: list[str] = []
    used = 0
    for name in names[:MAX_NAMES]:
        if room is not None and len(name) > room - 2:
            name = name[: max(room - 3, 1)] + "…"
        piece = f"«{name}»"
        if room is not None and shown and used + len(piece) + 2 > room:
            break
        shown.append(piece)
        used += len(piece) + 2
    text = ", ".join(shown)
    rest = len(names) - len(shown)
    return f"{text} и ещё {rest}" if rest else text


def _bar(request: Request, filters: Filters, count: int, *, initial: bool = False) -> dict[str, object]:
    """The strip under the rows in the mode of choosing: the button with the number, and «Отмена»."""
    return {
        "count": count,
        "initial": initial,
        "confirm_address": str(request.app.url_path_for("list_confirm")),
        "cancel_address": _address(request, filters),
    }


async def _view(
    request: Request, filters: Filters, selecting: bool, ticked: frozenset[int] = frozenset()
) -> tuple[str, dict[str, object]]:
    """The address of the list with this query and what the page and the fragment of the results show: the links, the
    rows or the sentence that stands for them. `ticked` are the rows ticked before the search changed the rows: those
    still among the rows stay ticked."""
    tracker = pages.tracker_of(request)
    titles = await tracker.list_titles(filters.kind, filters.statuses(), filters.order, filters.query or None)
    empty = ""
    if not titles:
        empty = await empty_phrase(
            query=filters.query, unfiltered=filters.unfiltered,
            anything=lambda: list_has_titles(tracker), nothing_at_all=EMPTY_LIST,
        )
    kinds, statuses, orders = _filter_links(request, filters)
    address = _address(request, filters, select=selecting)  # the mode is kept even when this search finds nothing
    selecting = selecting and bool(titles)
    shown_ticked = frozenset(t.id for t in titles if t.id in ticked)  # a row the search took away loses its tick
    return address, {
        "kinds": kinds, "statuses": statuses, "orders": orders, "rows": rows(request, titles), "size": LIST_SIZE,
        "shown": f"Показано {len(titles)} {titles_word(len(titles))}", "empty": empty,
        "empty_is_list": empty == EMPTY_LIST, "searched": empty == NOTHING_FOUND, "query": filters.query,
        "search_address": str(request.app.url_path_for("search")),
        "reset_address": _address(request, Filters(status=ALL_STATUSES)),
        "reset_query_address": _address(request, replace(filters, query="")),
        "selecting": selecting, "select_address": _address(request, filters, select=True),
        "cancel_address": _address(request, filters),
        "selection_address": str(request.app.url_path_for("list_selection")), "hidden": filters.params(),
        "ticked": shown_ticked,
        "bar": _bar(request, filters, len(shown_ticked), initial=True),
    }


@router.get("/list", name="list")
@pages.guarded
async def show_list(
    request: Request, kind: str = "", status: str = "", order: str = "", q: str = "", select: str = ""
) -> Response:
    filters = Filters.parse(kind, status, order, q)
    selecting = select == SELECT
    _, view = await _view(request, filters, selecting)
    return await pages.page(
        request, "title_list.html", current=str(request.app.url_path_for("list")),
        results_address=str(request.app.url_path_for("list_results")), form_address=str(request.app.url_path_for("list")),
        form_hidden={**filters.params(with_query=False), **({"select": SELECT} if selecting else {})}, **view,
    )


@router.get("/list/results", name="list_results")
@pages.guarded
async def results(
    request: Request, kind: str = "", status: str = "", order: str = "", q: str = "", select: str = ""
) -> Response:
    """The part of the page under the search field, for the search as the letters come. In the mode of choosing the
    request carries the numbers of the ticked rows (`id`, only those): the ones still among the rows found stay ticked,
    and the strip counts them (KI-31)."""
    filters = Filters.parse(kind, status, order, q)
    selecting = select == SELECT
    ticked = frozenset(_ids(request.query_params.getlist("id"))) if selecting else frozenset()
    return await results_answer(
        request, "title_list_results.html", _address(request, filters, select=selecting),
        lambda: _view(request, filters, selecting, ticked),
    )


@router.get("/list/selection", name="list_selection")
@pages.guarded
async def selection(request: Request, kind: str = "", status: str = "", order: str = "", q: str = "") -> Response:
    """The strip with the number of the ticked rows (HTMX asks for it at every tick)."""
    filters = Filters.parse(kind, status, order, q)
    count = len(_ids(request.query_params.getlist("id")))
    return pages.fragment(request, "delete_bar.html", bar=_bar(request, filters, count))


@router.get("/list/confirm", name="list_confirm")
@pages.guarded
async def confirm(request: Request, kind: str = "", status: str = "", order: str = "", q: str = "") -> Response:
    """The question before deleting the ticked titles, with their names. The strip turns into it; without HTMX it is a
    page of its own."""
    filters = Filters.parse(kind, status, order, q)
    names = await _names(request, _ids(request.query_params.getlist("id")))
    if not names:  # nothing ticked, or what was ticked is gone
        if pages.is_htmx(request):
            return pages.fragment(request, "delete_bar.html", bar=_bar(request, filters, 0))
        return pages.go(request, _address(request, filters))
    count = len(names)
    question = {
        "text": f"Удалить {count} {titles_word(count)} со всеми сезонами и событиями? {_quoted(list(names.values()))}",
        "ids": list(names),
        "hidden": filters.params(),
        "delete_address": str(request.app.url_path_for("list_delete")),
        "selection_address": str(request.app.url_path_for("list_selection")),
        "back_address": _address(request, filters, select=True),
    }
    if pages.is_htmx(request):
        return pages.fragment(request, "delete_question.html", question=question)
    return await pages.page(
        request, "delete_confirm.html", current=str(request.app.url_path_for("list")), question=question
    )


async def _names(request: Request, ids: Sequence[int]) -> dict[int, str]:
    """The names of the titles of these numbers that are in the list, in the order of the numbers."""
    named = {t.id: t.name for t in await pages.tracker_of(request).list_titles()}
    return {i: named[i] for i in ids if i in named}


@router.post("/list/delete", name="list_delete")
@pages.guarded
async def delete(
    request: Request,
    ids: list[str] = Form(default=[], alias="id"),
    kind: str = Form(""),
    status: str = Form(""),
    order: str = Form(""),
    q: str = Form(""),
) -> Response:
    """«Да, удалить»: the titles asked about go one by one, as in the bot — one that is gone already is skipped, one that
    fails does not stop the others. Back to the list with the same filters and a line about what happened."""
    filters = Filters.parse(kind, status, order, q)
    asked = _ids(ids)
    tracker = pages.tracker_of(request)
    names = await _names(request, asked)
    deleted: list[str] = []
    failed: list[str] = []
    for title_id in asked:
        try:
            await tracker.delete_title(title_id)
        except UnknownTitle:
            continue
        except Exception:
            logging.exception("web list: title %s was not deleted", title_id)
            failed.append(names.get(title_id, f"№{title_id}"))
        else:
            deleted.append(names.get(title_id, f"№{title_id}"))
    if asked:
        pages.notify(request, _report(deleted, failed))
    return pages.go(request, _address(request, filters))


def _report(deleted: list[str], failed: list[str]) -> str:
    """The line the list opens with after the deleting; it must fit the notice (a cookie), so the names are cut."""
    if not deleted and not failed:
        return ALL_GONE
    parts = []
    if deleted:
        parts.append(f"Удалено: {_quoted(deleted, 120 if failed else 250)}")
    if failed:
        parts.append(f"Не удалось удалить: {_quoted(failed, 100)}. Попробуйте ещё раз")
    return ". ".join(parts)
