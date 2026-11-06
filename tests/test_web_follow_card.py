"""The expansions and sequels of a game in the browser (spec 7.2, 7.3, 7.4 and 8 of stage 6.3, ticket 03): the three states of
the block under «Платформы» and «Steam», the texts, the rows with «Следить» and «В списке», the error in the block the press
came from, the line of the parent, the word «дополнение» in the List and the Archive.

The real core on in-memory SQLite with a stand-in clock, a made-up game source and a fake source of the follow-up check
(as in `test_tracker_game_follow_ups`); the web is the real app on a `TestClient`.
"""

import re

import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.follow_ups import FollowUpsSnapshot
from app.tracker.games import EXPANSION, STANDALONE, GameState
from app.tracker.models import TitleKind
from app.web import create_web_app
from app.web.card_blocks import series_sentence
from app.web.posters import image_sources
from test_tracker_follow_card import COLLECTION, answer_for_witcher, follow_up, expansion_state
from test_tracker_game_follow_ups import PC, T0, FakeClock, FakeFollowUps, FakeSender, MadeUpGames, add, run
from test_web_card import PASSWORD

HTMX = {"HX-Request": "true"}


def make_client(tracker, tmp_path, now):
    """The real web app whose wall clock is `now` (the card says «вчера в 12:00» by it, not by the date of the day)."""
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    app = create_web_app(
        health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker, now=now,
        image_sources=image_sources("https://shikimori.io"),
    )
    client = TestClient(app, follow_redirects=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def igdb():
    return MadeUpGames()


@pytest.fixture
def follow():
    return FakeFollowUps()


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def tracker(session_factory, igdb, follow, clock):
    return Tracker(
        session_factory, clock=clock, sender=FakeSender(), sources={TitleKind.GAME: igdb}, follow_up_source=follow
    )


@pytest.fixture
def bare(session_factory, igdb):
    """A core that has no source of the follow-up check."""
    return Tracker(session_factory, clock=FakeClock(T0), sender=FakeSender(), sources={TitleKind.GAME: igdb})


@pytest.fixture
def client(tracker, tmp_path, clock):
    return make_client(tracker, tmp_path, clock)


def witcher(tracker, igdb, follow):
    answer_for_witcher(follow)
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    return title_id


def block(html, key):
    found = re.search(rf'<section class="sequels" aria-labelledby="{key}-heading">.*?</section>', html, re.S)
    return found.group(0) if found else ""


def text_of(html):
    return re.sub(r"[ \t\r\n]+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def rows(html):
    return re.findall(r'<span class="sequel-name">([^<]+)</span> <span class="sequel-date">([^<]+)</span>', html)


def parent_line(html):
    found = re.search(r'<p class="parent-line">(.*?)</p>', html, re.S)
    return found.group(1) if found else None


# --- the three states (7.2) ------------------------------------------------------------------------------------------


def test_a_game_not_checked_yet_has_one_block_with_the_line_to_wait(tracker, igdb, client):
    title_id = add(tracker, igdb)

    html = client.get(f"/titles/{title_id}").text

    assert text_of(block(html, "follow-ups")) == "Дополнения и продолжения Ещё не проверял — проверю в ближайшие минуты"
    assert 'id="expansions-heading"' not in html and 'id="sequels-heading"' not in html


def test_a_checked_game_has_the_expansions_then_the_sequels_with_their_sentences(tracker, igdb, follow, client):
    title_id = witcher(tracker, igdb, follow)

    html = client.get(f"/titles/{title_id}").text

    expansions, sequels = block(html, "expansions"), block(html, "sequels")
    assert html.index(expansions) < html.index(sequels)
    assert rows(expansions) == [
        ("Каменные сердца", "12 октября 2015"), ("Кровь и Вино", "30 мая 2016"), ("Баллады прошлого", "дата не объявлена"),
    ]
    assert rows(sequels) == [("Gwent", "23 октября 2018"), ("The Witcher IV", "2028")]
    assert '<p class="hint">Проверяю раз в неделю, последняя проверка — в 12:00</p>' in expansions
    assert f'<p class="hint">Новые игры серии «{COLLECTION}» на ваших платформах</p>' in sequels
    assert "Ещё не проверял" not in html


def test_the_blocks_stand_under_the_platforms_and_before_the_buttons(tracker, igdb, follow, client):
    title_id = witcher(tracker, igdb, follow)

    html = client.get(f"/titles/{title_id}").text

    assert html.index('<section class="platforms"') < html.index('aria-labelledby="expansions-heading"')
    assert html.index('aria-labelledby="sequels-heading"') < html.index('<div class="actions">')


def test_a_game_with_nothing_found_says_so_in_both_blocks(tracker, igdb, follow, client):
    follow.answers["1"] = FollowUpsSnapshot()
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    html = client.get(f"/titles/{title_id}").text

    assert text_of(block(html, "expansions")) == (
        "Дополнения Дополнений пока нет. Проверяю раз в неделю, последняя проверка — в 12:00"
    )
    assert text_of(block(html, "sequels")) == "Продолжения Продолжений пока нет. Проверяю раз в неделю"


def test_the_sentence_of_the_series_for_one_two_and_no_series():
    assert series_sentence(("A",)) == "Новые игры серии «A» на ваших платформах"
    assert series_sentence(("A", "B")) == "Новые игры серий «A», «B» на ваших платформах"
    assert series_sentence(()) == "Новые игры серии на ваших платформах"


def test_the_last_check_is_said_the_way_the_page_says_a_past_moment(tracker, igdb, follow, clock, client):
    title_id = witcher(tracker, igdb, follow)
    clock.advance(days=1)

    html = client.get(f"/titles/{title_id}").text

    assert "последняя проверка — вчера в 12:00" in block(html, "expansions")


def test_the_card_of_a_game_in_a_core_without_the_follow_up_source_has_no_blocks(bare, igdb, tmp_path, clock):
    title_id = add(bare, igdb)

    html = make_client(bare, tmp_path, clock).get(f"/titles/{title_id}").text

    assert 'class="sequels"' not in html and "Ещё не проверял" not in html


# --- the rows (7.2) --------------------------------------------------------------------------------------------------


def test_a_row_has_follow_and_a_row_of_the_list_says_so_with_a_link_to_its_card(tracker, igdb, follow, client):
    igdb.put("20", GameState(platforms=(PC,)), "Кровь и Вино")
    followed = run(tracker.follow("game", "20")).title_id
    title_id = witcher(tracker, igdb, follow)

    expansions = block(client.get(f"/titles/{title_id}").text, "expansions")

    assert f'<a class="row-action button-link" href="/titles/{followed}">В списке</a>' in expansions
    assert expansions.count('class="idle">Следить</span>') == 2  # the other two rows


def test_the_follow_form_sends_the_kind_the_id_and_the_block(tracker, igdb, follow, client):
    title_id = witcher(tracker, igdb, follow)

    expansions = block(client.get(f"/titles/{title_id}").text, "expansions")

    assert f'action="/titles/{title_id}/follow"' in expansions
    assert re.findall(r'name="(kind|external_id|block)" value="([^"]*)"', expansions)[:3] == [
        ("kind", "game"), ("external_id", "21"), ("block", "expansions"),
    ]


@pytest.mark.parametrize("key, external_id", [("expansions", "20"), ("sequels", "30")])
def test_follow_adds_the_game_and_the_owner_stays_on_the_card_where_the_row_says_it_is_in_the_list(
    tracker, igdb, follow, client, key, external_id
):
    title_id = witcher(tracker, igdb, follow)
    igdb.put(external_id, GameState(platforms=(PC,)), "Кровь и Вино")

    answer = client.post(
        f"/titles/{title_id}/follow", data={"kind": "game", "external_id": external_id, "block": key}, headers=HTMX
    )

    assert answer.status_code == 200 and '<article id="card"' in answer.text and "<h1>Ведьмак 3</h1>" in answer.text
    added = run(tracker.add_title(TitleKind.GAME, external_id)).title_id
    assert f'href="/titles/{added}">В списке</a>' in block(answer.text, key)


def test_follow_without_htmx_goes_back_to_the_card(tracker, igdb, follow, client):
    title_id = witcher(tracker, igdb, follow)
    igdb.put("20", GameState(platforms=(PC,)), "Кровь и Вино")

    answer = client.post(f"/titles/{title_id}/follow", data={"kind": "game", "external_id": "20", "block": "expansions"})

    assert answer.status_code == 303 and answer.headers["location"] == f"/titles/{title_id}"


@pytest.mark.parametrize("key, other", [("expansions", "sequels"), ("sequels", "expansions")])
def test_an_error_is_a_line_in_the_block_the_press_came_from(tracker, igdb, follow, client, key, other):
    title_id = witcher(tracker, igdb, follow)

    async def down(external_id):
        raise RuntimeError("IGDB is down")

    igdb.snapshot_to_add = down

    answer = client.post(f"/titles/{title_id}/follow", data={"kind": "game", "external_id": "20", "block": key}, headers=HTMX)

    line = '<p class="error" role="alert">Не удалось связаться с IGDB. Попробуйте чуть позже</p>'
    assert line in block(answer.text, key) and 'role="alert"' not in block(answer.text, other)


def test_follow_of_a_game_the_source_does_not_know_says_so_in_the_block(tracker, igdb, follow, client):
    title_id = witcher(tracker, igdb, follow)

    answer = client.post(f"/titles/{title_id}/follow", data={"kind": "game", "external_id": "99", "block": "sequels"}, headers=HTMX)

    assert "IGDB больше не знает этот тайтл. Поищите заново" in block(answer.text, "sequels")


def test_follow_in_a_core_without_the_follow_up_source_is_refused(bare, igdb, tmp_path, clock):
    title_id = add(bare, igdb)
    igdb.put("20", GameState(platforms=(PC,)), "Кровь и Вино")

    answer = make_client(bare, tmp_path, clock).post(
        f"/titles/{title_id}/follow", data={"kind": "game", "external_id": "20"}, headers=HTMX
    )

    assert "Такого типа нет" in answer.text


def test_the_old_address_of_the_sequels_is_gone(tracker, igdb, follow, client):
    title_id = witcher(tracker, igdb, follow)

    assert client.post(f"/titles/{title_id}/sequels", data={"kind": "movie", "external_id": "2"}).status_code in (404, 405)


# --- the line of the parent (7.2, 8) ---------------------------------------------------------------------------------


def test_the_line_of_an_expansion_links_the_parent_that_is_in_the_list(tracker, igdb, follow, client):
    igdb.put("1942", GameState(platforms=(PC,)), "Ведьмак 3: Дикая охота")
    parent = run(tracker.add_title(TitleKind.GAME, "1942")).title_id
    igdb.put("20", expansion_state(STANDALONE), "Кровь и Вино")
    expansion = run(tracker.follow("game", "20")).title_id

    html = client.get(f"/titles/{expansion}").text

    assert parent_line(html) == f'Дополнение к игре «<a href="/titles/{parent}">Ведьмак 3: Дикая охота</a>»'
    assert html.index("<h1>") < html.index('class="parent-line"') < html.index('class="kind-line"')


def test_the_line_is_plain_text_with_the_name_of_igdb_when_the_parent_is_not_in_the_list(tracker, igdb, follow, client):
    igdb.put("20", expansion_state(EXPANSION), "Кровь и Вино")
    expansion = run(tracker.follow("game", "20")).title_id

    assert parent_line(client.get(f"/titles/{expansion}").text) == "Дополнение к игре «The Witcher 3: Wild Hunt»"


def test_a_game_that_is_no_expansion_has_no_such_line(tracker, igdb, follow, client):
    title_id = witcher(tracker, igdb, follow)

    assert parent_line(client.get(f"/titles/{title_id}").text) is None


def test_an_expansion_that_needs_its_game_has_no_blocks_and_a_standalone_one_has_both(tracker, igdb, follow, client):
    igdb.put("20", expansion_state(EXPANSION), "Кровь и Вино")
    igdb.put("21", expansion_state(STANDALONE), "Miles Morales")
    needs_game = run(tracker.follow("game", "20")).title_id
    standalone = run(tracker.follow("game", "21")).title_id
    follow.answers["21"] = FollowUpsSnapshot(games=(follow_up("30", "Игра", 2028),))
    run(tracker.poll_due())

    plain = client.get(f"/titles/{needs_game}").text
    alone = client.get(f"/titles/{standalone}").text

    assert 'class="sequels"' not in plain and parent_line(plain) is not None
    assert block(alone, "expansions") and block(alone, "sequels") and parent_line(alone) is not None


def test_an_expansion_in_the_list_is_a_game_with_its_platforms(tracker, igdb, follow, client):
    igdb.put("20", expansion_state(EXPANSION), "Кровь и Вино")
    expansion = run(tracker.follow("game", "20")).title_id

    assert '<section class="platforms"' in client.get(f"/titles/{expansion}").text


# --- the word in the List and the Archive (7.4) -----------------------------------------------------------------------


def test_the_list_and_the_archive_show_the_word_after_the_name_of_an_expansion(tracker, igdb, follow, client):
    igdb.put("20", expansion_state(EXPANSION), "Кровь и Вино")
    expansion = run(tracker.follow("game", "20")).title_id
    add(tracker, igdb, "1", "Ведьмак 3")

    listing = client.get("/list?status=all").text
    run(tracker.mark_watched(expansion))
    archive = client.get("/archive").text

    assert listing.count('<span class="row-tag">дополнение</span>') == 1
    assert re.search(r"Кровь и Вино <span class=\"row-tag\">дополнение</span>", listing)
    assert re.search(r"Кровь и Вино <span class=\"row-tag\">дополнение</span>", archive)
    assert "Ведьмак 3 <span" not in listing
