"""What every page shares: the page with the menu and the status line, a fragment, the answer to a press, the notice
that crosses to the next page, «the title is gone» and the net under an unexpected error. The pages reach all of it
through `request.app.state.web` (`WebContext`), so a page module has a router of its own and needs nothing built for it."""

import functools
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException

from app.tracker.core import SourceFailed, TitleNotFound, Tracker, UnknownKind
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.web.status_line import NO_DATA, status_text

if TYPE_CHECKING:
    from app.web.menu import Section

NOTICE_KEY = "notice"
NOTICE_LIMIT = 300  # the session lives in a cookie
TITLE_GONE = "Этого тайтла больше нет в списке"
FAILED = "Не получилось. Попробуйте ещё раз; подробности — в журнале"
NO_SUCH_KIND = "Такого типа нет"
REFRESH = "Обновить"
MAX_ID_DIGITS = 12  # a longer number in an address is no title or season of ours


@dataclass(frozen=True)
class WebContext:
    """What `create_web_app` hands to the pages."""

    templates: Jinja2Templates
    tracker: Tracker | None
    now: Callable[[], datetime]  # the wall clock (aware) the status line compares with
    signed_in: Callable[[Request], bool]
    sections: "Sequence[Section]"


def report_source_failure(kind: TitleKind, exc: SourceFailed, doing: str) -> str:
    """The source of the kind did not answer: writes to the log what `doing` was and the cause, and returns the sentence
    for the owner that names the source (any cause: the exact one is in the log)."""
    logging.warning("web %s: %s failed: %r", doing, exc, exc.__cause__)
    return f"Не удалось связаться с {KINDS[kind].source_name}. Попробуйте чуть позже"


def not_found(kind: TitleKind) -> str:
    return f"{KINDS[kind].source_name} больше не знает этот тайтл. Поищите заново"


async def try_follow_sequel(request: Request, kind: str, sequel_id: str) -> str:
    """«Следить» at a sequel (the card and the feed press it): asks the core and returns the sentence of what went wrong,
    or an empty string when the sequel joined the list. A source that did not answer is written to the log."""
    try:
        await tracker_of(request).follow_sequel_of(kind, sequel_id)
    except (UnknownKind, KeyError):  # no such kind, or one without sequels or a source
        return NO_SUCH_KIND
    except TitleNotFound:
        return not_found(TitleKind(kind))
    except SourceFailed as exc:
        return report_source_failure(TitleKind(kind), exc, "follow")
    return ""


def context_of(request: Request) -> WebContext:
    return request.app.state.web


def tracker_of(request: Request) -> Tracker:
    """The core the page asks. A web app made without one has only the pages that need none."""
    tracker = context_of(request).tracker
    if tracker is None:
        raise RuntimeError("the web app has no tracker")
    return tracker


def is_id(number: int) -> bool:
    """Whether a number of an address (a title, a season) can be one of ours. A longer one is no title, and the database
    cannot be asked about it: the core is not asked, and the page says the title is gone (KI-25)."""
    return 0 <= number < 10**MAX_ID_DIGITS


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


async def status_line(request: Request) -> str:
    """The text of the status line; a database that does not answer must not take the page down."""
    web = context_of(request)
    if web.tracker is None:
        return NO_DATA
    try:
        overview = await web.tracker.overview()
    except Exception:
        logging.exception("web: no data from the database for the status line")
        return NO_DATA
    return status_text(overview.title_count, overview.last_check_at, web.now())


async def page(request: Request, name: str, *, status_code: int = 200, **context: object) -> Response:
    """A whole page. The menu, the status line and the notice belong to the pages behind the sign-in."""
    web = context_of(request)
    context.setdefault("signed_in", web.signed_in(request))
    if context["signed_in"]:
        context.setdefault("current", "")
        context["status"] = await status_line(request)
        context["sections"] = web.sections
        context["notice"] = _take_notice(request)
    return web.templates.TemplateResponse(request, name, context, status_code=status_code)


