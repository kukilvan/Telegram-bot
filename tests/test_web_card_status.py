"""The card in the browser, part two: the buttons of every kind and status (table 4.3 of the spec of part 5.2),
«Бросил», «Вернуть в список», the block «Продолжения» of a watched film and «Следить» in it. On the real core with fake
sources; the presses go through the web app."""

import asyncio
import logging
import re
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from anime_fakes import FakeAniList, FakeShikimori
from app.runtime import Health
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import Title, TitleStatus
from app.tracker.seasons import Episode, Season
from app.tracker.sources.shikimori_anime import ShikimoriAnimeSource
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_sequels import CollectionPart, SequelSnapshot
from app.tracker.sources.tmdb_series import SeriesSnapshot
from app.web import create_web_app
from app.web.posters import image_sources
from season_helpers import season_id

PASSWORD = "correct horse battery"
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
HTMX = {"HX-Request": "true"}
GONE = "Этого тайтла больше нет в списке"
ABYSS = "34599"

FILM = MovieSnapshot(external_id="1", name="Дюна", original_name="Dune", year=2021, genres=[])
PART_TWO = MovieSnapshot(external_id="2", name="Дюна: Часть вторая", original_name="Dune: Part Two", year=2024, genres=[])
SEQUEL_TWO = CollectionPart("2", "Дюна: Часть вторая", date(2024, 2, 27))
SEQUEL_THREE = CollectionPart("3", "Дюна: Часть третья", date(2028, 12, 15))
SEQUEL_FOUR = CollectionPart("4", "Дюна: Часть четвёртая", None)
SHOW = SeriesSnapshot(
    external_id="10", name="Идущий", original_name="Running", year=2026, genres=[],
    seasons=[Season(1, "Сезон 1", 4, tuple(Episode(n + 1, datetime(2026, 3, 2) + timedelta(weeks=n)) for n in range(4)))],
)


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeSource:
    def __init__(self, key, *snapshots):
        self.source_key = key
        self.by_id = {s.external_id: s for s in snapshots}
        self.failing = False

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        if self.failing:
            raise ConnectionError("TMDb is down")
        return self.by_id.get(external_id)


class FakeSequelSource:
    source_key = "tmdb_sequels"

    def __init__(self):
        self.parts = []

    async def snapshot(self, external_id):
        return SequelSnapshot(own_date=date(2021, 9, 15), parts=list(self.parts))


class FakeClock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def movies():
    return FakeSource("tmdb_movie", FILM, PART_TWO)


@pytest.fixture
def sequels():
    return FakeSequelSource()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory, clock, movies, sequels):
    return Tracker(
        session_factory, clock=clock, sender=FakeSender(),
        sources={
            "movie": movies,
            "series": FakeSource("tmdb_tv", SHOW),
            "anime": ShikimoriAnimeSource(FakeShikimori(), FakeAniList()),
        },
        sequel_sources={"movie": sequels},
    )


@pytest.fixture
def client(tracker, tmp_path):
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


def add(tracker, kind, external_id):
    return run(tracker.add_title(kind, external_id)).title_id


def set_status(session_factory, title_id, status):
    with session_factory() as session:
        session.execute(update(Title).where(Title.id == title_id).values(status=status))
        session.commit()


def buttons(html):
    """The buttons of the card's own actions: the pressed ones and the opener of the question (the seasons' button and
    the «Следить» of the sequels are not counted here)."""
    pressed = re.findall(r'<span class="idle">([^<]+)</span>', html)
    return [b for b in pressed if b not in ("Отметить все вышедшие", "Следить")] + re.findall(r"<summary>([^<]+)</summary>", html)


def watched_film(tracker, sequels, *parts):
    film = add(tracker, "movie", "1")
    sequels.parts = list(parts)
    run(tracker.mark_watched(film))
    run(tracker.poll_due())
    return film


# ---- the buttons of each kind and status (4.3) -----------------------------------------------------------------

def test_a_wanted_film_has_watched_dropped_and_delete(tracker, client):
    film = add(tracker, "movie", "1")

    assert buttons(client.get(f"/titles/{film}").text) == ["Посмотрел", "Бросил", "Да, удалить", "Удалить"]


