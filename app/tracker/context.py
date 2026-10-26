"""What every part of the core shares: the session factory, the clock, the sender, the default time zone, the locks.

The facade `Tracker` makes one context and hands it to each module, so a part never reaches for another's state.
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, tzinfo
from typing import Protocol

from sqlalchemy.orm import sessionmaker

from app.tracker.actions import Action

Clock = Callable[[], datetime]  # returns an aware datetime

PRIMARY_ROLE = "primary"  # the role of a title's own source id, as opposed to the ids of its sequels


class Sender(Protocol):
    async def send(self, message: str, actions: Sequence[Action] = ()) -> None:
        """Deliver one message to the owner, with `actions` as buttons under it; raise on failure."""


def naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


@dataclass(frozen=True)
class CoreContext:
    session_factory: sessionmaker
    clock: Clock
    sender: Sender
    default_tz: tzinfo  # the time zone when the owner has set none (BOT_TIMEZONE); the set one is read from the database
    delivery_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    poll_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)  # one write at a time

    def now(self) -> datetime:
        """The moment of the clock as naive UTC, like everything stored."""
        return naive_utc(self.clock())
