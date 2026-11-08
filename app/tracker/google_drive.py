"""The connection of the Google Drive copy: whether it is on, the sign-in to Google and the sign-out, and the files of the connection in `data/`.

Rules: sections 4.1–4.3 and 4.7 of the spec of stage 7.1, ADR 0012. Whether the copy is on is decided in one place,
`DriveSettings.setup`. The sign-in is allowed only on this PC (`localhost`, `127.0.0.1`): one pending sign-in lives in
memory for 10 minutes (a new press replaces it, a restart forgets it); Google's answer is checked against its `state`
and its code is changed for a refresh token, which goes to `google_drive_token.json` — nothing is stored on a failure.
Where Google sends the owner back is one switch, `REDIRECT` (settled live, `.scratch/7-1-backups-export/checks.md`).
The files live next to the database, outside it, so a restore never brings back an old connection; they are read and
written in a worker thread (rule 1), written through a temporary file and `os.replace`, the token file with the rights
of the app's user only. A spoiled file reads as absent, with a warning. The token is never logged or shown.
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.tracker import drive_rows
from app.tracker.context import CoreContext
from app.tracker.drive_rows import DrivePart, DriveSetup

MIN_PASSWORD_LENGTH = 12  # BACKUP_PASSWORD, after the outer spaces are dropped
SIGN_IN_LASTS = timedelta(minutes=10)
TOKEN_FILE = "google_drive_token.json"
STATE_FILE = "google_drive_state.json"  # written by the sending (ticket 04); read and removed here
CALLBACK_PATH = "/settings/google-drive/callback"
SETTINGS_PATH = "/settings"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})
STATE_BYTES = 32
VERIFIER_BYTES = 64  # 86 characters: PKCE wants 43 to 128


class Redirect(Enum):
    """Where Google sends the owner back after the sign-in (spec 4.2, the risk paragraph), in the order of trying."""

    CALLBACK = "callback"  # http://<host of the request>/settings/google-drive/callback, on localhost or 127.0.0.1
    LOOPBACK_IP = "loopback_ip"  # the same path on 127.0.0.1 only: from localhost the owner is sent there first
    ROOT = "root"  # http://<host of the request>/ — the Feed's address takes the answer


REDIRECT = Redirect.CALLBACK  # the way Google accepts with the owner's client «Desktop app»


@dataclass(frozen=True)
class DriveSettings:
    """The values of `.env` for the Google Drive copy (spec 4.1), already stripped, and the port of the web on the PC."""

    client_id: str = ""
    client_secret: str = ""
    password: str = ""  # BACKUP_PASSWORD
    web_port: int = 8080  # WEB_PORT: the sentence for a page opened not on this PC

    @property
    def setup(self) -> DriveSetup:
        """The one place that decides whether the copy is on: the client id, its secret and a password of 12 or more."""
        if not (self.client_id and self.client_secret):
            return DriveSetup.OFF
        return DriveSetup.ON if len(self.password) >= MIN_PASSWORD_LENGTH else DriveSetup.NO_PASSWORD


@dataclass(frozen=True)
class DriveToken:
    """The content of `google_drive_token.json`."""

    refresh_token: str
    connected_at: datetime  # naive UTC
    folder_id: str | None = None  # the folder «Трекер — копии»; found or made by the sending (ticket 04)


@dataclass(frozen=True)
class SignInStep:
    """Where «Подключить Google Drive» leads: `address` to open (Google's page, or Settings on 127.0.0.1 first), or back
    to Settings with `notice` ("" — no notice)."""

    address: str = ""
    notice: str = ""


@dataclass(frozen=True)
class _Pending:
    state: str
    verifier: str
    redirect_uri: str
    made_at: datetime  # naive UTC


def hostname_of(host: str) -> str:
    """The name in a `Host` header («localhost:8080» → «localhost»); "" for one that cannot be read."""
    try:
        return (urlsplit(f"//{host}").hostname or "").lower()
    except ValueError:
        return ""


def port_of(host: str) -> int | None:
    try:
        return urlsplit(f"//{host}").port
    except ValueError:
        return None


def is_this_pc(host: str) -> bool:
    """Whether the page is opened on this PC: the one rule of the sign-in and of the button in Settings."""
    return hostname_of(host) in LOCAL_HOSTS


def challenge_of(verifier: str) -> str:
    """The PKCE S256 challenge: base64url of the SHA-256 of the verifier, without padding."""
    hashed = bytes.fromhex(hashlib.sha256(verifier.encode("ascii")).hexdigest())
    return base64.urlsafe_b64encode(hashed).rstrip(b"=").decode("ascii")


def clean_error(error: str) -> str:
    """Google's error code as it may stand in a notice: letters, digits, `_`, `.`, `-`, at most 60."""
    return re.sub(r"[^\w.-]", "", error)[:60] or "?"


class DriveFiles:
    """The two files of the connection in the folder of the database; no folder (a core without a database file) — no
    files, nothing written."""

    def __init__(self, folder: Path | None) -> None:
        self.folder = folder

    def token(self) -> DriveToken | None:
        """The token file; absent, unreadable or spoiled — None (the last two with a warning)."""
        data = self._read(TOKEN_FILE)
        if data is None:
            return None
        try:
            refresh_token, connected_at = data["refresh_token"], data["connected_at"]
            folder_id = data.get("folder_id")
            if not (isinstance(refresh_token, str) and refresh_token and isinstance(connected_at, str)):
                raise ValueError("refresh_token or connected_at is not a text")
            if folder_id is not None and not isinstance(folder_id, str):
                raise ValueError("folder_id is not a text")
            return DriveToken(refresh_token, datetime.fromisoformat(connected_at), folder_id)
        except (KeyError, ValueError) as exc:
            logging.warning("%s is spoiled, Google Drive counts as not connected: %r", TOKEN_FILE, exc)
            return None

    def state(self) -> dict[str, Any] | None:
        """The state of the sending (ticket 04 gives it its fields); absent or spoiled — None: no attempts yet."""
        return self._read(STATE_FILE)

    def write_token(self, token: DriveToken) -> None:
        content = {
            "refresh_token": token.refresh_token,
            "connected_at": token.connected_at.isoformat(timespec="seconds"),
            "folder_id": token.folder_id,
        }
        self._write(TOKEN_FILE, json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8"))

    def forget(self) -> None:
        """Both files removed (the sign-out); one that is not there is fine, one that cannot be removed is a warning."""
        if self.folder is None:
            return
        for name in (TOKEN_FILE, STATE_FILE):
            try:
                (self.folder / name).unlink(missing_ok=True)
            except OSError as exc:
                logging.warning("%s cannot be removed: %r", name, exc)

    def _read(self, name: str) -> dict[str, Any] | None:
        if self.folder is None:
            return None
        path = self.folder / name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:  # unreadable, not UTF-8, not JSON
            logging.warning("%s cannot be read, it counts as absent: %r", name, exc)
            return None
        if not isinstance(data, dict):
            logging.warning("%s is spoiled (not a JSON object), it counts as absent", name)
            return None
        return data

    def _write(self, name: str, content: bytes) -> None:
        """Atomically, with the rights of the app's user only (0600): a temporary file, then `os.replace`."""
        if self.folder is None:
            raise RuntimeError("no folder for the files of the Google Drive copy")
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / name
        temporary = path.with_name(path.name + ".tmp")
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)  # a temporary file left from before keeps its old rights under O_CREAT
        os.replace(temporary, path)


class GoogleDrive:
    """The Google Drive copy's connection for the owner. `api` is the Google client (`GoogleDriveApi`); `folder` the
    folder of the files (that of the database)."""

    def __init__(self, ctx: CoreContext, settings: DriveSettings, api: Any, folder: Path | None) -> None:
        self.ctx = ctx
        self.settings = settings
        self.api = api
        self.files = DriveFiles(folder)
        self._pending: _Pending | None = None
        # The seam of ticket 04: after a successful sign-in it finds or makes the folder and sends the newest copy, in
        # the background. None until the sending exists: the sign-in only stores the token
        self.on_connected: Callable[[], Awaitable[None]] | None = None
        self._background: set[asyncio.Task[None]] = set()

    @property
    def _on(self) -> bool:
        return self.settings.setup is DriveSetup.ON and self.api is not None

    async def part(self, host: str) -> DrivePart:
        """The Google Drive part of the Settings block for a page opened at `host`."""
        connected = await asyncio.to_thread(self.files.token) is not None
        return drive_rows.drive_part(self.settings.setup, connected, is_this_pc(host), self.settings.web_port)

    async def sign_in(self, host: str) -> SignInStep:
        """«Подключить Google Drive» on a page opened at `host` (with its port): the address of Google's page, with a
        new pending sign-in in place of the old one; on another host only the notice; with the copy not on — nothing."""
        if not self._on:
            return SignInStep()
        if not is_this_pc(host):
            return SignInStep(notice=drive_rows.only_here(self.settings.web_port))
        host = host.lower()
        if REDIRECT is Redirect.LOOPBACK_IP and hostname_of(host) != "127.0.0.1":
            port = port_of(host) or self.settings.web_port
            return SignInStep(address=f"http://127.0.0.1:{port}{SETTINGS_PATH}")
        path = "/" if REDIRECT is Redirect.ROOT else CALLBACK_PATH
        pending = _Pending(
            secrets.token_urlsafe(STATE_BYTES), secrets.token_urlsafe(VERIFIER_BYTES), f"http://{host}{path}", self.ctx.now()
        )
        self._pending = pending
        return SignInStep(address=self.api.sign_in_address(pending.redirect_uri, pending.state, challenge_of(pending.verifier)))

    async def signed_in(self, answer: Mapping[str, str]) -> str:
        """Google sent the owner back with `answer` (the query: `code` and `state`, or `error`). Returns the notice for
        Settings ("" — none). The refresh token is stored only when every check passed."""
        if not self._on:
            return ""
        pending = self._take(answer.get("state", ""))
        error = answer.get("error")
        if error is not None:
            logging.info("Google sign-in ended with the error %s", clean_error(error))
            return drive_rows.ACCESS_DENIED if error == "access_denied" else drive_rows.google_refused(clean_error(error))
        if pending is None:
            logging.info("Google sign-in answer with no pending sign-in of that state (stale, restarted or foreign)")
            return drive_rows.NOT_FINISHED
        code = answer.get("code", "")
        if not code:
            logging.warning("Google sign-in answer without a code")
            return drive_rows.NOT_CONFIRMED
        try:
            tokens = await self.api.exchange_code(code, pending.redirect_uri, pending.verifier)
        except Exception as exc:
            logging.warning("Google sign-in: the token request failed: %r", exc)
            return drive_rows.NOT_CONFIRMED
        refresh_token = tokens.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            logging.warning("Google sign-in: the answer has no refresh token (fields: %s)", sorted(tokens))
            return drive_rows.NOT_CONFIRMED
        try:
            await asyncio.to_thread(self.files.write_token, DriveToken(refresh_token, self.ctx.now()))
        except OSError as exc:
            logging.warning("Google sign-in: %s cannot be written: %r", TOKEN_FILE, exc)
            return drive_rows.NOT_CONFIRMED
        logging.info("Google Drive connected")
        if self.on_connected is not None:
            task = asyncio.get_running_loop().create_task(self.on_connected())
            self._background.add(task)
            task.add_done_callback(self._background.discard)
        return drive_rows.CONNECTED

    def _take(self, state: str) -> _Pending | None:
        """The pending sign-in if `state` is its own and it is not over 10 minutes old; one of its own is used up."""
        pending = self._pending
        if pending is None or not secrets.compare_digest(pending.state.encode(), state.encode()):
            return None
        self._pending = None
        return pending if self.ctx.now() - pending.made_at <= SIGN_IN_LASTS else None

    async def sign_out(self) -> str:
        """«Отключить Google Drive»: the refresh token is revoked at Google (a failure is only logged) and both files are
        removed."""
        self._pending = None
        token = await asyncio.to_thread(self.files.token)
        if token is not None and self.api is not None:
            try:
                await self.api.revoke(token.refresh_token)
            except Exception as exc:
                logging.warning("Google Drive: the token could not be revoked, the files are removed anyway: %r", exc)
        await asyncio.to_thread(self.files.forget)
        logging.info("Google Drive disconnected")
        return drive_rows.DISCONNECTED
