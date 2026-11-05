"""The rules of the follow-up check (`follow_ups`, spec 4, 5.4, 5.5, 6.1–6.3, 6.6 of stage 6.3): what is shown, the
date of a follow-up, the order, what is new and the events. On the saved IGDB answers of 2026-11-04
(`tests/fixtures/igdb/follow-ups-<game>.json`) and on made-up candidates; today is fixed, as the owner's clock gives it.
"""

import json
import pathlib
from dataclasses import replace
from datetime import date

import pytest

from app.tracker import follow_ups
from app.tracker.follow_ups import (
    EXPANSION_ANNOUNCED, NOT_CHECKED, SEQUEL_ANNOUNCED, TYPES, Candidate, FollowUps, FollowUpsSnapshot,
    came_out_before, check, expansions_shown, follow_up_date, sequels_shown,
)
from app.tracker.games import CANCELLED, EARLY, FULL, GameDate, Release
from app.tracker.platforms import Platform
from app.tracker.sources.igdb_follow_ups import parse_follow_ups

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "igdb"
TODAY = date(2026, 11, 4)
MINE = (Platform.PC, Platform.PS5)
ISRAEL = "il"
PC, PS4, PS5 = 6, 48, 167
WORLD = 8


def snapshot(name):
    return parse_follow_ups(json.loads((FIXTURES / f"follow-ups-{name}.json").read_text(encoding="utf-8"))[0])


def shown(name, mine=MINE, country=ISRAEL, today=TODAY):
    found = snapshot(name)
    return (
        [(c.name, follow_up_date(c, mine, country).label) for c in expansions_shown(found, mine, country)],
        [(c.name, follow_up_date(c, mine, country).label) for c in sequels_shown(found, mine, country, today)],
    )


def release(platform, text, kind=FULL):
    return Release(platform, WORLD, kind, GameDate.parse(text))


def candidate(id_, name="X", first=None, platforms=(PC,), releases=None, standalone=False):
    if releases is None:
        releases = tuple(release(number, first.isoformat() if first else None) for number in platforms)
    return Candidate(id_, name, first, tuple(platforms), tuple(releases), standalone)


# --- table 4.6 ---------------------------------------------------------------------------------------------------------

TABLE = {
    "witcher-3": (
        [
            ("Ведьмак 3: Дикая Охота - Каменные сердца", "12 октября 2015"),
            ("Ведьмак 3: Дикая Охота - Кровь и Вино", "30 мая 2016"),
            ("Ведьмак 3: Дикая Охота — Баллады прошлого", "2027"),
        ],
        [
            ("Gwent: The Witcher Card Game", "23 октября 2018"),
            ("The Witcher 3: Wild Hunt Remastered", "29 сентября 2026"),
            ("The Witcher IV", "2028"),
            ("The Witcher Remake", "дата не объявлена"),
        ],
    ),
    "elden-ring": (
        [("Elden Ring: Shadow of the Erdtree", "21 июня 2024")], [("Elden Ring Nightreign", "30 мая 2025")],
    ),
    "hades": ([], [("Hades II", "25 сентября 2025")]),
    "hades-2": ([], []),
    "gta-6": ([], []),
    "baldurs-gate-3": ([], []),  # The Black Hound is cancelled
    "hunter-deathwish": ([], []),  # no collection
    "cyberpunk-2077": ([("Cyberpunk 2077: Phantom Liberty", "26 сентября 2023")], []),  # Cyberpunk 2: no platform yet
    "spider-man": (
        [("Marvel's Spider-Man: Miles Morales", "12 ноября 2020")],
        [
            ("Marvel's Spider-Man Remastered", "19 ноября 2020"),
            ("Marvel Человек-Паук 2", "20 октября 2023"),
            ("Marvel's Wolverine", "15 сентября 2026"),
        ],
    ),
    "uncharted-4": (
        [("Uncharted: The Lost Legacy", "23 августа 2017")],
        [
            ("Uncharted 4: A Thief's End - Remastered", "28 января 2022"),
            ("Uncharted: The Lost Legacy - Remastered", "28 января 2022"),
        ],
    ),
    "lost-legacy": (
        [],
        [
            ("Uncharted 4: A Thief's End - Remastered", "28 января 2022"),
            ("Uncharted: The Lost Legacy - Remastered", "28 января 2022"),
        ],
    ),
    "god-of-war": (
        [],
        [
            ("God of War Рагнарёк", "9 ноября 2022"),
            ("God of War Sons of Sparta", "12 февраля 2026"),
            ("God of War Laufey", "16 февраля 2027"),
            ("God of War II Remake", "дата не объявлена"),
            ("God of War III Remake", "дата не объявлена"),
            ("God of War Remake", "дата не объявлена"),
        ],
    ),
    "ac-valhalla": (
        [
            ("Assassin's Creed Valhalla: Wrath of the Druids", "13 мая 2021"),
            ("Assassin's Creed Valhalla: The Siege of Paris", "12 августа 2021"),
            ("Discovery Tour: Viking Age", "19 октября 2021"),
            ("Assassin's Creed Valhalla: Dawn of Ragnarök", "10 марта 2022"),
        ],
        [
            ("Assassin's Creed Mirage", "5 октября 2023"),
            ("Assassin's Creed Shadows", "20 марта 2025"),
            ("Assassin's Creed Black Flag Resynced", "9 июля 2026"),
            ("Assassin's Creed: Codename Hexe", "дата не объявлена"),
        ],
    ),
}


