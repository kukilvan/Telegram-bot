"""The scores in the card in the browser: where the list is (table 2.3 of the spec of part 5.3), what it offers, the
presses that save a score, the lines when a score cannot be saved, the long numbers of an address (KI-25) and «Обновить»
at «Не получилось». On the real core with fake sources; the presses go through the web app."""

import asyncio
import logging
import re
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker import scores
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import TitleStatus
from app.tracker.seasons import Episode, Season
from app.tracker.sources.tmdb_movies import MovieSnapshot
from app.tracker.sources.tmdb_series import SeriesSnapshot
from app.web import create_web_app
from app.web.posters import image_sources
from season_helpers import season_id

PASSWORD = "correct horse battery"
T0 = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
HTMX = {"HX-Request": "true"}
GONE = "Этого тайтла больше нет в списке"
NO_SUCH_SCORE = "Такой оценки нет"
CANNOT = "Оценку ставят только просмотренному — карточка обновлена"
SEASON_GONE = "Этого сезона больше нет — карточка обновлена"
LONG = "9" * 20
LABELS = [scores.label(step) for step in scores.SCALE]


def weekly(first_day, count):
    start = datetime.fromisoformat(first_day)
    return tuple(Episode(n + 1, start + timedelta(weeks=n)) for n in range(count))


FILM = MovieSnapshot(external_id="1", name="Дюна", original_name="Dune", year=2021, genres=[], theatrical_date=date(2027, 3, 12))
NASTY = MovieSnapshot(external_id="2", name='<script>alert("x")</script> & «Q»', original_name="Nasty", year=2000, genres=[])
SHOW = SeriesSnapshot(
    external_id="10", name="Идущий", original_name="Running", year=2026, genres=[],
    seasons=[
        Season(1, "Сезон 1", 8, weekly("2026-03-02", 8)),
        Season(2, "Сезон 2", 8, weekly("2026-09-07", 8)),
        Season(3, "Сезон 3", None, ()),
    ],
)
OTHER = SeriesSnapshot(
    external_id="11", name="Другое", original_name="Other", year=2025, genres=[],
    seasons=[Season(1, "Сезон 1", 4, weekly("2025-01-06", 4))],
)


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
        sources={"movie": FakeSource("tmdb_movie", FILM, NASTY), "series": FakeSource("tmdb_tv", SHOW, OTHER)},
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
    web = TestClient(app, follow_redirects=False)
    assert web.post("/login", data={"password": PASSWORD}).status_code == 303
    return web


def add(tracker, kind, external_id):
    return run(tracker.add_title(kind, external_id)).title_id


def watched_film(tracker, external_id="1"):
    film = add(tracker, "movie", external_id)
    run(tracker.mark_watched(film))
    return film


def show_with_seasons(tracker, *numbers):
    show = add(tracker, "series", "10")
    for number in numbers:
        run(tracker.set_season_watched(show, season_id(tracker, show, number), True))
    return show


def lists(html):
    """The drop-down lists of a card: (the address they send to, the captions of the choices, the selected one)."""
    found = []
    for form in re.findall(r'<form class="score".*?</form>', html, re.S):
        address = re.search(r'action="([^"]+)"', form).group(1)
        options = re.findall(r'<option value="([^"]*)"( selected)?>([^<]*)</option>', form)
        found.append((address, [text for _, _, text in options], [text for _, sel, text in options if sel]))
    return found


# ---- where the list is ----------------------------------------------------------------------------------

def test_a_film_that_is_wanted_has_no_field_of_score(tracker, client):
    film = add(tracker, "movie", "1")

    html = client.get(f"/titles/{film}").text

    assert lists(html) == [] and "Оценка" not in html


@pytest.mark.parametrize("finish", ["mark_watched", "mark_dropped"])
def test_a_film_in_the_archive_has_the_list_under_the_status(tracker, client, finish):
    film = add(tracker, "movie", "1")
    run(getattr(tracker, finish)(film))

    html = client.get(f"/titles/{film}").text

    assert lists(html) == [(f"/titles/{film}/score", ["—"] + LABELS, ["—"])]
    assert html.index("Статус:") < html.index('<form class="score"') < html.index("Премьера в кино")


def test_a_film_brought_back_shows_no_field_and_shows_it_again_after_the_next_watch(tracker, client):
    film = watched_film(tracker)
    run(tracker.set_title_score(film, 28))
    run(tracker.restore_title(film))

    assert lists(client.get(f"/titles/{film}").text) == []

    run(tracker.mark_watched(film))

    assert lists(client.get(f"/titles/{film}").text)[0][2] == ["9+"]


def test_a_series_without_a_mark_has_no_list_anywhere(tracker, client):
    show = add(tracker, "series", "10")

    assert lists(client.get(f"/titles/{show}").text) == []


