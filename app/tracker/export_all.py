"""The JSON document of the export «Скачать всё (JSON)»: every table the owner's data lives in, read from one session.

Version 1 of the shape of spec 3.2 of stage 7.1. The owner's data is exported (titles with their sources, seasons with
episodes and parts, franchise movies, platforms, the price history, the settings, «Входящие»); the app's working state is
left out on purpose (source snapshots, events, the delivery queue, `failure_notified_at`). Reads only: the caller opened
the session, so the whole document is one picture of the database.
"""

import logging
from collections import defaultdict
from datetime import datetime, tzinfo
from typing import Any

from sqlalchemy import select, text

from app.tracker import games, scores, storage
from app.tracker.cards import STATUS_LABELS
from app.tracker.export_rows import FORMAT, VERSION, day_text, moment_text, zone_name
from app.tracker.sources.igdb_games import SOURCE_KEY as IGDB
from app.tracker.models import (
    EpisodeRecord, ExternalId, GamePlatformRecord, InboxRecord, MovieRecord, PartRecord, PriceRecord, SeasonRecord,
    SettingRecord, Title, TitleKind,
)

def _label(value: int | None) -> str | None:
    """The label of a stored score; a value off the scale (a spoiled row) is no score, and the log says so."""
    if value is None:
        return None
    try:
        return scores.label(value)
    except ValueError:
        logging.warning("export: a stored score is off the scale and is left out: %r", value)
        return None


def _by(rows, key) -> dict[int, list]:
    grouped: dict[int, list] = defaultdict(list)
    for row in rows:
        grouped[key(row)].append(row)
    return grouped


def _parents(session, names: dict[int, str]) -> dict[int, str]:
    """The name of the base game of each expansion, as the card shows it: the name in the list when the list has the game,
    else the name IGDB gave. A game whose stored state cannot be read has none (the log says so)."""
    states = storage.own_states_of(session, select(Title.id).where(Title.kind == TitleKind.GAME))
    asked: dict[int, games.Parent] = {}
    for title_id, state in states.items():
        try:
            if games.expansion_of(state) is not None and state.get("parent") is not None:
                asked[title_id] = games.Parent.from_state(state["parent"])
        except ValueError as spoiled:
            logging.warning("export: title %s: the expansion of a game cannot be read, left out: %r", title_id, spoiled)
    listed: dict[str, int] = {}
    wanted = {parent.id for parent in asked.values()}
    for external_id, title_id in session.execute(
        select(ExternalId.external_id, ExternalId.title_id).where(ExternalId.source == IGDB, ExternalId.external_id.in_(wanted))
    ):
        listed[external_id] = min(title_id, listed.get(external_id, title_id))  # the smaller number, as `known_ids`
    return {
        title_id: names.get(listed.get(parent.id, -1), parent.name) for title_id, parent in asked.items()
    }


def _seasons(session, tz: tzinfo) -> dict[int, list[dict[str, Any]]]:
    """The seasons of every title with their episodes and parts: title number → seasons by number."""
    episodes = _by(session.scalars(select(EpisodeRecord).order_by(EpisodeRecord.season_id, EpisodeRecord.number)),
                   lambda e: e.season_id)
    parts = _by(session.scalars(select(PartRecord).order_by(PartRecord.season_id, PartRecord.number)),
                lambda p: p.season_id)
    seasons: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for s in session.scalars(select(SeasonRecord).order_by(SeasonRecord.title_id, SeasonRecord.number)):
        seasons[s.title_id].append({
            "number": s.number, "name": s.name, "episode_count": s.episode_count, "watched": s.watched,
            "score": _label(s.score),
            "episodes": [{"number": e.number, "air_at": moment_text(e.air_at, tz)} for e in episodes.get(s.id, [])],
            "parts": [
                {"number": p.number, "first_episode": p.first_episode, "episode_count": p.episode_count}
                for p in parts.get(s.id, [])
            ],
        })
    return seasons


def _titles(session, tz: tzinfo) -> list[dict[str, Any]]:
    titles = list(session.scalars(select(Title).order_by(Title.id)))
    seasons = _seasons(session, tz)
    sources = _by(session.scalars(select(ExternalId).order_by(ExternalId.id)), lambda e: e.title_id)
    movies = _by(session.scalars(select(MovieRecord).order_by(MovieRecord.id)), lambda m: m.title_id)
    platforms = _by(session.scalars(select(GamePlatformRecord).order_by(GamePlatformRecord.id)), lambda p: p.title_id)
    prices = _by(session.scalars(select(PriceRecord).order_by(PriceRecord.seen_at, PriceRecord.id)), lambda p: p.title_id)
    parents = _parents(session, {t.id: t.name for t in titles})
    return [
        {
            "id": t.id, "kind": t.kind.value, "name": t.name, "original_name": t.original_name, "year": t.year,
            "genres": list(t.genres or []), "overview": t.overview, "poster": t.poster_path,
            "status": t.status.value, "status_label": STATUS_LABELS[t.status], "score": _label(t.score),
            "tracking": t.tracking_enabled, "added_at": moment_text(t.added_at, tz),
            "status_changed_at": moment_text(t.status_changed_at, tz), "restored_at": moment_text(t.restored_at, tz),
            "sources": [{"source": e.source, "id": e.external_id} for e in sources.get(t.id, [])],
            "seasons": seasons.get(t.id, []),
            "franchise_movies": [
                {"name": m.name, "aired_on": day_text(m.aired_on), "released": m.released} for m in movies.get(t.id, [])
            ],
            "platforms": [{"platform": p.platform, "playing": p.playing} for p in platforms.get(t.id, [])],
            "expansion_of": parents.get(t.id),
            "price_history": [
                {
                    "seen_at": moment_text(p.seen_at, tz), "country": p.country, "currency": p.currency,
                    "final": p.final, "original": p.original, "pct": p.pct,
                }
                for p in prices.get(t.id, [])
            ],
        }
        for t in titles
    ]


def _inbox(session, tz: tzinfo) -> list[dict[str, Any]]:
    """Every inbox item, the newest first, without the fields only the app works with."""
    rows = session.scalars(select(InboxRecord).order_by(InboxRecord.received_at.desc(), InboxRecord.id.desc()))
    return [
        {
            "id": i.id, "state": i.state.value, "reason": i.reason.value if i.reason else None,
            "kind": i.kind.value if i.kind else None, "text": i.text, "links": list(i.links or []),
            "post_url": i.post_url, "received_at": moment_text(i.received_at, tz), "moved_at": moment_text(i.moved_at, tz),
        }
        for i in rows
    ]


def document(session, tz: tzinfo, now: datetime) -> dict[str, Any]:
    """The whole export as plain values (`now`: naive UTC). All reads go through the one session."""
    revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return {
        "format": FORMAT, "version": VERSION, "exported_at": moment_text(now, tz), "time_zone": zone_name(tz),
        "database_revision": revision,
        "titles": _titles(session, tz),
        "settings": {row.key: row.value for row in session.scalars(select(SettingRecord).order_by(SettingRecord.key))},
        "inbox": _inbox(session, tz),
    }
