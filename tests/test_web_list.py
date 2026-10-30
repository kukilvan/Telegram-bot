"""The list in the browser: the rows, the filters and the order as links, the empty states, the mode of choosing and
deleting several titles at once. On the real core (rows put straight into the database); the presses go through the web
app."""

import logging
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.runtime import Health
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import Title, TitleKind, TitleStatus
from app.web import create_web_app
from app.web.posters import image_sources

PASSWORD = "correct horse battery"
T0 = datetime(2026, 10, 24, 12, 0)
HTMX = {"HX-Request": "true"}


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory):
    return Tracker(session_factory, clock=lambda: T0.replace(tzinfo=timezone.utc), sender=FakeSender())


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


def put(session_factory, name, kind=TitleKind.MOVIE, status=TitleStatus.WANT, minutes=0, poster=None, year=None):
    with session_factory() as session:
        title = Title(
            kind=kind, name=name, original_name=name, genres=[], status=status, tracking_enabled=True, year=year,
            added_at=T0 + timedelta(minutes=minutes), status_changed_at=T0, poster_path=poster,
        )
        session.add(title)
        session.commit()
        return title.id


def shown(html):
    """The names of the rows, top to bottom."""
    return re.findall(r'<span class="title-name"><span aria-hidden="true">[^<]*</span> ([^<]*)</span>', html)


def links(html, label):
    """The addresses of the filter links with this label (one per row of filters that has it)."""
    pattern = r'<a href="([^"]*)"(?: aria-current="true")?>' + re.escape(label) + "</a>"
    return [a.replace("&amp;", "&") for a in re.findall(pattern, html)]


def current(html):
    """The labels of the filter links that are marked as chosen."""
    return re.findall(r'<a href="[^"]*" aria-current="true">([^<]*)</a>', html)


def remaining(session_factory):
    with session_factory() as session:
        return sorted(session.scalars(select(Title.name)))


@pytest.fixture
def mixed(session_factory):
    """A film, a series, a dropped series, an anime and a watched film, added in this order."""
    return {
        "dune": put(session_factory, "Дюна", minutes=0, year=2021, poster="/dune.jpg"),
        "boys": put(session_factory, "Пацаны", TitleKind.SERIES, TitleStatus.IN_PROGRESS, minutes=1),
        "quit": put(session_factory, "Бросил сериал", TitleKind.SERIES, TitleStatus.DROPPED, minutes=2),
        "jjk": put(session_factory, "Магическая битва", TitleKind.ANIME, TitleStatus.WAITING, minutes=3),
        "seen": put(session_factory, "Аватар", TitleKind.MOVIE, TitleStatus.WATCHED, minutes=4),
    }


# ---- the rows ----------------------------------------------------------------------------------------------------

def test_the_list_opens_without_the_archive_newest_first(client, mixed):
    page = client.get("/list")

    assert page.status_code == 200 and "<h1>Список</h1>" in page.text
    assert shown(page.text) == ["Магическая битва", "Пацаны", "Дюна"]
    assert "Показано 3 тайтла" in page.text
    assert current(page.text) == ["Все", "Без архива", "Сначала новые"]
    assert page.text.count('aria-current="page"') == 1  # the menu: the list


def test_a_row_is_one_link_to_the_card_with_poster_icon_year_and_status(client, mixed):
    html = client.get("/list").text

    row = re.search(r'<a class="row-link" href="/titles/%d">(.*?)</a>' % mixed["dune"], html, re.S).group(1)
    assert "https://image.tmdb.org/t/p/w92/dune.jpg" in row and 'loading="lazy"' in row
    assert "🎬" in row and "Дюна" in row and ">2021<" in row and 'class="row-status">Хочу<' in row


def test_a_row_without_a_poster_has_the_icon_of_its_kind(client, mixed):
    html = client.get("/list?kind=anime").text

    assert 'class="poster-icon" aria-hidden="true">🎌' in html and "<img" not in html


def test_the_whole_list_shows_the_archive_too(client, mixed):
    page = client.get("/list?status=all")

    assert shown(page.text) == ["Аватар", "Магическая битва", "Бросил сериал", "Пацаны", "Дюна"]
    assert "Показано 5 тайтлов" in page.text and current(page.text) == ["Все", "Весь список", "Сначала новые"]


