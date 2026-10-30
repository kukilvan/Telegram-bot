"""KI-11: what the web answers to a request the pages did not expect — a method an address does not have (405), `HEAD`
(an external monitor asks `/health` that way) and an error nobody caught (500) — in the common page with the headers of
every other answer."""

import pytest
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.core import Overview
from app.web import create_web_app, pages

PASSWORD = "correct horse battery"
HEADERS = ("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy")


class FakeTracker:
    async def overview(self):
        return Overview(3, None)


def healthy() -> Health:
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    return health


def make_app(tmp_path, health=None):
    app = create_web_app(
        health=(health or healthy()).report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=FakeTracker()
    )
    router = APIRouter()

    @router.get("/t/uncaught")
    async def uncaught(request: Request):
        raise RuntimeError("secret detail of the failure")

    @router.get("/t/page")
    async def page(request: Request):
        return await pages.message_page(request, "Страница", "Текст страницы", 200)

    app.include_router(router)
    return app


@pytest.fixture
def app(tmp_path):
    return make_app(tmp_path)


@pytest.fixture
def client(app):
    client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


@pytest.fixture
def anonymous(app):
    return TestClient(app, follow_redirects=False, raise_server_exceptions=False)


# ---- 405 -----------------------------------------------------------------------------------------------------

def test_a_press_only_address_opened_from_the_address_bar_is_the_common_page(client):
    answer = client.get("/logout")

    assert answer.status_code == 405 and answer.headers["Allow"] == "POST"
    assert "Так не открывается" in answer.text and "Этот адрес работает только по кнопке на странице" in answer.text
    assert '<a href="/">Открыть Ленту</a>' in answer.text
    assert 'aria-label="Разделы"' in answer.text and "Method Not Allowed" not in answer.text  # the menu: the sign-in is there


def test_the_405_page_of_an_open_address_without_a_sign_in_has_no_menu(anonymous):
    answer = anonymous.get("/logout")

    assert answer.status_code == 405 and answer.headers["Allow"] == "POST"
    assert "Так не открывается" in answer.text and '<a href="/">Открыть Ленту</a>' in answer.text
    assert 'aria-label="Разделы"' not in answer.text and "Выйти" not in answer.text


@pytest.mark.parametrize("method, address, allowed", [
    ("GET", "/list/delete", "POST"), ("PUT", "/", "GET"), ("DELETE", "/list", "GET"), ("GET", "/login-nowhere", None),
])
def test_other_addresses_answer_the_same_way_with_the_allow_of_the_framework(client, method, address, allowed):
    answer = client.request(method, address)

    if allowed is None:
        assert answer.status_code == 404  # an address that does not exist stays a 404
        return
    assert answer.status_code == 405 and allowed in answer.headers["Allow"]
    assert "Так не открывается" in answer.text


def test_the_405_has_the_headers_of_every_answer(client):
    answer = client.get("/logout")

    assert all(name in answer.headers for name in HEADERS)
    assert "Cache-Control" not in answer.headers  # `/logout` is an open address, like `/login`
    assert client.get("/list/delete").headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("method, address", [("GET", "/list/delete"), ("PUT", "/"), ("GET", "/titles/1/delete")])
def test_an_address_behind_the_sign_in_asks_for_the_sign_in_before_it_speaks_of_the_method(anonymous, method, address):
    answer = anonymous.request(method, address)

    assert answer.status_code == 303 and answer.headers["location"].startswith("/login")
    assert "Так не открывается" not in answer.text


# ---- HEAD ----------------------------------------------------------------------------------------------------

def test_head_of_health_is_the_code_and_the_headers_of_get_without_a_body(anonymous):
    got = anonymous.get("/health")
    head = anonymous.head("/health")

    assert head.status_code == 200 and head.content == b""
    assert head.headers["content-type"] == got.headers["content-type"]
    assert head.headers["content-length"] == got.headers["content-length"]
    assert all(name in head.headers for name in HEADERS)


def test_head_of_health_in_trouble_is_503(tmp_path):
    health = healthy()
    health.scheduler_running = False
    sick = TestClient(make_app(tmp_path, health))

    head = sick.head("/health")

    assert head.status_code == 503 and head.content == b"" and sick.get("/health").status_code == 503


def test_head_of_a_page_without_a_sign_in_is_the_303_to_the_login(anonymous):
    head = anonymous.head("/list")

    assert head.status_code == 303 and head.headers["location"] == "/login?next=/list" and head.content == b""


def test_head_of_a_page_with_a_sign_in_is_200_without_a_body(client):
    got = client.get("/t/page")
    head = client.head("/t/page")

    assert head.status_code == 200 and head.content == b"" and got.content != b""
    assert head.headers["content-type"] == got.headers["content-type"]
    assert head.headers["Cache-Control"] == "no-store"


def test_head_of_a_static_file_is_200_without_a_body(anonymous):
    head = anonymous.head("/static/style.css")

    assert head.status_code == 200 and head.content == b"" and int(head.headers["content-length"]) > 0


def test_head_of_an_address_that_has_no_get_is_the_405_of_the_framework(client):
    head = client.head("/logout")

    assert head.status_code == 405 and head.content == b""


# ---- 500 -----------------------------------------------------------------------------------------------------

def test_an_error_nobody_caught_is_the_common_page_with_the_headers(client):
    answer = client.get("/t/uncaught")

    assert answer.status_code == 500 and "Не получилось" in answer.text and pages.FAILED in answer.text
    assert 'aria-label="Разделы"' in answer.text and "secret detail" not in answer.text
    assert answer.headers["Cache-Control"] == "no-store"
    assert answer.headers["X-Content-Type-Options"] == "nosniff"
    assert "default-src 'self'" in answer.headers["Content-Security-Policy"]
    assert answer.headers["Referrer-Policy"] == "same-origin"


def test_an_error_nobody_caught_goes_on_to_the_server_which_logs_the_traceback(app, client):
    raising = TestClient(app, follow_redirects=False)  # the test client raises what the server would log
    assert raising.post("/login", data={"password": PASSWORD}).status_code == 303

    with pytest.raises(RuntimeError, match="secret detail"):
        raising.get("/t/uncaught")


def test_when_even_the_page_of_the_500_cannot_be_built_the_answer_is_plain_text_with_the_headers(client, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("the template is gone")

    monkeypatch.setattr(pages, "message_page", broken)

    answer = client.get("/t/uncaught")

    assert answer.status_code == 500 and answer.text == pages.FAILED
    assert all(name in answer.headers for name in HEADERS) and answer.headers["Cache-Control"] == "no-store"


def test_an_error_nobody_caught_without_a_sign_in_still_asks_for_the_sign_in_first(anonymous):
    answer = anonymous.get("/t/uncaught")

    assert answer.status_code == 303 and "secret detail" not in answer.text