@pytest.mark.parametrize("name", sorted(TABLE))
def test_the_saved_answers_give_the_table_of_the_spec(name):
    assert shown(name) == TABLE[name]


def test_the_standalone_expansions_are_marked():
    assert [c.standalone for c in expansions_shown(snapshot("spider-man"), MINE, ISRAEL)] == [True]
    marks = {c.name: c.standalone for c in expansions_shown(snapshot("ac-valhalla"), MINE, ISRAEL)}
    assert marks["Discovery Tour: Viking Age"] and not marks["Assassin's Creed Valhalla: Wrath of the Druids"]


def test_pc_only_removes_the_candidates_of_the_playstation_alone():
    pc = (Platform.PC,)
    assert shown("uncharted-4", pc)[0] == []  # The Lost Legacy: PS4 only
    assert "Marvel's Wolverine" not in dict(shown("spider-man", pc)[1])
    assert [name for name, _ in shown("god-of-war", pc)[1]] == ["God of War Рагнарёк"]
    assert shown("witcher-3", pc) == TABLE["witcher-3"]


# --- on my platforms (4.1, 4.2) ----------------------------------------------------------------------------------------


def test_a_candidate_cancelled_on_my_platforms_is_not_shown():
    hound = next(c for c in snapshot("baldurs-gate-3").games if c.name == "Baldur's Gate III: The Black Hound")
    assert hound.releases[0].type == CANCELLED
    cancelled = candidate("1", platforms=(PC,), releases=(release(PC, None, CANCELLED),))
    elsewhere = candidate("2", platforms=(PC, PS5), releases=(release(PC, None, CANCELLED), release(PS5, "2027")))
    found = FollowUpsSnapshot(own_date=date(2020, 1, 1), expansions=(cancelled,), games=(cancelled, elsewhere))
    assert expansions_shown(found, MINE, ISRAEL) == []
    assert sequels_shown(found, MINE, ISRAEL, TODAY) == [elsewhere]
    assert sequels_shown(found, (Platform.PC,), ISRAEL, TODAY) == []


def test_a_ps4_candidate_is_on_the_ps5():
    old = candidate("1", platforms=(PS4,), first=date(2027, 3, 1))
    found = FollowUpsSnapshot(own_date=date(2020, 1, 1), games=(old,))
    assert sequels_shown(found, (Platform.PS5,), ISRAEL, TODAY) == [old]
    assert follow_up_date(old, (Platform.PS5,), ISRAEL).label == "1 марта 2027"


def test_an_expansion_announced_without_platforms_is_shown_with_no_date():
    bare = candidate("1", platforms=(), releases=())
    on_switch = candidate("2", platforms=(130,))
    found = FollowUpsSnapshot(own_date=date(2020, 1, 1), expansions=(bare, on_switch), games=(bare,))
    assert expansions_shown(found, MINE, ISRAEL) == [bare]
    assert follow_up_date(bare, MINE, ISRAEL).label == "дата не объявлена"
    assert sequels_shown(found, MINE, ISRAEL, TODAY) == []  # a game of the series needs a platform of mine
    with_record_only = candidate("3", platforms=(), releases=(release(130, "2027"),))
    assert expansions_shown(FollowUpsSnapshot(expansions=(with_record_only,)), MINE, ISRAEL) == []


