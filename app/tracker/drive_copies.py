"""The sending of the Google Drive copy: the newest copy archived and sent to the folder «Трекер — копии», the old archives rotated, the state written and a failure reported.

Rules: sections 4.4–4.6 of the spec of stage 7.1, ADR 0012. What goes is the newest daily or manual copy; the archive
(`app/utils/archive.py`) is made in a worker thread in `data/backups/upload/` and deleted after the attempt, sent or not.
The requests are `GoogleDriveApi`'s: the access token from the refresh token, kept in memory until a minute before it
ends; a 401 refreshes it once and repeats the request once, a second 401 means Google no longer accepts the sign-in.
The folder is the one of the token file, else found by its name, else made; a file of the same name and size in it
counts as sent, so a retry after a lost answer makes no duplicate. Only the app's own archive names are rotated, to the
30 newest; a failed delete is a warning. One attempt is never over 5 minutes. Each attempt writes the state file
(`drive_state`); a failure's reason (`backup_events`) is reported by the event `backup_failed:drive:<owner's date>`
at once or at the 2nd failure in a row. One attempt at a time: `hourly` and `send_newest` take `CoreContext.backup_lock`,
`send` is called with it held. Secrets never reach the log: tokens travel in headers and form bodies only.
"""

import asyncio
import dataclasses
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypeVar

from app.providers.google_drive import DriveFile, GoogleError
from app.tracker import backup_events
from app.tracker.backup_events import CONNECTION, DOWN, FULL, NO_COPY, SIGN_IN, UNKNOWN
from app.tracker.context import CoreContext
from app.tracker.db import BACKUP_STAMP_FORMAT, database_file
from app.tracker.drive_state import KEPT_IN_DRIVE, DriveState
from app.tracker.google_drive import DriveToken, GoogleDrive
from app.tracker.moment_words import moment_in_words
from app.tracker.queue import EventQueue
from app.tracker.settings_store import SettingsStore
from app.utils import backup
from app.utils.archive import archive_name, make_archive

FOLDER_NAME = "Трекер — копии"
UPLOAD_FOLDER = "upload"  # in `data/backups`: the archive lives there only during its attempt
ATTEMPT_SECONDS = 300  # one attempt, whatever its requests
TOKEN_MARGIN = timedelta(minutes=1)  # an access token is renewed this long before it ends
ARCHIVE_NAME = re.compile(r"^tracker_db_(\d{8}_\d{6})(?:_manual)?\.7z$")  # the app's own archives in the folder
SENDABLE = (backup.DAILY, backup.MANUAL)  # the copies made before an update or a restore are not sent
RATE_LIMITS = frozenset({"rateLimitExceeded", "userRateLimitExceeded"})

T = TypeVar("T")


class SignInRefused(Exception):
    """Google does not accept the sign-in any more: a 401 after a refresh, or the token file is gone."""


class NoCopy(Exception):
    """There is no daily or manual copy on the PC to send."""


def reason_of(exc: BaseException) -> str:
    """The reason key of a failed attempt (spec 4.6); what this does not know is «unknown», with the archive's failures."""
    if isinstance(exc, NoCopy):
        return NO_COPY
    if isinstance(exc, SignInRefused):
        return SIGN_IN
    if isinstance(exc, TimeoutError):
        return CONNECTION
    if not isinstance(exc, GoogleError):
        return UNKNOWN
    if exc.status is None:
        return CONNECTION if exc.cause is not None else UNKNOWN
    if exc.error == "invalid_grant" or exc.status == 401:
        return SIGN_IN
    if exc.status == 403 and exc.reason == "storageQuotaExceeded":
        return FULL
    if exc.status >= 500 or exc.status == 429 or (exc.status == 403 and exc.reason in RATE_LIMITS):
        return DOWN
    return UNKNOWN


def own_archives(files: list[DriveFile]) -> list[DriveFile]:
    """The app's own archives of the folder, newest first by the time in their names; other files are not in it."""
    found = []
    for file in files:
        match = ARCHIVE_NAME.match(file.name)
        if match is None:
            continue
        try:
            moment = datetime.strptime(match.group(1), BACKUP_STAMP_FORMAT)
        except ValueError:  # no such date: not one of the app's
            continue
        found.append((moment, file.name, file))
    return [file for _, _, file in sorted(found, key=lambda item: (item[0], item[1]), reverse=True)]


