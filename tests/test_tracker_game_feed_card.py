"""A game in the feed and on the card (spec 8, 9.1, 9.3 and 12 of part 6.1): the pieces of «Скоро» and «Позже», the lines
of the platforms, the links to the stores and why the list of platforms is empty; the card of a game in the bot. And the
rule behind them: what comes out and what a card holds is decided by the poller of the kind, the feed reads as much
for one title of each kind as for fifty, and `feed.py` and `listing.py` do not ask which kind a title is.

The rows of a game are cut from the saved answers of IGDB (no network) and from made-up dates; the feed and the card go
through the facade on in-memory SQLite with a stand-in clock; the bot through a real aiogram Dispatcher.
"""

import asyncio
import json
import pathlib
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy import event as sa_event
from sqlalchemy import select

from app.bot.access import AccessMiddleware
from app.bot.tracker_handlers import ADD_BUTTON, MY_TITLES_BUTTON, register_tracker_handlers
from app.tracker import game_rows
from app.tracker.actions import DELETE, card_actions
from app.tracker.cards import format_card
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.feed_rows import FeedTitle
from app.tracker.games import GameDate, GameState, Release
from app.tracker.models import (
    EpisodeRecord, ExternalId, GamePlatformRecord, SeasonRecord, SettingRecord, SourceSnapshot, Title, TitleKind,
    TitleStatus,
)
from app.tracker.platforms import EUROPE, WORLD, Platform
from app.tracker.settings_store import STORE_COUNTRY_SETTING
from app.tracker.sources.igdb_games import GameSnapshot, parse_game

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "igdb"
TRACKER = pathlib.Path(__file__).parent.parent / "app" / "tracker"
NOW = datetime(2026, 11, 9, 12, 0)  # naive UTC, like everything stored
TODAY = NOW.date()
PC, PS4, PS5, XBOX_ONE, SWITCH, SWITCH_2 = 6, 48, 167, 49, 130, 508
MINE = (Platform.PC, Platform.PS5)
EVERY = tuple(Platform)
ALL_MARKED: dict[str, bool] = {}
GAME = FeedTitle(1, TitleKind.GAME, "Elden Ring")


def run(coro):
    return asyncio.run(coro)


def fixture_game(name) -> GameSnapshot:
    return parse_game(json.loads((FIXTURES / f"game-{name}.json").read_text(encoding="utf-8"))[0])


def made_up(*releases, steam_id=None, ps_concept=None, platforms=None):
    """Releases of the world region as (IGDB platform, kind, date text)."""
    records = tuple(Release(platform=p, region=WORLD, type=k, date=GameDate.parse(d)) for p, k, d in releases)
    listed = platforms if platforms is not None else sorted({r.platform for r in records})
    return GameState(steam_id=steam_id, ps_concept=ps_concept, platforms=tuple(listed), releases=records)


def day(days):
    return TODAY + timedelta(days=days)


def lines(game, mine=MINE, playing=ALL_MARKED, country="il", today=TODAY):
    return [(row.platform, row.text, row.playing) for row in game_rows.platform_rows(game, mine, playing, country, today)]


def pieces(game, told=MINE, country="il", today=TODAY):
    return sorted((p.day, p.text, p.when) for p in game_rows.feed_pieces(GAME, game, told, country, today))


# --- the lines of the platforms (9.1) ------------------------------------------------------------------------------


def test_hades_ii_out_on_the_pc_has_its_day_and_no_early_access():
    assert lines(fixture_game("hades-2").game, mine=(Platform.PC,)) == [("pc", "ПК — 25 сентября 2025", True)]


def test_hades_ii_a_year_ago_had_no_date_and_the_early_access():
    hades = fixture_game("hades-2").game
    earlier = replace(hades, releases=tuple(
        replace(r, date=GameDate.parse(None)) if r.type == "full" else r for r in hades.releases
    ))

    assert lines(earlier, mine=(Platform.PC,), today=date(2025, 5, 1)) == [
        ("pc", "ПК — дата не объявлена, ранний доступ с 6 мая 2024", True)
    ]


