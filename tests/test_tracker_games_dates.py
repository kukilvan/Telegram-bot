"""The dates of a game (spec 5 of part 6.1): five precisions, the record of the country, backward compatibility,
a cancelled platform and a lost date. Pure: the saved IGDB answers go through the adapter, no network, no database."""

import json
import pathlib
from datetime import date

import pytest

from app.tracker.games import (
    CANCELLED, EARLY, FULL, NOT_ANNOUNCED, GameDate, GameState, PlatformDate, Release, carry_over, has_platform, pick,
    platform_dates,
)
from app.tracker.platforms import EUROPE, NORTH_AMERICA, STORE_COUNTRIES, WORLD, Platform
from app.tracker.sources.igdb_games import parse_game

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "igdb"
JAPAN = 5


def game(name) -> GameState:
    return parse_game(json.loads((FIXTURES / f"game-{name}.json").read_text(encoding="utf-8"))[0]).game


def full_label(state, platform, country="il"):
    return platform_dates(state, platform, country).full.label


# --- the date of a game ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, label, start, end, exact",
    [
        ("2027-03-12", "12 марта 2027", date(2027, 3, 12), date(2027, 3, 12), True),
        ("2027-03", "март 2027", date(2027, 3, 1), date(2027, 3, 31), False),
        ("2028-02", "февраль 2028", date(2028, 2, 1), date(2028, 2, 29), False),
        ("2026-Q4", "4 квартал 2026", date(2026, 10, 1), date(2026, 12, 31), False),
        ("2027-Q1", "1 квартал 2027", date(2027, 1, 1), date(2027, 3, 31), False),
        ("2027", "2027", date(2027, 1, 1), date(2027, 12, 31), False),
        (None, "дата не объявлена", None, None, False),
    ],
)
def test_five_precisions_have_their_labels_and_periods(text, label, start, end, exact):
    game_date = GameDate.parse(text)

    assert (game_date.label, game_date.start, game_date.end, game_date.exact) == (label, start, end, exact)
    assert game_date.text == text
    assert game_date.announced is (text is not None)


@pytest.mark.parametrize(
    "release, text",
    [
        ({"date_format": 0, "date": 1427414400, "y": 2015, "m": 3}, "2015-03-27"),
        ({"date_format": 1, "date": 1801958400, "y": 2027, "m": 2}, "2027-02"),
        ({"date_format": 2, "date": 1861833600, "y": 2028, "m": 12}, "2028"),  # `date` is 31 December, not the start
        ({"date_format": 5, "date": 1822262400, "y": 2027, "m": 9}, "2027-Q3"),  # `date` is the last day of the quarter
        ({"date_format": 6, "y": 2026}, "2026-Q4"),
        ({"date_format": 3, "y": 2027}, "2027-Q1"),
        ({"date_format": 7}, None),  # «TBD»
        ({}, None),
    ],
)
def test_a_date_of_igdb_by_its_format(release, text):
    assert GameDate.from_igdb(release).text == text


def test_y_and_m_come_from_date_when_they_are_missing():
    assert GameDate.from_igdb({"date_format": 1, "date": 1801958400}).text == "2027-02"  # 1 February 2027, UTC
    assert GameDate.from_igdb({"date_format": 2, "date": 1861833600}).text == "2028"  # 31 December 2028
    assert GameDate.from_igdb({"date_format": 5, "date": 1822262400}).text == "2027-Q3"


def test_the_day_is_read_by_utc():
    assert GameDate.from_igdb({"date_format": 0, "date": 1427414400 + 23 * 3600}).text == "2015-03-27"  # 23:00 UTC


@pytest.mark.parametrize(
    "release",
    [
        {"date_format": 0, "date": "yesterday"},
        {"date_format": 0},
        {"date_format": 1, "y": 2027, "m": 13},
        {"date_format": 2, "y": "2027"},
        {"date_format": 2, "y": True},
        {"date_format": 99, "y": 2027},
        {"date_format": 0, "date": 10**20},
    ],
)
def test_garbage_from_igdb_is_no_date(release):
    assert GameDate.from_igdb(release) == NOT_ANNOUNCED


@pytest.mark.parametrize("text", ["", "2027-13", "2027-Q5", "2027-Q0", "27", "2027-3-12", "20270312", "garbage", "2027-02-30", 2027])
def test_the_stored_text_is_read_strictly(text):
    with pytest.raises(ValueError):
        GameDate.parse(text)


def test_a_release_of_unknown_kind_in_the_snapshot_is_a_bug():
    with pytest.raises(ValueError):
        Release.from_state({"platform": 6, "region": 8, "type": "beta", "date": "2027"})


# --- the record of the country (spec 5.2) ------------------------------------------------------------------------------


