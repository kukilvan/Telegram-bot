"""What the owner reads about the Google Drive copy (pure): its line in Settings, the button under it and the notices of the sign-in and the sign-out.

Texts only, no files and no network: the core (`google_drive`) hands over whether the copy is set up, connected and
whether the page is opened on this PC. Rules: sections 4.2 and 4.7 of the spec of stage 7.1; the lines of the copies
sent and failed (rows 5 and 6 of 4.7) are ticket 04's.
"""

from dataclasses import dataclass
from enum import Enum


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


def drive_part(setup: DriveSetup, connected: bool, here: bool, port: int) -> DrivePart:
    """The part for the copy set up so (`setup`), `connected` (a token file that reads), the page opened on this PC
    (`here`) or not, and the port of the web on the PC (`port`, for the sentence of another host). Until ticket 04 sends
    copies, a connection is always «nothing sent yet»."""
    if setup is DriveSetup.OFF:
        return DrivePart(OFF_LINE)
    if setup is DriveSetup.NO_PASSWORD:
        return DrivePart(NO_PASSWORD_LINE)
    if not connected:
        if here:
            return DrivePart(NOT_CONNECTED_LINE, buttons=(DriveButton.CONNECT,))
        return DrivePart(NOT_CONNECTED_LINE, elsewhere=only_here(port))
    return DrivePart(CONNECTED_LINE, PASSWORD_HINT, (DriveButton.DISCONNECT,))