def test_hades_ii_before_its_full_release_names_both_dates():
    assert lines(fixture_game("hades-2").game, mine=(Platform.PC,), today=date(2025, 5, 1)) == [
        ("pc", "ПК — 25 сентября 2025, ранний доступ с 6 мая 2024", True)
    ]


def test_bloodborne_on_ps5_is_the_version_for_ps4():
    assert lines(fixture_game("bloodborne").game) == [("ps5", "PS5 — 27 марта 2015 (версия для PS4)", True)]


def test_hunter_deathwish_has_an_approximate_date():
    assert lines(fixture_game("hunter-deathwish").game)[1] == ("ps5", "PS5 — 3 квартал 2027", True)


def test_the_prince_of_persia_remake_is_cancelled():
    assert lines(fixture_game("pop-remake").game) == [("pc", "ПК — отменена", True), ("ps5", "PS5 — отменена", True)]


def test_only_my_platforms_the_game_is_on_in_the_order_of_the_table_with_their_marks():
    witcher = fixture_game("witcher-3").game

    found = lines(witcher, mine=(Platform.SWITCH, Platform.PC), playing={"pc": False, "switch": True})

    assert found == [("pc", "ПК — 19 мая 2015", False), ("switch", "Switch — 28 января 2021", True)]


def test_why_the_list_of_platforms_is_empty():
    mac_only = made_up((14, "full", "2026-03-12"))  # Mac: no platform of the tracker
    on_xbox = made_up((169, "full", "2026-03-12"))

    assert game_rows.platform_note(mac_only, ()) == "Платформы пока не объявлены"
    assert game_rows.platform_note(on_xbox, game_rows.platform_rows(on_xbox, MINE, {}, "il", TODAY)) == (
        "Игры нет на ваших платформах — выбрать платформы можно в Настройках"
    )
    assert game_rows.platform_note(on_xbox, game_rows.platform_rows(on_xbox, EVERY, {}, "il", TODAY)) == ""


# --- the links to the stores (9.1) ---------------------------------------------------------------------------------


def links(game, mine=MINE, country="il", name="Elden Ring"):
    return [(link.label, link.store, link.url) for link in game_rows.store_links(game, mine, country, name)]


def test_steam_and_the_concept_of_playstation_store_of_the_country():
    assert links(fixture_game("hades-2").game) == [
        ("Открыть в Steam", "Steam", "https://store.steampowered.com/app/1145350/"),
        ("Открыть в PlayStation Store", "PS Store", "https://store.playstation.com/en-il/concept/10018449"),
    ]
    assert links(fixture_game("hades-2").game, country="ua")[1][2] == (
        "https://store.playstation.com/ru-ua/concept/10018449"
    )


def test_without_a_concept_the_store_is_searched_by_the_original_name():
    hunter = fixture_game("hunter-deathwish")

    assert links(hunter.game, name=hunter.original_name)[1][2] == (
        "https://store.playstation.com/en-il/search/Hunter%3A%20The%20Reckoning%20-%20Deathwish"
    )


def test_a_game_only_on_ps4_has_the_store_too():
    assert [store for _, store, _ in links(fixture_game("bloodborne").game)] == ["PS Store"]


@pytest.mark.parametrize(
    "game, mine, country, stores",
    [
        ("hades-2", (Platform.PS5,), "il", ["PS Store"]),  # no ПК among mine: no Steam
        ("hades-2", (Platform.PC,), "il", ["Steam"]),  # no PS5 among mine: no PlayStation Store
        ("hades-2", MINE, "ru", ["Steam"]),  # Russia has no PlayStation Store
        ("hades-2", MINE, "kz", ["Steam"]),  # neither has Kazakhstan
        ("gta-6", MINE, "il", ["PS Store"]),  # no number of Steam
        ("pop-remake", (Platform.PC,), "il", []),
    ],
)
def test_where_a_link_is_missing(game, mine, country, stores):
    assert [store for _, store, _ in links(fixture_game(game).game, mine, country)] == stores