def test_a_marked_season_has_a_list_of_its_own_and_the_series_one_of_its_own(tracker, client):
    show = show_with_seasons(tracker, 2)

    found = lists(client.get(f"/titles/{show}").text)

    assert [address for address, _, _ in found] == [
        f"/titles/{show}/score", f"/titles/{show}/seasons/{season_id(tracker, show, 2)}/score",
    ]
    assert found[0][1] == ["По сезонам: пока нет"] + LABELS and found[0][2] == ["По сезонам: пока нет"]
    assert found[1][1] == ["—"] + LABELS and found[1][2] == ["—"]


def test_the_list_of_a_season_sits_in_its_row_and_a_season_without_a_mark_has_none(tracker, client):
    show = show_with_seasons(tracker, 2)

    html = client.get(f"/titles/{show}").text

    rows = re.findall(r'<li class="season-item">(.*?)</li>', html, re.S)
    assert [("class=\"score\"" in row) for row in rows] == [False, True, False]


def test_the_average_of_the_seasons_is_the_first_row_and_a_note_says_so(tracker, client):
    show = show_with_seasons(tracker, 1, 2)
    run(tracker.set_season_score(show, season_id(tracker, show, 1), 27))
    run(tracker.set_season_score(show, season_id(tracker, show, 2), 25))

    html = client.get(f"/titles/{show}").text

    found = lists(html)
    assert found[0][1][0] == "По сезонам: 9−" and found[0][2] == ["По сезонам: 9−"]
    assert found[1][2] == ["9"] and found[2][2] == ["8+"]
    assert '<span class="score-note">среднее по сезонам</span>' in html


def test_an_own_score_of_the_series_is_selected_and_the_note_goes(tracker, client):
    show = show_with_seasons(tracker, 1)
    run(tracker.set_season_score(show, season_id(tracker, show, 1), 27))
    run(tracker.set_title_score(show, scores.HIGHEST))

    html = client.get(f"/titles/{show}").text

    found = lists(html)
    assert found[0][1][0] == "По сезонам: 9" and found[0][2] == ["10"]
    assert "среднее по сезонам" not in html


def test_a_series_in_the_archive_without_marks_can_be_scored_as_a_whole(tracker, client):
    show = add(tracker, "series", "10")
    run(tracker.mark_dropped(show))

    found = lists(client.get(f"/titles/{show}").text)

    assert [address for address, _, _ in found] == [f"/titles/{show}/score"]


# ---- saving a score -------------------------------------------------------------------------------------

def test_a_chosen_score_is_saved_and_the_answer_is_the_fresh_card_with_it_selected(tracker, client):
    film = watched_film(tracker)

    answer = client.post(f"/titles/{film}/score", data={"score": "28"}, headers=HTMX)

    assert answer.status_code == 200 and '<article id="card"' in answer.text
    assert lists(answer.text)[0][2] == ["9+"]
    assert run(tracker.title_card(film)).score.own == 28


def test_the_empty_choice_takes_the_score_of_a_film_off(tracker, client):
    film = watched_film(tracker)
    run(tracker.set_title_score(film, 28))

    answer = client.post(f"/titles/{film}/score", data={"score": ""}, headers=HTMX)

    assert lists(answer.text)[0][2] == ["—"] and run(tracker.title_card(film)).score.own is None


def test_a_score_of_a_season_is_saved_and_the_average_of_the_series_is_new_in_the_answer(tracker, client):
    show = show_with_seasons(tracker, 1, 2)
    first = season_id(tracker, show, 1)

    answer = client.post(f"/titles/{show}/seasons/{first}/score", data={"score": "27"}, headers=HTMX)

    found = lists(answer.text)
    assert answer.status_code == 200 and found[0][2] == ["По сезонам: 9"] and found[1][2] == ["9"]


def test_the_first_row_of_the_series_list_gives_back_the_average(tracker, client):
    show = show_with_seasons(tracker, 1)
    run(tracker.set_season_score(show, season_id(tracker, show, 1), 27))
    run(tracker.set_title_score(show, 30))

    answer = client.post(f"/titles/{show}/score", data={"score": ""}, headers=HTMX)

    assert run(tracker.title_card(show)).score.own is None
    assert lists(answer.text)[0][2] == ["По сезонам: 9"]


def test_without_htmx_a_press_goes_back_to_the_card(tracker, client):
    film = watched_film(tracker)

    answer = client.post(f"/titles/{film}/score", data={"score": "30"})

    assert answer.status_code == 303 and answer.headers["location"] == f"/titles/{film}"
    assert run(tracker.title_card(film)).score.own == 30


def test_the_saving_list_sends_on_change_and_waits_for_the_answer(tracker, client):
    film = watched_film(tracker)

    html = client.get(f"/titles/{film}").text

    form = re.search(r'<form class="score".*?</form>', html, re.S).group(0)
    assert 'hx-trigger="change"' in form and 'hx-target="#card"' in form and 'hx-disabled-elt="find select"' in form


