"""A series: the fresh seasons are compared with the stored ones, and the owner's season marks keep the status."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.tracker import seasons as season_logic
from app.tracker import series_events, storage
from app.tracker.models import Title
from app.tracker.pollers.base import DueTitle, Poller


class SeriesPoller(Poller):
    def first_seasons(self, snapshot: Any, now: datetime) -> Sequence[season_logic.Season]:
        return snapshot.seasons

    def first_check(self, seasons: Sequence[season_logic.Season], state: dict[str, Any], now: datetime) -> datetime:
        return now + series_events.check_interval(series_events.ShowState.of(seasons, state), now)

    def apply(self, due: DueTitle, snapshot: Any) -> int:
        now = self.ctx.now()
        with self.ctx.session_factory() as session:
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            observed_at = stored.observed_at
            old = series_events.ShowState.of(
                (season for _, season in storage.load_seasons(session, due.id)), stored.state
            )
            gap = self.settings.part_gap(session)
        new = series_events.ShowState.of(
            (s for s in snapshot.seasons if s.number >= 1), snapshot.state()
        ).keeping_known(old)
        # events first: if storing the state fails, the next poll finds the same facts and the dedup key drops them
        found = self.record_all(
            due, series_events.detect_events(due.id, due.name, old, new, observed_at, now, gap), previous_look=observed_at
        )
        with self.ctx.write_session() as session:
            storage.sync_seasons(session, due.id, new.seasons)
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            stored.state = new.to_state()
            stored.observed_at = now
            stored.next_check_at = now + series_events.check_interval(new, now)
            storage.refresh_status(session, session.get(Title, due.id), now)
            session.commit()
        return found
