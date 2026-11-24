"""The names of the copies in UTC (stage 9.1d, ticket 05; spec 10.1, KI-66) and the long listing of Google Drive (spec 10.2,
KI-67): the writers' names with `Z`, the names of before read in a given zone, the mixed order and rotation, the restore in
the zone of Settings, the pages of a folder."""

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.providers import google_drive as provider
from app.providers.google_drive import DriveFile, GoogleDriveApi
from app.tracker import db
from app.tracker.db import create_session_factory, name_moment
from app.tracker.drive_copies import ARCHIVE_NAME, own_archives
from app.utils import backup, restore
from app.utils.archive import archive_name

MOSCOW = ZoneInfo("Europe/Moscow")
TOKYO = ZoneInfo("Asia/Tokyo")
BERLIN = ZoneInfo("Europe/Berlin")
UTC_NOW = datetime(2026, 11, 8, 12, 0, 5)


def put(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"copy")
    return path


def make_database(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE titles (id INTEGER PRIMARY KEY, name TEXT)")
    connection.commit()
    connection.close()
    return f"sqlite:///{path.as_posix()}"


# --- writing: every writer puts the UTC time and a Z in the name --------------------------------------


def test_every_writer_names_its_copy_by_the_utc_time_with_a_z(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    folder = tmp_path / "backups"

    assert backup.create_backup(url, UTC_NOW).name == "tracker_db_20261108_120005Z.db"
    assert backup.create_manual_backup(url, UTC_NOW).path.name == "tracker_db_20261108_120005Z_manual.db"
    assert backup.backup_if_due(url, UTC_NOW + timedelta(days=2)).name == "tracker_db_20261110_120005Z.db"
    assert db.backup_name(UTC_NOW, "before-restore") == "tracker_db_20261108_120005Z_before-restore.db"
    assert sorted(path.name for path in folder.iterdir()) == [
        "tracker_db_20261108_120005Z.db", "tracker_db_20261108_120005Z_manual.db", "tracker_db_20261110_120005Z.db",
    ]


def test_the_copy_before_a_migration_is_named_in_utc_with_a_z(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    connection = sqlite3.connect(tmp_path / "tracker.db")
    connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
    connection.execute("INSERT INTO alembic_version VALUES ('0001')")
    connection.commit()
    connection.close()

    try:
        create_session_factory(url, now=UTC_NOW)
    except Exception:  # the made-up base cannot be migrated: the copy is made before the migration runs
        pass

    assert (tmp_path / "backups" / "tracker_db_20261108_120005Z_before-0001.db").exists()


def test_the_archive_of_a_copy_keeps_the_z(tmp_path):
    path = tmp_path / "tracker_db_20261108_120005Z_manual.db"

    assert archive_name(path) == "tracker_db_20261108_120005Z_manual.7z"
    assert ARCHIVE_NAME.match("tracker_db_20261108_120005Z_manual.7z")
    assert ARCHIVE_NAME.match("tracker_db_20261108_120005.7z")  # an archive of before 9.1d
    assert not ARCHIVE_NAME.match("tracker_db_20261108_120005ZZ.7z")


# --- reading: the Z as written, an old name in the zone it was written in -----------------------------


def test_a_name_with_z_is_read_as_written_and_one_without_in_the_old_zone(tmp_path):
    folder = tmp_path / "backups"
    put(folder, "tracker_db_20261108_120000Z.db")
    put(folder, "tracker_db_20261107_120000.db")

    found = backup.copies(folder, MOSCOW)

    assert [copy.moment for copy in found] == [datetime(2026, 11, 8, 12, 0), datetime(2026, 11, 7, 9, 0)]


def test_a_name_without_z_goes_by_the_zone_of_the_process_when_none_is_given():
    expected = datetime(2026, 11, 7, 12, 0).astimezone(timezone.utc).replace(tzinfo=None)

    assert name_moment("20261107_120000", None) == expected
    assert name_moment("20261107_120000", "Z") == datetime(2026, 11, 7, 12, 0)
    with pytest.raises(ValueError):
        name_moment("20261399_000000", "Z")


def test_at_the_hour_the_clocks_went_back_the_earlier_moment_is_taken():
    # Berlin, 25 October 2026: 02:30 happened twice (00:30 UTC and 01:30 UTC)
    assert name_moment("20261025_023000", None, BERLIN) == datetime(2026, 10, 25, 0, 30)
    assert name_moment("20261025_033000", None, BERLIN) == datetime(2026, 10, 25, 2, 30)


def test_old_and_new_names_mix_in_one_order_by_the_utc_moment(tmp_path):
    folder = tmp_path / "backups"
    old = put(folder, "tracker_db_20261010_080000.db")  # 05:00 UTC in Moscow, though 08 > 06 as digits
    new = put(folder, "tracker_db_20261010_060000Z.db")
    older_manual = put(folder, "tracker_db_20261010_070000_manual.db")  # 04:00 UTC

    assert [copy.path for copy in backup.copies(folder, MOSCOW)] == [new, old, older_manual]


def test_the_mixed_rotation_keeps_the_14_newest_and_the_earliest_of_the_month_in_utc(tmp_path):
    folder = tmp_path / "backups"
    old = [put(folder, f"tracker_db_202610{day:02d}_070000.db") for day in range(1, 11)]  # 04:00 UTC, Moscow names
    new = [put(folder, f"tracker_db_202610{day:02d}_050000Z.db") for day in range(11, 21)]

    backup.rotate(folder, datetime(2026, 10, 21, 5, 0), MOSCOW)

    kept = {path.name for path in folder.iterdir()}
    assert old[0].name in kept  # the earliest of the month stays
    assert not any(path.name in kept for path in old[1:6])  # 20 daily copies: the 5 oldest but the earliest go
    assert {path.name for path in old[6:] + new} <= kept
    assert len(kept) == 15


def test_the_newest_copy_before_a_revision_goes_by_the_utc_moment(tmp_path):
    folder = tmp_path / "backups"
    put(folder, "tracker_db_20261108_150000_before-0007.db")  # 12:00 UTC in Moscow
    new = put(folder, "tracker_db_20261108_130000Z_before-0007.db")  # later in UTC, earlier as digits

    assert db._newest_copy_before(folder, "0007", MOSCOW) == new


def test_the_archives_of_the_folder_mix_old_and_new_names_in_one_order():
    files = [
        DriveFile("1", "tracker_db_20261010_080000.7z"),
        DriveFile("2", "tracker_db_20261010_060000Z.7z"),
        DriveFile("3", "tracker_db_20261010_070000_manual.7z"),
        DriveFile("4", "notes.txt"),
    ]

    assert [file.id for file in own_archives(files, MOSCOW)] == ["2", "1", "3"]


# --- the restore: every moment in the zone of Settings ------------------------------------------------


def base_with_zone(data: Path, zone: str | None, raw: str | None = None) -> Path:
    data.mkdir(parents=True, exist_ok=True)
    base = data / "tracker.db"
    connection = sqlite3.connect(base)
    connection.execute("CREATE TABLE settings (key VARCHAR(64) PRIMARY KEY, value JSON)")
    if zone is not None or raw is not None:
        connection.execute("INSERT INTO settings VALUES ('timezone', ?)", (raw if raw is not None else json.dumps(zone),))
    connection.commit()
    connection.close()
    return base


def listed(data: Path, process_zone) -> list[str]:
    outcome = restore.run(["list"], data, "", datetime(2026, 11, 8, 12, 0), process_zone)
    return [line for line in outcome.lines if not line.startswith("@")]


def test_the_restore_reads_the_zone_of_settings_from_the_base(tmp_path):
    assert restore.zone_of_settings(base_with_zone(tmp_path / "a", "Asia/Tokyo")) == TOKYO
    assert restore.zone_of_settings(base_with_zone(tmp_path / "b", None)) is None  # none chosen
    assert restore.zone_of_settings(base_with_zone(tmp_path / "c", None, raw="null")) is None
    assert restore.zone_of_settings(base_with_zone(tmp_path / "d", "Nowhere/Land")) is None  # not a zone
    assert restore.zone_of_settings(base_with_zone(tmp_path / "e", None, raw="{not json")) is None
    assert restore.zone_of_settings(tmp_path / "missing.db") is None  # no base
    (tmp_path / "f").mkdir()
    (tmp_path / "f" / "tracker.db").write_bytes(b"not a database")
    assert restore.zone_of_settings(tmp_path / "f" / "tracker.db") is None
    (tmp_path / "g").mkdir()
    sqlite3.connect(tmp_path / "g" / "tracker.db").close()  # no `settings` table
    assert restore.zone_of_settings(tmp_path / "g" / "tracker.db") is None


def test_the_list_shows_every_copy_in_the_zone_of_settings(tmp_path):
    data = tmp_path / "data"
    base_with_zone(data, "Asia/Tokyo")
    put(data / "backups", "tracker_db_20261108_045800Z.db")  # 13:58 in Tokyo; now is 21:00 there
    put(data / "backups", "tracker_db_20261107_075800.db")  # a name of before: Moscow, 04:58 UTC, 13:58 in Tokyo

    assert listed(data, MOSCOW) == [restore.HEADER, "  1) сегодня в 13:58", "  2) вчера в 13:58"]


def test_without_a_zone_in_the_base_the_list_uses_the_zone_of_the_process(tmp_path):
    data = tmp_path / "data"
    base_with_zone(data, None)
    put(data / "backups", "tracker_db_20261108_045800Z.db")

    assert listed(data, MOSCOW) == [restore.HEADER, "  1) сегодня в 07:58"]
    assert listed(data, timezone.utc) == [restore.HEADER, "  1) сегодня в 04:58"]


def test_without_a_base_the_list_uses_the_zone_of_the_process(tmp_path):
    data = tmp_path / "data"
    put(data / "backups", "tracker_db_20261108_045800Z.db")

    assert listed(data, MOSCOW) == [restore.HEADER, "  1) сегодня в 07:58"]


def test_phrase_of_turns_a_z_name_and_an_old_name_into_the_shown_zone():
    clock = restore.Clock(datetime(2026, 11, 8, 12, 0), TOKYO, MOSCOW)

    assert restore.phrase_of("tracker_db_20261108_045800Z.7z", clock) == "от сегодня в 13:58"
    assert restore.phrase_of("tracker_db_20261108_075800.db", clock) == "от сегодня в 13:58"
    assert restore.phrase_of("моя копия.db", clock) == "из файла моя копия.db"
    assert restore.phrase_of("tracker_db_20261399_000000Z.7z", clock) == "из файла tracker_db_20261399_000000Z.7z"


# --- Google Drive: a listing of several pages --------------------------------------------------------


class Pages:
    """A fake `files.list` of `total` files that gives them `per_page` at a time by `nextPageToken`."""

    def __init__(self, total: int, per_page: int = 1000) -> None:
        self.total = total
        self.per_page = per_page
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        start = int(request.url.params.get("pageToken", "0"))
        end = min(start + self.per_page, self.total)
        body = {"files": [{"id": f"id-{n}", "name": f"tracker_db_{n}.7z", "size": "10"} for n in range(start, end)]}
        if end < self.total:
            body["nextPageToken"] = str(end)
        return httpx.Response(200, json=body)


def api_of(pages: Pages) -> GoogleDriveApi:
    return GoogleDriveApi("client", "secret", transport=httpx.MockTransport(pages.handle))


def test_a_folder_of_1001_files_is_listed_whole_in_two_pages():
    pages = Pages(1001)

    files = asyncio.run(api_of(pages).list_folder("access", "folder-1"))

    assert len(files) == 1001 and files[-1].id == "id-1000"
    assert len(pages.requests) == 2
    assert "pageToken" not in pages.requests[0].url.params and pages.requests[1].url.params["pageToken"] == "1000"
    assert pages.requests[0].url.params["fields"] == "nextPageToken,files(id,name,size,createdTime)"


def test_a_folder_search_goes_through_the_pages_too():
    pages = Pages(1001)

    found = asyncio.run(api_of(pages).find_folder("access", "Трекер — копии"))

    assert found == "id-0" and len(pages.requests) == 2


def test_a_listing_of_50_pages_stops_with_a_warning(caplog):
    pages = Pages(3000, per_page=50)  # 60 pages of 50
    with caplog.at_level(logging.WARNING):
        files = asyncio.run(api_of(pages).list_folder("access", "folder-1"))

    assert len(pages.requests) == provider.MAX_PAGES == 50
    assert len(files) == 2500
    assert "more than 50 pages" in caplog.text
