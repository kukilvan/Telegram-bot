"""The archive in the browser, and the search by name in the list: the rows with the score, the four rows of links, the
search as a fragment with the address for the browser, the empty states, the escaping. On the real core (rows put straight
into the database)."""

import re
from datetime import datetime, timedelta, timezone

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import SeasonRecord, Title, TitleKind, TitleStatus
from app.web import create_web_app
from app.web.posters import image_sources

PASSWORD = "correct horse battery"
T0 = datetime(2026, 10, 24, 12, 0)
HTMX = {"HX-Request": "true"}
WATCHED, DROPPED = TitleStatus.WATCHED, TitleStatus.DROPPED


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def client(session_factory, tmp_path):
    tracker = Tracker(session_factory, clock=lambda: T0.replace(tzinfo=timezone.utc), sender=FakeSender())
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


def put(session_factory, name, kind=TitleKind.MOVIE, status=WATCHED, *, score=None, changed=0, genres=(), seasons=(),
        original=None, year=None):
    with session_factory() as session:
        title = Title(
            kind=kind, name=name, original_name=original or name, genres=list(genres), status=status,
            tracking_enabled=True, added_at=T0, status_changed_at=T0 + timedelta(minutes=changed), score=score, year=year,
        )
        session.add(title)
        session.flush()
        for number, (watched, season_score) in enumerate(seasons, 1):
            session.add(SeasonRecord(title_id=title.id, number=number, name=f"S{number}", watched=watched, score=season_score))
        session.commit()
        return title.id


def shown(html):
    return re.findall(r'<span class="title-name"><span aria-hidden="true">[^<]*</span> ([^<]*)</span>', html)


def links(html, label):
    pattern = r'<a href="([^"]*)"(?: aria-current="true")?>' + re.escape(label) + "</a>"
    return [a.replace("&amp;", "&") for a in re.findall(pattern, html)]


def current(html):
    return re.findall(r'<a href="[^"]*" aria-current="true">([^<]*)</a>', html)


def scores_in_rows(html):
    """The score of each row, top to bottom; an empty string for a row without one."""
    rows = re.findall(r'<a class="row-link" href="[^"]*">(.*?)</a>', html, re.S)
    return [(re.search(r'row-score">([^<]*)<', row) or [None, ""])[1] for row in rows]


@pytest.fixture
def archive(session_factory):
    """Four titles in the archive, a film and a series on the way, and a film that waits."""
    return {
        "dune": put(session_factory, "Дюна", score=28, changed=1, genres=["драма", "Фантастика"], year=2021),
        "avatar": put(session_factory, "Аватар", score=30, changed=0, genres=["Фантастика"]),
        "boys": put(
            session_factory, "Пацаны", TitleKind.SERIES, WATCHED, changed=2, genres=["Драма"],
            seasons=[(True, 27), (True, 25)],
        ),
        "quit": put(session_factory, "Бросил сериал", TitleKind.SERIES, DROPPED, changed=3, genres=["Боевик"]),
        "going": put(session_factory, "Идёт", TitleKind.SERIES, TitleStatus.IN_PROGRESS, genres=["Драма"]),
        "want": put(session_factory, "Хочу", status=TitleStatus.WANT, genres=["Ужасы"]),
    }


# ---- the page ----------------------------------------------------------------------------------------------------

def test_the_archive_is_a_page_of_its_own_with_the_best_score_first(client, archive):
    page = client.get("/archive")

    assert page.status_code == 200 and "<h1>Архив</h1>" in page.text and "Скоро будет" not in page.text
    assert shown(page.text) == ["Аватар", "Дюна", "Пацаны", "Бросил сериал"]  # 10, 9+, 9− (the average), no score
    assert "Показано 4 тайтла" in page.text
    assert current(page.text) == ["Все", "Все жанры", "Весь архив", "По оценке"]
    assert page.text.count('aria-current="page"') == 1  # the menu: the archive


def test_the_score_stands_on_the_right_of_the_row_and_an_average_has_the_mark(client, archive):
    html = client.get("/archive").text

    assert scores_in_rows(html) == ["10", "9+", "ср. 9−", ""]
    row = re.search(r'<a class="row-link" href="/titles/%d">(.*?)</a>' % archive["dune"], html, re.S).group(1)
    assert "🎬" in row and "Дюна" in row and ">2021<" in row and 'class="row-status">Просмотрено<' in row


def test_the_whole_row_is_a_link_to_the_card_and_nothing_outside_the_archive_is_shown(client, archive):
    html = client.get("/archive").text

    assert 'href="/titles/%d"' % archive["avatar"] in html
    assert "Идёт" not in html and "Хочу" not in html


