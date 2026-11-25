"""The restore of the database from a copy: the list of copies, the checks of a copy or an archive, the replacement of `tracker.db`, and the asking restore.

Run in a one-off container of the same image (`python -m app.container_start app.utils.restore …`): with no arguments or
with the path of a file it asks (the NAS: `docker compose run --rm tracker …`, three commands in `RESTORE_COMMAND`'s
place; answers are read from standard input line by line, so piped ones work too); `list | check <path> | apply <path>`
are the commands `restore-bot.ps1` calls and does the asking itself. Texts in Russian go to stdout, the exit code is 0
(done or cancelled) or 1 (refused, nothing changed; 2 for an unknown command). Lines that begin with `@` are for the
script, not the owner: `@copy <n> <path>` (a copy of the list) and `@when <phrase>` (the copy in words, for the question
and the last line).
`list` and `check` change nothing; `apply` touches only `tracker.db` and its `-wal`/`-shm`: the current base goes first
to `tracker_db_<now>Z_before-restore.db` (SQLite's online backup, so the content of its `-wal` too), and a failure before
the final `os.replace` leaves the base as it was. The base can be replaced only while the bot is stopped: `bot_running`
asks the Docker network whether the name of the bot's service resolves (`SERVICE_NAME`, the service of
`docker-compose.yml`: a one-off container sees that name only while the bot's container exists), and `apply` and the
asking restore refuse while it does or while the answer is unknown. That guard is a detail of this module, not an ADR.
"""

import contextlib
import errno
import json
import os
import re
import socket
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import py7zr

from app.tracker.db import (
    BACKUP_FOLDER,
    UTC_MARK,
    backup_name,
    copy_database,
    database_file,
    head_revision,
    is_known_revision,
    name_moment,
    utc_now,
)
from app.tracker.moment_words import local_moment, moment_in_words
from app.tracker.zones import known_names
from app.utils import backup
from app.utils.secrets_mask import mask_secrets

BASE_NAME = "tracker.db"
RESTORING_SUFFIX = ".restoring"  # the copy is written next to the base under this name, then replaces it
SIDE_FILES = ("-wal", "-shm")
NAME_TIME = re.compile(rf"^tracker_db_(\d{{8}}_\d{{6}})({UTC_MARK})?")  # the time at the start of the name of a copy or of its archive
ZONE_SETTING = "timezone"  # the row of the `settings` table that holds the zone chosen in Settings
NEEDED_TABLES = {"alembic_version", "titles"}
SERVICE_NAME = "tracker"  # the service of docker-compose.yml: its name resolves in the network only while the bot's container exists
COMMANDS = ("list", "check", "apply")  # one argument that is none of them is the path of a file
SERVICE_PORT = 8080  # asked only to have something to resolve; nothing connects
NO_SUCH_NAME = {getattr(socket, name) for name in ("EAI_NONAME", "EAI_NODATA") if hasattr(socket, name)}
RESTORE_COMMAND = f"docker compose run --rm {SERVICE_NAME} python -m app.container_start app.utils.restore"

HEADER = "Копии базы в data/backups (новые сверху):"
NO_COPIES = ('В data\\backups нет копий базы. Восстановить можно из скачанной копии: '
             '.\\restore-bot.ps1 "путь к файлу"')
NO_COPIES_ASKING = ("В data/backups нет копий базы. Восстановить можно из скачанной копии: положите файл .7z или .db "
                    f"в папку data/restore и запустите: {RESTORE_COMMAND} data/restore/<имя файла>")
UNREADABLE = "Папку data/backups не прочитать ({reason}). Ничего не изменено."
ORIGIN_WORDS = {backup.MANUAL: "сделана вручную"}
BEFORE_RESTORE_WORDS = "перед восстановлением"
BEFORE_UPDATE_WORDS = "перед обновлением базы"

NOT_FOUND = "Файл не найден: {path}"
WRONG_KIND = "Нужен файл .7z из Google Drive или .db из копий. Ничего не изменено."
NO_PASSWORD = ("В .env нет BACKUP_PASSWORD — впишите пароль копий и запустите снова. Или откройте архив 7-Zip вручную "
               "и укажите путь к файлу .db из него.")
NOT_7Z = "Это не архив 7z. Ничего не изменено."
BAD_PASSWORD = ("Пароль из .env не подходит к этой копии, или архив повреждён. Проверьте BACKUP_PASSWORD или откройте "
                "архив 7-Zip и введите пароль вручную.")
