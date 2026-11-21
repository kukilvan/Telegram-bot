"""The official Russian check at the end of a pass (spec 5.5, 5.9, 3.1, 3.2 of stage 9.1b, ticket 04) through the
facade on a fake clock: the reconciliation (a game in «Хочу» or «В процессе» gets a snapshot, none is dropped), the
reference points (an empty snapshot, a Steam page appearing, a changed number, the first check after «Вернуть в
список»), «not asked yet» stores nothing, «no data» keeps the previous look, events of appeared parts only and the
silence of a part that disappears; one write session for the events of a check; a failed pack, an unreadable answer of
one game, the same Steam number on two games, more than 100 games, never-checked first; an unreadable own state and a
spoiled look; the press («Прошёл», «Бросил», a press while Steam answers) and `DueTitle.statuses`; the card (web view and
the bot line) in every state that exists without ZoG.

The game source is a made-up IGDB (`MadeUpGames`), Steam's languages a fake the test writes.
"""

import logging
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.providers.steam import SteamError
from app.tracker import failures, russian_events
from app.tracker.cards import format_card
from app.tracker.checks import still_checked
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.games import GameState
from app.tracker.models import DeliveryItem, DeliveryStatus, Event, SourceSnapshot, Title, TitleKind, TitleStatus
from app.tracker.platforms import Platform
from app.tracker.pollers import game_russian
from app.tracker.pollers.base import DueTitle
from app.tracker.queue import EventQueue
from app.tracker.russian import NOT_ASKED, Support
from app.tracker.sources.steam_prices import UnreadAnswer
from test_tracker_game_prices import FakeClock, FakeSender, MadeUpGames, naive, run
from test_tracker_steam_events import T0

STRAY = "1332010"
CYBERPUNK = "1091500"
BOTH = Support(True, True)
TEXT = Support(True, False)
VOICE = Support(False, True)
NO = Support(False, False)


class FakeLanguages:
    """Steam's languages: what each number says (`support`, absent — nothing), `unread` numbers unreadable, `failure`
    — the whole request fails; `during` runs while Steam is answering."""

    def __init__(self):
        self.support = {}
        self.unread = set()
        self.failure = None
        self.during = None
        self.calls = []

    async def russian(self, appids):
        self.calls.append(list(appids))
        if self.during is not None:
            await self.during()
        if self.failure is not None:
            raise self.failure
        return {
            appid: UnreadAnswer(f"Steam app {appid}: supported_languages is no list") if appid in self.unread
            else self.support.get(appid)
            for appid in appids
        }


def game(steam_id=STRAY, platforms=(Platform.PC,), russian=None):
    numbers = {Platform.PC: 6, Platform.PS5: 167}
    return GameState(steam_id=steam_id, platforms=tuple(numbers[p] for p in platforms), russian=russian)


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
def tracker(session_factory, clock, igdb, steam):
    return Tracker(session_factory, clock=clock, sender=FakeSender(), sources={TitleKind.GAME: igdb}, language_source=steam)


def add(tracker, igdb, state=None, external_id="1", name="Stray"):
    igdb.put(external_id, state if state is not None else game(), name)
    return run(tracker.add_title(TitleKind.GAME, external_id)).title_id


def check(tracker, clock, hours=6):
    clock.advance(hours=hours)
    run(tracker.poll_due())


def igdb_says(session_factory, igdb, state, external_id="1"):
    """IGDB answers `state` from now on, and the game's own check is due in this pass."""
    igdb.by_id[external_id] = replace(igdb.by_id[external_id], game=state)
    with session_factory() as session:
        for stored in session.scalars(select(SourceSnapshot).where(SourceSnapshot.source == "igdb")):
            stored.next_check_at = None
        session.commit()


def snapshot(session_factory, title_id):
    with session_factory() as session:
        return session.scalar(
            select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "russian_official")
        )


def russian_texts(session_factory, title_id=None):
    with session_factory() as session:
        query = select(Event.payload).where(Event.type.in_(russian_events.TYPES)).order_by(Event.id)
        if title_id is not None:
            query = query.where(Event.title_id == title_id)
        return [payload["text"] for payload in session.scalars(query)]


