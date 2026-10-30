"""The FastAPI app, assembled: the login and the guard in front of every address, the security headers, the pages
behind (each section has a module and a router of its own, `create_web_app` only puts them together)."""

import logging
import mimetypes
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.tracker.core import Tracker
from app.web import archive, auth, card, feed, pages, posters, search, settings, title_list
from app.web.menu import OPEN_ADDRESSES, SECTIONS
from app.web.pages import WebContext

HERE = Path(__file__).resolve().parent
mimetypes.add_type("application/manifest+json", ".webmanifest")  # the installed app's file: not every system knows it
SESSION_COOKIE = "tracker_session"
SESSION_SECONDS = 30 * 24 * 60 * 60  # from the last request: every answer renews the cookie
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}
NOT_CONFIGURED = ("Вход в приложение не настроен: добавьте в файл .env строку WEB_PASSWORD=… "
                  "(не короче 8 символов) и запустите .\\start-bot.ps1")


def _is_open(path: str, *, always: bool = False) -> bool:
    """Whether the address needs no sign-in (`always`: and no configured password either), by `OPEN_ADDRESSES`.
    Everything else, even an address that does not exist, is closed — a new page needs no change here."""
    return any(
        (path.startswith(name) if name.endswith("/") else path == name) and (flag or not always)
        for name, flag in OPEN_ADDRESSES
    )