def test_bloodborne_has_the_european_day_for_israel_and_the_american_one_for_the_usa():
    bloodborne = game("bloodborne")

    assert pick(bloodborne.releases, 48, FULL, STORE_COUNTRIES["il"].regions).text == "2015-03-27"
    assert pick(bloodborne.releases, 48, FULL, STORE_COUNTRIES["us"].regions).text == "2015-03-24"


def test_yomawari_by_regions():
    yomawari = game("yomawari")

    # the PC: Europe for Israel, North America for the USA
    assert full_label(yomawari, Platform.PC, "il") == "28 октября 2016"
    assert full_label(yomawari, Platform.PC, "us") == "25 октября 2016"
    # PS5: no world and no Europe — North America before the earlier Japanese day
    assert full_label(yomawari, Platform.PS5, "il") == "5 ноября 2026"
    assert full_label(yomawari, Platform.PS5, "us") == "5 ноября 2026"


def test_the_world_comes_first_then_the_regions_of_the_country_then_the_earliest_of_the_others():
    def release(region, text):
        return Release(6, region, FULL, GameDate.parse(text))

    regions = STORE_COUNTRIES["il"].regions
    every = [release(JAPAN, "2026-01-01"), release(NORTH_AMERICA, "2026-02-01"), release(EUROPE, "2026-03-01"),
             release(WORLD, "2026-04-01")]

    assert pick(every, 6, FULL, regions).text == "2026-04-01"
    assert pick(every[:3], 6, FULL, regions).text == "2026-03-01"
    assert pick(every[:2], 6, FULL, regions).text == "2026-02-01"
    assert pick([release(JAPAN, None), release(9, "2027"), release(10, "2026-Q4")], 6, FULL, regions).text == "2026-Q4"
    assert pick([release(JAPAN, None)], 6, FULL, regions) == NOT_ANNOUNCED
    assert pick(every, 6, EARLY, regions) is None
    assert pick(every, 167, FULL, regions) is None


def test_two_records_of_one_region_the_earlier_start_wins_and_not_announced_is_last():
    releases = [Release(6, EUROPE, FULL, GameDate.parse(None)), Release(6, EUROPE, FULL, GameDate.parse("2027")),
                Release(6, EUROPE, FULL, GameDate.parse("2026-12-30"))]

    assert pick(releases, 6, FULL, STORE_COUNTRIES["il"].regions).text == "2026-12-30"


def test_hades_ii_has_the_early_access_and_the_full_release_on_the_pc():
    dates = platform_dates(game("hades-2"), Platform.PC, "il")

    assert (dates.early.label, dates.full.label, dates.cancelled) == ("6 мая 2024", "25 сентября 2025", False)
    assert platform_dates(game("hades-2"), Platform.PS5, "il").early is None


def test_approximate_dates_and_not_announced():
    assert full_label(game("witcher-4"), Platform.PS5) == "2028"
    assert full_label(game("hunter-deathwish"), Platform.PC) == "3 квартал 2027"
    assert full_label(game("ultimate-theater"), Platform.PC) == "29 октября 2025"
    assert full_label(game("ultimate-theater"), Platform.PS5) == "дата не объявлена"


# --- backward compatibility (spec 5.3) ---------------------------------------------------------------------------------


def test_bloodborne_on_ps5_is_the_ps4_version():
    assert full_label(game("bloodborne"), Platform.PS5, "il") == "27 марта 2015 (версия для PS4)"
    assert full_label(game("bloodborne"), Platform.PS5, "us") == "24 марта 2015 (версия для PS4)"
    assert platform_dates(game("bloodborne"), Platform.PC, "il") is None


def test_the_witcher_3_on_ps5_and_switch_2_takes_the_earlier_older_date():
    witcher = game("witcher-3")

    assert full_label(witcher, Platform.PS5) == "19 мая 2015 (версия для PS4)"
    assert full_label(witcher, Platform.SWITCH_2) == "28 января 2021 (версия для Switch)"
    assert full_label(witcher, Platform.XBOX_SERIES) == "19 мая 2015 (версия для Xbox One)"
    assert full_label(witcher, Platform.SWITCH) == "28 января 2021"
    assert full_label(witcher, Platform.PC) == "19 мая 2015"


def own_and_older(own, older):
    releases = []
    if own != "none":
        releases.append(Release(167, WORLD, FULL, GameDate.parse(own)))
    if older != "none":
        releases.append(Release(48, WORLD, FULL, GameDate.parse(older)))
    return GameState(platforms=(48, 167), releases=tuple(releases))


