"""AniList adapter for anime: the saved real answer (tests/fixtures/anilist) turned into per-part schedules.

Only the turning of an answer into data is checked here; the events built on it are tested through the core
(`test_tracker_anime_events`). No network.
"""

import json
import pathlib
from datetime import datetime, timezone

import pytest

from app.providers.anilist import AniListProvider
from app.tracker.sources.anilist_schedule import RECENT_KEY, PartSchedule, parse_schedules

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "anilist"
KUSURIYA_3, KUSURIYA_3_PART_2, KUSURIYA_2, ONE_PIECE, JJK_4 = "195516", "200927", "176301", "21", "209895"


def saved():
    return json.loads((FIXTURES / "schedules.json").read_text(encoding="utf-8"))["data"]["Page"]["media"]


def test_a_running_season_has_the_episodes_out_and_the_moment_of_the_next_one():
    schedules = parse_schedules(saved())

    assert schedules[KUSURIYA_3] == PartSchedule("RELEASING", released=4, next_episode=5, next_at=datetime(2026, 10, 30, 14, 0))


def test_a_running_show_without_a_known_end_still_counts_what_is_out():
    one_piece = parse_schedules(saved())[ONE_PIECE]

    assert (one_piece.released, one_piece.next_episode) == (1180, 1181)


def test_a_finished_season_has_all_its_episodes_out_and_no_next_one():
    assert parse_schedules(saved())[KUSURIYA_2] == PartSchedule("FINISHED", released=24, next_episode=None, next_at=None)


def test_a_season_not_yet_released_has_nothing_out_even_without_a_date():
    schedules = parse_schedules(saved())

    assert schedules[KUSURIYA_3_PART_2] == PartSchedule("NOT_YET_RELEASED", released=0, next_episode=None, next_at=None)
    assert schedules[JJK_4].released == 0


def test_every_record_of_the_answer_is_there_by_its_anilist_id():
    assert sorted(parse_schedules(saved())) == sorted(str(m["id"]) for m in saved())


def test_a_running_show_that_says_nothing_about_its_episodes_is_not_a_schedule():
    raw = [{"id": 7, "status": "RELEASING", "episodes": 12, "nextAiringEpisode": None}]

    assert parse_schedules(raw)["7"].released is None  # a gap in the answer, not «nothing is out»


def test_a_finished_show_without_a_count_is_not_a_schedule_either():
    raw = [{"id": 7, "status": "FINISHED", "episodes": None, "nextAiringEpisode": None}]

    assert parse_schedules(raw)["7"].released is None


def test_a_next_episode_without_a_number_or_a_moment_is_ignored():
    raw = [
        {"id": 7, "status": "RELEASING", "episodes": 12, "nextAiringEpisode": {"episode": None, "airingAt": 1793368800}},
        {"id": 8, "status": "RELEASING", "episodes": 12, "nextAiringEpisode": {"episode": 3, "airingAt": None}},
    ]

    schedules = parse_schedules(raw)

    assert schedules["7"].released is None
    assert (schedules["8"].released, schedules["8"].next_at) == (2, None)  # episode 3 is next, its time unknown


def test_records_without_an_id_and_an_empty_answer_give_nothing():
    assert parse_schedules([{"status": "FINISHED", "episodes": 12}, {}]) == {}
    assert parse_schedules([]) == {}


# --- the airings of the last days (spec 1.5 of stage 9.1c) ---------------------------------------------------------


def saved_with_airings():
    """The records of the saved answer with the airings the client puts in them, as the real client does."""
    data = json.loads((FIXTURES / "schedules_recent.json").read_text(encoding="utf-8"))["data"]
    return AniListProvider._with_airings(data["Page"]["media"], data["recent"])


def record(airings, episodes=12, media_id=7):
    return {"id": media_id, "status": "RELEASING", "episodes": episodes, "nextAiringEpisode": None, RECENT_KEY: airings}


