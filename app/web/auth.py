"""The web login without the web framework: the password rules, the signing key, the mark of the sign-ins file, the lock after wrong tries.

The lock keeps no file itself: `SignIns` of `app/web/sessions.py` builds it from `data/web_login.json` and writes its
`state` back, so a restart does not open the login (KI-7). A key file shorter than 32 bytes is made anew (KI-13)."""

import hmac
import logging
import math
import os
import secrets
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

MIN_PASSWORD_LENGTH = 8  # shorter secrets are not masked in the log (`secrets_mask._MIN_SECRET_LEN`)
MAX_INPUT_LENGTH = 1024  # a longer input is "wrong" without being compared
MAX_NEXT_LENGTH = 200
MAX_WRONG_TRIES = 5
LOCK_SECONDS = 15 * 60
KEY_BYTES = 32
FINGERPRINT_LENGTH = 32
SPOILED_KEY = "%s был испорчен и создан заново: на всех устройствах нужен новый вход"


def login_configured(password: str) -> bool:
    return len(password) >= MIN_PASSWORD_LENGTH


def password_matches(typed: str, password: str) -> bool:
    """Constant-time comparison of the bytes; an overlong input is wrong without being compared."""
    if len(typed) > MAX_INPUT_LENGTH:
        return False
    return hmac.compare_digest(typed.encode("utf-8"), password.encode("utf-8"))


def fingerprint(key: bytes, password: str) -> str:
    """What the session keeps instead of the password: change WEB_PASSWORD and every old sign-in stops matching."""
    return hmac.new(key, password.encode("utf-8"), sha256).hexdigest()[:FINGERPRINT_LENGTH]


def login_mark(key: bytes, password: str) -> str:
    """What `data/web_login.json` keeps to know that the password and the key are still the ones its sign-ins were made
    under (KI-75): 64 hex characters, HMAC-SHA256 with the key over `web_login.json:` and the password. It is not the
    fingerprint of the cookie, and the password is not in it."""
    return hmac.new(key, f"web_login.json:{password}".encode("utf-8"), sha256).hexdigest()


def same(value: object, expected: str) -> bool:
    """A fingerprint from the session against the expected one, in constant time."""
    return isinstance(value, str) and hmac.compare_digest(value.encode("utf-8"), expected.encode("utf-8"))


def safe_next(value: str | None) -> str:
    """Where to go after the login: only an address of this site (one `/`, not `//` or `/\\`, no scheme, no control
    characters, not long); anything else is the home page."""
    if (
        value and len(value) <= MAX_NEXT_LENGTH and value.startswith("/") and not value.startswith("//")
        and "\\" not in value and all(32 <= ord(char) != 127 for char in value)
    ):
        return value
    return "/"


def _write_key(file: Path, key: bytes, *, replace: bool) -> None:
    """The key into `file` with rights for the owner only: a new file at once, a spoiled one by a temporary file moved
    over it."""
    file.parent.mkdir(parents=True, exist_ok=True)
    target = file.with_name(f".{file.name}.{secrets.token_hex(4)}.tmp") if replace else file
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(key)
        if replace:
            os.replace(target, file)
    except BaseException:
        if replace:
            target.unlink(missing_ok=True)
        raise


def load_key(file: Path | None) -> bytes:
    """The key that signs the session cookie: 32 random bytes in `file`, made on the first run so that a sign-in
    survives a restart; a file shorter than that is spoiled and is made anew (every device signs in again). A file that
    cannot be read or written — the key lives in memory until the restart."""
    if file is not None:
        try:
            if file.exists():
                key = file.read_bytes()
                if len(key) >= KEY_BYTES:
                    return key
                key = secrets.token_bytes(KEY_BYTES)
                _write_key(file, key, replace=True)
                logging.warning(SPOILED_KEY, file.as_posix())
                return key
            key = secrets.token_bytes(KEY_BYTES)
            _write_key(file, key, replace=False)
            return key
        except OSError as exc:
            logging.warning("%s: ключ сессий не прочитать и не записать (%r), он только в памяти "
                            "(после перезапуска нужен новый вход)", file, exc)
    return secrets.token_bytes(KEY_BYTES)


def unused_key() -> bytes:
    """A key for the session middleware when the login is closed: it signs nothing that could be accepted later."""
    return secrets.token_bytes(KEY_BYTES)


class LoginGuard:
    """The wrong tries in a row, one count for the whole app (the owner is one, and every request comes from the same
    Docker gateway address). The fifth wrong one locks the login for 15 minutes; while locked even the right password
    is not looked at and the lock is not extended. `clock` is the wall clock in UTC seconds: the count and the end of a
    lock are kept in `data/web_login.json` (`state`, written by `SignIns`), so they survive a restart. A clock moved back
    can lengthen a lock by the shift — accepted."""

    def __init__(self, clock: Callable[[], float], *, wrong: int = 0, locked_until: float | None = None) -> None:
        self._clock = clock
        self._wrong = wrong
        self._locked_until = locked_until

    @property
    def state(self) -> tuple[int, float | None]:
        """The count and the end of the lock (UTC seconds), as the file keeps them."""
        return self._wrong, self._locked_until

    def locked_for(self) -> int:
        """Seconds the login stays locked (rounded up); 0 when it is open. The end of a lock starts the count anew."""
        if self._locked_until is None:
            return 0
        left = self._locked_until - self._clock()
        if left <= 0:
            self._locked_until = None
            self._wrong = 0
            return 0
        return math.ceil(left)

    def wrong(self) -> int:
        """A wrong try. Returns how many are left before the lock; 0 means the lock has just begun."""
        self._wrong += 1
        left = MAX_WRONG_TRIES - self._wrong
        if left <= 0:
            self._locked_until = self._clock() + LOCK_SECONDS
            return 0
        return left

    def right(self) -> None:
        self._wrong = 0

    @property
    def wrong_in_a_row(self) -> int:
        return self._wrong
