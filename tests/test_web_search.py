"""The search in the browser: the page with the switch of the kind, the suggestions (a fragment for HTMX and the whole
page without it), the errors in place of the suggestions or of the button, adding a suggestion. The look is checked
on a fake core; the way «press → database» on the real core with fake sources."""

import asyncio
import re
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.core import SourceFailed, TitleNotFound, Tracker
from app.tracker.db import create_session_factory
from app.tracker.kinds import KINDS
from app.tracker.models import TitleKind
from app.tracker.results import AddResult, WatchableSeason
from app.tracker.seasons import Episode, Season
from app.tracker.sources.tmdb_movies import MovieSnapshot, Suggestion
from app.tracker.sources.tmdb_series import SeriesSnapshot
from app.web import create_web_app
from app.web.posters import image_sources

PASSWORD = "correct horse battery"
HTMX = {"HX-Request": "true"}
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
SERIES_NOTE = "Аниме лучше искать в «Аниме»"

DUNE = Suggestion(TitleKind.MOVIE, "438631", "Дюна", "Dune", 2021, poster_path="/dune.jpg")
DUNE_2 = Suggestion(TitleKind.MOVIE, "693134", "Дюна: Часть вторая", "Dune: Part Two", 2024, title_id=7)
NASTY = Suggestion(TitleKind.MOVIE, "666", '<script>alert("x")</script> & «Q»', '"><img src=x onerror=y>', 2000)
JJK = Suggestion(
    TitleKind.ANIME, "40748", "Магическая битва", "Jujutsu Kaisen", 2020,
    poster_path="https://shikimori.io/uploads/poster/animes/40748/a.jpeg",
)


class FakeTracker:
    """The one door the pages use: what the search asks for, and a record of the calls."""

    def __init__(self, suggestions=(), error=None, added=AddResult(5, created=True), seasons=()):
        self.suggestions = list(suggestions)
        self.error = error
        self.added = added
        self.seasons = list(seasons)
        self.searched = []
        self.adds = []

    async def overview(self):
        raise RuntimeError("no status line in these tests")

    async def search(self, kind, query):
        self.searched.append((kind, query))
        if self.error is not None:
            raise self.error
        return self.suggestions

    async def add_title(self, kind, external_id):
        self.adds.append((kind, external_id))
        if self.error is not None:
            raise self.error
        return self.added

    async def watchable_seasons(self, title_id):
        return self.seasons