NO_DB_IN_ARCHIVE = "В архиве нет копии базы трекера. Ничего не изменено."
DAMAGED = "Копия повреждена (проверка SQLite не прошла). Ничего не изменено. Выберите другую копию."
NOT_TRACKER = "Этот файл не похож на копию базы трекера. Ничего не изменено."
NEWER = ("Эта копия сделана более новой версией трекера (база {revision}, а эта версия знает до {head}). "
         "Обновите трекер и запустите снова. Ничего не изменено.")
OLDER = "Копия от более старой версии: при запуске база обновится сама."
CHECKED = "Копия {phrase} в порядке, тайтлов в ней: {titles}."

SAVED = "Нынешняя база сохранена: data/backups/{name}"
SAVE_FAILED = "Не удалось сохранить нынешнюю базу ({reason}). Ничего не изменено."
RESTORE_FAILED = "Не удалось восстановить ({reason}). База не тронута."
RESTORED = "База восстановлена из копии {phrase}."
USAGE = "Команды: без аргументов — спросить копию; <путь> — восстановить файл; list, check <путь>, apply <путь>."
NUMBER_PROMPT = "Номер копии (Enter — отмена): "
NO_SUCH_COPY = "Нет копии с номером {answer}."
CANCELLED = "Отменено. Ничего не изменено."
QUESTION = ("Вернуть базу к копии {phrase}? Всё, что изменилось позже, пропадёт. Нынешняя база сохранится отдельно. "
            "(да/нет): ")
BOT_RUNNING = ("Бот работает, а базу можно заменить только у остановленного. Остановите его: docker compose stop — "
               "и запустите восстановление снова. Ничего не изменено.")
START_NOW = "Готово. Запустите бота: docker compose up -d"
START_OLD = "Запустите бота на прежней базе: docker compose up -d"
YES = "да"
NO_SPACE = "на диске нет места"


@dataclass(frozen=True)
class Clock:
    """The moments of one run: `now` (naive UTC; it names the copy before a restore), the zone every moment is shown in
    (`shown_in`: the zone of Settings of the base being replaced; None — the zone of this process) and the zone the names
    without `Z` were written in (`old_zone`; None — the zone of this process)."""

    now: datetime
    shown_in: tzinfo | None = None
    old_zone: tzinfo | None = None

    def local(self, moment: datetime) -> datetime:
        """A naive UTC moment on the wall clock of `shown_in`."""
        if self.shown_in is None:
            return moment.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)
        return local_moment(moment, self.shown_in)

    def words(self, moment: datetime) -> str:
        """A naive UTC moment in words against now, both on the wall clock of `shown_in`."""
        return moment_in_words(self.local(moment), self.local(self.now))


class Refusal(Exception):
    """The copy cannot be restored; the text is for the owner, and nothing is changed."""


@dataclass(frozen=True)
class Outcome:
    code: int  # 0 — done, 1 — refused; 2 — a command this module does not know (the script never gives one)
    lines: list[str]


@dataclass(frozen=True)
class Examined:
    """A copy that passed the checks of 5.4: the `.db` to read (taken out of its archive) and what the owner is told."""

    file: Path
    phrase: str  # «от сегодня в 07:58» or «из файла …»
    titles: int
    older: bool  # its revision is older than the head: the start migrates it


def origin_words(copy: backup.Copy) -> str:
    """What made a copy, after a dash in the list; a daily copy has none."""
    if copy.origin == backup.OTHER:
        suffix = copy.path.stem.split("_", 4)[-1]
        return BEFORE_RESTORE_WORDS if suffix == backup.BEFORE_RESTORE_SUFFIX else BEFORE_UPDATE_WORDS
    return ORIGIN_WORDS.get(copy.origin, "")


def zone_of_settings(base: Path) -> tzinfo | None:
    """The zone chosen in Settings of the base at `base`, read without a change to it; None when the base cannot be read,
    holds none or holds one that is not a zone (the zone of this process then)."""
    if not base.is_file():
        return None
    try:
        connection = _read_only(base)
        try:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (ZONE_SETTING,)).fetchone()
        finally:
            connection.close()
        name = json.loads(row[0]) if row else None
        return ZoneInfo(name) if isinstance(name, str) and name in known_names() else None
    except (sqlite3.Error, ValueError, TypeError, OSError, ZoneInfoNotFoundError):
        return None