def test_the_orders(client, archive):
    assert shown(client.get("/archive?order=archived").text) == ["Бросил сериал", "Пацаны", "Дюна", "Аватар"]
    assert shown(client.get("/archive?order=name").text) == ["Аватар", "Бросил сериал", "Дюна", "Пацаны"]
    assert current(client.get("/archive?order=archived").text)[-1] == "Сначала недавние"
    assert current(client.get("/archive?order=name").text)[-1] == "По названию"


def test_the_filters_by_kind_and_status(client, archive):
    assert shown(client.get("/archive?kind=series").text) == ["Пацаны", "Бросил сериал"]
    assert shown(client.get("/archive?kind=movie").text) == ["Аватар", "Дюна"]
    assert shown(client.get("/archive?status=dropped").text) == ["Бросил сериал"]
    assert shown(client.get("/archive?status=watched&kind=series").text) == ["Пацаны"]
    assert current(client.get("/archive?kind=series&status=dropped").text) == ["Сериалы", "Все жанры", "Бросил", "По оценке"]


def test_the_genres_are_those_of_the_archive_merged_and_in_alphabetical_order(client, archive):
    html = client.get("/archive").text

    row = re.search(r'<nav class="filters" aria-label="Жанр">(.*?)</nav>', html, re.S).group(1)
    assert re.findall(r">([^<]+)</a>", row) == ["Все жанры", "Боевик", "Драма", "Фантастика"]  # not «Ужасы» of «Хочу»
    assert shown(client.get("/archive?genre=Драма").text) == ["Дюна", "Пацаны"]  # «драма» and «Драма» are one genre
    assert current(client.get("/archive?genre=Драма").text) == ["Все", "Драма", "Весь архив", "По оценке"]


def test_the_genres_follow_the_kind_and_the_status(client, archive):
    html = client.get("/archive?kind=series&status=dropped").text

    row = re.search(r'<nav class="filters" aria-label="Жанр">(.*?)</nav>', html, re.S).group(1)
    assert re.findall(r">([^<]+)</a>", row) == ["Все жанры", "Боевик"]


@pytest.mark.parametrize(
    "query",
    ["kind=game", "status=want", "status=foo", "order=sideways", "order=added", "genre=Вестерн", "kind=&genre=&status=&order=", "q="],
)
def test_a_value_nobody_knows_counts_as_none(client, archive, query):
    page = client.get(f"/archive?{query}")

    assert page.status_code == 200 and shown(page.text) == ["Аватар", "Дюна", "Пацаны", "Бросил сериал"]
    assert current(page.text) == ["Все", "Все жанры", "Весь архив", "По оценке"]


def test_the_links_change_one_thing_and_keep_the_others_and_the_query(client, archive):
    html = client.get("/archive?q=а&kind=series&genre=Драма&status=watched&order=name").text

    q, genre = quote("а"), quote("Драма")
    assert links(html, "Все") == [f"/archive?q={q}&genre={genre}&status=watched&order=name"]
    assert links(html, "Фильмы") == [f"/archive?q={q}&kind=movie&genre={genre}&status=watched&order=name"]
    assert links(html, "Все жанры") == [f"/archive?q={q}&kind=series&status=watched&order=name"]
    assert links(html, "Драма") == [f"/archive?q={q}&kind=series&genre={genre}&status=watched&order=name"]
    assert links(html, "Весь архив") == [f"/archive?q={q}&kind=series&genre={genre}&order=name"]
    assert links(html, "Бросил") == [f"/archive?q={q}&kind=series&genre={genre}&status=dropped&order=name"]
    assert links(html, "По оценке") == [f"/archive?q={q}&kind=series&genre={genre}&status=watched"]
    assert links(html, "Сначала недавние") == [f"/archive?q={q}&kind=series&genre={genre}&status=watched&order=archived"]


def test_the_default_archive_has_clean_links(client, archive):
    html = client.get("/archive").text

    assert links(html, "Все") == ["/archive"] and links(html, "По оценке") == ["/archive"]
    assert links(html, "Просмотрено") == ["/archive?status=watched"]
    status_row = re.search(r'<nav class="filters" aria-label="Статус">(.*?)</nav>', html, re.S).group(1)
    assert re.findall(r">([^<]+)</a>", status_row) == ["Весь архив", "Просмотрено", "Бросил"]


# ---- the search --------------------------------------------------------------------------------------------------

