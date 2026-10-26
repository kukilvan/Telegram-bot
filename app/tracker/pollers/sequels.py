"""An archived movie: its own release is no longer followed, only the collection it belongs to, for sequels."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.tracker import seasons as season_logic
from app.tracker import sequel_events, storage
from app.tracker.models import ExternalId
from app.tracker.pollers.base import DueTitle, Poller


class SequelPoller(Poller):
    """Polls the sequel source of a kind. `release_source` is the source of the same kind's own release: a sequel the
    owner already follows is listed under its id."""

    def __init__(self, *args: Any, release_source: Any | None = None) -> None:
        super().__init__(*args)
        self.release_source = release_source

    def first_check(self, seasons: Sequence[season_logic.Season], state: dict[str, Any], now: datetime) -> datetime:
        return now  # an archived title is looked at as soon as it is archived

    def apply(self, due: DueTitle, snapshot: Any) -> int:
        """Announce the collection parts that were not there at the previous check."""
        now = self.ctx.now()
        with self.ctx.session_factory() as session:
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            first_look = "parts" not in stored.state
            old = sequel_events.Sequels.from_state(stored.state)
        new = sequel_events.Sequels.from_state(snapshot.state()).keeping_known(old)
        found = 0
        if not first_look:  # the first look only records what the collection holds now
            if self.release_source is None:
                raise KeyError(self.kind)  # no release source of this kind: the sequels the owner follows are unknown
            listed = self._listed_ids(self.release_source.source_key)
            events = [
                event
                for event in sequel_events.detect_sequel_events(due.name, due.kind, old, new)
                if event.data["sequel_id"] not in listed  # the owner already follows it: nothing to offer
            ]
            found = self.record_all(due, events)
        with self.ctx.session_factory() as session:
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            stored.state = new.to_state()
            stored.observed_at = now
            stored.next_check_at = now + sequel_events.INTERVAL
            session.commit()
        return found

    def _listed_ids(self, source_key: str) -> set[str]:
        with self.ctx.session_factory() as session:
            return set(session.scalars(select(ExternalId.external_id).where(ExternalId.source == source_key)))
