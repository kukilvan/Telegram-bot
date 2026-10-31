"""Game events (spec 7 of part 6.1) and when a game is looked at again (spec 6.6): pure rules on made-up snapshots.

The core around them (adding, the marks, the polls, delivery) is in `test_tracker_games.py`.
"""

from datetime import date, datetime, timedelta

import pytest

from app.tracker import delivery, game_events, games
from app.tracker.dedup import moved_key
from app.tracker.games import GameDate, GameState, Release
from app.tracker.platforms import EUROPE, NORTH_AMERICA, WORLD, Platform

PC, PS4, PS5, SWITCH, SWITCH_2 = 6, 48, 167, 130, 508
TODAY = date(2026, 11, 10)
LOOK = datetime(2026, 11, 9, 12, 0)  # the previous look: yesterday
ALL = tuple(Platform)


def state(*releases, platforms=()):
    """Releases as (IGDB platform, kind, date text) or (…, region); the platforms of the records are the game's."""
    records = tuple(
        Release(platform=r[0], region=r[3] if len(r) > 3 else WORLD, type=r[1], date=GameDate.parse(r[2]))
        for r in releases
    )
    return GameState(platforms=tuple(sorted(set(platforms) | {r.platform for r in records})), releases=records)


def detect(old, new, told=ALL, look=LOOK, today=TODAY, country="il", name="Elden Ring"):
    return game_events.detect_events(1, name, old, new, country, told, look, today)


def texts(events):
    return [event.text for event in events]


# --- which events (7.1) and their texts (7.2) ------------------------------------------------------------------------


def test_a_full_release_on_its_day_says_the_game_is_out():
    [event] = detect(state((PC, "full", "2026-11-10")), state((PC, "full", "2026-11-10")))

    assert event.type == game_events.RELEASED
    assert event.text == "🎮 Elden Ring вышла на ПК"
    assert event.dedup_key == "game:1:pc:released"
    assert event.data == {"name": "Elden Ring", "platform": "pc", "via": "", "date": "2026-11-10"}


def test_a_release_by_the_older_console_names_both():
    old = new = state((PS4, "full", "2026-11-10"))

    [event] = detect(old, new, told=(Platform.PS5,), name="Bloodborne")

    assert event.text == "🎮 Bloodborne вышла на PS4 (идёт на PS5)"
    assert event.data["via"] == "PS4" and event.data["platform"] == "ps5"
    assert event.dedup_key == "game:1:ps5:released"


def test_an_early_access_on_its_day_says_so():
    [event] = detect(state((PC, "early", "2026-11-10")), state((PC, "early", "2026-11-10")), name="Hades II")

    assert event.type == game_events.EARLY_ACCESS
    assert event.text == "🎮 Hades II вышла в раннем доступе на ПК"
    assert event.dedup_key == "game:1:pc:early_access"
    assert event.data["date"] == "2026-11-10"


def test_an_early_access_on_the_day_of_the_full_release_is_only_the_release():
    both = state((PC, "early", "2026-11-10"), (PC, "full", "2026-11-10"))

    assert [e.type for e in detect(both, both)] == [game_events.RELEASED]


def test_an_early_access_after_the_full_release_says_nothing():
    old = state((PC, "full", "2026-10-01"))
    new = state((PC, "full", "2026-10-01"), (PC, "early", "2026-11-10"))

    assert detect(old, new) == []


def test_an_exact_day_after_an_approximate_date_is_announced():
    [event] = detect(state((PS5, "full", "2027")), state((PS5, "full", "2027-03-12")))

    assert event.type == game_events.DATE_ANNOUNCED
    assert event.text == "🎮 Elden Ring: на PS5 объявлена дата — 12 марта 2027"
    assert event.dedup_key == moved_key("game:1:ps5:date_announced:2027-03-12", LOOK)
    assert event.data == {"name": "Elden Ring", "platform": "ps5", "via": "", "date": "2027-03-12"}


