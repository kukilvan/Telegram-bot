"""Two anime cases of stage 9.1d: an episode first seen after a bulk drop (KI-83, spec 5) and a premiere moved by hours
within its day (KI-84, spec 6). Pure rules: `anime_events.assemble`, `series_events.detect_events`, `series_moves`,
`series_messages.message_moved`."""

from datetime import datetime, timedelta, timezone

import pytest

from app.tracker import series_events, series_messages, series_moves
from app.tracker.anime_events import assemble, flavor
from app.tracker.models import EpisodeTiming
from app.tracker.seasons import Episode, PartCut, Season
from app.tracker.sources.anilist_schedule import PartSchedule
from app.tracker.sources.shikimori_chain import SeasonPart, SourceIds

EXACT, DAY, UNKNOWN = EpisodeTiming.EXACT, EpisodeTiming.DAY, EpisodeTiming.UNKNOWN
MOSCOW = timezone(timedelta(hours=3))
PART = SeasonPart(1, 1, 1, 12, SourceIds("100", "100", "200"), "ongoing")
CUTS = (PartCut(1, 12, "100"),)
START = datetime(2026, 10, 2)  # Shikimori's start day of every episode out
DROP = datetime(2026, 11, 20, 14, 0)  # episode 7 was expected then; 8 and 9 aired then too (the probe of the review)
LOOK_13, LOOK_14_30, LOOK_20 = datetime(2026, 11, 20, 13, 0), datetime(2026, 11, 20, 14, 30), datetime(2026, 11, 20, 20, 0)


def season(episodes):
    return Season(1, "Сезон 1", 12, tuple(episodes), CUTS, "100")


def shikimori(out):
    """What Shikimori alone says: `out` episodes out on the start day (the first one by the day, the rest unknown)."""
    return season(Episode(n, START, DAY if n == 1 else UNKNOWN) for n in range(1, out + 1))


# what was stored after the look of 14:30: six out, and episode 7 at 14:00 (AniList's next one at 13:00)
STORED = season([*shikimori(6).episodes, Episode(7, DROP, EXACT)])


def look_at_20(new_entries=(), previous=(STORED,)):
    schedule = PartSchedule("RELEASING", 9, 10, DROP + timedelta(weeks=1), aired={7: DROP, 8: DROP, 9: DROP})
    return assemble([shikimori(9)], [PART], {"100": schedule}, previous, LOOK_20, {"100"}, new_entries, LOOK_14_30)


def events(assembled, late=None):
    old = series_events.ShowState((STORED,))
    new = series_events.ShowState(assembled.seasons).keeping_known(old)
    late = assembled.late if late is None else late
    return series_events.detect_events(1, "Аниме", old, new, LOOK_14_30, LOOK_20, flavor=flavor(None), late=late)


def test_the_probe_case_reports_both_episodes_of_the_drop_at_their_airing():
    assembled = look_at_20()

    found = events(assembled)

    assert assembled.late == {(1, 8), (1, 9)}
    assert [(e.type, e.dedup_key, e.happened_at) for e in found] == [
        (series_events.EPISODE_OUT, "anime:1:src100:e8:out", DROP),
        (series_events.EPISODE_OUT, "anime:1:src100:e9:out", DROP),
    ]
    assert found[0].text.startswith("🎌 Аниме — вышла серия 8 из 12")


def test_without_the_late_episodes_the_drop_would_pass_in_silence():
    assert events(look_at_20(), late=frozenset()) == []


def test_the_past_of_an_entry_the_title_never_had_stays_silent():
    assert look_at_20(new_entries={"100"}).late == frozenset()


def test_adding_finds_nothing_late():
    assert look_at_20(previous=None).late == frozenset()


def test_an_episode_stored_with_no_moment_is_late_too():
    stored = season([*shikimori(7).episodes[:7], Episode(8, None)])
    schedule = PartSchedule("RELEASING", 8, 9, None, aired={8: DROP})

    assembled = assemble([shikimori(8)], [PART], {"100": schedule}, [stored], LOOK_20, {"100"}, (), LOOK_14_30)

    assert assembled.late == {(1, 8)}


def test_a_series_passes_nothing_and_a_backfill_stays_history():
    old = series_events.ShowState((season([Episode(1, datetime(2026, 11, 2), DAY)]),))
    new = series_events.ShowState((season([Episode(1, datetime(2026, 11, 2), DAY), Episode(2, datetime(2026, 11, 9), DAY)]),))

    assert series_events.detect_events(1, "Сериал", old, new, datetime(2026, 11, 20), datetime(2026, 11, 21)) == []


# --- KI-84 -----------------------------------------------------------------------------------------------------------


def premiere_move(old, new, tz=MOSCOW):
    return series_messages.message_moved("Магическая битва", 4, 1, old, new, premiere=True, flavor=flavor(tz))


def test_a_premiere_moved_within_its_day_shows_both_hours():
    text = premiere_move(Episode(1, datetime(2027, 1, 9, 15, 0), EXACT), Episode(1, datetime(2027, 1, 9, 16, 0), EXACT))

    assert text == "🎌 Магическая битва — премьера сезона 4 перенесена\n9 янв 2027, 18:00 → 9 янв 2027, 19:00"


def test_a_premiere_moved_by_minutes_shows_them_too():
    text = premiere_move(Episode(1, datetime(2027, 1, 9, 15, 0), EXACT), Episode(1, datetime(2027, 1, 9, 15, 30), EXACT))

    assert text.endswith("9 янв 2027, 18:00 → 9 янв 2027, 18:30")


def test_a_premiere_moved_to_another_day_keeps_the_days():
    text = premiere_move(Episode(1, datetime(2027, 1, 9, 15, 0), EXACT), Episode(1, datetime(2027, 1, 16, 15, 0), EXACT))

    assert text.endswith("\n9 янв 2027 → 16 янв 2027")


def ahead(episode):
    return season([Episode(1, START, DAY), episode])


@pytest.mark.parametrize(
    "before, after",
    [
        (Episode(2, datetime(2027, 1, 9), DAY), Episode(2, datetime(2027, 1, 9, 15, 0), EXACT)),  # the hour learned
        (Episode(2, datetime(2027, 1, 9, 15, 0), EXACT), Episode(2, datetime(2027, 1, 9), DAY)),  # fell back to the day
    ],
)
def test_the_same_day_with_and_without_an_hour_is_no_move_both_ways(before, after):
    observed_at = datetime(2026, 12, 1)

    assert series_moves.moved(ahead(before), ahead(after), observed_at, observed_at + timedelta(hours=1), flavor(MOSCOW)) is None


def test_a_moment_without_an_hour_on_the_same_day_is_none_too():
    before, after = Episode(2, datetime(2027, 1, 9), UNKNOWN), Episode(2, datetime(2027, 1, 9, 15, 0), EXACT)

    assert series_moves.same_day_one_without_hour(before, after, flavor(MOSCOW))
    assert not series_moves.same_day_one_without_hour(after, Episode(2, datetime(2027, 1, 9, 16, 0), EXACT), flavor(MOSCOW))


def test_an_hour_move_of_an_exact_premiere_is_still_a_move():
    before, after = Episode(2, datetime(2027, 1, 9, 15, 0), EXACT), Episode(2, datetime(2027, 1, 9, 16, 0), EXACT)
    observed_at = datetime(2026, 12, 1)

    assert series_moves.moved(ahead(before), ahead(after), observed_at, observed_at, flavor(MOSCOW)) == (2, before, after)