@pytest.mark.parametrize("kind, external_id", [("series", "10"), ("anime", ABYSS)])
@pytest.mark.parametrize("status", [TitleStatus.WANT, TitleStatus.IN_PROGRESS, TitleStatus.WAITING, TitleStatus.TO_FINISH])
def test_a_series_or_an_anime_out_of_the_archive_has_dropped_and_delete(tracker, client, session_factory, kind, external_id, status):
    title_id = add(tracker, kind, external_id)
    set_status(session_factory, title_id, status)

    html = client.get(f"/titles/{title_id}").text

    assert buttons(html) == ["Бросил", "Да, удалить", "Удалить"]
    assert "Посмотрел" not in html and "Вернуть в список" not in html and "Продолжения" not in html


def test_a_watched_film_has_restore_delete_and_the_sequels_block(tracker, client, sequels):
    film = add(tracker, "movie", "1")
    run(tracker.mark_watched(film))

    html = client.get(f"/titles/{film}").text

    assert buttons(html) == ["Вернуть в список", "Да, удалить", "Удалить"]
    assert '<h2 id="sequels-heading">Продолжения</h2>' in html
    assert "Ищу продолжения в коллекции TMDb — обновите страницу через минуту" in html


@pytest.mark.parametrize("kind, external_id", [("series", "10"), ("anime", ABYSS)])
def test_a_watched_series_or_anime_has_only_delete_and_the_line_about_the_marks(tracker, client, session_factory, kind, external_id):
    title_id = add(tracker, kind, external_id)
    set_status(session_factory, title_id, TitleStatus.WATCHED)

    html = client.get(f"/titles/{title_id}").text

    assert buttons(html) == ["Да, удалить", "Удалить"] and "Вернуть в список" not in html
    assert "Чтобы вернуть его в список, снимите галочку сезона" in html


@pytest.mark.parametrize("kind, external_id", [("movie", "1"), ("series", "10"), ("anime", ABYSS)])
def test_a_dropped_title_has_restore_and_delete(tracker, client, kind, external_id):
    title_id = add(tracker, kind, external_id)
    run(tracker.mark_dropped(title_id))

    html = client.get(f"/titles/{title_id}").text

    assert "Статус:</span> Бросил" in html
    assert buttons(html) == ["Вернуть в список", "Да, удалить", "Удалить"]
    assert "Продолжения" not in html and "Посмотрел" not in html and "сериал закрыт" not in html


def test_a_dropped_series_keeps_its_check_boxes(tracker, client):
    series = add(tracker, "series", "10")
    run(tracker.mark_dropped(series))

    answer = client.post(f"/titles/{series}/seasons/{season_id(tracker, series, 1)}", data={"watched": "1"}, headers=HTMX)

    assert 'name="watched" value="1" checked>' in answer.text and "Статус:</span> Бросил" in answer.text


# ---- the sequels block (4.5) -----------------------------------------------------------------------------------

def test_a_collection_with_no_sequels_says_so(tracker, client, sequels):
    film = watched_film(tracker, sequels)

    html = client.get(f"/titles/{film}").text

    assert "Продолжений пока нет. Проверяю раз в неделю" in html and "Ищу продолжения" not in html


def test_the_sequels_are_rows_with_their_dates_and_follow_or_in_the_list(tracker, client, sequels):
    film = watched_film(tracker, sequels, SEQUEL_FOUR, SEQUEL_THREE, SEQUEL_TWO)
    followed = add(tracker, "movie", "2")

    html = client.get(f"/titles/{film}").text

    rows = re.findall(r'<span class="sequel-name">([^<]+)</span> <span class="sequel-date">([^<]+)</span>', html)
    assert rows == [
        ("Дюна: Часть вторая", "27 февраля 2024"), ("Дюна: Часть третья", "15 декабря 2028"),
        ("Дюна: Часть четвёртая", "дата не объявлена"),
    ]
    assert f'<a class="row-action button-link" href="/titles/{followed}">В списке</a>' in html
    follows = re.findall(r'name="kind" value="([^"]+)">\s*<input type="hidden" name="sequel_id" value="([^"]+)">', html)
    assert follows == [("movie", "3"), ("movie", "4")]
    assert html.count(f'action="/titles/{film}/sequels"') == 2 and "Добавляю…" in html
    assert "Продолжений пока нет" not in html and "Ищу продолжения" not in html


