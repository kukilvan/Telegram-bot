"""«Недавно» of the feed under the announcements of games (spec 7.6 of stage 6.3, ticket 04): «Следить» with the kind and
the id of the announced game, «В списке» once the game is in the list, an announcement of the old format without a
button, and `POST /feed/follow` (`feed_follow`) for a game: the game joins the list, the errors name IGDB.

The same real core as `test_web_feed`, with a made-up game source and a fake source of the follow-up check.
"""

from datetime import timezone

import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker import follow_ups
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import TitleKind, TitleStatus
from app.web import create_web_app
from app.web.posters import image_sources
from test_tracker_game_follow_ups import FakeFollowUps, MadeUpGames, game
from test_web_feed import HTMX, MSK, NOW, PASSWORD, FakeSender, at, put_event, put_title, rows_of, run

HEADLINE = "🎮 Анонсировано дополнение: Elden Ring: Shadow of the Erdtree"
DATA = {"kind": "game", "sequel_id": "3", "sequel_title": "Elden Ring: Shadow of the Erdtree", "date": None}


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def igdb():
    source = MadeUpGames()
    source.put("3", game(), "Elden Ring: Shadow of the Erdtree")
    return source


@pytest.fixture
def tracker(session_factory, igdb):
    return Tracker(
        session_factory, clock=lambda: NOW.replace(tzinfo=timezone.utc), sender=FakeSender(),
        sources={TitleKind.GAME: igdb}, follow_up_source=FakeFollowUps(), default_tz=MSK,
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


def announce(session_factory, data=DATA, event_type=follow_ups.EXPANSION_ANNOUNCED):
    elden = put_title(session_factory, "Elden Ring", TitleKind.GAME, TitleStatus.COMPLETED)
    put_event(
        session_factory, elden, event_type,
        f"{HEADLINE}\nДополнение к игре «Elden Ring»\nВыход: дата не объявлена", at(0, 6), data,
    )
    return elden


def test_a_game_announcement_is_a_row_with_the_headline_the_smaller_lines_and_follow(client, session_factory):
    announce(session_factory)

    html = client.get("/").text

    assert rows_of(html, "recent") == [f"{HEADLINE} Дополнение к игре «Elden Ring» Выход: дата не объявлена Следить Добавляю…"]
    assert '<input type="hidden" name="kind" value="game">' in html
    assert '<input type="hidden" name="external_id" value="3">' in html
    assert 'hx-post="/feed/follow"' in html and "/feed/sequels" not in html


def test_the_announced_game_that_is_in_the_list_is_a_link(client, tracker, session_factory):
    announce(session_factory)
    followed = run(tracker.follow("game", "3")).title_id

    html = client.get("/").text

    assert f'<a class="row-action button-link" href="/titles/{followed}">В списке</a>' in html and "Следить" not in html


def test_an_announcement_of_the_old_format_has_no_button(client, session_factory):
    announce(session_factory, data={})

    html = client.get("/").text

    [row] = rows_of(html, "recent")
    assert row.startswith(HEADLINE) and "Следить" not in row and "В списке" not in row


def test_follow_adds_the_game_and_the_fresh_feed_says_it_is_in_the_list(client, tracker, session_factory):
    announce(session_factory)

    answer = client.post("/feed/follow", data={"kind": "game", "external_id": "3"}, headers=HTMX)

    added = [t for t in run(tracker.list_titles()) if t.name == "Elden Ring: Shadow of the Erdtree"]
    assert answer.status_code == 200 and "<html" not in answer.text and len(added) == 1
    assert f'<a class="row-action button-link" href="/titles/{added[0].id}">В списке</a>' in answer.text
    assert "Следить" not in answer.text


def test_follow_of_a_game_igdb_does_not_know_names_igdb(client, session_factory):
    announce(session_factory)

    answer = client.post("/feed/follow", data={"kind": "game", "external_id": "99"}, headers=HTMX)

    assert "IGDB больше не знает этот тайтл. Поищите заново" in answer.text


def test_the_old_address_is_gone(client):
    assert client.post("/feed/sequels", data={"kind": "game", "external_id": "3"}, headers=HTMX).status_code == 404