def test_by_name_is_alphabetical(client, mixed):
    page = client.get("/list?status=all&order=name")

    assert shown(page.text) == ["Аватар", "Бросил сериал", "Дюна", "Магическая битва", "Пацаны"]
    assert current(page.text) == ["Все", "Весь список", "По названию"]


@pytest.mark.parametrize(
    "query, expected",
    [
        ("kind=movie", ["Дюна"]),
        ("kind=series", ["Пацаны"]),
        ("kind=anime", ["Магическая битва"]),
        ("kind=series&status=all", ["Бросил сериал", "Пацаны"]),
        ("status=dropped", ["Бросил сериал"]),
        ("status=watched", ["Аватар"]),
        ("status=want", ["Дюна"]),
        ("status=in_progress", ["Пацаны"]),
        ("status=waiting", ["Магическая битва"]),
        ("status=to_finish", []),
    ],
)
def test_each_filter_asks_the_core_for_its_rows(client, mixed, query, expected):
    assert shown(client.get(f"/list?{query}").text) == expected


@pytest.mark.parametrize("query", ["kind=game", "status=foo", "order=sideways", "kind=&status=&order=", "select=maybe"])
def test_a_value_nobody_knows_counts_as_none(client, mixed, query):
    page = client.get(f"/list?{query}")

    assert page.status_code == 200 and shown(page.text) == ["Магическая битва", "Пацаны", "Дюна"]
    assert current(page.text) == ["Все", "Без архива", "Сначала новые"]


@pytest.mark.parametrize("count, word", [(1, "тайтл"), (2, "тайтла"), (5, "тайтлов"), (11, "тайтлов"), (21, "тайтл")])
def test_the_count_follows_the_number(client, session_factory, count, word):
    for number in range(count):
        put(session_factory, f"Тайтл {number}", minutes=number)

    assert f"Показано {count} {word}" in client.get("/list").text


# ---- the links ---------------------------------------------------------------------------------------------------

def test_the_filter_links_change_one_thing_and_keep_the_others(client, mixed):
    html = client.get("/list?kind=series&status=dropped&order=name").text

    assert links(html, "Все") == ["/list?status=dropped&order=name"]
    assert links(html, "Фильмы") == ["/list?kind=movie&status=dropped&order=name"]
    assert links(html, "Аниме") == ["/list?kind=anime&status=dropped&order=name"]
    assert links(html, "Без архива") == ["/list?kind=series&order=name"]
    assert links(html, "Хочу") == ["/list?kind=series&status=want&order=name"]
    assert links(html, "Весь список") == ["/list?kind=series&status=all&order=name"]
    assert links(html, "Сначала новые") == ["/list?kind=series&status=dropped"]
    assert links(html, "По названию") == ["/list?kind=series&status=dropped&order=name"]
    assert current(html) == ["Сериалы", "Бросил", "По названию"]


def test_the_default_list_has_clean_links_and_every_status_in_order(client, mixed):
    html = client.get("/list").text

    assert links(html, "Все") == ["/list"] and links(html, "Без архива") == ["/list"]
    assert links(html, "Просмотрено") == ["/list?status=watched"]
    status_row = re.search(r'<nav class="filters" aria-label="Статус">(.*?)</nav>', html, re.S).group(1)
    assert re.findall(r">([^<]+)</a>", status_row) == [
        "Без архива", "Хочу", "В процессе", "Жду", "Досмотреть", "Просмотрено", "Бросил", "Весь список",
    ]


def test_the_links_do_not_carry_the_mode_of_choosing(client, mixed):
    html = client.get("/list?select=1").text

    assert "select" not in "".join(links(html, "Фильмы") + links(html, "По названию"))


# ---- the empty states --------------------------------------------------------------------------------------------

def test_an_empty_list_says_so_and_points_to_the_search(client):
    html = client.get("/list").text

    assert "В списке пока ничего нет." in html and '<a href="/search">Найдите тайтл в Поиске</a>' in html
    assert "Показано" not in html and "Удалить несколько" not in html


def test_a_filter_nothing_fits_says_so_and_can_be_reset(client, mixed):
    html = client.get("/list?kind=movie&status=dropped").text

    assert "Под этот фильтр ничего не подходит" in html
    assert '<a href="/list?status=all">Сбросить фильтры</a>' in html and "Показано" not in html


def test_a_list_with_only_archive_titles_does_not_say_it_is_empty(client, session_factory):
    put(session_factory, "Аватар", status=TitleStatus.WATCHED)

    html = client.get("/list").text

    assert "Под этот фильтр ничего не подходит" in html and "пока ничего нет" not in html