@pytest.mark.parametrize("old", [state((PS5, "full", None)), state(platforms=(PS5,)), state()], ids=["tbd", "no-record", "new-platform"])
def test_an_exact_day_after_no_date_is_announced(old):
    assert texts(detect(old, state((PS5, "full", "2027-03-12")))) == [
        "🎮 Elden Ring: на PS5 объявлена дата — 12 марта 2027"
    ]


@pytest.mark.parametrize(
    "old, new, text",
    [
        ("2027-03-12", "2027-06-09", "🎮 Elden Ring: на PS5 дата перенесена — 12 марта → 9 июня 2027"),
        ("2026-12-15", "2027-01-22", "🎮 Elden Ring: на PS5 дата перенесена — 15 декабря 2026 → 22 января 2027"),
        ("2027-03-12", "2027", "🎮 Elden Ring: на PS5 дата перенесена — 12 марта 2027 → 2027"),
        ("2027-03-12", "2027-Q2", "🎮 Elden Ring: на PS5 дата перенесена — 12 марта 2027 → 2 квартал 2027"),
        ("2027-03-12", None, "🎮 Elden Ring: на PS5 дата перенесена — 12 марта 2027 → дата не объявлена"),
    ],
)
def test_a_move_of_an_exact_day_reads_by_what_it_moved_to(old, new, text):
    [event] = detect(state((PS5, "full", old)), state((PS5, "full", new)))

    assert event.type == game_events.DATE_MOVED
    assert event.text == text
    assert event.data == {"name": "Elden Ring", "platform": "ps5", "via": "", "old": old, "new": new}
    earlier = f"game:1:ps5:date_moved:{new or 'none'}"
    assert event.earlier_key == earlier and event.dedup_key == moved_key(earlier, LOOK)


def test_a_move_to_a_day_already_past_is_the_release():
    [event] = detect(state((PS5, "full", "2026-12-01")), state((PS5, "full", "2026-11-10")))

    assert event.type == game_events.RELEASED


@pytest.mark.parametrize("old, new", [("2026-Q4", "2027"), ("2027", "2027-05"), ("2027", None), (None, "2027")])
def test_an_approximate_date_changes_silently(old, new):
    assert detect(state((PS5, "full", old)), state((PS5, "full", new))) == []


def test_the_same_date_taken_from_the_older_console_now_is_silent():
    old = state((PS5, "full", "2027-03-12"))
    new = state((PS5, "full", "2027-03-12"), (PS4, "full", "2027-03-12"))

    assert detect(old, new, told=(Platform.PS5,)) == []


def test_a_day_of_release_up_to_30_days_old_is_news_and_an_older_one_a_correction():
    fresh = detect(state((PC, "full", "2026")), state((PC, "full", "2026-10-11")))
    old = detect(state((PC, "full", "2026")), state((PC, "full", "2026-10-10")))

    assert [e.type for e in fresh] == [game_events.RELEASED]
    assert old == []


def test_an_early_access_older_than_30_days_is_a_correction():
    assert detect(state((PC, "early", None)), state((PC, "early", "2026-10-10"))) == []


def test_a_game_added_on_its_day_of_release_says_nothing_at_the_first_check():
    added = state((PC, "full", "2026-11-10"))

    assert detect(added, added, look=datetime(2026, 11, 10, 8, 0)) == []


def test_a_cancelled_platform_says_nothing():
    old = state((PS5, "full", "2027-03-12"))
    new = state((PS5, "cancelled", None))

    assert detect(old, games.carry_over(old, new)) == []


def test_a_release_already_out_at_the_previous_look_is_not_news():
    out = state((PC, "full", "2026-11-05"))

    assert detect(out, out) == []


# --- whom it is told (6.4) -------------------------------------------------------------------------------------------


def test_only_the_platforms_told_about_get_events():
    old = state((PC, "full", "2026-11-12"), (PS5, "full", "2026-11-12"))
    new = state((PC, "full", "2026-11-10"), (PS5, "full", "2026-11-10"))

    assert [e.data["platform"] for e in detect(old, new, told=(Platform.PS5,))] == ["ps5"]
    assert detect(old, new, told=()) == []


