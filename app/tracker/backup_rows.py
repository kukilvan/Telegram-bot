"""What the owner reads about the copies (pure): the lines of the Settings block and the notice after «Сделать копию сейчас».

Texts only, no files and no database: the core hands over the times of the copies and the owner's clock. The Google
Drive part of the block is `drive_rows`'s; the notice after the press covers the copy sent there too (spec 2.2).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.tracker.backup_events import RETRY, SIGN_IN, drive_reason
from app.tracker.drive_rows import DrivePart
from app.tracker.moment_words import moment_in_words

COPIES_HINT = (
    "Копия делается сама раз в сутки и перед каждым обновлением базы; хранятся 14 последних и по одной за каждый из "
    "12 месяцев. Вернуть базу к копии — .\\restore-bot.ps1 в папке трекера."
)
NO_COPIES = "Копий базы на этом ПК пока нет: первая сделается в течение часа."
UNREADABLE = "Копии базы на этом ПК не прочитать — подробности в журнале."


@dataclass(frozen=True)
class BackupBlock:
    """The block «Копии и выгрузка» of Settings, as the page prints it."""

    copies_line: str  # the copies on this PC
    copies_hint: str
    drive: DrivePart | None = None  # the Google Drive copy (`drive_rows`); None — its part could not be built


class PressOutcome(Enum):
    """How «Сделать копию сейчас» ended."""

    MADE = "made"  # the copy is made; Google Drive is off or not connected
    SENT = "sent"  # the copy is made and sent to Google Drive
    NOT_SENT = "not_sent"  # the copy is made, sending it failed (`reason` — the reason key of `backup_events`)
    SENDING = "sending"  # the copy is made, sending it takes over a minute and goes on in the background
    FAILED = "failed"  # the copy is not made
    BUSY = "busy"  # another copy is being made, or one was made in this very second


def copies_block(moments: Sequence[datetime], now: datetime) -> BackupBlock:
    """The block for the copies found, newest first (`moments`, naive as written in their names) and the owner's
    wall clock `now`."""
    if not moments:
        return BackupBlock(NO_COPIES, COPIES_HINT)
    line = f"Копии базы на этом ПК: {len(moments)}, последняя — {moment_in_words(moments[0], now)}."
    return BackupBlock(line, COPIES_HINT)


def unreadable_block() -> BackupBlock:
    """The folder of the copies cannot be read, or the block could not be built."""
    return BackupBlock(UNREADABLE, COPIES_HINT)


def press_notice(outcome: PressOutcome, *, when: str = "", reason: str = "") -> str:
    """The notice on the page after the press: `when` (the copy in words) for a copy made, `reason` for a copy not made
    (its text) or not sent (its key). This is the one place that decides it."""
    if outcome is PressOutcome.MADE:
        return f"Копия сделана: {when}."
    if outcome is PressOutcome.SENT:
        return "Копия сделана и отправлена в Google Drive."
    if outcome is PressOutcome.NOT_SENT:  # nothing is retried after `sign_in` until the owner connects again
        retry = "" if reason == SIGN_IN else f" {RETRY}"
        return f"Копия сделана, но в Google Drive не ушла: {drive_reason(reason)}.{retry}"
    if outcome is PressOutcome.SENDING:
        return "Копия сделана; в Google Drive она ещё отправляется — итог появится здесь."
    if outcome is PressOutcome.FAILED:
        return f"Копия не сделана: {reason}."
    return "Копия уже делается — подождите несколько секунд."