def failure_sources(session_factory):
    with session_factory() as session:
        return [p["source"] for p in session.scalars(select(Event.payload).where(Event.type == failures.SOURCE_FAILED))]


# --- which games, the reconciliation ---------------------------------------------------------------------------------


def test_a_game_in_want_is_checked_in_the_same_pass_and_its_first_look_is_the_reference_point(tracker, igdb, steam, session_factory, clock):
    steam.support[STRAY] = TEXT
    title_id = add(tracker, igdb)

    run(tracker.poll_due())

    stored = snapshot(session_factory, title_id)
    assert stored.state == {"source": "steam", "appid": STRAY, "text": True, "voice": False}
    assert stored.observed_at == naive(T0)
    assert stored.next_check_at == naive(T0) + timedelta(hours=6)
    assert russian_texts(session_factory) == []
    assert steam.calls == [[STRAY]]


def test_in_progress_is_checked_and_other_statuses_are_not_while_the_snapshot_stays(tracker, igdb, steam, session_factory, clock):
    title_id = add(tracker, igdb)
    run(tracker.mark_started(title_id))
    run(tracker.poll_due())
    assert snapshot(session_factory, title_id) is not None

    run(tracker.mark_watched(title_id))
    steam.calls.clear()
    check(tracker, clock)
    check(tracker, clock)

    assert steam.calls == []
    assert snapshot(session_factory, title_id) is not None  # the card keeps the line


def test_a_dropped_game_added_back_keeps_one_snapshot_and_deleting_the_title_deletes_it(tracker, igdb, session_factory, clock):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    run(tracker.mark_dropped(title_id))
    run(tracker.restore_title(title_id))
    check(tracker, clock)
    with session_factory() as session:
        assert len(session.scalars(select(SourceSnapshot).where(SourceSnapshot.source == "russian_official")).all()) == 1

    run(tracker.delete_title(title_id))

    assert snapshot(session_factory, title_id) is None


def test_without_a_source_of_languages_nothing_is_checked_and_the_card_has_no_block(session_factory, clock, igdb):
    tracker = Tracker(session_factory, clock=clock, sender=FakeSender(), sources={TitleKind.GAME: igdb})
    title_id = add(tracker, igdb, game(russian=TEXT))

    run(tracker.poll_due())

    assert snapshot(session_factory, title_id) is None
    assert run(tracker.title_card(title_id)).russian is None


# --- the reference point and the events ------------------------------------------------------------------------------


def test_a_part_that_appears_later_gives_one_message_and_one_that_disappears_is_silent(tracker, igdb, steam, session_factory, clock):
    steam.support[STRAY] = TEXT
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    steam.support[STRAY] = BOTH
    check(tracker, clock)
    check(tracker, clock)
    steam.support[STRAY] = TEXT
    check(tracker, clock)

    assert russian_texts(session_factory, title_id) == ["🎮 В «Stray» появилась русская озвучка"]
    with session_factory() as session:
        event = session.scalar(select(Event).where(Event.type == russian_events.OFFICIAL))
    assert event.payload == {
        "text": "🎮 В «Stray» появилась русская озвучка", "name": "Stray", "parts": "voice", "source": "steam",
        "steam_id": STRAY, "pc": False,
    }
    assert event.dedup_key == f"game:{title_id}:russian:official:voice:from:20261109T120000"


def test_an_announced_game_whose_languages_steam_lists_for_the_first_time_is_told(tracker, igdb, steam, session_factory, clock):
    title_id = add(tracker, igdb, game(russian=None))
    run(tracker.poll_due())
    assert snapshot(session_factory, title_id).state == {"source": None, "appid": STRAY}

    steam.support[STRAY] = TEXT
    check(tracker, clock)

    assert russian_texts(session_factory, title_id) == ["🎮 В «Stray» появился русский текст"]


