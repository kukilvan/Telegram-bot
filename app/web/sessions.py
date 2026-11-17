"""The web sign-ins kept on the server: the store of `data/web_login.json` and the middleware of the session cookie.

The store (`SignIns`, spec 4.1 of stage 7.2, ADR 0014) keeps the sign-ins (`sid` → since, seen, device), the last login
and the lock count of the login (`LoginGuard` of `auth`). It is held in memory; every change is written at once to a
temporary file in the same folder and moved over the old one (`os.replace`), off the event loop. An absent file is empty;
a spoiled one (not JSON, another version, a wrong shape) is empty with a warning and is rewritten at the next change; a
file that cannot be read or written leaves everything in memory until the restart. A restore never touches it.

The middleware (`SessionCookies`, 4.2) gives `request.session` exactly as Starlette's `SessionMiddleware` does, signed the
same way (`itsdangerous`, the key of `data/web_secret`), but builds the cookie itself so that `Secure` can be chosen per
request (`secure`, off until ticket 04). Who is signed in is decided in one place, `guard_sign_in` of `app/web/app.py`,
with `SignIns.live`: the cookie alone signs nobody in."""

import asyncio
import json
import logging
import math
import os
import re
import secrets
import threading
import time
from base64 import b64decode, b64encode
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import itsdangerous
from itsdangerous.exc import BadSignature
from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import Session
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.web.auth import LoginGuard

VERSION = 1
COOKIE = "tracker_session"
LIFE_SECONDS = 30 * 24 * 60 * 60  # of the cookie from the last request, and of a sign-in from its last `seen`
SEEN_STEP_SECONDS = 60 * 60  # `seen` is written at most once an hour per sign-in
MAX_SIGN_INS = 20  # beyond that the one used least recently is dropped
UNKNOWN_DEVICE = "неизвестное устройство"
MOMENT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"  # UTC
SID = re.compile(r"[0-9a-f]{32}")
SPOILED = "%s испорчен — все входы закрыты, счётчик неверных паролей обнулён"
UNREADABLE = "%s не прочитать (%r): входы и счётчик неверных паролей только в памяти до перезапуска"
UNWRITABLE = "%s не записать (%r): входы и счётчик неверных паролей только в памяти до перезапуска"


def device_words(user_agent: str) -> str:
    """The device of a sign-in in words, never the raw `User-Agent`. A seam: ticket 05 of stage 7.2 puts the words of
    `app/web/devices.py` here; until then every device is unknown."""
    return UNKNOWN_DEVICE


@dataclass
class SignIn:
    """One browser where the password was typed; moments are UTC seconds."""

    since: int
    seen: int
    device: str


@dataclass(frozen=True)
class LastLogin:
    at: int  # UTC seconds
    device: str
    address: str | None  # a public address only (ticket 04); None here

    @property
    def moment(self) -> datetime:
        """The moment as a naive UTC time, as the core reads moments."""
        return datetime.fromtimestamp(self.at, timezone.utc).replace(tzinfo=None)


def _seconds_of(value: object) -> int:
    if not isinstance(value, str):
        raise ValueError("a moment is a text")
    return int(datetime.strptime(value, MOMENT_FORMAT).replace(tzinfo=timezone.utc).timestamp())


def _text_of(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, timezone.utc).strftime(MOMENT_FORMAT)


