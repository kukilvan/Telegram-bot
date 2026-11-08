"""The copies of the database for the owner: the Settings block, «Сделать копию сейчас» and the report of a failed daily copy.

The files themselves are `app/utils/backup.py`; this module adds what the core owns: the one lock that the hourly job and
the press share (`CoreContext.backup_lock`), the owner's clock for «сегодня в …», and the event `backup_failed` (texts and
reasons are the pure `backup_events`, the lines of the page `backup_rows`). The block carries the part of the Google Drive
copy (`google_drive`). The folder is read in a worker thread (rule 1); a block that cannot be built shows the unreadable
line, so the rest of the page stays.
"""

import asyncio
import dataclasses
import logging
from datetime import datetime

from app.tracker import backup_events, backup_rows
from app.tracker.backup_rows import BackupBlock, PressOutcome
from app.tracker.context import CoreContext
from app.tracker.google_drive import GoogleDrive
from app.tracker.moment_words import moment_in_words
from app.tracker.queue import EventQueue
from app.tracker.settings_store import SettingsStore
from app.utils import backup

PRESS_WAITS_SECONDS = 60  # a press waits so long for the hourly copy, then «уже делается»


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
        self._pressed = False  # a press is under way: the next one does not wait for it

    async def block(self, host: str) -> BackupBlock:
        """The lines of the Settings block for a page opened at `host`. Never raises: what cannot be read gives the
        unreadable line (the copies) or no Google Drive part, and a warning."""
        try:
            rules = await self.settings.delivery_rules()
            moments = await asyncio.to_thread(self._moments)
            block = backup_rows.copies_block(moments, rules.local(self.ctx.now()))
        except Exception as exc:
            logging.warning("The copies of the database cannot be read: %r", exc)
            block = backup_rows.unreadable_block()
        try:
            return dataclasses.replace(block, drive=await self.drive.part(host))
        except Exception as exc:
            logging.warning("The Google Drive part of the block cannot be built: %r", exc)
            return block

    def _moments(self) -> list[datetime]:
        file = backup.database_file(self.url) if self.url else None
        return [copy.moment for copy in backup.copies(file.parent / backup.BACKUP_FOLDER)] if file else []

    async def press(self) -> str:
        """«Сделать копию сейчас»: the manual copy, and the notice for the page. One copy at a time: the press waits up to
        a minute for the hourly job's copy; a press while another press works, or in the second of its copy, is «busy»."""
        if self._pressed:
            return backup_rows.press_notice(PressOutcome.BUSY)
        self._pressed = True
        try:
            try:
                await asyncio.wait_for(self.ctx.backup_lock.acquire(), PRESS_WAITS_SECONDS)
            except TimeoutError:
                return backup_rows.press_notice(PressOutcome.BUSY)
            try:
                made = await asyncio.to_thread(self._make_manual)
            except FileExistsError:  # a copy of this very second
                return backup_rows.press_notice(PressOutcome.BUSY)
            except Exception as exc:
                logging.warning("Manual database backup failed: %r", exc)
                return backup_rows.press_notice(PressOutcome.FAILED, reason=backup_events.reason_of(exc))
            finally:
                self.ctx.backup_lock.release()
            if made is None:
                logging.warning("No database file found for backup")
                return backup_rows.press_notice(PressOutcome.FAILED, reason=backup_events.OTHER_ERROR)
            logging.info("Manual database backup created: %s", made.path)
            rules = await self.settings.delivery_rules()
            when = moment_in_words(made.moment, rules.local(self.ctx.now()))
            return backup_rows.press_notice(PressOutcome.MADE, when=when)
        finally:
            self._pressed = False

    def _make_manual(self) -> backup.Copy | None:
        return backup.create_manual_backup(self.url, self.wall_clock()) if self.url else None

    async def hourly(self) -> None:
        """The scheduler's job: the daily copy when it is due (`backup.backup_database`, under the same lock), and a failed
        one is reported."""
        if self.url:
            await backup.backup_database(self.url, lock=self.ctx.backup_lock, on_failure=self._report_failure)

    async def _report_failure(self, exc: Exception) -> None:
        """Queue «⚠️ Копия базы не сделана…»: at most one a day (the key carries the owner's date), no title."""
        rules = await self.settings.delivery_rules()
        local_now = rules.local(self.ctx.now())
        moments = await asyncio.to_thread(self._moments)
        last = moment_in_words(moments[0], local_now) if moments else None
        text = backup_events.local_text(backup_events.reason_of(exc), last)
        key = backup_events.dedup_key(backup_events.LOCAL, local_now.date())
        await self.queue.record_event(backup_events.BACKUP_FAILED, {"text": text}, key)
