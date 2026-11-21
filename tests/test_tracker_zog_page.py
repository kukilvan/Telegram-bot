"""«Страница на ZoG» — the owner's page (spec 5.7 of stage 9.1b, ticket 06) through the facade on a fake clock:
`set_zog_page` with a fake ZoG client (every answer of 5.7: empty, a foreign address, «Ошибка», ZoG that did not answer, a
game out of the two statuses, a title that is no game or is gone; the save, the same link twice, the reference point,
«next check in 7 days», the withdrawal of the undelivered fan events, a layout that cannot be read) and
`reject_zog_page` («Не та игра»: the state, twice, a link after it, the withdrawal, ZoG not asked); the owner saving a
page while the weekly check is asking ZoG.

The game source is a made-up IGDB, Steam's languages and ZoG fakes of `test_tracker_zog_check`; the pages are the saved
ones or made up there.
"""

from datetime import timedelta

import pytest

from app.providers.zog import ZogError
from app.tracker.core import Tracker, UnknownTitle, ZogPageRefused
from app.tracker.db import create_session_factory
from app.tracker.models import TitleKind
from app.tracker.pollers import game_zog
from app.tracker.russian import Support
from app.tracker.zog_page import EMPTY, NO_SUCH_PAGE, NOT_ANSWERED, NOT_A_PAGE
from test_tracker_game_prices import FakeClock, MadeUpGames, naive, run
from test_tracker_russian_check import FakeLanguages
from test_tracker_steam_events import T0
from test_tracker_zog_check import (
    BALDURS, FakeZog, Sender, add, card, fan_events, made_up_page, week, zog_snapshot,
)
from test_web_card import FILM, FakeSource
from test_zog_pages import saved

BG3 = "https://www.zoneofgames.ru/games/baldurs_gate_3/"
NOTHING = {"page": None, "by": "rejected"}
OWNERS = {"page": "baldurs_gate_3", "by": "owner", "text": True, "voice": True}


class SlowZog(FakeZog):
    """ZoG that runs `during` (once) while it answers its first request: the owner pressing a button meanwhile."""

    def __init__(self):
        super().__init__()
        self.during = None

    async def page(self, page):
        if self.during is not None:
            callback, self.during = self.during, None
            await callback()
        return await super().page(page)


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def igdb():
    return MadeUpGames()


@pytest.fixture
def steam():
    return FakeLanguages()


@pytest.fixture
def zog():
    return SlowZog()


@pytest.fixture(autouse=True)
def pauses(monkeypatch, clock):
    async def pause(seconds):
        clock.advance(seconds=seconds)

    monkeypatch.setattr(game_zog, "sleep", pause)


@pytest.fixture
def tracker(session_factory, clock, igdb, steam, zog):
    return Tracker(
        session_factory, clock=clock, sender=Sender(),
        sources={TitleKind.GAME: igdb, TitleKind.MOVIE: FakeSource("tmdb_movie", FILM)}, language_source=steam,
        zog_source=zog,
    )


def refused(tracker, title_id, link):
    with pytest.raises(ZogPageRefused) as caught:
        run(tracker.set_zog_page(title_id, link))
    return caught.value.text


# --- the answers of 5.7: nothing is saved -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "link, text",
    [
        ("", EMPTY),
        ("   ", EMPTY),
        ("привет", NOT_A_PAGE),
        ("https://store.steampowered.com/app/1145350/", NOT_A_PAGE),
        ("https://www.zoneofgames.ru/news/", NOT_A_PAGE),
        ("ftp://www.zoneofgames.ru/games/stray/", NOT_A_PAGE),
        ("https://zoneofgames.ru.evil.example/games/stray/", NOT_A_PAGE),
    ],
)
def test_a_link_that_is_no_game_page_is_refused_without_asking_zog(link, text, tracker, igdb, zog, session_factory):
    title_id = add(tracker, igdb, "Stray", year=2022)

    assert refused(tracker, title_id, link) == text

    assert zog.calls == []
    assert zog_snapshot(session_factory, title_id) is None


