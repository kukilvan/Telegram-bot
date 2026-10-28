"""The web skeleton: the menu and the five stub pages, the status line fed by `Tracker.overview()`, HTMX, and the rule
that a page reaches the core only through the facade (coding standard 10)."""

import ast
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.cards import format_past_moment, titles_word
from app.tracker.core import Overview, Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import SourceSnapshot, Title, TitleKind, TitleStatus
from app.web import create_web_app
from app.web.status_line import NO_DATA, status_text
from web_helpers import all_routes

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "app" / "web"
PASSWORD = "correct horse battery"
OPEN_ADDRESSES = {"/login", "/logout", "/health"}  # plus /static/…: the pinned list of what needs no sign-in
MENU = [("/", "Лента"), ("/list", "Список"), ("/archive", "Архив"), ("/search", "Поиск"), ("/settings", "Настройки")]
STUBS = [(address, name) for address, name in MENU if address != "/search"]  # the search is a page of its own
MOSCOW = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 27, 15, 30, tzinfo=MOSCOW)


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeTracker:
    """The one door the pages use: only `overview`."""

    def __init__(self, overview=None, error=None):
        self.value = overview
        self.error = error
        self.calls = 0

    async def overview(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.value


def make_client(tracker, tmp_path, now=lambda: NOW):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    app = create_web_app(
        health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker, now=now,
    )
    client = TestClient(app, follow_redirects=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


@pytest.fixture
def run():
    return asyncio.run


@pytest.fixture
def client(tmp_path):
    return make_client(FakeTracker(Overview(12, NOW.replace(hour=14, minute=5))), tmp_path)


# ---- the pages ------------------------------------------------------------

@pytest.mark.parametrize("address, name", STUBS)
def test_every_stub_is_a_page_with_the_menu_and_the_current_section_marked(client, address, name):
    response = client.get(address)

    html = response.text
    assert response.status_code == 200 and f"<h1>{name}</h1>" in html and "Скоро будет" in html
    assert '<html lang="ru">' in html and 'name="viewport"' in html and "Трекер релизов" in html
    for other_address, other_name in MENU:
        assert f'<a href="{other_address}"' in html and other_name in html
    assert html.count('aria-current="page"') == 1
    assert f'<a href="{address}" aria-current="page">{name}</a>' in html
    assert 'action="/logout"' in html and "Выйти" in html


def test_each_stub_says_its_own_phrase(client):
    phrases = {address: client.get(address).text for address, _ in STUBS}

    assert "что выходит в ближайшие дни" in phrases["/"] and "(часть 5.3)" in phrases["/"]
    assert "фильтрами по типу и статусу" in phrases["/list"] and "(часть 5.2)" in phrases["/list"]
    assert "сортировка по оценке" in phrases["/archive"] and "(часть 5.3)" in phrases["/archive"]
    assert "фильтр «Просмотрено» или «Бросил»" in phrases["/archive"]  # until the Archive is built: where to look
    assert "час сводки, тихие часы" in phrases["/settings"] and "(часть 5.4)" in phrases["/settings"]


def test_the_page_not_found_is_in_the_common_template_with_no_section_marked(client):
    response = client.get("/nowhere")

    assert response.status_code == 404 and "Страница не найдена" in response.text
    assert "aria-current" not in response.text and "Выйти" in response.text and 'id="status-line"' in response.text


def test_the_login_page_has_no_menu_and_no_status_line(tmp_path):
    anonymous = TestClient(
        create_web_app(health=Health().report, password=PASSWORD, secret_file=tmp_path / "s", tracker=FakeTracker(Overview(1, None))),
        follow_redirects=False,
    )

    html = anonymous.get("/login").text

    assert "<nav" not in html and "status-line" not in html and "Выйти" not in html


def test_a_failed_login_page_of_the_signed_in_has_no_menu_either(client):
    html = client.post("/login", data={"password": "wrong password"}).text

    assert "Неверный пароль" in html and "<nav" not in html and "status-line" not in html


# ---- the status line ------------------------------------------------------

def test_the_status_line_is_in_every_page_and_polls_itself(client):
    html = client.get("/").text

    assert "В списке 12 тайтлов · последняя проверка источников в 14:05" in html
    assert 'hx-get="/status-line"' in html and 'hx-trigger="every 60s"' in html and 'hx-swap="outerHTML"' in html


def test_the_status_fragment_is_the_same_element_with_the_fresh_text(tmp_path):
    tracker = FakeTracker(Overview(1, None))
    client = make_client(tracker, tmp_path)

    first = client.get("/status-line")
    tracker.value = Overview(2, NOW - timedelta(days=1))
    second = client.get("/status-line")

    assert first.status_code == 200 and "<html" not in first.text
    assert "В списке 1 тайтл · источники ещё не проверялись" in first.text
    assert 'id="status-line"' in second.text and "В списке 2 тайтла · последняя проверка источников вчера в 15:30" in second.text


def test_the_status_line_without_sign_in_is_401_with_the_redirect_header(tmp_path):
    anonymous = TestClient(
        create_web_app(health=Health().report, password=PASSWORD, secret_file=tmp_path / "s", tracker=FakeTracker(Overview(1, None))),
        follow_redirects=False,
    )

    plain = anonymous.get("/status-line")
    htmx = anonymous.get("/status-line", headers={"HX-Request": "true"})

    for response in (plain, htmx):
        assert response.status_code == 401 and response.headers["HX-Redirect"] == "/login"


def test_a_database_that_does_not_answer_gives_a_line_and_a_page_not_a_500(tmp_path, caplog):
    client = make_client(FakeTracker(error=RuntimeError("database is locked")), tmp_path)

    with caplog.at_level(logging.ERROR):
        page = client.get("/")
        fragment = client.get("/status-line")

    assert page.status_code == 200 and NO_DATA in page.text and "Лента" in page.text
    assert fragment.status_code == 200 and NO_DATA in fragment.text
    assert any("no data from the database" in record.getMessage() for record in caplog.records)


def test_without_a_tracker_the_line_says_there_is_no_data(tmp_path):
    client = make_client(None, tmp_path)

    assert NO_DATA in client.get("/").text


@pytest.mark.parametrize("count, word", [(0, "тайтлов"), (1, "тайтл"), (2, "тайтла"), (4, "тайтла"), (5, "тайтлов"),
                                         (11, "тайтлов"), (12, "тайтлов"), (21, "тайтл"), (22, "тайтла"), (111, "тайтлов")])
def test_the_word_title_follows_the_number(count, word):
    assert titles_word(count) == word


def test_the_bot_and_the_web_take_the_word_from_one_function():
    failures = (ROOT / "app" / "tracker" / "failures.py").read_text(encoding="utf-8")

    assert "from app.tracker.cards import titles_word" in failures
    assert "def _titles_word" not in failures
    for path in (ROOT / "app").rglob("*.py"):
        if path.name != "cards.py":
            assert 'return "тайтла"' not in path.read_text(encoding="utf-8"), path


@pytest.mark.parametrize("count, last, expected", [
    (0, None, "В списке пока нет тайтлов"),
    (12, None, "В списке 12 тайтлов · источники ещё не проверялись"),
    (1, NOW.replace(hour=14, minute=5), "В списке 1 тайтл · последняя проверка источников в 14:05"),
    (21, NOW.replace(hour=0, minute=1), "В списке 21 тайтл · последняя проверка источников в 00:01"),
    (5, (NOW - timedelta(days=1)).replace(hour=23, minute=10), "В списке 5 тайтлов · последняя проверка источников вчера в 23:10"),
    (5, datetime(2026, 10, 26, 9, 5, tzinfo=MOSCOW) - timedelta(days=1), "В списке 5 тайтлов · последняя проверка источников 25 окт в 09:05"),
    (5, datetime(2026, 5, 3, 9, 5, tzinfo=MOSCOW), "В списке 5 тайтлов · последняя проверка источников 3 мая в 09:05"),
    (5, datetime(2025, 10, 26, 9, 5, tzinfo=MOSCOW), "В списке 5 тайтлов · последняя проверка источников 26 окт 2025 в 09:05"),
])
def test_the_text_of_the_status_line(count, last, expected):
    assert status_text(count, last, NOW) == expected


def test_a_day_is_the_day_of_the_owner_not_of_utc():
    # 21:30 UTC on the 26th is 00:30 on the 27th in Moscow: «today», not «yesterday»
    last = datetime(2026, 10, 26, 21, 30, tzinfo=timezone.utc).astimezone(MOSCOW)

    assert status_text(3, last, datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)) == (
        "В списке 3 тайтла · последняя проверка источников в 00:30"
    )


def test_a_moment_in_the_future_of_the_clock_reads_as_today():
    assert format_past_moment(NOW + timedelta(minutes=5), NOW) == "в 15:35"


# ---- Tracker.overview() ---------------------------------------------------

def make_tracker(**kwargs):
    return Tracker(create_session_factory("sqlite://"), clock=lambda: NOW, sender=FakeSender(), **kwargs)


def add_title(tracker, status=TitleStatus.WANT):
    with tracker.session_factory() as session:
        title = Title(
            kind=TitleKind.MOVIE, name="Дюна", original_name="Dune", year=2021, genres=[], status=status,
            tracking_enabled=True, added_at=datetime(2026, 1, 1), status_changed_at=datetime(2026, 1, 1),
        )
        session.add(title)
        session.commit()
        return title.id


def add_snapshot(tracker, title_id, source, observed_at):
    with tracker.session_factory() as session:
        session.add(SourceSnapshot(title_id=title_id, source=source, state={}, observed_at=observed_at, next_check_at=None))
        session.commit()


def test_an_empty_database_has_no_titles_and_no_check(run):
    assert run(make_tracker().overview()) == Overview(0, None)


def test_the_overview_counts_every_title_and_takes_the_latest_check(run):
    tracker = make_tracker(default_tz=MOSCOW)
    first = add_title(tracker)
    second = add_title(tracker, TitleStatus.WATCHED)  # the archive is in the list too
    add_snapshot(tracker, first, "tmdb_movie", datetime(2026, 10, 27, 8, 0))
    add_snapshot(tracker, second, "tmdb_movie", datetime(2026, 10, 27, 11, 5))
    add_snapshot(tracker, second, "tmdb_sequels", datetime(2026, 10, 26, 23, 0))

    overview = run(tracker.overview())

    assert overview.title_count == 2
    assert overview.last_check_at == datetime(2026, 10, 27, 11, 5, tzinfo=timezone.utc)
    assert overview.last_check_at.utcoffset() == timedelta(hours=3)  # on the owner's clock (default zone)
    assert overview.last_check_at.hour == 14


def test_the_overview_is_on_the_clock_of_the_zone_the_owner_set(run):
    tracker = make_tracker(default_tz=MOSCOW)
    add_snapshot(tracker, add_title(tracker), "tmdb_movie", datetime(2026, 10, 27, 11, 5))
    run(tracker.set_delivery_rules(tz_name="Asia/Jerusalem"))

    overview = run(tracker.overview())

    assert overview.last_check_at.hour == 13 and overview.last_check_at.tzinfo == ZoneInfo("Asia/Jerusalem")


def test_a_title_without_a_check_counts_but_moves_no_moment(run):
    tracker = make_tracker()
    add_title(tracker)

    assert run(tracker.overview()) == Overview(1, None)


# ---- HTMX and the templates -----------------------------------------------

def test_the_pages_load_htmx_from_the_project_and_the_file_is_served(client):
    html = client.get("/").text
    script = client.get("/static/htmx.min.js")

    assert '<script src="/static/htmx.min.js"' in html
    assert script.status_code == 200 and b"htmx" in script.content[:400] and b'version:"2.' in script.content
    config = re.search(r'<meta name="htmx-config" content=\'([^\']*)\'', html)
    assert config and '"includeIndicatorStyles": false' in config.group(1) and '"allowEval": false' in config.group(1)


def test_the_new_templates_keep_to_the_content_security_policy():
    for name in ("base.html", "section.html", "status_line.html"):
        text = (WEB / "templates" / name).read_text(encoding="utf-8")
        assert not re.search(r"<script(?![^>]*\bsrc=\"/static/)", text), name
        assert "style=" not in text and "http://" not in text and "https://" not in text, name


def test_the_pages_work_without_the_internet_the_only_script_is_ours(client):
    html = client.get("/").text

    assert re.findall(r'<script[^>]*src="([^"]*)"', html) == ["/static/htmx.min.js"]
    assert re.findall(r'<link[^>]*href="([^"]*)"', html) == ["/static/style.css"]


# ---- rule 10: the web is a thin shell -------------------------------------

ALLOWED_TRACKER_MODULES = {"core", "cards", "kinds", "models"}  # the facade and the pure modules without a database
FORBIDDEN_ROOTS = {"sqlalchemy", "alembic"}


def imports_of(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            if node.module == "app.tracker":
                for alias in node.names:
                    yield f"app.tracker.{alias.name}"
            elif node.module:
                yield node.module


def test_the_web_reaches_the_core_only_through_the_facade_and_pure_modules():
    seen = 0
    for path in WEB.glob("*.py"):
        for module in imports_of(path):
            seen += 1
            assert module.split(".")[0] not in FORBIDDEN_ROOTS, f"{path.name}: {module}"
            if module.startswith("app.tracker"):
                parts = module.split(".")
                assert len(parts) >= 3 and parts[2] in ALLOWED_TRACKER_MODULES, f"{path.name}: {module}"
    assert seen


def test_every_address_of_the_app_but_the_pinned_open_ones_is_closed_without_a_sign_in(tmp_path):
    app = create_web_app(health=Health().report, password=PASSWORD, secret_file=tmp_path / "s", tracker=FakeTracker(Overview(1, None)))

    @app.get("/future-page")  # a page added later needs no change in the guard
    async def future():
        return {"secret": 1}

    anonymous = TestClient(app, follow_redirects=False)
    addresses = {route.path for route in all_routes(app) if "GET" in route.methods}

    assert {"/", "/list", "/archive", "/search", "/settings", "/status-line", "/future-page"} <= addresses
    for address in sorted(addresses - OPEN_ADDRESSES):
        response = anonymous.get(address)
        assert response.status_code in (303, 401), address
        assert "secret" not in response.text and "Скоро будет" not in response.text, address