def test_the_platforms_told_about_are_mine_with_the_mark_and_a_new_one_counts_as_marked():
    mine = (Platform.PC, Platform.PS5, Platform.SWITCH)

    assert game_events.reported(mine, {"pc": True, "ps5": False}) == (Platform.PC, Platform.SWITCH)
    assert game_events.reported((Platform.PC,), {"pc": True, "xbox_series": True}) == (Platform.PC,)


def test_switch_2_by_the_date_of_switch_is_told_by_switch_alone():
    old = state((SWITCH, "full", "2026-11-12"))
    new = state((SWITCH, "full", "2026-11-10"))

    both = detect(old, new, told=(Platform.SWITCH_2, Platform.SWITCH))
    alone = detect(old, new, told=(Platform.SWITCH_2,))

    assert texts(both) == ["🎮 Elden Ring вышла на Switch"]
    assert texts(alone) == ["🎮 Elden Ring вышла на Switch (идёт на Switch 2)"]


def test_the_dates_are_read_for_the_country_and_a_new_country_gives_nothing():
    regions = state(
        (PS5, "full", "2026-11-10", EUROPE), (PS5, "full", "2026-12-01", NORTH_AMERICA), platforms=(PS5,)
    )
    old = state((PS5, "full", "2026-11-12", EUROPE), (PS5, "full", "2026-12-01", NORTH_AMERICA))

    assert texts(detect(old, regions, country="il")) == ["🎮 Elden Ring вышла на PS5"]
    assert detect(old, regions, country="us") == []  # America's day did not change
    # the owner moved from the USA to Israel: nothing changed in IGDB, the European day is long out, the American ahead
    same = state((PS5, "full", "2026-11-01", EUROPE), (PS5, "full", "2026-12-01", NORTH_AMERICA))
    assert detect(same, same, country="il") == detect(same, same, country="us") == []


# --- keys (7.3) -------------------------------------------------------------------------------------------------------


def test_an_announcement_found_again_from_the_same_look_has_the_same_key_and_from_a_later_look_a_new_one():
    first = detect(state((PS5, "full", None)), state((PS5, "full", "2027-03-12")))
    again = detect(state((PS5, "full", None)), state((PS5, "full", "2027-03-12")))
    later = detect(state((PS5, "full", None)), state((PS5, "full", "2027-03-12")), look=LOOK + timedelta(hours=6))

    assert first[0].dedup_key == again[0].dedup_key != later[0].dedup_key


# --- folding (7.4) ----------------------------------------------------------------------------------------------------


def pending(event, number, title_id=1):
    payload = {"text": event.text, **event.data}
    return delivery.Pending(number, number, event.type, title_id, event.text, payload, LOOK)


def released_on(*platforms, title_id=1):
    old = state(*((p, "full", "2026-11-12") for p in platforms))
    new = state(*((p, "full", "2026-11-10") for p in platforms))
    return [pending(event, title_id * 10 + n, title_id) for n, event in enumerate(detect(old, new))]


def test_the_platforms_of_one_game_fold_into_one_line_with_the_buttons_of_the_first():
    queue = released_on(PS5, PC)

    [unit] = delivery.fold(queue, episodes=False)

    assert unit.text == "🎮 Elden Ring вышла на ПК и PS5"
    assert unit.members == tuple(queue) and unit.lead is queue[0]


def test_three_platforms_read_in_the_order_of_the_table_and_an_older_one_says_where_it_runs():
    old = state((PC, "full", "2026-11-12"), (PS4, "full", "2026-11-12"), (169, "full", "2026-11-12"))
    new = state((PC, "full", "2026-11-10"), (PS4, "full", "2026-11-10"), (169, "full", "2026-11-10"))
    queue = [pending(event, n) for n, event in enumerate(detect(old, new))]

    [unit] = delivery.fold(list(reversed(queue)), episodes=False)

    assert unit.text == "🎮 Elden Ring вышла на ПК, PS4 (идёт на PS5) и Xbox Series X|S"


