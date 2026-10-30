"""The web login: the guard in front of every address, the password, the session, the lock after wrong tries, the
protection of requests and the headers."""

import logging
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.runtime import Health
from app.web import create_web_app
from app.web.auth import LOCK_SECONDS, load_key, safe_next

PASSWORD = "correct horse battery"
WRONG = "not the password"
OPEN_ADDRESSES = ["/login", "/logout", "/health", "/static/style.css"]  # the one list of what needs no sign-in
TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "web" / "templates"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def secret_file(tmp_path):
    return tmp_path / "data" / "web_secret"


def make_app(secret_file, clock, password=PASSWORD):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    return create_web_app(health=health.report, password=password, secret_file=secret_file, clock=clock)


@pytest.fixture
def client(secret_file, clock):
    return TestClient(make_app(secret_file, clock), follow_redirects=False)


def sign_in(client, next_address="/"):
    response = client.post("/login", data={"password": PASSWORD, "next": next_address})
    assert response.status_code == 303
    return response


# ---- the guard ------------------------------------------------------------

@pytest.mark.parametrize("address", ["/", "/list", "/archive", "/search", "/settings", "/nowhere", "/a/b"])
def test_every_closed_address_sends_a_visitor_to_the_login(client, address):
    response = client.get(address)

    assert response.status_code == 303
    assert response.headers["location"] == f"/login?next={address}"


def test_the_status_line_without_sign_in_is_401_with_the_redirect_header_even_for_a_plain_request(client):
    response = client.get("/status-line")

    assert response.status_code == 401 and response.headers["HX-Redirect"] == "/login"


def test_the_address_to_come_back_to_keeps_the_query(client):
    assert client.get("/list?kind=anime").headers["location"] == "/login?next=/list%3Fkind%3Danime"


def test_an_htmx_request_gets_401_and_a_redirect_header_instead_of_a_page(client):
    response = client.get("/status-line", headers={"HX-Request": "true"})

    assert response.status_code == 401 and response.headers["HX-Redirect"] == "/login"
    assert "location" not in response.headers


def test_a_post_without_sign_in_goes_to_the_login_without_a_way_back(client):
    response = client.post("/anything")

    assert response.status_code == 303 and response.headers["location"] == "/login"


def test_the_open_addresses_are_exactly_the_pinned_list(client):
    assert client.get("/login").status_code == 200
    assert client.post("/logout").status_code == 303
    assert client.get("/health").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    # Everything else is closed, nothing else is open: pages that exist and ones that do not
    for address in ["/", "/list", "/login/", "/health/", "/static", "/logout/x", "/docs", "/redoc", "/openapi.json"]:
        assert client.get(address).status_code == 303, address


def test_the_signed_in_see_the_stub_and_404_for_other_addresses(client):
    sign_in(client)

    feed = client.get("/settings")
    missing = client.get("/nowhere")

    assert feed.status_code == 200 and "Лента" in feed.text and "Выйти" in feed.text
    assert missing.status_code == 404 and "Страница не найдена" in missing.text


def test_the_api_docs_are_off_for_the_signed_in_too(client):
    sign_in(client)

    assert [client.get(a).status_code for a in ("/docs", "/redoc", "/openapi.json")] == [404, 404, 404]


# ---- the form and `next` --------------------------------------------------

def test_the_form_has_the_password_field_and_no_value_to_leak(client):
    response = client.get("/login")

    html = response.text
    assert 'name="password"' in html and 'type="password"' in html
    assert 'autocomplete="current-password"' in html and "autofocus" in html and "Войти" in html
    assert "Выйти" not in html  # no menu, no sign-out on the login page


def test_the_right_password_goes_to_next(client):
    response = client.post("/login", data={"password": PASSWORD, "next": "/list"})

    assert response.status_code == 303 and response.headers["location"] == "/list"


@pytest.mark.parametrize("foreign", [
    "//evil.example", "https://evil.example/x", "/\\evil.example", "evil", "", "/a\\b", "/x\r\nSet-Cookie: a=b", "/" + "a" * 200,
])
def test_a_foreign_next_goes_home(client, foreign):
    response = client.post("/login", data={"password": PASSWORD, "next": foreign})

    assert response.status_code == 303 and response.headers["location"] == "/"


def test_safe_next_keeps_only_own_addresses():
    assert safe_next("/list?kind=anime") == "/list?kind=anime"
    assert safe_next("/" + "a" * 199) == "/" + "a" * 199
    assert safe_next(None) == "/"


def test_the_form_carries_a_safe_next_only(client):
    assert 'value="/list"' in client.get("/login?next=/list").text
    assert 'value="/"' in client.get("/login?next=//evil.example").text