def test_a_page_zog_does_not_have_is_refused(tracker, igdb, zog, session_factory):
    title_id = add(tracker, igdb, "Stray", year=2022)

    assert refused(tracker, title_id, "https://www.zoneofgames.ru/games/no_such_game/") == NO_SUCH_PAGE

    assert zog.calls == ["no_such_game"]
    assert zog_snapshot(session_factory, title_id) is None


@pytest.mark.parametrize("failure", [ZogError("ZoG page stray: HTTP 503", status=503), TimeoutError("slow")])
def test_zog_that_does_not_answer_is_said_and_nothing_is_saved(failure, tracker, igdb, zog, session_factory):
    zog.pages["stray"] = saved("stray")
    title_id = add(tracker, igdb, "Stray", year=2022)
    run(tracker.poll_due())
    before = zog_snapshot(session_factory, title_id).state
    zog.failure = failure

    assert refused(tracker, title_id, "https://www.zoneofgames.ru/games/baldurs_gate_3/") == NOT_ANSWERED

    assert zog_snapshot(session_factory, title_id).state == before


def test_the_refusal_keeps_the_state_the_check_stored(tracker, igdb, zog, session_factory):
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Baldur's Gate 3")
    run(tracker.poll_due())
    before = zog_snapshot(session_factory, title_id)

    assert refused(tracker, title_id, "") == EMPTY

    after = zog_snapshot(session_factory, title_id)
    assert (after.state, after.observed_at, after.next_check_at) == (before.state, before.observed_at, before.next_check_at)


# --- a good link ------------------------------------------------------------------------------------------------------


def test_a_good_link_saves_the_page_as_the_owners_with_its_support_read_now(tracker, igdb, zog, session_factory):
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Stray", year=2022)  # the owner's choice wins: no name or year check

    result = run(tracker.set_zog_page(title_id, f"  {BG3}files/12.html?a=b#c  "))

    assert result.changed is True
    assert zog.calls == ["baldurs_gate_3"]
    stored = zog_snapshot(session_factory, title_id)
    assert stored.state == OWNERS
    assert stored.observed_at == naive(T0)
    assert stored.next_check_at == naive(T0) + timedelta(days=7)
    assert fan_events(session_factory) == []  # a reference point: no message
    view = card(tracker, title_id).russian
    assert view.line == "текст и озвучка — народные"
    assert view.zog_link == BG3
    assert (view.form, view.zog_value, view.can_reject) == (True, BG3, True)


def test_a_link_in_capitals_and_without_the_scheme_host_www_is_read(tracker, igdb, zog, session_factory):
    zog.pages["stray"] = saved("stray")
    title_id = add(tracker, igdb, "Stray", year=2022)

    run(tracker.set_zog_page(title_id, "HTTP://ZoneOfGames.RU/games/Stray/"))

    assert zog_snapshot(session_factory, title_id).state == {"page": "stray", "by": "owner", "text": False, "voice": False}


def test_the_same_link_twice_is_the_same_state(tracker, igdb, zog, session_factory):
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Baldur's Gate 3")
    run(tracker.set_zog_page(title_id, BG3))

    again = run(tracker.set_zog_page(title_id, BG3))

    assert again.changed is False
    assert zog_snapshot(session_factory, title_id).state == OWNERS
    assert fan_events(session_factory) == []


def test_a_game_not_checked_yet_gets_its_snapshot_from_the_press(tracker, igdb, zog, session_factory):
    zog.pages["stray"] = saved("stray")
    title_id = add(tracker, igdb, "Stray", year=2022)
    assert zog_snapshot(session_factory, title_id) is None  # the pass has not run

    run(tracker.set_zog_page(title_id, "https://www.zoneofgames.ru/games/stray/"))
    run(tracker.poll_due())

    assert zog.calls == ["stray"]  # the pass did not ask a page the owner has just given: next check in a week
    assert zog_snapshot(session_factory, title_id).state["by"] == "owner"


