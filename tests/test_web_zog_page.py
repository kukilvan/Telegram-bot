"""«Страница на ZoG» in the browser (spec 5.3 item 4 and 5.7 of stage 9.1b, ticket 06): the form of the block «Русский
язык» in every state (no page, a page found, the owner's page, rejected, unreadable, the game in another status, no
ZoG client, a title that is no game), the two presses `POST /titles/<id>/zog` and `/zog/reject` (login required, the
fresh card fragment, the error under the field with the typed text still in it, a title gone, a game that left
«Хочу» and «В процессе», a title that is no game) and the plain form without HTMX.

The real core on in-memory SQLite with a stand-in clock, a made-up game source, fakes for Steam's languages and ZoG;
the web is the real app on a `TestClient`.
"""

import re

import pytest

from app.providers.zog import ZogError
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import TitleKind
from app.tracker.russian import Support
from test_tracker_game_prices import FakeClock, MadeUpGames, run
from test_tracker_russian_check import FakeLanguages
from test_tracker_steam_events import T0
from test_tracker_zog_check import BALDURS, FakeZog, Sender, add, made_up_page, zog_snapshot
from test_tracker_zog_page import BG3, NOTHING, OWNERS
from test_web_card import FILM, FakeSource, HTMX, make_client
from test_zog_pages import saved

BAD = "Это не страница игры на ZoG. Нужна ссылка вида https://www.zoneofgames.ru/games/…/"
NOT_SET = "Страница на ZoG не указана — вставьте ссылку, если перевод есть"


@pytest.fixture
def igdb():
    return MadeUpGames()


@pytest.fixture
def steam():
    return FakeLanguages()


@pytest.fixture
def zog():
    return FakeZog()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def tracker(session_factory, igdb, steam, zog):
    return Tracker(
        session_factory, clock=FakeClock(T0), sender=Sender(),
        sources={TitleKind.GAME: igdb, TitleKind.MOVIE: FakeSource("tmdb_movie", FILM)}, language_source=steam,
        zog_source=zog,
    )


@pytest.fixture
def client(tracker, tmp_path):
    return make_client(tracker, tmp_path)


def section(html, name="russian"):
    found = re.search(rf'<section class="{name}".*?</section>', html, re.S)
    return found.group(0) if found else ""