def test_the_search_by_name_keeps_the_filters_and_the_field_holds_the_query(client, archive):
    page = client.get("/archive?q=ДЮН&kind=movie")

    assert shown(page.text) == ["Дюна"] and "Показано 1 тайтл" in page.text
    assert 'name="q" type="search" value="ДЮН"' in page.text and 'maxlength="100"' in page.text
    assert '<input type="hidden" name="kind" value="movie">' in page.text
    assert 'name="q" type="hidden"' not in page.text and '<input type="hidden" name="q"' not in page.text


def test_the_search_form_works_without_htmx_and_with_it(client, archive):
    html = client.get("/archive?kind=movie&order=name").text

    form = re.search(r'<form class="find-form"([^>]*)>', html).group(1)
    assert 'method="get"' in form and 'action="/archive"' in form  # without HTMX the form sends the page itself
    assert 'hx-get="/archive/results"' in form and 'hx-trigger="input delay:300ms, submit"' in form
    assert 'hx-target="#results"' in form and 'hx-sync="this:replace"' in form
    assert '<input type="hidden" name="order" value="name">' in html


def test_the_fragment_is_the_results_with_the_address_for_the_browser(client, archive):
    response = client.get("/archive/results?q=дюн&kind=movie&order=name", headers=HTMX)

    assert response.status_code == 200
    assert response.headers["HX-Push-Url"] == "/archive?q=%D0%B4%D1%8E%D0%BD&kind=movie&order=name"
    assert "<html" not in response.text and "<h1>" not in response.text and 'type="search"' not in response.text
    assert shown(response.text) == ["Дюна"] and 'aria-label="Тип"' in response.text and "Показано 1 тайтл" in response.text


def test_the_fragment_without_a_query_pushes_the_clean_address(client, archive):
    response = client.get("/archive/results?q=", headers=HTMX)

    assert response.headers["HX-Push-Url"] == "/archive" and len(shown(response.text)) == 4


def test_the_fragment_of_a_plain_request_sends_the_page(client, archive):
    response = client.get("/archive/results?q=дюн&kind=movie")

    assert response.status_code == 303 and response.headers["location"] == "/archive?q=%D0%B4%D1%8E%D0%BD&kind=movie"


def test_the_query_is_cut_to_a_hundred_letters_and_spaces_at_the_ends_do_not_count(client, archive):
    html = client.get("/archive?q=%20%20дюна%20%20").text
    assert shown(html) == ["Дюна"] and 'value="дюна"' in html

    long = client.get("/archive?q=" + "я" * 300).text
    assert 'value="' + "я" * 100 + '"' in long


def test_the_search_finds_by_the_original_name_and_yo_is_ye(client, session_factory):
    put(session_factory, "Чёрное зеркало", TitleKind.SERIES, original="Black Mirror")

    assert shown(client.get("/archive?q=black").text) == ["Чёрное зеркало"]
    assert shown(client.get("/archive?q=черное").text) == ["Чёрное зеркало"]


# ---- the empty states --------------------------------------------------------------------------------------------

def test_an_empty_archive_says_what_gets_there(client, session_factory):
    put(session_factory, "Хочу", status=TitleStatus.WANT)

    html = client.get("/archive").text

    assert "В архиве пока ничего нет. Сюда попадает просмотренное и брошенное" in html and "Сбросить фильтры" not in html
    assert "Показано" not in html


def test_a_filter_nothing_fits_says_so_and_resets(client, archive):
    html = client.get("/archive?kind=movie&status=dropped").text

    assert "Под этот фильтр ничего не подходит" in html
    assert links(html, "Сбросить фильтры") == ["/archive"]
    assert "Показано" not in html


def test_a_filter_on_an_empty_archive_still_says_the_archive_is_empty(client, session_factory):
    html = client.get("/archive?kind=movie").text

    assert "В архиве пока ничего нет" in html and "Под этот фильтр" not in html


def test_nothing_found_names_the_query_and_resets_only_the_search(client, archive):
    html = client.get("/archive?q=нет+такого&kind=movie&order=name").text

    assert "Ничего не нашлось по запросу «нет такого»" in html
    assert links(html, "Сбросить поиск") == ["/archive?kind=movie&order=name"]
    assert "Показано" not in html


# ---- escaping ----------------------------------------------------------------------------------------------------

def test_a_name_and_a_query_with_markup_are_text_in_the_archive_and_the_list(client, session_factory):
    evil = '<script>alert("x")</script> \'q\''
    put(session_factory, evil, genres=['<b>жанр</b>'])

    for address in ("/archive", "/list?status=all", "/archive?genre=%3Cb%3E%D0%B6%D0%B0%D0%BD%D1%80%3C/b%3E"):
        html = client.get(address).text
        assert "<script>alert" not in html and "&lt;script&gt;alert" in html, address
    for address in ("/archive?q=", "/list?status=all&q="):
        html = client.get(address + "%3Cscript%3Eнет").text
        assert "<script>" not in html and "«&lt;script&gt;нет»" in html, address
        assert 'value="&lt;script&gt;нет"' in html
    assert "<b>жанр</b>" not in client.get("/archive").text