class DriveCopies:
    def __init__(
        self, ctx: CoreContext, settings: SettingsStore, queue: EventQueue, drive: GoogleDrive, database_url: str | None,
    ) -> None:
        self.ctx = ctx
        self.settings = settings
        self.queue = queue
        self.drive = drive
        self.api = drive.api
        self.files = drive.files
        file = database_file(database_url) if database_url else None
        self.folder: Path | None = file.parent / backup.BACKUP_FOLDER if file else None  # the copies on the PC
        self._access: tuple[str, str, datetime] | None = None  # (refresh token, access token, valid until — naive UTC)

    # --- when a copy goes ----------------------------------------------------------------------

    async def connected(self) -> bool:
        """Whether a copy can go now: the copy is on and the token file reads."""
        return self.drive.on and await asyncio.to_thread(self.files.token) is not None

    def newest(self) -> backup.Copy | None:
        """The newest daily or manual copy on the PC; None — none. Blocking: called in a worker thread."""
        if self.folder is None:
            return None
        return next((copy for copy in backup.copies(self.folder) if copy.kind in SENDABLE), None)

    def _due(self) -> tuple[bool, backup.Copy | None]:
        """For the hourly job: whether an attempt is due, and the copy it sends (None — there is no copy, which the
        attempt reports). Not connected, waiting for a new sign-in, or the newest copy went last — not due."""
        token, state = self.files.token(), self.files.state()
        if token is None or (state is not None and state.waits_for_sign_in(token.connected_at)):
            return False, None
        copy = self.newest()
        if copy is not None and state is not None and copy.path.name == state.last_success_name:
            return False, copy
        return True, copy

    async def hourly(self) -> None:
        """The hourly job, after its daily copy: the newest copy sent when it has not gone yet (spec 4.5). A new daily
        copy goes in the same run, a failed or a manual one is retried, the PC that was off sends at its start."""
        if not self.drive.on:
            return
        async with self.ctx.backup_lock:
            try:
                due, copy = await asyncio.to_thread(self._due)
            except Exception as exc:  # the folder of the copies cannot be read: the attempt says so
                logging.warning("The copies to send to Google Drive cannot be read: %r", exc)
                due, copy = True, None
            if due:
                await self.send(copy)

    async def send_newest(self) -> None:
        """The newest copy sent at once (after «Подключить Google Drive»): the background seam of the sign-in."""
        if not self.drive.on:
            return
        async with self.ctx.backup_lock:
            try:
                copy = await asyncio.to_thread(self.newest)
            except Exception as exc:
                logging.warning("The copies to send to Google Drive cannot be read: %r", exc)
                copy = None
            await self.send(copy)

    # --- one attempt -----------------------------------------------------------------------------

    async def send(self, copy: backup.Copy | None) -> str | None:
        """One attempt to send `copy` (None — no copy to send); the caller holds `CoreContext.backup_lock`. Returns None
        when it went, else the reason key. The state file is written and a failure reported either way; never raises."""
        token = await asyncio.to_thread(self.files.token)
        state = await asyncio.to_thread(self.files.state) or DriveState()
        try:
            if token is None:
                raise SignInRefused("the token file is gone")
            if copy is None:
                raise NoCopy()
            kept = await self._attempt(token, copy)
        except Exception as exc:
            reason = reason_of(exc)
            logging.warning("The copy did not go to Google Drive (%s): %r", reason, exc)
            failed = state.after_failure(self.ctx.now(), reason)
            await self._write_state(failed)
            if backup_events.drive_reported(reason, failed.failures_in_row):
                await self._report(reason, failed)
            return reason
        logging.info("The copy went to Google Drive: %s (%d in the folder)", copy.path.name, kept)
        await self._write_state(state.after_success(self.ctx.now(), copy.path.name, kept))
        return None

    async def _attempt(self, token: DriveToken, copy: backup.Copy) -> int:
        """Steps 1–6 of spec 4.4; returns how many archives the folder keeps after the rotation. The requests are cut at
        5 minutes; the archive (a fraction of a second) is made before, so no worker thread still writes it when the
        attempt ends and it is deleted."""
        password = self.drive.settings.password
        archive = copy.path.parent / UPLOAD_FOLDER / archive_name(copy.path)
        try:
            await asyncio.to_thread(make_archive, copy.path, archive, password)
            content = await asyncio.to_thread(archive.read_bytes)
            async with asyncio.timeout(ATTEMPT_SECONDS):
                return await self._upload(token, archive.name, content)
        finally:
            try:
                await asyncio.to_thread(archive.unlink, True)
            except OSError as exc:
                logging.warning("The archive of the copy was not deleted: %s (%r)", archive, exc)

    async def _upload(self, token: DriveToken, name: str, content: bytes) -> int:
        folder = await self._folder(token)
        files = await self._call(token, lambda access: self.api.list_folder(access, folder))
        if not any(file.name == name and file.size == len(content) for file in files):
            sent = await self._call(token, lambda access: self.api.upload(access, folder, name, content))
            files = [file for file in files if file.id != sent.id] + [sent]
        else:
            logging.info("Google Drive already has %s: it is not sent again", name)
        return await self._rotate(token, files)

    async def _folder(self, token: DriveToken) -> str:
        """The folder «Трекер — копии»: the one of the token file while Google has it, else found by its name, else
        made; a new id is written to the token file."""
        known = token.folder_id
        if known and await self._call(token, lambda access: self.api.folder_alive(access, known)):
            return known
        folder = await self._call(token, lambda access: self.api.find_folder(access, FOLDER_NAME))
        if folder is None:
            folder = await self._call(token, lambda access: self.api.create_folder(access, FOLDER_NAME))
            logging.info("The folder «%s» is made in Google Drive", FOLDER_NAME)
        await asyncio.to_thread(self._remember_folder, token, folder)
        return folder

    def _remember_folder(self, token: DriveToken, folder: str) -> None:
        """The folder id into the token file, unless the owner connected anew (or disconnected) meanwhile."""
        current = self.files.token()
        if current is not None and current.refresh_token == token.refresh_token:
            self.files.write_token(dataclasses.replace(current, folder_id=folder))

    async def _rotate(self, token: DriveToken, files: list[DriveFile]) -> int:
        """All but the 30 newest of the app's own archives deleted; a failed delete stays counted, with a warning."""
        own = own_archives(files)
        kept = len(own)
        for file in own[KEPT_IN_DRIVE:]:
            try:
                await self._call(token, lambda access, file=file: self.api.delete(access, file.id))
                kept -= 1
            except Exception as exc:
                logging.warning("An old archive in Google Drive was not deleted: %s (%r)", file.name, exc)
        return kept

    async def _call(self, token: DriveToken, request: Callable[[str], Awaitable[T]]) -> T:
        """One Drive request with the access token; a 401 renews the token once and repeats the request once."""
        try:
            return await request(await self._access_token(token))
        except GoogleError as exc:
            if exc.status != 401:
                raise
        self._access = None
        try:
            return await request(await self._access_token(token))
        except GoogleError as exc:
            if exc.status == 401:
                raise SignInRefused("Google answered 401 after a new access token") from exc
            raise

    async def _access_token(self, token: DriveToken) -> str:
        now = self.ctx.now()
        if self._access is not None:
            refresh, access, until = self._access
            if refresh == token.refresh_token and now < until - TOKEN_MARGIN:
                return access
        access, lasts = await self.api.refresh(token.refresh_token)
        self._access = (token.refresh_token, access, now + timedelta(seconds=lasts))
        return access

    # --- the state and the report ----------------------------------------------------------------

    async def _write_state(self, state: DriveState) -> None:
        try:
            await asyncio.to_thread(self.files.write_state, state)
        except OSError as exc:
            logging.warning("The state of the Google Drive copy cannot be written: %r", exc)

    async def _report(self, reason: str, state: DriveState) -> None:
        """Queue «⚠️ Копия в Google Drive не ушла…»: at most one a day (the key carries the owner's date), no title."""
        try:
            rules = await self.settings.delivery_rules()
            local_now = rules.local(self.ctx.now())
            success = state.last_success_at
            last = moment_in_words(rules.local(success), local_now) if success else None
            key = backup_events.dedup_key(backup_events.DRIVE, local_now.date())
            text = backup_events.drive_text(reason, last)
            await self.queue.record_event(backup_events.BACKUP_FAILED, {"text": text}, key)
        except Exception as exc:  # the report is no reason to stop the job
            logging.warning("The report of the copy that did not go to Google Drive was not made: %r", exc)