def test_the_signed_in_visiting_the_login_go_home(client):
    sign_in(client)

    response = client.get("/login")

    assert response.status_code == 303 and response.headers["location"] == "/"


def test_spaces_around_the_typed_password_do_not_count(client):
    assert client.post("/login", data={"password": f"  {PASSWORD} "}).status_code == 303


def test_a_very_long_input_is_wrong_without_being_compared(client):
    response = client.post("/login", data={"password": "a" * 1025})

    assert response.status_code == 401 and "Неверный пароль" in response.text


# ---- wrong tries and the lock ---------------------------------------------

def test_a_wrong_password_says_how_many_tries_are_left_and_does_not_return_the_input(client):
    response = client.post("/login", data={"password": WRONG})

    assert response.status_code == 401
    assert "Неверный пароль. До блокировки осталось попыток: 4" in response.text
    assert WRONG not in response.text
    assert client.get("/").status_code == 303


def test_the_fifth_wrong_try_in_a_row_locks_the_login_for_15_minutes(client, clock):
    for left in (4, 3, 2, 1):
        assert f"осталось попыток: {left}" in client.post("/login", data={"password": WRONG}).text

    fifth = client.post("/login", data={"password": WRONG})

    assert fifth.status_code == 429 and fifth.headers["Retry-After"] == str(LOCK_SECONDS)
    assert "Слишком много неверных попыток. Вход снова откроется через 15 мин." in fifth.text
    right = client.post("/login", data={"password": PASSWORD})  # the right one is not looked at while locked
    assert right.status_code == 429 and "set-cookie" not in right.headers
    clock.now += 60
    later = client.post("/login", data={"password": PASSWORD})
    assert later.status_code == 429 and later.headers["Retry-After"] == str(LOCK_SECONDS - 60)
    assert "через 14 мин." in later.text  # the lock is not extended by the tries, only counted down


def test_minutes_of_the_lock_are_rounded_up(client, clock):
    for _ in range(5):
        client.post("/login", data={"password": WRONG})
    clock.now += LOCK_SECONDS - 1

    assert "через 1 мин." in client.post("/login", data={"password": PASSWORD}).text


def test_after_the_lock_ends_the_login_works_and_the_count_starts_anew(client, clock):
    for _ in range(5):
        client.post("/login", data={"password": WRONG})
    clock.now += LOCK_SECONDS

    assert "осталось попыток: 4" in client.post("/login", data={"password": WRONG}).text
    clock.now += 1
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303


def test_the_right_password_resets_the_count(client):
    for _ in range(4):
        client.post("/login", data={"password": WRONG})
    sign_in(client)
    client.post("/logout")

    assert "осталось попыток: 4" in client.post("/login", data={"password": WRONG}).text


def test_the_lock_does_not_touch_who_is_signed_in(client):
    sign_in(client)
    for _ in range(5):
        client.post("/login", data={"password": WRONG})

    assert client.get("/settings").status_code == 200


def test_the_log_tells_the_tries_without_the_password(client, clock, caplog):
    with caplog.at_level(logging.INFO):
        for _ in range(5):
            client.post("/login", data={"password": WRONG})
        clock.now += LOCK_SECONDS
        sign_in(client)

    assert "web login: wrong password (1 in a row)" in caplog.text
    assert "web login blocked for 15 min" in caplog.text
    assert WRONG not in caplog.text and PASSWORD not in caplog.text


def test_a_sign_in_is_logged(secret_file, clock, caplog):
    client = TestClient(make_app(secret_file, clock), follow_redirects=False)

    with caplog.at_level(logging.INFO):
        sign_in(client)

    assert "web login: ok" in caplog.text and PASSWORD not in caplog.text


# ---- the session ----------------------------------------------------------

def test_the_cookie_is_http_only_lax_and_lives_30_days(client):
    cookie = sign_in(client).headers["set-cookie"]

    assert cookie.startswith("tracker_session=")
    assert "httponly" in cookie.lower() and "samesite=lax" in cookie.lower() and "path=/" in cookie.lower()
    assert "max-age=2592000" in cookie.lower() and "secure" not in cookie.lower()


def test_every_answer_renews_the_cookie(client):
    sign_in(client)

    assert "max-age=2592000" in client.get("/settings").headers["set-cookie"].lower()


def test_the_session_survives_a_new_client_and_a_new_app_with_the_same_key_file(secret_file, clock):
    first = TestClient(make_app(secret_file, clock), follow_redirects=False)
    sign_in(first)
    cookie = first.cookies["tracker_session"]

    second = TestClient(make_app(secret_file, clock), follow_redirects=False)  # the app restarted, the file stayed
    second.cookies.set("tracker_session", cookie)

    assert second.get("/settings").status_code == 200


