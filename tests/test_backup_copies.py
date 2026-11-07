"""Copies of the database (spec 1 and 2.2 of stage 7.1): the kinds and names, the order, the rotation of the manual and
the daily copies that do not see each other, the lock of the hourly job and the press, the report `backup_failed`, the lines
of the block. Files in a temporary folder, the real core on a file database, the clock and the container's clock fixed."""

import asyncio
import errno
import logging
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.tracker import backup_events, backup_rows
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import DeliveryItem, Event
from app.utils import backup

MOSCOW = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 29, 19, 10, tzinfo=timezone.utc)  # Thursday 22:10 in Moscow
WALL = datetime(2026, 10, 29, 22, 10, 5)  # the container's clock at that moment
FULL_DISK = "⚠️ Копия базы не сделана: на диске нет места."


def run(coro):
    return asyncio.run(coro)


class FakeClock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


class FakeSender:
    def __init__(self):
        self.messages = []

    async def send(self, message, actions=()):
        self.messages.append(message)


@pytest.fixture
def folder(tmp_path):
    return tmp_path / "backups"


@pytest.fixture
def clock():
    return FakeClock(NOW)


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def tracker(tmp_path, clock, sender):
    url = f"sqlite:///{(tmp_path / 'tracker.db').as_posix()}"
    core = Tracker(create_session_factory(url), clock=clock, sender=sender, default_tz=MOSCOW, database_url=url)
    core._backups.wall_clock = lambda: WALL
    return core


