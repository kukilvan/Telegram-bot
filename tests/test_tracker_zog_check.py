"""The ZoG check at the end of a pass (spec 5.3, 5.6, 5.9 of stage 9.1b, ticket 05) through the facade on a fake clock:
finding a page (the order, each address once, the four-request limit, the first hit taken or refused by its name and
year), the cadence (two games a pass, never-checked first, a second between requests, a rejected page never asked),
the states, the reference points (the first read of a page, the first check after «Вернуть в список»), the fan events
with the official filter, an unreadable layout (the last support kept, a log line a day), a failure that tells the owner
nothing, a stored page turning «Ошибка»; the card (the line, the hints, the link, the bot button) and the sample.

The game source is a made-up IGDB (`MadeUpGames`), Steam's languages and ZoG fakes the test writes; the ZoG pages are
the saved ones (`tests/fixtures/zog/`) or made up here.
"""

import logging
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.providers.zog import ZogError
from app.tracker import actions, failures, russian_events
from app.tracker.cards import format_card
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.games import GameState
from app.tracker.models import Event, SourceSnapshot, TitleKind
from app.tracker.pollers import game_zog
from app.tracker.russian import Support
from app.tracker.sources.igdb_games import GameSnapshot
from test_tracker_game_prices import FakeClock, MadeUpGames, naive, run
from test_tracker_russian_check import FakeLanguages
from test_tracker_steam_events import T0
from test_zog_pages import saved

BALDURS = "1086940"
TEXT = Support(True, False)
VOICE = Support(False, True)
BOTH = Support(True, True)
ERROR_PAGE = saved("the_witcher_3_wild_hunt")


def made_up_page(name: str, entries: tuple[str, ...] = (), year: int = 2024) -> str:
    """A game page; no entries — no «Переводы:» at all (no translations)."""
    rows = "".join(f"<tr><td><a href='/games/x/files/{n}.html'>{text}</a></td></tr>" for n, text in enumerate(entries, 1))
    translations = f"<table><tr><td><b>Переводы:</b></td></tr>{rows}</table>" if entries else ""
    return (
        f"<title>{name} | Игровой архив на Zone of Games</title>"
        f"<p>В официальной продаже с <a href='/games/year/{year}.html'>{year}</a></p>{translations}"
    )


class FakeZog:
    """ZoG: `pages` — page → its text (absent: the «Ошибка» page), `failure` — every request fails."""

    def __init__(self):
        self.pages = {}
        self.failure = None
        self.calls = []

    async def page(self, page):
        self.calls.append(page)
        if self.failure is not None:
            raise self.failure
        return self.pages.get(page, ERROR_PAGE)


class Sender:
    def __init__(self):
        self.sent = []

    async def send(self, message, actions=()):
        self.sent.append((message, list(actions)))


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
    return FakeZog()


@pytest.fixture
def pauses(monkeypatch, clock):
    seen = []

    async def pause(seconds):
        seen.append(seconds)
        clock.advance(seconds=seconds)

    monkeypatch.setattr(game_zog, "sleep", pause)
    return seen


@pytest.fixture
def sender():
    return Sender()


@pytest.fixture
def tracker(session_factory, clock, igdb, steam, zog, pauses, sender):
    return Tracker(
        session_factory, clock=clock, sender=sender, sources={TitleKind.GAME: igdb}, language_source=steam,
        zog_source=zog,
    )


def add(tracker, igdb, name, external_id="1", year=2023, steam_id=BALDURS, platforms=(6,), original=None):
    igdb.by_id[external_id] = GameSnapshot(
        external_id, name, original or name, year, game=GameState(steam_id=steam_id, platforms=platforms)
    )
    return run(tracker.add_title(TitleKind.GAME, external_id)).title_id


def week(tracker, clock):
    clock.advance(days=7)
    run(tracker.poll_due())


def zog_snapshot(session_factory, title_id):
    with session_factory() as session:
        return session.scalar(
            select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "zog")
        )


