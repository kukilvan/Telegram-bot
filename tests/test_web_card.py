"""The card of a title in the browser: what it shows for a film, a series and an anime, the buttons of each state, and
the presses (a mark of a season, «Отметить все вышедшие», «Посмотрел», «Удалить») on the real core with fake sources."""

import ast
import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anime_fakes import FakeAniList, FakeShikimori
from app.runtime import Health
from app.tracker.core import Tracker, UnknownSeason, UnknownTitle
from app.tracker.db import create_session_factory
from app.tracker.seasons import Episode, Season
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_series import SeriesSnapshot
from app.web import create_web_app
from app.web.posters import image_sources

WEB = Path(__file__).resolve().parent.parent / "app" / "web"
PASSWORD = "correct horse battery"
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
HTMX = {"HX-Request": "true"}
GONE = "Этого тайтла больше нет в списке"


def weekly(first_day, count):
    start = datetime.fromisoformat(first_day)
    return tuple(Episode(n + 1, start + timedelta(weeks=n)) for n in range(count))


FILM = MovieSnapshot(
    external_id="1", name="Дюна", original_name="Dune", year=2021, genres=["фантастика", "драма"],
    poster_path="/dune.jpg", overview="Пол Атрейдес едет на Арракис.",
    theatrical_date=date(2027, 3, 12), digital_date=None,
)
NASTY = MovieSnapshot(
    external_id="2", name='<script>alert("x")</script> & «Q»', original_name='"><img src=x onerror=y>', year=2000,
    genres=["<b>жанр</b>"], overview="<i>описание</i>",
)
SHOW = SeriesSnapshot(
    external_id="10", name="Идущий", original_name="Running", year=2026, genres=["драма"],
    poster_path="/run.jpg", overview="Сериал про бег.",
    seasons=[
        Season(1, "Сезон 1", 8, weekly("2026-03-02", 8)),
        Season(2, "Магическая битва", 8, weekly("2026-09-07", 8)),
        Season(3, "Сезон 3", 8, ()),
    ],
)
ENDED = SeriesSnapshot(
    external_id="11", name="Закрытый", original_name="Closed", year=2020, genres=[],
    seasons=[Season(1, "Сезон 1", 6, weekly("2020-01-06", 6))], status="Ended",
)
EMPTY = SeriesSnapshot(external_id="12", name="Пустой", original_name="Empty", year=2027, genres=[], seasons=[])
ABYSS = "34599"


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeSource:
    def __init__(self, key, *snapshots):
        self.source_key = key
        self.by_id = {s.external_id: s for s in snapshots}

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return self.by_id.get(external_id)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def tracker():
    return Tracker(
        create_session_factory("sqlite://"), clock=lambda: T0, sender=FakeSender(),
        sources={
            "movie": FakeSource("tmdb_movie", FILM, NASTY),
            "series": FakeSource("tmdb_tv", SHOW, ENDED, EMPTY),
            "anime": ShikimoriAnimeSource(FakeShikimori(), FakeAniList()),
        },
    )


