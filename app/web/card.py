"""The card of a title: what is known of it, the season marks, the sequels of a watched film and the buttons. Every
press asks the core and answers with the whole card fresh (HTMX puts it in the place of the old one; a plain form gets
a redirect to the card). The buttons follow the kind and the status (table 4.3 of the spec of part 5.2)."""

import logging
from collections.abc import Awaitable, Callable
from typing import NamedTuple

from fastapi import APIRouter, Form, Request, Response

from app.tracker.cards import (
    NOT_ANNOUNCED, STATUS_LABELS, SequelsView, TitleCard, format_date, movie_date_lines, movie_line, season_row_text,
)
from app.tracker.core import SourceFailed, TitleNotFound, Tracker, UnknownKind, UnknownSeason, UnknownTitle
from app.tracker.kinds import KINDS, is_seasonal
from app.tracker.models import ARCHIVE_STATUSES, TitleKind, TitleStatus
from app.web import pages
from app.web.posters import CARD_SIZE

NOT_IN_LIST = "Этого тайтла нет в списке"
ALREADY_GONE = "Этого тайтла уже нет в списке"
SEASON_GONE = "Этого сезона больше нет — карточка обновлена"
CLOSED_NOTE = "Все вышедшие сезоны просмотрены, сериал закрыт. Чтобы вернуть его в список, снимите галочку сезона"
NO_SEQUELS = "Продолжений пока нет. Проверяю раз в неделю"

router = APIRouter()


class SeasonLine(NamedTuple):
    id: int  # the record of the season: the mark is sent with it, so a renumbered anime season keeps its mark
    text: str
    watched: bool
    can_mark: bool  # a season with nothing out has no mark
    address: str  # where the mark is sent


class SequelRow(NamedTuple):
    name: str
    when: str  # «15 декабря 2028» or «дата не объявлена»
    external_id: str  # what «Следить» sends
    card: str | None  # the card of the sequel when it is in the list already


class SequelsBlock(NamedTuple):
    """«Продолжения» of a watched film: a sentence while there are no rows, or the rows."""

    sentence: str
    rows: list[SequelRow]
    address: str  # where «Следить» is sent
    error: str  # what went wrong with the last «Следить»; empty: nothing


def _tracker(request: Request) -> Tracker:
    tracker = pages.context_of(request).tracker
    if tracker is None:
        raise RuntimeError("the web app has no tracker")
    return tracker


def _address(request: Request, name: str, **path: int) -> str:
    return str(request.app.url_path_for(name, **path))


def _kind_line(card: TitleCard) -> str:
    """«🎬 Фильм · 2026 · Драма, фантастика»."""
    kind = KINDS[card.kind]
    parts = [f"{kind.icon} {kind.label}"]
    if card.year:
        parts.append(str(card.year))
    if card.genres:
        parts.append(", ".join(card.genres))
    return " · ".join(parts)


def _sequels(request: Request, card: TitleCard, view: SequelsView, error: str) -> SequelsBlock:
    if not view.checked:  # the first look runs right after «Посмотрел»
        sentence = f"Ищу продолжения в коллекции {KINDS[card.kind].source_name} — обновите страницу через минуту"
    else:
        sentence = "" if view.lines else NO_SEQUELS
    rows = [
        SequelRow(
            line.name, format_date(line.date) if line.date else f"дата {NOT_ANNOUNCED}", line.external_id,
            None if line.title_id is None else _address(request, "card", title_id=line.title_id),
        )
        for line in view.lines
    ]
    return SequelsBlock(sentence, rows, _address(request, "card_sequels", title_id=card.id), error)


def _view(request: Request, card: TitleCard, notice: str = "", sequel_error: str = "") -> dict[str, object]:
    """What the card template shows, in the words of the page. The buttons follow the kind and the status."""
    seasonal = is_seasonal(card.kind)
    seasons = [
        SeasonLine(
            r.id, season_row_text(r, card.tz), r.watched, r.can_mark,
            _address(request, "card_season", title_id=card.id, season_id=r.id),
        )
        for r in card.season_rows
    ]
    show: dict[str, object] = {
        "card": card,
        "card_notice": notice,
        "poster_size": CARD_SIZE,
        "icon": KINDS[card.kind].icon,
        "kind_line": _kind_line(card),
        "status_label": STATUS_LABELS[card.status],
        "seasonal": seasonal,
        "seasons": seasons,
        "mark_all": any(r.can_mark and not r.watched for r in card.season_rows),
        "movies": [movie_line(m) for m in card.franchise_movies],
        "dates": [] if seasonal else movie_date_lines(card),
        "can_mark_watched": not seasonal and card.status == TitleStatus.WANT,
        "can_drop": card.status not in ARCHIVE_STATUSES,
        # a series that is «Просмотрено» comes back by taking a mark off: its marks gave it that status
        "can_restore": card.status == TitleStatus.DROPPED or (not seasonal and card.status == TitleStatus.WATCHED),
        "closed_note": CLOSED_NOTE if seasonal and card.status == TitleStatus.WATCHED else "",
        "sequels": None if card.sequels is None else _sequels(request, card, card.sequels, sequel_error),
        "address": _address(request, "card", title_id=card.id),
        "watched_address": _address(request, "card_watched", title_id=card.id),
        "dropped_address": _address(request, "card_dropped", title_id=card.id),
        "restore_address": _address(request, "card_restore", title_id=card.id),
        "released_address": _address(request, "card_released_watched", title_id=card.id),
        "delete_address": _address(request, "card_delete", title_id=card.id),
    }
    return show