def test_a_game_neither_on_ps5_nor_on_ps4_has_no_playstation_store():
    pc_only = made_up((PC, "full", "2026-03-12"), ps_concept="1")

    assert links(pc_only) == []


# --- the pieces of the feed (8) ------------------------------------------------------------------------------------


def test_platforms_of_one_day_are_one_piece_and_the_older_version_says_where_it_runs():
    same_day = made_up((PC, "full", day(3).isoformat()), (PS5, "full", day(3).isoformat()))
    older = made_up((PS4, "full", day(3).isoformat()))

    assert pieces(same_day) == [(day(3), "Выход на ПК и PS5", "")]
    assert pieces(older) == [(day(3), "Выход на PS4 (идёт на PS5)", "")]


def test_platforms_of_other_days_are_pieces_of_their_days():
    game = made_up((PC, "full", day(3).isoformat()), (PS5, "full", day(20).isoformat()))

    assert pieces(game) == [(day(3), "Выход на ПК", ""), (day(20), "Выход на PS5", "")]


def test_the_early_access_while_the_full_release_is_not_out():
    early = made_up((PC, "early", day(2).isoformat()), (PC, "full", "2027"))
    same_day = made_up((PC, "early", day(2).isoformat()), (PC, "full", day(2).isoformat()))

    assert pieces(early) == [(day(2), "Ранний доступ на ПК", ""), (date(2027, 12, 31), "Выход на ПК", "2027")]
    assert pieces(same_day) == [(day(2), "Выход на ПК", "")]


def test_an_approximate_date_stands_on_the_end_of_its_period_with_its_label():
    assert pieces(made_up((PS5, "full", "2026-Q4"))) == [(date(2026, 12, 31), "Выход на PS5", "4 квартал 2026")]


def test_nothing_out_already_cancelled_not_announced_or_not_told():
    out = made_up((PC, "full", day(-1).isoformat()), (PC, "early", day(-30).isoformat()))
    cancelled = made_up((PS5, "cancelled", day(3).isoformat()))
    not_announced = made_up((PC, "full", None))
    on_xbox = made_up((169, "full", day(3).isoformat()))

    for game in (out, cancelled, not_announced, on_xbox):
        assert pieces(game) == [], game
    assert pieces(made_up((PC, "full", day(3).isoformat())), told=(Platform.PS5,)) == []


def test_switch_2_by_the_date_of_switch_is_told_by_switch_itself():
    game = made_up((SWITCH, "full", day(3).isoformat()))

    assert pieces(game, told=(Platform.SWITCH_2, Platform.SWITCH)) == [(day(3), "Выход на Switch", "")]
    assert pieces(game, told=(Platform.SWITCH_2,)) == [(day(3), "Выход на Switch (идёт на Switch 2)", "")]


def test_the_dates_are_the_ones_of_the_country():
    game = GameState(platforms=(PC,), releases=(
        Release(PC, EUROPE, "full", GameDate.parse(day(3).isoformat())),
        Release(PC, 2, "full", GameDate.parse(day(5).isoformat())),  # North America
    ))

    assert pieces(game, country="il") == [(day(3), "Выход на ПК", "")]
    assert pieces(game, country="us") == [(day(5), "Выход на ПК", "")]


# --- the feed and the card through the facade ----------------------------------------------------------------------


class FakeSender:
    def __init__(self):
        self.sent = []

    async def send(self, message, actions=()):
        self.sent.append(message)


class MadeUpGames:
    source_key = "igdb"

    def __init__(self):
        self.by_id = {}

    async def suggest(self, query):
        return []

    async def snapshot(self, external_id):
        return self.by_id.get(external_id)

    async def snapshot_to_add(self, external_id):
        return self.by_id.get(external_id)


@pytest.fixture
def session_factory():
    return create_session_factory("sqlite://")


@pytest.fixture
def games():
    return MadeUpGames()


