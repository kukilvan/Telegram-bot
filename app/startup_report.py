"""Whether a failure before the start is reported to the owner, and the record of it in `data/startup_failure.json`.

Docker starts the process again every minute while the failure lasts; the owner hears of one and the same failure at
once and then at most once a day, of the same place with another text at most once an hour, of another place at once.
A failure has a code (the type and the places in the code) and a text (the message with every word that holds a digit
or a slash masked); the record keeps the SHA-256 of the code and of code and text together. A successful start
removes the record. When `data` cannot be written the record goes to the temp folder, and both files are read.

No network and no settings here: the clock, the files and the sending are handed in, so the tests hand their own.
"""

import hashlib
import json
import logging
import os
import re
import tempfile
import traceback
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, tzinfo
from pathlib import Path

from app.utils.secrets_mask import mask_secrets

REMIND_AFTER = timedelta(hours=24)  # the same failure, the same text
REPORT_AGAIN_AFTER = timedelta(hours=1)  # the same place, another text
TEXT_LENGTH = 300  # of the masked text that goes into the fingerprint
TEMP_FILE_NAME = "release-tracker-startup_failure.json"

_UNSTABLE_WORD = re.compile(r"[\d/\\]")  # temp names, paths, ports and addresses in memory must not make a failure new
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class Fingerprint:
    """What makes a failure the same: `code` (SHA-256 of the type and the places) and `full` (of the code and the text).
    Neither the text nor the traceback can be read back from them."""

    code: str
    full: str


def masked_text(text: str) -> str:
    """The text with secrets masked, every word that holds a digit, `/` or `\\` replaced by `#`, spaces folded, the
    first 300 characters."""
    words = [("#" if _UNSTABLE_WORD.search(word) else word) for word in _SPACE.split(mask_secrets(text).strip())]
    return " ".join(words)[:TEXT_LENGTH]


def fingerprint(exc: BaseException) -> Fingerprint:
    """The fingerprint of an exception: the type, the places (file without folders and function, in order) and the
    masked text. The chain of causes is not part of it."""
    exc_type = f"{type(exc).__module__}.{type(exc).__qualname__}"
    places = [[os.path.basename(frame.filename), frame.name] for frame in traceback.extract_tb(exc.__traceback__)]
    code = [exc_type, places]
    return Fingerprint(_sha256(code), _sha256([*code, masked_text(str(exc))]))


def _sha256(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FailureRecord:
    """The last failure before the start: its code and fingerprint, since when it happens at that place and when the
    owner last got a report (UTC)."""

    code: str
    fingerprint: str
    first_seen: datetime
    reported_at: datetime | None

    @property
    def latest_moment(self) -> datetime:
        """The moment that tells which of two records is the later one."""
        return self.reported_at or self.first_seen


def read_record(file: Path) -> FailureRecord | None:
    """The record in the file; None when there is no file or it cannot be read, makes no sense or is of the old form
    (no `code`)."""
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        first_seen = datetime.fromisoformat(data["first_seen"])
        reported_at = None if data["reported_at"] is None else datetime.fromisoformat(data["reported_at"])
        record = FailureRecord(data["code"], data["fingerprint"], first_seen, reported_at)
    except (OSError, ValueError, TypeError, KeyError):
        return None
    times_aware = all(t is None or t.tzinfo is not None for t in (first_seen, reported_at))
    return record if isinstance(record.code, str) and isinstance(record.fingerprint, str) and times_aware else None


def write_record(file: Path, record: FailureRecord) -> None:
    """Raises OSError when the file cannot be written."""
    data = {
        "code": record.code,
        "fingerprint": record.fingerprint,
        "first_seen": record.first_seen.isoformat(),
        "reported_at": None if record.reported_at is None else record.reported_at.isoformat(),
    }
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data, indent=2), encoding="utf-8")


def temp_file() -> Path:
    """Where the record goes when `data` cannot be written (`/tmp` in the container)."""
    return Path(tempfile.gettempdir()) / TEMP_FILE_NAME


def load_record(file: Path) -> FailureRecord | None:
    """The record of `file` and of the temp folder: the later one (by the report, else by the first sight) wins."""
    records = [record for record in (read_record(file), read_record(temp_file())) if record is not None]
    return max(records, key=lambda record: record.latest_moment, default=None)


