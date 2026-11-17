"""Recording the login report: the event of a login or of a lock, with its text, in the delivery queue.

The web hands over the facts (type, device in words, public address or None, the moment, the unique part of the key);
the text is made here with the moment in words on the owner's clock (`moment_in_words`). Recording is all this does:
sending at once is the caller's background task (`Tracker.deliver_pending` with `force` and `only`), so a login never
waits for Telegram. A report that fails to send stays queued and goes out later by the delivery rules (KI-73).
"""

from datetime import datetime

from app.tracker import login_events
from app.tracker.context import CoreContext, naive_utc
from app.tracker.login_events import WEB_LOGIN, WEB_LOGIN_LOCKED  # re-exported by the facade
from app.tracker.moment_words import moment_in_words
from app.tracker.queue import EventQueue
from app.tracker.settings_store import SettingsStore


__all__ = ["LoginReports", "WEB_LOGIN", "WEB_LOGIN_LOCKED"]


class LoginReports:
    def __init__(self, ctx: CoreContext, queue: EventQueue, settings: SettingsStore) -> None:
        self.ctx = ctx
        self.queue = queue
        self.settings = settings

    async def record(
        self, event_type: str, unique: str, device: str, address: str | None, moment: datetime
    ) -> int | None:
        """Queue the report of a fact. `moment` is aware. Returns the id of the event, or None when this fact (`unique`:
        the `sid` of a login, the end of a lock) was reported already. An `event_type` that is no report is a `ValueError`."""
        rules = await self.settings.delivery_rules()
        words = moment_in_words(rules.local(naive_utc(moment)), rules.local(self.ctx.now()))
        text = login_events.text_of(event_type, device, words, address)
        return await self.queue.record_event(event_type, {"text": text}, login_events.dedup_key(event_type, unique))
