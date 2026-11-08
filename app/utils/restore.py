"""The restore of the database from a copy: the list of the copies on the PC, the checks of a copy or a downloaded archive, and the replacement of `tracker.db`.

Run in a one-off container by `restore-bot.ps1` (spec 5 of stage 7.1): `python -m app.container_start app.utils.restore
list | check <path> | apply <path>`. Texts in Russian go to stdout, the exit code is 0 (done) or 1 (refused, nothing
changed); nothing here asks the owner: the script asks. Lines that begin with `@` are for the script, not the owner:
`@copy <n> <path>` (a copy of the list) and `@when <phrase>` (the copy in words, for the question and the last line).
`list` and `check` change nothing; `apply` is run only while the bot is stopped and touches only `tracker.db` and its
`-wal`/`-shm`: the current base goes first to `tracker_db_<now>_before-restore.db` (SQLite's online backup, so the
content of its `-wal` too), and a failure before the final `os.replace` leaves the base as it was.
"""

import contextlib
import errno
import os
import re
import sqlite3
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import py7zr

from app.tracker.db import (
    BACKUP_FOLDER,
    BACKUP_STAMP_FORMAT,
    backup_name,
    copy_database,
    database_file,
    head_revision,
    is_known_revision,
)
from app.tracker.moment_words import moment_in_words
from app.utils import backup
from app.utils.secrets_mask import mask_secrets

BASE_NAME = "tracker.db"
RESTORING_SUFFIX = ".restoring"  # the copy is written next to the base under this name, then replaces it
SIDE_FILES = ("-wal", "-shm")
NAME_TIME = re.compile(r"^tracker_db_(\d{8}_\d{6})")  # the time at the start of the name of a copy or of its archive
NEEDED_TABLES = {"alembic_version", "titles"}

HEADER = "Копии базы в data\\backups (новые сверху):"
NO_COPIES = ('В data\\backups нет копий базы. Восстановить можно из скачанной копии: '
             '.\\restore-bot.ps1 "путь к файлу"')
UNREADABLE = "Папку data\\backups не прочитать ({reason}). Ничего не изменено."
KIND_WORDS = {backup.MANUAL: "сделана вручную"}
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
OLDER = "Копия от более старой версии: при запуске база обновится сама (перед этим сделается ещё одна копия)."
CHECKED = "Копия {phrase} в порядке, тайтлов в ней: {titles}."

SAVED = "Нынешняя база сохранена: data\\backups\\{name}"
SAVE_FAILED = "Не удалось сохранить нынешнюю базу ({reason}). Ничего не изменено."
RESTORE_FAILED = "Не удалось восстановить ({reason}). База не тронута."
RESTORED = "База восстановлена из копии {phrase}."
USAGE = "Команды: list, check <путь>, apply <путь>."
NO_SPACE = "на диске нет места"


class Refusal(Exception):
    """The copy cannot be restored; the text is for the owner, and nothing is changed."""


@dataclass(frozen=True)
class Outcome:
    code: int  # 0 — done, 1 — refused
    lines: list[str]


@dataclass(frozen=True)
class Examined:
    """A copy that passed the checks of 5.4: the `.db` to read (taken out of its archive) and what the owner is told."""

    file: Path
    phrase: str  # «от сегодня в 07:58» or «из файла …»
    titles: int
    older: bool  # its revision is older than the head: the start migrates it


def kind_words(copy: backup.Copy) -> str:
    """The kind of a copy after a dash in the list; a daily copy has none."""
    if copy.kind == backup.OTHER:
        suffix = copy.path.stem.split("_", 4)[-1]
        return BEFORE_RESTORE_WORDS if suffix == backup.BEFORE_RESTORE_SUFFIX else BEFORE_UPDATE_WORDS
    return KIND_WORDS.get(copy.kind, "")


def list_copies(folder: Path, now: datetime) -> Outcome:
    """The numbered list of the copies in `folder`, newest first (spec 5.2), with a `@copy` line for each."""
    try:
        found = backup.copies(folder)
    except OSError as exc:
        return Outcome(1, [UNREADABLE.format(reason=reason_of(exc))])
    if not found:
        return Outcome(0, [NO_COPIES])
    lines = [HEADER]
    for number, copy in enumerate(found, start=1):
        kind = kind_words(copy)
        lines.append(f"{number:>3}) {moment_in_words(copy.moment, now)}{' — ' + kind if kind else ''}")
        lines.append(f"@copy {number} {copy.path.as_posix()}")
    return Outcome(0, lines)


def phrase_of(name: str, now: datetime) -> str:
    """The copy in words by the time at the start of its file name; a name without one is named as it is."""
    match = NAME_TIME.match(name)
    if match:
        try:
            return f"от {moment_in_words(datetime.strptime(match.group(1), BACKUP_STAMP_FORMAT), now)}"
        except ValueError:  # no such date
            pass
    return f"из файла {name}"


def reason_of(exc: BaseException) -> str:
    """A failure in a few words for the owner: a full disk by name, anything else as Python says it."""
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return NO_SPACE
    return mask_secrets(f"{type(exc).__name__}: {exc}")


def check(path: Path, password: str, now: datetime) -> Outcome:
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
def examined(path: Path, password: str, now: datetime) -> Iterator[Examined]:
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


def apply(path: Path, data_dir: Path, password: str, now: datetime) -> Outcome:
    """Replace `data_dir/tracker.db` by the copy at `path` (spec 5.5, steps 2–5); only while the bot is stopped."""
    try:
        with examined(path, password, now) as copy:
            return _replace(copy, data_dir, now)
    except Refusal as refusal:
        return Outcome(1, [str(refusal)])


def _replace(copy: Examined, data_dir: Path, now: datetime) -> Outcome:
    base = data_dir / BASE_NAME
    lines = []
    if base.exists():
        before = data_dir / BACKUP_FOLDER / backup_name(now, backup.BEFORE_RESTORE_SUFFIX)
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


def run(args: list[str], data_dir: Path, password: str, now: datetime) -> Outcome:
    """The command of `args` on the base in `data_dir`."""
    if args == ["list"]:
        return list_copies(data_dir / BACKUP_FOLDER, now)
    if len(args) == 2 and args[0] == "check":
        return check(Path(args[1]), password, now)
    if len(args) == 2 and args[0] == "apply":
        return apply(Path(args[1]), data_dir, password, now)
    return Outcome(2, [USAGE])


def main(argv: list[str] | None = None) -> int:
    file = database_file()
    data_dir = file.parent if file is not None else Path("data")
    password = os.environ.get("BACKUP_PASSWORD", "").strip()  # stripped as `Settings` strips it
    outcome = run(sys.argv[1:] if argv is None else argv, data_dir, password, datetime.now())
    for line in outcome.lines:
        print(line, flush=True)
    return outcome.code


if __name__ == "__main__":
    sys.exit(main())