class HeadAsGet:
    """`HEAD` for every address that answers `GET`: the same code and headers, no body. Done here once and not at every
    route (FastAPI routes of `GET` do not take `HEAD`); an external monitor asks `/health` this way."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "HEAD":
            await self.app(scope, receive, send)
            return

        async def without_body(message: Message) -> None:
            if message["type"] == "http.response.body":
                message = {"type": "http.response.body", "body": b"", "more_body": message.get("more_body", False)}
            await send(message)

        await self.app({**scope, "method": "GET"}, receive, without_body)


def create_web_app(
    *,
    health: Callable[[], tuple[int, dict[str, object]]],
    password: str = "",
    secret_file: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    tracker: Tracker | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    image_sources: Sequence[str] = (),
    telegram_down: Callable[[], bool] = lambda: False,
) -> FastAPI:
    """The web app. `health` is the process's own report (`Health.report`): it reads neither the database nor the
    network, so `/health` answers even when they are slow. `password` is WEB_PASSWORD (without it, or when it is
    short, the login is closed); `secret_file` keeps the key that signs the session; `clock` times the lock after
    wrong tries (seconds). `tracker` is the one door into the core (without it the status line has no data); `now`
    is the wall clock (aware) the status line compares with. `image_sources` are the sites pictures may be loaded
    from (`posters.image_sources`); without them the page loads none. `telegram_down` tells whether the bot has no
    connection to Telegram (the line under the status line); the web knows nothing of the runtime or of aiogram."""
    # No /docs, /redoc or /openapi.json: they would describe every address to anyone who asks
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=HERE / "templates")
    configured = auth.login_configured(password)
    key = auth.load_key(secret_file) if configured else b""
    expected = auth.fingerprint(key, password) if configured else ""
    guard = auth.LoginGuard(clock)
    security_headers = {**SECURITY_HEADERS}
    if image_sources:
        security_headers["Content-Security-Policy"] += "; img-src 'self' " + " ".join(image_sources)

    def signed_in(request: Request) -> bool:
        # The cookie is signed and has a lifetime (SessionMiddleware); the fingerprint dies with the password.
        # Outside the session middleware (the foreign-origin answer) nobody is signed in
        return configured and "session" in request.scope and auth.same(request.session.get("pw"), expected)

    templates.env.globals["poster_url"] = posters.poster_url
    app.state.web = WebContext(
        templates=templates, tracker=tracker, now=now, signed_in=signed_in, sections=SECTIONS, telegram_down=telegram_down
    )

    async def message(request: Request, heading: str, text: str, status: int) -> Response:
        return await pages.message_page(request, heading, text, status)

    async def login_page(request: Request, next_address: str, error: str = "", status: int = 200) -> Response:
        return await pages.page(
            request, "login.html", status_code=status, signed_in=False, next=next_address, error=error
        )

    async def locked_page(request: Request, next_address: str, seconds: int) -> Response:
        minutes = -(-seconds // 60)
        text = f"Слишком много неверных попыток. Вход снова откроется через {minutes} мин."
        response = await login_page(request, next_address, text, status=429)
        response.headers["Retry-After"] = str(seconds)
        return response

    # Middleware: the one registered last is the outermost. Order of a request: headers and origin → session → guard.

    @app.middleware("http")
    async def guard_sign_in(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if _is_open(path, always=True):
            return await call_next(request)
        if not configured:
            return await message(request, "Вход не настроен", NOT_CONFIGURED, 503)
        if _is_open(path):
            return await call_next(request)
        if signed_in(request):
            request.session["pw"] = expected  # writing it again makes the middleware send a fresh cookie: 30 days from now
            return await call_next(request)
        if request.headers.get("hx-request") or path == "/status-line":
            return Response(status_code=401, headers={"HX-Redirect": "/login"})
        target = "/login"
        if request.method == "GET":
            address = path + (f"?{request.url.query}" if request.url.query else "")
            target += f"?next={quote(address, safe='/')}"
        return RedirectResponse(target, status_code=303)

    app.add_middleware(
        SessionMiddleware, secret_key=key.hex() if configured else "unused", session_cookie=SESSION_COOKIE,
        max_age=SESSION_SECONDS, same_site="lax", https_only=False,
    )

    @app.middleware("http")
    async def protect_requests(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        foreign = origin is not None and origin not in (f"http://{host}", f"https://{host}")
        if request.method not in SAFE_METHODS and foreign:
            response = await message(request, "Запрос отклонён", "Запрос с чужой страницы отклонён", 403)
        else:
            response = await call_next(request)
        response.headers.update(security_headers)
        if not _is_open(request.url.path):
            response.headers["Cache-Control"] = "no-store"  # after the sign-out "Back" must not show a page
        return response

    @app.get("/health")
    async def health_check() -> JSONResponse:
        status, body = health()
        return JSONResponse(body, status_code=status)

    @app.get("/login")
    async def login_form(request: Request, next: str = "/") -> Response:
        if signed_in(request):
            return RedirectResponse("/", status_code=303)
        return await login_page(request, auth.safe_next(next))

    @app.post("/login")
    async def login(request: Request, password_typed: str = Form("", alias="password"), next: str = Form("/")) -> Response:
        target = auth.safe_next(next)
        seconds = guard.locked_for()
        if seconds:
            return await locked_page(request, target, seconds)  # the password is not even looked at
        if not auth.password_matches(password_typed.strip(), password):
            left = guard.wrong()
            logging.warning("web login: wrong password (%s in a row)", guard.wrong_in_a_row)
            if left == 0:
                logging.warning("web login blocked for %s min", auth.LOCK_SECONDS // 60)
                return await locked_page(request, target, guard.locked_for())
            return await login_page(request, target, f"Неверный пароль. До блокировки осталось попыток: {left}", status=401)
        guard.right()
        logging.info("web login: ok")
        request.session.clear()
        request.session["pw"] = expected
        return RedirectResponse(target, status_code=303)

    @app.post("/logout")
    async def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/status-line")
    async def status_fragment(request: Request) -> Response:
        return pages.fragment(request, "status_line.html", **await pages.status_parts(request))

    app.include_router(card.router)
    app.include_router(feed.router)
    app.include_router(archive.router)
    app.include_router(search.router)
    app.include_router(title_list.router)
    app.include_router(settings.router)

    @app.exception_handler(404)
    async def not_found(request: Request, exc: HTTPException) -> Response:
        return await message(request, "Страница не найдена", "Такого адреса нет.", 404)

    @app.exception_handler(405)
    async def not_allowed(request: Request, exc: HTTPException) -> Response:
        # a press-only address opened from the address bar (`/logout`): the common page, and `Allow` as the framework gave it
        link = (str(request.app.url_path_for("feed")), "Открыть Ленту")
        response = await pages.message_page(
            request, "Так не открывается", "Этот адрес работает только по кнопке на странице", 405, link=link
        )
        response.headers.update(exc.headers or {})
        return response

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception) -> Response:
        # Runs in the outermost layer of Starlette, outside the middleware above: the headers are put on here. The
        # traceback goes to the log from the server, which gets the exception once this answer is sent
        try:
            response = await message(request, "Не получилось", pages.FAILED, 500)
        except Exception:
            logging.exception("web: the page of the 500 could not be built")
            response = PlainTextResponse(pages.FAILED, status_code=500)
        response.headers.update({**security_headers, "Cache-Control": "no-store"})
        return response

    app.add_middleware(HeadAsGet)  # the last one added is the outermost: a `HEAD` is a `GET` for all the layers inside

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    return app