def fan_events(session_factory):
    with session_factory() as session:
        return list(session.scalars(select(Event).where(Event.type == russian_events.FAN).order_by(Event.id)))


def failure_events(session_factory):
    with session_factory() as session:
        return list(session.scalars(select(Event).where(Event.type == failures.SOURCE_FAILED)))


def card(tracker, title_id):
    return run(tracker.title_card(title_id))


# --- finding a page --------------------------------------------------------------------------------------------------


def test_baldurs_gate_3_is_found_read_and_shown_without_a_message(tracker, igdb, steam, zog, session_factory):
    steam.support[BALDURS] = TEXT
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Baldur's Gate 3")

    run(tracker.poll_due())

    assert zog.calls == ["baldurs_gate_3"]
    stored = zog_snapshot(session_factory, title_id)
    assert stored.state == {"page": "baldurs_gate_3", "by": "found", "text": True, "voice": True}
    assert stored.next_check_at == naive(T0) + timedelta(days=7)
    assert fan_events(session_factory) == []  # the first read of a page is the reference point
    view = card(tracker, title_id).russian
    assert view.line == "текст — официально; озвучка — народная"
    assert view.hints == ("Steam — проверено сегодня в 12:00 · ZoG — проверено сегодня в 12:00",)
    assert view.zog_link == "https://www.zoneofgames.ru/games/baldurs_gate_3/"


def test_the_bot_card_has_the_line_and_the_translation_page_button_before_delete(tracker, igdb, steam, zog):
    steam.support[BALDURS] = TEXT
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Baldur's Gate 3")
    run(tracker.poll_due())

    the_card = card(tracker, title_id)
    buttons = actions.card_actions(the_card)

    assert "Русский: текст — официально; озвучка — народная" in format_card(the_card).splitlines()
    assert [button.label for button in buttons] == ["🌐 Страница перевода", "🗑 Удалить"]
    assert buttons[0].url == "https://www.zoneofgames.ru/games/baldurs_gate_3/"


@pytest.mark.parametrize(
    "name, page, calls",
    [
        ("Baldur's Gate III", "baldurs_gate_3", ["baldurs_gate_iii", "baldurs_gate_3"]),
        ("Hades II", "hades_2", ["hades_ii", "hades_2"]),
    ],
)
def test_the_numbers_switched_find_the_page(name, page, calls, tracker, igdb, zog, session_factory):
    zog.pages[page] = saved(page)
    title_id = add(tracker, igdb, name, year=2025 if page == "hades_2" else 2023)

    run(tracker.poll_due())

    assert zog.calls == calls
    assert zog_snapshot(session_factory, title_id).state["page"] == page


def test_the_witcher_3_asks_four_addresses_and_is_not_found(tracker, igdb, steam, zog, session_factory):
    steam.support[BALDURS] = BOTH
    title_id = add(tracker, igdb, "The Witcher 3: Wild Hunt", year=2015)

    run(tracker.poll_due())

    assert zog.calls == ["the_witcher_3_wild_hunt", "the_witcher_iii_wild_hunt", "the_witcher_3", "the_witcher_iii"]
    stored = zog_snapshot(session_factory, title_id)
    assert stored.state == {"page": None, "by": "none"}
    assert stored.next_check_at == naive(T0) + timedelta(days=7, seconds=3)  # three pauses before the store
    view = card(tracker, title_id).russian
    assert view.line == "текст и озвучка — официально"
    assert view.hints == (
        "Steam — проверено сегодня в 12:00", "Страница на ZoG не найдена — вставьте ссылку, если перевод есть",
    )
    assert view.zog_link == ""


def test_prey_of_2006_is_refused_for_prey_of_2017_and_the_finding_stops(tracker, igdb, zog, session_factory):
    zog.pages["prey"] = saved("prey")
    title_id = add(tracker, igdb, "Prey", year=2017)

    run(tracker.poll_due())

    assert zog.calls == ["prey"]
    assert zog_snapshot(session_factory, title_id).state == {"page": None, "by": "none"}


