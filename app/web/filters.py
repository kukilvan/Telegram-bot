"""What the list and the archive share about their filters: a value read from the address, the row of links for the kind,
the sentence of an empty page and the answer with the results under the search field. What differs stays with the
pages: their own `Filters` (the fields are not the same) and their own rows of links. Rules: 6.1 of the spec of part 5.4."""

from collections.abc import Awaitable, Callable, Collection, Mapping
from enum import Enum
from typing import TypeVar

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.web import pages
from app.web.title_rows import Link

NOTHING_FITS = "Под этот фильтр ничего не подходит"
NOTHING_FOUND = "Ничего не нашлось по запросу"

Choice = TypeVar("Choice", bound=Enum)


def parse_choice(
    choices: type[Choice], raw: str, *, allowed: Collection[Choice] | None = None, default: Choice | None = None
) -> Choice | None:
    """The member of `choices` the address names. A value nobody knows, an empty one and one outside `allowed` count as
    none: `default` (nothing, if none is given)."""
    try:
        chosen = choices(raw)
    except ValueError:
        return default
    return chosen if allowed is None or chosen in allowed else default


def kind_links(current: TitleKind | None, address_of: Callable[[TitleKind | None], str]) -> list[Link]:
    """The row «Все · Фильмы · Сериалы · Аниме»; `address_of(kind)` is the address of the page with that kind chosen
    (`None`: any)."""
    links = [Link("Все", address_of(None), current is None)]
    links += [Link(KINDS[kind].plural, address_of(kind), current == kind) for kind in TitleKind]
    return links


async def empty_phrase(
    *, query: str, unfiltered: bool, anything: Callable[[], Awaitable[bool]], nothing_at_all: str
) -> str:
    """What the page says when it has no rows: nothing found by the search, nothing at all (`nothing_at_all`: no filter
    is on, or the whole page has nothing to show even without one) or nothing that fits the filter. `anything` tells
    whether the page has rows without the filter; it is asked only when a filter is on."""
    if query:
        return NOTHING_FOUND
    if unfiltered or not await anything():
        return nothing_at_all
    return NOTHING_FITS


async def results_answer(
    request: Request, template: str, page_address: str, view: Callable[[], Awaitable[Mapping[str, object]]]
) -> Response:
    """The part of the page under the search field, for the search as the letters come. Without HTMX it is the page
    (`page_address`: 303). The view holds the address of the page with this query (`address`), and it goes to the browser
    (`HX-Push-Url`), so «Назад» and a bookmark keep the query."""
    if not pages.is_htmx(request):
        return RedirectResponse(page_address, status_code=303)
    shown = await view()
    response = pages.fragment(request, template, **shown)
    response.headers["HX-Push-Url"] = str(shown["address"])
    return response
