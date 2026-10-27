"""The report of a failure before the start (`app/startup_report.py`): the fingerprint, the record in
`data/startup_failure.json`, when the report goes (table 1.4 of the spec) and its text. The clock and the file are
the tests' own; nothing goes to the network."""

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

from app.startup_report import (
    Decision,
    FailureRecord,
    decide,
    fingerprint,
    forget_failure,
    heading,
    local_text,
    read_record,
    report_failure,
    write_record,
)

T0 = datetime(2026, 10, 27, 11, 5, tzinfo=timezone.utc)
MOSCOW = ZoneInfo("Europe/Moscow")


def fail(exc: BaseException) -> None:
    raise exc


def caught(exc: BaseException) -> BaseException:
    """The exception with a traceback, raised from the same places every time."""
    try:
        fail(exc)
    except BaseException as raised:
        return raised


def caught_elsewhere(exc: BaseException) -> BaseException:
    try:
        raise exc
    except BaseException as raised:
        return raised


def raise_from_one_of_two_lines(first: bool) -> None:
    if first:
        raise ValueError("the database is locked")
    raise ValueError("the database is locked")


def caught_on_line(first: bool) -> BaseException:
    try:
        raise_from_one_of_two_lines(first)
    except BaseException as raised:
        return raised


# ---- the fingerprint ------------------------------------------------------

def test_the_same_failure_twice_has_one_fingerprint():
    first = caught(ZoneInfoNotFoundError("No time zone found with key Europe/Moskva"))
    second = caught(ZoneInfoNotFoundError("No time zone found with key Europe/Moskva"))

    assert fingerprint(first) == fingerprint(second)


def test_another_typo_in_the_setting_is_another_failure():
    latin = caught(ZoneInfoNotFoundError("No time zone found with key Europe/Moskva"))
    cyrillic_s = caught(ZoneInfoNotFoundError("No time zone found with key Europe/Mosсow"))

    assert fingerprint(latin) != fingerprint(cyrillic_s)


def test_times_and_addresses_in_the_text_do_not_make_a_failure_new():
    first = caught(ValueError("at 2026-10-27 14:05:31 the object <Lock at 0x7f3a2c1b9e50> was busy"))
    second = caught(ValueError("at 2026-10-28 09:41:02 the object <Lock at 0x55d0aa01ff10> was busy"))

    assert fingerprint(first) == fingerprint(second)


def test_spaces_and_line_breaks_do_not_make_a_failure_new():
    assert fingerprint(caught(ValueError("a  b\n c"))) == fingerprint(caught(ValueError("a b c")))


def test_only_the_beginning_of_a_long_text_counts():
    assert fingerprint(caught(ValueError("x" * 300 + "tail one"))) == fingerprint(caught(ValueError("x" * 300 + "2")))


def test_the_line_in_the_function_does_not_count_the_function_does():
    assert fingerprint(caught_on_line(True)) == fingerprint(caught_on_line(False))
    assert fingerprint(caught(ValueError("the database is locked"))) != fingerprint(
        caught_elsewhere(ValueError("the database is locked"))
    )


def test_the_type_counts():
    assert fingerprint(caught(TimeoutError("no answer"))) != fingerprint(caught(ConnectionError("no answer")))


def test_the_record_holds_neither_the_text_of_the_failure_nor_the_token(tmp_path, monkeypatch):
    token = "123456789:AAH-secretTokenValue_abcdefghijklmnopqrstuv"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    file = tmp_path / "startup_failure.json"
    exc = caught(ZoneInfoNotFoundError(f"No time zone found with key Europe/Moskva; token {token}"))

    report_failure(exc, send=lambda heading: False, file=file, now=T0)

    text = file.read_text(encoding="utf-8")
    assert "Moskva" not in text and "zone" not in text and token not in text and "123456789" not in text
    assert json.loads(text)["fingerprint"] == fingerprint(exc)


# ---- when the report goes (table 1.4) -------------------------------------

