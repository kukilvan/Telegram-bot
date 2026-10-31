"""A game in the core (spec 6 and 7 of part 6.1): adding with its platforms, the marks «играю здесь», the statuses of a
game, the polls and their messages, folded by platforms, and the samples of «Тестовое событие».

Driven through the facade: fake clock, fake sender, in-memory SQLite. Adding goes through the real IGDB adapter on the
saved answers of IGDB and Steam (no network); the polls take made-up snapshots, whose dates the test moves.
"""

import asyncio
import json
import pathlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.tracker import game_events, games
from app.tracker.core import (
    CannotScore, SourceNotConfigured, Tracker, UnknownPlatform, UnknownTitle,
)
from app.tracker.games import GameDate, GameState, Release
from app.tracker.models import (
    DeliveryItem, DeliveryStatus, GamePlatformRecord, SettingRecord, SourceSnapshot, Title, TitleKind, TitleStatus,
)
from app.tracker.platforms import WORLD
from app.tracker.settings_store import MY_PLATFORMS_SETTING
from app.tracker.sources.igdb_games import GameSnapshot, IgdbGameSource, parse_state
from app.tracker.db import create_session_factory

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
T0 = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
PC, PS4, PS5, SWITCH = 6, 48, 167, 130
HADES, POP_REMAKE, WITCHER = "228525", "138383", "1942"
FILES = {HADES: "hades-2", POP_REMAKE: "pop-remake", WITCHER: "witcher-3"}


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def run(coro):
    return asyncio.run(coro)


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


class FakeSender:
    def __init__(self):
        self.sent = []  # (message, [(action name, arg)])

    async def send(self, message, actions=()):
        self.sent.append((message, [(a.name, a.arg) for a in actions]))

    @property
    def texts(self):
        return [message for message, _ in self.sent]


class FakeIgdb:
    """Serves the saved answers of IGDB by the number in the query."""

    def __init__(self, enabled=True):
        self.enabled = enabled

    async def games(self, body, *, at_once=False):
        if body.startswith("search"):
            return load("igdb/search-the-witcher-3-filtered.json")
        number = body.rsplit("=", 1)[1].strip(" ;")
        return load(f"igdb/game-{FILES[number]}.json") if number in FILES else []


class FakeSteam:
    def __init__(self, failing=False):
        self.failing = failing

    async def app_details(self, appid):
        if self.failing:
            return None
        return load(f"steam/appdetails_{appid}.json")[str(appid)].get("data")


class MadeUpGames:
    """A game source whose snapshots the test writes: adding and polling read the same ones."""

    source_key = "igdb"

    def __init__(self):
        self.by_id = {}

    def put(self, external_id, game, name="Elden Ring"):
        self.by_id[external_id] = GameSnapshot(external_id, name, name, 2026, game=game)

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return self.by_id.get(external_id)

    async def snapshot_to_add(self, external_id):
        return self.by_id.get(external_id)


def state(*releases):
    """Releases of the world region as (IGDB platform, kind, date text)."""
    records = tuple(Release(platform=p, region=WORLD, type=k, date=GameDate.parse(d)) for p, k, d in releases)
    return GameState(platforms=tuple(sorted({r.platform for r in records})), releases=records)


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def made_up():
    return MadeUpGames()


@pytest.fixture
def tracker(session_factory, clock, sender, made_up):
    return Tracker(session_factory, clock=clock, sender=sender, sources={TitleKind.GAME: made_up})


def igdb_tracker(session_factory, clock, sender, igdb=None, steam=None):
    source = IgdbGameSource(igdb or FakeIgdb(), steam or FakeSteam())
    return Tracker(session_factory, clock=clock, sender=sender, sources={TitleKind.GAME: source})


def rows(session_factory, title_id):
    with session_factory() as session:
        return {
            r.platform: r.playing
            for r in session.scalars(select(GamePlatformRecord).where(GamePlatformRecord.title_id == title_id))
        }