def test_the_owners_page_is_a_reference_point_then_a_later_part_is_told(tracker, igdb, steam, zog, clock, session_factory):
    steam.support[BALDURS] = Support(True, False)
    zog.pages["baldurs_gate_3"] = made_up_page("Baldur's Gate 3", ("Українізатор (текст)",), 2023)
    title_id = add(tracker, igdb, "Baldur's Gate 3")
    run(tracker.set_zog_page(title_id, BG3))
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")

    week(tracker, clock)

    [event] = fan_events(session_factory)
    assert event.payload["parts"] == "voice"
    assert event.payload["zog_page"] == "baldurs_gate_3"
    assert zog_snapshot(session_factory, title_id).state["by"] == "owner"


def test_a_link_withdraws_the_undelivered_fan_events_of_the_game(tracker, igdb, zog, clock, session_factory):
    zog.pages["hades_2"] = made_up_page("Hades 2", (), 2025)
    title_id = add(tracker, igdb, "Hades 2", year=2025)
    run(tracker.poll_due())
    zog.pages["hades_2"] = saved("hades_2")
    week(tracker, clock)
    assert len(fan_events(session_factory)) == 1
    zog.pages["split_fiction"] = saved("split_fiction")

    run(tracker.set_zog_page(title_id, "https://www.zoneofgames.ru/games/split_fiction/"))

    assert fan_events(session_factory) == []
    assert zog_snapshot(session_factory, title_id).state["page"] == "split_fiction"


def test_a_layout_that_cannot_be_read_is_still_the_owners_page_marked_unreadable(tracker, igdb, zog, session_factory):
    zog.pages["broken"] = "<title>Совсем другая страница</title>"
    title_id = add(tracker, igdb, "Stray", year=2022)

    run(tracker.set_zog_page(title_id, "https://www.zoneofgames.ru/games/broken/"))

    assert zog_snapshot(session_factory, title_id).state == {"page": "broken", "by": "owner", "unreadable": True}
    view = card(tracker, title_id).russian
    assert view.hints[-1] == "Страницу на ZoG не удалось прочитать — народный перевод пока неизвестен"
    assert view.zog_link == ""


def test_a_page_with_entries_nobody_can_read_is_unreadable_too(tracker, igdb, zog, session_factory):
    zog.pages["odd"] = "<title>Odd | Игровой архив на Zone of Games</title><b>Переводы:</b></table>"
    title_id = add(tracker, igdb, "Stray", year=2022)

    run(tracker.set_zog_page(title_id, "https://www.zoneofgames.ru/games/odd/"))

    assert zog_snapshot(session_factory, title_id).state == {"page": "odd", "by": "owner", "unreadable": True}


# --- «Не та игра» -----------------------------------------------------------------------------------------------------


def test_not_that_game_rejects_the_page_without_asking_zog(tracker, igdb, zog, session_factory):
    zog.pages["stray"] = saved("stray")
    title_id = add(tracker, igdb, "Stray", year=2022)
    run(tracker.poll_due())
    zog.calls.clear()

    result = run(tracker.reject_zog_page(title_id))

    assert result.changed is True
    assert zog.calls == []
    stored = zog_snapshot(session_factory, title_id)
    assert stored.state == NOTHING
    assert stored.next_check_at == naive(T0) + timedelta(days=7)
    view = card(tracker, title_id).russian
    assert view.hints[-1] == "Страница на ZoG не указана — вставьте ссылку, если перевод есть"
    assert (view.form, view.zog_value, view.can_reject, view.zog_link) == (True, "", False, "")


def test_not_that_game_twice_is_the_same(tracker, igdb, zog, session_factory):
    title_id = add(tracker, igdb, "Stray", year=2022)
    run(tracker.reject_zog_page(title_id))

    again = run(tracker.reject_zog_page(title_id))

    assert again.changed is False
    assert zog_snapshot(session_factory, title_id).state == NOTHING


def test_a_rejected_game_is_not_found_by_itself_and_a_link_after_it_is_the_owners_page(tracker, igdb, zog, clock, session_factory):
    zog.pages["stray"] = saved("stray")
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Stray", year=2022)
    run(tracker.reject_zog_page(title_id))
    week(tracker, clock)
    assert zog.calls == []  # never asked, nothing found
    assert zog_snapshot(session_factory, title_id).state == NOTHING

    run(tracker.set_zog_page(title_id, BG3))

    assert zog_snapshot(session_factory, title_id).state == OWNERS
    assert fan_events(session_factory) == []


