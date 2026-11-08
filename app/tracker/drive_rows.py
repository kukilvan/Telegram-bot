"""What the owner reads about the Google Drive copy (pure): its line in Settings, the buttons under it and the notices of the sign-in and the sign-out.

Texts only, no files and no network: the core (`google_drive`) hands over whether the copy is set up, connected, the
state of its sending and whether the page is opened on this PC. Rules: sections 4.2 and 4.7 of the spec of stage 7.1;
the reasons of a copy that did not go are `backup_events`'s.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.tracker.backup_events import SIGN_IN, drive_reason
from app.tracker.cards import plural
from app.tracker.drive_state import KEPT_IN_DRIVE, DriveState


class DriveSetup(Enum):
    """What `.env` gives the Google Drive copy; decided in one place, `google_drive.DriveSettings.setup`."""

    OFF = "off"  # no client id or no secret
    NO_PASSWORD = "no_password"  # the client is there, BACKUP_PASSWORD is missing or too short
    ON = "on"  # all three: the copy is on and needs only the connection


class DriveButton(Enum):
    CONNECT = "connect"  # «Подключить Google Drive»
    DISCONNECT = "disconnect"  # «Отключить Google Drive»


@dataclass(frozen=True)
class DrivePart:
    """The Google Drive part of the block «Копии и выгрузка», as the page prints it."""

    line: str
    hint: str = ""  # the small text under the line; "" — none
    buttons: tuple[DriveButton, ...] = ()
    elsewhere: str = ""  # instead of «Подключить Google Drive» when the page is not opened on this PC


OFF_LINE = "Копия в Google Drive выключена. Как включить — docs/backups.md в папке трекера."
NO_PASSWORD_LINE = (
    "Копия в Google Drive не включится: в .env нет пароля BACKUP_PASSWORD или он короче 12 знаков."
)
NOT_CONNECTED_LINE = "Google Drive не подключён."
CONNECTED_LINE = "Google Drive подключён; первая копия уйдёт в течение часа."
PASSWORD_HINT = (
    "Копии зашифрованы паролем BACKUP_PASSWORD из .env. Храните его и вне этого ПК: без него копии из Google Drive не "
    "открыть. Новый пароль действует только для новых копий."
)

CONNECTED = "Google Drive подключён. Первая копия отправляется — итог появится здесь через минуту."
ACCESS_DENIED = "Вы не дали доступ к Google Drive — копия туда не включена."
NOT_FINISHED = "Вход в Google не завершён — нажмите «Подключить Google Drive» ещё раз."
NOT_CONFIRMED = "Google не подтвердил вход. Попробуйте ещё раз; если повторится — подробности в журнале."
DISCONNECTED = "Google Drive отключён. Копии, которые уже там, остались в папке «Трекер — копии»."


def only_here(port: int) -> str:
    """The sentence for a page opened not on this PC (the phone in the home network): the sign-in returns to this PC."""
    return f"Подключить Google Drive можно только на этом ПК: откройте http://localhost:{port}/settings."


def google_refused(error: str) -> str:
    """Google sent the owner back with an error other than «access denied»; `error` is its code, already cleaned."""
    return f"Google не подтвердил вход ({error}). Попробуйте ещё раз."


def copies_word(count: int) -> str:
    """«копия» in the form that follows the number: 1 копия, 2 копии, 5 копий."""
    return plural(count, "копия", "копии", "копий")


def sent_line(state: DriveState, words: Callable[[datetime], str]) -> str | None:
    """The line of a connection that has tried to send («Works» or «Failed last time»); None — nothing tried yet.
    `words` gives a stored moment (naive UTC) in words on the owner's clock."""
    if state.failed and state.last_attempt_at is not None:
        last = f"Последняя удачная — {words(state.last_success_at)}." if state.last_success_at else "Удачных ещё не было."
        return f"Копия в Google Drive не ушла: {words(state.last_attempt_at)} — {drive_reason(state.error)}. {last}"
    if state.last_success_at is not None:
        kept = state.kept
        return f"Копия в Google Drive: {words(state.last_success_at)}, там {kept} {copies_word(kept)} из {KEPT_IN_DRIVE} хранимых."
    return None


def drive_part(
    setup: DriveSetup, connected: bool, here: bool, port: int,
    state: DriveState | None = None, words: Callable[[datetime], str] = str,
) -> DrivePart:
    """The part for the copy set up so (`setup`), `connected` (a token file that reads), the page opened on this PC
    (`here`) or not, the port of the web on the PC (`port`, for the sentence of another host), and the `state` of the
    sending (None — no attempts yet) with `words` for its moments."""
    if setup is DriveSetup.OFF:
        return DrivePart(OFF_LINE)
    if setup is DriveSetup.NO_PASSWORD:
        return DrivePart(NO_PASSWORD_LINE)
    if not connected:
        if here:
            return DrivePart(NOT_CONNECTED_LINE, buttons=(DriveButton.CONNECT,))
        return DrivePart(NOT_CONNECTED_LINE, elsewhere=only_here(port))
    line = sent_line(state, words) if state is not None else None
    if line is None:
        return DrivePart(CONNECTED_LINE, PASSWORD_HINT, (DriveButton.DISCONNECT,))
    if state is not None and state.error == SIGN_IN:  # Google refused the sign-in: connecting again is the way out
        if here:
            return DrivePart(line, PASSWORD_HINT, (DriveButton.CONNECT, DriveButton.DISCONNECT))
        return DrivePart(line, PASSWORD_HINT, (DriveButton.DISCONNECT,), only_here(port))
    return DrivePart(line, PASSWORD_HINT, (DriveButton.DISCONNECT,))