def list_copies(folder: Path, clock: Clock, asking: bool = False) -> Outcome:
    """The numbered list of the copies in `folder`, newest first (spec 5.2), with a `@copy` line for each; with no copy
    it says how to restore a downloaded one, by the script (`asking` False) or by the asking restore."""
    try:
        found = backup.copies(folder, clock.old_zone)
    except OSError as exc:
        return Outcome(1, [UNREADABLE.format(reason=reason_of(exc))])
    if not found:
        return Outcome(0, [NO_COPIES_ASKING if asking else NO_COPIES])
    lines = [HEADER]
    for number, copy in enumerate(found, start=1):
        words = origin_words(copy)
        lines.append(f"{number:>3}) {clock.words(copy.moment)}{' — ' + words if words else ''}")
        lines.append(f"@copy {number} {copy.path.as_posix()}")
    return Outcome(0, lines)


def phrase_of(name: str, clock: Clock) -> str:
    """The copy in words by the time at the start of its file name (UTC with `Z`, else the clock of the old names); a
    name without one is named as it is."""
    match = NAME_TIME.match(name)
    if match:
        try:
            return f"от {clock.words(name_moment(match.group(1), match.group(2), clock.old_zone))}"
        except ValueError:  # no such date
            pass
    return f"из файла {name}"


def reason_of(exc: BaseException) -> str:
    """A failure in a few words for the owner: a full disk by name, anything else as Python says it."""
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return NO_SPACE
    return mask_secrets(f"{type(exc).__name__}: {exc}")


def check(path: Path, password: str, now: Clock) -> Outcome:
    """The checks of spec 5.3 and 5.4 of a copy or an archive, with its description and a `@when` line; changes
    nothing."""
    try:
        with examined(path, password, now) as copy:
            lines = [CHECKED.format(phrase=copy.phrase, titles=copy.titles)]
            if copy.older:
                lines.append(OLDER)
            return Outcome(0, [*lines, f"@when {copy.phrase}"])
    except Refusal as refusal:
        return Outcome(1, [str(refusal)])


@contextlib.contextmanager
def examined(path: Path, password: str, now: Clock) -> Iterator[Examined]:
    """The copy at `path` checked (an archive opened into a temporary folder that goes when the block ends); `Refusal`
    with the owner's text when it does not pass."""
    if not path.is_file():
        raise Refusal(NOT_FOUND.format(path=path))
    suffix = path.suffix.lower()
    if suffix not in (".7z", ".db"):
        raise Refusal(WRONG_KIND)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        file = _unpacked(path, password, Path(folder)) if suffix == ".7z" else path
        titles, older = _inspected(file)
        name = path.name if NAME_TIME.match(path.name) else file.name
        yield Examined(file, phrase_of(name, now), titles, older)


def _unpacked(archive: Path, password: str, folder: Path) -> Path:
    """The one `.db` of the archive, taken out into `folder` (spec 5.3)."""
    if not password:
        raise Refusal(NO_PASSWORD)
    try:
        is_archive = py7zr.is_7zfile(archive)
    except OSError:
        is_archive = False
    if not is_archive:
        raise Refusal(NOT_7Z)
    try:  # a wrong password gives whatever error the garbage makes: every one means the same to the owner
        with py7zr.SevenZipFile(archive, "r", password=password) as opened:
            names = [info.filename for info in opened.list() if not info.is_directory]
    except Exception:
        raise Refusal(BAD_PASSWORD) from None
    databases = [name for name in names if name.lower().endswith(".db")]
    if len(databases) != 1:
        raise Refusal(NO_DB_IN_ARCHIVE)
    target = (folder / databases[0]).resolve()
    try:
        if not target.is_relative_to(folder.resolve()):  # a name that climbs out of the folder
            raise ValueError(databases[0])
        with py7zr.SevenZipFile(archive, "r", password=password) as opened:
            opened.extract(path=folder, targets=databases)
        if not target.is_file():
            raise FileNotFoundError(databases[0])
    except Exception:
        raise Refusal(BAD_PASSWORD) from None
    return target


def _read_only(file: Path) -> sqlite3.Connection:
    """The file opened read-only as it is (`immutable`): no lock, no `-wal`/`-shm` left next to it."""
    return sqlite3.connect(f"{file.resolve().as_uri()}?immutable=1", uri=True)


def _integrity_ok(file: Path) -> bool:
    try:
        connection = _read_only(file)
        try:
            return connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        finally:
            connection.close()
    except sqlite3.Error:
        return False


