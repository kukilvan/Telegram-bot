"""Phase 7.5: pure tier function mapping an observed TMDb state to a re-check interval."""

DAILY = 86_400          # seconds; items with no release/season data yet are re-checked daily
WEEKLY = 604_800       # seconds; stable states (known date / fully-aired season) are re-checked weekly
JITTER_MAX_SECONDS = 300    # random +0..5 min added to a deadline so items are spread across the day
RATE_LIMIT_EXTRA_DELAY = 300  # extra seconds appended when an item's fetch hit HTTP 429 (move to next slot)


def tier_interval(state: dict | None, media_type: str) -> int:
    """Pure state -> re-check interval in seconds (no network, no clock).

    Tier rules (approved plan §15, phase 7.5; Phase 8: anime via TMDb; Phase 9: games via IGDB):
      movie/game: known digital release date -> WEEKLY (verify the date did not change);
                  no release information at all -> DAILY (wait for an announcement).
      tv/anime:   current season airing or waiting for a new-season announcement -> DAILY;
                  latest season fully aired with no next-season activity -> WEEKLY.
    """
    if not state:
        return DAILY  # nothing observed yet

    if media_type in ("tv", "anime"):
        total = int(state.get("total_episodes_current_season") or 0)
        aired = int(state.get("episodes_aired_current_season") or 0)
        season = state.get("latest_season")
        if season is not None and total > 0 and aired >= total:
            return WEEKLY
        return DAILY

    # movie (and any TMDb-based type handled like a film)
    release = state.get("digital_release")
    if release:
        return WEEKLY
    return DAILY


def due_sort_key(next_check_at):
    """Sort key for processing order: items without a deadline come first."""
    import datetime as _dt

    return next_check_at or _dt.datetime.min