async def _fresh_card(request: Request, title_id: int, notice: str = "", sequel_error: str = "") -> Response:
    """The block of the card as it is in the database now; the title may be gone meanwhile."""
    card = await _tracker(request).title_card(title_id)
    if card is None:
        return await pages.title_gone(request)
    return pages.fragment(request, "card_body.html", **_view(request, card, notice, sequel_error))


async def _press(request: Request, title_id: int, act: Callable[[Tracker], Awaitable[object]]) -> Response:
    """A press on the card: `act` asks the core. The title gone is the fragment of 1.4; a season that is gone is the
    fresh card with a line about it."""
    notice = ""
    try:
        await act(_tracker(request))
    except UnknownTitle:
        return await pages.title_gone(request)
    except UnknownSeason:
        notice = SEASON_GONE
        if not pages.is_htmx(request):
            pages.notify(request, notice)
    address = _address(request, "card", title_id=title_id)
    return await pages.answer(request, address, lambda: _fresh_card(request, title_id, notice))


@router.get("/titles/{title_id:int}", name="card")
@pages.guarded
async def show_card(request: Request, title_id: int) -> Response:
    card = await _tracker(request).title_card(title_id)
    if card is None:
        link = (_address(request, "list"), "Открыть Список")
        return await pages.message_page(request, "Тайтла нет", NOT_IN_LIST, 404, link=link)
    return await pages.page(request, "card.html", current=_address(request, "list"), **_view(request, card))


@router.post("/titles/{title_id:int}/seasons/{season_id:int}", name="card_season")
@pages.guarded
async def mark_season(request: Request, title_id: int, season_id: int, watched: str = Form("")) -> Response:
    """The check mark of a season, by the record of the season (not its number, which an anime season may lose): the
    state it is in after the press (the box is checked or not), not a switch, so a double click or a second tab gives
    what the screen shows."""
    return await _press(request, title_id, lambda tracker: tracker.set_season_watched(title_id, season_id, watched == "1"))


@router.post("/titles/{title_id:int}/released-watched", name="card_released_watched")
@pages.guarded
async def mark_all_released(request: Request, title_id: int) -> Response:
    return await _press(request, title_id, lambda tracker: tracker.mark_all_released(title_id))


@router.post("/titles/{title_id:int}/watched", name="card_watched")
@pages.guarded
async def mark_watched(request: Request, title_id: int) -> Response:
    return await _press(request, title_id, lambda tracker: tracker.mark_watched(title_id))


@router.post("/titles/{title_id:int}/dropped", name="card_dropped")
@pages.guarded
async def mark_dropped(request: Request, title_id: int) -> Response:
    return await _press(request, title_id, lambda tracker: tracker.mark_dropped(title_id))


@router.post("/titles/{title_id:int}/restore", name="card_restore")
@pages.guarded
async def restore(request: Request, title_id: int) -> Response:
    return await _press(request, title_id, lambda tracker: tracker.restore_title(title_id))


@router.post("/titles/{title_id:int}/sequels", name="card_sequels")
@pages.guarded
async def follow_sequel(request: Request, title_id: int, kind: str = Form(""), sequel_id: str = Form("")) -> Response:
    """«Следить» at a sequel of the watched film: the sequel joins the list and the owner stays on this card, where its
    row now says «В списке» (several sequels can be followed one after another). What went wrong is a line in the block."""
    error = ""
    try:
        await _tracker(request).follow_sequel_of(kind, sequel_id)
    except (UnknownKind, KeyError):  # no such kind, or one without sequels or a source
        error = pages.NO_SUCH_KIND
    except TitleNotFound:
        error = pages.not_found(TitleKind(kind))
    except SourceFailed as exc:
        logging.warning("web follow: %s failed: %r", exc, exc.__cause__)
        error = pages.unreachable(TitleKind(kind))
    if error and not pages.is_htmx(request):
        pages.notify(request, error)
    address = _address(request, "card", title_id=title_id)
    return await pages.answer(request, address, lambda: _fresh_card(request, title_id, sequel_error=error))


@router.post("/titles/{title_id:int}/delete", name="card_delete")
@pages.guarded
async def delete(request: Request, title_id: int) -> Response:
    """After the owner said «Да, удалить» on the page: on to the list, with a line about what happened."""
    try:
        result = await _tracker(request).delete_title(title_id)
    except UnknownTitle:
        pages.notify(request, ALREADY_GONE)
    else:
        pages.notify(request, f"Удалено: «{result.name}»")
    return pages.go(request, _address(request, "list"))
