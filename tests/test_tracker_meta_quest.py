"""The platform Meta Quest and SteamVR as ПК (spec 1–5 of stage 6.5): the table, the dates of a platform with several own
IGDB numbers, the line of a suggestion, the card rows, the folded release message and the first poll after the update.

Pure: the saved IGDB answers of 2026-11-28 (`fixtures/igdb/quest-games.json`) go through the adapter, no network, no
database.
"""

import json
import pathlib
from datetime import date, datetime

import pytest

from app.tracker import delivery, game_events, game_rows
from app.tracker.games import (
    CANCELLED,
    EARLY,
    FULL,
    KNOWN_BEFORE_6_5,
    GameState,
    PlatformDate,
    Release,
    has_platform,
    igdb_numbers,
    platform_dates,
)
from app.tracker.platforms import IGDB_LABELS, PLATFORMS, WORLD, Platform
from app.tracker.release_dates import ReleaseDate
from app.tracker.settings_store import check_platforms
from app.tracker.sources.igdb_games import parse_game, platform_line

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "igdb"
PC, STEAMVR, PS4, PS5, SWITCH, SWITCH_2 = 6, 163, 48, 167, 130, 508
QUEST_3, QUEST_2, QUEST_1 = 471, 386, 384
OCULUS_VR, RIFT, WMR, PSVR, PSVR2 = 162, 385, 161, 165, 390
JAPAN = 5
QUEST = Platform.META_QUEST

_ANSWERS = {item["name"]: item for item in json.loads((FIXTURES / "quest-games.json").read_text(encoding="utf-8"))}


def answer(start: str) -> dict:
    """The saved IGDB record whose name starts so (one of them has a broken apostrophe)."""
    [item] = [item for name, item in _ANSWERS.items() if name.startswith(start)]
    return item


def game(start: str) -> GameState:
    return parse_game(answer(start)).game


def state(*records, platforms=()):
    """Records as (IGDB platform, type, date text) or (…, region)."""
    releases = tuple(
        Release(r[0], r[3] if len(r) > 3 else WORLD, r[1], ReleaseDate.parse(r[2])) for r in records
    )
    return GameState(platforms=tuple(sorted(set(platforms) | {r.platform for r in releases})), releases=releases)


def full_label(game_state, platform, country="il"):
    dates = platform_dates(game_state, platform, country)
    return dates.full.label if dates.full is not None else None


# --- the table (spec 1) ---------------------------------------------------------------------------------------------


def test_meta_quest_is_the_last_platform_with_its_labels_and_three_own_numbers():
    assert list(Platform)[-1] is QUEST and QUEST.value == "meta_quest"
    info = PLATFORMS[QUEST]
    assert (info.settings_label, info.label, info.igdb_ids, info.older) == ("Meta Quest", "Meta Quest", (471, 386, 384), None)
    assert PLATFORMS[Platform.PC].igdb_ids == (PC, STEAMVR)


def test_every_own_number_has_its_platform_label_and_the_not_taken_ones_are_unknown():
    assert {number: IGDB_LABELS[number] for number in (PC, STEAMVR, QUEST_3, QUEST_2, QUEST_1)} == {
        PC: "ПК", STEAMVR: "ПК", QUEST_3: "Meta Quest", QUEST_2: "Meta Quest", QUEST_1: "Meta Quest",
    }
    assert not {OCULUS_VR, RIFT, WMR, 387, PSVR, PSVR2} & set(IGDB_LABELS)


def test_the_numbers_of_a_platform_are_its_own_and_the_older_one():
    assert igdb_numbers(QUEST) == (471, 386, 384)
    assert igdb_numbers(Platform.PC) == (6, 163)
    assert igdb_numbers(Platform.PS5) == (167, 48)


def test_meta_quest_is_a_platform_of_the_settings():
    assert check_platforms(["meta_quest", "pc"]) == ["pc", "meta_quest"]


# --- the dates (spec 2) ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "start, rows",
    [
        ("Batman", {QUEST: "22 октября 2024"}),
        ("Asgard", {QUEST: "15 декабря 2023"}),
        ("Beat Saber", {Platform.PC: "21 мая 2019", QUEST: "21 мая 2019"}),
        ("Supernatural", {QUEST: "23 апреля 2020"}),
        ("Red Matter 2", {Platform.PC: "18 августа 2022", QUEST: "18 августа 2022"}),
    ],
)
def test_the_examples_of_the_spec_give_their_rows_for_israel(start, rows):
    found = {
        platform: dates.full.label for platform in Platform
        if (dates := platform_dates(game(start), platform, "il")) is not None
    }
    assert found == rows
    assert all(platform_dates(game(start), p, "il").full.via is None for p in rows)  # no version text


def test_postal_2_vr_with_a_month_on_quest_2_reads_the_month():
    assert full_label(state((QUEST_2, FULL, "2027-06")), QUEST) == "июнь 2027"


