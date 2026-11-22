"""Where the moment of an episode comes from (spec 1.1–1.4 of stage 9.1c; KI-28, KI-32): the adapters set the timing,
`assemble` and `keeping_known` keep a stored one, and the one rule of `cards.episode_when` reads a moment the same way
in the Feed, the cards and the bot messages, east and west of UTC. Pure functions; no database, no network."""

import asyncio
import json
import pathlib
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from anime_fakes import FakeShikimori, load

from app.tracker import anime_events, cards, feed_rows, series_events
from app.tracker.models import EpisodeTiming
from app.tracker.seasons import Episode, PartCut, Season, SeasonAnnouncement, SeasonProgress, AIRING, RELEASED
from app.tracker.sources.anilist_schedule import PartSchedule
from app.tracker.sources.shikimori_anime import SeasonPart, ShikimoriAnimeSource, SourceIds, parse_entry, part_episodes
from app.tracker.sources.tmdb_series import parse_show

EXACT, DAY, UNKNOWN = EpisodeTiming.EXACT, EpisodeTiming.DAY, EpisodeTiming.UNKNOWN
ISRAEL = ZoneInfo("Asia/Jerusalem")  # UTC+2 in November
WEST = timezone(timedelta(hours=-5))
NOW = datetime(2026, 10, 24, 12, 0)
TMDB = pathlib.Path(__file__).parent / "fixtures" / "tmdb"


def run(coro):
    return asyncio.run(coro)


def timings(season):
    return {e.number: e.timing for e in season.episodes}


# --- the adapters -------------------------------------------------------------------------------------------------


def test_every_dated_tmdb_episode_is_known_by_the_day():
    show = json.loads((TMDB / "tv_125988.json").read_text(encoding="utf-8"))
    details = {n: json.loads((TMDB / f"tv_125988_season_{n}.json").read_text(encoding="utf-8")) for n in (1, 2, 3, 4)}

    snapshot = parse_show(show, details)

    dated = [e for s in snapshot.seasons for e in s.episodes if e.air_at is not None]
    assert dated and {e.timing for e in dated} == {DAY}
    assert all(e.air_at.time() == time(0) for e in dated)


def franchise(fixture, start):
    return run(ShikimoriAnimeSource(FakeShikimori(fixture), None).snapshot(start))


def test_one_piece_the_first_episode_has_the_start_day_the_others_out_none_and_the_next_its_moment():
    [season] = franchise("one_piece.json", "21").seasons
    found = timings(season)

    assert found[1] == DAY
    assert {found[n] for n in range(2, 1181)} == {UNKNOWN}
    assert found[1181] == EXACT


def test_kusuriya_the_next_episode_is_exact_and_the_premiere_of_part_2_is_a_day():
    third = franchise("kusuriya.json", "54492").seasons[2]
    found = timings(third)

    assert (found[1], found[2], found[4], found[5]) == (DAY, UNKNOWN, UNKNOWN, EXACT)
    assert found[13] == DAY and third.parts()[1].first_episode() == Episode(13, datetime(2027, 4, 1), DAY)


def test_jujutsu_kaisen_seasons_out_in_full_have_the_start_day_once():
    seasons = franchise("jujutsu_kaisen.json", "40748").seasons
    first = timings(seasons[0])

    assert first[1] == DAY and {first[n] for n in range(2, 25)} == {UNKNOWN}
    assert seasons[3].episodes == ()  # announced with no day: no stub


def test_an_entry_known_only_by_the_day_it_ended_gives_no_episode_a_day():
    [raw] = [a for a in load("kusuriya.json") if a["id"] == "54492"]
    entry = replace(parse_entry(raw), aired_on=None)

    episodes = part_episodes(entry, 1)

    assert len(episodes) == 24 and {e.timing for e in episodes} == {UNKNOWN}


# --- AniList over Shikimori -------------------------------------------------------------------------------------

PART = SeasonPart(1, 1, 1, 12, SourceIds("100", "100", "200"), "ongoing")
START = datetime(2026, 10, 2)  # the start day Shikimori gives every episode out
AIRING_AT = datetime(2026, 10, 30, 14, 0)


