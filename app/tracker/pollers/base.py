"""What every kind of title does when it is added and when it is polled: one object per kind, one set of actions.

`first_seasons` and `first_check` say what a new title starts with, `store_extras` keeps what only this kind has, and
`apply` compares a fresh snapshot with the stored one, queues the events and stores the new state. The core never asks
«which kind is it?»: it asks the poller of the kind (the table is in `polling`).
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.tracker import seasons as season_logic
from app.tracker.context import CoreContext
from app.tracker.models import SeasonRecord, TitleKind

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

    def first_seasons(self, snapshot: Any, now: datetime) -> Sequence[season_logic.Season]:
        """The seasons to store with a new title."""
        return ()

    def first_check(self, seasons: Sequence[season_logic.Season], state: dict[str, Any], now: datetime) -> datetime | None:
        """When the first poll is due; the snapshot taken at adding is the baseline it compares against."""
        raise NotImplementedError

    def store_extras(self, session, title_id: int, records: dict[int, SeasonRecord], snapshot: Any) -> None:
        """What only this kind keeps beside the seasons (an anime's source entries and franchise films)."""

    # --- polling a title ---

    def apply(self, due: DueTitle, snapshot: Any) -> int:
        """Compare the fresh snapshot with the stored one, queue events, store the new state. Returns the events found."""
        raise NotImplementedError

    def record_all(self, due: DueTitle, events: Iterable[Any]) -> int:
        """Queue the detected events of a title; returns how many were new."""
        found = 0
        for event in events:
            payload = {"text": event.text, **event.data}
            if self.queue.record(event.type, payload, event.dedup_key, title_id=due.id) is not None:
                found += 1
        return found