# --- «came out before» (4.3) -------------------------------------------------------------------------------------------


def test_before_by_the_own_date_the_same_day_counts():
    own = date(2020, 5, 1)
    assert came_out_before(candidate("1", first=date(2020, 4, 30)), own, TODAY)
    assert came_out_before(candidate("1", first=own), own, TODAY)
    assert not came_out_before(candidate("1", first=date(2020, 5, 2)), own, TODAY)
    assert not came_out_before(candidate("1", first=None), own, TODAY)


def test_before_without_the_own_date_is_by_today():
    assert came_out_before(candidate("1", first=TODAY), None, TODAY)
    assert not came_out_before(candidate("1", first=date(2026, 11, 5)), None, TODAY)
    assert not came_out_before(candidate("1", first=None), None, TODAY)


def test_a_game_not_out_shows_only_the_games_not_out():
    out, coming = candidate("1", first=date(2025, 1, 1)), candidate("2", first=date(2027, 1, 1))
    found = FollowUpsSnapshot(own_date=None, games=(out, coming))
    assert sequels_shown(found, MINE, ISRAEL, TODAY) == [coming]


def test_year_only_dates_compare_as_igdb_stores_them():
    remastered = next(c for c in snapshot("witcher-3").games if c.name == "The Witcher 3: Wild Hunt Remastered")
    witcher_4 = next(c for c in snapshot("witcher-3").games if c.name == "The Witcher IV")
    assert came_out_before(remastered, witcher_4.first, TODAY)


# --- the date and the order (4.4, 4.5) ---------------------------------------------------------------------------------


def test_the_date_is_the_full_release_that_ends_earliest():
    both = candidate("1", platforms=(PC, PS5), releases=(release(PC, "2027"), release(PS5, "2027-03-12")))
    assert follow_up_date(both, MINE, ISRAEL).label == "12 марта 2027"
    assert follow_up_date(both, (Platform.PC,), ISRAEL).label == "2027"
    quarter = candidate("2", platforms=(PC, PS5), releases=(release(PC, "2026-Q4"), release(PS5, "2027-01")))
    assert follow_up_date(quarter, MINE, ISRAEL).label == "4 квартал 2026"


def test_early_access_counts_only_without_a_full_release():
    hades = next(c for c in snapshot("hades").games if c.name == "Hades II")
    assert follow_up_date(hades, MINE, ISRAEL).label == "25 сентября 2025"
    early = replace(hades, releases=tuple(r for r in hades.releases if r.type == EARLY))
    assert follow_up_date(early, MINE, ISRAEL).label == "6 мая 2024 (ранний доступ)"
    assert follow_up_date(early, (Platform.PS5,), ISRAEL).label == "дата не объявлена"


def test_a_cancelled_platform_and_an_unannounced_record_give_no_date():
    odd = candidate("1", platforms=(PC, PS5), releases=(release(PC, None), release(PS5, "2027", CANCELLED)))
    assert follow_up_date(odd, MINE, ISRAEL).label == "дата не объявлена"


def test_the_order_is_by_date_then_name_then_id_and_no_date_last():
    late = candidate("5", "Alpha", first=date(2028, 1, 1))
    early_b = candidate("4", "Beta", first=date(2027, 1, 1))
    early_a = candidate("30", "beta", first=date(2027, 1, 1))
    early_c = candidate("200", "Ёж", first=date(2027, 1, 1))
    none = candidate("1", "Aaa", platforms=(PC,), releases=(release(PC, None),))
    year = candidate("7", "Zeta", platforms=(PC,), releases=(release(PC, "2027"),))
    found = FollowUpsSnapshot(own_date=date(2020, 1, 1), games=(none, late, early_c, early_a, year, early_b))
    assert [c.id for c in sequels_shown(found, MINE, ISRAEL, TODAY)] == ["4", "30", "200", "7", "5", "1"]


# --- what is new (5.4, 5.5) --------------------------------------------------------------------------------------------


def run_check(previous, now, mine=MINE, country=ISRAEL, today=TODAY, listed=(), game="Ведьмак 3: Дикая охота"):
    return check(previous, now, game, mine, country, today, listed)