def test_a_filter_on_an_empty_list_says_the_list_is_empty(client):
    assert "В списке пока ничего нет." in client.get("/list?kind=anime").text


# ---- the text is text --------------------------------------------------------------------------------------------

def test_a_name_with_markup_is_text_in_the_list_and_in_the_question(client, session_factory):
    evil = put(session_factory, '<script>alert("x")</script> & "кавычки"')

    page = client.get("/list").text
    selecting = client.get("/list?select=1").text
    question = client.get("/list/confirm", params={"id": evil}, headers=HTMX).text

    for html in (page, selecting, question):
        assert "<script>alert" not in html and "&lt;script&gt;alert" in html


# ---- the mode of choosing ----------------------------------------------------------------------------------------

def test_in_the_mode_of_choosing_a_row_is_a_check_mark_and_not_a_link(client, mixed):
    html = client.get("/list?select=1").text

    assert html.count('<input type="checkbox" name="id"') == 3 and 'class="row-link"' not in html
    assert f'name="id" value="{mixed["dune"]}"' in html
    assert 'hx-get="/list/selection"' in html and 'hx-trigger="change"' in html
    assert "Удалить несколько" not in html
    assert '<button type="button" hx-get="/list/confirm"' in html and "disabled>Удалить выбранные (0)" in html
    assert '<a class="button-link" href="/list">Отмена</a>' in html


def test_the_mode_of_choosing_keeps_the_filters_in_the_form_and_the_cancel_link(client, mixed):
    html = client.get("/list?kind=series&status=all&order=name&select=1").text

    assert '<input type="hidden" name="kind" value="series">' in html
    assert '<input type="hidden" name="status" value="all">' in html and '<input type="hidden" name="order" value="name">' in html
    assert '<a class="button-link" href="/list?kind=series&amp;status=all&amp;order=name">Отмена</a>' in html


def test_the_link_into_the_mode_keeps_the_filters(client, mixed):
    html = client.get("/list?kind=series&status=all").text

    assert '<a href="/list?kind=series&amp;status=all&amp;select=1">Удалить несколько</a>' in html


def test_the_button_without_a_script_is_in_noscript(client, mixed):
    html = client.get("/list?select=1").text

    assert '<noscript><button type="submit" form="selection-form">Удалить выбранные</button></noscript>' in html
    assert 'action="/list/confirm"' in html and 'id="selection-form"' in html


def test_nothing_to_choose_from_is_no_mode(client):
    assert "Удалить выбранные" not in client.get("/list?select=1").text


def test_the_strip_says_how_many_are_ticked(client, mixed):
    one = client.get("/list/selection", params=[("id", mixed["dune"])], headers=HTMX)
    two = client.get("/list/selection", params=[("id", mixed["dune"]), ("id", mixed["boys"]), ("id", mixed["dune"])], headers=HTMX)
    none = client.get("/list/selection", headers=HTMX)

    assert "Удалить выбранные (1)" in one.text and " disabled" not in one.text
    assert "Удалить выбранные (2)" in two.text  # the same number twice is one title
    assert "Удалить выбранные (0)" in none.text and re.search(r"<button[^>]* disabled>", none.text)
    assert "<html" not in one.text and '<div id="delete-bar"' in one.text


def test_the_strip_ignores_what_is_not_a_number(client):
    answer = client.get("/list/selection", params=[("id", "abc"), ("id", "-1"), ("id", "1.5"), ("id", "9" * 40), ("id", "7")])

    assert "Удалить выбранные (1)" in answer.text


# ---- the search in the mode of choosing (KI-31) ------------------------------------------------------------------

@pytest.fixture
def three(session_factory):
    """Дюна 1, Дюна: часть вторая 2, Аватар 3 (want, newest last)."""
    return [
        put(session_factory, "Дюна", minutes=0),
        put(session_factory, "Дюна: часть вторая", minutes=1),
        put(session_factory, "Аватар", minutes=2),
    ]


def ticked(html):
    """The numbers of the rows that stand ticked."""
    return [int(n) for n in re.findall(r'<input type="checkbox" name="id" value="(\d+)" checked>', html)]


def rows_of(html):
    return [int(n) for n in re.findall(r'<input type="checkbox" name="id" value="(\d+)"', html)]


