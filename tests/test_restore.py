"""The restore of the database (stage 7.1, ticket 05; spec 5): `app.utils.restore` on files in a temporary folder and the
texts and commands of `restore-bot.ps1`."""

import errno
import hashlib
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import py7zr
import pytest
from alembic import command

from app.tracker import db as tracker_db
from app.tracker.db import create_session_factory, create_tracker_engine, head_revision
from app.utils import restore
from app.utils.archive import make_archive

ROOT = Path(__file__).resolve().parent.parent
BOM = b"\xef\xbb\xbf"
NOW = datetime(2026, 11, 8, 12, 0, 0)
PASSWORD = "Пароль копий 2026"
STAMP = "20261108_075800"


# ---- helpers ----------------------------------------------------------------

def _migrated(file: Path, revision: str = "head") -> Path:
    """A tracker database at `revision`, made by the migrations themselves."""
    engine = create_tracker_engine(f"sqlite:///{file.as_posix()}")
    with engine.begin() as connection:
        config = tracker_db._alembic_config()
        config.attributes["connection"] = connection
        command.upgrade(config, revision)
    engine.dispose()
    return file


@pytest.fixture(scope="module")
def template(tmp_path_factory) -> Path:
    return _migrated(tmp_path_factory.mktemp("template") / "tracker.db")


def _database(template: Path, file: Path, marker: str = "copy", titles: int = 0, revision: str | None = None) -> Path:
    """A copy of the migrated template with a marker in the settings, some titles and, if given, another revision."""
    file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, file)
    connection = sqlite3.connect(file)
    try:
        connection.execute("INSERT INTO settings (key, value) VALUES ('marker', ?)", (f'"{marker}"',))
        columns = [row for row in connection.execute("PRAGMA table_info(titles)") if row[1] != "id"]
        for number in range(titles):
            values = [_filler(row[2], number) for row in columns]
            names = ", ".join(row[1] for row in columns)
            connection.execute(f"INSERT INTO titles ({names}) VALUES ({', '.join('?' * len(columns))})", values)
        if revision is not None:
            connection.execute("UPDATE alembic_version SET version_num = ?", (revision,))
        connection.commit()
    finally:
        connection.close()
    return file


def _filler(column_type: str, number: int):
    kind = column_type.upper()
    if "INT" in kind or "BOOL" in kind:
        return 0
    if "DATE" in kind:
        return "2026-11-01 10:00:00.000000"
    if "JSON" in kind:
        return "[]"
    if "VARCHAR(16)" in kind:  # the enumerations stored as text
        return "movie"
    return f"Тайтл {number}"


def _marker(file: Path) -> str:
    connection = sqlite3.connect(file)
    try:
        return connection.execute("SELECT value FROM settings WHERE key = 'marker'").fetchone()[0].strip('"')
    finally:
        connection.close()


def _dump(file: Path) -> str:
    connection = sqlite3.connect(file)
    try:
        return hashlib.sha256("\n".join(connection.iterdump()).encode()).hexdigest()
    finally:
        connection.close()


def _files(folder: Path) -> dict[str, bytes]:
    return {path.relative_to(folder).as_posix(): path.read_bytes() for path in sorted(folder.rglob("*")) if path.is_file()}


def _base_with_wal(template: Path, data: Path, marker: str = "current") -> Path:
    """`data/tracker.db` whose newest change lives only in its `-wal` (copied while a writer still had it open)."""
    scratch = data.parent / "writer"
    source = _database(template, scratch / "tracker.db", marker="old")
    writer = sqlite3.connect(source)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("UPDATE settings SET value = ? WHERE key = 'marker'", (f'"{marker}"',))
    writer.commit()
    data.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal"):
        shutil.copyfile(f"{source}{suffix}", data / f"tracker.db{suffix}")
    writer.close()
    return data / "tracker.db"


