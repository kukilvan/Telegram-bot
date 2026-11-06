"""The tab «Входящие»: the items the bot could not resolve, newest first, with «Найти» and «Убрать».

«Найти» is a link to the search filled with the kind and the query of the item. «Убрать» deletes the item; with HTMX the
row goes and the number of the menu follows. Adding a title in the search with `inbox=<id>` deletes the item: that is
`search`."""

from datetime import datetime, timezone, tzinfo
from typing import NamedTuple
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Response

from app.tracker.cards import format_day_month
from app.tracker.core import INBOX_REASONS, MEDIA_WORDS, InboxEntry
from app.tracker.kinds import KINDS
from app.web import pages

EMPTY = "Здесь пусто: всё, что вы присылали боту, разобрано."
NO_KIND = "тип не выбран"
MAX_LINES = 4  # a longer text is cut here, the rest is under «показать всё»
MAX_CHARS = 300

router = APIRouter()


class Row(NamedTuple):
    """An item as the page shows it."""

    id: int
    when: str  # «Сегодня, 14:20»
    kind: str  # «🎮 Игра», or «тип не выбран»
    reason: str  # «не нашёл»
    shown: str  # the text cut to 4 lines / 300 characters, or «(картинка без подписи)» for an item without text
    has_text: bool
    full: str  # the whole text when it was cut; empty otherwise
    find: str | None  # the address of the search, none for an item without text and without a kind
    post_url: str | None
    remove: str  # the address of «Убрать»


def shorten(text: str) -> tuple[str, bool]:
    """The text as the page shows it and whether it was cut: the first `MAX_LINES` lines (empty ones do not count) and
    `MAX_CHARS` characters, cut at a word with «…»."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    head = "\n".join(lines[:MAX_LINES])
    cut = len(lines) > MAX_LINES
    if len(head) > MAX_CHARS:
        inside_word = not head[MAX_CHARS].isspace() and any(c.isspace() for c in head[:MAX_CHARS])
        head = head[:MAX_CHARS].rsplit(None, 1)[0] if inside_word else head[:MAX_CHARS]
        cut = True
    return (head.rstrip() + "…", True) if cut else ("\n".join(lines), False)


def when_text(moment: datetime, tz: tzinfo | None, now: datetime) -> str:
    """The arrival (naive UTC) on the owner's clock: «Сегодня, 14:20», «Вчера, 22:41», «3 ноября, 09:12», and with the
    year in another year: «3 ноября 2025, 09:12». `now` is aware."""
    zone = tz or timezone.utc
    local = moment.replace(tzinfo=timezone.utc).astimezone(zone)
    today = now.astimezone(zone).date()
    days = (today - local.date()).days
    clock = f"{local:%H:%M}"
    if days <= 0:
        return f"Сегодня, {clock}"
    if days == 1:
        return f"Вчера, {clock}"
    year = f" {local.year}" if local.year != today.year else ""
    return f"{format_day_month(local.date())}{year}, {clock}"


def _no_text(media: str | None) -> str:
    return f"({MEDIA_WORDS.get(media or 'message', MEDIA_WORDS['message'])} без подписи)"


def _find_address(request: Request, entry: InboxEntry) -> str | None:
    if not entry.text.strip() and entry.kind is None:
        return None
    params: dict[str, object] = {}
    if entry.kind is not None:
        params["kind"] = entry.kind.value
    if entry.query:
        params["q"] = entry.query
    params["inbox"] = entry.id
    return f"{request.app.url_path_for('search')}?{urlencode(params)}"


def _row(request: Request, entry: InboxEntry, now: datetime) -> Row:
    has_text = bool(entry.text.strip())
    shown, cut = shorten(entry.text) if has_text else (_no_text(entry.media), False)
    kind = f"{KINDS[entry.kind].icon} {KINDS[entry.kind].label}" if entry.kind is not None else NO_KIND
    return Row(
        entry.id, when_text(entry.received_at, entry.tz, now), kind,
        INBOX_REASONS[entry.reason] if entry.reason is not None else "", shown, has_text,
        "\n".join(line for line in entry.text.splitlines() if line.strip()) if cut else "",
        _find_address(request, entry), entry.post_url,
        str(request.app.url_path_for("inbox_remove", item_id=entry.id)),
    )


@router.get("/inbox", name="inbox")
@pages.guarded_with_refresh("inbox")
async def show_inbox(request: Request) -> Response:
    """The page; a core that does not answer is the common «Не получилось» with a link to reload."""
    now = pages.context_of(request).now()
    rows = [_row(request, entry, now) for entry in await pages.tracker_of(request).inbox_items()]
    return await pages.page(
        request, "inbox.html", current=str(request.app.url_path_for("inbox")), rows=rows, empty=EMPTY
    )


@router.post("/inbox/{item_id}/remove", name="inbox_remove")
@pages.guarded_with_refresh("inbox")
async def remove(request: Request, item_id: int) -> Response:
    """«Убрать»: deletes the item without a question. An item gone already is the same answer. HTMX gets an empty
    place for the row and, out of band, the menu with the new number (and the empty page's sentence after the last one);
    a plain form goes back to the page."""
    tracker = pages.tracker_of(request)
    if pages.is_id(item_id):
        await tracker.forget_inbox_item(item_id)
    address = str(request.app.url_path_for("inbox"))

    async def row_gone() -> Response:
        count = await pages.inbox_count(request)
        return pages.fragment(
            request, "inbox_removed.html", oob=True, current=address, sections=pages.menu_of(request, count),
            empty=EMPTY if count == 0 else "",
        )

    return await pages.answer(request, address, row_gone)