def _inspected(file: Path) -> tuple[int, bool]:
    """(the number of titles, whether its revision is older than the head) of a copy that passes spec 5.4."""
    if not _integrity_ok(file):
        raise Refusal(DAMAGED)
    try:
        connection = _read_only(file)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not NEEDED_TABLES <= tables:
                raise Refusal(NOT_TRACKER)
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if row is None or not isinstance(row[0], str):
                raise Refusal(NOT_TRACKER)
            revision = row[0]
            head = head_revision()
            if not is_known_revision(revision):
                raise Refusal(NEWER.format(revision=revision, head=head))
            titles = connection.execute("SELECT count(*) FROM titles").fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error:
        raise Refusal(DAMAGED) from None
    return titles, revision != head


def _side(file: Path, suffix: str) -> Path:
    return file.with_name(file.name + suffix)


def _remove_with_sides(file: Path) -> None:
    for path in (file, *(_side(file, suffix) for suffix in SIDE_FILES)):
        path.unlink(missing_ok=True)


def _checkpoint(base: Path) -> None:
    """Everything of the base's `-wal` written into the base and the `-wal`/`-shm` removed (spec 5.5, step 4). A
    checkpoint that does not finish raises before anything is removed: the `-wal` may still hold data."""
    connection = sqlite3.connect(base)
    try:
        busy, _log, _done = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if busy:
            raise sqlite3.OperationalError("база занята другой программой")
    finally:
        connection.close()
    for suffix in SIDE_FILES:
        _side(base, suffix).unlink(missing_ok=True)


def bot_running() -> bool:
    """Whether the bot's container exists, by its name in the network: a stopped or removed one leaves the names, one that
    is starting (migrations, the web not listening yet) is there. Any answer but «no such name» counts as running."""
    try:
        socket.getaddrinfo(SERVICE_NAME, SERVICE_PORT)
    except socket.gaierror as exc:
        return exc.errno not in NO_SUCH_NAME
    except OSError:
        pass  # no answer we understand: the bot may well be there
    return True


def apply(path: Path, data_dir: Path, password: str, now: Clock, running: Callable[[], bool] | None = None) -> Outcome:
    """Replace `data_dir/tracker.db` by the copy at `path` (spec 5.5, steps 2–5); refused while the bot runs
    (`running` — `bot_running` unless a test gives its own)."""
    if (running or bot_running)():
        return Outcome(1, [BOT_RUNNING])
    return _apply(path, data_dir, password, now)


def _apply(path: Path, data_dir: Path, password: str, now: Clock) -> Outcome:
    try:
        with examined(path, password, now) as copy:
            return _replace(copy, data_dir, now)
    except Refusal as refusal:
        return Outcome(1, [str(refusal)])


def _replace(copy: Examined, data_dir: Path, now: Clock) -> Outcome:
    base = data_dir / BASE_NAME
    lines = []
    if base.exists():
        before = data_dir / BACKUP_FOLDER / backup_name(now.now, backup.BEFORE_RESTORE_SUFFIX)
        try:
            copy_database(base, before)  # the online backup reads through the `-wal`: its content is in the copy
        except Exception as exc:
            return Outcome(1, [SAVE_FAILED.format(reason=reason_of(exc))])
        lines.append(SAVED.format(name=before.name))
    restoring = base.with_name(base.name + RESTORING_SUFFIX)
    try:
        _remove_with_sides(restoring)  # left from a broken run
        if base.exists():
            _checkpoint(base)
        copy_database(copy.file, restoring)
        if not _integrity_ok(restoring):
            raise sqlite3.DatabaseError("копия не прошла проверку SQLite после записи")
        os.replace(restoring, base)
    except Exception as exc:
        with contextlib.suppress(OSError):
            _remove_with_sides(restoring)
        return Outcome(1, [*lines, RESTORE_FAILED.format(reason=reason_of(exc))])
    with contextlib.suppress(OSError):
        _remove_with_sides(restoring)  # the `-wal`/`-shm` of the written copy, if any were left
    return Outcome(0, [*lines, RESTORED.format(phrase=copy.phrase)])


def _clock(data_dir: Path, now: datetime, process_zone: tzinfo | None) -> Clock:
    return Clock(now, zone_of_settings(data_dir / BASE_NAME) or process_zone, process_zone)