def title(session_factory, title_id):
    with session_factory() as session:
        return session.get(Title, title_id)


def set_my_platforms(session_factory, *values):
    with session_factory() as session:
        session.merge(SettingRecord(key=MY_PLATFORMS_SETTING, value=list(values)))
        session.commit()


def add(tracker, made_up, game, external_id="1", name="Elden Ring"):
    made_up.put(external_id, game, name)
    return run(tracker.add_title(TitleKind.GAME, external_id)).title_id


def poll(tracker, session_factory, made_up, game, external_id="1", deliver=True):
    """IGDB answers `game` now; every check is due, the poll runs and what it queued goes out."""
    snapshot = made_up.by_id[external_id]
    made_up.by_id[external_id] = replace(snapshot, game=game)
    with session_factory() as session:
        for stored in session.scalars(select(SourceSnapshot)):
            stored.next_check_at = None
        session.commit()
    report = run(tracker.poll_due())
    if deliver:
        run(tracker.deliver_pending())
    return report


# --- adding (6.3) ----------------------------------------------------------------------------------------------------


def test_a_game_is_added_as_wanted_with_a_row_for_every_platform_marked_where_it_is_mine(session_factory, clock, sender):
    tracker = igdb_tracker(session_factory, clock, sender)

    result = run(tracker.add_title(TitleKind.GAME, HADES))

    added = title(session_factory, result.title_id)
    assert result.created and added.kind == TitleKind.GAME and added.status == TitleStatus.WANT and added.tracking_enabled
    assert added.name == "Hades II" and added.original_name == "Hades II"
    assert added.overview and any("а" <= letter <= "я" for letter in added.overview.lower())  # Steam's Russian text
    assert rows(session_factory, result.title_id) == {
        "pc": True, "ps5": True, "xbox_series": False, "switch_2": False, "switch": False,
    }


def test_the_dates_are_stored_in_the_snapshot_and_come_back_from_it(session_factory, clock, sender):
    # BUG-15: the dates of a game are kept and read back
    tracker = igdb_tracker(session_factory, clock, sender)

    title_id = run(tracker.add_title(TitleKind.GAME, HADES)).title_id

    with session_factory() as session:
        stored = session.scalars(select(SourceSnapshot).where(SourceSnapshot.title_id == title_id)).one()
        assert stored.source == "igdb"
        assert stored.state == parse_state(load("igdb/game-hades-2.json")[0]).state()
        game = GameState.from_state(stored.state)
        assert stored.next_check_at == T0.replace(tzinfo=None) + games.check_interval(game, "il", T0.date())
    pc = games.platform_dates(game, games.Platform.PC, "il")
    assert pc.full.date.text == "2025-09-25" and pc.early.date.text == "2024-05-06"


def test_a_game_already_in_the_list_opens_the_same_title(session_factory, clock, sender):
    tracker = igdb_tracker(session_factory, clock, sender)
    first = run(tracker.add_title(TitleKind.GAME, HADES))

    again = run(tracker.add_title(TitleKind.GAME, HADES))

    assert again.title_id == first.title_id and not again.created


def test_without_steam_the_game_has_the_name_and_description_of_igdb(session_factory, clock, sender):
    tracker = igdb_tracker(session_factory, clock, sender, steam=FakeSteam(failing=True))

    added = title(session_factory, run(tracker.add_title(TitleKind.GAME, WITCHER)).title_id)

    raw = load("igdb/game-witcher-3.json")[0]
    assert added.name == "Ведьмак 3: Дикая охота"  # the Russian name of IGDB
    assert added.overview == raw["summary"]


def test_a_cancelled_platform_gets_its_row_too(session_factory, clock, sender):
    tracker = igdb_tracker(session_factory, clock, sender)

    title_id = run(tracker.add_title(TitleKind.GAME, POP_REMAKE)).title_id

    assert rows(session_factory, title_id) == {"pc": True, "ps5": True, "xbox_series": False}


