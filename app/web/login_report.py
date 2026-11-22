"""The login report on the web side: records the two events through the core and sends each at once, in the background.

A right password queues `WEB_LOGIN` (keyed by the `sid` of the new sign-in), the wrong try that begins a lock queues
`WEB_LOGIN_LOCKED` (keyed by the end of the lock); a locked try and the wrong passwords before the fifth send nothing
(spec 6 of stage 7.2). The texts are the core's: this module hands over facts only. The record is made inside the
request; the send runs as a task of its own, so the answer of the login never waits for Telegram. A send that fails
leaves the event queued and the next delivery pass sends it, whatever the rules (KI-73). A report that cannot be recorded
is logged and never stops a login.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from app.tracker.core import WEB_LOGIN, WEB_LOGIN_LOCKED, Tracker


class LoginReporter:
    """`tracker` None (a web app made without the core): nothing is reported. `now` is the wall clock, aware."""

    def __init__(self, tracker: Tracker | None, now: Callable[[], datetime]) -> None:
        self._tracker = tracker
        self._now = now
        self._sending: set[asyncio.Task[None]] = set()  # a task nobody holds can be collected before it ends

    async def logged_in(self, sid: str, device: str, address: str | None) -> None:
        """A right password: the report of the new sign-in `sid`."""
        await self._report(WEB_LOGIN, sid, device, address)

    async def locked(self, locked_until: float | None, device: str, address: str | None) -> None:
        """The wrong try that began a lock ending at `locked_until` (UTC seconds): the report of this lock."""
        if locked_until is not None:
            await self._report(WEB_LOGIN_LOCKED, str(int(locked_until)), device, address)

    async def _report(self, event_type: str, unique: str, device: str, address: str | None) -> None:
        if self._tracker is None:
            return
        try:
            event_id = await self._tracker.record_login_report(event_type, unique, device, address, self._now())
        except Exception:
            logging.exception("web: the login report could not be recorded")
            return
        if event_id is not None:  # None: this fact was reported already
            task = asyncio.create_task(self._send(self._tracker, event_id))
            self._sending.add(task)
            task.add_done_callback(self._sending.discard)

    @staticmethod
    async def _send(tracker: Tracker, event_id: int) -> None:
        try:
            await tracker.deliver_pending(force=True, only=frozenset({event_id}))
        except Exception:
            logging.exception("web: the login report could not be sent; it waits in the queue")
