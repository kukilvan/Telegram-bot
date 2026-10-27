"""The FastAPI app: the login and the guard in front of every address, the security headers, the pages behind."""

import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.web import auth

HERE = Path(__file__).resolve().parent
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


def _is_open(path: str) -> bool:
    """The addresses that need no sign-in. The one list: everything else, even an address that does not exist, is
    closed — a new page needs no change here."""
    return path in ("/login", "/logout", "/health") or path.startswith("/static/")


def create_web_app(
    *,
    health: Callable[[], tuple[int, dict[str, object]]],
    password: str = "",
    secret_file: Path | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    """The web app. `health` is the process's own report (`Health.report`): it reads neither the database nor the
    network, so `/health` answers even when they are slow. `password` is WEB_PASSWORD (without it, or when it is
    short, the login is closed); `secret_file` keeps the key that signs the session; `clock` times the lock after
    wrong tries (seconds)."""
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

    def page(request: Request, name: str, *, status: int = 200, **context: object) -> Response:
        context.setdefault("signed_in", signed_in(request))
        return templates.TemplateResponse(request, name, context, status_code=status)

    def message(request: Request, heading: str, text: str, status: int) -> Response:
        return page(request, "message.html", status=status, heading=heading, text=text)

    def login_page(request: Request, next_address: str, error: str = "", status: int = 200) -> Response:
        return page(request, "login.html", status=status, next=next_address, error=error)

    def locked_page(request: Request, next_address: str, seconds: int) -> Response:
        minutes = -(-seconds // 60)
        text = f"Слишком много неверных попыток. Вход снова откроется через {minutes} мин."
        response = login_page(request, next_address, text, status=429)
        response.headers["Retry-After"] = str(seconds)
        return response

    # Middleware: the one registered last is the outermost. Order of a request: headers and origin → session → guard.

    @app.middleware("http")
    async def guard_sign_in(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if path == "/health" or path.startswith("/static/"):
            return await call_next(request)
        if not configured:
            return message(request, "Вход не настроен", NOT_CONFIGURED, 503)
        if signed_in(request):
            request.session["pw"] = expected  # writing it again makes the middleware send a fresh cookie: 30 days from now
            return await call_next(request)
        if path in ("/login", "/logout"):
            return await call_next(request)
        if request.headers.get("hx-request"):
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
            response = message(request, "Запрос отклонён", "Запрос с чужой страницы отклонён", 403)
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
        return login_page(request, auth.safe_next(next))

    @app.post("/login")
    async def login(request: Request, password_typed: str = Form("", alias="password"), next: str = Form("/")) -> Response:
        target = auth.safe_next(next)
        seconds = guard.locked_for()
        if seconds:
            return locked_page(request, target, seconds)  # the password is not even looked at
        if not auth.password_matches(password_typed.strip(), password):
            left = guard.wrong()
            logging.warning("web login: wrong password (%s in a row)", guard.wrong_in_a_row)
            if left == 0:
                logging.warning("web login blocked for %s min", auth.LOCK_SECONDS // 60)
                return locked_page(request, target, guard.locked_for())
            return login_page(request, target, f"Неверный пароль. До блокировки осталось попыток: {left}", status=401)
        guard.right()
        logging.info("web login: ok")
        request.session.clear()
        request.session["pw"] = expected
        return RedirectResponse(target, status_code=303)

    @app.post("/logout")
    async def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/login", status_code=303)

    @app.get("/")
    async def feed(request: Request) -> Response:
        return page(request, "feed.html")

    @app.exception_handler(404)
    async def not_found(request: Request, exc: HTTPException) -> Response:
        return message(request, "Страница не найдена", "Такого адреса нет.", 404)

    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    return app
