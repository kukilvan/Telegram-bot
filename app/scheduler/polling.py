"""Adaptive polling cycle (Phase 5): fetch → compare → dedup → send."""

import json as _json
from dataclasses import replace as _replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import ExternalId, MediaItem, SourceState
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
    session.commit()


async def _fetch_tmdb_state(session: Session, provider, item: MediaItem) -> dict:
    """Fetch current normalized TMDb state for a movie item.

    Placeholder normalization (Phase 6 refines digital release detection).
    Returns {} when the item has no TMDb external id or details are missing.
    """
    ext = session.execute(
        select(ExternalId).where(
            (ExternalId.source == "tmdb") &
            (ExternalId.media_item_id == item.id)
        )
    ).scalar_one_or_none()
    if ext is None:
        return {}
    details = await provider.get_movie_details(int(ext.external_id))
    if not details:
        return {}
    rd = details.get("release_date")
    return {"digital_release": rd}


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