# ---- scores that cannot be saved ------------------------------------------------------------------------

@pytest.fixture
def spy(monkeypatch):
    """The scores that reached the core."""
    asked = []

    async def title_score(self, title_id, score):
        asked.append(("title", title_id, score))
        return await original_title(self, title_id, score)

    async def season_score(self, title_id, season_id_, score):
        asked.append(("season", title_id, season_id_, score))
        return await original_season(self, title_id, season_id_, score)

    original_title, original_season = Tracker.set_title_score, Tracker.set_season_score
    monkeypatch.setattr(Tracker, "set_title_score", title_score)
    monkeypatch.setattr(Tracker, "set_season_score", season_score)
    return asked


@pytest.mark.parametrize("raw", ["31", "2", "0", "-5", "abc", "9.5", "٢٨", "28 28"])
def test_a_value_off_the_scale_is_a_line_and_the_core_is_not_asked(tracker, client, spy, raw):
    film = watched_film(tracker)
    run(tracker.set_title_score(film, 27))
    spy.clear()

    answer = client.post(f"/titles/{film}/score", data={"score": raw}, headers=HTMX)

    assert answer.status_code == 200 and NO_SUCH_SCORE in answer.text and lists(answer.text)[0][2] == ["9"]
    assert spy == [] and run(tracker.title_card(film)).score.own == 27


def test_a_season_value_off_the_scale_is_the_same_line(tracker, client, spy):
    show = show_with_seasons(tracker, 1)

    answer = client.post(f"/titles/{show}/seasons/{season_id(tracker, show, 1)}/score", data={"score": "31"}, headers=HTMX)

    assert NO_SUCH_SCORE in answer.text and spy == []


def test_a_value_off_the_scale_without_htmx_is_a_line_on_the_card(tracker, client):
    film = watched_film(tracker)

    answer = client.post(f"/titles/{film}/score", data={"score": "31"})

    assert answer.status_code == 303
    assert NO_SUCH_SCORE in client.get(answer.headers["location"]).text


def test_a_film_that_is_wanted_cannot_be_scored(tracker, client):
    film = add(tracker, "movie", "1")

    answer = client.post(f"/titles/{film}/score", data={"score": "28"}, headers=HTMX)

    assert answer.status_code == 200 and CANNOT in answer.text and lists(answer.text) == []
    assert run(tracker.title_card(film)).status == TitleStatus.WANT


def test_a_season_whose_mark_was_taken_off_elsewhere_says_so(tracker, client):
    show = show_with_seasons(tracker, 1)
    first = season_id(tracker, show, 1)
    run(tracker.set_season_watched(show, first, False))

    answer = client.post(f"/titles/{show}/seasons/{first}/score", data={"score": "27"}, headers=HTMX)

    assert answer.status_code == 200 and CANNOT in answer.text


def test_a_season_of_another_title_or_one_that_is_gone_says_so(tracker, client):
    show = show_with_seasons(tracker, 1)
    other = add(tracker, "series", "11")

    foreign = client.post(f"/titles/{show}/seasons/{season_id(tracker, other, 1)}/score", data={"score": "27"}, headers=HTMX)
    missing = client.post(f"/titles/{show}/seasons/9999/score", data={"score": "27"}, headers=HTMX)

    assert SEASON_GONE in foreign.text and SEASON_GONE in missing.text and '<article id="card"' in missing.text


def test_a_title_that_is_gone_is_the_sentence_of_the_gone_title(tracker, client):
    for path in ("/titles/777/score", "/titles/777/seasons/1/score"):
        answer = client.post(path, data={"score": "27"}, headers=HTMX)

        assert answer.status_code == 200 and GONE in answer.text


def test_a_title_that_is_gone_without_htmx_is_a_page_with_a_404(tracker, client):
    answer = client.post("/titles/777/score", data={"score": "27"})

    assert answer.status_code == 404 and GONE in answer.text


# ---- KI-25: a number too long for an address --------------------------------------------------------------

def test_the_card_of_a_number_too_long_is_not_in_the_list_and_the_core_is_not_asked(tracker, client, monkeypatch):
    async def never(self, *args):
        raise AssertionError("the core was asked about a number that cannot be ours")

    monkeypatch.setattr(Tracker, "title_card", never)

    answer = client.get(f"/titles/{LONG}")

    assert answer.status_code == 404 and "Этого тайтла нет в списке" in answer.text