def test_the_saved_answer_gives_episode_8_of_kusuriya_its_airing_moment():
    schedules = parse_schedules(saved_with_airings())

    assert schedules[KUSURIYA_3].aired == {8: datetime(2026, 11, 20, 14, 0)}  # 1795183200
    assert 1795183200 == int(datetime(2026, 11, 20, 14, 0, tzinfo=timezone.utc).timestamp())
    assert all(s.aired == {} for i, s in schedules.items() if i != KUSURIYA_3)  # no data for the rest
    assert schedules[KUSURIYA_3].next_episode == 9  # the schedule itself is read as before


def test_the_client_and_the_adapter_name_the_airings_the_same_way():
    assert AniListProvider.RECENT_KEY == RECENT_KEY


def test_a_broken_airing_is_skipped_and_the_good_ones_stay():
    good = {"mediaId": 7, "episode": 3, "airingAt": 1795183200}
    broken = [
        {"episode": 4, "airingAt": 1795183200},  # no id
        {"mediaId": "7", "episode": 4, "airingAt": 1795183200},  # an id that is no number
        {"mediaId": True, "episode": 4, "airingAt": 1795183200},
        {"mediaId": 7, "airingAt": 1795183200},  # no episode
        {"mediaId": 7, "episode": 0, "airingAt": 1795183200},
        {"mediaId": 7, "episode": -2, "airingAt": 1795183200},
        {"mediaId": 7, "episode": "5", "airingAt": 1795183200},
        {"mediaId": 7, "episode": 2.0, "airingAt": 1795183200},
        {"mediaId": 7, "episode": 6},  # no moment
        {"mediaId": 7, "episode": 6, "airingAt": 1795183200.5},  # a moment that is no whole number
        {"mediaId": 7, "episode": 6, "airingAt": "1795183200"},
        {"mediaId": 7, "episode": 6, "airingAt": None},
        "garbage",
        None,
        [],
    ]

    assert parse_schedules([record([*broken, good])])["7"].aired == {3: datetime(2026, 11, 20, 14, 0)}


def test_an_airing_of_an_id_that_was_not_asked_is_skipped():
    other = {"mediaId": 8, "episode": 3, "airingAt": 1795183200}
    asked = {"mediaId": 7, "episode": 4, "airingAt": 1795183200}

    assert parse_schedules([record([other, asked])])["7"].aired == {4: datetime(2026, 11, 20, 14, 0)}


def test_the_client_gives_an_entry_only_the_airings_of_its_own_id():
    media = [{"id": 7, "status": "RELEASING"}, {"id": 8, "status": "RELEASING"}]
    nodes = [
        {"mediaId": 7, "episode": 1, "airingAt": 1},
        {"mediaId": 99, "episode": 1, "airingAt": 2},  # an id that was not asked: no record to go to
        {"mediaId": 8, "episode": 2, "airingAt": 3},
        {"mediaId": 7, "episode": 2, "airingAt": 4},
    ]

    records = AniListProvider._with_airings(media, {"airingSchedules": nodes})

    assert [r[RECENT_KEY] for r in records] == [[nodes[0], nodes[3]], [nodes[2]]]
    assert "recentAirings" not in media[0]  # the answer is not changed in place


def test_numbers_beyond_the_count_of_the_entry_are_dropped():
    airings = [{"mediaId": 7, "episode": n, "airingAt": 1795183200 + n} for n in (11, 12, 13)]

    assert sorted(parse_schedules([record(airings, episodes=12)])["7"].aired) == [11, 12]
    assert sorted(parse_schedules([record(airings, episodes=None)])["7"].aired) == [11, 12, 13]  # a count that is not known


@pytest.mark.parametrize("recent", [None, {}, {"airingSchedules": None}, {"airingSchedules": "x"}, [], "x", 5])
def test_an_answer_without_airings_or_with_a_broken_part_gives_every_part_no_airings(recent):
    media = [{"id": 7, "status": "RELEASING", "episodes": 12, "nextAiringEpisode": {"episode": 5, "airingAt": 1795183200}}]

    schedules = parse_schedules(AniListProvider._with_airings(media, recent))

    assert schedules["7"].aired == {}
    assert (schedules["7"].released, schedules["7"].next_episode) == (4, 5)  # the schedule is used as now


def test_a_record_with_a_broken_list_of_airings_has_none():
    for broken in (None, "x", {"episode": 1}, 5):
        assert parse_schedules([record(broken)])["7"].aired == {}
