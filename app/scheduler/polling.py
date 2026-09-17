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

from app.database.models import ExternalId, MediaItem, SourceState, UserWatchItem
from app.domain.events import compare_states
from app.services.notifications import get_enabled_rules, has_been_sent, mark_sent


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
    return {"digital_release": _earliest_digital_date(release_dates)}


async def poll_item(session: Session, provider, item: MediaItem, user_id: int):
    """Run one polling cycle for a watch item.

    Fetches the current normalized state from the provider, compares it with
    the last stored source_state, and for each detected event checks dedup +
    enabled rule before marking it sent. Returns events that passed both gates;
    the caller sends the returned Telegram messages.
    """
    state = await _fetch_tmdb_state(session, provider, item)
    old = _load_state(session, item.id, "tmdb")
    if old is None:
        # First poll: store baseline, no event.
        _store_state(session, item.id, "tmdb", state)
        return []

    to_send = []
    for ev in compare_states(old, state):
        ev = _replace(ev, media_item_id=item.id)  # attach item id for per-item dedup
        fp = ev.fingerprint()
        if has_been_sent(session, fp):
            continue  # dedup: already sent
        enabled_rules = get_enabled_rules(session, user_id, item.id)
        if not any(r.event_type == ev.event_type for r in enabled_rules):
            continue  # no enabled rule for this event type
        mark_sent(session, fp, item.id)
        to_send.append(ev)

    _store_state(session, item.id, "tmdb", state)
    return to_send


def _due_rows_query(session):
    """All watch rows joined with their tmdb source-state row (outer join).

    A watch row without any stored state yet is due immediately (it still needs a baseline fetch).
    """
    return (
        select(UserWatchItem, SourceState)
        .join(MediaItem, UserWatchItem.media_item_id == MediaItem.id)
        .outerjoin(
            SourceState,
            and_(
                SourceState.media_item_id == MediaItem.id,
                SourceState.source_name == "tmdb",
            ),
        )
    )


async def poll_due_items(session: Session, provider, now=None) -> list[tuple[int, MediaItem, list]]:
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
    due_rows = [
        (w, st)
        for w, st in rows
        if st is None or (st.next_check_at is not None and st.next_check_at <= now)
    ]
    # Oldest deadlines first; items without a deadline go out right away.
    due_rows.sort(key=lambda pair: due_sort_key(pair[1].next_check_at))

    results = []
    for w, st in due_rows:
        item = session.get(MediaItem, w.media_item_id)
        if item is None:
            continue
        events = await poll_item(session, provider, item, user_id=w.user_id)
        state_now = _load_state(session, item.id, "tmdb") or {}
        interval = tier_interval(state_now, item.media_type)
        jitter = random.uniform(0.0, JITTER_MAX_SECONDS)
        extra = RATE_LIMIT_EXTRA_DELAY if getattr(provider, "hit_429", False) else 0.0
        deadline = now + timedelta(seconds=interval + jitter + extra)
        st_row = session.execute(
            select(SourceState).where(
                (SourceState.media_item_id == item.id)
                &
                (SourceState.source_name == "tmdb")
            )
        ).scalar_one()
        st_row.next_check_at = deadline
        session.commit()
        results.append((w.user_id, item, events))
    return results
