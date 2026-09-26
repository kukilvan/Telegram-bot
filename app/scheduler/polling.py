"""Adaptive polling cycle: fetch → compare → dedup → send.

Phase 7.5: the full-every-600s cycle was replaced by a due-item scan — each item
keeps its own re-check deadline (source_states.next_check_at), tiers are computed
from the observed state, and TMDb calls are staggered/capped inside TMDbProvider.
"""

import json as _json
import random
from dataclasses import replace as _replace
from datetime import date, datetime, timedelta, timezone as _tz

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.database.models import ExternalId, GamePlatform, MediaItem, SourceState, UserWatchItem
from app.domain.events import compare_anilist_states, compare_igdb_states, compare_steam_states, compare_states
from app.services.notifications import get_enabled_rules, has_been_sent, mark_sent

# Primary source for each media type (determines which SourceState to use for scheduling)
PRIMARY_SOURCE = {"movie": "tmdb", "tv": "tmdb", "anime": "anilist", "game": "igdb"}


def _load_state(session: Session, media_item_id: str, source_name: str) -> dict | None:
    """Load the last stored normalized state for (item, source)."""
    row = session.execute(
        select(SourceState).where(
            (SourceState.media_item_id == media_item_id) &
            (SourceState.source_name == source_name)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    try:
        return _json.loads(row.state_data or "{}")
    except ValueError:
        return {}


def _store_state(session: Session, media_item_id: str, source_name: str, state: dict) -> None:
    """Store the current normalized state for (item, source)."""
    row = session.execute(
        select(SourceState).where(
            (SourceState.media_item_id == media_item_id) &
            (SourceState.source_name == source_name)
        )
    ).scalar_one_or_none()
    if row is None:
        row = SourceState(media_item_id=media_item_id, source_name=source_name, state_data=_json.dumps(state))
        session.add(row)
    else:
        row.state_data = _json.dumps(state)
        row.observed_at = datetime.now(tz=_tz.utc)  # keep the "last observed" moment fresh
    session.commit()


# TMDb movie release_dates `type` codes (official):
#   1=Premiere, 2=Theatrical(limited), 3=Theatrical, 4=Digital, 5=Physical, 6=TV
_DIGITAL_RELEASE_TYPE = 4
_THEATRICAL_RELEASE_TYPE = 3
_LIMITED_THEATRICAL_RELEASE_TYPE = 2


def _earliest_digital_date(regions: list[dict]) -> str | None:
    """Return the earliest 'Digital' (type 4) release date across regions.

    TMDb /movie/{id}/release_dates returns a nested per-region structure; each
    region has `release_dates` entries with integer `type` codes and an ISO
    datetime string in `release_date`. We pick the min Digital date.
    """
    digital = [
        rd.get("release_date")[:10]
        for r in regions or []
        for rd in (r.get("release_dates") or [])
        if rd.get("type") == _DIGITAL_RELEASE_TYPE and rd.get("release_date")
    ]
    return min(digital) if digital else None


def _earliest_theatrical_date(regions: list[dict]) -> str | None:
    """Return the earliest 'Theatrical' (type 3 or 6) release date across regions."""
    theatrical = [
        rd.get("release_date")[:10]
        for r in regions or []
        for rd in (r.get("release_dates") or [])
        if rd.get("type") in (_THEATRICAL_RELEASE_TYPE, _LIMITED_THEATRICAL_RELEASE_TYPE) and rd.get("release_date")
    ]
    return min(theatrical) if theatrical else None


def _tv_state_from_seasons(seasons: list[dict], today: str) -> dict:
    """Normalize a TMDb seasons array into TV tracking state (pure, no network).

    Fields: latest_season, total_episodes_current_season,
    episodes_aired_current_season.

    An episode counts as aired only if its air_date is not null AND on or before
    `today`. Scheduled FUTURE air dates do NOT count — otherwise an announced
    season with placeholder/future-dated episodes would be reported as fully
    out (verified live: Silo S4 = 1 placeholder ep dated 2027-07-08; Fonari
    S1 = 5 aired + 3 future as of 2026-09-15).
    """
    if not seasons:
        return {
            "latest_season": None,
            "total_episodes_current_season": 0,
            "episodes_aired_current_season": 0,
        }
    latest = max(s.get("season_number") or 1 for s in seasons)
    current = [s for s in seasons if (s.get("season_number") or 1) == latest]
    episodes = current[0].get("episodes") or []
    total = len(episodes)
    aired = 0
    for ep in episodes:
        ad = (ep.get("air_date") or "")[:10]
        if ad and ad <= today:
            aired += 1
    return {
        "latest_season": latest,
        "total_episodes_current_season": total,
        "episodes_aired_current_season": aired,
    }


async def _fetch_tmdb_state(session: Session, provider, item: MediaItem) -> dict:
    """Fetch current normalized TMDb state for a movie/TV item (Phases 6-7).

    Movies use /movie/{id}/release_dates to pick the earliest 'Digital' release
    date; TV items normalize the seasons array into latest_season + episode
    counts. Returns {} when the item has no TMDb external id or details are
    missing.
    """
    ext = session.execute(
        select(ExternalId).where(
            (ExternalId.source == "tmdb") &
            (ExternalId.media_item_id == item.id)
        )
    ).scalar_one_or_none()
    if ext is None:
        return {}
    if item.media_type in ("tv", "anime"):
        # TMDb show-level endpoint returns season metadata only (episode_count),
        # NOT the episodes array — verified live. Episode air dates come from
        # GET /tv/{id}/season/{latest}; _tv_state_from_seasons normalizes them.
        tv_id = int(ext.external_id)
        seasons = await provider.get_tv_seasons(tv_id)
        latest = max((s.get("season_number") or 1) for s in seasons) if seasons else None
        episodes = (
            await provider.get_tv_season_episodes(tv_id, latest)
            if latest is not None
            else []
        )
        return _tv_state_from_seasons(
            [{"season_number": latest, "episodes": episodes}]
            if latest is not None
            else [],
            today=date.today().isoformat(),
        )
    release_dates = await provider.get_movie_release_dates(int(ext.external_id))
    return {
        "theatrical_release_date": _earliest_theatrical_date(release_dates),
        "digital_release": _earliest_digital_date(release_dates),
    }


async def _fetch_anilist_state(session: Session, provider, item: MediaItem) -> dict:
    """Fetch current normalized AniList state for an anime item (Phase 8).

    Returns a dict with:
      next_episode_number: int | None
      next_episode_air_date: str | None  (ISO 'YYYY-MM-DD')
      total_episodes: int
      status: str (RELEASING / FINISHED / etc.)
    """
    ext = session.execute(
        select(ExternalId).where(
            (ExternalId.source == "anilist") &
            (ExternalId.media_item_id == item.id)
        )
    ).scalars().first()
    if ext is None:
        return {}
    anilist_id = int(ext.external_id)
    details = await provider.get_anime_details(anilist_id)
    if details is None:
        return {}
    return _normalize_anilist_details(details)


def _normalize_anilist_details(details: dict) -> dict:
    """Normalize an AniList Media object into tracking state (pure, no network)."""
    next_ep = details.get("nextAiringEpisode")
    next_episode_number = next_ep.get("episode") if next_ep else None
    next_episode_air_at = next_ep.get("airingAt") if next_ep else None
    next_episode_air_date = (
        datetime.fromtimestamp(next_episode_air_at, tz=_tz.utc).date().isoformat()
        if next_episode_air_at else None
    )

    return {
        "next_episode_number": next_episode_number,
        "next_episode_air_date": next_episode_air_date,
        "total_episodes": details.get("episodes") or 0,
        "status": details.get("status") or "",
    }


def _normalize_igdb_details(details: dict) -> dict:
    """Normalize an IGDB game object into tracking state (pure, no network)."""
    release_dates = details.get("release_dates") or []
    # Find the earliest release date
    earliest = None
    release_status = None
    for rd in release_dates:
        date_str = rd.get("date")
        if date_str:
            if isinstance(date_str, (int, float)):
                date_str = datetime.fromtimestamp(date_str, tz=_tz.utc).date().isoformat()
            elif isinstance(date_str, str):
                date_str = date_str[:10]
            if earliest is None or date_str < earliest:
                earliest = date_str
        status = rd.get("status")
        if status == 2:  # Released
            release_status = "Released"
        elif status == 3 and release_status != "Released":  # Coming Soon
            release_status = "Coming Soon"
    # Check first_release_date field as fallback
    frd = details.get("first_release_date")
    if frd:
        if isinstance(frd, (int, float)):
            frd = datetime.fromtimestamp(frd, tz=_tz.utc).date().isoformat()
        elif isinstance(frd, str):
            frd = frd[:10]
        if earliest is None or frd < earliest:
            earliest = frd
    return {
        "igdb_digital_release": earliest,
        "release_status": release_status,
    }


async def _fetch_igdb_state(session: Session, provider, item: MediaItem) -> dict:
    """Fetch current normalized IGDB state for a game item (Phase 9)."""
    ext = session.execute(
        select(ExternalId).where(
            (ExternalId.source == "igdb") &
            (ExternalId.media_item_id == item.id)
        )
    ).scalar_one_or_none()
    if ext is None:
        return {}
    igdb_id = int(ext.external_id)
    details = await provider.get_game_details(igdb_id)
    if details is None:
        return {}
    return _normalize_igdb_details(details)


async def _fetch_steam_state(session: Session, provider, item: MediaItem) -> dict:
    """Fetch current normalized Steam state for a game item (Phase 10)."""
    ext = session.execute(
        select(ExternalId).where(
            (ExternalId.source == "steam") &
            (ExternalId.media_item_id == item.id)
        )
    ).scalar_one_or_none()
    if ext is None:
        return {}
    steam_id = int(ext.external_id)
    details = await provider.get_game_details(steam_id)
    if details is None:
        return {}
    return _normalize_steam_details(details)


def _normalize_steam_details(details: dict) -> dict:
    """Normalize Steam game details for state comparison (Phase 10)."""
    release_date = details.get("release_date", {}).get("date") or ""
    coming_soon = details.get("release_date", {}).get("coming_soon")
    steam_date = None
    if release_date and not coming_soon:
        # Convert "25 Sep, 2023" or "May 4, 2023" to ISO format "2023-05-04"
        from datetime import datetime as _dt
        try:
            parsed = _dt.strptime(release_date, "%d %b, %Y")
            steam_date = parsed.strftime("%Y-%m-%d")
        except ValueError:
            try:
                parsed = _dt.strptime(release_date, "%b %d, %Y")
                steam_date = parsed.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass
    return {
        "steam_release_date": steam_date,
        "store_page": True,
    }


async def _fetch_psn_state(session: Session, provider, item: MediaItem) -> dict:
    """Fetch current normalized PSN state for a game item (Phase 11)."""
    ext = session.execute(
        select(ExternalId).where(
            (ExternalId.source == "psn") &
            (ExternalId.media_item_id == item.id)
        )
    ).scalar_one_or_none()
    if ext is None:
        return {}
    psn_id = int(ext.external_id)
    details = await provider.get_game_details(psn_id)
    if details is None:
        return {}
    return _normalize_psn_details(details)


def _normalize_psn_details(details: dict) -> dict:
    """Normalize PSN game details for state comparison (Phase 11)."""
    release_date = details.get("release_date") or ""
    psn_date = None
    if release_date:
        try:
            psn_date = str(release_date)[:10]
        except (ValueError, TypeError):
            pass
    return {
        "psn_release_date": psn_date,
        "store_page": True,
    }


async def _fetch_game_platform_state(session: Session, provider, platform: str, platform_id: str) -> dict:
    """Fetch current normalized state for a GamePlatform entry.

    Uses the provider's get_game_details with the platform-specific ID.
    """
    try:
        pid = int(platform_id)
    except (ValueError, TypeError):
        return {}

    if platform == "igdb":
        details = await provider.get_game_details(pid)
        if details is None:
            return {}
        return _normalize_igdb_details(details)
    elif platform == "steam":
        details = await provider.get_game_details(pid)
        if details is None:
            return {}
        return _normalize_steam_details(details)
    elif platform == "psn":
        details = await provider.get_game_details(pid)
        if details is None:
            return {}
        return _normalize_psn_details(details)
    return {}


async def _refresh_anime_season(session: Session, shikimori_provider, anilist_provider, item: MediaItem, franchise_key: str) -> list:
    """Refresh anime season info from Shikimori and AniList.
    
    Runs only if needed (every 12-24 hours) to avoid rate limits.
    Returns events if season changed or new season announced.
    """
    if not shikimori_provider or not anilist_provider:
        return []
    
    # Check if refresh is needed
    shiki_state = _load_state(session, item.id, "shikimori")
    if shiki_state:
        synced_at = shiki_state.get("synced_at")
        if synced_at:
            synced_dt = datetime.fromisoformat(synced_at.replace("Z", "+00:00")) if "Z" in synced_at else datetime.fromisoformat(str(synced_at))
            from datetime import timezone as tz
            if synced_dt.tzinfo is None:
                synced_dt = synced_dt.replace(tzinfo=tz.utc)
            hours_since_sync = (datetime.now(tz=tz.utc) - synced_dt).total_seconds() / 3600
            
            # Refresh every 24 hours, or every 12 hours if status is FINISHED
            current_status = shiki_state.get("current_status", "")
            if current_status == "released" and hours_since_sync < 12:
                return []
            elif hours_since_sync < 24:
                return []
    
    # Build franchise summary
    summary = await shikimori_provider.build_franchise_summary(franchise_key)
    if not summary:
        return []
    
    current = summary.current
    old_shiki_state = shiki_state or {}
    old_shiki_id = old_shiki_state.get("current_shiki_id")
    
    events = []
    
    # Check if season changed
    if old_shiki_id and str(current.get("id")) != str(old_shiki_id):
        # Season changed - get AniList data for new season
        mal_id = current.get("malId")
        if mal_id:
            anilist_details = await anilist_provider.get_anime_by_mal(int(mal_id))
            if anilist_details:
                # Update ExternalIds
                existing_shiki = session.query(ExternalId).filter(
                    ExternalId.media_item_id == item.id,
                    ExternalId.source == "shikimori",
                ).first()
                if existing_shiki:
                    existing_shiki.external_id = str(current.get("id"))
                else:
                    session.add(ExternalId(media_item_id=item.id, source="shikimori", external_id=str(current.get("id"))))
                
                existing_anilist = session.query(ExternalId).filter(
                    ExternalId.media_item_id == item.id,
                    ExternalId.source == "anilist",
                ).first()
                if existing_anilist:
                    existing_anilist.external_id = str(anilist_details["id"])
                else:
                    session.add(ExternalId(media_item_id=item.id, source="anilist", external_id=str(anilist_details["id"])))
                
                session.commit()
                
                # Create event for new season
                event_type = "NEW_SEASON_STARTED" if current.get("status") == "ongoing" else "NEW_SEASON_ANNOUNCED"
                events.append(DomainEvent(
                    event_type=event_type,
                    source="shikimori",
                    payload={
                        "season_index": summary.current_index,
                        "shiki_id": current.get("id"),
                        "status": current.get("status"),
                    },
                ))
    
    # Save Shikimori state
    new_shiki_state = {
        "franchise_key": franchise_key,
        "current_shiki_id": current.get("id"),
        "current_mal_id": current.get("malId"),
        "anilist_id": None,  # Will be updated when we get AniList data
        "season_index": summary.current_index,
        "total_seasons": summary.total_seasons,
        "current_status": current.get("status"),
        "synced_at": datetime.now(tz=_tz.utc).isoformat(),
    }
    _store_state(session, item.id, "shikimori", new_shiki_state)
    
    return events


from app.domain.events import DomainEvent


async def poll_item(session: Session, tmdb_provider, anilist_provider, item: MediaItem, user_id: int, igdb_provider=None):
    """Run one polling cycle for a watch item.

    Fetches the current normalized state from the provider(s), compares it with
    the last stored source_state, and for each detected event checks dedup +
    enabled rule before marking it sent. Returns events that passed both gates;
    the caller sends the returned Telegram messages.

    Anime items are polled from BOTH TMDb and AniList (two independent sources).
    Game items are polled from IGDB.
    """
    to_send = []

    # TMDb poll (movies, TV, anime)
    state = await _fetch_tmdb_state(session, tmdb_provider, item)
    old = _load_state(session, item.id, "tmdb")
    if old is not None:
        for ev in compare_states(old, state):
            ev = _replace(ev, media_item_id=item.id)
            fp = ev.fingerprint()
            if has_been_sent(session, fp):
                continue
            enabled_rules = get_enabled_rules(session, user_id, item.id)
            if not any(r.event_type == ev.event_type for r in enabled_rules):
                continue
            mark_sent(session, fp, item.id)
            to_send.append(ev)
        _store_state(session, item.id, "tmdb", state)
    else:
        if state:
            _store_state(session, item.id, "tmdb", state)

    # AniList poll (anime only)
    if item.media_type == "anime" and anilist_provider is not None:
        anilist_state = await _fetch_anilist_state(session, anilist_provider, item)
        old_al = _load_state(session, item.id, "anilist")
        if old_al is not None:
            for ev in compare_anilist_states(old_al, anilist_state):
                ev = _replace(ev, media_item_id=item.id)
                fp = ev.fingerprint()
                if has_been_sent(session, fp):
                    continue
                enabled_rules = get_enabled_rules(session, user_id, item.id)
                if not any(r.event_type == ev.event_type for r in enabled_rules):
                    continue
                mark_sent(session, fp, item.id)
                to_send.append(ev)
            _store_state(session, item.id, "anilist", anilist_state)
        else:
            if anilist_state:
                _store_state(session, item.id, "anilist", anilist_state)

    # Game platform poll (games only) — uses GamePlatform table
    if item.media_type == "game" and igdb_provider is not None:
        # Get tracked platforms from watch item
        w = session.query(UserWatchItem).filter(
            UserWatchItem.user_id == user_id,
            UserWatchItem.media_item_id == item.id,
        ).first()
        tracked = _json.loads(w.tracked_platforms) if w and w.tracked_platforms else []
        if tracked:
            # Get GamePlatform records for tracked platforms
            platforms = session.query(GamePlatform).filter(
                GamePlatform.media_item_id == item.id,
                GamePlatform.platform.in_(tracked),
            ).all()
            for gp in platforms:
                state = await _fetch_game_platform_state(session, igdb_provider, gp.platform, gp.platform_id)
                old = _load_state(session, item.id, f"gp_{gp.platform}")
                if old is not None:
                    # Determine which compare function to use
                    if gp.platform == "igdb":
                        compare_fn = compare_igdb_states
                    elif gp.platform == "steam":
                        compare_fn = compare_steam_states
                    elif gp.platform == "psn":
                        compare_fn = compare_steam_states  # PSN uses same comparison
                    else:
                        compare_fn = compare_states

                    for ev in compare_fn(old, state):
                        ev = _replace(ev, media_item_id=item.id)
                        fp = ev.fingerprint()
                        if has_been_sent(session, fp):
                            continue
                        enabled_rules = get_enabled_rules(session, user_id, item.id)
                        if not any(r.event_type == ev.event_type for r in enabled_rules):
                            continue
                        mark_sent(session, fp, item.id)
                        to_send.append(ev)
                    _store_state(session, item.id, f"gp_{gp.platform}", state)
                else:
                    if state:
                        _store_state(session, item.id, f"gp_{gp.platform}", state)

    return to_send


def _get_primary_source(item: MediaItem) -> str:
    """Get the primary source name for a media item."""
    return PRIMARY_SOURCE.get(item.media_type, "tmdb")


def _due_rows_query(session):
    """All watch rows joined with their primary source-state row (outer join).

    A watch row without any stored state yet is due immediately (it still needs a baseline fetch).
    """
    # We need to join on the correct source based on media_type
    # Since we can't use a dynamic value in the join condition directly, we'll handle this in poll_due_items
    return (
        select(UserWatchItem, MediaItem)
        .join(MediaItem, UserWatchItem.media_item_id == MediaItem.id)
    )


async def poll_due_items(session: Session, tmdb_provider, anilist_provider=None, igdb_provider=None, shikimori_provider=None, now=None) -> list[tuple[int, MediaItem, list]]:
    """Process only watch items whose tier deadline has arrived (Phase 7.5).

    Staggering happens inside TMDbProvider (~1.5 s between calls + per-minute cap), so even many due items are never fired as a burst.
    Each processed item gets a fresh deadline: now + tier_interval(new state) + up to JITTER_MAX_SECONDS of spread, plus RATE_LIMIT_EXTRA_DELAY if the fetch hit HTTP 429 (the item moves to its next slot).

    Returns (user_id, MediaItem, events) per processed item so callers can send notifications. Timestamps are stored/compared as naive-UTC for safe SQLite comparison.
    """
    from app.scheduler.tiering import (
        JITTER_MAX_SECONDS,
        RATE_LIMIT_EXTRA_DELAY,
        due_sort_key,
        tier_interval,
    )

    now = now or datetime.now(tz=_tz.utc).replace(tzinfo=None)
    rows = session.execute(_due_rows_query(session)).all()
    
    results = []
    for w, item in rows:
        primary_source = _get_primary_source(item)
        st_row = session.execute(
            select(SourceState).where(
                (SourceState.media_item_id == item.id)
                &
                (SourceState.source_name == primary_source)
            )
        ).scalar_one_or_none()
        st = _json.loads(st_row.state_data) if st_row and st_row.state_data else None
        
        # Skip if not due
        if st_row and st_row.next_check_at and st_row.next_check_at > now:
            continue
            
        # For anime with shikimori_franchise, disable TMDb poll
        if item.media_type == "anime":
            shiki_franchise_ext = session.query(ExternalId).filter(
                ExternalId.media_item_id == item.id,
                ExternalId.source == "shikimori_franchise",
            ).first()
            if shiki_franchise_ext:
                # Run anime-specific refresh before polling
                events = await _refresh_anime_season(session, shikimori_provider, anilist_provider, item, shiki_franchise_ext.external_id)
                if events:
                    # Process events
                    for ev in events:
                        ev = _replace(ev, media_item_id=item.id)
                        fp = ev.fingerprint()
                        if has_been_sent(session, fp):
                            continue
                        enabled_rules = get_enabled_rules(session, w.user_id, item.id)
                        if not any(r.event_type == ev.event_type for r in enabled_rules):
                            continue
                        mark_sent(session, fp, item.id)
                        results.append((w.user_id, item, [ev]))
                # Skip TMDb poll for anime franchises
                state = {}
                old = _load_state(session, item.id, "tmdb")
                if old is not None:
                    _store_state(session, item.id, "tmdb", state)
            else:
                # No shikimori_franchise, run normal poll
                events = await poll_item(session, tmdb_provider, anilist_provider, item, user_id=w.user_id, igdb_provider=igdb_provider)
                state_now = _load_state(session, item.id, primary_source) or {}
                interval = tier_interval(state_now, item.media_type)
                jitter = random.uniform(0.0, JITTER_MAX_SECONDS)
                extra = RATE_LIMIT_EXTRA_DELAY if (getattr(tmdb_provider, "hit_429", False) or getattr(anilist_provider, "hit_429", False)) else 0.0
                deadline = now + timedelta(seconds=interval + jitter + extra)
                st_row = session.execute(
                    select(SourceState).where(
                        (SourceState.media_item_id == item.id)
                        &
                        (SourceState.source_name == primary_source)
                    )
                ).scalar_one_or_none()
                if st_row is not None:
                    st_row.next_check_at = deadline
                    session.commit()
                results.append((w.user_id, item, events))
                continue
        
        # Normal poll for non-anime
        events = await poll_item(session, tmdb_provider, anilist_provider, item, user_id=w.user_id, igdb_provider=igdb_provider)
        state_now = _load_state(session, item.id, primary_source) or {}
        # For games, check game platform states for tier calculation
        if item.media_type == "game" and not state_now:
            for gp_platform in ["igdb", "steam", "psn"]:
                gp_state = _load_state(session, item.id, f"gp_{gp_platform}")
                if gp_state:
                    state_now = gp_state
                    break
        interval = tier_interval(state_now, item.media_type)
        jitter = random.uniform(0.0, JITTER_MAX_SECONDS)
        extra = RATE_LIMIT_EXTRA_DELAY if getattr(tmdb_provider, "hit_429", False) else 0.0
        deadline = now + timedelta(seconds=interval + jitter + extra)
        st_row = session.execute(
            select(SourceState).where(
                (SourceState.media_item_id == item.id)
                &
                (SourceState.source_name == primary_source)
            )
        ).scalar_one_or_none()
        if st_row is not None:
            st_row.next_check_at = deadline
            session.commit()
        results.append((w.user_id, item, events))
    return results


def backup_database() -> None:
    """Create a backup of the SQLite database. Called periodically by the scheduler."""
    from app.utils.backup import create_backup
    import logging
    
    backup = create_backup()
    if backup:
        logging.info(f"Database backup created: {backup}")
    else:
        logging.warning("No database file found for backup")
