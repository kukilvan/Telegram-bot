"""The copies of the database for the owner: the Settings block, «Сделать копию сейчас» and the hourly job, with the report of a failed daily copy.

The files themselves are `app/utils/backup.py`; this module adds what the core owns: the one lock that the hourly job and
the press share (`CoreContext.backup_lock`), the owner's clock for «сегодня в …», and the event `backup_failed` (texts and
reasons are the pure `backup_events`, the lines of the page `backup_rows`). The block carries the part of the Google Drive
copy (`google_drive`); the sending of that copy is `drive_copies` — after the daily copy in the hourly job, after the
press (waited for up to a minute, then it goes on in the background) and after the sign-in. The folder is read in a
worker thread (rule 1); a block that cannot be built shows the unreadable line, so the rest of the page stays.
"""

import asyncio
import dataclasses
import logging
from collections.abc import Callable
from datetime import datetime

from app.tracker import backup_events, backup_rows
from app.tracker.backup_rows import BackupBlock, PressOutcome
from app.tracker.context import CoreContext
from app.tracker.drive_copies import DriveCopies
from app.tracker.google_drive import GoogleDrive
from app.tracker.moment_words import moment_in_words
from app.tracker.queue import EventQueue
from app.tracker.settings_store import SettingsStore
from app.utils import backup

PRESS_WAITS_SECONDS = 60  # a press waits so long for the hourly copy, then «уже делается»
SEND_WAITS_SECONDS = 60  # and so long for the sending of its copy to Google Drive, then it goes on in the background


class Backups:
    def __init__(
        self, ctx: CoreContext, settings: SettingsStore, queue: EventQueue, database_url: str | None, drive: GoogleDrive,
        wall_clock=datetime.now,
    ) -> None:
        self.ctx = ctx
        self.drive = drive
        self.settings = settings
        self.queue = queue
        self.url = database_url  # None: no database file to copy (the core made without one)
        self.wall_clock = wall_clock  # the clock of the container: it writes the time into the names of the copies
        self.copies = DriveCopies(ctx, settings, queue, drive, database_url)
        drive.on_connected = self.copies.send_newest  # the seam of the sign-in: the first copy goes in the background
        self._pressed = False  # a press is under way: the next one does not wait for it
        self._background: set[asyncio.Task[str | None]] = set()

    async def block(self, host: str) -> BackupBlock:
        """The lines of the Settings block for a page opened at `host`. Never raises: what cannot be read gives the
        unreadable line (the copies) or no Google Drive part, and a warning."""
        words: Callable[[datetime], str] = str  # a stored moment in words; the plain one while the clock is not read
        try:
            rules = await self.settings.delivery_rules()
            local_now = rules.local(self.ctx.now())
            words = lambda moment: moment_in_words(rules.local(moment), local_now)  # noqa: E731
            moments = await asyncio.to_thread(self._moments)
            block = backup_rows.copies_block(moments, local_now)
        except Exception as exc:
            logging.warning("The copies of the database cannot be read: %r", exc)
            block = backup_rows.unreadable_block()
        try:
            return dataclasses.replace(block, drive=await self.drive.part(host, words))
        except Exception as exc:
            logging.warning("The Google Drive part of the block cannot be built: %r", exc)
            return block

    def _moments(self) -> list[datetime]:
        file = backup.database_file(self.url) if self.url else None
        return [copy.moment for copy in backup.copies(file.parent / backup.BACKUP_FOLDER)] if file else []

    async def press(self) -> str:
        """«Сделать копию сейчас»: the manual copy, sent to Google Drive when it is connected, and the notice for the
        page. One copy at a time: the press waits up to a minute for the hourly job; a press while another press works,
        or in the second of its copy, is «busy». The sending holds the lock until it ends, in the background too."""
        if self._pressed:
            return backup_rows.press_notice(PressOutcome.BUSY)
        self._pressed = True
        try:
            try:
                await asyncio.wait_for(self.ctx.backup_lock.acquire(), PRESS_WAITS_SECONDS)
            except TimeoutError:
                return backup_rows.press_notice(PressOutcome.BUSY)
            return await self._press_locked()
        finally:
            self._pressed = False

    async def _press_locked(self) -> str:
        """The press with the lock held: it is released here, or by the sending it is handed to."""
        handed = False
        try:
            try:
                made = await asyncio.to_thread(self._make_manual)
            except FileExistsError:  # a copy of this very second
                return backup_rows.press_notice(PressOutcome.BUSY)
            except Exception as exc:
                logging.warning("Manual database backup failed: %r", exc)
                return backup_rows.press_notice(PressOutcome.FAILED, reason=backup_events.reason_of(exc))
            if made is None:
                logging.warning("No database file found for backup")
                return backup_rows.press_notice(PressOutcome.FAILED, reason=backup_events.OTHER_ERROR)
            logging.info("Manual database backup created: %s", made.path)
            if await self.copies.connected():
                sending = asyncio.get_running_loop().create_task(self._send_then_release(made))
                handed = True
                self._background.add(sending)
                sending.add_done_callback(self._background.discard)
                return await self._sent_notice(sending)
        finally:
            if not handed:
                self.ctx.backup_lock.release()
        rules = await self.settings.delivery_rules()
        when = moment_in_words(made.moment, rules.local(self.ctx.now()))
        return backup_rows.press_notice(PressOutcome.MADE, when=when)

    async def _send_then_release(self, copy: backup.Copy) -> str | None:
        try:
            return await self.copies.send(copy)
        finally:
            self.ctx.backup_lock.release()

    @staticmethod
    async def _sent_notice(sending: "asyncio.Task[str | None]") -> str:
        """The notice of the sending, waited for up to a minute; longer — it goes on, the line of Settings tells."""
        try:
            reason = await asyncio.wait_for(asyncio.shield(sending), SEND_WAITS_SECONDS)
        except TimeoutError:
            return backup_rows.press_notice(PressOutcome.SENDING)
        if reason is None:
            return backup_rows.press_notice(PressOutcome.SENT)
        return backup_rows.press_notice(PressOutcome.NOT_SENT, reason=reason)

    def _make_manual(self) -> backup.Copy | None:
        return backup.create_manual_backup(self.url, self.wall_clock()) if self.url else None

    async def hourly(self) -> None:
        """The scheduler's job: the daily copy when it is due (`backup.backup_database`, under the same lock), a failed
        one reported; then the newest copy sent to Google Drive when it has not gone yet."""
        if self.url:
            await backup.backup_database(self.url, lock=self.ctx.backup_lock, on_failure=self._report_failure)
        await self.copies.hourly()

    async def _report_failure(self, exc: Exception) -> None:
        """Queue «⚠️ Копия базы не сделана…»: at most one a day (the key carries the owner's date), no title."""
        rules = await self.settings.delivery_rules()
        local_now = rules.local(self.ctx.now())
        moments = await asyncio.to_thread(self._moments)
        last = moment_in_words(moments[0], local_now) if moments else None
        text = backup_events.local_text(backup_events.reason_of(exc), last)
        key = backup_events.dedup_key(backup_events.LOCAL, local_now.date())
        await self.queue.record_event(backup_events.BACKUP_FAILED, {"text": text}, key)