def test_the_marks_follow_my_platforms_at_the_moment_of_adding(tracker, session_factory, made_up):
    set_my_platforms(session_factory, "switch")

    title_id = add(tracker, made_up, state((PC, "full", "2027"), (SWITCH, "full", "2027")))

    # Switch 2 runs the games of Switch: the game is on it too
    assert rows(session_factory, title_id) == {"pc": False, "switch_2": False, "switch": True}


def test_without_the_keys_of_igdb_nothing_is_asked(session_factory, clock, sender):
    tracker = igdb_tracker(session_factory, clock, sender, igdb=FakeIgdb(enabled=False))

    with pytest.raises(SourceNotConfigured):
        run(tracker.add_title(TitleKind.GAME, HADES))
    with pytest.raises(SourceNotConfigured):
        run(tracker.search(TitleKind.GAME, "hades"))


def test_the_search_marks_a_game_already_in_the_list(session_factory, clock, sender):
    tracker = igdb_tracker(session_factory, clock, sender)
    title_id = run(tracker.add_title(TitleKind.GAME, WITCHER)).title_id

    [suggestion] = run(tracker.search(TitleKind.GAME, "the witcher 3"))

    assert suggestion.kind == TitleKind.GAME and suggestion.title_id == title_id


# --- the statuses of a game (6.5) ------------------------------------------------------------------------------------


def test_started_moves_a_wanted_game_on_and_keeps_following_it(tracker, session_factory, made_up, clock):
    title_id = add(tracker, made_up, state((PC, "full", "2027")))
    clock.advance(hours=1)

    assert run(tracker.mark_started(title_id)).changed is True
    assert run(tracker.mark_started(title_id)).changed is False

    started = title(session_factory, title_id)
    assert started.status == TitleStatus.IN_PROGRESS and started.tracking_enabled
    assert started.status_changed_at == clock.now.replace(tzinfo=None)


@pytest.mark.parametrize("before", ["completed", "dropped"])
def test_started_changes_nothing_out_of_wanted(tracker, session_factory, made_up, before):
    title_id = add(tracker, made_up, state((PC, "full", "2027")))
    run(tracker.mark_watched(title_id) if before == "completed" else tracker.mark_dropped(title_id))

    assert run(tracker.mark_started(title_id)).changed is False
    assert title(session_factory, title_id).status == TitleStatus(before)


def test_started_changes_nothing_of_a_kind_without_the_button(session_factory, clock, sender):
    from tests.test_tracker_movie_events import FakeMovieSource, movie

    movies = FakeMovieSource(movie("7"))
    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={TitleKind.MOVIE: movies})
    title_id = run(tracker.add_title(TitleKind.MOVIE, "7")).title_id

    assert run(tracker.mark_started(title_id)).changed is False
    assert title(session_factory, title_id).status == TitleStatus.WANT
    assert run(tracker.mark_watched(title_id)).changed is True
    assert title(session_factory, title_id).status == TitleStatus.WATCHED  # «Посмотрел» of a film as before


@pytest.mark.parametrize("started", [False, True], ids=["from-wanted", "from-in-progress"])
def test_completed_puts_the_game_in_the_archive_without_a_sequel_check(tracker, session_factory, made_up, started):
    title_id = add(tracker, made_up, state((PC, "full", "2027")))
    if started:
        run(tracker.mark_started(title_id))

    assert run(tracker.mark_watched(title_id)).changed is True
    assert run(tracker.mark_watched(title_id)).changed is False

    done = title(session_factory, title_id)
    assert done.status == TitleStatus.COMPLETED and not done.tracking_enabled
    with session_factory() as session:
        assert session.scalars(select(SourceSnapshot.source).where(SourceSnapshot.title_id == title_id)).all() == ["igdb"]