def run(
    args: list[str], data_dir: Path, password: str, now: datetime, process_zone: tzinfo | None = None,
    running: Callable[[], bool] | None = None,
) -> Outcome:
    """The command of `args` on the base in `data_dir`; `now` is naive UTC. The moments are shown in the zone of Settings
    of that base, else in `process_zone` (None — the zone of this process, which is also the zone of the old names)."""
    clock = _clock(data_dir, now, process_zone)
    if args == ["list"]:
        return list_copies(data_dir / BACKUP_FOLDER, clock)
    if len(args) == 2 and args[0] == "check":
        return check(Path(args[1]), password, clock)
    if len(args) == 2 and args[0] == "apply":
        return apply(Path(args[1]), data_dir, password, clock, running)
    return Outcome(2, [USAGE])


class Console:
    """The owner's terminal: lines to stdout, answers read from stdin one line at a time (so a terminal and piped answers
    work alike). Input that is not UTF-8 is read with replacement characters; an answer read from a pipe is echoed."""

    def __init__(self) -> None:
        reconfigure = getattr(sys.stdin, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    def say(self, line: str) -> None:
        print(line, flush=True)

    def ask(self, prompt: str) -> str | None:
        """The answer without its line end; None at the end of input. `Ctrl+C` ends the line and raises."""
        print(prompt, end="", flush=True)
        try:
            line = sys.stdin.readline()
        except KeyboardInterrupt:
            print(flush=True)
            raise
        if not line:
            print(flush=True)
            return None
        answer = line.rstrip("\r\n")
        if not sys.stdin.isatty():
            print(answer, flush=True)
        return answer


def _say_shown(console: Console, lines: list[str]) -> None:
    """The lines for the owner: those that do not begin with `@`."""
    for line in lines:
        if not line.startswith("@"):
            console.say(line)


def _copies_of(lines: list[str]) -> dict[str, str]:
    """The number → path of the `@copy` lines of a list."""
    found = {}
    for line in lines:
        match = re.fullmatch(r"@copy (\d+) (.+)", line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def _choose_copy(console: Console, copies: dict[str, str]) -> str | None:
    """The path of the copy the owner names by its number; None when the owner cancels (Enter or the end of input)."""
    while True:
        answer = console.ask(NUMBER_PROMPT)
        answer = answer.strip() if answer is not None else ""
        if not answer:
            return None
        number = str(int(answer)) if answer.isascii() and answer.isdigit() else answer
        if number in copies:
            return copies[number]
        console.say(NO_SUCH_COPY.format(answer=answer))


def ask_restore(
    path: str | None, data_dir: Path, password: str, now: datetime, console: Console,
    process_zone: tzinfo | None = None, running: Callable[[], bool] | None = None,
) -> int:
    """The asking restore (spec 2.2 of stage 7.3): the copy by a number from the list (`path` None) or the file at `path`,
    the check, the question, then the replacement; returns the exit code. Nothing is asked while the bot runs, and the
    guard is asked again just before the change."""
    is_running = running or bot_running
    if is_running():
        console.say(BOT_RUNNING)
        return 1
    clock = _clock(data_dir, now, process_zone)
    try:
        if path is None:
            listing = list_copies(data_dir / BACKUP_FOLDER, clock, asking=True)
            _say_shown(console, listing.lines)
            copies = _copies_of(listing.lines)
            if not copies:
                return listing.code
            path = _choose_copy(console, copies)
            if path is None:
                console.say(CANCELLED)
                return 0
        checked = check(Path(path), password, clock)
        _say_shown(console, checked.lines)
        if checked.code != 0:
            return 1
        phrase = next(line[len("@when "):] for line in checked.lines if line.startswith("@when "))
        answer = console.ask(QUESTION.format(phrase=phrase))
    except KeyboardInterrupt:
        console.say(CANCELLED)
        return 1
    if answer is None or "".join(answer.split()).casefold() != YES:
        console.say(CANCELLED)
        return 0
    if is_running():
        console.say(BOT_RUNNING)
        return 1
    outcome = _apply(Path(path), data_dir, password, clock)
    for line in outcome.lines:
        console.say(line)
    console.say(START_NOW if outcome.code == 0 else START_OLD)
    return outcome.code


def main(argv: list[str] | None = None, console: Console | None = None, running: Callable[[], bool] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    file = database_file()
    data_dir = file.parent if file is not None else Path("data")
    password = os.environ.get("BACKUP_PASSWORD", "").strip()  # stripped as `Settings` strips it
    if not args or (len(args) == 1 and args[0] not in COMMANDS):
        return ask_restore(args[0] if args else None, data_dir, password, utc_now(), console or Console(), running=running)
    outcome = run(args, data_dir, password, utc_now(), running=running)
    for line in outcome.lines:
        print(line, flush=True)
    return outcome.code


if __name__ == "__main__":
    sys.exit(main())
