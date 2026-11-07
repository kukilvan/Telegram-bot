"""What the owner reads about the copies (pure): the lines of the Settings block and the notice after «Сделать копию сейчас».

Texts only, no files and no database: the core hands over the times of the copies and the owner's clock. Tickets 02–04
add their lines (the export, the Google Drive copy) to `BackupBlock` and their outcomes to `PressOutcome` and `press_notice`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

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


class PressOutcome(Enum):
    """How «Сделать копию сейчас» ended. The Google Drive outcomes join these in ticket 04."""

    MADE = "made"  # the copy is made
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
    """The notice on the page after the press: `when` (the copy in words) for a copy made, `reason` for a copy not made.
    This is the one place that decides it; the sending to Google Drive adds its outcomes here."""
    if outcome is PressOutcome.MADE:
        return f"Копия сделана: {when}."
    if outcome is PressOutcome.FAILED:
        return f"Копия не сделана: {reason}."
    return "Копия уже делается — подождите несколько секунд."
