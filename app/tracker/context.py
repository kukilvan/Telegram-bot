"""What every part of the core shares: the session factory, the clock, the sender, the default time zone, the locks.

The facade `Tracker` makes one context and hands it to each module, so a part never reaches for another's state.
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from app.tracker.actions import Action
from app.tracker.db import WRITE_OPTION

Clock = Callable[[], datetime]  # returns an aware datetime

PRIMARY_ROLE = "primary"  # the role of a title's own source id, as opposed to the ids of its sequels


class Sender(Protocol):
    async def send(self, message: str, actions: Sequence[Action] = ()) -> None:
        """Deliver one message to the owner, with `actions` as buttons under it; raise on failure."""


def naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True)
class CoreContext:
    session_factory: sessionmaker
    clock: Clock
    sender: Sender
    default_tz: tzinfo  # the time zone when the owner has set none (BOT_TIMEZONE); the set one is read from the database
    delivery_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    poll_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def write_session(self) -> Session:
        """A session whose transaction is already open for writing: use it as `with ctx.write_session() as session:`.

        Every write of the core goes through it; `session_factory()` is for reading. While it is open a second writer,
        of this process or of another on the same file (the web application), waits up to `busy_timeout`, so what is
        checked inside stays true until the commit. A write that cannot get the database in that time raises.

        The guarantee is of the transaction it begins: after `session.rollback()` the next statement begins an ordinary
        one, so do not carry on writing in the session after a rollback."""
        session = self.session_factory()
        try:
            session.connection(execution_options={WRITE_OPTION: True})  # begins the transaction, `BEGIN IMMEDIATE`
        except BaseException:
            session.close()
            raise
        return session

    def now(self) -> datetime:
        """The moment of the clock as naive UTC, like everything stored."""
        return naive_utc(self.clock())