def test_a_game_is_scored_only_in_the_archive(tracker, made_up):
    title_id = add(tracker, made_up, state((PC, "full", "2027")))

    with pytest.raises(CannotScore):
        run(tracker.set_title_score(title_id, 24))
    run(tracker.mark_watched(title_id))

    assert run(tracker.set_title_score(title_id, 24)).changed is True


def test_dropped_takes_the_messages_of_the_game_out_of_the_queue(tracker, session_factory, made_up):
    title_id = add(tracker, made_up, state((PC, "full", "2026-11-11")))
    poll(tracker, session_factory, made_up, state((PC, "full", "2026-11-09")), deliver=False)

    run(tracker.mark_dropped(title_id))

    with session_factory() as session:
        assert session.scalars(select(DeliveryItem).where(DeliveryItem.status == DeliveryStatus.PENDING)).all() == []


@pytest.mark.parametrize("final", ["completed", "dropped"])
def test_back_to_the_list_is_wanted_checked_at_once_and_the_first_check_is_the_baseline(
    tracker, session_factory, made_up, sender, clock, final
):
    title_id = add(tracker, made_up, state((PC, "full", "2026-11-20")))
    run(tracker.mark_watched(title_id) if final == "completed" else tracker.mark_dropped(title_id))
    clock.advance(days=1)

    assert run(tracker.restore_title(title_id)).changed is True

    back = title(session_factory, title_id)
    assert back.status == TitleStatus.WANT and back.tracking_enabled
    with session_factory() as session:
        assert session.scalars(select(SourceSnapshot.next_check_at)).one() == clock.now.replace(tzinfo=None)
    made_up.by_id["1"] = replace(made_up.by_id["1"], game=state((PC, "full", "2026-11-10")))
    run(tracker.poll_due())
    run(tracker.deliver_pending())
    assert sender.sent == []  # the release while it was in the archive is the baseline


# --- «играю здесь» (6.4) ---------------------------------------------------------------------------------------------


def test_the_mark_is_set_taken_off_and_the_same_twice_changes_nothing(tracker, session_factory, made_up):
    title_id = add(tracker, made_up, state((PC, "full", "2027"), (PS5, "full", "2027")))

    assert run(tracker.set_platform_playing(title_id, "ps5", False)).changed is True
    assert run(tracker.set_platform_playing(title_id, "ps5", False)).changed is False
    assert rows(session_factory, title_id)["ps5"] is False
    assert run(tracker.set_platform_playing(title_id, "ps5", True)).changed is True
    assert rows(session_factory, title_id)["ps5"] is True
    assert title(session_factory, title_id).status == TitleStatus.WANT  # the marks do not move the status


@pytest.mark.parametrize("platform", ["switch", "ps4", "abc"])
def test_a_platform_the_game_is_not_on_is_unknown(tracker, made_up, platform):
    title_id = add(tracker, made_up, state((PC, "full", "2027")))

    with pytest.raises(UnknownPlatform):
        run(tracker.set_platform_playing(title_id, platform, True))


def test_a_title_that_is_no_game_has_no_platforms(session_factory, clock, sender):
    from tests.test_tracker_movie_events import FakeMovieSource, movie

    tracker = Tracker(session_factory, clock=clock, sender=sender, sources={TitleKind.MOVIE: FakeMovieSource(movie("7"))})
    title_id = run(tracker.add_title(TitleKind.MOVIE, "7")).title_id

    with pytest.raises(UnknownPlatform):
        run(tracker.set_platform_playing(title_id, "pc", True))
    with pytest.raises(UnknownTitle):
        run(tracker.set_platform_playing(999, "pc", True))


# --- the polls and their messages (7) -------------------------------------------------------------------------------


def test_a_release_on_two_platforms_is_one_message_with_the_card_of_the_game(tracker, session_factory, made_up, sender):
    title_id = add(tracker, made_up, state((PC, "full", "2026-11-12"), (PS5, "full", "2026-11-12")))

    report = poll(tracker, session_factory, made_up, state((PC, "full", "2026-11-09"), (PS5, "full", "2026-11-09")))

    assert report.events == 2
    assert sender.sent == [("🎮 Elden Ring вышла на ПК и PS5", [("card", title_id)])]


