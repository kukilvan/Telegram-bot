"""The event «copy not made» (pure): the reasons, the messages of both kinds (on this PC, to Google Drive), the once-a-day key and the samples of «Тестовое событие».

It sits next to `failures.py` (the same kind of message: a failure the owner can do something about) but in a module of
its own (rule 7): `failures.py` is about titles that could not be checked, this one is about copies. The event has no
title, so the Feed does not show it; it is delivered by the delivery rules. The Google Drive reasons (spec 4.6 of stage
7.1) are keys stored in `google_drive_state.json`; their texts and the rule «at once or at the 2nd failure in a row»
live here, the notice after «Сделать копию сейчас» and the line of Settings take the same texts.
"""

import errno
import sqlite3
from datetime import date

BACKUP_FAILED = "backup_failed"  # event type

LOCAL = "local"  # the kind of the copy on this PC
DRIVE = "drive"  # the kind of the copy to Google Drive

# the reasons of a copy that did not go to Google Drive (spec 4.6), as stored in the state file
CONNECTION = "connection"  # no answer, DNS, timeout
SIGN_IN = "sign_in"  # invalid_grant on refresh, 401 after a refresh, the token file gone
FULL = "full"  # 403 storageQuotaExceeded
DOWN = "down"  # 5xx, 429, 403 rateLimitExceeded / userRateLimitExceeded
NO_COPY = "no_copy"  # no copy on the PC to send
UNKNOWN = "unknown"  # anything else, the archive too
DRIVE_REASONS: dict[str, str] = {
    CONNECTION: "нет связи с Google Drive",
    SIGN_IN: "Google Drive не принял вход — подключите его заново в Настройках",
    FULL: "в Google Drive нет места",
    DOWN: "Google Drive сейчас недоступен",
    NO_COPY: "на этом ПК нет копии базы",
    UNKNOWN: "неизвестная ошибка, подробности в журнале",
}
REPORTED_AT_ONCE = frozenset({SIGN_IN, FULL, NO_COPY})  # the others wait for the 2nd failure in a row
RETRY = "Попробую снова через час."

NO_SPACE = "на диске нет места"
OTHER_ERROR = "ошибка, подробности в журнале"
SAMPLE_LAST = "вчера в 18:32"


def reason_of(exc: BaseException) -> str:
    """The reason of a failed copy for the owner: no room on the disk (the file system says so, or SQLite does while it
    writes the copy), else «ошибка, подробности в журнале»; the text of the exception stays in the log."""
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return NO_SPACE
    if isinstance(exc, sqlite3.OperationalError) and getattr(exc, "sqlite_errorcode", None) == sqlite3.SQLITE_FULL:
        return NO_SPACE
    return OTHER_ERROR


def dedup_key(kind: str, day: date) -> str:
    """One report of each kind a day; `day` is the owner's date."""
    return f"{BACKUP_FAILED}:{kind}:{day.isoformat()}"


def local_text(reason: str, last: str | None) -> str:
    """«⚠️ Копия базы не сделана: на диске нет места. Последняя — вчера в 18:32. Попробую снова через час.»; `last` is
    the newest copy in words, None when the PC has none."""
    after = f"Последняя — {last}." if last else "Копий базы на этом ПК пока нет."
    return f"⚠️ Копия базы не сделана: {reason}. {after} Попробую снова через час."


def drive_reason(key: str | None) -> str:
    """The text of a reason key; a key this version does not know (a state file of another version) — «unknown»."""
    return DRIVE_REASONS.get(key or UNKNOWN, DRIVE_REASONS[UNKNOWN])


def drive_reported(reason: str, failures_in_row: int) -> bool:
    """Whether this failure is reported: at once for a reason the owner has to act on, otherwise from the 2nd failure in
    a row (a lone hiccup of the connection is not worth a message). The once-a-day key cuts the repeats."""
    return reason in REPORTED_AT_ONCE or failures_in_row >= 2


def drive_text(reason: str, last: str | None) -> str:
    """«⚠️ Копия в Google Drive не ушла: нет связи с Google Drive. Последняя удачная — вчера в 18:32. Попробую снова
    через час.»; `last` is the last success in words, None when none went yet. For `sign_in` nothing is retried, so the
    last sentence is left out."""
    after = f"Последняя удачная — {last}." if last else "Удачных копий там ещё не было."
    retry = "" if reason == SIGN_IN else f" {RETRY}"
    return f"⚠️ Копия в Google Drive не ушла: {drive_reason(reason)}. {after}{retry}"


# (id, menu label, message text) of the samples of «Тестовое событие»
TEST_SAMPLES: list[tuple[str, str, str]] = [
    ("backup-failed-local", "Копия базы не сделана", local_text(NO_SPACE, SAMPLE_LAST)),
    ("backup-failed-drive", "Копия в Google Drive не ушла", drive_text(CONNECTION, SAMPLE_LAST)),
]