def reference(name="witcher-3", **kwargs):
    return run_check(NOT_CHECKED, snapshot(name), **kwargs).state


def test_the_reference_point_gives_nothing_and_fills_known():
    result = run_check(NOT_CHECKED, snapshot("witcher-3"))
    assert result.events == ()
    assert result.state.snapshot == snapshot("witcher-3")
    assert result.state.known == {"12503", "13166", "403150", "19474", "415005", "194662", "220277"}


def test_the_same_snapshot_again_gives_nothing():
    state = reference()
    result = run_check(state, snapshot("witcher-3"))
    assert result.events == () and result.state == state


def test_a_new_game_of_the_series_is_announced_once():
    before = replace(snapshot("witcher-3"), games=tuple(c for c in snapshot("witcher-3").games if c.id != "194662"))
    state = run_check(NOT_CHECKED, before).state
    result = run_check(state, snapshot("witcher-3"))
    [event] = result.events
    assert event.type == SEQUEL_ANNOUNCED
    assert event.dedup_key == "game:follow_up:194662"
    assert event.text == (
        "🎮 Анонсирована новая игра серии: The Witcher IV\nПродолжение игры «Ведьмак 3: Дикая охота»\nВыход: 2028"
    )
    assert event.data == {"kind": "game", "sequel_id": "194662", "sequel_title": "The Witcher IV", "date": "2028"}
    assert "194662" in result.state.known
    assert run_check(result.state, snapshot("witcher-3")).events == ()


def test_a_new_expansion_is_announced_with_its_text():
    before = replace(snapshot("witcher-3"), expansions=snapshot("witcher-3").expansions[:2])
    [event] = run_check(run_check(NOT_CHECKED, before).state, snapshot("witcher-3")).events
    assert event.type == EXPANSION_ANNOUNCED
    assert event.text == (
        "🎮 Анонсировано дополнение: Ведьмак 3: Дикая Охота — Баллады прошлого\n"
        "Дополнение к игре «Ведьмак 3: Дикая охота»\nВыход: 2027"
    )
    assert event.data == {
        "kind": "game", "sequel_id": "403150", "sequel_title": "Ведьмак 3: Дикая Охота — Баллады прошлого",
        "date": "2027",
    }
    assert event.dedup_key == "game:follow_up:403150"


def test_expansions_come_before_sequels_and_a_date_not_announced_is_null():
    found = snapshot("witcher-3")
    empty = replace(found, expansions=(), games=())
    events = run_check(run_check(NOT_CHECKED, empty).state, found).events
    assert [e.type for e in events] == [EXPANSION_ANNOUNCED] * 3 + [SEQUEL_ANNOUNCED] * 4
    assert events[-1].data["date"] is None and events[-1].text.endswith("Выход: дата не объявлена")


def test_a_first_platform_of_mine_is_news():
    found = snapshot("witcher-3")
    sirius = next(c for c in found.games if c.name == "The Witcher: Project Sirius")
    state = run_check(NOT_CHECKED, found).state
    assert sirius.id not in state.known
    with_platform = replace(sirius, platforms=(PC,), releases=(release(PC, "2027"),))
    now = replace(found, games=tuple(with_platform if c.id == sirius.id else c for c in found.games))
    [event] = run_check(state, now).events
    assert (event.type, event.data["sequel_id"], event.data["date"]) == (SEQUEL_ANNOUNCED, sirius.id, "2027")


def test_cyberpunk_2_getting_a_platform_is_news():
    found = snapshot("cyberpunk-2077")
    state = run_check(NOT_CHECKED, found, game="Cyberpunk 2077").state
    [second] = found.games
    now = replace(found, games=(replace(second, platforms=(PS5,), releases=(release(PS5, "2030"),)),))
    [event] = run_check(state, now, game="Cyberpunk 2077").events
    assert event.text.splitlines()[1] == "Продолжение игры «Cyberpunk 2077»"


def test_a_first_date_after_the_game_is_news():
    found = FollowUpsSnapshot(own_date=date(2020, 1, 1), games=(candidate("1", first=date(2019, 1, 1)),))
    state = run_check(NOT_CHECKED, found).state
    assert state.known == frozenset()
    fixed = replace(found, games=(candidate("1", first=date(2027, 1, 1)),))
    [event] = run_check(state, fixed).events
    assert event.data["sequel_id"] == "1"


