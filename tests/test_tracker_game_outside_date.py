"""A date outside the regions of the country (KI-35, spec 1.1 of stage 9.1b): it is no release for the owner, the card says
it in a line of its own, and nothing is told or fed by it.

The line is pure (`game_rows.outside_date`); the rest goes through the facade with a made-up game source.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.tracker import game_rows
from app.tracker.cards import format_card
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.games import CANCELLED, EARLY, FULL, GameState, Release
from app.tracker.release_dates import ReleaseDate
from app.tracker.models import Event, SourceSnapshot, TitleKind
from app.tracker.platforms import REGION_WORDS, STORE_COUNTRIES, Platform
from test_tracker_game_prices import FakeClock, FakePrices, FakeSender, MadeUpGames, T0, add, igdb_says, run
from test_tracker_steam_card import card_of
from test_web_card import make_client

PC, PS4, PS5 = 6, 48, 167
JAPAN, AUSTRALIA, WORLD, EUROPE = 5, 3, 8, 1
BOTH = (Platform.PC, Platform.PS5)


def state(*records, platforms=None):
    """Records as (IGDB platform, region, type, date text)."""
    releases = tuple(Release(p, region, kind, ReleaseDate.parse(text)) for p, region, kind, text in records)
    return GameState(platforms=tuple(platforms or sorted({r.platform for r in releases})), releases=releases)


def line(game, mine=BOTH, country="il"):
    return game_rows.outside_date(game, mine, country)


# --- the line -------------------------------------------------------------------------------------------------------


def test_a_date_only_in_japan_is_the_outside_line_and_the_platform_has_none_of_its_own():
    game = state((PS5, JAPAN, FULL, "2027-03-12"))

    assert line(game) == "в Японии — 12 марта 2027"
    assert game_rows.platform_rows(game, BOTH, {}, "il", T0.date())[0].text == "PS5 — дата не объявлена"


def test_an_approximate_date_reads_as_such():
    assert line(state((PS5, JAPAN, FULL, "2027-03"))) == "в Японии — март 2027"


def test_it_is_hidden_when_the_platforms_own_date_ends_earlier_and_shown_when_it_ends_later():
    earlier = state((PS5, EUROPE, FULL, "2027-02-01"), (PS5, JAPAN, FULL, "2027-03-12"))
    later = state((PS5, EUROPE, FULL, "2027-05-01"), (PS5, JAPAN, FULL, "2027-03-12"))

    assert line(earlier) == ""
    assert line(later) == "в Японии — 12 марта 2027"


def test_a_year_of_the_country_does_not_hide_an_earlier_day_outside_it():
    assert line(state((PS5, EUROPE, FULL, "2027"), (PS5, JAPAN, FULL, "2027-03-12"))) == "в Японии — 12 марта 2027"
    assert line(state((PS5, EUROPE, FULL, "2027-03-12"), (PS5, JAPAN, FULL, "2027"))) == ""


@pytest.mark.parametrize(
    "region, words",
    [(3, "в Австралии"), (4, "в Новой Зеландии"), (5, "в Японии"), (6, "в Китае"), (7, "в Азии"), (9, "в Корее"),
     (10, "в Бразилии"), (0, "в другой стране"), (99, "в другой стране")],
)
def test_every_region_has_its_words(region, words):
    assert line(state((PC, region, FULL, "2027-03-12"))) == f"{words} — 12 марта 2027"


def test_the_regions_of_every_country_never_need_a_word():
    assert not {1, 2, 8} & set(REGION_WORDS)
    for country in STORE_COUNTRIES.values():
        assert {1, 2, 8} <= set(country.regions)


def test_the_regions_of_the_country_are_not_outside_and_the_country_changes_the_line():
    game = state((PC, EUROPE, FULL, "2027-03-12"), (PC, 2, FULL, "2027-03-13"))

    assert line(game) == ""
    assert line(game, country="us") == ""


def test_the_older_platforms_record_counts_and_the_earliest_start_of_all_wins():
    game = state((PS4, JAPAN, FULL, "2027-04-01"), (PC, AUSTRALIA, FULL, "2027-03-12"), platforms=(PC, PS5))

    assert line(game) == "в Австралии — 12 марта 2027"
    assert line(game, mine=(Platform.PS5,)) == "в Японии — 1 апреля 2027"


def test_a_cancelled_platform_a_platform_the_game_is_not_on_and_a_platform_not_mine_are_left_out():
    cancelled = state((PS4, JAPAN, FULL, "2027-03-12"), (PS5, WORLD, CANCELLED, None))
    assert line(cancelled) == ""  # PS5 is cancelled: the older console's day in Japan gives it no line
    assert line(state((PC, JAPAN, FULL, "2027-03-12")), mine=(Platform.PS5,)) == ""  # not on PS5
    assert line(state((PC, JAPAN, FULL, "2027-03-12"), (PS5, JAPAN, FULL, "2027-05-12")), mine=(Platform.PS5,)) == (
        "в Японии — 12 мая 2027"
    )


def test_an_early_access_and_a_not_announced_record_outside_are_no_line():
    assert line(state((PC, JAPAN, EARLY, "2027-03-12"))) == ""
    assert line(state((PC, JAPAN, FULL, None))) == ""
    assert line(state()) == ""


# --- through the core -----------------------------------------------------------------------------------------------


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
def tracker(session_factory, clock, igdb):
    return Tracker(
        session_factory, clock=clock, sender=FakeSender(), sources={TitleKind.GAME: igdb}, price_source=FakePrices()
    )


def pending(session_factory):
    with session_factory() as session:
        return list(session.scalars(select(Event.type)))


def test_the_card_has_the_line_and_the_bot_card_prints_it_after_the_platforms(tracker, igdb):
    title = add(tracker, igdb, state((PS5, JAPAN, FULL, "2027-03-12"), (PC, WORLD, FULL, "2025-01-01")))

    card = card_of(tracker, title)

    assert card.outside_date == "в Японии — 12 марта 2027"
    lines = format_card(card).splitlines()
    assert lines[lines.index("PS5 — дата не объявлена") + 1] == "в Японии — 12 марта 2027"


def test_a_card_without_such_a_date_has_an_empty_line_and_the_bot_card_has_no_extra_line(tracker, igdb):
    title = add(tracker, igdb, state((PC, WORLD, FULL, "2025-01-01")))

    card = card_of(tracker, title)

    assert card.outside_date == ""
    assert "в Японии" not in format_card(card)


def test_a_japanese_day_that_has_come_is_no_release_no_message_and_no_feed_piece(
    tracker, igdb, session_factory, clock
):
    title = add(tracker, igdb, state((PS5, JAPAN, FULL, None)))
    igdb_says(session_factory, igdb, state((PS5, JAPAN, FULL, "2026-11-01")))
    clock.advance(days=1)

    run(tracker.poll_due())

    assert pending(session_factory) == []
    feed = run(tracker.feed())
    assert [row for day in feed.upcoming for row in day.rows] == [] and not feed.later
    assert card_of(tracker, title).platforms[0].text == "PS5 — дата не объявлена"


def test_such_a_date_does_not_shorten_the_interval_of_the_check(tracker, igdb, session_factory, clock):
    title = add(tracker, igdb, state((PS5, JAPAN, FULL, None)))
    igdb_says(session_factory, igdb, state((PS5, JAPAN, FULL, (T0 + timedelta(days=1)).date().isoformat())))
    clock.advance(days=1)
    run(tracker.poll_due())

    with session_factory() as session:
        snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.source == "igdb"))
        assert snapshot.next_check_at - snapshot.observed_at >= timedelta(days=1)
    assert title


# --- the web card ---------------------------------------------------------------------------------------------------

HINT = "Дата только в Японии — не выход для вашей страны: сообщения «вышла» по ней не будет."


def test_the_web_card_has_a_row_without_a_checkbox_and_the_hint_under_the_platforms(tracker, igdb, tmp_path):
    title = add(tracker, igdb, state((PS5, JAPAN, FULL, "2027-03-12"), (PC, WORLD, FULL, "2025-01-01")))

    html = make_client(tracker, tmp_path).get(f"/titles/{title}").text

    assert '<li class="season-item outside-date">в Японии — 12 марта 2027</li>' in html
    assert html.count('type="checkbox" name="playing"') == 2  # the two platforms; the row has none
    assert html.index("PS5 — дата не объявлена") < html.index("в Японии — 12 марта 2027") < html.index(HINT)


def test_the_web_card_has_neither_the_row_nor_the_hint_without_such_a_date(tracker, igdb, tmp_path):
    title = add(tracker, igdb, state((PC, WORLD, FULL, "2025-01-01")))

    html = make_client(tracker, tmp_path).get(f"/titles/{title}").text

    assert "outside-date" not in html and "Дата только" not in html