def test_a_name_that_does_not_match_is_refused(tracker, igdb, zog, session_factory):
    zog.pages["stray"] = made_up_page("Stray Souls", ("Русификатор (текст)",))
    title_id = add(tracker, igdb, "Stray")

    run(tracker.poll_due())

    assert zog_snapshot(session_factory, title_id).state == {"page": None, "by": "none"}


def test_the_russian_name_matches_too(tracker, igdb, zog, session_factory):
    zog.pages["the_witcher_3_wild_hunt"] = made_up_page("Ведьмак 3: Дикая Охота", ("Русификатор (звук)",), 2015)
    title_id = add(tracker, igdb, "Ведьмак 3: Дикая Охота", year=2015, original="The Witcher 3: Wild Hunt")

    run(tracker.poll_due())

    assert zog.calls == ["the_witcher_3_wild_hunt"]  # the addresses are of the original name
    assert zog_snapshot(session_factory, title_id).state["page"] == "the_witcher_3_wild_hunt"


def test_zog_read_before_the_official_check_keeps_the_not_checked_hint(tracker, igdb, steam, zog, session_factory):
    zog.pages["grand_theft_auto_6"] = made_up_page("Grand Theft Auto 6", (), 2026)
    title_id = add(tracker, igdb, "Grand Theft Auto VI", year=2026, steam_id=None, platforms=(167,))

    run(tracker.poll_due())  # IGDB «not asked yet», no Steam page: the official look stays empty

    view = card(tracker, title_id).russian
    assert view.line == "нет данных"
    assert view.hints == ("Ещё не проверяли — строка появится через минуту-другую", "ZoG — проверено сегодня в 12:00")


# --- the cadence -----------------------------------------------------------------------------------------------------


def test_two_games_a_pass_never_checked_first_a_second_between_requests(tracker, igdb, zog, pauses, clock, session_factory):
    for number, name in enumerate(("Stray", "Hades 2", "Disco Elysium"), 1):
        zog.pages[name.lower().replace(" ", "_")] = saved(name.lower().replace(" ", "_"))
    first = add(tracker, igdb, "Stray", external_id="1", year=2022)
    add(tracker, igdb, "Hades 2", external_id="2", year=2025)
    third = add(tracker, igdb, "Disco Elysium", external_id="3", year=2019)

    run(tracker.poll_due())

    assert zog.calls == ["stray", "hades_2"]
    assert pauses == [1.0]  # between the two requests, not before the first
    assert zog_snapshot(session_factory, third).state == {}
    clock.advance(minutes=1)
    run(tracker.poll_due())
    assert zog.calls == ["stray", "hades_2", "disco_elysium"]
    assert pauses == [1.0]  # the first request of a pass does not wait
    assert zog_snapshot(session_factory, third).state["page"] == "disco_elysium"
    clock.advance(minutes=1)
    run(tracker.poll_due())
    assert len(zog.calls) == 3  # nothing due for a week
    assert zog_snapshot(session_factory, first).state["by"] == "found"


def test_a_rejected_page_is_never_asked(tracker, igdb, zog, clock, session_factory):
    title_id = add(tracker, igdb, "Stray", year=2022)
    with session_factory() as session:
        session.add(SourceSnapshot(title_id=title_id, source="zog", state={"page": None, "by": "rejected"},
                                   observed_at=naive(T0), next_check_at=None))
        session.commit()

    run(tracker.poll_due())

    assert zog.calls == []
    stored = zog_snapshot(session_factory, title_id)
    assert stored.state == {"page": None, "by": "rejected"}
    assert stored.next_check_at == naive(T0) + timedelta(days=7)
    assert card(tracker, title_id).russian.hints[-1] == "Страница на ZoG не указана — вставьте ссылку, если перевод есть"


def test_a_game_out_of_the_two_statuses_is_not_asked_and_keeps_its_snapshot(tracker, igdb, zog, clock, session_factory):
    zog.pages["stray"] = saved("stray")
    title_id = add(tracker, igdb, "Stray", year=2022)
    run(tracker.poll_due())
    run(tracker.mark_watched(title_id))

    week(tracker, clock)

    assert zog.calls == ["stray"]
    assert zog_snapshot(session_factory, title_id).state["page"] == "stray"