def put(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(b"copy")
    return path


def stamp(moment: datetime, suffix: str = "") -> str:
    return f"tracker_db_{moment:%Y%m%d_%H%M%S}{'_' + suffix if suffix else ''}.db"


def names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def events(tracker, type=backup_events.BACKUP_FAILED):
    with tracker.session_factory() as session:
        return list(session.scalars(select(Event).where(Event.type == type).order_by(Event.id)))


def make_database(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE titles (id INTEGER PRIMARY KEY, name TEXT)")
    connection.commit()
    connection.close()
    return f"sqlite:///{path.as_posix()}"


# --- what a copy is -------------------------------------------------------------------------------


def test_the_kinds_of_names_are_copies_and_the_look_alikes_are_not(folder):
    real = [
        stamp(datetime(2026, 5, 1, 7, 0)), stamp(datetime(2026, 5, 2, 7, 0), "manual"),
        stamp(datetime(2026, 5, 3, 7, 0), "before-0014"), stamp(datetime(2026, 5, 4, 7, 0), "before-restore"),
    ]
    for name in real + [
        "tracker_db_20261301_000000.db",  # no such month
        "tracker_db_20260230_000000.db",  # no such day
        "tracker_db_20260501_070000_other.db", "tracker_db_20260501_070000_manual2.db",
        "tracker_db_20260501_070000_before-.db", "tracker_db_20260501_070000.db.bak",
        "tracker_db_20260501_07000.db", "old_tracker_db_20260501_070000.db", "notes.txt",
    ]:
        put(folder, name)

    found = backup.copies(folder)

    assert [c.path.name for c in found] == list(reversed(real))
    assert {c.kind for c in found} == {backup.DAILY, backup.MANUAL, backup.OTHER}


def test_copies_are_newest_first_and_equal_times_go_daily_manual_others(folder):
    moment = datetime(2026, 5, 1, 7, 0)
    for name in (
        stamp(moment, "before-0014"), stamp(moment, "manual"), stamp(moment), stamp(moment + timedelta(seconds=1), "manual"),
        stamp(moment - timedelta(days=1)),
    ):
        put(folder, name)

    kinds = [(c.moment, c.kind) for c in backup.copies(folder)]

    assert kinds == [
        (moment + timedelta(seconds=1), backup.MANUAL), (moment, backup.DAILY), (moment, backup.MANUAL),
        (moment, backup.OTHER), (moment - timedelta(days=1), backup.DAILY),
    ]


def test_a_missing_folder_has_no_copies_and_an_unreadable_one_raises(folder):
    assert backup.copies(folder) == []

    put(folder, stamp(WALL))
    with patch.object(Path, "iterdir", side_effect=PermissionError("denied")), pytest.raises(OSError):
        backup.copies(folder)


# --- rotation -------------------------------------------------------------------------------------


def test_a_manual_copy_is_named_manual_and_the_10_newest_stay(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    folder = tmp_path / "backups"
    for number in range(12):
        backup.create_manual_backup(url, WALL + timedelta(seconds=number))

    kept = [c.moment for c in backup.copies(folder)]

    assert len(kept) == 10 and kept[0] == datetime(2026, 10, 29, 22, 10, 16) and kept[-1] == datetime(2026, 10, 29, 22, 10, 7)
    assert all(p.name.endswith("_manual.db") for p in folder.iterdir())


def test_the_manual_rotation_never_touches_the_daily_or_the_other_copies(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    folder = tmp_path / "backups"
    safe = [put(folder, stamp(datetime(2020, 1, day))) for day in range(1, 21)]  # 20 daily copies, years old
    safe.append(put(folder, stamp(datetime(2020, 1, 1), "before-0013")))
    safe.append(put(folder, stamp(datetime(2020, 1, 1), "before-restore")))
    for number in range(11):
        backup.create_manual_backup(url, WALL + timedelta(seconds=number))

    assert all(path.exists() for path in safe)
    assert len([c for c in backup.copies(folder) if c.kind == backup.MANUAL]) == 10


def test_the_daily_rotation_never_sees_the_manual_copies(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    folder = tmp_path / "backups"
    manual = [put(folder, stamp(datetime(2020, 1, day), "manual")) for day in range(1, 11)]  # old, but manual
    for day in range(1, 21):
        put(folder, stamp(datetime(2026, 10, day)))

    backup.create_backup(url, WALL)

    assert all(path.exists() for path in manual)
    daily = [c for c in backup.copies(folder) if c.kind == backup.DAILY]
    assert len(daily) == 14 + 1  # the 14 newest and the earliest of the month that has older ones


def test_a_manual_copy_does_not_move_the_daily_schedule(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    folder = tmp_path / "backups"
    put(folder, stamp(WALL - timedelta(hours=25)))
    backup.create_manual_backup(url, WALL)

    made = backup.backup_if_due(url, WALL + timedelta(seconds=1))

    assert made is not None and made.name == stamp(WALL + timedelta(seconds=1))


def test_a_manual_copy_of_the_same_second_is_refused_and_nothing_is_rewritten(tmp_path):
    url = make_database(tmp_path / "tracker.db")
    first = backup.create_manual_backup(url, WALL)
    first.path.write_bytes(b"marker")

    with pytest.raises(FileExistsError):
        backup.create_manual_backup(url, WALL)

    assert first.path.read_bytes() == b"marker"


def test_a_daily_and_a_manual_copy_of_the_same_second_are_both_made(tmp_path):
    url = make_database(tmp_path / "tracker.db")

    backup.create_backup(url, WALL)
    backup.create_manual_backup(url, WALL)

    assert names(tmp_path / "backups") == [stamp(WALL), stamp(WALL, "manual")]


# --- the press: the lock, the notices ---------------------------------------------------------------


def test_the_press_makes_a_manual_copy_and_says_when(tracker, tmp_path):
    notice = run(tracker.make_backup_now())

    assert notice == "Копия сделана: сегодня в 22:10."
    assert names(tmp_path / "backups") == [stamp(WALL, "manual")]


def test_a_second_press_in_the_same_second_is_already_working(tracker, tmp_path):
    run(tracker.make_backup_now())

    assert run(tracker.make_backup_now()) == "Копия уже делается — подождите несколько секунд."
    assert names(tmp_path / "backups") == [stamp(WALL, "manual")]


def test_a_press_in_the_next_second_makes_the_next_copy(tracker, tmp_path):
    run(tracker.make_backup_now())
    tracker._backups.wall_clock = lambda: WALL + timedelta(seconds=1)

    assert run(tracker.make_backup_now()) == "Копия сделана: сегодня в 22:10."
    assert len(names(tmp_path / "backups")) == 2


def test_a_press_while_another_press_works_does_not_wait_and_makes_no_second_copy(tracker, tmp_path):
    real = backup.create_manual_backup

    def slow(url, now=None):
        time.sleep(0.2)
        return real(url, now)

    async def two_presses():
        with patch.object(backup, "create_manual_backup", slow):
            return await asyncio.gather(tracker.make_backup_now(), tracker.make_backup_now())

    first, second = run(two_presses())

    assert first == "Копия сделана: сегодня в 22:10."
    assert second == "Копия уже делается — подождите несколько секунд."
    assert len(names(tmp_path / "backups")) == 1


def test_a_press_waits_for_the_hourly_copy_and_then_makes_its_own(tracker, tmp_path):
    order = []
    real_due, real_manual = backup.backup_if_due, backup.create_manual_backup

    def slow_due(url, now=None):
        order.append("hourly starts")
        time.sleep(0.2)
        order.append("hourly ends")
        return real_due(url, now)

    def manual(url, now=None):
        order.append("press copies")
        return real_manual(url, now)

    async def both():
        with patch.object(backup, "backup_if_due", slow_due), patch.object(backup, "create_manual_backup", manual):
            hourly = asyncio.create_task(tracker.backup_database())
            await asyncio.sleep(0.05)  # the hourly copy holds the lock
            notice = await tracker.make_backup_now()
            await hourly
            return notice

    notice = run(both())

    assert notice == "Копия сделана: сегодня в 22:10."
    assert order == ["hourly starts", "hourly ends", "press copies"]


def test_a_press_that_waits_too_long_for_the_hourly_copy_is_already_working(tracker, tmp_path):
    def slow_due(url, now=None):
        time.sleep(0.3)

    async def both():
        with patch.object(backup, "backup_if_due", slow_due), patch("app.tracker.backups.PRESS_WAITS_SECONDS", 0.05):
            hourly = asyncio.create_task(tracker.backup_database())
            await asyncio.sleep(0.05)
            notice = await tracker.make_backup_now()
            await hourly
            return notice

    assert run(both()) == "Копия уже делается — подождите несколько секунд."
    assert not (tmp_path / "backups").exists() or names(tmp_path / "backups") == []


def test_the_hourly_job_waits_for_a_press_under_way(tracker, tmp_path):
    real = backup.create_manual_backup
    order = []

    def slow_manual(url, now=None):
        order.append("press copies")
        time.sleep(0.2)
        return real(url, now)

    def due(url, now=None):
        order.append("hourly checks")

    async def both():
        with patch.object(backup, "create_manual_backup", slow_manual), patch.object(backup, "backup_if_due", due):
            pressing = asyncio.create_task(tracker.make_backup_now())
            await asyncio.sleep(0.05)
            await tracker.backup_database()
            await pressing

    run(both())

    assert order == ["press copies", "hourly checks"]


@pytest.mark.parametrize("error, reason", [
    (OSError(errno.ENOSPC, "No space left on device"), "на диске нет места"),
    (sqlite3.OperationalError("some other trouble"), "ошибка, подробности в журнале"),
    (RuntimeError("boom"), "ошибка, подробности в журнале"),
])
def test_a_failed_press_says_why_and_leaves_the_lock_free(tracker, error, reason, caplog):
    with patch.object(backup, "create_manual_backup", side_effect=error), caplog.at_level(logging.WARNING):
        notice = run(tracker.make_backup_now())

    assert notice == f"Копия не сделана: {reason}."
    assert "Manual database backup failed" in caplog.text
    assert run(tracker.make_backup_now()).startswith("Копия сделана")  # the lock was released and the press is free again


def test_the_full_disk_error_of_sqlite_is_the_reason_no_space():
    error = sqlite3.OperationalError("database or disk is full")
    error.sqlite_errorcode = sqlite3.SQLITE_FULL

    assert backup_events.reason_of(error) == backup_events.NO_SPACE


def test_a_press_without_a_database_file_is_not_made(clock, sender):
    core = Tracker(create_session_factory("sqlite://"), clock=clock, sender=sender, default_tz=MOSCOW)

    assert run(core.make_backup_now()) == "Копия не сделана: ошибка, подробности в журнале."


# --- the report of a failed daily copy --------------------------------------------------------------


def failing_hourly(tracker, error):
    with patch.object(backup, "backup_if_due", side_effect=error):
        run(tracker.backup_database())


def test_a_failed_daily_copy_queues_the_event_with_the_reason_and_the_last_copy(tracker, tmp_path):
    put(tmp_path / "backups", stamp(datetime(2026, 10, 28, 18, 32)))

    failing_hourly(tracker, OSError(errno.ENOSPC, "No space left on device"))

    [event] = events(tracker)
    assert event.title_id is None
    assert event.payload["text"] == f"{FULL_DISK} Последняя — вчера в 18:32. Попробую снова через час."
    assert event.dedup_key == "backup_failed:local:2026-10-29"


def test_another_error_gives_the_general_reason_and_no_copy_says_so(tracker):
    failing_hourly(tracker, RuntimeError("secret detail"))

    [event] = events(tracker)
    assert event.payload["text"] == (
        "⚠️ Копия базы не сделана: ошибка, подробности в журнале. Копий базы на этом ПК пока нет. Попробую снова через час."
    )
    assert "secret detail" not in event.payload["text"]


def test_the_failure_is_reported_once_a_day_on_the_owners_date(tracker, clock):
    failing_hourly(tracker, OSError(errno.ENOSPC, "full"))
    failing_hourly(tracker, OSError(errno.ENOSPC, "full"))
    assert len(events(tracker)) == 1

    clock.now = NOW + timedelta(hours=1)  # 23:10 in Moscow, the same date
    failing_hourly(tracker, OSError(errno.ENOSPC, "full"))
    assert len(events(tracker)) == 1

    clock.now = NOW + timedelta(hours=5)  # 03:10 on the 30th in Moscow, but still the 29th in UTC
    failing_hourly(tracker, OSError(errno.ENOSPC, "full"))
    assert [e.dedup_key for e in events(tracker)] == ["backup_failed:local:2026-10-29", "backup_failed:local:2026-10-30"]


def test_a_copy_that_is_made_or_not_due_reports_nothing(tracker, tmp_path):
    run(tracker.backup_database())  # makes the first daily copy
    run(tracker.backup_database())  # not due

    assert events(tracker) == [] and len(backup.copies(tmp_path / "backups")) == 1


def test_a_failed_press_is_no_event(tracker):
    with patch.object(backup, "create_manual_backup", side_effect=OSError(errno.ENOSPC, "full")):
        run(tracker.make_backup_now())

    assert events(tracker) == []


def test_the_report_goes_out_by_the_delivery_rules_and_the_feed_does_not_show_it(tracker, sender):
    failing_hourly(tracker, OSError(errno.ENOSPC, "full"))

    run(tracker.deliver_pending(force=True))

    assert sender.messages == [f"{FULL_DISK} Копий базы на этом ПК пока нет. Попробую снова через час."]
    assert run(tracker.feed()).recent == ()
    with tracker.session_factory() as session:
        assert [item.status.value for item in session.scalars(select(DeliveryItem))] == ["delivered"]


def test_a_failing_report_does_not_stop_the_job(tracker, caplog):
    with patch.object(tracker._backups.queue, "record_event", side_effect=RuntimeError("queue is broken")):
        with caplog.at_level(logging.WARNING):
            failing_hourly(tracker, OSError(errno.ENOSPC, "full"))  # does not raise

    assert "report of the failed backup was not made" in caplog.text


def test_a_core_without_a_database_file_does_nothing_in_the_hourly_job(clock, sender):
    core = Tracker(create_session_factory("sqlite://"), clock=clock, sender=sender, default_tz=MOSCOW)

    run(core.backup_database())

    assert events(core) == []


def test_the_sample_of_the_report_is_in_the_test_event_list(tracker, sender):
    sample = next(s for s in tracker.test_samples() if s.id == "backup-failed-local")

    assert sample.label == "Копия базы не сделана"
    run(tracker.send_test_event("backup-failed-local"))
    assert sender.messages == [
        f"🧪 Тестовое событие «Копия базы не сделана»: {FULL_DISK} Последняя — вчера в 18:32. Попробую снова через час."
    ]


# --- the block ------------------------------------------------------------------------------------


def test_the_block_says_how_many_copies_and_when_the_newest_is(tracker, tmp_path):
    folder = tmp_path / "backups"
    put(folder, stamp(datetime(2026, 10, 28, 7, 58)))
    put(folder, stamp(datetime(2026, 10, 29, 7, 58)))
    put(folder, stamp(datetime(2026, 10, 29, 7, 58), "manual"))
    put(folder, stamp(datetime(2026, 10, 20, 7, 58), "before-0014"))
    put(folder, "tracker_db_junk.db")

    block = run(tracker.backup_block())

    assert block.copies_line == "Копии базы на этом ПК: 4, последняя — сегодня в 07:58."
    assert block.copies_hint == backup_rows.COPIES_HINT


def test_the_block_without_copies_says_the_first_is_coming(tracker):
    assert run(tracker.backup_block()).copies_line == "Копий базы на этом ПК пока нет: первая сделается в течение часа."


def test_a_folder_that_cannot_be_read_is_a_line_and_a_warning(tracker, tmp_path, caplog):
    put(tmp_path / "backups", stamp(WALL))

    with patch.object(Path, "iterdir", side_effect=PermissionError("denied")), caplog.at_level(logging.WARNING):
        block = run(tracker.backup_block())

    assert block.copies_line == "Копии базы на этом ПК не прочитать — подробности в журнале."
    assert block.copies_hint == backup_rows.COPIES_HINT
    assert "cannot be read" in caplog.text


def test_the_block_is_read_in_a_worker_thread(tracker, tmp_path):
    seen = []
    real = backup.copies

    def spying(folder):
        seen.append(threading.current_thread())
        return real(folder)

    async def read():
        with patch.object(backup, "copies", spying):
            await tracker.backup_block()
        return threading.current_thread()

    assert run(read()) is not seen[0]


def test_the_block_counts_the_time_of_a_name_as_written_whatever_the_zone(tracker, clock, tmp_path):
    put(tmp_path / "backups", stamp(datetime(2026, 10, 29, 7, 58)))
    clock.now = datetime(2026, 10, 29, 21, 30, tzinfo=timezone.utc)  # 30 October, 00:30 in Moscow

    assert run(tracker.backup_block()).copies_line.endswith("последняя — вчера в 07:58.")
