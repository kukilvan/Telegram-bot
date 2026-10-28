"""The list: the rows with a filter by kind and by status and an order (links, so «Назад» and bookmarks work), the mode
of choosing, in which several titles are deleted at once after a question on the page. The filters live in the address
(`kind`, `status`, `order`); a value nobody knows counts as none. The mode is `select=1`. Rules: section 5 of the spec of
part 5.2."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import NamedTuple
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request, Response

from app.tracker.cards import STATUS_LABELS, titles_word
from app.tracker.core import ListOrder, Tracker, UnknownTitle
from app.tracker.kinds import KINDS
from app.tracker.models import ARCHIVE_STATUSES, TitleKind, TitleStatus
from app.web import pages
from app.web.posters import LIST_SIZE

ALL_STATUSES = "all"  # the value of `status` for the whole list, the archive included
MAX_NAMES = 10  # the names a question or a line names; the rest is «и ещё N»
MAX_ID_DIGITS = 12  # a longer number is no title of ours
SELECT = "1"  # the value of `select`

EMPTY_LIST = "В списке пока ничего нет."
NOTHING_FITS = "Под этот фильтр ничего не подходит"
ALL_GONE = "Этих тайтлов уже нет в списке"

router = APIRouter()


@dataclass(frozen=True)
class Filters:
    """What the address asks of the list. `status` is None (no archive), `ALL_STATUSES` or the value of a status."""

    kind: TitleKind | None = None
    status: str | None = None
    order: ListOrder = ListOrder.ADDED

    @staticmethod
    def parse(kind: str = "", status: str = "", order: str = "") -> "Filters":
        try:
            chosen_kind = TitleKind(kind) if kind else None
        except ValueError:
            chosen_kind = None
        try:
            chosen_status = TitleStatus(status).value if status != ALL_STATUSES else ALL_STATUSES
        except ValueError:
            chosen_status = None
        try:
            chosen_order = ListOrder(order) if order else ListOrder.ADDED
        except ValueError:
            chosen_order = ListOrder.ADDED
        return Filters(chosen_kind, chosen_status, chosen_order)

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

    def params(self) -> dict[str, str]:
        """What stands in the address: only what differs from the default."""
        shown: dict[str, str] = {}
        if self.kind is not None:
            shown["kind"] = self.kind.value
        if self.status is not None:
            shown["status"] = self.status
        if self.order != ListOrder.ADDED:
            shown["order"] = self.order.value
        return shown


class Link(NamedTuple):
    label: str
    address: str
    current: bool


class Row(NamedTuple):
    address: str  # the card
    id: int
    poster: str | None
    icon: str
    name: str
    year: int | None
    status: str  # the label


def _tracker(request: Request) -> Tracker:
    tracker = pages.context_of(request).tracker
    if tracker is None:
        raise RuntimeError("the web app has no tracker")
    return tracker


def _address(request: Request, filters: Filters, *, select: bool = False) -> str:
    params = filters.params()
    if select:
        params["select"] = SELECT
    base = str(request.app.url_path_for("list"))
    return f"{base}?{urlencode(params)}" if params else base


def _rows(request: Request, titles: Sequence) -> list[Row]:
    return [
        Row(
            str(request.app.url_path_for("card", title_id=t.id)), t.id, t.poster_path, KINDS[t.kind].icon, t.name, t.year,
            STATUS_LABELS[t.status],
        )
        for t in titles
    ]


def _filter_links(request: Request, filters: Filters) -> tuple[list[Link], list[Link], list[Link]]:
    """The three rows of links. Each link is the address of the list with one thing changed; choosing leaves the mode
    of choosing (what was ticked would not fit the new rows)."""

    def link(label: str, changed: Filters, current: bool) -> Link:
        return Link(label, _address(request, changed), current)

    kinds = [link("Все", replace(filters, kind=None), filters.kind is None)]
    kinds += [link(KINDS[k].plural, replace(filters, kind=k), filters.kind == k) for k in TitleKind]
    statuses = [link("Без архива", replace(filters, status=None), filters.status is None)]
    statuses += [link(STATUS_LABELS[s], replace(filters, status=s.value), filters.status == s.value) for s in TitleStatus]
    statuses.append(link("Весь список", replace(filters, status=ALL_STATUSES), filters.status == ALL_STATUSES))
    orders = [
        link("Сначала новые", replace(filters, order=ListOrder.ADDED), filters.order == ListOrder.ADDED),
        link("По названию", replace(filters, order=ListOrder.NAME), filters.order == ListOrder.NAME),
    ]
    return kinds, statuses, orders


def _ids(raw: Sequence[str]) -> list[int]:
    """The numbers of a request, each once, in the order given; whatever is not a number of ours is left out."""
    found: list[int] = []
    for text in raw:
        text = text.strip()
        if text.isascii() and text.isdigit() and len(text) <= MAX_ID_DIGITS and int(text) not in found:
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


@router.get("/list", name="list")
@pages.guarded
async def show_list(request: Request, kind: str = "", status: str = "", order: str = "", select: str = "") -> Response:
    filters = Filters.parse(kind, status, order)
    tracker = _tracker(request)
    titles = await tracker.list_titles(filters.kind, filters.statuses(), filters.order)
    empty = ""
    if not titles:
        # nothing under the filter, and an empty list is a different sentence from a filter nothing fits
        empty = NOTHING_FITS if not filters.unfiltered and await tracker.list_titles() else EMPTY_LIST
    kinds, statuses, orders = _filter_links(request, filters)
    selecting = select == SELECT and bool(titles)
    return await pages.page(
        request, "title_list.html", current=str(request.app.url_path_for("list")),
        kinds=kinds, statuses=statuses, orders=orders, rows=_rows(request, titles), size=LIST_SIZE,
        shown=f"Показано {len(titles)} {titles_word(len(titles))}", empty=empty,
        empty_is_list=empty == EMPTY_LIST, search_address=str(request.app.url_path_for("search")),
        reset_address=_address(request, Filters(status=ALL_STATUSES)),
        selecting=selecting, select_address=_address(request, filters, select=True), cancel_address=_address(request, filters),
        selection_address=str(request.app.url_path_for("list_selection")), hidden=filters.params(),
        bar=_bar(request, filters, 0, initial=True),
    )


@router.get("/list/selection", name="list_selection")
@pages.guarded
async def selection(request: Request, kind: str = "", status: str = "", order: str = "") -> Response:
    """The strip with the number of the ticked rows (HTMX asks for it at every tick)."""
    filters = Filters.parse(kind, status, order)
    count = len(_ids(request.query_params.getlist("id")))
    return pages.fragment(request, "delete_bar.html", bar=_bar(request, filters, count))


@router.get("/list/confirm", name="list_confirm")
@pages.guarded
async def confirm(request: Request, kind: str = "", status: str = "", order: str = "") -> Response:
    """The question before deleting the ticked titles, with their names. The strip turns into it; without HTMX it is a
    page of its own."""
    filters = Filters.parse(kind, status, order)
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
    named = {t.id: t.name for t in await _tracker(request).list_titles()}
    return {i: named[i] for i in ids if i in named}


@router.post("/list/delete", name="list_delete")
@pages.guarded
async def delete(
    request: Request,
    ids: list[str] = Form(default=[], alias="id"),
    kind: str = Form(""),
    status: str = Form(""),
    order: str = Form(""),
) -> Response:
    """«Да, удалить»: the titles asked about go one by one, as in the bot — one that is gone already is skipped, one that
    fails does not stop the others. Back to the list with the same filters and a line about what happened."""
    filters = Filters.parse(kind, status, order)
    asked = _ids(ids)
    tracker = _tracker(request)
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