# --- failures and layouts --------------------------------------------------------------------------------------------


def test_a_failure_tells_the_owner_nothing_and_comes_again_in_six_hours(tracker, igdb, zog, clock, session_factory, caplog):
    zog.failure = ZogError("ZoG page stray: HTTP 503", status=503)
    title_id = add(tracker, igdb, "Stray", year=2022)

    with caplog.at_level(logging.WARNING):
        run(tracker.poll_due())

    stored = zog_snapshot(session_factory, title_id)
    assert stored.state == {}
    assert stored.next_check_at == naive(T0) + timedelta(hours=6)
    assert failure_events(session_factory) == []
    assert "ZoG check of title" in caplog.text
    zog.failure = None
    zog.pages["stray"] = saved("stray")
    clock.advance(hours=6)
    run(tracker.poll_due())
    assert zog_snapshot(session_factory, title_id).state == {"page": "stray", "by": "found", "text": False, "voice": False}


def test_a_bug_in_one_game_is_logged_with_its_traceback_and_tells_the_owner_nothing(
    tracker, igdb, zog, session_factory, caplog
):
    # review 9.1b, F3: not a failure of ZoG, so not a warning without a trace that hides the bug
    zog.failure = TypeError("a bug in reading the page")
    title_id = add(tracker, igdb, "Stray", year=2022)

    with caplog.at_level(logging.WARNING):
        run(tracker.poll_due())

    stored = zog_snapshot(session_factory, title_id)
    assert stored.state == {}
    assert stored.next_check_at == naive(T0) + timedelta(hours=6)
    assert failure_events(session_factory) == []
    bug = [record for record in caplog.records if "failed by a bug" in record.getMessage()]
    assert len(bug) == 1 and bug[0].levelno == logging.ERROR and bug[0].exc_info is not None


def test_a_failure_while_finding_keeps_the_state(tracker, igdb, zog, steam, session_factory):
    zog.failure = ZogError("timeout")
    title_id = add(tracker, igdb, "Baldur's Gate III")

    run(tracker.poll_due())

    assert zog.calls == ["baldurs_gate_iii"]  # the finding stops at the failure
    assert zog_snapshot(session_factory, title_id).state == {}


def force_due(session_factory, title_id):
    with session_factory() as session:
        stored = session.scalar(select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "zog"))
        stored.next_check_at = None
        session.commit()


def test_an_unreadable_layout_keeps_the_last_support_and_logs_once_a_day(
    tracker, igdb, steam, zog, clock, session_factory, caplog
):
    steam.support[BALDURS] = TEXT
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Baldur's Gate 3")
    run(tracker.poll_due())
    zog.pages["baldurs_gate_3"] = "<html><title>Технические работы</title></html>"

    with caplog.at_level(logging.WARNING):
        week(tracker, clock)
        force_due(session_factory, title_id)
        clock.advance(hours=1)
        run(tracker.poll_due())

    assert caplog.text.count("cannot be read") == 1
    stored = zog_snapshot(session_factory, title_id)
    assert stored.state == {"page": "baldurs_gate_3", "by": "found", "unreadable": True, "text": True, "voice": True}
    view = card(tracker, title_id).russian
    assert view.line == "текст — официально; озвучка — народная"
    assert view.hints[-1] == "Страницу на ZoG не удалось прочитать — народный перевод пока неизвестен"
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    week(tracker, clock)
    assert zog_snapshot(session_factory, title_id).state == {"page": "baldurs_gate_3", "by": "found", "text": True, "voice": True}
    assert fan_events(session_factory) == []