def shikimori_episodes(out, next_at=None):
    episodes = {n: Episode(n, START, DAY if n == 1 else UNKNOWN) for n in range(1, out + 1)}
    if next_at is not None:
        episodes[out + 1] = Episode(out + 1, next_at, EXACT)
    return episodes


def test_anilist_with_an_airing_gives_the_next_episode_its_exact_moment_and_the_ones_out_shikimoris():
    schedule = PartSchedule("RELEASING", 4, 5, AIRING_AT)

    built = anime_events._scheduled(PART, schedule, shikimori_episodes(3), NOW)

    assert built == [
        Episode(1, START, DAY),
        Episode(2, START, UNKNOWN),
        Episode(3, START, UNKNOWN),
        Episode(4, NOW, UNKNOWN),  # Shikimori is behind: the moment of this look
        Episode(5, AIRING_AT, EXACT),
    ]


def test_anilist_without_an_airing_takes_shikimoris_moment_of_the_next_episode_with_its_timing():
    schedule = PartSchedule("RELEASING", 4, 5, None)

    built = anime_events._scheduled(PART, schedule, shikimori_episodes(4, next_at=AIRING_AT), NOW)

    assert built[-1] == Episode(5, AIRING_AT, EXACT)
    assert anime_events._scheduled(PART, schedule, shikimori_episodes(4), NOW)[-1] == Episode(5, None)


def season_of(episodes):
    return Season(1, "Сезон 1", 12, tuple(episodes[n] for n in sorted(episodes)), (PartCut(1, 12, "100"),), "100")


def assemble(fresh, stored, schedule=None, now=NOW, **rest):
    schedules = {"100": schedule} if schedule else {}
    [season] = anime_events.assemble(
        [season_of(fresh)], [PART], schedules, [season_of(stored)] if stored is not None else None, now, **rest
    )
    return {e.number: e for e in season.episodes}


def test_a_stored_moment_of_an_episode_out_stays_with_its_timing():
    stored = {**shikimori_episodes(3), 4: Episode(4, AIRING_AT, EXACT)}

    found = assemble(shikimori_episodes(4), stored, now=AIRING_AT + timedelta(hours=1))

    assert found[4] == Episode(4, AIRING_AT, EXACT)


def test_an_episode_found_now_keeps_a_moment_a_source_named_exactly():
    later = AIRING_AT + timedelta(minutes=37)
    fresh = {**shikimori_episodes(3), 4: Episode(4, AIRING_AT, EXACT)}  # a moment Shikimori named, already behind

    found = assemble(fresh, shikimori_episodes(3), now=later)  # AniList silent this time

    assert found[4] == Episode(4, AIRING_AT, EXACT)


def test_an_episode_found_now_with_no_moment_of_its_own_gets_the_moment_of_this_look_as_unknown():
    found = assemble(shikimori_episodes(4), shikimori_episodes(3))

    assert found[4] == Episode(4, NOW, UNKNOWN)
    assert found[1] == Episode(1, START, DAY)  # stored, and stays


def test_an_episode_of_a_new_entry_out_by_the_previous_look_keeps_its_own_day():
    found = assemble(shikimori_episodes(2), {}, new_entries={"100"}, observed_at=NOW - timedelta(hours=1))

    assert found[1] == Episode(1, START, DAY) and found[2] == Episode(2, START, UNKNOWN)


def test_a_stored_season_laid_over_a_fresh_chain_keeps_the_timing_of_its_episodes():
    stored = season_of({1: Episode(1, START, DAY), 2: Episode(2, AIRING_AT, EXACT)})

    layout = anime_events.relayout([stored], [PART])

    assert {e.number: e.timing for e in layout.seasons[0].episodes} == {1: DAY, 2: EXACT}


def test_a_series_answer_without_a_date_keeps_the_stored_episode_whole():
    old = series_events.ShowState((Season(1, "Сезон 1", 3, (Episode(1, AIRING_AT, EXACT), Episode(2, START, DAY))),))
    new = series_events.ShowState((Season(1, "Сезон 1", 3, (Episode(1, None), Episode(2, None), Episode(3, None))),))

    kept = new.keeping_known(old).seasons[0].episodes

    assert kept == (Episode(1, AIRING_AT, EXACT), Episode(2, START, DAY), Episode(3, None))


# --- how a moment reads: the one rule -------------------------------------------------------------------------------

MIDNIGHT = datetime(2026, 11, 25, 0, 0)