def make_tracker(session_factory, games=None, now=NOW):
    return Tracker(
        session_factory, clock=lambda: now.replace(tzinfo=timezone.utc), sender=FakeSender(),
        sources={TitleKind.GAME: games} if games is not None else {},
    )


@pytest.fixture
def tracker(session_factory, games):
    return make_tracker(session_factory, games)


def add(tracker, games, game, external_id="1", name="Elden Ring", original_name=None):
    games.by_id[external_id] = GameSnapshot(external_id, name, original_name or name, 2026, game=game)
    return run(tracker.add_title(TitleKind.GAME, external_id)).title_id


def set_marks(session_factory, title_id, **marks):
    with session_factory() as session:
        for row in session.scalars(select(GamePlatformRecord).where(GamePlatformRecord.title_id == title_id)):
            row.playing = marks.get(row.platform, row.playing)
        session.commit()


def put_setting(session_factory, key, value):
    with session_factory() as session:
        session.merge(SettingRecord(key=key, value=value))
        session.commit()


def soon(feed):
    return [(d.day, [(r.title.name, r.text) for r in d.rows]) for d in feed.upcoming]


def later(feed):
    return [(r.title.name, r.day, r.text, r.when) for r in feed.later]


def test_an_exact_day_is_in_soon_with_the_platforms_of_the_day_in_one_piece(tracker, games):
    add(tracker, games, made_up((PC, "full", day(3).isoformat()), (PS5, "full", day(3).isoformat())))

    feed = run(tracker.feed())

    assert soon(feed) == [(day(3), [("Elden Ring", "Выход на ПК и PS5")])]
    assert later(feed) == []


def test_an_approximate_date_is_only_in_later_however_near_the_end_of_its_period(session_factory, games):
    tracker = make_tracker(session_factory, games, now=datetime(2026, 11, 25, 12, 0))
    add(tracker, games, made_up((PS5, "full", "2026-11")))

    feed = run(tracker.feed())

    assert soon(feed) == []
    assert later(feed) == [("Elden Ring", date(2026, 11, 30), "Выход на PS5", "ноябрь 2026")]


def test_a_game_with_a_row_in_soon_has_none_in_later(tracker, games):
    add(tracker, games, made_up((PC, "early", day(2).isoformat()), (PS5, "full", "2027")))

    feed = run(tracker.feed())

    assert soon(feed) == [(day(2), [("Elden Ring", "Ранний доступ на ПК")])]
    assert later(feed) == []


def test_unmarked_not_mine_and_archived_are_not_in_the_feed(tracker, session_factory, games):
    unmarked = add(tracker, games, made_up((PC, "full", day(3).isoformat()), (PS5, "full", day(4).isoformat())))
    set_marks(session_factory, unmarked, pc=False)
    add(tracker, games, made_up((169, "full", day(5).isoformat())), external_id="2", name="Halo")
    archived = add(tracker, games, made_up((PC, "full", day(6).isoformat())), external_id="3", name="Hades")
    run(tracker.mark_watched(archived))

    feed = run(tracker.feed())

    assert soon(feed) == [(day(4), [("Elden Ring", "Выход на PS5")])]


def test_a_game_is_in_the_feed_without_its_source(session_factory, games):
    add(make_tracker(session_factory, games), games, made_up((PC, "full", day(3).isoformat())))

    feed = run(make_tracker(session_factory).feed())  # the keys of IGDB are gone from `.env`

    assert soon(feed) == [(day(3), [("Elden Ring", "Выход на ПК")])]


def test_the_feed_and_the_card_take_the_country_of_the_stores_now(tracker, session_factory, games):
    game = GameState(platforms=(PC,), releases=(
        Release(PC, EUROPE, "full", GameDate.parse(day(3).isoformat())),
        Release(PC, 2, "full", GameDate.parse(day(5).isoformat())),
    ))
    title_id = add(tracker, games, game)
    put_setting(session_factory, STORE_COUNTRY_SETTING, "us")

    assert soon(run(tracker.feed())) == [(day(5), [("Elden Ring", "Выход на ПК")])]
    assert [row.text for row in run(tracker.title_card(title_id)).platforms] == [f"ПК — {day(5).day} ноября 2026"]