def test_the_key_file_is_made_once_with_owner_only_rights(secret_file, clock):
    make_app(secret_file, clock)
    key = secret_file.read_bytes()
    make_app(secret_file, clock)

    assert len(key) == 32 and secret_file.read_bytes() == key
    if hasattr(secret_file, "stat") and Path("/").anchor == "/":  # POSIX rights only mean something off Windows
        assert secret_file.stat().st_mode & 0o777 == 0o600


def test_without_a_key_file_to_read_or_make_the_key_lives_in_memory_and_the_log_warns(tmp_path, clock, caplog):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the folder should be")
    with caplog.at_level(logging.WARNING):
        client = TestClient(make_app(blocker / "web_secret", clock), follow_redirects=False)

    assert "ключ сессий" in caplog.text
    sign_in(client)
    assert client.get("/settings").status_code == 200


def test_a_broken_key_file_is_not_overwritten(secret_file, clock, caplog):
    secret_file.parent.mkdir(parents=True)
    secret_file.write_bytes(b"short")

    with caplog.at_level(logging.WARNING):
        key = load_key(secret_file)

    assert len(key) == 32 and secret_file.read_bytes() == b"short" and "повреждён" in caplog.text


def test_another_password_throws_everybody_out(secret_file, clock):
    old = TestClient(make_app(secret_file, clock), follow_redirects=False)
    sign_in(old)
    cookie = old.cookies["tracker_session"]

    new = TestClient(make_app(secret_file, clock, password="another password"), follow_redirects=False)
    new.cookies.set("tracker_session", cookie)

    assert new.get("/").status_code == 303


def test_a_spoiled_cookie_is_the_same_as_none(client):
    sign_in(client)
    client.cookies.set("tracker_session", client.cookies["tracker_session"][:-3] + "abc")

    assert client.get("/").status_code == 303


def test_a_cookie_from_another_key_is_not_accepted(tmp_path, clock):
    mine = TestClient(make_app(tmp_path / "one", clock), follow_redirects=False)
    sign_in(mine)
    other = TestClient(make_app(tmp_path / "two", clock), follow_redirects=False)
    other.cookies.set("tracker_session", mine.cookies["tracker_session"])

    assert other.get("/").status_code == 303


def test_a_cookie_older_than_30_days_is_not_accepted(secret_file, clock, monkeypatch):
    import time as time_module
    client = TestClient(make_app(secret_file, clock), follow_redirects=False)
    real = time_module.time()
    sign_in(client)
    assert client.get("/settings").status_code == 200

    monkeypatch.setattr(time_module, "time", lambda: real + 30 * 24 * 3600 + 60)

    assert client.get("/").status_code == 303


def test_the_sign_out_clears_the_session(client):
    sign_in(client)

    response = client.post("/logout")

    assert response.status_code == 303 and response.headers["location"] == "/login"
    assert client.get("/").status_code == 303


# ---- no password ----------------------------------------------------------

@pytest.mark.parametrize("password", ["", "short", "1234567", "   "])
def test_without_a_proper_password_the_login_is_closed_with_503(secret_file, clock, password):
    client = TestClient(make_app(secret_file, clock, password=password.strip()), follow_redirects=False)

    for response in (client.get("/"), client.get("/login"), client.get("/list"), client.post("/login", data={"password": password})):
        assert response.status_code == 503
        assert "Вход в приложение не настроен" in response.text and "WEB_PASSWORD" in response.text
    assert client.get("/health").status_code == 200 and client.get("/static/style.css").status_code == 200
    assert not secret_file.exists()  # no login, no key


def test_eight_characters_are_enough(secret_file, clock):
    client = TestClient(make_app(secret_file, clock, password="12345678"), follow_redirects=False)

    assert client.get("/login").status_code == 200