@pytest.mark.parametrize(
    "episode, tz, expected",
    [
        (Episode(4, MIDNIGHT, EXACT), ISRAEL, (date(2026, 11, 25), time(2, 0))),  # KI-28: a named moment at 00:00 UTC
        (Episode(4, MIDNIGHT, EXACT), WEST, (date(2026, 11, 24), time(19, 0))),
        (Episode(1, MIDNIGHT, DAY), ISRAEL, (date(2026, 11, 25), None)),
        (Episode(1, MIDNIGHT, DAY), WEST, (date(2026, 11, 25), None)),  # the source's date, not the day before
        (Episode(7, datetime(2026, 11, 25, 12, 42, 13), UNKNOWN), ISRAEL, (date(2026, 11, 25), None)),  # KI-32
        (Episode(7, datetime(2026, 11, 25, 2, 0), UNKNOWN), WEST, (date(2026, 11, 24), None)),
        (Episode(4, MIDNIGHT, EXACT), None, (date(2026, 11, 25), None)),  # a kind whose source gives the day
    ],
)
def test_the_feed_reads_a_moment_by_where_it_comes_from(episode, tz, expected):
    assert feed_rows.day_of(episode, tz) == expected


def progress(next_episode):
    return SeasonProgress(3, 3, 12, AIRING, next_episode)


@pytest.mark.parametrize(
    "episode, tz, expected",
    [
        (Episode(4, MIDNIGHT, EXACT), ISRAEL, "ср, 25 ноя в 02:00"),
        (Episode(4, MIDNIGHT, EXACT), WEST, "вт, 24 ноя в 19:00"),
        (Episode(4, MIDNIGHT, DAY), WEST, "ср, 25 ноя"),
        (Episode(4, datetime(2026, 11, 25, 14, 0), UNKNOWN), ISRAEL, "ср, 25 ноя"),
        (Episode(4, datetime(2026, 11, 25, 2, 0), UNKNOWN), WEST, "вт, 24 ноя"),
    ],
)
def test_the_card_names_the_hour_of_the_next_episode_only_for_an_exact_moment(episode, tz, expected):
    assert cards.progress_line(progress(episode), tz) == f"Сезон 3: вышло 3 из 12, следующая — {expected}"


@pytest.mark.parametrize(
    "episode, tz, expected",
    [
        (Episode(13, datetime(2027, 3, 27), DAY), WEST, "с 27 марта"),
        (Episode(13, datetime(2027, 3, 27), EXACT), WEST, "с 26 марта"),
        (Episode(13, datetime(2027, 3, 26, 23, 0), EXACT), ISRAEL, "с 27 марта"),
    ],
)
def test_the_part_line_reads_its_day_by_the_rule(episode, tz, expected):
    line = cards.progress_line(SeasonProgress(3, 12, 12, RELEASED, None, 1, 2, episode), tz)

    assert line == f"Сезон 3, часть 1: вышло 12 из 12; часть 2 — {expected}"


@pytest.mark.parametrize(
    "episode, tz, expected",
    [
        (Episode(1, datetime(2027, 1, 9), DAY), WEST, "премьера 9 января 2027"),
        (Episode(1, datetime(2027, 1, 9), DAY), ISRAEL, "премьера 9 января 2027"),
        (Episode(1, datetime(2027, 1, 9, 23, 0), EXACT), ISRAEL, "премьера 10 января 2027"),
        (None, ISRAEL, "дата не объявлена"),
    ],
)
def test_the_announced_line_reads_the_premiere_day_by_the_rule(episode, tz, expected):
    assert cards.announced_line(SeasonAnnouncement(4, episode), tz) == f"Сезон 4 анонсирован, {expected}"


def anime(tz):
    return anime_events.flavor(tz)


def test_the_next_line_of_a_message_has_the_hour_only_for_an_exact_moment():
    exact = Season(1, "Сезон 1", 12, (Episode(5, MIDNIGHT, EXACT),))
    known_by_day = Season(1, "Сезон 1", 12, (Episode(5, MIDNIGHT, DAY),))

    assert series_events._next_line(exact, NOW, anime(ISRAEL)) == "следующая: ср, 25 ноя в 02:00"
    assert series_events._next_line(known_by_day, NOW, anime(WEST)) == "следующая: ср, 25 ноя"
    assert series_events._next_line(known_by_day, NOW) == "следующая: ср, 25 ноя"  # a series, as before


