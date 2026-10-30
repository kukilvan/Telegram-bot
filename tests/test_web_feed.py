"""The feed in the browser (ticket 05 of part 5.3): the days of «Скоро», «Позже» with the whole date, the days of «Недавно»,
the hour of an anime, the poster or the icon, the empty places, «Посмотрел» and «Следить» and their errors, the escaping.
On the real core (titles, seasons and events put straight into the database) with fake sources; the presses go through
the web app."""

import ast
import asyncio
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker import movie_events, sequel_events
from app.tracker.cards import format_date, format_weekday_date
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import (
    EpisodeRecord, Event, ExternalId, PartRecord, SeasonRecord, SourceSnapshot, Title, TitleKind, TitleStatus,
)
from app.tracker.series_events import EPISODE_OUT
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_sequels import SequelSnapshot
from app.web import create_web_app
from app.web.posters import image_sources

PASSWORD = "correct horse battery"
NOW = datetime(2026, 10, 30, 12, 0)  # a Friday, naive UTC like everything stored
TODAY = NOW.date()
MSK = timezone(timedelta(hours=3))
HTMX = {"HX-Request": "true"}
GONE = "Этого тайтла больше нет в списке"
SEQUEL_THREE = MovieSnapshot(external_id="3", name="Дюна: Часть третья", original_name="Dune 3", year=2028, genres=[])
ROOT = Path(__file__).resolve().parent.parent


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeSource:
    source_key = "tmdb_movie"

    def __init__(self, *snapshots):
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

    async def snapshot(self, external_id):
        return SequelSnapshot(own_date=date(2021, 9, 15), parts=[])


def run(coro):
    return asyncio.run(coro)


def at(days, hour=12):
    return datetime.combine(TODAY + timedelta(days=days), time(hour))


def day(days):
    return TODAY + timedelta(days=days)