def make_client(tracker, tmp_path):
    health = Health()
    app = create_web_app(
        health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker,
        image_sources=image_sources("https://shikimori.io"),
    )
    client = TestClient(app, follow_redirects=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


def failing(cause):
    try:
        raise SourceFailed("tmdb_movie") from cause
    except SourceFailed as exc:
        return exc


def checked(html):
    return re.findall(r'<input type="radio" name="kind" value="(\w+)" checked>', html)


def add_buttons(html):
    """(kind, id) of every «Добавить» of the suggestions."""
    return re.findall(
        r'<input type="hidden" name="kind" value="(\w+)">\s*<input type="hidden" name="external_id" value="([^"]+)">',
        html,
    )


# ---- the page --------------------------------------------------------------------------------------------------

def test_the_page_has_the_switch_the_field_and_the_menu_with_the_search_marked(tmp_path):
    client = make_client(FakeTracker(), tmp_path)

    response = client.get("/search")

    html = response.text
    assert response.status_code == 200 and "<h1>Поиск</h1>" in html
    assert [label for label in re.findall(r'<input type="radio" name="kind" value="\w+"(?: checked)?> <span>(\w+)</span>', html)] == [
        "Фильм", "Сериал", "Аниме",
    ]
    assert "Название — по-русски или по-английски" in html and "autofocus" in html and "Найти" in html
    assert '<a href="/search" aria-current="page">Поиск</a>' in html and "Скоро будет" not in html


def test_the_first_search_is_for_a_film(tmp_path):
    assert checked(make_client(FakeTracker(), tmp_path).get("/search").text) == ["movie"]


def test_the_kind_of_the_last_search_is_remembered_in_the_session(tmp_path):
    client = make_client(FakeTracker(), tmp_path)

    client.get("/search/suggestions", params={"kind": "anime", "q": "би"}, headers=HTMX)

    assert checked(client.get("/search").text) == ["anime"]


def test_the_kind_in_the_address_wins_over_the_remembered_one_and_an_unknown_one_counts_as_none(tmp_path):
    client = make_client(FakeTracker(), tmp_path)
    client.get("/search/suggestions", params={"kind": "anime", "q": "би"}, headers=HTMX)

    assert checked(client.get("/search?kind=series").text) == ["series"]
    assert checked(client.get("/search?kind=game").text) == ["anime"]


def test_the_form_asks_after_a_pause_at_a_change_and_at_enter_and_drops_a_stale_request(tmp_path):
    html = make_client(FakeTracker(), tmp_path).get("/search").text

    form = re.search(r'<form class="search-form"[^>]*>', html).group(0)
    assert 'method="get" action="/search"' in form and 'hx-get="/search/suggestions"' in form
    assert 'hx-trigger="input delay:500ms, submit"' in form and 'hx-sync="this:replace"' in form
    assert 'hx-target="#suggestions"' in form and 'hx-indicator="#searching"' in form
    assert '<p id="searching" class="searching" role="status">Ищу…</p>' in html


def test_under_the_series_there_is_the_line_about_the_anime(tmp_path):
    client = make_client(FakeTracker(), tmp_path)

    assert SERIES_NOTE in client.get("/search?kind=series").text
    assert SERIES_NOTE not in client.get("/search?kind=movie").text
    assert KINDS[TitleKind.SERIES].search_note.startswith(SERIES_NOTE)


def test_the_answer_with_the_suggestions_brings_the_line_of_the_kind_out_of_band(tmp_path):
    client = make_client(FakeTracker(), tmp_path)

    series = client.get("/search/suggestions", params={"kind": "series", "q": ""}, headers=HTMX).text
    movie = client.get("/search/suggestions", params={"kind": "movie", "q": ""}, headers=HTMX).text

    assert re.search(r'<p id="kind-note" class="kind-note" hx-swap-oob="true">Аниме лучше искать', series)
    assert '<p id="kind-note" class="kind-note" hx-swap-oob="true"></p>' in movie


# ---- the suggestions -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("query", ["д", " д ", "   ", "\t"])
def test_less_than_two_letters_does_not_reach_the_core(tmp_path, query):
    tracker = FakeTracker([DUNE])

    html = make_client(tracker, tmp_path).get("/search/suggestions", params={"kind": "movie", "q": query}, headers=HTMX).text

    assert tracker.searched == []
    assert ("Наберите хотя бы две буквы" in html) == bool(query.strip())


def test_the_query_is_trimmed_and_cut_to_a_hundred_letters(tmp_path):
    tracker = FakeTracker([DUNE])
    client = make_client(tracker, tmp_path)

    client.get("/search/suggestions", params={"kind": "movie", "q": "  дюна  "}, headers=HTMX)
    client.get("/search/suggestions", params={"kind": "movie", "q": "я" * 150}, headers=HTMX)

    assert tracker.searched == [(TitleKind.MOVIE, "дюна"), (TitleKind.MOVIE, "я" * 100)]


def test_the_suggestions_have_the_poster_the_names_the_year_and_add_or_in_the_list(tmp_path):
    tracker = FakeTracker([DUNE, DUNE_2])

    response = make_client(tracker, tmp_path).get(
        "/search/suggestions", params={"kind": "movie", "q": "дюна"}, headers=HTMX
    )

    html = response.text
    assert response.status_code == 200 and "<html" not in html
    assert 'src="https://image.tmdb.org/t/p/w92/dune.jpg"' in html and 'loading="lazy"' in html
    assert "Дюна" in html and "Dune" in html and "2021" in html
    assert add_buttons(html) == [("movie", "438631")]  # the one not in the list
    assert re.search(r'<form class="row-action" method="post" action="/titles" hx-post="/titles" hx-target="this" '
                     r'hx-swap="outerHTML" hx-disabled-elt="find button">', html)
    assert '<span class="idle">Добавить</span><span class="busy">Добавляю…</span>' in html
    assert '<a class="row-action button-link" href="/titles/7">В списке</a>' in html


def test_an_anime_suggestion_shows_the_shikimori_poster_as_it_is(tmp_path):
    html = make_client(FakeTracker([JJK]), tmp_path).get(
        "/search/suggestions", params={"kind": "anime", "q": "битва"}, headers=HTMX
    ).text

    assert 'src="https://shikimori.io/uploads/poster/animes/40748/a.jpeg"' in html and "🎌" in html


def test_at_most_ten_suggestions_are_shown(tmp_path):
    many = [Suggestion(TitleKind.MOVIE, str(n), f"Фильм {n}", "", 2000) for n in range(15)]

    html = make_client(FakeTracker(many), tmp_path).get(
        "/search/suggestions", params={"kind": "movie", "q": "фильм"}, headers=HTMX
    ).text

    assert len(add_buttons(html)) == 10


def test_nothing_found_says_so_with_the_query(tmp_path):
    html = make_client(FakeTracker([]), tmp_path).get(
        "/search/suggestions", params={"kind": "movie", "q": "ыыы"}, headers=HTMX
    ).text

    assert "Ничего не нашлось по запросу «ыыы». Попробуйте другое название или другой тип" in html


@pytest.mark.parametrize("kind, name", [("movie", "TMDb"), ("anime", "Shikimori")])
def test_a_failing_source_is_one_line_with_its_name_and_a_200(tmp_path, kind, name, caplog):
    tracker = FakeTracker(error=failing(ConnectionError("down")))

    response = make_client(tracker, tmp_path).get("/search/suggestions", params={"kind": kind, "q": "дюна"}, headers=HTMX)

    assert response.status_code == 200
    assert f"Не удалось связаться с {name}. Попробуйте чуть позже" in response.text
    assert "ConnectionError" in caplog.text  # the exact cause is in the log


def test_an_unknown_kind_says_there_is_no_such_kind(tmp_path):
    tracker = FakeTracker([DUNE])

    html = make_client(tracker, tmp_path).get("/search/suggestions", params={"kind": "game", "q": "дюна"}, headers=HTMX).text

    assert "Такого типа нет" in html and tracker.searched == []


def test_a_kind_without_a_source_says_there_is_no_such_kind(tmp_path):
    html = make_client(FakeTracker(error=KeyError("anime")), tmp_path).get(
        "/search/suggestions", params={"kind": "anime", "q": "битва"}, headers=HTMX
    ).text

    assert "Такого типа нет" in html


def test_an_unexpected_error_is_the_sentence_of_the_net(tmp_path):
    response = make_client(FakeTracker(error=ValueError("boom")), tmp_path).get(
        "/search/suggestions", params={"kind": "movie", "q": "дюна"}, headers=HTMX
    )

    assert response.status_code == 200 and "Не получилось. Попробуйте ещё раз" in response.text


def test_the_whole_page_with_a_query_comes_with_the_suggestions_without_htmx(tmp_path):
    tracker = FakeTracker([DUNE])
    client = make_client(tracker, tmp_path)

    html = client.get("/search", params={"kind": "series", "q": "дюна"}).text

    assert "<html" in html and add_buttons(html) == [("series", "438631")] and 'value="дюна"' in html
    assert tracker.searched == [(TitleKind.SERIES, "дюна")]
    assert checked(client.get("/search").text) == ["series"]  # a search from the page is remembered too


def test_a_name_with_tags_and_quotes_is_shown_as_text(tmp_path):
    html = make_client(FakeTracker([NASTY]), tmp_path).get(
        "/search/suggestions", params={"kind": "movie", "q": "<script>"}, headers=HTMX
    ).text

    assert "<script>" not in html and "onerror=y>" not in html
    assert "&lt;script&gt;" in html and "&#34;&gt;&lt;img" in html


# ---- adding ----------------------------------------------------------------------------------------------------

def test_adding_through_htmx_goes_to_the_card_with_the_line_added(tmp_path):
    tracker = FakeTracker(added=AddResult(5, created=True))
    client = make_client(tracker, tmp_path)

    response = client.post("/titles", data={"kind": "movie", "external_id": "438631", "q": "дюна"}, headers=HTMX)

    assert response.status_code == 200 and response.headers["HX-Redirect"] == "/titles/5"
    assert tracker.adds == [(TitleKind.MOVIE, "438631")]
    assert "Добавлено в список" in client.get("/search").text  # the notice waits for the next page
    assert "Добавлено в список" not in client.get("/search").text  # and is shown once


def test_adding_without_htmx_is_a_redirect_to_the_card(tmp_path):
    response = make_client(FakeTracker(), tmp_path).post("/titles", data={"kind": "movie", "external_id": "438631"})

    assert response.status_code == 303 and response.headers["location"] == "/titles/5"


def test_a_title_with_seasons_to_mark_asks_to_mark_them(tmp_path):
    client = make_client(FakeTracker(seasons=[WatchableSeason(1, False)]), tmp_path)

    client.post("/titles", data={"kind": "series", "external_id": "10"}, headers=HTMX)

    assert "Добавлено в список. Отметьте сезоны, которые уже посмотрели" in client.get("/search").text


def test_a_title_that_was_in_the_list_says_so(tmp_path):
    client = make_client(FakeTracker(added=AddResult(3, created=False)), tmp_path)

    response = client.post("/titles", data={"kind": "anime", "external_id": "40748"}, headers=HTMX)

    assert response.headers["HX-Redirect"] == "/titles/3"
    html = client.get("/search").text
    assert "Этот тайтл уже в списке" in html and "Добавлено" not in html


@pytest.mark.parametrize("error, text", [
    (TitleNotFound("tmdb_movie:1"), "TMDb больше не знает этот тайтл. Поищите заново"),
    (failing(TimeoutError("slow")), "Не удалось связаться с TMDb. Попробуйте чуть позже"),
    (KeyError("movie"), "Такого типа нет"),
])
def test_what_went_wrong_with_adding_is_said_in_place_of_the_button(tmp_path, error, text):
    response = make_client(FakeTracker(error=error), tmp_path).post(
        "/titles", data={"kind": "movie", "external_id": "1"}, headers=HTMX
    )

    assert response.status_code == 200 and "HX-Redirect" not in response.headers
    assert response.text.strip() == f'<p class="error" role="alert">{text}</p>'


def test_without_htmx_what_went_wrong_goes_back_to_the_search_with_a_line(tmp_path):
    client = make_client(FakeTracker(error=TitleNotFound("x")), tmp_path)

    response = client.post("/titles", data={"kind": "movie", "external_id": "1", "q": "дюна"})

    assert response.status_code == 303 and response.headers["location"] == "/search?kind=movie&q=%D0%B4%D1%8E%D0%BD%D0%B0"
    assert "TMDb больше не знает этот тайтл" in client.get("/search").text


def test_adding_an_unknown_kind_does_not_reach_the_core(tmp_path):
    tracker = FakeTracker()

    response = make_client(tracker, tmp_path).post("/titles", data={"kind": "game", "external_id": "1"}, headers=HTMX)

    assert "Такого типа нет" in response.text and tracker.adds == []


# ---- the guard ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("method, address", [
    ("get", "/search"), ("get", "/search?kind=movie&q=дюна"), ("get", "/search/suggestions?kind=movie&q=дюна"),
    ("post", "/titles"),
])
def test_the_search_is_closed_without_the_sign_in(tmp_path, method, address):
    tracker = FakeTracker([DUNE])
    app = create_web_app(health=Health().report, password=PASSWORD, secret_file=tmp_path / "s", tracker=tracker)
    client = TestClient(app, follow_redirects=False)

    response = getattr(client, method)(address, **({"data": {"kind": "movie", "external_id": "1"}} if method == "post" else {}))

    assert response.status_code in (303, 401) and tracker.searched == [] and tracker.adds == []


