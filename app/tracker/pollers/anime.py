"""An anime franchise: two sources are put together (Shikimori for the seasons, AniList for the schedule), and the
source entries behind the seasons and the franchise films are kept beside them."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.tracker import anime_events
from app.tracker import seasons as season_logic
from app.tracker import series_events, storage
from app.tracker.models import MovieRecord, PartRecord, SeasonRecord, Title
from app.tracker.pollers.base import DueTitle, Poller


class AnimePoller(Poller):
    def first_seasons(self, snapshot: Any, now: datetime) -> Sequence[season_logic.Season]:
        """An anime's episodes are put together from both its sources."""
        return anime_events.assemble(snapshot.seasons, snapshot.parts, snapshot.schedules, None, now)

    def first_check(self, seasons: Sequence[season_logic.Season], state: dict[str, Any], now: datetime) -> datetime:
        return now + series_events.check_interval(series_events.ShowState.of(seasons, state), now)

    def store_extras(self, session, title_id: int, records: dict[int, SeasonRecord], snapshot: Any) -> None:
        """The source entries behind an anime's seasons (one per part, with their ids) and its franchise movies."""
        for part in snapshot.parts:
            record = records.get(part.season)
            if record is None:
                continue
            session.add(
                PartRecord(
                    title_id=title_id, season_id=record.id, number=part.number, first_episode=part.first_episode,
                    episode_count=part.episode_count, shikimori_id=part.ids.shikimori, mal_id=part.ids.mal,
                    anilist_id=part.ids.anilist,
                )
            )
        for movie in snapshot.movies:
            session.add(
                MovieRecord(
                    title_id=title_id, name=movie.name, aired_on=movie.aired_on, released=movie.released,
                    shikimori_id=movie.ids.shikimori, mal_id=movie.ids.mal, anilist_id=movie.ids.anilist,
                )
            )

    def apply(self, due: DueTitle, snapshot: Any) -> int:
        """Put the anime's two sources together, compare with the stored seasons, queue events, store what is new."""
        now = self.ctx.now()
        with self.ctx.session_factory() as session:
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            observed_at = stored.observed_at
            previous = tuple(season for _, season in storage.load_seasons(session, due.id))
            gap = self.settings.part_gap(session)
            tz = self.settings.time_zone(session)
            title = session.get(Title, due.id)
            name = title.name if title.original_name in ("", title.name) else f"{title.name} ({title.original_name})"
            known = set(
                session.scalars(
                    select(PartRecord.shikimori_id).where(PartRecord.title_id == due.id, PartRecord.anilist_id.is_not(None))
                )
            )
            films = {
                m.shikimori_id: m.released
                for m in session.scalars(select(MovieRecord).where(MovieRecord.title_id == due.id))
            }
        known.update(p.ids.shikimori for p in snapshot.parts if p.ids.anilist)
        old = series_events.ShowState.of(previous, {})
        assembled = anime_events.assemble(snapshot.seasons, snapshot.parts, snapshot.schedules, previous, now, known)
        new = series_events.ShowState.of(assembled, {}).keeping_known(old)
        detected = series_events.detect_events(
            due.id, name, old, new, observed_at, now, gap, anime_events.flavor(tz)
        )
        detected += anime_events.detect_movie_events(due.id, name, films, snapshot.movies, observed_at.date())
        # events first: if storing the state fails, the next poll finds the same facts and the dedup key drops them
        found = self.record_all(due, detected)
        with self.ctx.session_factory() as session:
            storage.sync_seasons(session, due.id, new.seasons)
            session.flush()
            self._sync_entries(session, due.id, snapshot)
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            stored.state = {**stored.state, **{k: v for k, v in snapshot.state().items() if v is not None}}
            stored.observed_at = now
            stored.next_check_at = now + series_events.check_interval(new, now)
            storage.refresh_status(session, session.get(Title, due.id), now)
            session.commit()
        return found

    @staticmethod
    def _sync_entries(session, title_id: int, snapshot: Any) -> None:
        """The source entries behind the seasons and the franchise films: new ones are stored, known ones learn the
        counts and the AniList ids found since. What is stored is never emptied by a source that stays silent."""
        seasons = {r.number: r.id for r in session.scalars(select(SeasonRecord).where(SeasonRecord.title_id == title_id))}
        rows = {p.shikimori_id: p for p in session.scalars(select(PartRecord).where(PartRecord.title_id == title_id))}
        taken_anilist = {p.anilist_id for p in rows.values() if p.anilist_id}
        taken_slots = {(p.season_id, p.number) for p in rows.values()}
        for part in snapshot.parts:
            row = rows.get(part.ids.shikimori)
            if row is None:
                season_id = seasons.get(part.season)
                if season_id is None or (season_id, part.number) in taken_slots:
                    continue
                row = PartRecord(
                    title_id=title_id, season_id=season_id, number=part.number, first_episode=part.first_episode,
                    episode_count=part.episode_count, shikimori_id=part.ids.shikimori, mal_id=part.ids.mal,
                    anilist_id=None,
                )
                session.add(row)
                taken_slots.add((season_id, part.number))
            else:
                row.first_episode = part.first_episode
                row.episode_count = part.episode_count
            if row.anilist_id is None and part.ids.anilist and part.ids.anilist not in taken_anilist:
                row.anilist_id = part.ids.anilist
                taken_anilist.add(part.ids.anilist)

        films = {m.shikimori_id: m for m in session.scalars(select(MovieRecord).where(MovieRecord.title_id == title_id))}
        taken_anilist = {m.anilist_id for m in films.values() if m.anilist_id}
        for film in snapshot.movies:
            row = films.get(film.ids.shikimori)
            if row is None:
                row = MovieRecord(
                    title_id=title_id, name=film.name, aired_on=film.aired_on, released=film.released,
                    shikimori_id=film.ids.shikimori, mal_id=film.ids.mal, anilist_id=None,
                )
                session.add(row)
            else:
                row.name = film.name
                row.aired_on = film.aired_on or row.aired_on
                row.released = row.released or film.released  # a film does not become «announced» again
            if row.anilist_id is None and film.ids.anilist and film.ids.anilist not in taken_anilist:
                row.anilist_id = film.ids.anilist
                taken_anilist.add(film.ids.anilist)
