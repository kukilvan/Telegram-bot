"""AniList adapter for anime: the saved real answer (tests/fixtures/anilist) turned into per-part schedules.

Only the turning of an answer into data is checked here; the events built on it are tested through the core
(`test_tracker_anime_events`). No network.
"""

import json
import pathlib
from datetime import datetime

from app.tracker.sources.anilist_schedule import PartSchedule, parse_schedules

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