def fragment(request: Request, name: str, *, status_code: int = 200, **context: object) -> Response:
    """A piece of a page, for HTMX to put in its place."""
    return context_of(request).templates.TemplateResponse(request, name, context, status_code=status_code)


async def message_page(
    request: Request, heading: str, text: str, status_code: int, *, link: tuple[str, str] | None = None
) -> Response:
    """The common page with a heading, a sentence and, if given, a link (address, label)."""
    return await page(request, "message.html", status_code=status_code, heading=heading, text=text, link=link)


def notify(request: Request, text: str) -> None:
    """A line for the next page: shown once, then gone. It goes through the session and not the address, so a reload
    or a bookmark does not repeat it."""
    request.session[NOTICE_KEY] = text[:NOTICE_LIMIT]


def _take_notice(request: Request) -> str:
    return request.session.pop(NOTICE_KEY, "") if "session" in request.scope else ""


def go(request: Request, address: str) -> Response:
    """The way on after a press (a title added or deleted). HTMX is sent by a header, a plain form by a 303."""
    if is_htmx(request):
        return Response(status_code=200, headers={"HX-Redirect": address})
    return RedirectResponse(address, status_code=303)


async def answer(request: Request, address: str, make: Callable[[], Awaitable[Response]]) -> Response:
    """The answer to a press on a page. HTMX gets the fragment `make` builds, and a `200` even when the fragment is
    an error («the title is gone»): HTMX 2 does not show a `4xx` or `5xx`. A plain form gets a 303 back to the page."""
    if is_htmx(request):
        return await make()
    return RedirectResponse(address, status_code=303)


async def title_gone(request: Request) -> Response:
    """The title was deleted somewhere else (in the bot, in another tab) while its card stayed open."""
    link = (str(request.app.url_path_for("list")), "Открыть Список")
    if is_htmx(request):
        return fragment(request, "title_gone.html", text=TITLE_GONE, link=link)
    return await message_page(request, "Тайтла нет", TITLE_GONE, 404, link=link)


async def failed(request: Request, refresh: str | None = None) -> Response:
    """«Не получилось». With the address of the page (`refresh`) the sentence ends in a link «Обновить» to it."""
    link = None if refresh is None else (refresh, REFRESH)
    if is_htmx(request):
        return fragment(request, "failed.html", text=FAILED, link=link)
    return await message_page(request, "Не получилось", FAILED, 500, link=link)


def _under_net(
    handler: Callable[..., Awaitable[Response]], refresh: tuple[str, ...] | None
) -> Callable[..., Awaitable[Response]]:
    @functools.wraps(handler)
    async def wrapper(request: Request, *args: object, **kwargs: object) -> Response:
        try:
            return await handler(request, *args, **kwargs)
        except HTTPException:
            raise
        except Exception:
            logging.exception("web: unexpected error in %s %s", request.method, request.url.path)
            address = None
            if refresh is not None:
                name, *names = refresh
                address = str(request.app.url_path_for(name, **{n: request.path_params[n] for n in names}))
            return await failed(request, address)

    return wrapper


def guarded(handler: Callable[..., Awaitable[Response]]) -> Callable[..., Awaitable[Response]]:
    """A handler under the net: an error nobody expected goes to the log with its traceback, and the owner gets a
    sentence (a fragment for HTMX, a page with a `500` otherwise) instead of an empty place. What the framework
    itself answers with (`HTTPException`) is let through."""
    return _under_net(handler, None)


def guarded_with_refresh(route: str, *params: str) -> Callable[[Callable[..., Awaitable[Response]]], Callable[..., Awaitable[Response]]]:
    """`guarded`, and the sentence ends in «Обновить»: a link to the page of the route `route` (its address takes the
    path parameters `params` of the request, such as the number of the title)."""
    return lambda handler: _under_net(handler, (route, *params))
