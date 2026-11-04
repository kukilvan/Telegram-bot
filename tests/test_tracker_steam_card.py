"""What the owner sees of the Steam prices through the core (spec 6 of part 6.2, ticket 05): the block «Steam» of the card
(when it is there and when it is not), the mark «−30 %» of the rows of the list, the line «Цена в Steam» of the bot card
and the feed that stays as it was.

Through the facade: fake clock, in-memory SQLite, a made-up game source and a fake source of price looks (as in
`test_tracker_game_prices`); the lines themselves are tested in `test_tracker_price_rows`.
"""

from datetime import timedelta

import pytest
from sqlalchemy import event, select

from app.tracker.cards import format_card
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.games import GameDate, GameState, Release
from app.tracker.models import SourceSnapshot, TitleKind, TitleStatus
from app.tracker.platforms import WORLD
from app.tracker.prices import PRICE, Price, PriceLook
from app.tracker.settings_store import MY_PLATFORMS_SETTING, STORE_COUNTRY_SETTING
from test_tracker_game_prices import (
    HADES, PC, PS5, T0, FakeClock, FakePrices, FakeSender, MadeUpGames, add, game, igdb_says, naive, put_setting, run,
)

NOT_CHECKED = "Цену ещё не проверяли — она появится через минуту-другую"
MINUS_30 = "−30 %"


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
def prices():
    return FakePrices()


@pytest.fixture
def tracker(session_factory, clock, igdb, prices):
    return Tracker(session_factory, clock=clock, sender=FakeSender(), sources={TitleKind.GAME: igdb}, price_source=prices)


def card_of(tracker, title_id):
    return run(tracker.title_card(title_id))


def store_look(session_factory, title_id, look):
    """The snapshot of the prices as a check would have left it."""
    with session_factory() as session:
        session.scalar(
            select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == "steam")
        ).state = look.state()
        session.commit()


def on_sale(prices, appid=HADES, final=19530, original=27900, pct=30):
    prices.final[appid] = final
    prices.discount[appid] = (original, pct)


# --- the block of the card --------------------------------------------------------------------------------------------


def test_the_card_of_a_game_for_prices_has_the_block_with_its_lines(tracker, igdb, prices):
    title_id = add(tracker, igdb)
    assert card_of(tracker, title_id).steam.line == NOT_CHECKED  # the snapshot is not made yet: the rule, not the snapshot
    run(tracker.poll_due())
    steam = card_of(tracker, title_id).steam
    assert steam.line == "Цена: ₪279" and steam.bot_line == "₪279"
    assert steam.caption == "Цены для страны «Израиль» · проверено в 12:00"
    assert steam.lowest == "" and steam.bundles == ()  # one record of the history: nothing to compare


def test_the_block_of_a_game_with_a_discount_says_when_it_ends_and_that_it_is_the_lowest(tracker, igdb, prices, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())  # the price before the sale is a record of the history
    ends = naive(T0) + timedelta(days=3)
    store_look(session_factory, title_id, PriceLook(HADES, "il", PRICE, "₪{}", Price(19530, 27900, 30, ends)))
    with session_factory() as session:
        from app.tracker.models import PriceRecord

        session.add(PriceRecord(title_id=title_id, seen_at=naive(T0), appid=HADES, country="il", currency="₪{}",
                                final=19530, original=27900, pct=30))
        session.commit()
    steam = card_of(tracker, title_id).steam
    assert steam.line == f"Скидка {MINUS_30}: ₪279 → ₪195,30, до 12 ноября"
    assert steam.lowest == "Сейчас — самая низкая цена с добавления"


def test_a_discount_whose_end_has_come_is_not_shown_by_the_card_nor_the_list(tracker, igdb, prices, session_factory, clock):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    ends = naive(T0) + timedelta(hours=1)
    store_look(session_factory, title_id, PriceLook(HADES, "il", PRICE, "₪{}", Price(19530, 27900, 30, ends)))
    assert card_of(tracker, title_id).steam.line.startswith("Скидка")
    assert run(tracker.list_titles())[0].mark == MINUS_30

    clock.advance(hours=2)  # the end has come, the next check is in hours
    assert card_of(tracker, title_id).steam.line == "Цена: ₪279"
    assert run(tracker.list_titles())[0].mark == ""