def test_not_asked_yet_stores_nothing_until_igdb_answers_and_then_it_is_the_reference_point(
    tracker, igdb, steam, session_factory, clock
):
    title_id = add(tracker, igdb, game(steam_id=None, russian=NOT_ASKED))
    run(tracker.poll_due())
    stored = snapshot(session_factory, title_id)
    assert stored.state == {}
    assert stored.next_check_at == naive(T0) + timedelta(hours=6)

    igdb_says(session_factory, igdb, game(steam_id=None, russian=BOTH))
    check(tracker, clock)

    assert snapshot(session_factory, title_id).state == {"source": "igdb", "appid": None, "text": True, "voice": True}
    assert russian_texts(session_factory) == []
    assert steam.calls == []  # no Steam page: IGDB only, no request


def test_no_data_keeps_the_previous_look_and_says_nothing(tracker, igdb, steam, session_factory, clock):
    steam.support[STRAY] = BOTH
    title_id = add(tracker, igdb, game(russian=TEXT))
    run(tracker.poll_due())

    del steam.support[STRAY]
    check(tracker, clock)
    stored = snapshot(session_factory, title_id)

    assert stored.state == {"source": "steam", "appid": STRAY, "text": True, "voice": True}
    assert stored.observed_at == naive(T0) + timedelta(hours=6)  # the moment of the last check
    assert russian_texts(session_factory) == []


def test_a_steam_page_that_appears_is_a_silent_reference_point(tracker, igdb, steam, session_factory, clock):
    title_id = add(tracker, igdb, game(steam_id=None, russian=TEXT))
    run(tracker.poll_due())

    steam.support[STRAY] = BOTH
    igdb_says(session_factory, igdb, game(russian=TEXT))
    check(tracker, clock)

    assert snapshot(session_factory, title_id).state == {"source": "steam", "appid": STRAY, "text": True, "voice": True}
    assert russian_texts(session_factory) == []


def test_another_steam_number_is_a_silent_reference_point(tracker, igdb, steam, session_factory, clock):
    steam.support[STRAY] = TEXT
    steam.support[CYBERPUNK] = BOTH
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    igdb_says(session_factory, igdb, game(steam_id=CYBERPUNK))
    check(tracker, clock)

    assert snapshot(session_factory, title_id).state["appid"] == CYBERPUNK
    assert russian_texts(session_factory) == []


def test_the_first_check_after_return_is_the_reference_point(tracker, igdb, steam, session_factory, clock):
    steam.support[STRAY] = TEXT
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    run(tracker.mark_dropped(title_id))
    clock.advance(hours=7)
    run(tracker.restore_title(title_id))

    steam.support[STRAY] = BOTH
    check(tracker, clock, hours=1)
    steam.support[STRAY] = Support(True, True)
    check(tracker, clock)

    assert snapshot(session_factory, title_id).state["voice"] is True
    assert russian_texts(session_factory) == []


def test_the_pc_mark_ends_the_message_when_the_owner_plays_elsewhere_too(tracker, igdb, steam, session_factory, clock):
    steam.support[STRAY] = NO
    title_id = add(tracker, igdb, game(platforms=(Platform.PC, Platform.PS5)))
    run(tracker.poll_due())

    steam.support[STRAY] = TEXT
    check(tracker, clock)

    assert russian_texts(session_factory, title_id) == ["🎮 В «Stray» появился русский текст (ПК)"]


def test_the_events_of_all_the_games_of_a_check_go_in_one_write_session(tracker, igdb, steam, session_factory, clock, monkeypatch):
    steam.support.update({STRAY: NO, CYBERPUNK: NO})
    add(tracker, igdb)
    add(tracker, igdb, game(steam_id=CYBERPUNK), external_id="2", name="Cyberpunk 2077")
    run(tracker.poll_due())
    batches = []
    real = EventQueue.enqueue_all

    def counted(session, batch, now):
        batches.append(len(batch))
        return real(session, batch, now)

    monkeypatch.setattr(EventQueue, "enqueue_all", staticmethod(counted))
    steam.support.update({STRAY: TEXT, CYBERPUNK: BOTH})
    check(tracker, clock)

    assert batches == [2]
    assert russian_texts(session_factory) == [
        "🎮 В «Stray» появился русский текст", "🎮 В «Cyberpunk 2077» появились русский текст и озвучка",
    ]