def search(client, q, *ids, **filters):
    params = [("select", "1"), ("q", q), *[(name, value) for name, value in filters.items()], *[("id", i) for i in ids]]
    return client.get("/list/results", params=params, headers=HTMX)


def test_the_search_keeps_the_tick_of_a_row_it_still_finds_and_drops_the_one_it_took_away(client, three):
    first, second, third = three

    answer = search(client, "дюн", first, second)  # ticked: 1 and 2; the search keeps 1 and 2 …
    narrowed = search(client, "часть", first, second)  # … and now only 2
    other = search(client, "а", first, third)  # ticked 1 and 3: all three rows have «а», 1 and 3 stay ticked

    assert rows_of(answer.text) == [second, first] and ticked(answer.text) == [second, first]
    assert rows_of(narrowed.text) == [second] and ticked(narrowed.text) == [second]
    assert ticked(other.text) == [third, first] and "Удалить выбранные (2)" in other.text


def test_the_ticked_one_the_search_left_and_the_one_it_added_are_told_apart(client, three):
    first, second, third = three

    answer = search(client, "ава", first, second)  # ticked 1 and 2, the search finds only 3

    assert rows_of(answer.text) == [third] and ticked(answer.text) == []
    assert "Удалить выбранные (0)" in answer.text and re.search(r"<button[^>]* disabled>", answer.text)


def test_the_strip_counts_the_ticked_among_the_shown_rows(client, three):
    first, second, third = three

    answer = search(client, "дюн", first, third)  # 1 is found, 3 is not

    assert "Удалить выбранные (1)" in answer.text and ticked(answer.text) == [first]


def test_the_search_request_carries_the_ticked_rows_and_one_query(client, three):
    html = client.get("/list?select=1&q=дюн&kind=movie").text
    search_form = re.search(r'<form class="find-form".*?</form>', html, re.S).group(0)

    assert 'hx-include="#selection-form input[name=id]"' in search_form and 'hx-get="/list/results"' in search_form
    # the form of the search holds its own field «q» and the filters, not the ticked rows and not a second «q»
    assert search_form.count('name="q"') == 1 and 'name="id"' not in search_form
    assert '<input type="hidden" name="kind" value="movie">' in search_form
    assert '<input type="hidden" name="select" value="1">' in search_form
    assert 'type="hidden" name="q"' not in search_form
    assert 'id="selection-form"' in html  # the ticked rows are in the form the selector points at


def test_the_search_outside_the_mode_has_no_ticks_and_ignores_the_numbers(client, three):
    answer = client.get("/list/results", params=[("q", "дюн"), ("id", three[0])], headers=HTMX)

    assert "checkbox" not in answer.text and "Удалить выбранные" not in answer.text and "Удалить несколько" in answer.text


def test_the_search_keeps_the_filters_and_the_mode_in_the_address_it_pushes(client, three):
    answer = search(client, "дюн", three[0], kind="movie", status="all", order="name")

    assert answer.headers["HX-Push-Url"] == "/list?kind=movie&status=all&order=name&q=%D0%B4%D1%8E%D0%BD&select=1"
    assert ticked(answer.text) == [three[0]]


def test_a_search_that_finds_nothing_in_the_mode_keeps_the_mode_in_the_address(client, three):
    answer = search(client, "ничего такого", three[0])

    assert "Ничего не нашлось по запросу" in answer.text and "checkbox" not in answer.text
    assert answer.headers["HX-Push-Url"].endswith("&select=1") or "select=1" in answer.headers["HX-Push-Url"]


def test_after_a_search_the_question_and_the_deleting_touch_only_what_is_shown_and_ticked(client, session_factory, three):
    first, second, third = three
    found = search(client, "дюн", first, third)  # the rows 1 and 2 are shown; 1 is ticked, 3 is not shown any more
    shown_rows = rows_of(found.text)

    asked = client.get("/list/confirm", params=[("id", n) for n in ticked(found.text)], headers=HTMX)  # the form of the rows sends these
    client.post("/list/delete", data={"id": [str(n) for n in ticked(found.text)]})

    assert shown_rows == [second, first] and ticked(found.text) == [first]
    assert "Удалить 1 тайтл" in asked.text and "«Дюна»" in asked.text and "Аватар" not in asked.text
    assert remaining(session_factory) == ["Аватар", "Дюна: часть вторая"]