def text_of(html):
    return re.sub(r"[ \t\r\n]+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def block(client, title_id):
    return section(client.get(f"/titles/{title_id}").text)


def field_value(html):
    found = re.search(r'<input id="zog-link"[^>]*? value="([^"]*)"', html)
    return found.group(1) if found else None


def baldurs(tracker, igdb, steam, zog):
    """Baldur's Gate 3 checked by the pass: the page found by itself."""
    steam.support[BALDURS] = Support(True, False)
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Baldur's Gate 3")
    run(tracker.poll_due())
    return title_id


# --- the form in every state --------------------------------------------------------------------------------------------


def test_a_game_not_checked_yet_has_an_empty_field_and_no_reject_button(tracker, igdb, client):
    title_id = add(tracker, igdb, "Stray", year=2022)

    html = block(client, title_id)

    assert '<label for="zog-link">Страница на ZoG</label>' in html
    assert field_value(html) == ""
    assert 'placeholder="https://www.zoneofgames.ru/games/…/"' in html
    assert f'hx-post="/titles/{title_id}/zog"' in html and 'name="link"' in html and 'type="text"' in html  # no browser check
    assert "Сохранить" in html and "Не та игра" not in html


def test_a_page_found_shows_its_address_and_the_reject_button(tracker, igdb, steam, zog, client):
    title_id = baldurs(tracker, igdb, steam, zog)

    html = block(client, title_id)

    assert field_value(html) == BG3
    assert f'hx-post="/titles/{title_id}/zog/reject"' in html and "Не та игра" in html
    assert f'<a href="{BG3}" target="_blank" rel="noopener">Страница перевода</a>' in html


def test_the_page_not_found_has_the_hint_and_an_empty_field(tracker, igdb, zog, client):
    title_id = add(tracker, igdb, "Stray", year=2022)
    zog.pages["stray"] = made_up_page("Совсем другая игра", (), 2022)
    run(tracker.poll_due())

    html = block(client, title_id)

    assert "Страница на ZoG не найдена — вставьте ссылку, если перевод есть" in text_of(html)
    assert field_value(html) == "" and "Не та игра" not in html


def test_a_rejected_game_has_the_hint_an_empty_field_and_no_reject_button(tracker, igdb, client):
    title_id = add(tracker, igdb, "Stray", year=2022)
    run(tracker.reject_zog_page(title_id))

    html = block(client, title_id)

    assert NOT_SET in text_of(html)
    assert field_value(html) == "" and "Не та игра" not in html


def test_a_game_in_another_status_has_the_line_and_no_form(tracker, igdb, steam, zog, client):
    title_id = baldurs(tracker, igdb, steam, zog)
    run(tracker.mark_watched(title_id))

    html = block(client, title_id)

    assert "Русский:" in html
    assert "zog-form" not in html and "zog-link" not in html and "Не та игра" not in html


def test_no_form_without_the_zog_client(igdb, steam, session_factory, tmp_path):
    tracker = Tracker(
        session_factory, clock=FakeClock(T0), sender=Sender(), sources={TitleKind.GAME: igdb}, language_source=steam
    )
    steam.support[BALDURS] = Support(True, False)
    title_id = add(tracker, igdb, "Stray", year=2022)
    run(tracker.poll_due())

    html = block(make_client(tracker, tmp_path), title_id)

    assert "Русский:" in html and "zog-form" not in html


def test_a_movie_has_no_such_block(tracker, client):
    movie_id = run(tracker.add_title(TitleKind.MOVIE, "1")).title_id

    assert "zog-form" not in client.get(f"/titles/{movie_id}").text


# --- the presses --------------------------------------------------------------------------------------------------------


def test_the_presses_need_the_login(tracker, igdb, session_factory, tmp_path):
    title_id = add(tracker, igdb, "Stray", year=2022)
    from fastapi.testclient import TestClient

    anonymous = TestClient(make_client(tracker, tmp_path).app, follow_redirects=False)

    for address, data in ((f"/titles/{title_id}/zog", {"link": BG3}), (f"/titles/{title_id}/zog/reject", {})):
        answer = anonymous.post(address, data=data, headers=HTMX)
        assert answer.status_code in (303, 401) and "Страница" not in answer.text
    assert zog_snapshot(session_factory, title_id) is None


def test_a_bad_link_is_the_error_under_the_field_with_the_typed_text_kept(tracker, igdb, zog, client, session_factory):
    title_id = add(tracker, igdb, "Stray", year=2022)

    answer = client.post(f"/titles/{title_id}/zog", data={"link": "привет"}, headers=HTMX)

    assert answer.status_code == 200
    assert answer.text.lstrip().startswith('<article id="card"')  # the fresh card, not a page
    html = section(answer.text)
    assert BAD in html and 'role="alert"' in html
    assert field_value(html) == "привет"
    assert zog_snapshot(session_factory, title_id) is None
    assert zog.calls == []


@pytest.mark.parametrize(
    "link, text, calls",
    [
        ("", "Вставьте ссылку на страницу игры на ZoG", 0),
        ("https://www.zoneofgames.ru/games/no_such_game/", "На ZoG нет такой страницы — проверьте ссылку", 1),
    ],
)
def test_the_other_refusals_stand_as_written(link, text, calls, tracker, igdb, zog, client, session_factory):
    title_id = add(tracker, igdb, "Stray", year=2022)

    html = section(client.post(f"/titles/{title_id}/zog", data={"link": link}, headers=HTMX).text)

    assert text in text_of(html)
    assert field_value(html) == link
    assert len(zog.calls) == calls
    assert zog_snapshot(session_factory, title_id) is None


def test_a_zog_that_does_not_answer_is_said_and_the_text_stays(tracker, igdb, zog, client, session_factory):
    title_id = add(tracker, igdb, "Stray", year=2022)
    zog.failure = ZogError("timeout")

    html = section(client.post(f"/titles/{title_id}/zog", data={"link": BG3}, headers=HTMX).text)

    assert "ZoG не ответил — попробуйте позже" in text_of(html)
    assert field_value(html) == BG3
    assert zog_snapshot(session_factory, title_id) is None


def test_an_html_link_is_shown_escaped_in_the_field(tracker, igdb, client):
    title_id = add(tracker, igdb, "Stray", year=2022)

    html = client.post(f"/titles/{title_id}/zog", data={"link": '"><script>alert(1)</script>'}, headers=HTMX).text

    assert "<script>alert(1)</script>" not in html
    assert field_value(section(html)) == "&#34;&gt;&lt;script&gt;alert(1)&lt;/script&gt;"


def test_a_good_link_gives_the_line_the_link_the_address_and_the_reject_button(tracker, igdb, steam, zog, client, session_factory):
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Baldur's Gate 3")

    answer = client.post(f"/titles/{title_id}/zog", data={"link": BG3}, headers=HTMX)

    html = section(answer.text)
    assert "<b>Русский:</b> текст и озвучка — народные" in html
    assert f'<a href="{BG3}" target="_blank" rel="noopener">Страница перевода</a>' in html
    assert field_value(html) == BG3 and "Не та игра" in html and 'role="alert"' not in html
    assert zog_snapshot(session_factory, title_id).state == OWNERS


def test_not_that_game_takes_the_fan_part_away_and_says_the_page_is_not_set(tracker, igdb, steam, zog, client, session_factory):
    title_id = baldurs(tracker, igdb, steam, zog)
    assert "народн" in block(client, title_id)

    answer = client.post(f"/titles/{title_id}/zog/reject", headers=HTMX)

    html = section(answer.text)
    assert "народн" not in html and "Страница перевода" not in html
    assert NOT_SET in text_of(html)
    assert field_value(html) == "" and "Не та игра" not in html
    assert zog_snapshot(session_factory, title_id).state == NOTHING


def test_the_owners_walk_of_the_check(tracker, igdb, steam, zog, client, session_factory):
    """The owner check of the ticket: a wrong text, a right link, «Не та игра»."""
    steam.support[BALDURS] = Support(False, False)
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Stray", year=2022)

    first = section(client.post(f"/titles/{title_id}/zog", data={"link": "привет"}, headers=HTMX).text)
    second = section(client.post(f"/titles/{title_id}/zog", data={"link": BG3}, headers=HTMX).text)
    third = section(client.post(f"/titles/{title_id}/zog/reject", headers=HTMX).text)

    assert BAD in text_of(first) and field_value(first) == "привет"
    assert "<b>Русский:</b> текст и озвучка — народные" in second
    assert "Страница перевода" in second and field_value(second) == BG3 and "Не та игра" in second
    assert NOT_SET in text_of(third) and "народн" not in third and "Не та игра" not in third


def test_a_game_that_left_the_statuses_gets_the_card_without_the_form(tracker, igdb, steam, zog, client, session_factory):
    title_id = baldurs(tracker, igdb, steam, zog)
    run(tracker.mark_dropped(title_id))
    before = zog_snapshot(session_factory, title_id).state

    for address, data in ((f"/titles/{title_id}/zog", {"link": BG3}), (f"/titles/{title_id}/zog/reject", {})):
        answer = client.post(address, data=data, headers=HTMX)
        assert answer.status_code == 200
        assert answer.text.lstrip().startswith('<article id="card"')
        assert "zog-form" not in answer.text and "Не та игра" not in answer.text

    assert zog_snapshot(session_factory, title_id).state == before


def test_a_title_that_is_gone_gives_the_fragment_title_gone(tracker, igdb, client):
    title_id = add(tracker, igdb, "Stray", year=2022)
    run(tracker.delete_title(title_id))

    for address, data in ((f"/titles/{title_id}/zog", {"link": BG3}), (f"/titles/{title_id}/zog/reject", {})):
        answer = client.post(address, data=data, headers=HTMX)
        assert answer.status_code == 200
        assert "Этого тайтла больше нет в списке" in answer.text
        assert "<article" not in answer.text


def test_a_press_on_a_number_that_is_no_title_is_title_gone_too(client):
    answer = client.post("/titles/99999999999999999999999/zog", data={"link": BG3}, headers=HTMX)

    assert answer.status_code == 200 and "Этого тайтла больше нет в списке" in answer.text


def test_a_press_on_a_movie_gives_its_card_without_the_form(tracker, client, session_factory):
    movie_id = run(tracker.add_title(TitleKind.MOVIE, "1")).title_id

    answer = client.post(f"/titles/{movie_id}/zog", data={"link": BG3}, headers=HTMX)

    assert answer.status_code == 200 and answer.text.lstrip().startswith('<article id="card"')
    assert "zog-form" not in answer.text
    assert zog_snapshot(session_factory, movie_id) is None


def test_the_plain_form_without_htmx_goes_back_to_the_card_with_the_error_as_a_notice(tracker, igdb, client, session_factory):
    title_id = add(tracker, igdb, "Stray", year=2022)

    answer = client.post(f"/titles/{title_id}/zog", data={"link": "привет"})

    assert answer.status_code == 303 and answer.headers["location"] == f"/titles/{title_id}"
    assert BAD in text_of(client.get(f"/titles/{title_id}").text)
    assert zog_snapshot(session_factory, title_id) is None


def test_the_plain_form_saves_a_good_link(tracker, igdb, zog, client, session_factory):
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Baldur's Gate 3")

    answer = client.post(f"/titles/{title_id}/zog", data={"link": BG3})

    assert answer.status_code == 303
    assert zog_snapshot(session_factory, title_id).state == OWNERS
    assert field_value(block(client, title_id)) == BG3
