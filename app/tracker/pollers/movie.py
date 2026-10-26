"""A movie: its own release dates are compared, and its snapshot says when to look again."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.tracker import movie_events
from app.tracker import seasons as season_logic
from app.tracker import storage
from app.tracker.pollers.base import DueTitle, Poller


class MoviePoller(Poller):
    def first_check(self, seasons: Sequence[season_logic.Season], state: dict[str, Any], now: datetime) -> datetime:
        return now + movie_events.check_interval_for_state(state, now.date())

    def apply(self, due: DueTitle, snapshot: Any) -> int:
        now = self.ctx.now()
        today = now.date()
        with self.ctx.session_factory() as session:
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            old = movie_events.MovieDates.from_state(stored.state)
            new = movie_events.MovieDates.from_state(snapshot.state()).keeping_known(old)
            observed_on = stored.observed_at.date()
        # events first: if storing the state fails, the next poll finds the same facts and the dedup key drops them
        found = self.record_all(due, movie_events.detect_events(due.id, due.name, old, new, observed_on, today))
        with self.ctx.session_factory() as session:
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            stored.state = new.to_state()
            stored.observed_at = now
            stored.next_check_at = now + movie_events.check_interval(new, today)
            session.commit()
        return found