def test_a_page_never_read_gives_no_data_and_its_first_readable_read_is_silent(tracker, igdb, steam, zog, clock, session_factory):
    steam.support[BALDURS] = Support(False, False)
    zog.pages["stray"] = made_up_page("Stray", (), 2022) + "<table><tr><td>Переводы:</td></tr></table>"  # no entry link
    title_id = add(tracker, igdb, "Stray", year=2022)
    run(tracker.poll_due())

    assert zog_snapshot(session_factory, title_id).state == {"page": "stray", "by": "found", "unreadable": True}
    assert card(tracker, title_id).russian.line == "официально нет"  # never read: the fan part is no data
    zog.pages["stray"] = made_up_page("Stray", ("Русификатор (текст)",), 2022)
    week(tracker, clock)
    assert card(tracker, title_id).russian.line == "текст — народный"
    assert fan_events(session_factory) == []


def test_a_stored_page_turning_error_is_found_again_and_none_found_is_no_data(tracker, igdb, steam, zog, clock, session_factory):
    steam.support[BALDURS] = TEXT
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")
    title_id = add(tracker, igdb, "Baldur's Gate 3")
    run(tracker.poll_due())
    del zog.pages["baldurs_gate_3"]

    week(tracker, clock)

    assert zog.calls == ["baldurs_gate_3", "baldurs_gate_3", "baldurs_gate_iii"]  # the stored page is not asked twice
    assert zog_snapshot(session_factory, title_id).state == {"page": None, "by": "none"}
    view = card(tracker, title_id).russian
    assert view.line == "текст — официально"
    assert view.zog_link == ""
    assert fan_events(session_factory) == []


def test_a_renamed_page_is_found_under_its_new_address(tracker, igdb, zog, clock, session_factory):
    zog.pages["baldurs_gate_iii"] = made_up_page("Baldur's Gate III", ("Русификатор (звук)",), 2023)
    title_id = add(tracker, igdb, "Baldur's Gate III")
    run(tracker.poll_due())
    del zog.pages["baldurs_gate_iii"]
    zog.pages["baldurs_gate_3"] = made_up_page("Baldur's Gate 3", ("Русификатор (звук)", "Русификатор (текст)"), 2023)

    week(tracker, clock)

    assert zog_snapshot(session_factory, title_id).state == {"page": "baldurs_gate_3", "by": "found", "text": True, "voice": True}
    assert fan_events(session_factory) == []  # another page: the reference point


# --- the events ------------------------------------------------------------------------------------------------------


def test_a_later_fan_part_is_told_with_the_translation_page(tracker, igdb, steam, zog, clock, session_factory, sender):
    steam.support[BALDURS] = TEXT
    zog.pages["baldurs_gate_3"] = made_up_page("Baldur’s Gate 3", ("Українізатор (текст)",), 2023)
    title_id = add(tracker, igdb, "Baldur's Gate 3")
    run(tracker.poll_due())
    zog.pages["baldurs_gate_3"] = saved("baldurs_gate_3")

    week(tracker, clock)

    [event] = fan_events(session_factory)
    assert event.payload == {
        "text": "🎮 Для «Baldur's Gate 3» вышла народная русская озвучка", "name": "Baldur's Gate 3", "parts": "voice",
        "zog_page": "baldurs_gate_3", "pc": False,
    }  # the fan text is not told: the official has text
    assert event.dedup_key == "game:1:russian:fan:baldurs_gate_3:voice:from:20261109T120000"
    buttons = actions.event_actions(event.type, event.id, title_id, event.payload)
    assert [(button.label, button.url) for button in buttons] == [
        ("📄 Карточка", None), ("🌐 Страница перевода", "https://www.zoneofgames.ru/games/baldurs_gate_3/"),
    ]


def test_a_fan_part_the_official_has_is_not_told(tracker, igdb, steam, zog, clock, session_factory):
    steam.support[BALDURS] = BOTH
    zog.pages["baldurs_gate_3"] = made_up_page("Baldur's Gate 3", (), 2023)
    add(tracker, igdb, "Baldur's Gate 3")
    run(tracker.poll_due())
    zog.pages["baldurs_gate_3"] = made_up_page("Baldur's Gate 3", ("Русификатор (текст и звук)",), 2023)

    week(tracker, clock)

    assert fan_events(session_factory) == []


