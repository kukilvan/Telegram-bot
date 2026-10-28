"""How the web is laid out for the pages of part 5.2: a module and a router per page, the common answers (a page, a
fragment, the notice that crosses once, a press with and without HTMX, «the title is gone», the net under an unexpected
error), the posters and the sites pictures may come from, and the row of a title."""

import ast
import logging
import re
from pathlib import Path

import pytest
from fastapi import APIRouter, HTTPException, Request
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.core import Overview
from app.web import create_web_app, menu, pages
from app.web.posters import CARD_SIZE, LIST_SIZE, image_sources, poster_url
from web_helpers import all_routes

WEB = Path(__file__).resolve().parent.parent / "app" / "web"
PASSWORD = "correct horse battery"
SHIKIMORI = "https://shikimori.io"


class FakeTracker:
    async def overview(self):
        return Overview(3, None)


def make_app(tmp_path, **kwargs):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    return create_web_app(
        health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=FakeTracker(), **kwargs
    )


def signed_in(app):
    client = TestClient(app, follow_redirects=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


HTMX = {"HX-Request": "true"}
SENTENCE = "Этого тайтла больше нет в списке"


# ---- the pages are modules with routers; create_web_app only assembles -----------------------------

def test_the_app_module_only_assembles_the_stubs_and_the_pages_are_routers_of_their_own(tmp_path):
    app = make_app(tmp_path)

    own = {route.path for route in all_routes(app) if route.endpoint.__module__ == "app.web.app"}
    stubs = {route.path for route in all_routes(app) if route.endpoint.__module__ == "app.web.menu"}

    assert own == {"/health", "/login", "/logout", "/status-line"}  # no page in create_web_app
    assert stubs == {section.address for section in menu.SECTIONS if section.phrase is not None}


def test_the_web_modules_of_the_part_are_in_the_import_check_of_rule_10():
    names = {path.stem for path in WEB.glob("*.py")}

    assert {"app", "menu", "pages", "posters", "auth", "status_line", "server"} <= names
    for stem in ("menu", "pages", "posters"):
        for node in ast.walk(ast.parse((WEB / f"{stem}.py").read_text(encoding="utf-8"))):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", None) or node.names[0].name
                assert module.split(".")[0] not in {"sqlalchemy", "alembic"}, (stem, module)
                assert not module.startswith("app.tracker.") or module.split(".")[2] in {"core", "cards", "kinds", "models"}


def test_every_address_of_every_method_but_the_open_ones_is_closed_without_a_sign_in(tmp_path):
    app = make_app(tmp_path)
    router = APIRouter()

    @router.get("/later-page")
    async def later_get():
        return {"secret": 1}

    @router.post("/later-press")
    async def later_post():
        return {"secret": 1}

    app.include_router(router)  # a page added later needs no change in the guard
    anonymous = TestClient(app, follow_redirects=False)
    seen = 0

    for route in all_routes(app):
        if route.path in {"/health", "/login", "/logout"}:
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            response = anonymous.request(method, route.path)
            seen += 1
            assert response.status_code in (303, 401), (method, route.path)
            assert "secret" not in response.text and "Скоро будет" not in response.text, (method, route.path)
    assert seen >= 8


def test_the_stubs_come_from_the_one_list_of_sections_and_a_section_without_a_phrase_has_no_stub(tmp_path):
    app = make_app(tmp_path)

    assert [section.code for section in menu.SECTIONS] == ["feed", "list", "archive", "search", "settings"]
    for section in menu.SECTIONS:
        assert app.url_path_for(section.code) == section.address
    assert [section.code for section in menu.SECTIONS if section.phrase is None] == ["search"]  # a page of its own
    assert menu.Section._fields == ("address", "code", "label", "phrase")
    assert menu.OpenAddress._fields == ("name", "always")
    assert [(a.name, a.always) for a in menu.OPEN_ADDRESSES] == [
        ("/health", True), ("/static/", True), ("/login", False), ("/logout", False),
    ]


def test_the_archive_stub_says_where_the_viewed_and_dropped_are_meanwhile(tmp_path):
    html = signed_in(make_app(tmp_path)).get("/archive").text

    assert "Скоро будет: поиск и сортировка по оценке (часть 5.3)." in html
    assert "Пока просмотренное и брошенное — в Списке, фильтр «Просмотрено» или «Бросил»" in html


# ---- the security header and the sites of pictures ---------------------------------------------------

def policy(response):
    return {part.split()[0]: part.split()[1:] for part in response.headers["Content-Security-Policy"].split("; ")}


def test_img_src_is_self_tmdb_and_the_shikimori_of_the_setting_with_its_subdomains(tmp_path):
    app = make_app(tmp_path, image_sources=image_sources(SHIKIMORI))

    response = signed_in(app).get("/")

    assert policy(response)["img-src"] == ["'self'", "https://image.tmdb.org", "https://shikimori.io", "https://*.shikimori.io"]
    assert policy(response)["default-src"] == ["'self'"] and policy(response)["form-action"] == ["'self'"]
    hosts = re.findall(r"https?://[^\s;]+", response.headers["Content-Security-Policy"])
    assert sorted(hosts) == ["https://*.shikimori.io", "https://image.tmdb.org", "https://shikimori.io"]  # no other


@pytest.mark.parametrize("path", ["/health", "/login", "/nowhere", "/static/style.css"])
def test_the_pictures_header_is_on_every_answer(tmp_path, path):
    response = TestClient(make_app(tmp_path, image_sources=image_sources(SHIKIMORI))).get(path)

    assert "img-src 'self' https://image.tmdb.org" in response.headers["Content-Security-Policy"]


def test_another_shikimori_address_changes_the_header(tmp_path):
    app = make_app(tmp_path, image_sources=image_sources("https://shikimori.one/api/graphql"))

    assert policy(signed_in(app).get("/"))["img-src"] == [
        "'self'", "https://image.tmdb.org", "https://shikimori.one", "https://*.shikimori.one",
    ]


def test_without_sources_the_header_is_the_old_one(tmp_path):
    response = signed_in(make_app(tmp_path)).get("/")

    assert response.headers["Content-Security-Policy"] == (
        "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )


@pytest.mark.parametrize("address, expected", [
    (SHIKIMORI, ("https://image.tmdb.org", "https://shikimori.io", "https://*.shikimori.io")),
    ("  https://Shikimori.IO/  ", ("https://image.tmdb.org", "https://shikimori.io", "https://*.shikimori.io")),
    ("https://shikimori.example:8443/x", ("https://image.tmdb.org", "https://shikimori.example:8443", "https://*.shikimori.example:8443")),
    ("https://127.0.0.1:9000", ("https://image.tmdb.org", "https://127.0.0.1:9000")),  # numbers have no subdomains
    ("http://shikimori.io", ("https://image.tmdb.org",)),  # a picture needs `https`
    ("", ("https://image.tmdb.org",)),
    ("shikimori.io", ("https://image.tmdb.org",)),
    ("https://a;b.example", ("https://image.tmdb.org",)),  # nothing that could add a directive to the header
    ("https://bad host.example", ("https://image.tmdb.org",)),
    ("https://shikimori.io:port", ("https://image.tmdb.org",)),
])
def test_the_sources_of_pictures_come_from_the_start_of_the_setting(address, expected):
    assert image_sources(address) == expected


# ---- the posters --------------------------------------------------------------------------------------

@pytest.mark.parametrize("stored, size, expected", [
    ("/abc.jpg", LIST_SIZE, "https://image.tmdb.org/t/p/w92/abc.jpg"),
    ("/abc.jpg", CARD_SIZE, "https://image.tmdb.org/t/p/w342/abc.jpg"),
    ("https://shikimori.io/uploads/poster/animes/1/x.jpeg", LIST_SIZE, "https://shikimori.io/uploads/poster/animes/1/x.jpeg"),
    ("https://shikimori.io/uploads/poster/animes/1/x.jpeg", CARD_SIZE, "https://shikimori.io/uploads/poster/animes/1/x.jpeg"),
    (None, LIST_SIZE, None),
    ("", LIST_SIZE, None),
    ("   ", CARD_SIZE, None),
    ("abc.jpg", LIST_SIZE, None),
    ("http://shikimori.io/x.jpeg", LIST_SIZE, None),
    ("javascript:alert(1)", LIST_SIZE, None),
])
def test_the_address_of_a_poster(stored, size, expected):
    assert poster_url(stored, size) == expected


def test_the_sizes_are_the_two_of_tmdb():
    assert (LIST_SIZE.name, CARD_SIZE.name) == ("w92", "w342")


def render(tmp_path, source, **context):
    templates = make_app(tmp_path).state.web.templates
    return templates.env.from_string(source).render(**context)


ROW = '{% from "macros.html" import title_main %}{{ title_main(poster, size, icon, name, original, year) }}'


def row(tmp_path, **overrides):
    context = dict(poster="/abc.jpg", size=LIST_SIZE, icon="🎬", name="Дюна", original="Dune", year=2021) | overrides
    return render(tmp_path, ROW, **context)


def test_the_row_has_the_poster_in_a_frame_with_the_icon_under_the_picture(tmp_path):
    html = row(tmp_path)

    assert html.index("poster-icon") < html.index("<img")  # the icon is in the frame, the picture lies over it
    assert '<img src="https://image.tmdb.org/t/p/w92/abc.jpg" alt="" width="92" height="138" loading="lazy">' in html
    assert 'class="poster poster-small"' in html
    assert "Дюна" in html and "Dune" in html and "2021" in html and "🎬" in html


def test_the_card_poster_is_the_large_one(tmp_path):
    html = row(tmp_path, size=CARD_SIZE)

    assert 'src="https://image.tmdb.org/t/p/w342/abc.jpg"' in html and 'width="342" height="513"' in html
    assert "poster-large" in html


@pytest.mark.parametrize("stored", [None, "", "abc.jpg", "http://shikimori.io/x.jpeg"])
def test_without_a_poster_the_row_shows_the_icon_only(tmp_path, stored):
    html = row(tmp_path, poster=stored, icon="🎌")

    assert "<img" not in html and "poster-icon" in html and "🎌" in html


def test_a_shikimori_poster_is_shown_as_it_is(tmp_path):
    html = row(tmp_path, poster="https://shikimori.io/uploads/poster/animes/1/x.jpeg", icon="🎌")

    assert 'src="https://shikimori.io/uploads/poster/animes/1/x.jpeg"' in html


def test_the_original_name_and_the_year_are_left_out_when_there_is_nothing_to_say(tmp_path):
    same = row(tmp_path, original="Дюна", year=None)
    empty = row(tmp_path, original="", year=None)

    for html in (same, empty):
        assert "title-original" not in html and "title-year" not in html


def test_a_name_with_markup_and_quotes_is_text(tmp_path):
    html = row(
        tmp_path, name='<script>alert("x")</script>', original="\"><img src=x onerror=y>", year=2000,
        poster='https://shikimori.io/x" onerror="y',
    )

    assert "<script" not in html and "&lt;script&gt;" in html and "&#34;" in html
    assert html.count("<img") == 1 and ' onerror="y' not in html


# ---- the templates keep to the content security policy ------------------------------------------------

def test_no_template_has_a_script_a_style_a_handler_an_eval_expression_a_confirm_or_an_outside_address():
    templates = sorted((WEB / "templates").glob("*.html"))

    assert {path.name for path in templates} >= {"base.html", "macros.html", "failed.html", "title_gone.html"}
    for path in templates:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=\"/static/htmx\.min\.js\")", text), path.name
        assert "style=" not in text and not re.search(r"\son\w+=", text), path.name
        assert "hx-on" not in text and "js:" not in text and "hx-confirm" not in text, path.name
        assert "http://" not in text and "https://" not in text, path.name


def test_the_only_script_of_a_page_is_htmx_from_the_project(tmp_path):
    html = signed_in(make_app(tmp_path)).get("/").text

    assert re.findall(r"<script[^>]*>", html) == ['<script src="/static/htmx.min.js" defer>']


# ---- a page, a fragment, the notice -------------------------------------------------------------------

def add_test_routes(app):
    router = APIRouter()

    @router.get("/t/show")
    async def show(request: Request):
        return await pages.message_page(request, "Тест", "Текст страницы", 200)

    @router.post("/t/notice")
    async def notice(request: Request):
        pages.notify(request, request.query_params["text"])
        return pages.go(request, "/t/show")

    @router.post("/t/press")
    async def press(request: Request):
        async def make():
            return pages.fragment(request, "failed.html", text="фрагмент нажатия")

        return await pages.answer(request, "/t/show", make)

    @router.post("/t/gone")
    async def gone(request: Request):
        return await pages.title_gone(request)

    @router.post("/t/boom")
    @pages.guarded
    async def boom(request: Request):
        raise RuntimeError("the database is gone")

    @router.get("/t/page-boom")
    @pages.guarded
    async def page_boom(request: Request):
        raise RuntimeError("the core did not answer")

    @router.get("/t/http-error")
    @pages.guarded
    async def http_error(request: Request):
        raise HTTPException(status_code=404)

    @router.post("/t/fine/{number}")
    @pages.guarded
    async def fine(request: Request, number: int):
        return pages.fragment(request, "failed.html", text=f"номер {number}")

    app.include_router(router)
    return app


@pytest.fixture
def client(tmp_path):
    return signed_in(add_test_routes(make_app(tmp_path)))


def test_a_page_has_the_menu_and_the_status_line_and_a_fragment_has_neither(client):
    page = client.get("/t/show")
    fragment = client.post("/t/press", headers=HTMX)

    assert 'aria-label="Разделы"' in page.text and 'id="status-line"' in page.text and "В списке 3 тайтла" in page.text
    assert fragment.status_code == 200 and "<html" not in fragment.text and "<nav" not in fragment.text


def test_the_notice_is_shown_once_and_is_gone(client):
    assert client.post("/t/notice", params={"text": "Добавлено в список"}).status_code == 303

    first = client.get("/t/show")
    second = client.get("/t/show")

    assert '<p class="notice" role="status">Добавлено в список</p>' in first.text
    assert 'class="notice"' not in second.text


def test_the_notice_survives_the_redirect_even_when_a_fragment_is_asked_in_between(client):
    client.post("/t/notice", params={"text": "Удалено: «Дюна»"})

    client.get("/status-line")  # a fragment does not eat it
    client.post("/t/press", headers=HTMX)
    shown = client.get("/t/show")

    assert "Удалено: «Дюна»" in shown.text


def test_a_long_notice_is_cut_to_300_characters(client):
    client.post("/t/notice", params={"text": "я" * 500})

    shown = client.get("/t/show").text

    assert re.search(r'<p class="notice" role="status">(я+)</p>', shown).group(1) == "я" * 300


def test_the_notice_is_text_not_markup(client):
    client.post("/t/notice", params={"text": "<b>Дюна</b>"})

    shown = client.get("/t/show").text

    assert "&lt;b&gt;Дюна&lt;/b&gt;" in shown and "<b>Дюна" not in shown


def test_no_notice_no_line(client):
    assert 'class="notice"' not in client.get("/t/show").text


# ---- the answers to a press ---------------------------------------------------------------------------

def test_a_press_through_htmx_gets_the_fragment_and_200(client):
    response = client.post("/t/press", headers=HTMX)

    assert response.status_code == 200 and "фрагмент нажатия" in response.text and "<html" not in response.text


def test_the_same_press_without_htmx_gets_303_to_the_page(client):
    response = client.post("/t/press")

    assert response.status_code == 303 and response.headers["location"] == "/t/show"


def test_a_way_on_through_htmx_is_200_with_hx_redirect_and_without_it_303(client):
    through = client.post("/t/notice", headers=HTMX, params={"text": "ок"})
    plain = client.post("/t/notice", params={"text": "ок"})

    assert through.status_code == 200 and through.headers["HX-Redirect"] == "/t/show" and "location" not in through.headers
    assert plain.status_code == 303 and plain.headers["location"] == "/t/show" and "HX-Redirect" not in plain.headers


def test_a_title_that_is_gone_is_a_fragment_with_a_link_for_htmx_and_the_404_page_without(client):
    fragment = client.post("/t/gone", headers=HTMX)
    page = client.post("/t/gone")

    assert fragment.status_code == 200 and "<html" not in fragment.text
    assert SENTENCE in fragment.text and '<a href="/list">Открыть Список</a>' in fragment.text
    assert page.status_code == 404 and "<html" in page.text and 'aria-label="Разделы"' in page.text
    assert SENTENCE in page.text and '<a href="/list">Открыть Список</a>' in page.text


# ---- the net under an unexpected error ----------------------------------------------------------------

def test_an_unexpected_error_in_a_press_is_logged_with_the_traceback_and_told_in_a_fragment(client, caplog):
    with caplog.at_level(logging.ERROR):
        response = client.post("/t/boom", headers=HTMX)

    assert response.status_code == 200 and "Не получилось. Попробуйте ещё раз; подробности — в журнале" in response.text
    assert "<html" not in response.text
    [record] = [r for r in caplog.records if "unexpected error" in r.getMessage()]
    assert "POST /t/boom" in record.getMessage() and record.exc_info and "the database is gone" in str(record.exc_info[1])


def test_an_unexpected_error_in_a_page_is_the_common_page_with_500(client, caplog):
    with caplog.at_level(logging.ERROR):
        response = client.get("/t/page-boom")

    assert response.status_code == 500 and "Не получилось. Попробуйте ещё раз; подробности — в журнале" in response.text
    assert 'aria-label="Разделы"' in response.text and "the core did not answer" not in response.text
    assert any(r.exc_info for r in caplog.records if "unexpected error" in r.getMessage())


def test_an_unexpected_error_without_htmx_in_a_press_is_also_the_page_with_500(client):
    response = client.post("/t/boom")

    assert response.status_code == 500 and "Не получилось" in response.text and "<html" in response.text


def test_what_the_framework_answers_with_is_let_through_and_the_arguments_of_the_handler_still_work(client):
    assert client.get("/t/http-error").status_code == 404
    assert "Такого адреса нет" in client.get("/t/http-error").text
    assert "номер 7" in client.post("/t/fine/7", headers=HTMX).text
    assert client.post("/t/fine/abc", headers=HTMX).status_code == 422  # the framework checks the address as before


# ---- what stays as it was -----------------------------------------------------------------------------

def test_a_foreign_origin_press_is_still_refused_before_any_handler(client, caplog):
    response = client.post("/t/boom", headers={"Origin": "http://evil.example"})

    assert response.status_code == 403 and not [r for r in caplog.records if "unexpected" in r.getMessage()]
