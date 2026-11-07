"""The event «copy not made» (pure): the reasons, the message, the once-a-day key and the sample of «Тестовое событие».

It sits next to `failures.py` (the same kind of message: a failure the owner can do something about) but in a module of
its own (rule 7): `failures.py` is about titles that could not be checked, this one is about copies and will also carry
the Google Drive kind. The event has no title, so the Feed does not show it; it is delivered by the delivery rules.
"""

import errno
import sqlite3
from datetime import date

BACKUP_FAILED = "backup_failed"  # event type

LOCAL = "local"  # the kind of the copy on this PC; the Google Drive kind joins it later

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


# (id, menu label, message text) of the samples of «Тестовое событие»
TEST_SAMPLES: list[tuple[str, str, str]] = [
    ("backup-failed-local", "Копия базы не сделана", local_text(NO_SPACE, SAMPLE_LAST)),
]