def test_text_and_voice_together_with_the_pc_mark(tracker, igdb, steam, zog, clock, session_factory):
    zog.pages["split_fiction"] = made_up_page("Split Fiction", (), 2025)
    add(tracker, igdb, "Split Fiction", year=2025, platforms=(6, 167))  # PC and PS5, both marked
    run(tracker.poll_due())
    zog.pages["split_fiction"] = saved("split_fiction")

    week(tracker, clock)

    [event] = fan_events(session_factory)
    assert event.payload["text"] == "🎮 Для «Split Fiction» вышли народный русский перевод текста и озвучка (ПК)"
    assert event.payload["parts"] == "text_voice"


def test_official_text_after_a_told_fan_text_hides_it(tracker, igdb, steam, zog, clock, session_factory):
    steam.support[BALDURS] = Support(False, False)
    zog.pages["lorelei_and_the_laser_eyes"] = made_up_page("Lorelei and the Laser Eyes", ("Українізатор (текст)",), 2024)
    title_id = add(tracker, igdb, "Lorelei and the Laser Eyes", year=2024)
    run(tracker.poll_due())
    zog.pages["lorelei_and_the_laser_eyes"] = saved("lorelei_and_the_laser_eyes")
    week(tracker, clock)
    assert [event.payload["parts"] for event in fan_events(session_factory)] == ["text"]
    assert card(tracker, title_id).russian.line == "текст — народный"

    steam.support[BALDURS] = TEXT
    clock.advance(hours=6)
    run(tracker.poll_due())

    view = card(tracker, title_id).russian
    assert view.line == "текст — официально"
    assert view.zog_link == ""


def test_the_first_check_after_return_to_the_list_is_silent(tracker, igdb, steam, zog, clock, session_factory):
    zog.pages["hades_2"] = made_up_page("Hades 2", (), 2025)
    title_id = add(tracker, igdb, "Hades 2", year=2025)
    run(tracker.poll_due())
    run(tracker.mark_dropped(title_id))
    clock.advance(days=1)
    run(tracker.restore_title(title_id))
    zog.pages["hades_2"] = saved("hades_2")

    week(tracker, clock)

    assert fan_events(session_factory) == []
    assert zog_snapshot(session_factory, title_id).state["voice"] is True


def test_dropping_a_game_withdraws_its_undelivered_fan_event(tracker, igdb, zog, clock, session_factory):
    zog.pages["hades_2"] = made_up_page("Hades 2", (), 2025)
    title_id = add(tracker, igdb, "Hades 2", year=2025)
    run(tracker.poll_due())
    zog.pages["hades_2"] = saved("hades_2")
    week(tracker, clock)
    assert len(fan_events(session_factory)) == 1  # queued, not delivered yet

    run(tracker.mark_dropped(title_id))

    assert fan_events(session_factory) == []
    assert zog_snapshot(session_factory, title_id).state["page"] == "hades_2"  # the snapshot stays


# --- the sample ------------------------------------------------------------------------------------------------------


def test_the_sample_of_a_fan_translation_is_sent_with_its_button(tracker, sender):
    assert "Игра: народный перевод" in [sample.label for sample in tracker.test_samples()]

    run(tracker.send_test_event("game-russian-fan"))

    [(text, buttons)] = [item for item in sender.sent if "народная" in item[0]]
    assert "🎮 Для «Baldur’s Gate 3» вышла народная русская озвучка" in text
    assert [(button.label, button.url) for button in buttons] == [
        ("🌐 Страница перевода", "https://www.zoneofgames.ru/games/baldurs_gate_3/"),
    ]


def test_no_zog_source_no_check_and_no_fan_part(session_factory, clock, igdb, steam):
    tracker = Tracker(session_factory, clock=clock, sender=Sender(), sources={TitleKind.GAME: igdb}, language_source=steam)
    steam.support[BALDURS] = TEXT
    title_id = add(tracker, igdb, "Baldur's Gate 3")
    run(tracker.poll_due())

    assert zog_snapshot(session_factory, title_id) is None
    assert card(tracker, title_id).russian.hints == ("Steam — проверено сегодня в 12:00",)