def test_not_that_game_withdraws_the_undelivered_fan_events(tracker, igdb, zog, clock, session_factory):
    zog.pages["hades_2"] = made_up_page("Hades 2", (), 2025)
    title_id = add(tracker, igdb, "Hades 2", year=2025)
    run(tracker.poll_due())
    zog.pages["hades_2"] = saved("hades_2")
    week(tracker, clock)
    assert len(fan_events(session_factory)) == 1

    run(tracker.reject_zog_page(title_id))

    assert fan_events(session_factory) == []


# --- who may press ----------------------------------------------------------------------------------------------------


def test_a_game_out_of_the_two_statuses_changes_nothing_and_asks_nothing(tracker, igdb, steam, zog, session_factory):
    steam.support[BALDURS] = Support(True, False)  # the card keeps its last line after «Прошёл»
    zog.pages["stray"] = saved("stray")
    title_id = add(tracker, igdb, "Stray", year=2022)
    run(tracker.poll_due())
    run(tracker.mark_watched(title_id))
    before = zog_snapshot(session_factory, title_id).state
    zog.calls.clear()

    assert run(tracker.set_zog_page(title_id, BG3)).changed is False
    assert run(tracker.set_zog_page(title_id, "")).changed is False  # no error under a field that is not there
    assert run(tracker.reject_zog_page(title_id)).changed is False

    assert zog.calls == []
    assert zog_snapshot(session_factory, title_id).state == before
    assert card(tracker, title_id).russian.form is False


def test_a_title_that_is_no_game_changes_nothing(tracker, session_factory):
    movie_id = run(tracker.add_title(TitleKind.MOVIE, "1")).title_id

    assert run(tracker.set_zog_page(movie_id, BG3)).changed is False
    assert run(tracker.reject_zog_page(movie_id)).changed is False
    assert zog_snapshot(session_factory, movie_id) is None


def test_a_title_that_is_gone_raises_unknown_title(tracker):
    with pytest.raises(UnknownTitle):
        run(tracker.set_zog_page(99, BG3))
    with pytest.raises(UnknownTitle):
        run(tracker.reject_zog_page(99))


def test_a_game_that_left_the_statuses_while_zog_answered_is_not_saved(tracker, igdb, zog, session_factory):
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Stray", year=2022)
    zog.during = lambda: tracker.mark_dropped(title_id)

    assert run(tracker.set_zog_page(title_id, BG3)).changed is False

    assert zog_snapshot(session_factory, title_id) is None


def test_without_the_zog_client_nothing_is_saved_and_the_card_has_no_form(clock, igdb, steam, session_factory):
    tracker = Tracker(session_factory, clock=clock, sender=Sender(), sources={TitleKind.GAME: igdb}, language_source=steam)
    title_id = add(tracker, igdb, "Stray", year=2022)

    assert run(tracker.set_zog_page(title_id, BG3)).changed is False
    assert run(tracker.reject_zog_page(title_id)).changed is False

    assert zog_snapshot(session_factory, title_id) is None
    assert card(tracker, title_id).russian.form is False


# --- the owner saves while the weekly check asks ZoG -------------------------------------------------------------------


@pytest.mark.parametrize("press", ["reject", "link"])
def test_the_owners_page_wins_over_a_check_that_was_asking_zog(press, tracker, igdb, zog, session_factory):
    zog.pages["stray"] = saved("stray")
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Stray", year=2022)
    if press == "reject":
        zog.during = lambda: tracker.reject_zog_page(title_id)
    else:
        zog.during = lambda: tracker.set_zog_page(title_id, BG3)

    run(tracker.poll_due())

    stored = zog_snapshot(session_factory, title_id)
    assert stored.state == (NOTHING if press == "reject" else OWNERS)
    assert stored.next_check_at == naive(T0) + timedelta(days=7)
    assert fan_events(session_factory) == []