def test_adding_from_a_foreign_page_is_refused(tmp_path):
    tracker = FakeTracker()
    client = make_client(tracker, tmp_path)

    response = client.post(
        "/titles", data={"kind": "movie", "external_id": "1"}, headers={"Origin": "https://evil.example"}
    )

    assert response.status_code == 403 and tracker.adds == []


# ---- on the real core ------------------------------------------------------------------------------------------

class FakeSender:
    async def send(self, message, actions=()):
        pass


class SlowSource:
    """A movie source that takes a moment to answer, so two presses are both waiting for it at once."""

    source_key = "tmdb_movie"

    def __init__(self):
        self.snapshots = 0

    async def suggest(self, query):
        return [Suggestion(TitleKind.MOVIE, "1", "Дюна", "Dune", 2021, poster_path="/dune.jpg")]

    async def snapshot(self, external_id):
        self.snapshots += 1
        await asyncio.sleep(0.2)
        return MovieSnapshot(external_id="1", name="Дюна", original_name="Dune", year=2021)


class SeriesSource:
    source_key = "tmdb_tv"

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        season = Season(1, "Сезон 1", 2, (Episode(1, datetime(2025, 1, 1)), Episode(2, datetime(2025, 1, 8))))
        return SeriesSnapshot(external_id=external_id, name="Сериал", original_name="Show", year=2025, seasons=[season])