def test_without_htmx_the_search_in_the_mode_is_the_plain_form_and_the_ticks_are_gone(client, three):
    answer = client.get("/list/results", params=[("select", "1"), ("q", "дюн"), ("id", three[0])])

    assert answer.status_code == 303 and answer.headers["location"] == "/list?q=%D0%B4%D1%8E%D0%BD&select=1"
    assert ticked(client.get(answer.headers["location"]).text) == []


def test_the_numbers_of_the_search_are_read_like_those_of_the_strip(client, three):
    answer = search(client, "дюн", "abc", "-1", "9" * 40, three[0], three[0])

    assert ticked(answer.text) == [three[0]] and "Удалить выбранные (1)" in answer.text


# ---- the question ------------------------------------------------------------------------------------------------

def test_the_question_names_the_titles_and_holds_exactly_those_numbers(client, mixed):
    ids = [mixed["dune"], mixed["boys"], mixed["jjk"]]

    html = client.get("/list/confirm", params=[("id", i) for i in ids] + [("kind", "series"), ("order", "name")], headers=HTMX).text

    assert "Удалить 3 тайтла со всеми сезонами и событиями? «Дюна», «Пацаны», «Магическая битва»" in html
    assert re.findall(r'name="id" value="(\d+)"', html) == [str(i) for i in ids]
    assert '<input type="hidden" name="kind" value="series">' in html and '<input type="hidden" name="order" value="name">' in html
    assert 'action="/list/delete"' in html and "Да, удалить" in html and "Отмена" in html
    assert 'hx-get="/list/selection"' in html  # «Отмена» brings the strip back
    assert "<html" not in html


def test_the_question_for_one_title_says_one(client, mixed):
    html = client.get("/list/confirm", params={"id": mixed["dune"]}, headers=HTMX).text

    assert "Удалить 1 тайтл со всеми" in html


def test_the_question_names_ten_titles_and_counts_the_rest(client, session_factory):
    ids = [put(session_factory, f"Тайтл {n:02d}", minutes=n) for n in range(1, 14)]

    html = client.get("/list/confirm", params=[("id", i) for i in ids], headers=HTMX).text

    assert "Удалить 13 тайтлов" in html and "«Тайтл 10» и ещё 3" in html and "Тайтл 11" not in html
    assert len(re.findall(r'name="id" value=', html)) == 13  # all of them are deleted, ten are named


def test_a_title_that_is_gone_is_not_asked_about(client, mixed):
    html = client.get("/list/confirm", params=[("id", mixed["dune"]), ("id", 9999)], headers=HTMX).text

    assert "Удалить 1 тайтл" in html and 'value="9999"' not in html


def test_a_question_about_nothing_gives_the_strip_back(client, mixed):
    html = client.get("/list/confirm", params={"id": 9999}, headers=HTMX).text

    assert "Удалить выбранные (0)" in html and "Да, удалить" not in html


def test_without_htmx_the_question_is_a_page_of_its_own(client, mixed):
    page = client.get("/list/confirm", params=[("id", mixed["dune"]), ("kind", "movie")])

    assert page.status_code == 200 and "<html" in page.text and "Удалить 1 тайтл" in page.text
    assert 'href="/list?kind=movie&amp;select=1"' in page.text  # «Отмена» leads back to the rows


def test_without_htmx_a_question_about_nothing_goes_back_to_the_list(client, mixed):
    answer = client.get("/list/confirm", params={"kind": "movie"})

    assert answer.status_code == 303 and answer.headers["location"] == "/list?kind=movie"


# ---- deleting ----------------------------------------------------------------------------------------------------

def test_the_titles_asked_about_are_deleted_and_the_list_opens_with_the_same_filters(client, session_factory, mixed):
    answer = client.post(
        "/list/delete",
        data={"id": [str(mixed["dune"]), str(mixed["boys"])], "kind": "series", "status": "all", "order": "name"},
    )

    assert answer.status_code == 303 and answer.headers["location"] == "/list?kind=series&status=all&order=name"
    assert remaining(session_factory) == ["Аватар", "Бросил сериал", "Магическая битва"]
    page = client.get(answer.headers["location"])
    assert "Удалено: «Дюна», «Пацаны»" in page.text and 'class="notice"' in page.text
    assert "Удалено" not in client.get(answer.headers["location"]).text  # shown once