@pytest.fixture
def movies():
    return FakeSource(SEQUEL_THREE)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory, movies):
    return Tracker(
        session_factory, clock=lambda: NOW.replace(tzinfo=timezone.utc), sender=FakeSender(),
        sources={"movie": movies}, sequel_sources={"movie": FakeSequelSource()}, default_tz=MSK,
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


def put_title(session_factory, name, kind=TitleKind.SERIES, status=TitleStatus.WANT, poster=None):
    with session_factory() as session:
        title = Title(
            kind=kind, name=name, original_name=name, genres=[], poster_path=poster, status=status,
            tracking_enabled=True, added_at=NOW, status_changed_at=NOW,
        )
        session.add(title)
        session.commit()
        return title.id


def put_season(session_factory, title_id, number, episodes, parts=()):
    with session_factory() as session:
        record = SeasonRecord(title_id=title_id, number=number, name=f"Сезон {number}", episode_count=None, watched=False)
        session.add(record)
        session.flush()
        session.add_all(EpisodeRecord(season_id=record.id, number=n, air_at=moment) for n, moment in episodes.items())
        session.add_all(
            PartRecord(title_id=title_id, season_id=record.id, number=index, first_episode=first, episode_count=count,
                       shikimori_id=f"{title_id}-{number}-{index}")
            for index, (first, count) in enumerate(parts, 1)
        )
        session.commit()


def put_movie_dates(session_factory, title_id, external_id):
    with session_factory() as session:
        session.add(ExternalId(title_id=title_id, source="tmdb_movie", external_id=external_id, role="primary"))
        state = movie_events.MovieDates(None, None).to_state()
        session.add(SourceSnapshot(title_id=title_id, source="tmdb_movie", state=state, observed_at=NOW))
        session.commit()


def put_event(session_factory, title_id, type_, text, found, data=None):
    with session_factory() as session:
        session.add(Event(type=type_, title_id=title_id, payload={"text": text, **(data or {})},
                          dedup_key=f"{type_}:{title_id}:{found.isoformat()}:{text}", detected_at=found))
        session.commit()


def rows_of(html, block):
    """The rows of one block of the feed (`soon`, `later`, `recent`) as the text of each, tags dropped."""
    section = re.search(rf'<section class="feed-block" aria-labelledby="{block}-heading">(.*?)</section>', html, re.S)
    assert section, block
    rows = re.findall(r'<li class="title-row">(.*?)</li>', section.group(1), re.S)
    return [" ".join(re.sub(r"<[^>]+>", " ", re.sub(r'<span class="poster-icon".*?</span>', "", row)).split()) for row in rows]


def days_of(html, block):
    section = re.search(rf'<section class="feed-block" aria-labelledby="{block}-heading">(.*?)</section>', html, re.S).group(1)
    return re.findall(r'<h3 class="feed-day">([^<]*)</h3>', section)


def titles_in_feed(client):
    return client.get("/").text


# ---- the page ----------------------------------------------------------------------------------------------------

def test_the_feed_is_the_main_page_and_the_stub_is_gone(client, session_factory):
    put_title(session_factory, "Укрытие")

    page = client.get("/")

    assert page.status_code == 200 and "<h1>Лента</h1>" in page.text and "Скоро будет" not in page.text
    assert '<a href="/" aria-current="page">Лента</a>' in page.text and page.text.count('aria-current="page"') == 1
    assert '<h2 id="soon-heading">Скоро</h2>' in page.text and '<h2 id="recent-heading">Недавно</h2>' in page.text


def test_the_days_of_soon_are_today_tomorrow_and_then_the_weekday_and_date(client, session_factory):
    show = put_title(session_factory, "Укрытие")
    put_season(session_factory, show, 2, {4: at(-1), 5: at(0), 6: at(1), 7: at(3)})

    html = client.get("/").text

    assert days_of(html, "soon") == ["Сегодня", "Завтра", format_weekday_date(day(3))]
    assert [r for r in rows_of(html, "soon")] == [
        "📺 Укрытие Сезон 2, серия 5", "📺 Укрытие Сезон 2, серия 6", "📺 Укрытие Сезон 2, серия 7",
    ]
    assert 'id="later-heading"' not in html  # nothing later: no block


def test_later_has_one_row_per_title_with_the_whole_date(client, session_factory):
    show = put_title(session_factory, "Пацаны")
    put_season(session_factory, show, 5, {1: at(20), 2: at(27)})

    html = client.get("/").text

    assert rows_of(html, "later") == [f"📺 Пацаны Сезон 5 — премьера {format_date(day(20))}"]
    assert "ничего не выходит" in html and "Найдите тайтл в Поиске" not in html.split('id="later-heading"')[0]


def test_an_anime_row_has_the_hour_on_the_owners_clock(client, session_factory):
    anime = put_title(session_factory, "Магическая битва", TitleKind.ANIME)
    put_season(session_factory, anime, 1, {1: at(-7, 15), 4: at(0, 15)}, parts=[(1, None)])

    html = client.get("/").text

    assert rows_of(html, "soon") == ["🎌 Магическая битва Сезон 1, серия 4 в 18:00"]


def test_the_days_of_recent_are_today_yesterday_and_then_the_weekday_and_date(client, session_factory):
    show = put_title(session_factory, "Укрытие")
    for days, number in ((0, 5), (-1, 4), (-3, 3)):
        put_event(session_factory, show, EPISODE_OUT, f"📺 Укрытие — вышла серия {number}\nСезон 2", at(days),
                  {"season": 2, "episode": number})

    html = client.get("/").text

    assert days_of(html, "recent") == ["Сегодня", "Вчера", format_weekday_date(day(-3))]
    assert rows_of(html, "recent") == [
        "📺 Укрытие — вышла серия 5 Сезон 2", "📺 Укрытие — вышла серия 4 Сезон 2", "📺 Укрытие — вышла серия 3 Сезон 2",
    ]


def test_every_row_leads_to_the_card_and_has_the_poster_or_the_icon(client, session_factory):
    shown = put_title(session_factory, "С постером", poster="/abc.jpg")
    bare = put_title(session_factory, "Без постера")
    put_season(session_factory, shown, 1, {1: at(0)})
    put_season(session_factory, bare, 1, {1: at(0)})

    html = client.get("/").text

    assert f'<a class="row-link" href="/titles/{shown}">' in html and f'<a class="row-link" href="/titles/{bare}">' in html
    assert html.count("https://image.tmdb.org/t/p/w92/abc.jpg") == 1
    assert html.count('<span class="poster-icon" aria-hidden="true">📺</span>') == 2  # the icon stays under any picture


def test_the_day_of_a_row_follows_the_owners_clock_not_utc(client, session_factory):
    anime = put_title(session_factory, "Ночное", TitleKind.ANIME)
    put_season(session_factory, anime, 1, {1: at(0, 23)}, parts=[(1, None)])  # 23:00 UTC is 02:00 tomorrow in Moscow

    html = client.get("/").text

    assert days_of(html, "soon") == ["Завтра"] and rows_of(html, "soon")[0].endswith("в 02:00")


# ---- the empty places --------------------------------------------------------------------------------------------

def test_an_empty_list_says_so_and_has_no_blocks(client):
    html = client.get("/").text

    assert "В списке пока ничего нет." in html and '<a href="/search">Найдите тайтл в Поиске</a>' in html
    assert "soon-heading" not in html and "recent-heading" not in html


def test_nothing_coming_and_nothing_later_says_so_with_a_link_to_the_search(client, session_factory):
    put_title(session_factory, "Тихий")

    html = client.get("/").text

    assert "В ближайшие 14 дней ничего не выходит. <a href=\"/search\">Найдите тайтл в Поиске</a>" in html
    assert 'id="later-heading"' not in html and "За неделю ничего не случилось" in html


def test_nothing_coming_but_something_later_says_so_and_then_shows_later(client, session_factory):
    show = put_title(session_factory, "Пацаны")
    put_season(session_factory, show, 5, {1: at(30)})

    html = client.get("/").text

    assert "В ближайшие 14 дней ничего не выходит</p>" in html
    assert html.index("ничего не выходит") < html.index('id="later-heading"') < html.index('id="recent-heading"')


def test_nothing_recent_says_so(client, session_factory):
    show = put_title(session_factory, "Укрытие")
    put_season(session_factory, show, 2, {5: at(0)})
    put_event(session_factory, show, EPISODE_OUT, "📺 Укрытие — вышла серия 1", at(-8), {"season": 1, "episode": 1})  # eight days ago

    html = client.get("/").text

    assert "За неделю ничего не случилось" in html and "вышла серия 1" not in html


# ---- the buttons -------------------------------------------------------------------------------------------------

def announce(session_factory, dune, sequel_id="3"):
    put_event(session_factory, dune, sequel_events.SEQUEL_ANNOUNCED, f"🎬 Анонсировано продолжение {sequel_id}", at(0, 6),
              {"kind": "movie", "sequel_id": sequel_id})


def test_the_buttons_are_where_the_core_gave_them(client, session_factory):
    wanted = put_title(session_factory, "Дюна", TitleKind.MOVIE)
    seen = put_title(session_factory, "Аватар", TitleKind.MOVIE, TitleStatus.WATCHED)
    put_event(session_factory, wanted, movie_events.RELEASED, "🎬 Дюна — вышел в кино", at(0, 6))
    put_event(session_factory, seen, movie_events.DIGITAL, "🎬 Аватар — цифровой релиз", at(0, 7))
    announce(session_factory, seen)

    html = client.get("/").text

    assert html.count(f'"/feed/titles/{wanted}/watched"') == 2  # the form and its htmx address
    assert f"/feed/titles/{seen}/watched" not in html
    assert html.count('<span class="idle">Посмотрел</span><span class="busy">Сохраняю…</span>') == 1
    assert '<input type="hidden" name="kind" value="movie">' in html and '<input type="hidden" name="sequel_id" value="3">' in html
    assert '<span class="idle">Следить</span><span class="busy">Добавляю…</span>' in html


def test_a_sequel_the_list_has_already_is_a_link_not_a_button(client, session_factory):
    dune = put_title(session_factory, "Дюна", TitleKind.MOVIE, TitleStatus.WATCHED)
    three = put_title(session_factory, "Дюна: Часть третья", TitleKind.MOVIE)
    put_movie_dates(session_factory, three, "3")
    announce(session_factory, dune)

    html = client.get("/").text

    assert f'<a class="row-action button-link" href="/titles/{three}">В списке</a>' in html and "Следить" not in html


def test_watched_marks_the_film_and_answers_with_the_fresh_feed(client, tracker, session_factory):
    film = put_title(session_factory, "Дюна", TitleKind.MOVIE)
    put_event(session_factory, film, movie_events.RELEASED, "🎬 Дюна — вышел в кино", at(0, 6))

    answer = client.post(f"/feed/titles/{film}/watched", headers=HTMX)

    assert answer.status_code == 200 and "<html" not in answer.text and 'id="feed"' in answer.text
    assert "Дюна — вышел в кино" in answer.text and "Посмотрел" not in answer.text  # the line stays, the button goes
    assert run(tracker.title_card(film)).status == TitleStatus.WATCHED


def test_watched_without_htmx_goes_back_to_the_feed(client, tracker, session_factory):
    film = put_title(session_factory, "Дюна", TitleKind.MOVIE)

    answer = client.post(f"/feed/titles/{film}/watched")

    assert answer.status_code == 303 and answer.headers["location"] == "/"
    assert run(tracker.title_card(film)).status == TitleStatus.WATCHED


def test_watched_of_a_film_that_is_watched_already_changes_nothing(client, tracker, session_factory):
    film = put_title(session_factory, "Дюна", TitleKind.MOVIE, TitleStatus.WATCHED)
    changed = run(tracker.title_card(film)).status

    answer = client.post(f"/feed/titles/{film}/watched", headers=HTMX)

    assert answer.status_code == 200 and 'id="feed"' in answer.text and GONE not in answer.text
    assert run(tracker.title_card(film)).status == changed


def test_follow_adds_the_sequel_and_the_fresh_feed_says_it_is_in_the_list(client, tracker, session_factory):
    dune = put_title(session_factory, "Дюна", TitleKind.MOVIE, TitleStatus.WATCHED)
    announce(session_factory, dune)

    answer = client.post("/feed/sequels", data={"kind": "movie", "sequel_id": "3"}, headers=HTMX)

    added = [t for t in run(tracker.list_titles()) if t.name == "Дюна: Часть третья"]
    assert answer.status_code == 200 and "<html" not in answer.text and len(added) == 1
    assert f'<a class="row-action button-link" href="/titles/{added[0].id}">В списке</a>' in answer.text
    assert "Следить" not in answer.text


def test_follow_without_htmx_goes_back_to_the_feed(client, tracker, session_factory):
    dune = put_title(session_factory, "Дюна", TitleKind.MOVIE, TitleStatus.WATCHED)
    announce(session_factory, dune)

    answer = client.post("/feed/sequels", data={"kind": "movie", "sequel_id": "3"})

    assert answer.status_code == 303 and answer.headers["location"] == "/"
    assert len(run(tracker.list_titles())) == 2


def test_follow_while_the_source_is_down_is_a_line_on_top_of_the_fresh_feed(client, tracker, session_factory, movies, caplog):
    dune = put_title(session_factory, "Дюна", TitleKind.MOVIE, TitleStatus.WATCHED)
    announce(session_factory, dune)
    movies.failing = True

    with caplog.at_level(logging.WARNING):
        answer = client.post("/feed/sequels", data={"kind": "movie", "sequel_id": "3"}, headers=HTMX)

    assert answer.status_code == 200 and "Следить" in answer.text
    assert answer.text.index("Не удалось связаться с TMDb. Попробуйте чуть позже") < answer.text.index('id="soon-heading"')
    assert len(run(tracker.list_titles())) == 1 and "TMDb is down" in caplog.text


def test_follow_while_the_source_is_down_without_htmx_says_so_on_the_page(client, session_factory, movies):
    dune = put_title(session_factory, "Дюна", TitleKind.MOVIE, TitleStatus.WATCHED)
    announce(session_factory, dune)
    movies.failing = True

    answer = client.post("/feed/sequels", data={"kind": "movie", "sequel_id": "3"})

    assert answer.status_code == 303
    assert "Не удалось связаться с TMDb. Попробуйте чуть позже" in client.get("/").text
    assert "Не удалось связаться" not in client.get("/").text  # said once


def test_follow_of_a_sequel_the_source_does_not_know_says_so(client, session_factory):
    dune = put_title(session_factory, "Дюна", TitleKind.MOVIE, TitleStatus.WATCHED)
    announce(session_factory, dune, "9")

    answer = client.post("/feed/sequels", data={"kind": "movie", "sequel_id": "9"}, headers=HTMX)

    assert "TMDb больше не знает этот тайтл. Поищите заново" in answer.text


@pytest.mark.parametrize("kind", ["game", "series", ""])
def test_follow_of_a_kind_without_sequels_is_refused(client, tracker, kind):
    answer = client.post("/feed/sequels", data={"kind": kind, "sequel_id": "3"}, headers=HTMX)

    assert answer.status_code == 200 and "Такого типа нет" in answer.text and len(run(tracker.list_titles())) == 0


# ---- errors ------------------------------------------------------------------------------------------------------

def test_watched_of_a_title_that_is_gone_is_the_fresh_feed_with_a_line(client, session_factory):
    other = put_title(session_factory, "Укрытие")
    put_season(session_factory, other, 1, {1: at(0)})

    answer = client.post("/feed/titles/999/watched", headers=HTMX)

    assert answer.status_code == 200 and answer.text.index(GONE) < answer.text.index('id="soon-heading"')
    assert "Укрытие" in answer.text


def test_a_number_too_long_for_a_title_is_gone_and_the_core_is_not_asked(client, monkeypatch):
    async def asked(self, *args):
        raise AssertionError("the core was asked")

    monkeypatch.setattr(Tracker, "mark_watched", asked)

    answer = client.post(f"/feed/titles/{10 ** 20}/watched", headers=HTMX)

    assert answer.status_code == 200 and GONE in answer.text


def test_gone_without_htmx_crosses_to_the_page_as_a_notice(client):
    answer = client.post("/feed/titles/999/watched")

    assert answer.status_code == 303 and GONE in client.get("/").text


def test_an_unexpected_error_in_a_press_is_told_in_a_fragment_with_a_refresh(client, monkeypatch, caplog):
    async def broken(self, *args):
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(Tracker, "mark_watched", broken)

    with caplog.at_level(logging.ERROR):
        answer = client.post("/feed/titles/1/watched", headers=HTMX)

    assert answer.status_code == 200 and "Не получилось. Попробуйте ещё раз; подробности — в журнале" in answer.text
    assert '<a href="/">Обновить</a>' in answer.text
    assert any(r.exc_info for r in caplog.records if "unexpected error" in r.getMessage())


def test_an_unexpected_error_on_the_page_is_a_500_with_a_refresh(client, monkeypatch):
    async def broken(self):
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(Tracker, "feed", broken)

    page = client.get("/")

    assert page.status_code == 500 and "Не получилось" in page.text and '<a href="/">Обновить</a>' in page.text


# ---- escaping, sign-in, rule 10 ----------------------------------------------------------------------------------

def test_a_name_and_a_text_with_markup_are_text(client, session_factory):
    show = put_title(session_factory, '<script>alert("x")</script>')
    put_season(session_factory, show, 1, {1: at(0)})
    put_event(session_factory, show, EPISODE_OUT, '📺 <b onclick="x()">вышла</b>\n<i>серия</i> "5"', at(0), {"season": 1, "episode": 1})

    html = client.get("/").text

    assert "<script>alert" not in html and "&lt;script&gt;alert" in html
    assert "<b onclick" not in html and "&lt;b onclick" in html and "<i>серия" not in html


def test_the_presses_need_a_sign_in_and_a_foreign_origin_is_refused(client, tracker, session_factory):
    film = put_title(session_factory, "Дюна", TitleKind.MOVIE)
    anonymous = TestClient(client.app, follow_redirects=False)

    assert anonymous.get("/").status_code == 303
    assert anonymous.post(f"/feed/titles/{film}/watched").status_code == 303
    assert anonymous.post("/feed/sequels", data={"kind": "movie", "sequel_id": "3"}).status_code == 303
    foreign = {"Origin": "http://evil.example"}
    assert client.post(f"/feed/titles/{film}/watched", headers=foreign).status_code == 403
    assert client.post("/feed/sequels", data={"kind": "movie", "sequel_id": "3"}, headers=foreign).status_code == 403
    assert run(tracker.title_card(film)).status == TitleStatus.WANT


def test_the_feed_module_reaches_the_core_only_through_the_facade_and_pure_modules():
    tree = ast.parse((ROOT / "app" / "web" / "feed.py").read_text(encoding="utf-8"))
    seen = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("app.tracker")]

    assert seen and set(seen) <= {"app.tracker.cards", "app.tracker.core", "app.tracker.kinds", "app.tracker.models"}


def test_the_feed_templates_have_no_script_and_no_inline_style():
    for name in ("feed.html", "feed_body.html"):
        text = (ROOT / "app" / "web" / "templates" / name).read_text(encoding="utf-8")
        assert "<script" not in text and "style=" not in text, name