@pytest.mark.parametrize("number", [QUEST_3, QUEST_2, QUEST_1])
def test_each_quest_number_gives_the_own_date(number):
    assert platform_dates(state((number, FULL, "2027-03-12")), QUEST, "il").full == PlatformDate(
        ReleaseDate.parse("2027-03-12")
    )


def test_beat_saber_takes_no_patch_record_of_status_36():
    beat_saber = game("Beat Saber")
    assert {release.platform for release in beat_saber.releases} == {STEAMVR, QUEST_1}
    quest_only_patches = state(platforms=(QUEST_3,))
    assert platform_dates(quest_only_patches, QUEST, "il").full is None  # «дата не объявлена»


@pytest.mark.parametrize(
    "records, expected",
    [
        (((QUEST_3, FULL, "2027-03-12"), (QUEST_2, FULL, "2027-02-20")), "20 февраля 2027"),  # earlier end
        (((QUEST_3, FULL, "2027-03-12"), (QUEST_2, FULL, "2027")), "12 марта 2027"),  # a day ends before its year
        (((QUEST_3, FULL, "2026"), (QUEST_2, FULL, "2026-12-31")), "31 декабря 2026"),  # equal ends: the narrower
        (((QUEST_3, FULL, "2026-12"), (QUEST_2, FULL, "2026-Q4")), "декабрь 2026"),  # equal ends: the narrower
        (((QUEST_3, FULL, None), (QUEST_2, FULL, "2028")), "2028"),  # «не объявлена» loses
        (((QUEST_3, FULL, None), (QUEST_2, FULL, None)), "дата не объявлена"),
    ],
)
def test_among_own_numbers_the_date_that_ends_earliest_wins(records, expected):
    assert full_label(state(*records), QUEST) == expected


def test_pc_year_and_steamvr_day_give_the_day():
    assert full_label(state((PC, FULL, "2026"), (STEAMVR, FULL, "2026-03-12")), Platform.PC) == "12 марта 2026"


def test_steamvr_alone_gives_the_pc_date():
    assert full_label(state((STEAMVR, FULL, "2022-08-18")), Platform.PC) == "18 августа 2022"
    assert has_platform(state(platforms=(STEAMVR,)), Platform.PC)


def test_pc_cancelled_and_a_steamvr_date_is_not_cancelled():
    dates = platform_dates(state((PC, CANCELLED, None), (STEAMVR, FULL, "2026-03-12")), Platform.PC, "il")
    assert not dates.cancelled and dates.full.label == "12 марта 2026"


def test_all_own_numbers_cancelled_is_cancelled():
    dates = platform_dates(state((QUEST_3, CANCELLED, None), (QUEST_2, CANCELLED, None)), QUEST, "il")
    assert dates.cancelled and dates.full is None


def test_the_early_access_is_read_among_own_numbers_too():
    dates = platform_dates(state((QUEST_2, EARLY, "2026-05-06"), (QUEST_3, EARLY, "2026-06-01")), QUEST, "il")
    assert dates.early.label == "6 мая 2026" and dates.full is None


def test_a_game_only_on_oculus_vr_is_not_on_meta_quest():
    supernatural_like = state((OCULUS_VR, FULL, "2020-04-23"))
    assert supernatural_like.platforms == (OCULUS_VR,)
    assert platform_dates(supernatural_like, QUEST, "il") is None


def test_older_tells_reads_the_own_numbers_of_another_told_platform():
    assert game_events.older_tells(Platform.SWITCH_2, [Platform.SWITCH])
    assert not game_events.older_tells(Platform.SWITCH_2, [Platform.PC, QUEST])
    assert not game_events.older_tells(QUEST, list(Platform))  # no older platform


def test_the_date_outside_the_country_is_read_over_every_own_number():
    japan_first = state((QUEST_2, FULL, "2027-03-12", JAPAN), (QUEST_3, FULL, "2027"))
    assert game_rows.outside_date(japan_first, [QUEST], "il") == "в Японии — 12 марта 2027"


# --- the line of a suggestion (spec 3) ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "numbers, line",
    [
        (answer("Beat Saber")["platforms"], "ПК, Meta Quest"),
        ([QUEST_2, QUEST_3], "Meta Quest"),
        ([PC, STEAMVR], "ПК"),
        ([PS5, PS4], "PS5, PS4"),
        ([SWITCH_2, SWITCH], "Switch 2, Switch"),
        ([OCULUS_VR], None),
    ],
)
def test_the_line_of_a_suggestion_names_each_label_once(numbers, line):
    assert platform_line(numbers) == line


# --- what the owner sees (spec 4) -----------------------------------------------------------------------------------


def test_the_card_row_of_meta_quest_is_last_and_reads_as_the_others():
    beat_saber = game("Beat Saber")
    rows = game_rows.platform_rows(beat_saber, list(Platform), {}, "il", date(2026, 11, 28))
    assert [(row.platform, row.text, row.playing) for row in rows] == [
        ("pc", "ПК — 21 мая 2019", True), ("meta_quest", "Meta Quest — 21 мая 2019", True),
    ]
    no_date = state(platforms=(QUEST_3,))
    [row] = game_rows.platform_rows(no_date, [QUEST], {"meta_quest": False}, "il", date(2026, 11, 28))
    assert (row.text, row.playing) == ("Meta Quest — дата не объявлена", False)
    cancelled = state((QUEST_3, CANCELLED, None))
    assert game_rows.platform_rows(cancelled, [QUEST], {}, "il", date(2026, 11, 28))[0].text == "Meta Quest — отменена"


