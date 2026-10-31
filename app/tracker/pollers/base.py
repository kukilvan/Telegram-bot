"""What every kind of title does when it is added and when it is polled: one object per kind, one set of actions.

`snapshot_to_add`, `first_seasons` and `first_check` say what a new title starts with, `store_extras` keeps what only this kind has,
`known_ids` and `snapshot_ids` tell a title already in the list by the ids of the source, and `apply` compares a fresh
snapshot with the stored one, queues the events and stores the new state. The core never asks «which kind is it?»: it
asks the poller of the kind (the table is in `polling`).
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Select, select

from app.tracker import seasons as season_logic
from app.tracker.context import PRIMARY_ROLE, CoreContext
from app.tracker.models import ExternalId, SeasonRecord, TitleKind

if TYPE_CHECKING:
    from app.tracker.queue import EventQueue
    from app.tracker.settings_store import SettingsStore


@dataclass(frozen=True)
class DueTitle:
    id: int
    kind: TitleKind
    name: str
    external_id: str
    snapshot_source: str  # which of the title's snapshots is due: its release source or its sequel source
    sequels: bool  # True: an archived movie, checked only for sequels
    # True: the first check of the own source since «Вернуть в список»; what it finds is the baseline, no events
    baseline: bool = False


class Poller:
    def __init__(
        self, kind: TitleKind, source: Any, ctx: CoreContext, settings: "SettingsStore", queue: "EventQueue"
    ) -> None:
        self.kind = kind
        self.source = source
        self.ctx = ctx
        self.settings = settings
        self.queue = queue

    # --- adding a title ---

    async def snapshot_to_add(self, external_id: str) -> Any:
        """The snapshot a new title is made of; None when the source has nothing at this id. Most kinds take the one of
        the polling; a game asks Steam for its Russian texts too, only here (spec 4.4 of part 6.1)."""
        return await self.source.snapshot(external_id)

    def first_seasons(self, snapshot: Any, now: datetime) -> Sequence[season_logic.Season]:
        """The seasons to store with a new title."""
        return ()

    def first_check(
        self, session, seasons: Sequence[season_logic.Season], state: dict[str, Any], now: datetime
    ) -> datetime | None:
        """When the first poll is due; the snapshot taken at adding is the baseline it compares against. `session` is the
        write session of adding: what the rule reads of the settings (a game: the country of the stores) is read there."""
        raise NotImplementedError

    def store_extras(self, session, title_id: int, records: dict[int, SeasonRecord], snapshot: Any) -> None:
        """What only this kind keeps beside the seasons (an anime's source entries and franchise films)."""

    # --- knowing a title again ---

    def known_ids(self, session, ids: Iterable[str]) -> dict[str, int]:
        """Which of these ids of the source name a title of this kind that is in the list: id → the title's number, in
        one read. An id that names two titles (the source joined two chains) gives the smaller number."""
        wanted = set(ids)
        if not wanted:
            return {}
        found: dict[str, int] = {}
        for external_id, title_id in session.execute(self._known(wanted)):
            found[external_id] = min(title_id, found.get(external_id, title_id))
        return found

    def _known(self, wanted: set[str]) -> Select:
        """(id, title) pairs of the titles these ids name. A movie and a series are known by their own id."""
        return select(ExternalId.external_id, ExternalId.title_id).where(
            ExternalId.source == self.source.source_key,
            ExternalId.role == PRIMARY_ROLE,
            ExternalId.external_id.in_(wanted),
        )

    def snapshot_ids(self, snapshot: Any) -> set[str]:
        """Every id of the source a fresh snapshot names: a title known by any of them is the title of the snapshot."""
        return {snapshot.external_id}

    # --- polling a title ---

    def apply(self, due: DueTitle, snapshot: Any) -> int:
        """Compare the fresh snapshot with the stored one, queue events, store the new state. Returns the events found."""
        raise NotImplementedError

    def record_all(self, due: DueTitle, events: Iterable[Any], previous_look: datetime | None = None) -> int:
        """Queue the detected events of a title; returns how many were new. An event whose fact an earlier version of
        its key already queued after `previous_look` is not queued again. The first check after «Вернуть в список»
        queues nothing: what happened while the title was in the archive is the baseline, as when it is added."""
        if due.baseline:
            logging.info("title %s: first check after return, recorded as the baseline", due.id)
            return 0
        found = 0
        for event in events:
            earlier = getattr(event, "earlier_key", None)
            if earlier is not None and previous_look is not None and self.queue.queued_since(earlier, previous_look):
                continue
            payload = {"text": event.text, **event.data}
            if self.queue.record(event.type, payload, event.dedup_key, title_id=due.id) is not None:
                found += 1
        return found