@pytest.mark.parametrize(
    "own, older, expected",
    [
        ("2027-03-12", "2027-03-12", PlatformDate(GameDate.parse("2027-03-12"))),  # a tie: the own one
        ("2027-03-12", "2027", PlatformDate(GameDate.parse("2027"), "PS4")),  # the year starts earlier
        ("2027", "2027-03-12", PlatformDate(GameDate.parse("2027"))),
        (None, "2027", PlatformDate(GameDate.parse("2027"), "PS4")),  # not announced loses
        ("2027", None, PlatformDate(GameDate.parse("2027"))),
        (None, None, PlatformDate(NOT_ANNOUNCED)),
        ("none", "2015-05-19", PlatformDate(GameDate.parse("2015-05-19"), "PS4")),  # only the older one has a record
        ("none", None, PlatformDate(NOT_ANNOUNCED, "PS4")),
        ("2027", "none", PlatformDate(GameDate.parse("2027"))),
    ],
)
def test_the_own_date_or_the_older_one(own, older, expected):
    assert platform_dates(own_and_older(own, older), Platform.PS5, "il").full == expected


def test_the_game_is_on_a_platform_by_its_list_or_by_its_records():
    assert has_platform(GameState(platforms=(48,)), Platform.PS5)
    assert has_platform(GameState(releases=(Release(130, WORLD, FULL, NOT_ANNOUNCED),)), Platform.SWITCH_2)
    assert not has_platform(GameState(platforms=(48,)), Platform.PC)
    assert not has_platform(GameState(platforms=(167,)), Platform.SWITCH)  # an older console does not run newer games
    dates = platform_dates(GameState(platforms=(6,)), Platform.PC, "il")
    assert dates == platform_dates(GameState(platforms=(6,)), Platform.PC, "us")
    assert (dates.full, dates.early, dates.cancelled) == (None, None, False)


# --- cancelled (spec 5.2) ----------------------------------------------------------------------------------------------


def test_prince_of_persia_is_cancelled_everywhere():
    remake = game("pop-remake")

    for platform in (Platform.PC, Platform.PS5, Platform.XBOX_SERIES):
        assert platform_dates(remake, platform, "il").cancelled, platform
    assert platform_dates(remake, Platform.SWITCH, "il") is None


def test_a_cancelled_platform_whose_older_one_came_out_is_the_older_version():
    state = GameState(platforms=(48, 167), releases=(
        Release(167, WORLD, CANCELLED, NOT_ANNOUNCED), Release(48, WORLD, FULL, GameDate.parse("2020-11-12")),
    ))

    dates = platform_dates(state, Platform.PS5, "il")

    assert not dates.cancelled and dates.full.label == "12 ноября 2020 (версия для PS4)"


def test_a_platform_with_a_cancelled_record_and_a_date_is_not_cancelled():
    state = GameState(platforms=(6,), releases=(
        Release(6, JAPAN, CANCELLED, NOT_ANNOUNCED), Release(6, WORLD, FULL, GameDate.parse("2027")),
    ))

    assert not platform_dates(state, Platform.PC, "il").cancelled


# --- a lost date (spec 5.4) --------------------------------------------------------------------------------------------


def state_of(*releases, platforms=(6, 167)):
    return GameState(platforms=platforms, releases=tuple(Release(p, WORLD, kind, GameDate.parse(text)) for p, kind, text in releases))


def test_a_record_the_source_stopped_sending_is_carried_over():
    previous = state_of((6, FULL, "2027-03-12"), (6, EARLY, "2026-05-01"), (167, FULL, "2027-03-12"))
    current = state_of((167, FULL, "2027-04-02"))

    merged = carry_over(previous, current)

    assert {(r.platform, r.type, r.date.text) for r in merged.releases} == {
        (167, FULL, "2027-04-02"), (6, FULL, "2027-03-12"), (6, EARLY, "2026-05-01"),
    }


def test_a_tbd_record_replaces_the_previous_date():
    previous = state_of((6, FULL, "2027-03-12"))
    current = state_of((6, FULL, None))

    assert carry_over(previous, current) == current


def test_a_cancellation_is_not_overridden_by_the_previous_date():
    previous = state_of((6, FULL, "2027-03-12"))
    current = state_of((6, CANCELLED, None))

    merged = carry_over(previous, current)

    assert merged == current and platform_dates(merged, Platform.PC, "il").cancelled


def test_only_the_lost_kind_is_carried_over():
    previous = state_of((6, FULL, "2027-03-12"), (6, EARLY, "2026-05-01"))
    current = state_of((6, FULL, "2027-06-01"))

    merged = carry_over(previous, current)

    assert [(r.type, r.date.text) for r in merged.releases] == [(FULL, "2027-06-01"), (EARLY, "2026-05-01")]


def test_a_platform_gone_from_the_list_comes_back_with_its_records():
    previous = state_of((167, FULL, "2027-03-12"), platforms=(6, 167))
    current = state_of((6, FULL, "2027"), platforms=(6,))

    merged = carry_over(previous, current)

    assert merged.platforms == (6, 167)
    assert full_label(merged, Platform.PS5) == "12 марта 2027"


def test_nothing_lost_leaves_the_new_snapshot_as_it_is():
    previous = state_of((6, FULL, "2027"))
    current = state_of((6, FULL, "2027-03-12"), platforms=(6,))

    assert carry_over(previous, current) is current