def test_the_password_setting_is_blank_by_default_and_trimmed(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:dummy-token-for-tests")
    monkeypatch.setenv("TMDB_API_KEY", "dummy")
    monkeypatch.delenv("WEB_PASSWORD", raising=False)
    assert Settings(_env_file=None).web_password == ""

    monkeypatch.setenv("WEB_PASSWORD", "  secret phrase ")
    assert Settings(_env_file=None).web_password == "secret phrase"


# ---- protection of requests and headers -----------------------------------

def test_a_post_from_a_foreign_origin_is_refused(client):
    sign_in(client)

    for origin in ("https://evil.example", "http://testserver.evil.example", "null", "http://evil.example"):
        response = client.post("/logout", headers={"Origin": origin})
        assert response.status_code == 403 and "Запрос с чужой страницы отклонён" in response.text, origin
    assert client.get("/settings").status_code == 200  # nothing was signed out


def test_a_foreign_origin_cannot_even_try_passwords(client):
    response = client.post("/login", data={"password": PASSWORD}, headers={"Origin": "https://evil.example"})

    assert response.status_code == 403 and "set-cookie" not in response.headers


def test_own_origin_and_none_pass(client):
    assert client.post("/login", data={"password": PASSWORD}, headers={"Origin": "http://testserver"}).status_code == 303
    assert client.post("/logout", headers={"Origin": "https://testserver"}).status_code == 303
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303


def test_the_origin_is_compared_with_the_host_of_the_request(client):
    response = client.post("/login", data={"password": PASSWORD}, headers={"Host": "localhost:8081", "Origin": "http://localhost:8081"})

    assert response.status_code == 303


def test_a_get_with_a_foreign_origin_is_not_refused(client):
    assert client.get("/login", headers={"Origin": "https://evil.example"}).status_code == 200


def test_security_headers_are_on_every_answer(client):
    sign_in(client)
    answers = [client.get(a) for a in ("/", "/nowhere", "/login", "/health", "/static/style.css")]
    answers.append(client.post("/logout", headers={"Origin": "https://evil.example"}))
    answers.append(TestClient(client.app).get("/list"))  # refused as a visitor

    for response in answers:
        assert response.headers["Content-Security-Policy"] == (
            "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Referrer-Policy"] == "same-origin"


def test_pages_behind_the_login_are_not_cached(client):
    sign_in(client)

    assert client.get("/settings").headers["Cache-Control"] == "no-store"
    assert client.get("/nowhere").headers["Cache-Control"] == "no-store"
    assert "cache-control" not in client.get("/health").headers
    assert "cache-control" not in client.get("/static/style.css").headers


def test_the_password_never_reaches_the_log(client, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post("/login", data={"password": WRONG})
        sign_in(client)
        client.post("/logout")

    assert WRONG not in caplog.text and PASSWORD not in caplog.text


# ---- templates ------------------------------------------------------------

def test_templates_have_no_inline_scripts_styles_or_handlers():
    templates = list(TEMPLATES.glob("*.html"))

    assert templates
    for template in templates:
        text = template.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=)", text), template.name
        assert "style=" not in text and not re.search(r"\son\w+=", text), template.name
        assert "http://" not in text and "https://" not in text, template.name


def test_the_stylesheet_has_no_outside_addresses():
    css = (Path(__file__).resolve().parent.parent / "app" / "web" / "static" / "style.css").read_text(encoding="utf-8")

    assert "http" not in css and "@import" not in css


# ---- the one list of open addresses ---------------------------------------

def test_the_guard_and_the_no_store_header_take_the_open_addresses_from_one_place(secret_file, clock, monkeypatch):
    from app.web import app as web_app

    app = make_app(secret_file, clock)

    @app.get("/future-page")
    async def future():
        return {"ok": 1}

    client = TestClient(app, follow_redirects=False)
    assert client.get("/future-page").status_code == 303  # closed until the one list says otherwise
    assert client.get("/future-page").headers.get("cache-control") == "no-store"

    monkeypatch.setattr(web_app, "OPEN_ADDRESSES", (*web_app.OPEN_ADDRESSES, ("/future-page", False)))

    opened = client.get("/future-page")
    assert opened.status_code == 200 and "cache-control" not in opened.headers  # the guard and the header agree


def test_without_a_password_only_the_service_addresses_are_open(secret_file, clock):
    client = TestClient(make_app(secret_file, clock, password=""), follow_redirects=False)

    assert client.get("/health").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    for response in (client.get("/login"), client.post("/logout"), client.get("/settings"), client.get("/nowhere")):
        assert response.status_code == 503 and "Вход не настроен" in response.text


def test_a_signed_in_visit_to_the_login_does_not_renew_the_session(client):
    sign_in(client)

    response = client.get("/login")

    assert response.status_code == 303 and response.headers["location"] == "/"
    assert "set-cookie" not in response.headers  # nothing to renew there: the visit only sends the owner on


def test_the_sections_are_named_in_code_by_the_glossary(secret_file, clock):
    app = make_app(secret_file, clock)

    assert app.url_path_for("feed") == "/"
    for name in ("list", "archive", "search", "settings"):
        assert app.url_path_for(name) == f"/{name}"
    names = {route.name for route in app.routes if getattr(route, "methods", None)}
    assert not [name for name in names if re.search("[А-Яа-я]", name)]


def test_the_glossary_names_the_search_and_settings_screens():
    glossary = (Path(__file__).resolve().parent.parent / "CONTEXT.md").read_text(encoding="utf-8")

    assert "**Поиск**:" in glossary and "В коде: `search`." in glossary
    assert "**Настройки**:" in glossary and "В коде: `settings`." in glossary
    assert "В коде: `feed`" in glossary and "`feed` (в коде пока нет)" not in glossary