# ---- the list: the search and the score --------------------------------------------------------------------------

@pytest.fixture
def listed(session_factory):
    return {
        "dune": put(session_factory, "Дюна", TitleKind.MOVIE, TitleStatus.WANT, changed=0),
        "boys": put(session_factory, "Пацаны", TitleKind.SERIES, TitleStatus.IN_PROGRESS, seasons=[(True, 27), (False, None)]),
        "seen": put(session_factory, "Дюна: часть вторая", TitleKind.MOVIE, WATCHED, score=28),
        "jjk": put(session_factory, "Магическая битва", TitleKind.ANIME, TitleStatus.WAITING),
    }


def test_the_list_searches_by_name_and_the_field_keeps_the_query(client, listed):
    page = client.get("/list?q=дюн")

    assert shown(page.text) == ["Дюна"]  # the archive is not in the list by default
    assert 'name="q" type="search" value="дюн"' in page.text
    assert shown(client.get("/list?q=дюн&status=all").text) == ["Дюна: часть вторая", "Дюна"]


def test_the_list_search_is_in_every_link_and_in_the_mode_of_choosing(client, listed):
    html = client.get("/list?q=дюн&status=all&kind=movie").text

    assert links(html, "Фильмы") == ["/list?kind=movie&status=all&q=%D0%B4%D1%8E%D0%BD"]
    assert links(html, "По названию") == ["/list?kind=movie&status=all&order=name&q=%D0%B4%D1%8E%D0%BD"]
    assert re.search(r'href="(/list\?[^"]*select=1[^"]*)"', html).group(1).replace("&amp;", "&") == (
        "/list?kind=movie&status=all&q=%D0%B4%D1%8E%D0%BD&select=1"
    )

    chosen = client.get("/list?q=дюн&status=all&select=1").text
    assert '<input type="hidden" name="q" value="дюн">' in chosen  # the ticks go on asking with the query
    assert "Удалить выбранные" in chosen and shown(chosen) == ["Дюна: часть вторая", "Дюна"]


def test_the_search_form_of_the_list_keeps_the_filters_and_the_mode(client, listed):
    html = client.get("/list?status=all&order=name&select=1").text

    form = re.search(r'<form class="find-form"([^>]*)>(.*?)</form>', html, re.S)
    assert 'action="/list"' in form.group(1) and 'hx-get="/list/results"' in form.group(1)
    for name, value in (("status", "all"), ("order", "name"), ("select", "1")):
        assert f'<input type="hidden" name="{name}" value="{value}">' in form.group(2)


def test_the_list_fragment_has_the_address_and_keeps_the_mode(client, listed):
    response = client.get("/list/results?q=дюн&status=all&select=1", headers=HTMX)

    assert response.headers["HX-Push-Url"] == "/list?status=all&q=%D0%B4%D1%8E%D0%BD&select=1"
    assert "<html" not in response.text and 'type="search"' not in response.text
    assert 'id="selection-form"' in response.text and shown(response.text) == ["Дюна: часть вторая", "Дюна"]
    assert client.get("/list/results?q=дюн").status_code == 303  # not HTMX: the page itself


def test_the_list_says_nothing_was_found_and_resets_only_the_search(client, listed):
    html = client.get("/list?q=нет+такого&kind=movie").text

    assert "Ничего не нашлось по запросу «нет такого»" in html
    assert links(html, "Сбросить поиск") == ["/list?kind=movie"]


def test_deleting_several_comes_back_to_the_list_with_the_query(client, session_factory, listed):
    question = client.get(f"/list/confirm?id={listed['dune']}&q=дюн&status=all").text
    assert '<input type="hidden" name="q" value="дюн">' in question

    response = client.post("/list/delete", data={"id": [str(listed["dune"])], "q": "дюн", "status": "all"})

    assert response.status_code == 303 and response.headers["location"] == "/list?status=all&q=%D0%B4%D1%8E%D0%BD"


def test_the_list_row_shows_the_score_when_it_is_visible(client, listed):
    html = client.get("/list?status=all").text

    by_name = dict(zip(shown(html), scores_in_rows(html)))
    assert by_name == {"Магическая битва": "", "Дюна: часть вторая": "9+", "Пацаны": "ср. 9", "Дюна": ""}