def test_a_game_has_no_watched_button_under_its_message(tracker, session_factory, made_up, sender):
    add(tracker, made_up, state((PS5, "full", "2027")))

    poll(tracker, session_factory, made_up, state((PS5, "full", "2027-03-12")))

    [(text, actions)] = sender.sent
    assert text == "🎮 Elden Ring: на PS5 объявлена дата — 12 марта 2027" and [name for name, _ in actions] == ["card"]


def test_releases_on_two_days_are_two_messages_and_one_summary_folds_them(tracker, session_factory, made_up, sender, clock):
    add(tracker, made_up, state((PC, "full", "2026-11-12"), (PS5, "full", "2026-11-14")))
    poll(tracker, session_factory, made_up, state((PC, "full", "2026-11-09"), (PS5, "full", "2026-11-14")))
    clock.advance(days=2)
    poll(tracker, session_factory, made_up, state((PC, "full", "2026-11-09"), (PS5, "full", "2026-11-11")))

    assert sender.texts == ["🎮 Elden Ring вышла на ПК", "🎮 Elden Ring вышла на PS5"]


def test_a_summary_folds_the_platforms_and_keeps_one_card_button(tracker, session_factory, made_up, sender):
    title_id = add(tracker, made_up, state((PC, "full", "2026-11-12"), (PS5, "full", "2026-11-12")))
    poll(tracker, session_factory, made_up, state((PC, "full", "2026-11-09"), (PS5, "full", "2026-11-09")), deliver=False)

    run(tracker.summary_now())

    [(text, actions)] = sender.sent
    assert text.splitlines()[1:] == ["🎮 Elden Ring вышла на ПК и PS5"]
    assert actions == [("card", title_id)]


def test_the_feed_folds_the_platforms_of_a_game_in_recent(tracker, session_factory, made_up):
    add(tracker, made_up, state((PC, "full", "2026-11-12"), (PS5, "full", "2026-11-12")))
    poll(tracker, session_factory, made_up, state((PC, "full", "2026-11-09"), (PS5, "full", "2026-11-09")))

    [day] = run(tracker.feed()).recent

    assert [row.headline for row in day.rows] == ["🎮 Elden Ring вышла на ПК и PS5"]


def test_an_unmarked_platform_and_one_not_mine_give_nothing(tracker, session_factory, made_up, sender):
    title_id = add(tracker, made_up, state((PC, "full", "2026-11-12"), (PS5, "full", "2026-11-12"), (SWITCH, "full", "2026-11-12")))
    run(tracker.set_platform_playing(title_id, "ps5", False))

    poll(tracker, session_factory, made_up, state((PC, "full", "2026-11-09"), (PS5, "full", "2026-11-09"), (SWITCH, "full", "2026-11-09")))

    assert sender.texts == ["🎮 Elden Ring вышла на ПК"]


def test_a_release_while_the_mark_was_off_does_not_come_when_it_is_back(tracker, session_factory, made_up, sender):
    title_id = add(tracker, made_up, state((PS5, "full", "2026-11-12")))
    run(tracker.set_platform_playing(title_id, "ps5", False))
    poll(tracker, session_factory, made_up, state((PS5, "full", "2026-11-09")))
    run(tracker.set_platform_playing(title_id, "ps5", True))

    poll(tracker, session_factory, made_up, state((PS5, "full", "2026-11-09")))

    assert sender.sent == []


def test_a_new_platform_of_mine_gets_its_row_marked_and_its_event(tracker, session_factory, made_up, sender):
    title_id = add(tracker, made_up, state((PC, "full", "2025-05-01")))
    assert rows(session_factory, title_id) == {"pc": True}

    poll(tracker, session_factory, made_up, state((PC, "full", "2025-05-01"), (PS5, "full", "2027-03-12"), (SWITCH, "full", "2027")))

    assert rows(session_factory, title_id) == {"pc": True, "ps5": True, "switch_2": False, "switch": False}
    assert sender.texts == ["🎮 Elden Ring: на PS5 объявлена дата — 12 марта 2027"]