def test_two_games_and_two_types_stay_apart():
    queue = released_on(PC, PS5) + released_on(PC, title_id=2)
    early = state((PS5, "early", "2026-11-12"))
    queue += [pending(e, 99) for e in detect(early, state((PS5, "early", "2026-11-10")))]

    units = delivery.fold(queue, episodes=False)

    assert [len(u.members) for u in units] == [2, 1, 1]


def test_announcements_of_different_days_do_not_fold_and_of_one_day_do():
    one = detect(state((PC, "full", "2027"), (PS5, "full", "2027")), state((PC, "full", "2027-03-12"), (PS5, "full", "2027-03-12")))
    two = detect(state((PC, "full", "2027"), (PS5, "full", "2027")), state((PC, "full", "2027-03-12"), (PS5, "full", "2027-04-01")))

    [folded] = delivery.fold([pending(e, n) for n, e in enumerate(one)], episodes=False)
    apart = delivery.fold([pending(e, n) for n, e in enumerate(two)], episodes=False)

    assert folded.text == "🎮 Elden Ring: на ПК и PS5 объявлена дата — 12 марта 2027"
    assert len(apart) == 2


def test_moves_fold_only_with_the_same_old_and_new_date():
    old = state((PC, "full", "2027-03-12"), (PS5, "full", "2027-03-12"), (SWITCH, "full", "2027-03-12"))
    new = state((PC, "full", "2027-06-09"), (PS5, "full", "2027-06-09"), (SWITCH, "full", "2027-07-01"))

    units = delivery.fold([pending(e, n) for n, e in enumerate(detect(old, new))], episodes=False)

    assert [u.text for u in units] == [
        "🎮 Elden Ring: на ПК и PS5 дата перенесена — 12 марта → 9 июня 2027",
        "🎮 Elden Ring: на Switch дата перенесена — 12 марта → 1 июля 2027",
    ]


def test_a_single_event_keeps_its_own_text_and_is_its_own_lead():
    [single] = released_on(PC)

    [unit] = delivery.fold([single], episodes=False)

    assert unit.text == single.text and unit.lead is single


# --- the samples (7.5) ------------------------------------------------------------------------------------------------


def test_there_are_four_samples_and_one_of_two_events_that_fold():
    assert [label for _, label, _ in game_events.TEST_SAMPLES] == [
        "Игра: объявлена дата", "Игра: дата перенесена", "Игра: вышла", "Игра: ранний доступ",
    ]
    events = game_events.sample_two_platforms_events()
    queue = [delivery.Pending(n, n, t, None, p["text"], p, LOOK) for n, (t, p) in enumerate(events)]

    [unit] = delivery.fold(queue, episodes=False)

    assert len(events) == 2 and unit.text == "🎮 Elden Ring вышла на ПК и PS5"


# --- when to look again (6.6) ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "game, interval",
    [
        (state((PC, "full", "2026-11-12")), timedelta(hours=1)),
        (state((PC, "full", "2026-11-24"), (PS5, "full", "2027")), timedelta(hours=6)),
        (state((PC, "early", "2026-11-11"), (PC, "full", None)), timedelta(hours=1)),
        (state((PC, "full", "2026-12-24")), timedelta(hours=24)),
        (state((PC, "full", "2026-Q4")), timedelta(hours=24)),
        (state((PC, "full", "2025-05-01"), (PS5, "full", None)), timedelta(hours=24)),
        (state((PC, "full", "2025-05-01"), (PS4, "full", "2025-06-01")), timedelta(days=7)),
        (state((PC, "cancelled", None), (PS5, "cancelled", None)), timedelta(days=7)),
        (state((PC, "full", "2025-05-01"), (PS5, "cancelled", None)), timedelta(days=7)),
    ],
    ids=["two-days", "fourteen-days", "early-soon", "far-day", "approximate", "one-not-announced", "all-out",
         "all-cancelled", "out-and-cancelled"],
)
def test_the_next_check_follows_the_nearest_date_of_every_platform(game, interval):
    assert games.check_interval(game, "il", TODAY) == interval
