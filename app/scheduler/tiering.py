"""Phase 7.5: pure tier function mapping an observed state to a re-check interval."""

from datetime import datetime, timezone

DAILY = 86_400          # seconds; items with no release/season data yet are re-checked daily
WEEKLY = 604_800       # seconds; stable states (known date / fully-aired season) are re-checked weekly
JITTER_MAX_SECONDS = 300    # random +0..5 min added to a deadline so items are spread across the day
RATE_LIMIT_EXTRA_DELAY = 300  # extra seconds appended when an item's fetch hit HTTP 429 (move to next slot)


def tier_interval(state: dict | None, media_type: str) -> int:
    """Pure state -> re-check interval in seconds (no network, no clock).

    Tier rules (approved plan §15, phase 7.5; Phase 8: anime via AniList; Phase 9: games via IGDB):
      movie/game: known digital release date -> WEEKLY (verify the date did not change);
                  no release information at all -> DAILY (wait for an announcement).
      tv:         current season airing or waiting for a new-season announcement -> DAILY;
                  latest season fully aired with no next-season activity -> WEEKLY.
      anime:      next episode in <24h -> 1h; season airing -> 6h; FINISHED/announced -> 24h.
    """
    if not state:
        return DAILY  # nothing observed yet

    if media_type == "anime":
        # AniList-specific tiering
        status = state.get("status", "")
        next_air_date = state.get("next_episode_air_date")
        next_ep = state.get("next_episode_number")
        total = state.get("total_episodes")
        
        # If series is finished
        if status == "FINISHED":
            return DAILY  # check for new season announcements
        
        # If there's a next episode
        if next_air_date and next_ep is not None:
            try:
                next_dt = datetime.fromisoformat(next_air_date)
                if next_dt.tzinfo is None:
                    next_dt = next_dt.replace(tzinfo=timezone.utc)
                hours_until = (next_dt - datetime.now(tz=timezone.utc)).total_seconds() / 3600
                
                if hours_until < 24:
                    return 3600  # 1 hour before episode
                else:
                    return 6 * 3600  # 6 hours for ongoing season
            except (ValueError, TypeError):
                pass
        
        # Default for airing series
        return 6 * 3600  # 6 hours
    
    if media_type == "tv":
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
