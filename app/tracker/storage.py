"""What the parts of the core read and write together in one session: a title's seasons and episodes, its stored
snapshots, and its status that follows from them. Helpers on a session someone else opened; the caller commits."""

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.tracker import progress, series_events
from app.tracker import seasons as season_logic
from app.tracker.context import PRIMARY_ROLE
from app.tracker.kinds import is_seasonal
from app.tracker.models import EpisodeRecord, ExternalId, PartRecord, SeasonRecord, SourceSnapshot, Title


def store_seasons(session, title_id: int, seasons: Sequence[season_logic.Season]) -> dict[int, SeasonRecord]:
    records = {}
    for season in seasons:
        if season.number < 1:  # specials are not seasons, whatever the source adapter let through
            continue
        record = SeasonRecord(
            title_id=title_id, number=season.number, name=season.name, episode_count=season.expected, watched=False
        )
        session.add(record)
        session.flush()
        session.add_all(EpisodeRecord(season_id=record.id, number=e.number, air_at=e.air_at) for e in season.episodes)
        records[season.number] = record
    return records


def load_seasons(session, title_id: int) -> list[tuple[SeasonRecord, season_logic.Season]]:
    records = session.scalars(select(SeasonRecord).where(SeasonRecord.title_id == title_id).order_by(SeasonRecord.number))
    loaded = []
    for record in records:
        episodes = session.scalars(select(EpisodeRecord).where(EpisodeRecord.season_id == record.id))
        parts = session.scalars(
            select(PartRecord).where(PartRecord.season_id == record.id).order_by(PartRecord.number)
        ).all()
        season = season_logic.Season(
            number=record.number,
            name=record.name,
            expected=record.episode_count,
            episodes=tuple(sorted((season_logic.Episode(e.number, e.air_at) for e in episodes), key=lambda e: e.number)),
            cuts=tuple(season_logic.PartCut(p.first_episode, p.episode_count, p.shikimori_id) for p in parts),
            source_id=parts[0].shikimori_id if parts else None,  # the first part (smallest number) starts the season
        )
        loaded.append((record, season))
    return loaded


def relayout_records(
    session, title_id: int, renumber: Mapping[int, int], dissolved: Mapping[int, str | None]
) -> None:
    """Bring the stored seasons to the numbering the source has now. A season that starts no season any more is deleted
    with its episodes and parts (the database cascades), its mark with it, and the log says so. The others keep their
    record and their mark and get the new number, through temporary ones: no two seasons of a title may share a number
    even for a moment."""
    records = {r.number: r for r in session.scalars(select(SeasonRecord).where(SeasonRecord.title_id == title_id))}
    name = session.get(Title, title_id).name
    for number, entry in dissolved.items():
        record = records.pop(number, None)
        if record is None:
            continue
        logging.warning(
            "Anime season dissolved: title %r, season %s, entry %s, watched mark: %s", name, number, entry, record.watched
        )
        session.delete(record)
    session.flush()
    moving = [(records[old], new) for old, new in renumber.items() if old != new and old in records]
    for record, _ in moving:
        record.number = -record.id
    session.flush()
    for record, new in moving:
        record.number = new
    session.flush()


def sync_seasons(session, title_id: int, seasons: Sequence[season_logic.Season]) -> None:
    """Bring the stored seasons and episodes to the given ones; the owner's «watched» marks stay."""
    records = {r.number: r for r in session.scalars(select(SeasonRecord).where(SeasonRecord.title_id == title_id))}
    for season in seasons:
        record = records.get(season.number)
        if record is None:
            record = SeasonRecord(title_id=title_id, number=season.number, name=season.name,
                                  episode_count=season.expected, watched=False)
            session.add(record)
            session.flush()
        record.name = season.name
        record.episode_count = season.expected
        stored = {e.number: e for e in session.scalars(select(EpisodeRecord).where(EpisodeRecord.season_id == record.id))}
        for episode in season.episodes:
            if episode.number in stored:
                stored[episode.number].air_at = episode.air_at
            else:
                session.add(EpisodeRecord(season_id=record.id, number=episode.number, air_at=episode.air_at))
        listed = {e.number for e in season.episodes}
        for number, row in stored.items():
            if number not in listed:
                session.delete(row)


def own_state(session, title_id: int) -> dict[str, Any]:
    """State from the title's own source (the archive's sequel snapshot holds no dates)."""
    snapshot = session.scalar(
        select(SourceSnapshot)
        .join(ExternalId, ExternalId.title_id == SourceSnapshot.title_id)
        .where(
            SourceSnapshot.title_id == title_id,
            ExternalId.role == PRIMARY_ROLE,
            SourceSnapshot.source == ExternalId.source,
        )
    )
    return snapshot.state if snapshot else {}


def stored_snapshot(session, title_id: int, source: str) -> SourceSnapshot:
    return session.scalars(
        select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == source)
    ).one()


def refresh_status(session, title: Title, now: datetime) -> None:
    """Give a seasonal title the status that follows from its season marks and the state of the show."""
    if not is_seasonal(title.kind):
        return
    loaded = load_seasons(session, title.id)
    outcome = progress.series_status(
        title.status,
        (season for _, season in loaded),
        {record.number for record, _ in loaded if record.watched},
        series_events.is_closed(own_state(session, title.id).get("show_status")),
        now,
    )
    if outcome is None:
        return
    if outcome.status != title.status:
        title.status = outcome.status
        title.status_changed_at = now
    title.tracking_enabled = outcome.tracking
