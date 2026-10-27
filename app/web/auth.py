"""The web login without the web framework: the password rules, the signing key, the lock after wrong tries."""

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


def load_key(file: Path | None) -> bytes:
    """The key that signs the session cookie: 32 random bytes in `file`, made on the first run so that a sign-in
    survives a restart. A file that cannot be read or made — the key lives in memory until the restart."""
    if file is not None:
        try:
            if file.exists():
                key = file.read_bytes()
                if len(key) >= KEY_BYTES:
                    return key
                logging.warning("%s: файл ключа сессий повреждён, ключ только в памяти "
                                "(после перезапуска нужен новый вход)", file)
            else:
                key = secrets.token_bytes(KEY_BYTES)
                file.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(key)
                return key
        except OSError as exc:
            logging.warning("%s: ключ сессий не прочитать и не создать (%r), он только в памяти "
                            "(после перезапуска нужен новый вход)", file, exc)
    return secrets.token_bytes(KEY_BYTES)


class LoginGuard:
    """The wrong tries in a row, one count for the whole app (the owner is one, and every request comes from the same
    Docker gateway address). The fifth wrong one locks the login for 15 minutes; while locked even the right password
    is not looked at and the lock is not extended. In memory: a restart clears it."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._wrong = 0
        self._locked_until: float | None = None

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