def test_a_failed_store_finds_the_same_fact_again_and_its_key_drops_it(tracker, igdb, steam, session_factory, clock, monkeypatch):
    steam.support[STRAY] = NO
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    steam.support[STRAY] = TEXT
    monkeypatch.setattr(game_russian.GameRussian, "_store", lambda self, item, now: 1 / 0)
    check(tracker, clock)
    monkeypatch.undo()

    check(tracker, clock, hours=1)  # 30 minutes after the failed store

    assert russian_texts(session_factory, title_id) == ["🎮 В «Stray» появился русский текст"]
    assert snapshot(session_factory, title_id).state["text"] is True


# --- failures and packs -----------------------------------------------------------------------------------------------


def test_a_failed_request_is_a_failure_of_every_game_of_the_pack_told_as_steam(tracker, igdb, steam, session_factory, clock):
    steam.failure = SteamError("Steam GetItems failed (HTTP 503)", 503)
    first = add(tracker, igdb)
    second = add(tracker, igdb, game(steam_id=CYBERPUNK), external_id="2", name="Cyberpunk 2077")
    without_steam = add(tracker, igdb, game(steam_id=None, russian=TEXT), external_id="3", name="Bloodborne")

    run(tracker.poll_due())

    for title_id in (first, second):
        assert snapshot(session_factory, title_id).next_check_at == naive(T0) + timedelta(minutes=30)
        assert snapshot(session_factory, title_id).state == {}
    assert snapshot(session_factory, without_steam).state["source"] == "igdb"
    assert failure_sources(session_factory) == ["Steam", "Steam"]
    assert failures.source_name("russian_official") == "Steam"


def test_an_unreadable_answer_is_a_failure_of_its_game_only(tracker, igdb, steam, session_factory, caplog):
    steam.unread.add(STRAY)
    steam.support[CYBERPUNK] = BOTH
    first = add(tracker, igdb)
    second = add(tracker, igdb, game(steam_id=CYBERPUNK), external_id="2", name="Cyberpunk 2077")

    with caplog.at_level(logging.WARNING):
        run(tracker.poll_due())

    assert snapshot(session_factory, first).state == {}
    assert snapshot(session_factory, second).state["source"] == "steam"
    assert failure_sources(session_factory) == ["Steam"]
    assert any("supported_languages is no list" in record.getMessage() for record in caplog.records)


def test_one_steam_number_of_two_games_is_asked_once_and_serves_both(tracker, igdb, steam, session_factory):
    steam.support[STRAY] = TEXT
    first = add(tracker, igdb)
    second = add(tracker, igdb, external_id="2", name="Stray (другая запись)")

    run(tracker.poll_due())

    assert steam.calls == [[STRAY]]
    assert snapshot(session_factory, first).state == snapshot(session_factory, second).state


def test_230_games_are_asked_in_packs_of_100(tracker, igdb, steam, session_factory):
    for number in range(230):
        add(tracker, igdb, game(steam_id=str(1000 + number)), external_id=str(number + 1), name=f"Игра {number}")

    run(tracker.poll_due())

    assert [len(call) for call in steam.calls] == [100, 100, 30]


def test_a_never_checked_game_goes_first(tracker, igdb, steam, session_factory, clock):
    add(tracker, igdb)
    run(tracker.poll_due())
    clock.advance(hours=6)
    add(tracker, igdb, game(steam_id=CYBERPUNK), external_id="2", name="Cyberpunk 2077")
    steam.calls.clear()

    run(tracker.poll_due())

    assert steam.calls == [[CYBERPUNK, STRAY]]