def test_follow_adds_the_sequel_and_the_fresh_card_says_it_is_in_the_list(tracker, client, sequels, movies):
    movies.by_id["3"] = MovieSnapshot(external_id="3", name="Дюна: Часть третья", original_name="", year=2028, genres=[])
    film = watched_film(tracker, sequels, SEQUEL_THREE)

    answer = client.post(f"/titles/{film}/sequels", data={"kind": "movie", "sequel_id": "3"}, headers=HTMX)

    assert answer.status_code == 200 and 'id="card"' in answer.text and "<html" not in answer.text
    added = next(row.id for row in run(tracker.list_titles()) if row.name == "Дюна: Часть третья")
    assert f'href="/titles/{added}">В списке</a>' in answer.text
    assert "HX-Redirect" not in answer.headers  # the owner stays on the card of the watched film


def test_follow_without_htmx_is_a_303_back_to_the_card(tracker, client, sequels):
    film = watched_film(tracker, sequels, SEQUEL_TWO)

    answer = client.post(f"/titles/{film}/sequels", data={"kind": "movie", "sequel_id": "2"})

    assert answer.status_code == 303 and answer.headers["location"] == f"/titles/{film}"
    assert len(run(tracker.list_titles())) == 2


def test_follow_while_the_source_is_down_is_a_line_in_the_block(tracker, client, sequels, movies, caplog):
    film = watched_film(tracker, sequels, SEQUEL_TWO)
    movies.failing = True

    with caplog.at_level(logging.WARNING):
        answer = client.post(f"/titles/{film}/sequels", data={"kind": "movie", "sequel_id": "2"}, headers=HTMX)

    assert answer.status_code == 200
    assert '<p class="error" role="alert">Не удалось связаться с TMDb. Попробуйте чуть позже</p>' in answer.text
    assert len(run(tracker.list_titles())) == 1 and "TMDb is down" in caplog.text


def test_follow_while_the_source_is_down_without_htmx_says_so_on_the_card(tracker, client, sequels, movies):
    film = watched_film(tracker, sequels, SEQUEL_TWO)
    movies.failing = True

    answer = client.post(f"/titles/{film}/sequels", data={"kind": "movie", "sequel_id": "2"})

    assert answer.status_code == 303
    assert "Не удалось связаться с TMDb. Попробуйте чуть позже" in client.get(answer.headers["location"]).text


def test_follow_of_a_sequel_the_source_does_not_know_says_so(tracker, client, sequels):
    film = watched_film(tracker, sequels, SEQUEL_FOUR)

    answer = client.post(f"/titles/{film}/sequels", data={"kind": "movie", "sequel_id": "4"}, headers=HTMX)

    assert "TMDb больше не знает этот тайтл. Поищите заново" in answer.text


@pytest.mark.parametrize("kind", ["game", "series", ""])
def test_follow_of_a_kind_without_sequels_is_refused(tracker, client, sequels, kind):
    film = watched_film(tracker, sequels, SEQUEL_TWO)

    answer = client.post(f"/titles/{film}/sequels", data={"kind": kind, "sequel_id": "2"}, headers=HTMX)

    assert answer.status_code == 200 and "Такого типа нет" in answer.text
    assert len(run(tracker.list_titles())) == 1


# ---- the presses of «Бросил» and «Вернуть в список» (4.4) ------------------------------------------------------

def test_dropped_answers_with_the_fresh_card(tracker, client):
    film = add(tracker, "movie", "1")

    answer = client.post(f"/titles/{film}/dropped", headers=HTMX)

    assert answer.status_code == 200 and "Статус:</span> Бросил" in answer.text and "<html" not in answer.text
    assert buttons(answer.text) == ["Вернуть в список", "Да, удалить", "Удалить"]
    assert run(tracker.title_card(film)).status == TitleStatus.DROPPED