def test_bug_15_the_card_of_a_game_shows_the_dates_of_its_platforms(tracker, session_factory, games):
    hades = fixture_game("hades-2")
    title_id = add(tracker, games, hades.game, name="Hades II")
    set_marks(session_factory, title_id, ps5=False)

    card = run(tracker.title_card(title_id))

    assert [(r.platform, r.text, r.playing) for r in card.platforms] == [
        ("pc", "ПК — 25 сентября 2025", True), ("ps5", "PS5 — 14 апреля 2026", False),
    ]
    assert [link.store for link in card.store_links] == ["Steam", "PS Store"]
    assert card.platform_note == ""
    assert (card.theatrical_date, card.digital_date, card.seasons) == (None, None, None)


def test_the_card_names_my_platforms_whatever_the_game_has(tracker, session_factory, games):
    title_id = add(tracker, games, made_up((169, "full", "2026-03-12")))

    card = run(tracker.title_card(title_id))

    assert card.platforms == () and card.store_links == ()
    assert card.platform_note == "Игры нет на ваших платформах — выбрать платформы можно в Настройках"


def test_the_search_link_takes_the_original_name(tracker, session_factory, games):
    title_id = add(tracker, games, made_up((PS5, "full", "2027")), name="Ведьмак", original_name="The Witcher")

    card = run(tracker.title_card(title_id))

    assert [link.url for link in card.store_links] == ["https://store.playstation.com/en-il/search/The%20Witcher"]


# --- the number of reads does not grow with the number of titles --------------------------------------------------


def fill(session_factory, n):
    """`n` titles of each kind not in the archive, each with something coming, and one archived game."""
    with session_factory() as session:
        for i in range(n):
            series = Title(kind=TitleKind.SERIES, name=f"Сериал {i}", original_name="", genres=[], status=TitleStatus.WANT,
                           tracking_enabled=True, added_at=NOW, status_changed_at=NOW)
            anime = Title(kind=TitleKind.ANIME, name=f"Аниме {i}", original_name="", genres=[], status=TitleStatus.WANT,
                          tracking_enabled=True, added_at=NOW, status_changed_at=NOW)
            session.add_all([series, anime])
            session.flush()
            for title in (series, anime):
                season = SeasonRecord(title_id=title.id, number=1, name="Сезон 1", episode_count=None, watched=False)
                session.add(season)
                session.flush()
                session.add(EpisodeRecord(season_id=season.id, number=1, air_at=datetime.combine(day(2), time(12))))
            for kind, state in (
                (TitleKind.MOVIE, {"theatrical_date": day(2).isoformat(), "digital_date": None}),
                (TitleKind.GAME, made_up((PC, "full", day(2).isoformat()), (PS5, "full", "2027")).state()),
            ):
                title = Title(kind=kind, name=f"{kind.value} {i}", original_name="", genres=[], status=TitleStatus.WANT,
                              tracking_enabled=True, added_at=NOW, status_changed_at=NOW)
                session.add(title)
                session.flush()
                source = "tmdb_movie" if kind == TitleKind.MOVIE else "igdb"
                session.add(ExternalId(title_id=title.id, source=source, external_id=str(title.id), role="primary"))
                session.add(SourceSnapshot(title_id=title.id, source=source, state=state, observed_at=NOW))
                if kind == TitleKind.GAME:
                    session.add_all(GamePlatformRecord(title_id=title.id, platform=p, playing=True) for p in ("pc", "ps5"))
        session.commit()


def count_reads(session_factory):
    statements = []
    engine = session_factory.kw["bind"]

    def note(conn, cursor, statement, *args):
        statements.append(statement)

    sa_event.listen(engine, "before_cursor_execute", note)
    try:
        result = run(make_tracker(session_factory).feed())
    finally:
        sa_event.remove(engine, "before_cursor_execute", note)
    return len(statements), result