def test_an_unreadable_own_state_skips_the_game_with_one_log_line_a_day(tracker, igdb, steam, session_factory, clock, caplog):
    title_id = add(tracker, igdb)
    with session_factory() as session:
        own = session.scalar(select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "igdb"))
        own.state = {**own.state, "russian": "garbage"}
        own.next_check_at = naive(T0) + timedelta(days=30)
        session.commit()

    with caplog.at_level(logging.WARNING):
        run(tracker.poll_due())
        clock.advance(minutes=1)
        run(tracker.poll_due())

    lines = [r for r in caplog.records if "its own snapshot cannot be read, Russian not checked" in r.getMessage()]
    assert len(lines) == 1
    assert steam.calls == [] and failure_sources(session_factory) == []
    assert snapshot(session_factory, title_id).state == {}


def test_a_spoiled_look_is_a_failure_of_its_game(tracker, igdb, steam, session_factory, clock):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    with session_factory() as session:
        stored = session.scalar(select(SourceSnapshot).where(SourceSnapshot.source == "russian_official"))
        stored.state = {"source": "zog"}
        stored.next_check_at = None
        session.commit()

    run(tracker.poll_due())

    assert failure_sources(session_factory) == ["Steam"]
    assert snapshot(session_factory, title_id).next_check_at == naive(T0) + timedelta(minutes=30)
    assert run(tracker.title_card(title_id)).russian is None  # no block; the check reports it


# --- the press and `statuses` -----------------------------------------------------------------------------------------


def queued_types(session_factory, title_id):
    with session_factory() as session:
        return sorted(session.scalars(
            select(Event.type).join(DeliveryItem, DeliveryItem.event_id == Event.id).where(
                Event.title_id == title_id, DeliveryItem.status == DeliveryStatus.PENDING
            )
        ))


@pytest.mark.parametrize("how", ["completed", "dropped"])
def test_leaving_want_and_in_progress_withdraws_the_undelivered_russian_events_and_keeps_the_snapshot(
    how, tracker, igdb, session_factory
):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    run(tracker.record_event(russian_events.OFFICIAL, {"text": "русский"}, "game:1:russian:official:text", title_id=title_id))
    run(tracker.record_event("game_release", {"text": "вышла"}, "game:1:released", title_id=title_id))

    run(tracker.mark_watched(title_id) if how == "completed" else tracker.mark_dropped(title_id))

    assert russian_events.OFFICIAL not in queued_types(session_factory, title_id)
    assert snapshot(session_factory, title_id) is not None
    with session_factory() as session:  # the key is free again (KI-54)
        assert session.scalar(select(Event).where(Event.dedup_key == "game:1:russian:official:text")) is None


def test_starting_the_game_and_the_pc_mark_keep_the_russian_events(tracker, igdb, session_factory):
    title_id = add(tracker, igdb, game(platforms=(Platform.PC, Platform.PS5)))
    run(tracker.record_event(russian_events.OFFICIAL, {"text": "русский"}, "game:1:russian:official:text", title_id=title_id))

    run(tracker.mark_started(title_id))
    run(tracker.set_platform_playing(title_id, "pc", False))

    assert queued_types(session_factory, title_id) == [russian_events.OFFICIAL]


def test_a_game_completed_while_steam_answers_queues_nothing(tracker, igdb, steam, session_factory, clock):
    steam.support[STRAY] = NO
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    steam.support[STRAY] = TEXT

    async def completed_meanwhile():
        await tracker.mark_watched(title_id)

    steam.during = completed_meanwhile
    check(tracker, clock)

    assert russian_texts(session_factory) == []
    assert failure_sources(session_factory) == []