def test_restore_of_a_watched_film_makes_it_wanted_and_takes_the_sequels_block_away(tracker, client, sequels, clock):
    film = watched_film(tracker, sequels, SEQUEL_THREE)
    clock.now += timedelta(days=1)

    answer = client.post(f"/titles/{film}/restore", headers=HTMX)

    assert "Статус:</span> Хочу" in answer.text and "Продолжения" not in answer.text
    assert buttons(answer.text) == ["Посмотрел", "Бросил", "Да, удалить", "Удалить"]


def test_restore_of_a_dropped_series_gives_the_status_of_its_marks(tracker, client):
    series = add(tracker, "series", "10")
    run(tracker.set_season_watched(series, season_id(tracker, series, 1), True))
    run(tracker.mark_dropped(series))

    answer = client.post(f"/titles/{series}/restore", headers=HTMX)

    assert "Статус:</span> Жду" in answer.text


@pytest.mark.parametrize("path", ["/dropped", "/restore"])
def test_the_presses_without_htmx_are_a_303_to_the_card(tracker, client, path):
    film = add(tracker, "movie", "1")
    if path == "/restore":
        run(tracker.mark_dropped(film))

    answer = client.post(f"/titles/{film}{path}")

    assert answer.status_code == 303 and answer.headers["location"] == f"/titles/{film}"


@pytest.mark.parametrize("path", ["/dropped", "/restore"])
def test_a_press_that_changes_nothing_is_just_the_fresh_card(tracker, client, path):
    film = add(tracker, "movie", "1")
    if path == "/dropped":
        run(tracker.mark_dropped(film))

    answer = client.post(f"/titles/{film}{path}", headers=HTMX)

    assert answer.status_code == 200 and 'id="card"' in answer.text


@pytest.mark.parametrize("path", ["/dropped", "/restore", "/sequels"])
def test_a_press_on_a_title_deleted_elsewhere_is_the_gone_fragment(tracker, client, path):
    film = add(tracker, "movie", "1")
    run(tracker.delete_title(film))

    # a sequel the source does not know: an added one would take the freed number (KI-24)
    answer = client.post(f"/titles/{film}{path}", data={"kind": "movie", "sequel_id": "9"}, headers=HTMX)

    assert answer.status_code == 200 and GONE in answer.text and "<html" not in answer.text


@pytest.mark.parametrize("path", ["/dropped", "/restore", "/sequels"])
def test_an_unexpected_error_is_logged_and_told_in_a_fragment(tracker, client, monkeypatch, caplog, path):
    film = add(tracker, "movie", "1")

    async def broken(self, *args, **kwargs):
        raise RuntimeError("the database is gone")

    for name in ("mark_dropped", "restore_title", "follow_sequel_of"):
        monkeypatch.setattr(Tracker, name, broken)

    with caplog.at_level(logging.ERROR):
        answer = client.post(f"/titles/{film}{path}", data={"kind": "movie", "sequel_id": "2"}, headers=HTMX)

    assert answer.status_code == 200 and "Не получилось. Попробуйте ещё раз; подробности — в журнале" in answer.text
    assert any(r.exc_info for r in caplog.records if "unexpected error" in r.getMessage())


@pytest.mark.parametrize("path", ["/dropped", "/restore", "/sequels"])
def test_a_press_from_a_foreign_page_is_refused(tracker, client, path):
    film = add(tracker, "movie", "1")

    answer = client.post(f"/titles/{film}{path}", headers={"Origin": "http://evil.example"})

    assert answer.status_code == 403 and run(tracker.title_card(film)).status == TitleStatus.WANT


@pytest.mark.parametrize("path", ["/dropped", "/restore", "/sequels"])
def test_the_presses_need_a_sign_in(tracker, client, path):
    film = add(tracker, "movie", "1")
    anonymous = TestClient(client.app, follow_redirects=False)

    assert anonymous.post(f"/titles/{film}{path}").status_code == 303
    assert run(tracker.title_card(film)).status == TitleStatus.WANT


def test_a_sequel_name_with_markup_is_text(tracker, client, sequels):
    film = watched_film(tracker, sequels, replace(SEQUEL_THREE, name='<script>alert("x")</script>'))

    html = client.get(f"/titles/{film}").text

    assert "<script>alert" not in html and "&lt;script&gt;alert" in html