def _only_main_file_marker(file: Path) -> str:
    connection = sqlite3.connect(f"{file.resolve().as_uri()}?immutable=1", uri=True)
    try:
        return connection.execute("SELECT value FROM settings WHERE key = 'marker'").fetchone()[0].strip('"')
    finally:
        connection.close()


def _archive(copy: Path, target: Path, password: str = PASSWORD) -> Path:
    return make_archive(copy, target, password)


# ---- list -------------------------------------------------------------------

def test_the_list_numbers_the_copies_newest_first_with_their_moments_and_kinds(tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    for name in ("tracker_db_20261108_075800.db", "tracker_db_20261107_183200_manual.db",
                 "tracker_db_20261107_075800_before-0013.db", "tracker_db_20261106_162500_before-restore.db",
                 "tracker_db_20251025_091200.db", "tracker_db_20261399_000000.db", "notes.txt"):
        (folder / name).write_bytes(b"")
    (folder / "upload").mkdir()

    outcome = restore.list_copies(folder, NOW)

    assert outcome.code == 0
    shown = [line for line in outcome.lines if not line.startswith("@")]
    assert shown == [
        "Копии базы в data\\backups (новые сверху):",
        "  1) сегодня в 07:58",
        "  2) вчера в 18:32 — сделана вручную",
        "  3) вчера в 07:58 — перед обновлением базы",
        "  4) 6 ноября в 16:25 — перед восстановлением",
        "  5) 25 октября 2025 в 09:12",
    ]
    assert outcome.lines[2] == f"@copy 1 {(folder / 'tracker_db_20261108_075800.db').as_posix()}"
    assert [line.split(" ", 2)[1] for line in outcome.lines if line.startswith("@copy")] == ["1", "2", "3", "4", "5"]


def test_the_list_aligns_two_digit_numbers(tmp_path):
    folder = tmp_path / "backups"
    folder.mkdir()
    for day in range(1, 12):
        (folder / f"tracker_db_202610{day:02d}_090000.db").write_bytes(b"")

    shown = [line for line in restore.list_copies(folder, NOW).lines if not line.startswith("@")]

    assert shown[1] == "  1) 11 октября в 09:00" and shown[11] == " 11) 1 октября в 09:00"


@pytest.mark.parametrize("make", [False, True])
def test_no_copies_points_to_a_downloaded_one(tmp_path, make):
    folder = tmp_path / "backups"
    if make:
        folder.mkdir()

    outcome = restore.list_copies(folder, NOW)

    assert outcome.code == 0
    assert outcome.lines == ['В data\\backups нет копий базы. Восстановить можно из скачанной копии: '
                             '.\\restore-bot.ps1 "путь к файлу"']


# ---- check ------------------------------------------------------------------

def test_a_good_copy_is_described_and_left_as_it_was(template, tmp_path):
    copy = _database(template, tmp_path / "backups" / f"tracker_db_{STAMP}_manual.db", titles=3)
    before = _files(tmp_path)

    outcome = restore.check(copy, "", NOW)

    assert outcome == restore.Outcome(0, ["Копия от сегодня в 07:58 в порядке, тайтлов в ней: 3.",
                                          "@when от сегодня в 07:58"])
    assert _files(tmp_path) == before  # no `-wal` or `-shm` left next to it


def test_an_archive_opens_by_a_cyrillic_password(template, tmp_path):
    copy = _database(template, tmp_path / "made" / f"tracker_db_{STAMP}.db", titles=1)
    archive = _archive(copy, tmp_path / "restore" / f"tracker_db_{STAMP}.7z")
    before = _files(tmp_path)

    outcome = restore.check(archive, PASSWORD, NOW)

    assert outcome.code == 0
    assert outcome.lines[0] == "Копия от сегодня в 07:58 в порядке, тайтлов в ней: 1."
    assert _files(tmp_path) == before  # taken out into a temporary folder that is gone


def test_a_downloaded_name_without_a_time_is_named_by_the_copy_inside_or_by_itself(template, tmp_path):
    copy = _database(template, tmp_path / "made" / f"tracker_db_{STAMP}.db")
    archive = _archive(copy, tmp_path / "restore" / "копия (1).7z")
    plain = _database(template, tmp_path / "restore" / "моя копия.db")

    assert restore.check(archive, PASSWORD, NOW).lines[-1] == "@when от сегодня в 07:58"
    assert restore.check(plain, "", NOW).lines[-1] == "@when из файла моя копия.db"
    assert restore.phrase_of("tracker_db_20261399_000000.7z", NOW) == "из файла tracker_db_20261399_000000.7z"


def test_an_older_revision_is_accepted_with_the_note(template, tmp_path):
    copy = _database(template, tmp_path / f"tracker_db_{STAMP}.db", revision="0010")

    outcome = restore.check(copy, "", NOW)

    assert outcome.code == 0
    assert outcome.lines[1] == ("Копия от более старой версии: при запуске база обновится сама "
                                "(перед этим сделается ещё одна копия).")


def test_a_newer_revision_is_refused(template, tmp_path):
    copy = _database(template, tmp_path / f"tracker_db_{STAMP}.db", revision="0099")

    outcome = restore.check(copy, "", NOW)

    assert outcome == restore.Outcome(1, [
        f"Эта копия сделана более новой версией трекера (база 0099, а эта версия знает до {head_revision()}). "
        "Обновите трекер и запустите снова. Ничего не изменено."])


def _refusal(path: Path, password: str = PASSWORD) -> str:
    outcome = restore.check(path, password, NOW)
    assert outcome.code == 1 and len(outcome.lines) == 1
    return outcome.lines[0]


def test_an_archive_without_the_password_names_the_way_by_hand(template, tmp_path):
    archive = _archive(_database(template, tmp_path / f"tracker_db_{STAMP}.db"), tmp_path / "x.7z")

    assert _refusal(archive, "") == restore.NO_PASSWORD
    assert "В .env нет BACKUP_PASSWORD" in restore.NO_PASSWORD


def test_a_wrong_password_junk_and_a_cut_archive_are_one_text(template, tmp_path):
    copy = _database(template, tmp_path / f"tracker_db_{STAMP}.db")
    archive = _archive(copy, tmp_path / "good.7z")
    cut = tmp_path / "cut.7z"
    cut.write_bytes(archive.read_bytes()[: archive.stat().st_size // 2])
    plain = tmp_path / "plain.7z"  # names readable, only the content encrypted: a wrong password fails on extraction
    with py7zr.SevenZipFile(plain, "w", password=PASSWORD) as opened:
        opened.write(copy, copy.name)

    assert _refusal(archive, "другой пароль копий") == restore.BAD_PASSWORD
    assert _refusal(cut) == restore.BAD_PASSWORD
    assert _refusal(plain, "другой пароль копий") == restore.BAD_PASSWORD
    assert restore.BAD_PASSWORD.startswith("Пароль из .env не подходит к этой копии, или архив повреждён.")


def test_a_file_that_is_not_7z_is_said_so(tmp_path):
    junk = tmp_path / "tracker_db_20261108_075800.7z"
    junk.write_bytes(b"not an archive at all" * 10)

    assert _refusal(junk) == "Это не архив 7z. Ничего не изменено."


def test_an_archive_with_no_or_two_databases_is_not_a_copy(template, tmp_path):
    first = _database(template, tmp_path / "a.db")
    second = _database(template, tmp_path / "b.db")
    note = tmp_path / "note.txt"
    note.write_text("x")
    two, none = tmp_path / "two.7z", tmp_path / "none.7z"
    with py7zr.SevenZipFile(two, "w", password=PASSWORD) as opened:
        opened.write(first, first.name)
        opened.write(second, second.name)
    with py7zr.SevenZipFile(none, "w", password=PASSWORD) as opened:
        opened.write(note, note.name)

    assert _refusal(two) == "В архиве нет копии базы трекера. Ничего не изменено."
    assert _refusal(none) == "В архиве нет копии базы трекера. Ничего не изменено."


def test_a_damaged_database_and_junk_named_db_fail_the_sqlite_check(template, tmp_path):
    whole = _database(template, tmp_path / "whole.db", titles=50)
    cut = tmp_path / "cut.db"
    cut.write_bytes(whole.read_bytes()[: whole.stat().st_size // 3])
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"\x00garbage" * 1000)
    damaged = tmp_path / "damaged.db"
    data = bytearray(whole.read_bytes())
    data[4096 * 3: 4096 * 3 + 200] = b"\xff" * 200  # a page in the middle spoiled
    damaged.write_bytes(bytes(data))

    for file in (cut, junk, damaged):
        assert _refusal(file, "") == ("Копия повреждена (проверка SQLite не прошла). Ничего не изменено. "
                                      "Выберите другую копию."), file.name


def test_a_database_without_the_tracker_tables_is_not_a_copy(tmp_path):
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    other = tmp_path / "other.db"
    connection = sqlite3.connect(other)
    connection.execute("CREATE TABLE titles (id INTEGER)")
    connection.commit()
    connection.close()

    assert _refusal(empty, "") == "Этот файл не похож на копию базы трекера. Ничего не изменено."
    assert _refusal(other, "") == "Этот файл не похож на копию базы трекера. Ничего не изменено."


def test_a_missing_file_and_another_extension_are_refused(tmp_path):
    other = tmp_path / "copy.zip"
    other.write_bytes(b"x")

    assert _refusal(tmp_path / "gone.db") == f"Файл не найден: {tmp_path / 'gone.db'}"
    assert _refusal(other) == "Нужен файл .7z из Google Drive или .db из копий. Ничего не изменено."


# ---- apply ------------------------------------------------------------------

def _data_folder(template: Path, tmp_path: Path) -> Path:
    """`data` with a base (its newest change only in `-wal`) and the files a restore must not touch."""
    data = tmp_path / "data"
    _base_with_wal(template, data)
    (data / "web_secret").write_bytes(b"secret")
    (data / "google_drive_token.json").write_text('{"refresh_token": "x"}')
    (data / "google_drive_state.json").write_text("{}")
    (data / "startup_failure.json").write_text("{}")
    (data / "logs").mkdir()
    (data / "logs" / "bot.log").write_text("log line\n")
    return data


def _untouched(data: Path) -> dict[str, bytes]:
    return {name: content for name, content in _files(data).items()
            if not name.startswith("tracker.db") and not name.startswith("backups/")}


def test_apply_saves_the_current_base_with_its_wal_then_replaces_it(template, tmp_path):
    data = _data_folder(template, tmp_path)
    assert _only_main_file_marker(data / "tracker.db") == "old"  # the newest change is only in the `-wal`
    copy = _database(template, data / "backups" / f"tracker_db_{STAMP}.db", marker="restored", titles=2)
    others = _untouched(data)

    outcome = restore.apply(copy, data, "", NOW)

    before = data / "backups" / "tracker_db_20261108_120000_before-restore.db"
    assert outcome == restore.Outcome(0, ["Нынешняя база сохранена: data\\backups\\tracker_db_20261108_120000_before-restore.db",
                                          "База восстановлена из копии от сегодня в 07:58."])
    assert _marker(before) == "current"  # the content of the `-wal` is in the copy
    assert _marker(data / "tracker.db") == "restored"
    names = {path.name for path in data.iterdir()}
    assert not names & {"tracker.db-wal", "tracker.db-shm", "tracker.db.restoring"}
    assert _untouched(data) == others  # .env-like files, web_secret, the Google Drive files and the logs alone
    assert copy.exists()


def test_apply_from_a_downloaded_archive(template, tmp_path):
    data = _data_folder(template, tmp_path)
    made = _database(template, tmp_path / "made" / f"tracker_db_{STAMP}.db", marker="from drive")
    archive = _archive(made, data / "restore" / f"tracker_db_{STAMP}.7z")

    outcome = restore.apply(archive, data, PASSWORD, NOW)

    assert outcome.code == 0
    assert _marker(data / "tracker.db") == "from drive"
    assert _marker(data / "backups" / "tracker_db_20261108_120000_before-restore.db") == "current"


def test_apply_without_a_current_base_just_puts_the_copy(template, tmp_path):
    data = tmp_path / "data"
    copy = _database(template, data / "backups" / f"tracker_db_{STAMP}.db", marker="restored")

    outcome = restore.apply(copy, data, "", NOW)

    assert outcome == restore.Outcome(0, ["База восстановлена из копии от сегодня в 07:58."])
    assert _marker(data / "tracker.db") == "restored"


def test_a_before_restore_copy_can_be_restored_too(template, tmp_path):
    data = _data_folder(template, tmp_path)
    copy = _database(template, data / "backups" / f"tracker_db_{STAMP}.db", marker="restored")
    restore.apply(copy, data, "", NOW)
    back = data / "backups" / "tracker_db_20261108_120000_before-restore.db"

    outcome = restore.apply(back, data, "", datetime(2026, 11, 8, 12, 5))

    assert outcome.code == 0 and outcome.lines[-1] == "База восстановлена из копии от сегодня в 12:00."
    assert _marker(data / "tracker.db") == "current"
    assert _marker(data / "backups" / "tracker_db_20261108_120500_before-restore.db") == "restored"


def _assert_base_whole(data: Path, dump: str) -> None:
    assert _dump(data / "tracker.db") == dump
    assert not (data / "tracker.db.restoring").exists()


def test_a_refused_copy_changes_nothing(template, tmp_path):
    data = _data_folder(template, tmp_path)
    copy = _database(template, data / "backups" / f"tracker_db_{STAMP}.db", revision="0099")
    before = _files(data)

    outcome = restore.apply(copy, data, "", NOW)

    assert outcome.code == 1 and outcome.lines[0].startswith("Эта копия сделана более новой версией трекера")
    assert _files(data) == before


def test_a_full_disk_on_the_before_restore_copy_stops_everything(template, tmp_path, monkeypatch):
    data = _data_folder(template, tmp_path)
    copy = _database(template, data / "backups" / f"tracker_db_{STAMP}.db", marker="restored")
    before = _files(data)

    def full(source, target):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(restore, "copy_database", full)

    outcome = restore.apply(copy, data, "", NOW)

    assert outcome == restore.Outcome(1, ["Не удалось сохранить нынешнюю базу (на диске нет места). Ничего не изменено."])
    assert _files(data) == before  # the `-wal` too: nothing was checkpointed


@pytest.mark.parametrize("stage", ["checkpoint", "write", "integrity", "replace"])
def test_a_failure_before_the_replacement_leaves_the_base_whole(template, tmp_path, monkeypatch, stage):
    data = _data_folder(template, tmp_path)
    copy = _database(template, data / "backups" / f"tracker_db_{STAMP}.db", marker="restored")
    dump = _dump(_snapshot(data))
    real_copy = restore.copy_database

    if stage == "checkpoint":
        def broken_checkpoint(base):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(restore, "_checkpoint", broken_checkpoint)
    elif stage == "write":
        def copy_or_fail(source, target):
            if target.name.endswith(".restoring"):
                target.write_bytes(b"half")
                raise OSError(errno.ENOSPC, "No space left on device")
            real_copy(source, target)

        monkeypatch.setattr(restore, "copy_database", copy_or_fail)
    elif stage == "integrity":
        real_check = restore._integrity_ok
        monkeypatch.setattr(restore, "_integrity_ok", lambda file: real_check(file) and not file.name.endswith(".restoring"))
    else:
        def refuse(source, target):
            raise PermissionError(13, "Access is denied")

        monkeypatch.setattr(restore.os, "replace", refuse)

    outcome = restore.apply(copy, data, "", NOW)

    assert outcome.code == 1
    assert outcome.lines[0].startswith("Нынешняя база сохранена:")
    assert outcome.lines[1].startswith("Не удалось восстановить (") and outcome.lines[1].endswith("). База не тронута.")
    if stage == "write":
        assert "(на диске нет места)" in outcome.lines[1]
    assert _marker(data / "tracker.db") == "current"
    _assert_base_whole(data, dump)


def _snapshot(data: Path) -> Path:
    """A plain copy of the base with its `-wal`, to compare the content after a failed restore."""
    folder = data.parent / "snapshot"
    folder.mkdir(exist_ok=True)
    for suffix in ("", "-wal"):
        if Path(f"{data / 'tracker.db'}{suffix}").exists():
            shutil.copyfile(f"{data / 'tracker.db'}{suffix}", folder / f"tracker.db{suffix}")
    return folder / "tracker.db"


def test_a_failed_checkpoint_keeps_the_wal(template, tmp_path, monkeypatch):
    data = _data_folder(template, tmp_path)
    copy = _database(template, data / "backups" / f"tracker_db_{STAMP}.db")
    wal = (data / "tracker.db-wal").read_bytes()

    class Busy:
        def execute(self, sql):
            return self

        def fetchone(self):
            return (1, 10, 0)

        def close(self):
            pass

    monkeypatch.setattr(restore.sqlite3, "connect", lambda *args, **kwargs: Busy())
    with pytest.raises(sqlite3.OperationalError):
        restore._checkpoint(data / "tracker.db")
    monkeypatch.undo()

    assert (data / "tracker.db-wal").read_bytes() == wal
    assert copy.exists()


def test_an_older_copy_is_migrated_at_the_start_with_its_own_copy(tmp_path):
    data = tmp_path / "data"
    copy = _migrated(tmp_path / "made" / f"tracker_db_{STAMP}.db", "0013")
    assert restore.check(copy, "", NOW).lines[1] == restore.OLDER

    assert restore.apply(copy, data, "", NOW).code == 0
    factory = create_session_factory(f"sqlite:///{(data / 'tracker.db').as_posix()}", now=datetime(2026, 11, 8, 12, 1))
    factory.kw["bind"].dispose()

    assert restore.check(data / "tracker.db", "", NOW).lines == ["Копия из файла tracker.db в порядке, тайтлов в ней: 0.",
                                                                 "@when из файла tracker.db"]
    assert (data / "backups" / "tracker_db_20261108_120100_before-0013.db").exists()


# ---- the command line -------------------------------------------------------

def test_main_runs_the_command_on_the_data_folder_and_prints_its_lines(template, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _database(template, tmp_path / "data" / "backups" / f"tracker_db_{STAMP}.db")
    monkeypatch.setenv("BACKUP_PASSWORD", f"  {PASSWORD}  ")

    assert restore.main(["list"]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert printed[0] == "Копии базы в data\\backups (новые сверху):"
    assert printed[2] == f"@copy 1 data/backups/tracker_db_{STAMP}.db"

    assert restore.main(["check", f"data/backups/tracker_db_{STAMP}.db"]) == 0
    assert restore.main(["check", "data/restore/gone.7z"]) == 1
    assert restore.main(["undo"]) == 2


def test_main_reads_the_password_stripped(template, tmp_path, monkeypatch):
    archive = _archive(_database(template, tmp_path / f"tracker_db_{STAMP}.db"), tmp_path / "data" / "x.7z")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BACKUP_PASSWORD", f"  {PASSWORD}  ")

    assert restore.main(["check", str(archive)]) == 0


# ---- restore-bot.ps1 --------------------------------------------------------

def _script(name: str) -> str:
    raw = (ROOT / name).read_bytes()
    assert raw.startswith(BOM)  # with BOM, or Windows PowerShell 5.1 garbles the Russian text
    return raw.decode("utf-8-sig")


def test_the_script_has_every_text_of_the_spec():
    script = _script("restore-bot.ps1")

    for text in (
        "Номер копии (Enter — отмена)",
        "Нет копии с номером $answer.",
        "Отменено. Ничего не изменено.",
        "Файл не найден: $Path",
        "Нужен файл .7z из Google Drive или .db из копий. Ничего не изменено.",
        "Вернуть базу к копии $phrase? Всё, что изменилось позже, пропадёт. Нынешняя база сохранится отдельно. (да/нет)",
        "Бот не остановился за 60 секунд. База не тронута. Остановите его: .\\stop-bot.ps1 и запустите восстановление снова.",
        "Запускаю бота…",
        "Готово: бот работает на копии $phrase.",
        "База восстановлена, но бот не запустился — ошибка выше. Вернуть прежнюю базу: .\\restore-bot.ps1 и выберите копию «перед восстановлением».",
    ):
        assert text in script, text


def test_the_script_checks_docker_and_env_with_the_texts_of_the_start_script():
    start, script = _script("start-bot.ps1"), _script("restore-bot.ps1")
    checks = [line for line in start.splitlines() if line.strip().startswith("Write-Host") and (
        "Docker Desktop" in line or "файла .env" in line or "файле .env" in line or "Уберите знак" in line)]

    assert len(checks) == 5
    for line in checks:
        assert line in script, line
    lines = [line.strip() for line in script.splitlines()]
    at = lines.index("Set-Location $PSScriptRoot")
    assert lines[at + 1] == "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8"


def test_the_script_calls_the_one_off_container_and_the_bot_scripts():
    script = _script("restore-bot.ps1")

    assert ("docker compose run --rm --no-deps --build --quiet-build --interactive=false -T tracker python -m app.container_start app.utils.restore @Arguments"
            in script)
    assert 'Invoke-Restore @("list")' in script
    assert 'Invoke-Restore @("check", $copyPath)' in script and 'Invoke-Restore @("apply", $copyPath)' in script
    assert script.index('"check", $copyPath') < script.index("(да/нет)") < script.index("stop-bot.ps1")
    assert script.index("stop-bot.ps1") < script.index("docker compose ps -q tracker") < script.index('"apply", $copyPath')
    assert script.index('"apply", $copyPath') < script.rindex("start-bot.ps1")
    assert "$waited -le 60" in script


def test_the_script_takes_only_yes_and_empties_its_folder_whatever_happens():
    script = _script("restore-bot.ps1")

    assert """if (($answer -replace '\\s', '') -ne "да")""" in script  # -ne ignores case in PowerShell
    assert 'Join-Path $PSScriptRoot "data\\restore"' in script and '$copyPath = "data/restore/$fileName"' in script
    assert script.count("Clear-RestoreFolder") == 3  # the function, the start and the `finally`
    assert "} finally {\n    Clear-RestoreFolder\n}" in script.replace("\r\n", "\n")


def test_the_script_never_reads_values_of_env_and_hides_the_lines_for_itself():
    script = _script("restore-bot.ps1")

    assert "BACKUP_PASSWORD" not in script and "Select-String" not in script
    assert "'^@copy (\\d+) (.+)$'" in script and "StartsWith('@when ')" in script
    assert 'if (-not $line.StartsWith("@")) { Write-Host $line }' in script


def test_a_relative_path_counts_from_where_the_owner_stands_and_typed_answers_are_utf8():
    script = _script("restore-bot.ps1")

    resolve = "[System.IO.Path]::GetFullPath([System.IO.Path]::Combine((Get-Location).ProviderPath, $Path))"
    assert script.index(resolve) < script.index("Set-Location $PSScriptRoot")
    assert "if ([Console]::IsInputRedirected) { [Console]::InputEncoding = [System.Text.Encoding]::UTF8 }" in script