def test_a_game_without_a_steam_page_has_the_block_that_says_so(tracker, igdb, prices):
    title_id = add(tracker, igdb, game(steam_id=None))
    run(tracker.poll_due())
    steam = card_of(tracker, title_id).steam
    assert steam.line == "Страницы в Steam пока нет — придёт сообщение, когда появится" and prices.calls == []
    assert steam.caption == "Цены для страны «Израиль»"


def test_a_look_of_another_country_waits_for_its_check_instead_of_showing_the_old_currency(tracker, igdb, prices, session_factory):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    put_setting(session_factory, STORE_COUNTRY_SETTING, "de")
    assert card_of(tracker, title_id).steam.line == NOT_CHECKED
    run(tracker.poll_due())  # the check in the new country
    assert card_of(tracker, title_id).steam.caption.startswith("Цены для страны «Германия»")


@pytest.mark.parametrize(
    "why",
    ["started", "completed", "dropped", "mark off", "pc not mine", "igdb took pc away", "no source"],
)
def test_no_block_where_prices_are_not_told_about(why, tracker, igdb, prices, session_factory, clock):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    assert card_of(tracker, title_id).steam is not None

    if why == "started":
        run(tracker.mark_started(title_id))
    elif why == "completed":
        run(tracker.mark_watched(title_id))
    elif why == "dropped":
        run(tracker.mark_dropped(title_id))
    elif why == "mark off":
        run(tracker.set_platform_playing(title_id, "pc", False))
    elif why == "pc not mine":
        put_setting(session_factory, MY_PLATFORMS_SETTING, ["ps5"])
    elif why == "igdb took pc away":
        igdb_says(session_factory, igdb, game(platforms=(PS5,)))
        run(tracker.poll_due())
    else:
        tracker = Tracker(
            session_factory, clock=clock, sender=FakeSender(), sources={TitleKind.GAME: igdb}, price_source=None
        )
    # before the check of the next minute reconciles the snapshots: the block follows the rule, not the snapshot
    assert card_of(tracker, title_id).steam is None


def test_a_film_has_no_block(tracker, session_factory):
    from app.tracker.models import Title

    with session_factory() as session:
        session.add(Title(kind=TitleKind.MOVIE, name="Дюна", original_name="Dune", year=2021, genres=[],
                          status=TitleStatus.WANT, tracking_enabled=True, added_at=naive(T0), status_changed_at=naive(T0)))
        session.commit()
    assert card_of(tracker, 1).steam is None


# --- the mark of the list ---------------------------------------------------------------------------------------------


def two_games(tracker, igdb, prices):
    sale = add(tracker, igdb, game(), "1", "Hades II")
    plain = add(tracker, igdb, game(steam_id="2"), "2", "Elden Ring")
    on_sale(prices, HADES)
    run(tracker.poll_due())
    return sale, plain


def test_the_row_of_a_game_with_a_discount_has_the_mark_and_the_others_have_none(tracker, igdb, prices):
    sale, plain = two_games(tracker, igdb, prices)
    marks = {row.id: row.mark for row in run(tracker.list_titles())}
    assert marks == {sale: MINUS_30, plain: ""}


def test_a_giveaway_has_the_mark_of_a_hundred_percent(tracker, igdb, prices):
    add(tracker, igdb)
    on_sale(prices, HADES, final=0, original=27900, pct=100)
    run(tracker.poll_due())
    assert run(tracker.list_titles())[0].mark == "−100 %"


@pytest.mark.parametrize("why", ["started", "completed", "dropped", "mark off", "pc not mine"])
def test_a_game_that_prices_are_not_told_about_has_no_mark(why, tracker, igdb, prices, session_factory):
    title_id = add(tracker, igdb)
    on_sale(prices, HADES)
    run(tracker.poll_due())
    assert run(tracker.list_titles())[0].mark == MINUS_30
    if why == "started":
        run(tracker.mark_started(title_id))
    elif why == "completed":
        run(tracker.mark_watched(title_id))
    elif why == "dropped":
        run(tracker.mark_dropped(title_id))
    elif why == "mark off":
        run(tracker.set_platform_playing(title_id, "pc", False))
    else:
        put_setting(session_factory, MY_PLATFORMS_SETTING, ["ps5"])
    assert [row.mark for row in run(tracker.list_titles())] == [""]