def real_tracker():
    return Tracker(
        create_session_factory("sqlite://"), clock=lambda: T0, sender=FakeSender(),
        sources={"movie": SlowSource(), "series": SeriesSource()},
    )


def test_two_presses_at_once_on_the_real_core_make_one_title(tmp_path):
    tracker = real_tracker()
    app = create_web_app(health=Health().report, password=PASSWORD, secret_file=tmp_path / "s", tracker=tracker)

    async def both():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.post("/login", data={"password": PASSWORD})).status_code == 303
            press = {"data": {"kind": "movie", "external_id": "1"}, "headers": HTMX}
            return await asyncio.gather(client.post("/titles", **press), client.post("/titles", **press))

    first, second = asyncio.run(both())

    assert first.headers["HX-Redirect"] == second.headers["HX-Redirect"] == "/titles/1"
    assert tracker.sources[TitleKind.MOVIE].snapshots == 2  # both waited for the source
    assert [t.id for t in asyncio.run(tracker.list_titles())] == [1]


def test_a_title_added_on_the_real_core_is_in_the_list_at_the_next_search(tmp_path):
    client = make_client(real_tracker(), tmp_path)

    before = client.get("/search/suggestions", params={"kind": "movie", "q": "дюна"}, headers=HTMX).text
    client.post("/titles", data={"kind": "movie", "external_id": "1"}, headers=HTMX)
    after = client.get("/search/suggestions", params={"kind": "movie", "q": "дюна"}, headers=HTMX).text

    assert add_buttons(before) == [("movie", "1")]
    assert add_buttons(after) == [] and 'href="/titles/1">В списке</a>' in after


def test_the_card_after_adding_a_series_has_the_line_about_the_seasons(tmp_path):
    client = make_client(real_tracker(), tmp_path)

    response = client.post("/titles", data={"kind": "series", "external_id": "10"})
    card = client.get(response.headers["location"]).text

    assert "Добавлено в список. Отметьте сезоны, которые уже посмотрели" in card and "<h1>Сериал</h1>" in card


def test_the_card_after_adding_a_film_has_only_the_line_added(tmp_path):
    client = make_client(real_tracker(), tmp_path)

    response = client.post("/titles", data={"kind": "movie", "external_id": "1"})
    card = client.get(response.headers["location"]).text

    assert "Добавлено в список" in card and "Отметьте сезоны" not in card