def test_a_change_of_my_platforms_or_of_the_country_is_no_news():
    state = reference("uncharted-4", mine=(Platform.PC,))
    assert "26193" not in state.known
    result = run_check(state, snapshot("uncharted-4"), mine=MINE)
    assert result.events == ()
    assert "26193" in result.state.known
    assert run_check(result.state, snapshot("uncharted-4"), mine=MINE, country="us").events == ()


def test_a_listed_candidate_gives_nothing_but_goes_into_known():
    before = replace(snapshot("witcher-3"), games=())
    state = run_check(NOT_CHECKED, before).state
    result = run_check(state, snapshot("witcher-3"), listed={"194662", "1942"})
    assert "194662" not in {e.data["sequel_id"] for e in result.events}
    assert len(result.events) == 3
    assert "194662" in result.state.known


def test_a_candidate_gone_and_back_is_no_news():
    found = snapshot("witcher-3")
    state = run_check(NOT_CHECKED, found).state
    gone = run_check(state, replace(found, games=tuple(c for c in found.games if c.id != "194662")))
    assert gone.events == () and "194662" in gone.state.known
    assert run_check(gone.state, found).events == ()


def test_two_games_of_one_series_give_one_key():
    uncharted = snapshot("uncharted-4")
    lost = snapshot("lost-legacy")
    keys = []
    for found in (uncharted, lost):
        empty = replace(found, expansions=(), games=())
        keys += [e.dedup_key for e in run_check(run_check(NOT_CHECKED, empty).state, found).events]
    assert keys.count("game:follow_up:168668") == 2  # the queue keeps the first, its key drops the second


# --- the stored state --------------------------------------------------------------------------------------------------


def test_not_checked_is_stored_as_nothing():
    assert NOT_CHECKED.state() == {}
    assert FollowUps.from_state({}) == NOT_CHECKED and not NOT_CHECKED.checked


def test_the_state_survives_the_store():
    state = reference()
    stored = json.loads(json.dumps(state.state()))
    assert stored["known"] == ["12503", "13166", "19474", "194662", "220277", "403150", "415005"]
    assert FollowUps.from_state(stored) == state and state.checked


@pytest.mark.parametrize(
    "spoil",
    [
        lambda s: {**s, "known": "1"},
        lambda s: {k: v for k, v in s.items() if k != "known"},
        lambda s: {k: v for k, v in s.items() if k != "games"},
        lambda s: {**s, "own_date": "soon"},
        lambda s: {**s, "collections": [5]},
        lambda s: {**s, "known": [1942]},
        lambda s: {**s, "games": [{**s["games"][0], "standalone": "no"}]},
        lambda s: {**s, "games": [{**s["games"][0], "id": 1}]},
        lambda s: {**s, "games": [{k: v for k, v in s["games"][0].items() if k != "first"}]},
        lambda s: {**s, "expansions": [{**s["expansions"][0], "releases": [{"type": "soon"}]}]},
        lambda s: {**s, "expansions": None},
        lambda s: [s],
    ],
)
def test_a_spoiled_state_raises(spoil):
    with pytest.raises(ValueError):
        FollowUps.from_state(spoil(reference().state()))


# --- types and samples (6.1, 6.6) --------------------------------------------------------------------------------------


def test_the_types():
    assert (EXPANSION_ANNOUNCED, SEQUEL_ANNOUNCED) == ("game_expansion_announced", "game_sequel_announced")
    assert set(TYPES) == {EXPANSION_ANNOUNCED, SEQUEL_ANNOUNCED}


def test_the_samples_of_the_test_event():
    assert list(follow_ups.TEST_SAMPLES) == [
        (
            "game-expansion",
            "Игра: анонсировано дополнение",
            "🎮 Анонсировано дополнение: Ведьмак 3: Дикая Охота — Баллады прошлого\n"
            "Дополнение к игре «Ведьмак 3: Дикая охота»\nВыход: 2027",
        ),
        (
            "game-sequel",
            "Игра: новая игра серии",
            "🎮 Анонсирована новая игра серии: The Witcher IV\nПродолжение игры «Ведьмак 3: Дикая охота»\nВыход: 2028",
        ),
    ]