def test_still_checked_with_statuses_requires_one_of_them(tracker, igdb, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    due = DueTitle(title_id, TitleKind.GAME, "Stray", "1", "russian_official", sequels=False,
                   statuses=(TitleStatus.WANT, TitleStatus.IN_PROGRESS))

    with session_factory() as session:
        assert still_checked(session, due)
        session.get(Title, title_id).status = TitleStatus.COMPLETED
        assert not still_checked(session, due)
        assert still_checked(session, replace(due, statuses=None))  # without them the snapshot is enough


# --- the card (spec 5.3, 5.4) ----------------------------------------------------------------------------------------


def card(tracker, title_id):
    return run(tracker.title_card(title_id))


def test_before_the_first_check_the_line_reads_by_igdb(tracker, igdb):
    title_id = add(tracker, igdb, game(russian=TEXT))

    view = card(tracker, title_id).russian

    assert view.line == "текст — официально"
    assert view.hints == ("Ещё не проверяли — строка появится через минуту-другую",)
    assert view.form is False


def test_after_a_check_the_line_and_the_moment_of_its_source(tracker, igdb, steam, clock):
    steam.support[CYBERPUNK] = BOTH
    title_id = add(tracker, igdb, game(steam_id=CYBERPUNK), name="Cyberpunk 2077")
    run(tracker.poll_due())

    view = card(tracker, title_id).russian

    assert view.line == "текст и озвучка — официально"
    assert view.hints == ("Steam — проверено сегодня в 12:00",)
    clock.advance(days=1)
    assert card(tracker, title_id).russian.hints == ("Steam — проверено вчера в 12:00",)


def test_igdb_as_the_source_and_bloodborne_without_a_steam_page(tracker, igdb):
    title_id = add(tracker, igdb, game(steam_id=None, platforms=(Platform.PS5,), russian=TEXT), name="Bloodborne")
    run(tracker.poll_due())

    view = card(tracker, title_id).russian

    assert (view.line, view.hints) == ("текст — официально", ("IGDB — проверено сегодня в 12:00",))


def test_official_no_and_the_pc_mark_with_its_hint(tracker, igdb, steam):
    steam.support[STRAY] = NO
    title_id = add(tracker, igdb, game(platforms=(Platform.PC, Platform.PS5)))
    run(tracker.poll_due())

    view = card(tracker, title_id).russian

    assert view.line == "официально нет (ПК)"
    assert view.hints == (
        "Steam — проверено сегодня в 12:00", "(ПК) — данные о версии для ПК, а вы играете ещё и на другой платформе",
    )


@pytest.mark.parametrize(
    "steam_id, hint",
    [
        (STRAY, "Языки ещё не объявлены. Проверяю: Steam — каждые 6 часов, ZoG — раз в неделю"),
        (None, "Языки ещё не объявлены. Проверяю: IGDB — вместе с датами игры, ZoG — раз в неделю"),
    ],
)
def test_no_data_after_a_check_with_and_without_a_steam_page(steam_id, hint, tracker, igdb):
    title_id = add(tracker, igdb, game(steam_id=steam_id, platforms=(Platform.PC, Platform.PS5), russian=None))
    run(tracker.poll_due())

    view = card(tracker, title_id).russian

    assert view.line == "нет данных"  # never «(ПК)» after it
    source = "Steam" if steam_id else "IGDB"
    assert view.hints == (f"{source} — проверено сегодня в 12:00", hint)


def test_another_status_shows_the_last_line_with_its_hint_and_nothing_without_data(tracker, igdb, steam):
    steam.support[STRAY] = TEXT
    with_data = add(tracker, igdb)
    without = add(tracker, igdb, game(steam_id=None, russian=None), external_id="2", name="Без данных")
    run(tracker.poll_due())
    run(tracker.mark_watched(with_data))
    run(tracker.mark_watched(without))

    view = card(tracker, with_data).russian

    assert view.line == "текст — официально"
    assert view.hints[-1] == "Игра не в «Хочу» и не «В процессе» — русский язык больше не проверяется"
    assert card(tracker, without).russian is None


def test_the_bot_card_has_the_same_line_after_the_platforms_and_before_the_stores(tracker, igdb, steam):
    steam.support[STRAY] = TEXT
    title_id = add(tracker, igdb)
    run(tracker.poll_due())

    lines = format_card(card(tracker, title_id)).splitlines()

    position = lines.index("Русский: текст — официально")
    store = next(number for number, line in enumerate(lines) if line.startswith("Steam: "))
    assert position < store
    assert lines[position - 1].startswith("ПК")


def test_the_samples_of_the_test_event_include_the_russian_one(tracker):
    labels = [sample.label for sample in tracker.test_samples()]

    assert "Игра: появился русский язык" in labels