def _words(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("a text is expected")
    return value


def _read(document: Any) -> tuple[dict[str, SignIn], LastLogin | None, int, float | None]:
    """The file's document read strictly: anything off its shape raises (`ValueError`, `TypeError`, `KeyError`,
    `AttributeError`)."""
    if not isinstance(document, dict) or document.get("version") != VERSION:
        raise ValueError("another version")
    sessions: dict[str, SignIn] = {}
    for sid, record in document["sessions"].items():
        if not SID.fullmatch(sid):
            raise ValueError("not a sid")
        sessions[sid] = SignIn(_seconds_of(record["since"]), _seconds_of(record["seen"]), _words(record["device"]))
    last = document["last_login"]
    last_login = None if last is None else LastLogin(
        _seconds_of(last["at"]), _words(last["device"]), None if last["address"] is None else _words(last["address"])
    )
    guard = document["guard"]
    wrong, locked = guard["wrong"], guard["locked_until"]
    if type(wrong) is not int or wrong < 0:
        raise ValueError("not a count")
    return sessions, last_login, wrong, None if locked is None else float(_seconds_of(locked))


class SignIns:
    """The sign-ins, the last login and the lock of the login, in memory and in `file` (None: in memory only). `clock`
    is the wall clock in UTC seconds; the lock (`guard`) runs on it too, so it survives a restart."""

    def __init__(self, file: Path | None, clock: Callable[[], float] = time.time) -> None:
        self.file = file
        self._clock = clock
        self._sessions, self._last_login, wrong, locked_until = self._load()
        self.guard = LoginGuard(clock, wrong=wrong, locked_until=locked_until)
        self._guard_written = self.guard.state
        self._write_lock = threading.Lock()
        self._number = 0  # of the last document handed to a write
        self._written = 0  # of the last document written (or given up)
        self._failing = False  # the last write failed: the next failure is not logged again

    def _load(self) -> tuple[dict[str, SignIn], LastLogin | None, int, float | None]:
        """Read once at start, before the web serves anything."""
        empty: tuple[dict[str, SignIn], LastLogin | None, int, float | None] = ({}, None, 0, None)
        if self.file is None:
            return empty
        try:
            text = self.file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return empty
        except OSError as exc:
            logging.warning(UNREADABLE, self.file.as_posix(), exc)
            return empty
        try:
            return _read(json.loads(text))
        except (ValueError, TypeError, KeyError, AttributeError):
            logging.warning(SPOILED, self.file.as_posix())
            return empty

    def _now(self) -> int:
        return int(self._clock())

    def live(self, sid: object) -> bool:
        """Whether `sid` is a sign-in whose last request is under 30 days old."""
        record = self._sessions.get(sid) if isinstance(sid, str) else None
        return record is not None and self._clock() - record.seen < LIFE_SECONDS

    @property
    def count(self) -> int:
        """The live sign-ins."""
        return sum(1 for sid in self._sessions if self.live(sid))

    @property
    def last_login(self) -> LastLogin | None:
        return self._last_login

    async def touch(self, sid: str) -> None:
        """A request of a live sign-in: its `seen` moves to now when it is over an hour old."""
        record = self._sessions.get(sid)
        now = self._now()
        if record is not None and now - record.seen >= SEEN_STEP_SECONDS:
            record.seen = now
            await self._save()

    async def sign_in(self, device: str, address: str | None, *, replacing: object = None) -> str:
        """The right password: a new sign-in (the one of `replacing`, this browser's previous one, ends), the last login
        replaced. Returns its `sid`. The lock count is written with it (`guard.right()` is the caller's)."""
        now = self._now()
        if isinstance(replacing, str):
            self._sessions.pop(replacing, None)
        sid = secrets.token_hex(16)
        self._sessions[sid] = SignIn(now, now, device)
        while len(self._sessions) > MAX_SIGN_INS:  # the oldest `seen` goes; of equal ones the earliest made
            del self._sessions[min(self._sessions, key=lambda key: self._sessions[key].seen)]
        self._last_login = LastLogin(now, device, address)
        await self._save()
        return sid

    async def end(self, sid: object) -> None:
        """«Выйти»: this sign-in ends; a copy of its cookie no longer works."""
        if isinstance(sid, str) and self._sessions.pop(sid, None) is not None:
            await self._save()

    async def end_all(self) -> int:
        """«Выйти на всех устройствах»: every sign-in ends; the last login and the lock stay. Returns how many lived."""
        ended = self.count
        self._sessions.clear()
        await self._save()
        return ended

    async def save_guard(self) -> None:
        """Writes the lock count when `guard` changed it (a wrong try, a reset, the end of a lock)."""
        if self.guard.state != self._guard_written:
            await self._save()

    def _document(self) -> dict[str, Any]:
        now = self._now()
        for sid in [sid for sid, record in self._sessions.items() if now - record.seen >= LIFE_SECONDS]:
            del self._sessions[sid]  # 30 days without a request: dropped at the next write
        wrong, locked_until = self._guard_written = self.guard.state
        last = self._last_login
        return {
            "version": VERSION,
            "sessions": {
                sid: {"since": _text_of(record.since), "seen": _text_of(record.seen), "device": record.device}
                for sid, record in self._sessions.items()
            },
            "last_login": None if last is None else {"at": _text_of(last.at), "device": last.device, "address": last.address},
            # rounded up: a lock read back from the file never ends earlier than it should
            "guard": {"wrong": wrong, "locked_until": None if locked_until is None else _text_of(math.ceil(locked_until))},
        }

    async def _save(self) -> None:
        """The state as it is now goes to the file, in a thread. The document is taken here, on the event loop; a write
        that comes after a newer one has been written is skipped."""
        if self.file is None:
            return
        self._number += 1
        await asyncio.to_thread(self._write, self._number, self._document())

    def _write(self, number: int, document: dict[str, Any]) -> None:
        assert self.file is not None
        with self._write_lock:
            if number < self._written:
                return
            self._written = number
            temporary = self.file.with_name(f".{self.file.name}.{secrets.token_hex(4)}.tmp")
            try:
                self.file.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                try:
                    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                        json.dump(document, stream, ensure_ascii=False, indent=1)
                    os.replace(temporary, self.file)
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            except OSError as exc:
                if not self._failing:
                    logging.warning(UNWRITABLE, self.file.as_posix(), exc)
                self._failing = True
                return
            self._failing = False


def cookie_header(value: str, *, secure: bool, clear: bool = False) -> str:
    """The `Set-Cookie` of the session: `HttpOnly`, `SameSite=Lax`, `Path=/`, 30 days (or gone at once when `clear`),
    `Secure` when the request came over `https`."""
    life = "expires=Thu, 01 Jan 1970 00:00:00 GMT" if clear else f"Max-Age={LIFE_SECONDS}"
    return f"{COOKIE}={value}; path=/; {life}; httponly; samesite=lax" + ("; secure" if secure else "")


class SessionCookies:
    """`request.session` from the signed cookie, as Starlette's `SessionMiddleware` gives it: a changed session is sent
    anew (30 days from now), a cleared one removes the cookie. A cookie with a bad or over 30-day-old signature is an
    empty session. `secure` tells, per request, whether the cookie gets `Secure`."""

    def __init__(self, app: ASGIApp, *, key: bytes, secure: Callable[[Scope], bool] = lambda scope: False) -> None:
        self.app = app
        self.signer = itsdangerous.TimestampSigner(key.hex())  # the same signing as before: old cookies still read
        self.secure = secure

    def _session_of(self, scope: Scope) -> Session | None:
        raw = HTTPConnection(scope).cookies.get(COOKIE)
        if raw is None:
            return None
        try:
            data = json.loads(b64decode(self.signer.unsign(raw.encode("utf-8"), max_age=LIFE_SECONDS)))
        except (BadSignature, ValueError):
            return None
        return Session(data) if isinstance(data, dict) else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        found = self._session_of(scope)
        scope["session"] = found if found is not None else Session()

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                session: Session = scope["session"]
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                if session.accessed:
                    headers.add_vary_header("Cookie")
                if session.modified and session:
                    value = self.signer.sign(b64encode(json.dumps(session).encode("utf-8"))).decode("utf-8")
                    headers.append("Set-Cookie", cookie_header(value, secure=self.secure(scope)))
                elif session.modified and found is not None:
                    headers.append("Set-Cookie", cookie_header("null", secure=self.secure(scope), clear=True))
            await send(message)

        await self.app(scope, receive, send_with_cookie)