@pytest.mark.parametrize("path", [
    f"/titles/{LONG}/seasons/1", f"/titles/{LONG}/score", f"/titles/{LONG}/seasons/1/score", f"/titles/{LONG}/released-watched",
    f"/titles/{LONG}/watched", f"/titles/{LONG}/dropped", f"/titles/{LONG}/restore", f"/titles/{LONG}/sequels",
])
def test_a_press_at_a_number_too_long_is_the_gone_title_and_the_core_is_not_asked(tracker, client, monkeypatch, path):
    async def never(self, *args, **kwargs):
        raise AssertionError("the core was asked about a number that cannot be ours")

    for name in ("title_card", "set_season_watched", "set_title_score", "set_season_score", "mark_all_released",
                 "mark_watched", "mark_dropped", "restore_title", "follow_sequel_of"):
        monkeypatch.setattr(Tracker, name, never)

    answer = client.post(path, data={"score": "27", "kind": "movie", "sequel_id": "2"}, headers=HTMX)

    assert answer.status_code == 200 and GONE in answer.text


def test_a_number_of_a_season_too_long_is_a_season_that_is_gone(tracker, client, spy):
    show = show_with_seasons(tracker, 1)

    scored = client.post(f"/titles/{show}/seasons/{LONG}/score", data={"score": "27"}, headers=HTMX)
    marked = client.post(f"/titles/{show}/seasons/{LONG}", data={"watched": "1"}, headers=HTMX)

    assert SEASON_GONE in scored.text and SEASON_GONE in marked.text and spy == []


def test_deleting_a_number_too_long_goes_on_to_the_list_with_the_line_of_a_title_gone(tracker, client):
    answer = client.post(f"/titles/{LONG}/delete")

    assert answer.status_code == 303 and answer.headers["location"] == "/list"
    assert "Этого тайтла уже нет в списке" in client.get("/list").text


# ---- «Обновить» -------------------------------------------------------------------------------------------

def test_not_managed_on_the_card_ends_in_a_link_to_the_card(tracker, client, monkeypatch, caplog):
    film = watched_film(tracker)

    async def broken(self, *args):
        raise RuntimeError("boom")

    monkeypatch.setattr(Tracker, "set_title_score", broken)

    with caplog.at_level(logging.ERROR):
        answer = client.post(f"/titles/{film}/score", data={"score": "28"}, headers=HTMX)

    assert answer.status_code == 200
    assert f'Не получилось. Попробуйте ещё раз; подробности — в журнале. <a href="/titles/{film}">Обновить</a>' in answer.text
    assert any(r.exc_info for r in caplog.records if "unexpected error" in r.getMessage())


def test_not_managed_on_a_season_press_links_to_the_card_of_the_title(tracker, client, monkeypatch):
    show = show_with_seasons(tracker, 1)

    async def broken(self, *args):
        raise RuntimeError("boom")

    monkeypatch.setattr(Tracker, "set_season_score", broken)

    answer = client.post(f"/titles/{show}/seasons/{season_id(tracker, show, 1)}/score", data={"score": "27"}, headers=HTMX)

    assert f'<a href="/titles/{show}">Обновить</a>' in answer.text


def test_not_managed_without_htmx_is_a_page_with_the_link(tracker, client, monkeypatch):
    film = watched_film(tracker)

    async def broken(self, *args):
        raise RuntimeError("boom")

    monkeypatch.setattr(Tracker, "set_title_score", broken)

    answer = client.post(f"/titles/{film}/score", data={"score": "28"})

    assert answer.status_code == 500 and f'<a href="/titles/{film}">Обновить</a>' in answer.text


def test_a_page_without_a_refresh_stays_as_it_was(tracker, client, monkeypatch):
    async def broken(self):
        raise RuntimeError("boom")

    monkeypatch.setattr(Tracker, "list_titles", lambda self, *a, **k: broken(self))

    answer = client.get("/list")

    assert answer.status_code == 500 and "Обновить" not in answer.text


# ---- safety and text ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["/score", "/seasons/1/score"])
def test_a_press_from_a_foreign_page_is_refused(tracker, client, spy, path):
    film = watched_film(tracker)

    answer = client.post(f"/titles/{film}{path}", data={"score": "28"}, headers={"Origin": "http://evil.example"})

    assert answer.status_code == 403 and spy == []


@pytest.mark.parametrize("path", ["/score", "/seasons/1/score"])
def test_the_presses_need_a_sign_in(tracker, client, spy, path):
    film = watched_film(tracker)
    anonymous = TestClient(client.app, follow_redirects=False)

    assert anonymous.post(f"/titles/{film}{path}", data={"score": "28"}).status_code == 303
    assert spy == []


def test_a_name_with_markup_stays_text_on_a_card_with_a_score(tracker, client):
    film = watched_film(tracker, "2")
    run(tracker.set_title_score(film, 28))

    html = client.get(f"/titles/{film}").text

    assert "<script>alert" not in html and "&lt;script&gt;alert" in html and lists(html)[0][2] == ["9+"]