def test_the_feed_reads_as_much_for_one_title_of_each_kind_as_for_fifty_games_too():
    one, fifty = create_session_factory("sqlite://"), create_session_factory("sqlite://")
    fill(one, 1)
    fill(fifty, 50)

    reads_one, _ = count_reads(one)
    reads_fifty, big = count_reads(fifty)

    assert reads_one == reads_fifty
    assert len(big.upcoming[0].rows) == 200  # every title of the four kinds was read


def test_the_feed_and_the_list_do_not_ask_which_kind_a_title_is():
    for name in ("feed.py", "listing.py"):
        source = (TRACKER / name).read_text(encoding="utf-8")
        assert "TitleKind." not in source and "is_seasonal" not in source and "local_times" not in source, name


# --- the bot (9.3, 12) ---------------------------------------------------------------------------------------------


OWNER = 42


@pytest.fixture
def replies(monkeypatch):
    said = []

    async def message_answer(self, text=None, **kwargs):
        markup = kwargs.get("reply_markup")
        rows = getattr(markup, "inline_keyboard", []) if markup else []
        said.append((text, [b for row in rows for b in row]))

    async def callback_answer(self, text=None, **kwargs):
        said.append((text, []))

    monkeypatch.setattr(Message, "answer", message_answer)
    monkeypatch.setattr(CallbackQuery, "answer", callback_answer)
    return said


def feed_update(tracker, update):
    dp = Dispatcher()
    dp.update.outer_middleware(AccessMiddleware([OWNER]))
    register_tracker_handlers(dp, tracker, [OWNER])
    run(dp.feed_update(Bot(token="123456:TEST"), update))


def say(tracker, text):
    user = User(id=OWNER, is_bot=False, first_name="x")
    message = Message(message_id=1, date=0, chat=Chat(id=OWNER, type="private"), from_user=user, text=text)
    feed_update(tracker, Update(update_id=1, message=message))


def press(tracker, data):
    user = User(id=OWNER, is_bot=False, first_name="x")
    message = Message(message_id=1, date=0, chat=Chat(id=OWNER, type="private"), from_user=user, text="menu")
    feed_update(tracker, Update(update_id=2, callback_query=CallbackQuery(
        id="1", from_user=user, chat_instance="c", data=data, message=message,
    )))


def test_the_card_of_a_game_in_the_bot(tracker, session_factory, games, replies):
    title_id = add(tracker, games, fixture_game("hades-2").game, name="Hades II")
    set_marks(session_factory, title_id, ps5=False)

    say(tracker, MY_TITLES_BUTTON)
    [button] = [b for b in replies[-1][1] if "Hades" in b.text]
    press(tracker, button.callback_data)

    text, buttons = replies[-1]
    assert button.text == "🎮 Hades II (2026)"
    assert text.split("\n") == [
        "🎮 Игра · Хочу",
        "Hades II",
        "Год: 2026",
        "ПК — 25 сентября 2025",
        "PS5 — 14 апреля 2026 (не отмечена)",
        "Steam: https://store.steampowered.com/app/1145350/",
        "PS Store: https://store.playstation.com/en-il/concept/10018449",
    ]
    assert [b.text for b in buttons] == ["🗑 Удалить"]


def test_a_game_without_my_platforms_says_why_in_the_bot(tracker, games):
    card = run(tracker.title_card(add(tracker, games, made_up((14, "full", "2026-03-12")))))

    assert format_card(card).split("\n")[3:] == ["Платформы пока не объявлены"]
    assert [action.name for action in card_actions(card)] == [DELETE]


def test_a_wanted_game_has_no_watched_button(tracker, games):
    card = run(tracker.title_card(add(tracker, games, made_up((PC, "full", day(3).isoformat())))))

    assert card.status == TitleStatus.WANT and [action.name for action in card_actions(card)] == [DELETE]


def test_add_offers_no_game_even_with_its_source(tracker, replies):
    say(tracker, ADD_BUTTON)

    assert [b.text for b in replies[-1][1]] == []