def test_an_announced_premiere_known_by_the_day_keeps_its_date_west_of_utc_in_the_message():
    text = series_events.message_announced("Фрирен", 2, Episode(1, datetime(2027, 1, 9), DAY), flavor=anime(WEST))

    assert text.endswith("Премьера: 9 января 2027")


def test_a_moved_episode_reads_both_moments_by_their_timing():
    old, new = Episode(7, MIDNIGHT, DAY), Episode(7, datetime(2026, 11, 26, 14, 0), EXACT)

    text = series_events.message_moved("Фрирен", 2, 7, old, new, premiere=False, flavor=anime(ISRAEL))
    premiere = series_events.message_moved("Фрирен", 2, 1, old, new, premiere=True, flavor=anime(WEST))

    assert text.endswith("Сезон 2 · ср, 25 ноя → чт, 26 ноя в 16:00")
    assert premiere.endswith("25 ноя 2026 → 26 ноя 2026")


def test_the_end_of_a_part_names_the_day_of_the_next_part_by_the_rule():
    season = Season(
        3, "Сезон 3", 24,
        tuple(Episode(n, datetime(2026, 10, 5) + timedelta(weeks=n - 1), UNKNOWN) for n in range(1, 13))
        + (Episode(13, datetime(2027, 4, 1), DAY),),
        (PartCut(1, 12), PartCut(13, 12)),
    )
    first, second = season.parts()

    text = series_events.message_part_ended("Аниме", first, 12, second, anime(WEST))

    assert text.endswith("часть 2 — с 1 апреля")


# --- the examples of spec 1.4 ---------------------------------------------------------------------------------------


def test_example_anilist_names_an_episode_at_midnight_utc_for_an_owner_in_israel():
    episode = Episode(4, MIDNIGHT, EXACT)

    assert feed_rows.day_of(episode, ISRAEL) == (date(2026, 11, 25), time(2, 0))
    assert cards.progress_line(progress(episode), ISRAEL).endswith("следующая — ср, 25 ноя в 02:00")


def test_example_shikimori_alone_finds_episode_7_at_a_check():
    assert feed_rows.day_of(Episode(7, datetime(2026, 11, 22, 12, 42), UNKNOWN), ISRAEL) == (date(2026, 11, 22), None)


def test_example_shikimori_announces_an_entry_for_a_day():
    episode = Episode(1, datetime(2027, 1, 9), DAY)

    assert feed_rows.day_of(episode, ISRAEL) == (date(2027, 1, 9), None)
    assert cards.announced_line(SeasonAnnouncement(4, episode), ISRAEL) == "Сезон 4 анонсирован, премьера 9 января 2027"


def test_example_an_airing_found_by_a_later_check_keeps_its_hour():
    assert feed_rows.day_of(Episode(8, datetime(2026, 11, 22, 14, 0), EXACT), ISRAEL) == (date(2026, 11, 22), time(16, 0))


# --- the moves and the keys on old data -----------------------------------------------------------------------------


def test_the_key_of_a_move_keeps_its_midnight_rule():
    assert series_events._moment_key(datetime(2026, 11, 25)) == "2026-11-25"
    assert series_events._moment_key(datetime(2026, 11, 25, 14, 0)) == "2026-11-25T1400"


@pytest.mark.parametrize(
    "before, after, learned",
    [
        (Episode(5, MIDNIGHT, DAY), Episode(5, datetime(2026, 11, 25, 14, 0), EXACT), True),  # old data: midnight → day
        (Episode(5, MIDNIGHT, DAY), Episode(5, datetime(2026, 11, 26, 14, 0), EXACT), False),
        (Episode(5, datetime(2026, 11, 25, 9, 0), EXACT), Episode(5, datetime(2026, 11, 25, 14, 0), EXACT), False),
        (Episode(5, MIDNIGHT, EXACT), Episode(5, datetime(2026, 11, 25, 14, 0), EXACT), False),  # a named 00:00 moved
    ],
)
def test_only_a_day_only_date_given_its_hour_on_the_same_day_is_no_move(before, after, learned):
    assert series_events._only_the_hour_learned(before, after) is learned