def make_client(tracker, tmp_path):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    app = create_web_app(
        health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker,
        image_sources=image_sources("https://shikimori.io"),
    )
    client = TestClient(app, follow_redirects=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


@pytest.fixture
def client(tracker, tmp_path):
    return make_client(tracker, tmp_path)


def add(tracker, kind, external_id):
    return run(tracker.add_title(kind, external_id)).title_id


def buttons(html):
    """The captions of the buttons of a card: the pressed ones (form buttons) and the openers of a question."""
    return re.findall(r'<span class="idle">([^<]+)</span>', html) + re.findall(r"<summary>([^<]+)</summary>", html)


def seasons_of(html):
    """The lines of the seasons: the ones with a check box and the ones without."""
    marked = re.findall(r'<input type="checkbox"[^>]*> <span>([^<]+)</span>', html)
    plain = re.findall(r'<p class="season-plain">([^<]+)</p>', html)
    return marked, plain


# ---- what the card shows ------------------------------------------------------------------------------------

def test_the_card_of_a_film_has_its_facts_its_dates_and_the_two_buttons(tracker, client):
    film = add(tracker, "movie", "1")

    page = client.get(f"/titles/{film}")

    assert page.status_code == 200
    html = page.text
    assert "<h1>Дюна</h1>" in html and "Dune" in html
    assert "🎬 Фильм · 2021 · фантастика, драма" in html
    assert "Статус:</span> Хочу" in html
    assert "Пол Атрейдес едет на Арракис." in html
    assert "Премьера в кино: 12 марта 2027" in html and "Цифровой релиз: не объявлена" in html
    assert 'src="https://image.tmdb.org/t/p/w342/dune.jpg"' in html and "poster-large" in html
    assert buttons(html) == ["Посмотрел", "Да, удалить", "Удалить"]
    assert "Сезоны" not in html and "Отметить все вышедшие" not in html


def test_the_card_is_a_page_with_the_menu_the_list_marked_and_the_title_in_the_tab(tracker, client):
    film = add(tracker, "movie", "1")

    html = client.get(f"/titles/{film}").text

    assert 'aria-label="Разделы"' in html and 'id="status-line"' in html and "<title>Дюна · Трекер релизов</title>" in html


def test_the_card_of_a_series_lists_the_seasons_with_marks_the_names_and_an_announced_one_without_a_mark(tracker, client):
    series = add(tracker, "series", "10")

    html = client.get(f"/titles/{series}").text

    marked, plain = seasons_of(html)
    assert marked[0].startswith("Сезон 1: вышло 8 из 8")
    assert marked[1].startswith("Сезон 2 — Магическая битва: вышло ")
    assert plain == ["Сезон 3 анонсирован, дата не объявлена"]
    assert "<h2 id=\"seasons-heading\">Сезоны</h2>" in html
    assert buttons(html) == ["Отметить все вышедшие", "Да, удалить", "Удалить"]
    assert "Посмотрел" not in html and "Премьера в кино" not in html
    assert 'src="https://image.tmdb.org/t/p/w342/run.jpg"' in html and "Сериал про бег." in html


def test_a_ticked_season_is_checked_and_each_box_sends_to_its_own_season(tracker, client):
    series = add(tracker, "series", "10")
    run(tracker.set_season_watched(series, 2, True))

    html = client.get(f"/titles/{series}").text

    boxes = re.findall(r'<form method="post" action="([^"]+)" hx-post="[^"]+" hx-trigger="change"[^>]*>\s*<label class="check"><input type="checkbox" name="watched" value="1"( checked)?>', html)
    assert boxes == [(f"/titles/{series}/seasons/1", ""), (f"/titles/{series}/seasons/2", " checked")]


def test_the_mark_all_button_goes_when_every_released_season_is_marked(tracker, client):
    series = add(tracker, "series", "10")
    run(tracker.mark_all_released(series))

    html = client.get(f"/titles/{series}").text

    assert "Отметить все вышедшие" not in html


def test_a_series_without_seasons_says_so(tracker, client):
    empty = add(tracker, "series", "12")

    html = client.get(f"/titles/{empty}").text

    assert "Сезонов пока нет" in html and seasons_of(html) == ([], [])
    assert buttons(html) == ["Да, удалить", "Удалить"]


def test_the_card_of_an_anime_lists_the_seasons_and_all_the_films_of_the_franchise(tracker, client):
    anime = add(tracker, "anime", ABYSS)

    html = client.get(f"/titles/{anime}").text

    assert "🎌 Аниме" in html and "Фильмы франшизы" in html
    films = re.findall(r'<li>(Созданный[^<]*)</li>', html)
    assert len(films) == 5 and films[0] == "Созданный в Бездне: Начало путешествия (2019)"
    assert films[-1].endswith("— анонсирован")
    marked, _ = seasons_of(html)
    assert any(line.startswith("Сезон 2") for line in marked) and "Отметить все вышедшие" in html
    assert buttons(html)[-2:] == ["Да, удалить", "Удалить"] and "Посмотрел" not in buttons(html)


def test_a_watched_film_has_only_the_delete_button(tracker, client):
    film = add(tracker, "movie", "1")
    run(tracker.mark_watched(film))

    html = client.get(f"/titles/{film}").text

    assert "Статус:</span> Просмотрено" in html and buttons(html) == ["Да, удалить", "Удалить"]


def test_a_closed_series_with_every_season_marked_says_how_to_bring_it_back(tracker, client):
    ended = add(tracker, "series", "11")
    run(tracker.set_season_watched(ended, 1, True))

    html = client.get(f"/titles/{ended}").text

    assert "Статус:</span> Просмотрено" in html
    assert "Все вышедшие сезоны просмотрены, сериал закрыт. Чтобы вернуть его в список, снимите галочку сезона" in html
    assert buttons(html) == ["Да, удалить", "Удалить"] and "Отметить все вышедшие" not in html
    assert " checked>" in html  # the mark can be taken off


def test_an_open_series_has_no_closed_line(tracker, client):
    series = add(tracker, "series", "10")

    assert "сериал закрыт" not in client.get(f"/titles/{series}").text


def test_the_delete_button_opens_a_question_with_the_name_and_a_way_out(tracker, client):
    film = add(tracker, "movie", "1")

    html = client.get(f"/titles/{film}").text

    assert "<details" in html and "Удалить «Дюна» со всеми сезонами и событиями?" in html
    assert f'action="/titles/{film}/delete"' in html
    assert f'<a class="button-link" href="/titles/{film}">Отмена</a>' in html
    assert "hx-confirm" not in html


def test_a_title_that_is_not_there_is_the_404_page_with_the_link_to_the_list(client):
    page = client.get("/titles/99999")

    assert page.status_code == 404 and "Этого тайтла нет в списке" in page.text
    assert '<a href="/list">Открыть Список</a>' in page.text and "<html" in page.text


@pytest.mark.parametrize("path", ["/titles/abc", "/titles/1.5", "/titles/-"])
def test_an_address_that_is_not_a_number_is_a_404(client, path):
    assert client.get(path).status_code == 404


def test_the_card_needs_a_sign_in(tracker, tmp_path):
    film = add(tracker, "movie", "1")
    anonymous = TestClient(make_client(tracker, tmp_path).app, follow_redirects=False)

    assert anonymous.get(f"/titles/{film}").status_code == 303
    assert anonymous.post(f"/titles/{film}/delete").status_code == 303
    assert run(tracker.title_card(film)) is not None


def test_a_name_with_markup_is_text_in_every_place_of_the_card(tracker, client):
    nasty = add(tracker, "movie", "2")

    html = client.get(f"/titles/{nasty}").text

    assert "<script>alert" not in html and "&lt;script&gt;alert(&#34;x&#34;)&lt;/script&gt;" in html
    assert "<img src=x" not in html and "&lt;b&gt;жанр&lt;/b&gt;" in html and "&lt;i&gt;описание&lt;/i&gt;" in html
    assert html.count("Удалить «&lt;script&gt;") == 1


# ---- the presses --------------------------------------------------------------------------------------------

def test_a_tick_marks_the_season_and_answers_with_the_fresh_card(tracker, client):
    series = add(tracker, "series", "10")

    answer = client.post(f"/titles/{series}/seasons/1", data={"watched": "1"}, headers=HTMX)

    assert answer.status_code == 200 and "<html" not in answer.text and 'id="card"' in answer.text
    assert run(tracker.title_card(series)).seasons.watched == (1,)
    assert re.search(r'name="watched" value="1" checked>', answer.text)
    assert "Статус:</span> В процессе" in answer.text  # the status was recounted without a reload


def test_taking_the_tick_off_asks_for_the_state_without_the_box(tracker, client):
    series = add(tracker, "series", "10")
    run(tracker.set_season_watched(series, 1, True))

    answer = client.post(f"/titles/{series}/seasons/1", headers=HTMX)  # an unchecked box sends nothing

    assert answer.status_code == 200 and run(tracker.title_card(series)).seasons.watched == ()


def test_a_double_press_gives_what_the_screen_shows(tracker, client):
    series = add(tracker, "series", "10")

    for _ in range(2):
        client.post(f"/titles/{series}/seasons/1", data={"watched": "1"}, headers=HTMX)

    assert run(tracker.title_card(series)).seasons.watched == (1,)


def test_the_same_press_without_htmx_is_a_303_to_the_card(tracker, client):
    series = add(tracker, "series", "10")

    answer = client.post(f"/titles/{series}/seasons/1", data={"watched": "1"})

    assert answer.status_code == 303 and answer.headers["location"] == f"/titles/{series}"
    assert run(tracker.title_card(series)).seasons.watched == (1,)


def test_a_season_that_is_gone_is_the_fresh_card_with_a_line(tracker, client):
    series = add(tracker, "series", "10")

    answer = client.post(f"/titles/{series}/seasons/3", data={"watched": "1"}, headers=HTMX)  # season 3 has nothing out
    unknown = client.post(f"/titles/{series}/seasons/9", data={"watched": "1"}, headers=HTMX)

    for response in (answer, unknown):
        assert response.status_code == 200 and "Этого сезона больше нет — карточка обновлена" in response.text
        assert 'id="card"' in response.text and "<html" not in response.text
    assert run(tracker.title_card(series)).seasons.watched == ()


def test_a_season_that_is_gone_without_htmx_shows_the_line_once_on_the_card(tracker, client):
    series = add(tracker, "series", "10")

    answer = client.post(f"/titles/{series}/seasons/9", data={"watched": "1"})
    first = client.get(answer.headers["location"])
    second = client.get(answer.headers["location"])

    assert answer.status_code == 303
    assert "Этого сезона больше нет — карточка обновлена" in first.text
    assert "Этого сезона больше нет" not in second.text


def test_mark_all_released_marks_the_seasons_and_answers_with_the_card(tracker, client):
    series = add(tracker, "series", "10")

    answer = client.post(f"/titles/{series}/released-watched", headers=HTMX)

    assert answer.status_code == 200 and "Отметить все вышедшие" not in answer.text
    assert run(tracker.title_card(series)).seasons.watched == (1, 2)
    assert client.post(f"/titles/{series}/released-watched").status_code == 303


def test_watched_makes_the_film_watched_and_the_card_shows_it(tracker, client):
    film = add(tracker, "movie", "1")

    answer = client.post(f"/titles/{film}/watched", headers=HTMX)

    assert answer.status_code == 200 and "Статус:</span> Просмотрено" in answer.text
    assert buttons(answer.text) == ["Да, удалить", "Удалить"]
    assert run(tracker.title_card(film)).status == "watched"


def test_watched_twice_is_just_the_fresh_card(tracker, client):
    film = add(tracker, "movie", "1")
    client.post(f"/titles/{film}/watched", headers=HTMX)

    answer = client.post(f"/titles/{film}/watched", headers=HTMX)

    assert answer.status_code == 200 and "Просмотрено" in answer.text


@pytest.mark.parametrize("path", ["/seasons/1", "/released-watched", "/watched"])
def test_a_press_on_a_card_whose_title_was_deleted_elsewhere_is_the_gone_fragment_with_200(tracker, client, path):
    film = add(tracker, "movie", "1")
    run(tracker.delete_title(film))

    answer = client.post(f"/titles/{film}{path}", headers=HTMX)

    assert answer.status_code == 200 and GONE in answer.text and '<a href="/list">Открыть Список</a>' in answer.text
    assert "<html" not in answer.text


def test_a_press_without_htmx_on_a_title_deleted_elsewhere_is_the_404_page(tracker, client):
    film = add(tracker, "movie", "1")
    run(tracker.delete_title(film))

    answer = client.post(f"/titles/{film}/watched")

    assert answer.status_code == 404 and GONE in answer.text


def test_a_title_deleted_between_the_press_and_the_fresh_card_is_the_gone_fragment(tracker, client, monkeypatch):
    film = add(tracker, "movie", "1")
    real = tracker.title_card

    async def vanished(title_id):
        await tracker.delete_title(title_id)
        return await real(title_id)

    monkeypatch.setattr(Tracker, "title_card", lambda self, title_id: vanished(title_id))

    answer = client.post(f"/titles/{film}/watched", headers=HTMX)

    assert answer.status_code == 200 and GONE in answer.text


@pytest.mark.parametrize("path", ["/seasons/1", "/released-watched", "/watched", "/delete"])
def test_an_unexpected_error_is_logged_and_told_in_a_fragment(tracker, client, monkeypatch, caplog, path):
    film = add(tracker, "movie", "1")

    async def broken(self, *args, **kwargs):
        raise RuntimeError("the database is gone")

    for name in ("set_season_watched", "mark_all_released", "mark_watched", "delete_title"):
        monkeypatch.setattr(Tracker, name, broken)

    with caplog.at_level(logging.ERROR):
        answer = client.post(f"/titles/{film}{path}", headers=HTMX)

    assert answer.status_code == 200 and "Не получилось. Попробуйте ещё раз; подробности — в журнале" in answer.text
    assert "<html" not in answer.text and "the database is gone" not in answer.text
    assert any(r.exc_info for r in caplog.records if "unexpected error" in r.getMessage())


def test_a_card_page_the_core_cannot_read_is_the_500_page(tracker, client, monkeypatch, caplog):
    film = add(tracker, "movie", "1")

    async def broken(self, title_id):
        raise RuntimeError("no database")

    monkeypatch.setattr(Tracker, "title_card", broken)

    with caplog.at_level(logging.ERROR):
        page = client.get(f"/titles/{film}")

    assert page.status_code == 500 and "Не получилось" in page.text and "no database" not in page.text


# ---- deleting -----------------------------------------------------------------------------------------------

def test_deleting_removes_the_title_and_goes_to_the_list_with_a_line(tracker, client):
    film = add(tracker, "movie", "1")

    answer = client.post(f"/titles/{film}/delete", headers=HTMX)

    assert answer.status_code == 200 and answer.headers["HX-Redirect"] == "/list"
    assert run(tracker.title_card(film)) is None
    shown = client.get("/list").text
    assert '<p class="notice" role="status">Удалено: «Дюна»</p>' in shown
    assert 'class="notice"' not in client.get("/list").text  # shown once


def test_deleting_without_htmx_is_a_303_to_the_list(tracker, client):
    film = add(tracker, "movie", "1")

    answer = client.post(f"/titles/{film}/delete")

    assert answer.status_code == 303 and answer.headers["location"] == "/list"
    assert "Удалено: «Дюна»" in client.get("/list").text


def test_deleting_a_title_that_is_already_gone_says_so_on_the_list(tracker, client):
    film = add(tracker, "movie", "1")
    client.post(f"/titles/{film}/delete", headers=HTMX)
    client.get("/list")

    answer = client.post(f"/titles/{film}/delete", headers=HTMX)

    assert answer.status_code == 200 and answer.headers["HX-Redirect"] == "/list"
    assert "Этого тайтла уже нет в списке" in client.get("/list").text


def test_a_name_with_markup_is_text_in_the_line_after_deleting(tracker, client):
    nasty = add(tracker, "movie", "2")

    client.post(f"/titles/{nasty}/delete", headers=HTMX)
    shown = client.get("/list").text

    assert "<script>alert" not in shown and "Удалено: «&lt;script&gt;" in shown


def test_a_press_from_a_foreign_page_is_refused_and_changes_nothing(tracker, client):
    film = add(tracker, "movie", "1")

    answer = client.post(f"/titles/{film}/delete", headers={"Origin": "http://evil.example"})

    assert answer.status_code == 403 and run(tracker.title_card(film)) is not None


# ---- the rules of the web ------------------------------------------------------------------------------------

def test_the_card_module_reaches_the_core_only_through_the_facade_and_the_pure_modules():
    for node in ast.walk(ast.parse((WEB / "card.py").read_text(encoding="utf-8"))):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", None) or node.names[0].name
            assert module.split(".")[0] not in {"sqlalchemy", "alembic"}, module
            assert not module.startswith("app.tracker.") or module.split(".")[2] in {"core", "cards", "kinds", "models"}, module


def test_the_card_is_a_module_with_a_router_of_its_own_and_the_app_only_assembles_it(tracker, tmp_path):
    from web_helpers import all_routes

    app = make_client(tracker, tmp_path).app

    mine = {route.path for route in all_routes(app) if route.endpoint.__module__ == "app.web.card"}
    assert mine == {
        "/titles/{title_id:int}", "/titles/{title_id:int}/seasons/{number:int}", "/titles/{title_id:int}/released-watched",
        "/titles/{title_id:int}/watched", "/titles/{title_id:int}/delete",
    }
    assert app.url_path_for("card", title_id=5) == "/titles/5"


def test_the_core_raises_what_the_card_catches():
    assert issubclass(UnknownTitle, Exception) and issubclass(UnknownSeason, Exception)