def test_an_announcement_taken_back_and_made_again_comes_each_time(tracker, session_factory, made_up, sender, clock):
    add(tracker, made_up, state((PS5, "full", "2027")))
    poll(tracker, session_factory, made_up, state((PS5, "full", "2027-03-12")))
    clock.advance(hours=1)
    poll(tracker, session_factory, made_up, state((PS5, "full", None)))
    clock.advance(hours=1)
    poll(tracker, session_factory, made_up, state((PS5, "full", "2027-03-12")))
    clock.advance(hours=1)
    poll(tracker, session_factory, made_up, state((PS5, "full", "2027-03-12")))

    assert sender.texts == [
        "🎮 Elden Ring: на PS5 объявлена дата — 12 марта 2027",
        "🎮 Elden Ring: на PS5 дата перенесена — 12 марта 2027 → дата не объявлена",
        "🎮 Elden Ring: на PS5 объявлена дата — 12 марта 2027",
    ]


def test_a_date_igdb_stopped_sending_is_kept(tracker, session_factory, made_up, sender):
    title_id = add(tracker, made_up, state((PS5, "full", "2027-03-12")))

    poll(tracker, session_factory, made_up, GameState())

    assert sender.sent == []
    with session_factory() as session:
        kept = GameState.from_state(session.scalars(select(SourceSnapshot.state)).one())
    assert games.platform_dates(kept, games.Platform.PS5, "il").full.date.text == "2027-03-12"
    assert rows(session_factory, title_id) == {"ps5": True}


def test_a_new_poster_of_igdb_replaces_the_stored_one(tracker, session_factory, made_up):
    title_id = add(tracker, made_up, state((PC, "full", "2027")))
    made_up.by_id["1"] = replace(made_up.by_id["1"], poster_path="https://images.igdb.com/new.jpg")

    poll(tracker, session_factory, made_up, state((PC, "full", "2027")))

    assert title(session_factory, title_id).poster_path == "https://images.igdb.com/new.jpg"


def test_the_next_check_follows_the_dates_of_the_game(tracker, session_factory, made_up, clock):
    add(tracker, made_up, state((PC, "full", "2027")))

    poll(tracker, session_factory, made_up, state((PC, "full", "2026-11-10")))

    with session_factory() as session:
        assert session.scalars(select(SourceSnapshot.next_check_at)).one() == clock.now.replace(tzinfo=None) + timedelta(hours=1)


def test_the_samples_of_games_are_in_the_menu_and_the_two_platforms_come_as_one_message(tracker, sender):
    ids = {sample.id for sample in tracker.test_samples()}
    assert {"game-announced", "game-moved", "game-released", "game-early-access", game_events.SAMPLE_TWO_PLATFORMS_ID} <= ids

    result = run(tracker.send_test_event(game_events.SAMPLE_TWO_PLATFORMS_ID))

    assert result.delivered
    assert sender.sent == [("Тестовое событие «Игра: вышла на двух платформах»: 🎮 Elden Ring вышла на ПК и PS5", [])]


@pytest.mark.parametrize(
    "sample_id, text",
    [
        ("game-announced", "🎮 Elden Ring: на PS5 объявлена дата — 12 марта 2027"),
        ("game-moved", "🎮 Elden Ring: на PS5 дата перенесена — 12 марта → 9 июня 2027"),
        ("game-released", "🎮 Elden Ring вышла на ПК"),
        ("game-early-access", "🎮 Hades II вышла в раннем доступе на ПК"),
    ],
)
def test_every_game_sample_reads_as_the_real_message(tracker, sender, sample_id, text):
    run(tracker.send_test_event(sample_id))

    [(message, _)] = sender.sent
    assert message.endswith(text)
