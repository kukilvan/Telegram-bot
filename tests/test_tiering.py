"""Phase 7.5: pure tier function (state -> interval) tests, no network."""

from datetime import datetime


def test_movie_with_known_date_is_weekly():
    from app.scheduler.tiering import DAILY, WEEKLY, tier_interval
    state = {"digital_release": "2031-05-05"}
    assert tier_interval(state, "movie") == WEEKLY, (
        "known digital release date -> verify weekly"
    )


def test_movie_without_any_info_is_daily():
    from app.scheduler.tiering import DAILY, tier_interval
    state = {"digital_release": None}
    assert tier_interval(state, "movie") == DAILY, (
        "no release info yet -> wait for an announcement daily"
    )


def test_empty_state_is_daily_for_every_type():
    from app.scheduler.tiering import DAILY, tier_interval
    assert tier_interval({}, "movie") == DAILY
    assert tier_interval({}, "tv") == DAILY
    assert tier_interval(None, "anime") == DAILY


def test_tv_fully_aired_season_is_weekly():
    from app.scheduler.tiering import WEEKLY, tier_interval
    state = {
        "latest_season": 1,
        "total_episodes_current_season": 3,
        "episodes_aired_current_season": 3,
    }
    assert tier_interval(state, "tv") == WEEKLY, (
        "fully aired season with no next activity -> weekly"
    )


def test_tv_airing_or_stubbed_announced_season_is_daily():
    from app.scheduler.tiering import DAILY, tier_interval

    airing = {
        "latest_season": 1,
        "total_episodes_current_season": 8,
        "episodes_aired_current_season": 5,
    }
    assert tier_interval(airing, "tv") == DAILY, (
        "mid-season episode stream -> daily"
    )

    stub = {  # announced season with placeholder episodes not yet aired
        "latest_season": 4,
        "total_episodes_current_season": 1,
        "episodes_aired_current_season": 0,
    }
    assert tier_interval(stub, "tv") == DAILY, (
        "waiting for a new season -> daily"
    )

    no_seasons = {
        "latest_season": None,
        "total_episodes_current_season": 0,
        "episodes_aired_current_season": 0,
    }
    assert tier_interval(no_seasons, "anime") == DAILY


def test_due_sort_key_puts_missing_deadlines_first():
    from app.scheduler.tiering import due_sort_key
    t = datetime(2026, 9, 15, 12, 0, 0)
    assert due_sort_key(None) < due_sort_key(t)


if __name__ == "__main__":
    # Run like the other no-network modules: python -m tests.test_tiering
    test_movie_with_known_date_is_weekly()
    test_movie_without_any_info_is_daily()
    test_empty_state_is_daily_for_every_type()
    test_tv_fully_aired_season_is_weekly()
    test_tv_airing_or_stubbed_announced_season_is_daily()
    test_due_sort_key_puts_missing_deadlines_first()
    print("tiering tests passed")