def save_record(file: Path, record: FailureRecord) -> None:
    """The record into `file`; when that fails, into the temp folder (a line in the log). Both fail — a warning: the
    next start reports again, better an extra message than silence."""
    try:
        write_record(file, record)
        return
    except OSError as exc_data:
        data_error = exc_data
    temp = temp_file()
    try:
        write_record(temp, record)
    except OSError as exc_temp:
        logging.warning("запись о сбое запуска не сохранилась (%s, %s): %r, %r", file, temp, data_error, exc_temp)
        return
    logging.warning("запись о сбое запуска сохранена во временную папку: %s (data недоступна: %s)", temp, data_error)


@dataclass(frozen=True)
class Decision:
    send: bool
    reminder: bool  # the failure is the one in the record: the report says since when it lasts
    record: FailureRecord  # the record as it stands; `after` gives it once the report went out or did not
    fingerprint: Fingerprint  # of the failure just met

    def after(self, sent: bool, now: datetime) -> FailureRecord:
        """The record to keep: once the report went out it holds the fingerprint just met and the moment; when it did
        not go out the record stays as it stands, so the next start reports again."""
        if not sent:
            return self.record
        return replace(self.record, fingerprint=self.fingerprint.full, reported_at=now)


def decide(fingerprint: Fingerprint, record: FailureRecord | None, now: datetime) -> Decision:
    """Whether to report the failure with this fingerprint, given the record of the last one (table 1.1 of the spec of
    9.1a): a new place, no record and one whose last report did not go out — at once; the same failure — again 24 hours
    after the last report; the same place with another text — at once when the last report is an hour old, else
    never mind (the record stays, so the text is compared with the reported one). The clock gone back past the last
    report counts as due."""
    if record is None or record.code != fingerprint.code:
        fresh = FailureRecord(fingerprint.code, fingerprint.full, now, None)
        return Decision(True, False, fresh, fingerprint)
    reported_at = record.reported_at
    if record.fingerprint == fingerprint.full:
        due = reported_at is None or now - reported_at >= REMIND_AFTER or reported_at > now
        return Decision(due, True, record, fingerprint)
    due = reported_at is None or now - reported_at >= REPORT_AGAIN_AFTER or reported_at > now
    return Decision(due, False, record, fingerprint)


def local_text(moment: datetime, tz: tzinfo | None = None) -> str:
    """`ДД.ММ ЧЧ:ММ` by the container's clock (`TZ`, set from BOT_TIMEZONE when the container starts)."""
    return moment.astimezone(tz).strftime("%d.%m %H:%M")


def heading(decision: Decision, tz: tzinfo | None = None) -> str:
    """The lines of the report above the traceback (Telegram HTML)."""
    if decision.reminder:
        return (f"⚠️ <b>Бот всё ещё не запускается</b> (с {local_text(decision.record.first_seen, tz)}). "
                "Следующее напоминание — через сутки.")
    return ("⚠️ <b>Бот не запустился.</b> Docker повторяет запуск каждую минуту. "
            "Об этом же сбое напомню через сутки, если он не пройдёт; о другом сбое — сразу.")


def report_failure(exc: BaseException, send: Callable[[str], bool], file: Path, now: datetime) -> None:
    """Report the failure if it is due (`send` gets the heading and says whether Telegram took the report), then
    update the record. A record that cannot be saved goes to the temp folder; when that fails too it is a warning: the
    report still goes, the next start reports again."""
    record = load_record(file)
    failure = fingerprint(exc)
    decision = decide(failure, record, now)
    if not decision.send:
        if record.fingerprint == failure.full:
            logging.info("отчёт о сбое запуска уже отправлен %s, следующее напоминание после %s",
                         local_text(record.reported_at), local_text(record.reported_at + REMIND_AFTER))
        else:
            logging.info("сбой запуска на том же месте, текст другой: отчёт отправлен %s, следующий не раньше %s",
                         local_text(record.reported_at), local_text(record.reported_at + REPORT_AGAIN_AFTER))
        return
    sent = send(heading(decision))
    save_record(file, decision.after(sent, now))


def forget_failure(file: Path) -> None:
    """A successful start: remove the record (in `data` and in the temp folder), so the same failure later is reported
    at once."""
    record = load_record(file)
    removed = True
    for path in (file, temp_file()):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logging.warning("запись о сбое запуска не удалилась (%s): %r", path, exc)
            removed = False
    if removed and record is not None:
        logging.info("сбой запуска (с %s) больше не повторяется", local_text(record.first_seen))