def record(failure: str = "a", first_seen: datetime = T0, reported_at: datetime | None = T0) -> FailureRecord:
    return FailureRecord(failure, first_seen, reported_at)


def test_without_a_record_the_failure_is_new_and_reported_at_once():
    decision = decide("a", None, T0)

    assert (decision.send, decision.reminder) == (True, False)
    assert decision.after(sent=True, now=T0) == record("a", T0, T0)


def test_the_same_failure_within_a_day_of_the_report_is_not_reported_again():
    assert decide("a", record(), T0 + timedelta(minutes=1)).send is False
    assert decide("a", record(), T0 + timedelta(hours=23, minutes=59)).send is False


def test_the_same_failure_a_day_after_the_report_is_a_reminder():
    later = T0 + timedelta(hours=24)

    decision = decide("a", record(first_seen=T0 - timedelta(hours=5)), later)

    assert (decision.send, decision.reminder) == (True, True)
    assert decision.after(sent=True, now=later) == record("a", T0 - timedelta(hours=5), later)


def test_another_failure_is_reported_at_once_and_starts_its_own_record():
    later = T0 + timedelta(minutes=1)

    decision = decide("b", record("a"), later)

    assert (decision.send, decision.reminder) == (True, False)
    assert decision.after(sent=True, now=later) == record("b", later, later)


def test_the_same_failure_whose_report_did_not_go_out_is_reported_at_once():
    decision = decide("a", record(reported_at=None), T0 + timedelta(minutes=1))

    assert (decision.send, decision.reminder) == (True, True)


def test_a_report_time_in_the_future_means_the_clock_went_back_and_the_report_goes():
    assert decide("a", record(reported_at=T0 + timedelta(hours=3)), T0).send is True


def test_a_report_that_did_not_go_out_leaves_no_report_time():
    assert decide("a", None, T0).after(sent=False, now=T0).reported_at is None
    reminder = decide("a", record(reported_at=None), T0 + timedelta(minutes=1))
    assert reminder.after(sent=False, now=T0 + timedelta(minutes=1)) == record(reported_at=None)


# ---- the whole round with the file ----------------------------------------

class Telegram:
    def __init__(self, answers_200: bool = True) -> None:
        self.headings: list[str] = []
        self.answers_200 = answers_200

    def __call__(self, heading: str) -> bool:
        self.headings.append(heading)
        return self.answers_200


def test_one_and_the_same_failure_every_minute_is_reported_once_a_day(tmp_path):
    file = tmp_path / "startup_failure.json"
    telegram = Telegram()
    exc = caught(ZoneInfoNotFoundError("No time zone found with key Europe/Moskva"))

    for minute in range(0, 24 * 60 + 1, 1):  # a day of restarts, one a minute, and one more
        report_failure(exc, send=telegram, file=file, now=T0 + timedelta(minutes=minute))

    assert len(telegram.headings) == 2
    assert "Бот не запустился" in telegram.headings[0] and "Бот всё ещё не запускается" in telegram.headings[1]
    assert read_record(file) == record(fingerprint(exc), T0, T0 + timedelta(hours=24))


def test_a_report_that_did_not_go_out_is_tried_again_at_the_next_start(tmp_path):
    file = tmp_path / "startup_failure.json"
    offline = Telegram(answers_200=False)
    exc = caught(ConnectionError("no network"))

    report_failure(exc, send=offline, file=file, now=T0)
    report_failure(exc, send=offline, file=file, now=T0 + timedelta(minutes=1))

    assert len(offline.headings) == 2
    assert read_record(file) == record(fingerprint(exc), T0, None)


def test_a_failure_within_a_day_says_in_the_log_when_the_next_reminder_is(tmp_path, caplog):
    file = tmp_path / "startup_failure.json"
    exc = caught(ConnectionError("no network"))
    report_failure(exc, send=Telegram(), file=file, now=T0)

    with caplog.at_level(logging.INFO):
        report_failure(exc, send=Telegram(), file=file, now=T0 + timedelta(minutes=1))

    assert "отчёт о сбое запуска уже отправлен" in caplog.text and "следующее напоминание после" in caplog.text


