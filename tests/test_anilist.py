"""Phase 8: AniList provider tests (pure logic, no network)."""

from datetime import datetime, timezone as _tz


def test_anilist_state_normalization():
    from app.scheduler.polling import _normalize_anilist_details
    from datetime import date

    # Normal airing anime
    details = {
        "title": {"romaji": "Shingeki no Kyojin", "english": "Attack on Titan"},
        "nextAiringEpisode": {
            "airingAt": 1760000000,
            "episode": 10,
        },
        "episodes": 12,
        "status": "RELEASING",
    }
    state = _normalize_anilist_details(details)
    assert state["next_episode_number"] == 10
    assert state["total_episodes"] == 12
    assert state["status"] == "RELEASING"
    assert state["next_episode_air_date"] is not None

    # Finished anime
    details_finished = {
        "title": {"romaji": "Steins;Gate"},
        "nextAiringEpisode": None,
        "episodes": 24,
        "status": "FINISHED",
    }
    state_finished = _normalize_anilist_details(details_finished)
    assert state_finished["next_episode_number"] is None
    assert state_finished["status"] == "FINISHED"

    # No next episode data
    details_no_ep = {
        "title": {"romaji": "Some Anime"},
        "nextAiringEpisode": None,
        "episodes": 0,
        "status": "NOT_YET_RELEASED",
    }
    state_no_ep = _normalize_anilist_details(details_no_ep)
    assert state_no_ep["next_episode_number"] is None


def test_compare_anilist_states_new_episode():
    from app.domain.events import compare_anilist_states, NEXT_EPISODE_AIRING

    old = {
        "next_episode_number": 5,
        "next_episode_air_date": "2026-10-01",
        "total_episodes": 12,
        "status": "RELEASING",
    }
    new = {
        "next_episode_number": 6,
        "next_episode_air_date": "2026-10-08",
        "total_episodes": 12,
        "status": "RELEASING",
    }
    events = compare_anilist_states(old, new)
    assert len(events) == 1
    assert events[0].event_type == NEXT_EPISODE_AIRING
    assert events[0].payload["episode"] == 6


def test_compare_anilist_states_no_change():
    from app.domain.events import compare_anilist_states

    state = {
        "next_episode_number": 5,
        "next_episode_air_date": "2026-10-01",
        "total_episodes": 12,
        "status": "RELEASING",
    }
    events = compare_anilist_states(state, state)
    assert events == []


def test_compare_anilist_states_finished():
    from app.domain.events import compare_anilist_states, ALL_EPISODES_OUT

    old = {
        "next_episode_number": 24,
        "next_episode_air_date": "2026-09-01",
        "total_episodes": 24,
        "status": "RELEASING",
    }
    new = {
        "next_episode_number": None,
        "next_episode_air_date": None,
        "total_episodes": 24,
        "status": "FINISHED",
    }
    events = compare_anilist_states(old, new)
    assert len(events) == 1
    assert events[0].event_type == ALL_EPISODES_OUT
    assert events[0].payload["total_episodes"] == 24


def test_compare_anilist_states_first_poll():
    from app.domain.events import compare_anilist_states

    old = {}
    new = {
        "next_episode_number": 5,
        "next_episode_air_date": "2026-10-01",
        "total_episodes": 12,
        "status": "RELEASING",
    }
    events = compare_anilist_states(old, new)
    assert events == []  # first poll: no event


if __name__ == "__main__":
    test_anilist_state_normalization()
    test_compare_anilist_states_new_episode()
    test_compare_anilist_states_no_change()
    test_compare_anilist_states_finished()
    test_compare_anilist_states_first_poll()
    print("anilist tests passed")
