"""The FastAPI app: the login and the guard in front of every address, the security headers, the pages behind."""

import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.tracker.core import Tracker
from app.web import auth
from app.web.status_line import NO_DATA, status_text

HERE = Path(__file__).resolve().parent
SESSION_COOKIE = "tracker_session"
SESSION_SECONDS = 30 * 24 * 60 * 60  # from the last request: every answer renews the cookie
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}
# The menu: address, the name in code (from CONTEXT.md; it names the route), the label and the one phrase of the
# placeholder until the section is built
SECTIONS = (
    ("/", "feed", "Лента", "Скоро будет: что выходит в ближайшие дни и что вышло недавно (часть 5.3)"),
    ("/list", "list", "Список", "Скоро будет: все тайтлы с фильтрами по типу и статусу (часть 5.2)"),
    ("/archive", "archive", "Архив", "Скоро будет: просмотренное с поиском и сортировкой по оценке (часть 5.3)"),
    ("/search", "search", "Поиск", "Скоро будет: поиск с подсказками и добавление (часть 5.2)"),
    ("/settings", "settings", "Настройки", "Скоро будет: часовой пояс, рабочие дни, час сводки, тихие часы (часть 5.4)"),
)
# The one list of the addresses that need no sign-in. A name ending in "/" is a folder (everything under it). The flag:
# open even when no password is set (the service ones: Docker and the styles are needed always); `/login` and
# `/logout` are not — without a password they say "sign-in is not configured"
OPEN_ADDRESSES = (
    ("/health", True),
    ("/static/", True),
    ("/login", False),
    ("/logout", False),
)
NOT_CONFIGURED = ("Вход в приложение не настроен: добавьте в файл .env строку WEB_PASSWORD=… "
                  "(не короче 8 символов) и запустите .\\start-bot.ps1")


def _is_open(path: str, *, always: bool = False) -> bool:
    """Whether the address needs no sign-in (`always`: and no configured password either), by `OPEN_ADDRESSES`.
    Everything else, even an address that does not exist, is closed — a new page needs no change here."""
    return any(
        (path.startswith(name) if name.endswith("/") else path == name) and (flag or not always)
        for name, flag in OPEN_ADDRESSES
    )


def create_web_app(
    *,
    health: Callable[[], tuple[int, dict[str, object]]],
    password: str = "",
    secret_file: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
    tracker: Tracker | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> FastAPI:
    """The web app. `health` is the process's own report (`Health.report`): it reads neither the database nor the
    network, so `/health` answers even when they are slow. `password` is WEB_PASSWORD (without it, or when it is
    short, the login is closed); `secret_file` keeps the key that signs the session; `clock` times the lock after
    wrong tries (seconds). `tracker` is the one door into the core (without it the status line has no data); `now`
    is the wall clock (aware) the status line compares with."""
    # No /docs, /redoc or /openapi.json: they would describe every address to anyone who asks
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=HERE / "templates")
    configured = auth.login_configured(password)
    key = auth.load_key(secret_file) if configured else b""
    expected = auth.fingerprint(key, password) if configured else ""
    guard = auth.LoginGuard(clock)

    def signed_in(request: Request) -> bool:
        # The cookie is signed and has a lifetime (SessionMiddleware); the fingerprint dies with the password.
        # Outside the session middleware (the foreign-origin answer) nobody is signed in
        return configured and "session" in request.scope and auth.same(request.session.get("pw"), expected)

    async def status_line() -> str:
        """The text of the status line; a database that does not answer must not take the page down."""
        if tracker is None:
            return NO_DATA
        try:
            overview = await tracker.overview()
        except Exception:
            logging.exception("web: no data from the database for the status line")
            return NO_DATA
        return status_text(overview.title_count, overview.last_check_at, now())

    async def page(request: Request, name: str, *, status: int = 200, **context: object) -> Response:
        context.setdefault("signed_in", signed_in(request))
        if context["signed_in"]:  # the menu and the status line belong to the pages behind the sign-in
            context.setdefault("current", "")
            context["status"] = await status_line()
            context["sections"] = SECTIONS
        return templates.TemplateResponse(request, name, context, status_code=status)

    async def message(request: Request, heading: str, text: str, status: int) -> Response:
        return await page(request, "message.html", status=status, heading=heading, text=text)

    async def login_page(request: Request, next_address: str, error: str = "", status: int = 200) -> Response:
        return await page(request, "login.html", status=status, signed_in=False, next=next_address, error=error)

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
        response.headers.update(SECURITY_HEADERS)
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
        return templates.TemplateResponse(request, "status_line.html", {"status": await status_line()})

    def add_section(address: str, code: str, label: str, phrase: str) -> None:
        @app.get(address, name=code)
        async def section(request: Request) -> Response:
            return await page(request, "section.html", current=address, heading=label, phrase=phrase)

    for address, code, label, phrase in SECTIONS:
        add_section(address, code, label, phrase)

    @app.exception_handler(404)
    async def not_found(request: Request, exc: HTTPException) -> Response:
        return await message(request, "Страница не найдена", "Такого адреса нет.", 404)

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    return app