TODAY = date(2026, 11, 10)
LOOK = datetime(2026, 11, 9, 12, 0)


def detect(old, new, told=tuple(Platform)):
    return game_events.detect_events(1, "Thief VR", old, new, "il", told, LOOK, TODAY, TODAY)


def test_ps5_and_meta_quest_released_the_same_day_fold_into_one_message():
    old = state((PS5, FULL, "2026-11-12"), (QUEST_3, FULL, "2026-11-12"))
    new = state((PS5, FULL, "2026-11-10"), (QUEST_3, FULL, "2026-11-10"))
    events = detect(old, new)
    queue = [
        delivery.Pending(n, n, event.type, 1, event.text, {"text": event.text, **event.data}, LOOK)
        for n, event in enumerate(events)
    ]

    [unit] = delivery.fold(queue, episodes=False)

    assert unit.text == "🎮 Thief VR вышла на PS5 и Meta Quest"


def test_a_release_on_two_quest_numbers_is_one_event():
    old = state((QUEST_3, FULL, "2026-11-12"), (QUEST_2, FULL, "2026-11-14"))
    new = state((QUEST_3, FULL, "2026-11-10"), (QUEST_2, FULL, "2026-11-14"))
    assert [event.text for event in detect(old, new)] == ["🎮 Thief VR вышла на Meta Quest"]


# --- the first poll after the update (spec 5) -----------------------------------------------------------------------


def legacy(*records):
    """A snapshot stored before stage 6.5: no `known`, only the numbers the tracker knew then."""
    return GameState.from_state({key: value for key, value in state(*records).state().items() if key != "known"})


def test_a_snapshot_without_known_knew_the_table_before_the_stage_and_a_new_one_knows_everything():
    old = legacy((PC, FULL, "2026-12-01"))
    assert old.known == KNOWN_BEFORE_6_5 == (6, 48, 49, 130, 167, 169, 508)
    assert GameState().known == tuple(sorted(IGDB_LABELS))
    assert game("Beat Saber").state()["known"] == [6, 48, 49, 130, 163, 167, 169, 384, 386, 471, 508]
    stored = game("Beat Saber").state()
    assert GameState.from_state(stored) == game("Beat Saber")


def test_the_first_poll_records_the_steamvr_and_quest_dates_without_events():
    old = legacy((PC, FULL, "2026-12-01"))
    new = state((PC, FULL, "2026-12-01"), (STEAMVR, FULL, "2026-11-01"), (QUEST_3, FULL, "2027-03-12"))

    assert detect(old, new) == []
    assert detect(GameState.from_state(new.state()), new) == []  # nothing changed


def test_a_pc_release_of_the_first_poll_still_comes_and_by_its_own_number():
    old = legacy((PC, FULL, "2026-11-12"))
    new = state((PC, FULL, "2026-11-10"), (STEAMVR, FULL, "2026-11-01"), (QUEST_3, FULL, "2027-03-12"))

    [event] = detect(old, new)

    assert (event.type, event.text, event.data["date"]) == (game_events.RELEASED, "🎮 Thief VR вышла на ПК", "2026-11-10")
    assert "late" not in event.data


def test_the_second_poll_compares_everything():
    first = state((PC, FULL, "2026-12-01"), (STEAMVR, FULL, "2026-12-01"), (QUEST_3, FULL, "2027-03-12"))
    stored = GameState.from_state(first.state())
    second = state((PC, FULL, "2026-12-01"), (STEAMVR, FULL, "2026-12-01"), (QUEST_3, FULL, "2027-04-02"))

    assert [event.text for event in detect(stored, second)] == [
        "🎮 Thief VR: на Meta Quest дата перенесена — 12 марта → 2 апреля 2027"
    ]


def test_a_game_on_quest_only_gives_nothing_on_the_first_poll_and_a_move_on_the_second():
    old = legacy()  # IGDB's Quest records were dropped before the stage
    new = state((QUEST_3, FULL, "2027-03-12"))
    assert detect(old, new) == []
    later = state((QUEST_3, FULL, "2027-04-02"))
    assert len(detect(GameState.from_state(new.state()), later)) == 1


def test_seen_as_leaves_out_the_numbers_the_old_snapshot_did_not_know():
    new = state((PC, FULL, "2026-12-01"), (STEAMVR, FULL, "2026-11-01"), platforms=(QUEST_2,))
    seen = new.seen_as(KNOWN_BEFORE_6_5)
    assert seen.platforms == (PC,) and [release.platform for release in seen.releases] == [PC]
    assert seen.known == KNOWN_BEFORE_6_5