def test_the_list_reads_as_much_for_fifty_games_as_for_one(tracker, igdb, prices, session_factory):
    def reads():
        statements = []
        engine = session_factory.kw["bind"]
        listener = lambda *args: statements.append(args[2])  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        try:
            rows = run(tracker.list_titles())
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len([s for s in statements if s.lstrip().upper().startswith("SELECT")]), rows

    on_sale(prices, HADES)
    add(tracker, igdb, game(), "1")
    run(tracker.poll_due())
    one, rows = reads()
    assert [row.mark for row in rows] == [MINUS_30]
    for n in range(2, 51):
        add(tracker, igdb, game(steam_id=str(n)), str(n), f"Игра {n}")
    run(tracker.poll_due())
    fifty, rows = reads()
    assert len(rows) == 50 and one == fifty


def test_without_a_source_of_prices_the_rows_have_no_mark(session_factory, clock, igdb, prices):
    on_sale(prices, HADES)
    with_prices = Tracker(session_factory, clock=clock, sender=FakeSender(), sources={TitleKind.GAME: igdb}, price_source=prices)
    add(with_prices, igdb)
    run(with_prices.poll_due())
    without = Tracker(session_factory, clock=clock, sender=FakeSender(), sources={TitleKind.GAME: igdb})
    assert [row.mark for row in run(without.list_titles())] == [""]


def test_the_archive_has_no_marks(tracker, igdb, prices):
    title_id = add(tracker, igdb)
    on_sale(prices, HADES)
    run(tracker.poll_due())
    run(tracker.mark_dropped(title_id))
    from app.tracker.models import ARCHIVE_STATUSES

    assert [row.mark for row in run(tracker.list_titles(statuses=ARCHIVE_STATUSES))] == [""]


# --- the bot -----------------------------------------------------------------------------------------------------------


def test_the_bot_card_has_the_price_line_between_the_platforms_and_the_stores(tracker, igdb, prices):
    title_id = add(tracker, igdb)
    on_sale(prices, HADES)
    run(tracker.poll_due())
    lines = format_card(card_of(tracker, title_id)).split("\n")
    store = next(i for i, line in enumerate(lines) if line.startswith("Steam: "))
    assert lines[store - 1] == f"Цена в Steam: ₪195,30 ({MINUS_30})"
    assert lines[store - 2].startswith("ПК — ") or lines[store - 2].startswith("PS5 — ")
    assert not any("Самая низкая" in line or "Бандл" in line for line in lines)  # not in the bot


def test_the_bot_card_without_the_block_has_no_price_line(tracker, igdb, prices):
    title_id = add(tracker, igdb)
    run(tracker.poll_due())
    run(tracker.mark_started(title_id))
    assert "Цена в Steam" not in format_card(card_of(tracker, title_id))


def test_the_bot_card_before_the_first_check_says_so(tracker, igdb):
    title_id = add(tracker, igdb)
    assert "Цена в Steam: ещё не проверяли" in format_card(card_of(tracker, title_id)).split("\n")


# --- the feed ----------------------------------------------------------------------------------------------------------


def test_the_feed_is_the_same_before_and_after_the_prices_come(tracker, igdb, prices):
    def pc_game(steam_id, day):
        release = Release(platform=PC, region=WORLD, type="full", date=GameDate.parse(day))
        return GameState(steam_id=steam_id, platforms=(PC,), releases=(release,))

    add(tracker, igdb, pc_game(HADES, "2026-11-12"), "1", "Hades II")
    add(tracker, igdb, pc_game("2", "2027-06-04"), "2", "Elden Ring")
    before = run(tracker.feed())
    assert before.upcoming and before.later  # «Скоро» and «Позже» both have a game
    on_sale(prices, HADES)
    run(tracker.poll_due())
    assert run(tracker.feed()) == before