def test_through_htmx_the_answer_is_a_redirect_header(client, session_factory, mixed):
    answer = client.post("/list/delete", data={"id": str(mixed["dune"])}, headers=HTMX)

    assert answer.status_code == 200 and answer.headers["HX-Redirect"] == "/list"
    assert "Дюна" not in remaining(session_factory)


def test_a_title_already_gone_is_skipped_and_the_others_go(client, session_factory, mixed):
    answer = client.post("/list/delete", data={"id": ["9999", str(mixed["dune"])]})

    html = client.get("/list").text
    assert answer.status_code == 303 and "Удалено: «Дюна»" in html and "9999" not in html
    assert "Дюна" not in remaining(session_factory)


def test_when_all_were_gone_already_the_line_says_so(client, mixed):
    client.post("/list/delete", data={"id": str(mixed["dune"])})
    client.get("/list")  # the line of that deleting is seen

    answer = client.post("/list/delete", data={"id": str(mixed["dune"])})

    assert answer.status_code == 303
    assert "Этих тайтлов уже нет в списке" in client.get("/list").text


def test_an_empty_request_goes_to_the_list_without_a_line(client, mixed):
    answer = client.post("/list/delete", data={"kind": "movie"})

    assert answer.status_code == 303 and answer.headers["location"] == "/list?kind=movie"
    assert 'class="notice"' not in client.get("/list").text


def test_one_failure_does_not_stop_the_others(client, session_factory, mixed, monkeypatch, caplog):
    real = Tracker.delete_title

    async def flaky(self, title_id):
        if title_id == mixed["boys"]:
            raise RuntimeError("the database is gone")
        return await real(self, title_id)

    monkeypatch.setattr(Tracker, "delete_title", flaky)

    with caplog.at_level(logging.ERROR):
        answer = client.post("/list/delete", data={"id": [str(mixed["dune"]), str(mixed["boys"]), str(mixed["jjk"])]})

    assert answer.status_code == 303
    assert remaining(session_factory) == ["Аватар", "Бросил сериал", "Пацаны"]
    html = client.get("/list").text
    assert "Удалено: «Дюна», «Магическая битва»" in html
    assert "Не удалось удалить: «Пацаны». Попробуйте ещё раз" in html
    assert any(r.exc_info for r in caplog.records if "was not deleted" in r.getMessage())


def test_a_long_line_about_the_deleting_fits_the_notice(client, session_factory):
    ids = [put(session_factory, f"Очень длинное название тайтла номер {n:02d} " + "я" * 60, minutes=n) for n in range(12)]

    client.post("/list/delete", data={"id": [str(i) for i in ids]})
    html = client.get("/list").text

    line = re.search(r'<p class="notice" role="status">(.*?)</p>', html).group(1)
    assert line.startswith("Удалено: «Очень длинное") and re.search(r" и ещё \d+$", line)
    assert len(line) <= 300


# ---- the guards --------------------------------------------------------------------------------------------------

def test_a_delete_from_a_foreign_page_is_refused(client, session_factory, mixed):
    answer = client.post("/list/delete", data={"id": str(mixed["dune"])}, headers={"Origin": "http://evil.example"})

    assert answer.status_code == 403 and "Дюна" in remaining(session_factory)


@pytest.mark.parametrize(
    "method, address", [("GET", "/list"), ("GET", "/list/selection"), ("GET", "/list/confirm"), ("POST", "/list/delete")]
)
def test_the_addresses_of_the_list_need_a_sign_in(client, session_factory, mixed, method, address):
    anonymous = TestClient(client.app, follow_redirects=False)

    answer = anonymous.request(method, address, data={"id": str(mixed["dune"])} if method == "POST" else None)

    assert answer.status_code in (303, 401) and "Дюна" not in answer.text
    assert "Дюна" in remaining(session_factory)


def test_a_failure_of_the_core_is_a_sentence_and_not_a_blank_page(client, monkeypatch, caplog):
    async def broken(self, *args, **kwargs):
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(Tracker, "list_titles", broken)

    with caplog.at_level(logging.ERROR):
        answer = client.get("/list")

    assert answer.status_code == 500 and "Не получилось. Попробуйте ещё раз; подробности — в журнале" in answer.text


def test_the_card_leads_on_to_the_real_list_with_the_line(client, mixed):
    answer = client.post(f"/titles/{mixed['dune']}/delete")

    assert answer.headers["location"] == "/list"
    assert "Удалено: «Дюна»" in client.get("/list").text
