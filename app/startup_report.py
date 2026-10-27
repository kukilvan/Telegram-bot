"""Whether a failure before the start is reported to the owner, and the record of it in `data/startup_failure.json`.

Docker starts the process again every minute while the failure lasts; the owner hears of one and the same failure at
once and then at most once a day, of another failure at once. "The same" is the same fingerprint: the type, the places
in the code without line numbers and the text with the numbers masked. A successful start removes the record.

No network and no settings here: the clock, the file and the sending are handed in, so the tests hand their own.
"""

import hashlib
import json
import logging
import os
import re
import traceback
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, tzinfo
from pathlib import Path

from app.utils.secrets_mask import mask_secrets

REMIND_AFTER = timedelta(hours=24)
TEXT_LENGTH = 300  # of the masked text that goes into the fingerprint

_NUMBER = re.compile(r"0x[0-9a-fA-F]+|\d+")  # times, ids and addresses in memory must not make a failure new
_SPACE = re.compile(r"\s+")


def fingerprint(exc: BaseException) -> str:
    """SHA-256 of the type, the places (file without folders and function, in order) and the masked text of the
    exception. The chain of causes is not part of it; neither the text nor the traceback can be read back from it."""
    kind = f"{type(exc).__module__}.{type(exc).__qualname__}"
    places = [[os.path.basename(frame.filename), frame.name] for frame in traceback.extract_tb(exc.__traceback__)]
    text = _SPACE.sub(" ", _NUMBER.sub("#", mask_secrets(str(exc)))).strip()[:TEXT_LENGTH]
    return hashlib.sha256(json.dumps([kind, places, text], ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FailureRecord:
    """The last failure before the start: since when it happens and when the owner last got a report (UTC)."""

    fingerprint: str
    first_seen: datetime
    reported_at: datetime | None


def read_record(file: Path) -> FailureRecord | None:
    """The record in the file; None when there is no file or it cannot be read or makes no sense."""
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        first_seen = datetime.fromisoformat(data["first_seen"])
        reported_at = None if data["reported_at"] is None else datetime.fromisoformat(data["reported_at"])
        record = FailureRecord(data["fingerprint"], first_seen, reported_at)
    except (OSError, ValueError, TypeError, KeyError):
        return None
    times_aware = all(t is None or t.tzinfo is not None for t in (first_seen, reported_at))
    return record if isinstance(record.fingerprint, str) and times_aware else None


def write_record(file: Path, record: FailureRecord) -> None:
    """Raises OSError when the file cannot be written."""
    data = {
        "fingerprint": record.fingerprint,
        "first_seen": record.first_seen.isoformat(),
        "reported_at": None if record.reported_at is None else record.reported_at.isoformat(),
    }
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(data, indent=2), encoding="utf-8")


@dataclass(frozen=True)
class Decision:
    send: bool
    reminder: bool  # the failure is the one in the record: the report says since when it lasts
    first_seen: datetime
    record: FailureRecord  # the record as it stands; `after` gives it once the report went out or did not

    def after(self, sent: bool, now: datetime) -> FailureRecord:
        return replace(self.record, reported_at=now) if sent else self.record


def decide(failure: str, record: FailureRecord | None, now: datetime) -> Decision:
    """Whether to report the failure with this fingerprint, given the record of the last one (table 1.4 of the spec):
    a new failure and one whose last report did not go out — at once; the same one — again 24 hours after the last
    report, or at once when the clock went back past it."""
    if record is None or record.fingerprint != failure:
        return Decision(True, False, now, FailureRecord(failure, now, None))
    reported_at = record.reported_at
    due = reported_at is None or now - reported_at >= REMIND_AFTER or reported_at > now
    return Decision(due, True, record.first_seen, record)


def local_text(moment: datetime, tz: tzinfo | None = None) -> str:
    """`ДД.ММ ЧЧ:ММ` by the container's clock (`TZ`, set from BOT_TIMEZONE when the container starts)."""
    return moment.astimezone(tz).strftime("%d.%m %H:%M")


def heading(decision: Decision, tz: tzinfo | None = None) -> str:
    """The lines of the report above the traceback (Telegram HTML)."""
    if decision.reminder:
        return (f"⚠️ <b>Бот всё ещё не запускается</b> (с {local_text(decision.first_seen, tz)}). "
                "Следующее напоминание — через сутки.")
    return ("⚠️ <b>Бот не запустился.</b> Docker повторяет запуск каждую минуту. "
            "Об этом же сбое напомню через сутки, если он не пройдёт; о другом сбое — сразу.")


def report_failure(exc: BaseException, send: Callable[[str], bool], file: Path, now: datetime) -> None:
    """Report the failure if it is due (`send` gets the heading and says whether Telegram took the report), then
    update the record. A record that cannot be saved is a warning: the report still goes, the next start reports
    again."""
    record = read_record(file)
    decision = decide(fingerprint(exc), record, now)
    if not decision.send:
        logging.info("отчёт о сбое запуска уже отправлен %s, следующее напоминание после %s",
                     local_text(record.reported_at), local_text(record.reported_at + REMIND_AFTER))
        return
    sent = send(heading(decision))
    try:
        write_record(file, decision.after(sent, now))
    except OSError as exc_write:
        logging.warning("запись о сбое запуска не сохранилась (%s): %r", file, exc_write)


def forget_failure(file: Path) -> None:
    """A successful start: remove the record, so the same failure later is reported at once."""
    record = read_record(file)
    try:
        file.unlink(missing_ok=True)
    except OSError as exc:
        logging.warning("запись о сбое запуска не удалилась (%s): %r", file, exc)
        return
    if record is not None:
        logging.info("сбой запуска (с %s) больше не повторяется", local_text(record.first_seen))