@pytest.mark.parametrize("content", [
    "", "not json", "[]", '{"fingerprint": "a"}', '{"fingerprint": 5, "first_seen": "2026-10-27T11:05:00+00:00", '
    '"reported_at": null}', '{"fingerprint": "a", "first_seen": "yesterday", "reported_at": null}',
    '{"fingerprint": "a", "first_seen": "2026-10-27T11:05:00", "reported_at": null}',
])
def test_a_spoiled_record_counts_as_no_record(tmp_path, content):
    file = tmp_path / "startup_failure.json"
    file.write_text(content, encoding="utf-8")

    assert read_record(file) is None


def test_a_record_survives_the_round_through_the_file(tmp_path):
    file = tmp_path / "startup_failure.json"

    write_record(file, record("a", T0, None))
    assert read_record(file) == record("a", T0, None)
    write_record(file, record("a", T0, T0 + timedelta(hours=1)))
    assert read_record(file) == record("a", T0, T0 + timedelta(hours=1))


def test_a_record_that_cannot_be_written_does_not_stop_the_report(tmp_path, caplog):
    telegram = Telegram()
    not_a_file = tmp_path  # a folder: reading and writing it fail with OSError

    with caplog.at_level(logging.WARNING):
        report_failure(caught(ConnectionError("no network")), send=telegram, file=not_a_file, now=T0)
        report_failure(caught(ConnectionError("no network")), send=telegram, file=not_a_file, now=T0)

    assert len(telegram.headings) == 2  # no record: every start reports
    assert "запись о сбое запуска не сохранилась" in caplog.text


# ---- a successful start ---------------------------------------------------

def test_a_successful_start_removes_the_record_and_the_same_failure_is_new_again(tmp_path, caplog):
    file = tmp_path / "startup_failure.json"
    telegram = Telegram()
    exc = caught(ConnectionError("no network"))
    report_failure(exc, send=telegram, file=file, now=T0)

    with caplog.at_level(logging.INFO):
        forget_failure(file)
    report_failure(exc, send=telegram, file=file, now=T0 + timedelta(minutes=5))

    assert "сбой запуска (с " in caplog.text and "больше не повторяется" in caplog.text
    assert len(telegram.headings) == 2 and "Бот не запустился" in telegram.headings[1]


def test_a_successful_start_without_a_record_says_nothing(tmp_path, caplog):
    with caplog.at_level(logging.INFO):
        forget_failure(tmp_path / "startup_failure.json")

    assert caplog.text == ""


def test_a_record_that_cannot_be_removed_is_a_warning(tmp_path, caplog):
    folder = tmp_path / "startup_failure.json"
    folder.mkdir()  # unlink of a folder fails with OSError

    with caplog.at_level(logging.WARNING):
        forget_failure(folder)

    assert "запись о сбое запуска не удалилась" in caplog.text


# ---- the text -------------------------------------------------------------

def test_the_report_of_a_new_failure_says_docker_retries_and_when_it_reminds():
    text = heading(decide("a", None, T0))

    assert text == ("⚠️ <b>Бот не запустился.</b> Docker повторяет запуск каждую минуту. "
                    "Об этом же сбое напомню через сутки, если он не пройдёт; о другом сбое — сразу.")


def test_the_reminder_says_since_when_by_the_container_clock():
    reminder = Decision(True, True, T0, record())

    assert heading(reminder, MOSCOW) == ("⚠️ <b>Бот всё ещё не запускается</b> (с 27.10 14:05). "
                                         "Следующее напоминание — через сутки.")


def test_the_time_is_day_month_hours_minutes():
    assert local_text(datetime(2026, 3, 4, 5, 6, tzinfo=timezone.utc), timezone.utc) == "04.03 05:06"
