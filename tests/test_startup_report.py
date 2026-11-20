"""The report of a failure before the start (`app/startup_report.py`): the fingerprint (code and text), the record in
`data/startup_failure.json` and in the temp folder, when the report goes (table 1.1 of the spec of 9.1a) and its text.
The clock and the files are the tests' own; nothing goes to the network."""

import dataclasses
import json
import logging
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

import app.startup_report as startup_report
from app.startup_report import (
    Decision,
    FailureRecord,
    Fingerprint,
    decide,
    fingerprint,
    forget_failure,
    heading,
    load_record,
    local_text,
    masked_text,
    read_record,
    report_failure,
    temp_file,
    write_record,
)

T0 = datetime(2026, 10, 27, 11, 5, tzinfo=timezone.utc)
MOSCOW = ZoneInfo("Europe/Moscow")


@pytest.fixture(autouse=True)
def temp_folder(tmp_path, monkeypatch):
    """The record's second home is a folder of the test, never the real temp folder."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "temp"))


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


# ---- the masked text ------------------------------------------------------

@pytest.mark.parametrize("text, masked", [
    ("cannot open tmpk3j9x_q", "cannot open #"),  # a temporary name with a digit
    ("cannot open /tmp/cache", "cannot open #"),  # a path
    (r"cannot open C:\data\x.json", "cannot open #"),
    ("port 8080 is busy", "port # is busy"),
    ("the object <Lock at 0x7f3a2c1b9e50> was busy", "the object <Lock at # was busy"),
    ("a  b\n c", "a b c"),  # spaces folded
    ("  edges  ", "edges"),
    ("", ""),
])
def test_a_word_with_a_digit_or_a_slash_is_masked_and_spaces_are_folded(text, masked):
    assert masked_text(text) == masked


def test_only_the_first_300_characters_of_the_masked_text_count():
    assert masked_text("x" * 400) == "x" * 300
    assert masked_text("x" * 299 + " tail") == "x" * 299 + " "


def test_a_token_in_the_text_is_masked(monkeypatch):
    token = "123456789:AAH-secretTokenValue_abcdefghijklmnopqrstuv"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)

    assert token not in masked_text(f"bad token {token}") and "123456789" not in masked_text(f"bad token {token}")


# ---- the fingerprint ------------------------------------------------------

def test_the_same_failure_twice_has_one_fingerprint():
    first = caught(ZoneInfoNotFoundError("No time zone found with key Europe/Moskva"))
    second = caught(ZoneInfoNotFoundError("No time zone found with key Europe/Moskva"))

    assert fingerprint(first) == fingerprint(second)


def test_another_word_in_the_text_is_another_fingerprint_with_the_same_code():
    first = fingerprint(caught(ValueError("cannot open lucky")))
    second = fingerprint(caught(ValueError("cannot open unlucky")))

    assert first.code == second.code and first.full != second.full


def test_temp_names_paths_times_and_addresses_in_the_text_do_not_change_the_fingerprint():
    first = caught(ValueError("at 2026-10-27 14:05:31 /tmp/tmpk3j9x_q was busy <Lock at 0x7f3a2c1b9e50>"))
    second = caught(ValueError("at 2026-10-28 09:41:02 /tmp/tmp8h2qwe was busy <Lock at 0x55d0aa01ff10>"))

    assert fingerprint(first) == fingerprint(second)


def test_the_line_in_the_function_does_not_count_the_function_does():
    assert fingerprint(caught_on_line(True)) == fingerprint(caught_on_line(False))
    assert fingerprint(caught(ValueError("the database is locked"))).code != fingerprint(
        caught_elsewhere(ValueError("the database is locked"))
    ).code


def test_the_type_counts_in_the_code():
    assert fingerprint(caught(TimeoutError("no answer"))).code != fingerprint(caught(ConnectionError("no answer"))).code


def test_the_record_holds_neither_the_text_of_the_failure_nor_the_token(tmp_path, monkeypatch):
    token = "123456789:AAH-secretTokenValue_abcdefghijklmnopqrstuv"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    file = tmp_path / "startup_failure.json"
    exc = caught(ZoneInfoNotFoundError(f"No time zone found with key Europe/Moskva; token {token}"))

    report_failure(exc, send=lambda heading: False, file=file, now=T0)

    text = file.read_text(encoding="utf-8")
    assert "Moskva" not in text and "zone" not in text and token not in text and "123456789" not in text
    assert json.loads(text)["code"] == fingerprint(exc).code
    assert json.loads(text)["fingerprint"] == fingerprint(exc).full


# ---- when the report goes (table 1.1) -------------------------------------

def fp(code: str = "c", text: str = "t") -> Fingerprint:
    return Fingerprint(code, code + text)


def record(code: str = "c", text: str = "t", first_seen: datetime = T0, reported_at: datetime | None = T0) -> FailureRecord:
    return FailureRecord(code, code + text, first_seen, reported_at)


def test_without_a_record_the_failure_is_new_and_reported_at_once():
    decision = decide(fp(), None, T0)

    assert (decision.send, decision.reminder) == (True, False)
    assert decision.after(sent=True, now=T0) == record()


def test_another_place_is_reported_at_once_and_starts_its_own_record():
    later = T0 + timedelta(minutes=1)

    decision = decide(fp("b"), record("c", reported_at=T0), later)

    assert (decision.send, decision.reminder) == (True, False)
    assert decision.after(sent=True, now=later) == record("b", first_seen=later, reported_at=later)


def test_the_same_failure_within_a_day_of_the_report_is_not_reported_again():
    assert decide(fp(), record(), T0 + timedelta(minutes=1)).send is False
    assert decide(fp(), record(), T0 + timedelta(hours=23, minutes=59)).send is False


def test_the_same_failure_a_day_after_the_report_is_a_reminder_that_keeps_first_seen():
    later = T0 + timedelta(hours=24)
    started = T0 - timedelta(hours=5)

    decision = decide(fp(), record(first_seen=started), later)

    assert (decision.send, decision.reminder) == (True, True)
    assert decision.after(sent=True, now=later) == record(first_seen=started, reported_at=later)


def test_the_same_failure_whose_report_did_not_go_out_is_reported_at_once():
    decision = decide(fp(), record(reported_at=None), T0 + timedelta(minutes=1))

    assert (decision.send, decision.reminder) == (True, True)


def test_a_report_time_in_the_future_means_the_clock_went_back_and_the_report_goes():
    assert decide(fp(), record(reported_at=T0 + timedelta(hours=3)), T0).send is True
    assert decide(fp(text="other"), record(reported_at=T0 + timedelta(hours=3)), T0).send is True


def test_the_same_place_with_another_text_waits_an_hour_after_the_report():
    assert decide(fp(text="other"), record(), T0 + timedelta(minutes=59)).send is False

    decision = decide(fp(text="other"), record(), T0 + timedelta(hours=1))

    assert (decision.send, decision.reminder) == (True, False)


def test_a_text_that_is_not_reported_is_not_saved_so_the_next_one_compares_with_the_reported():
    skipped = decide(fp(text="other"), record(), T0 + timedelta(minutes=10))

    assert skipped.send is False and skipped.record == record()
    assert skipped.after(sent=False, now=T0 + timedelta(minutes=10)) == record()


def test_the_same_place_with_another_text_that_is_reported_keeps_first_seen_and_takes_the_new_text():
    started = T0 - timedelta(hours=5)
    later = T0 + timedelta(hours=2)

    decision = decide(fp(text="other"), record(first_seen=started), later)

    assert decision.after(sent=True, now=later) == record(text="other", first_seen=started, reported_at=later)


def test_the_same_place_with_another_text_whose_report_did_not_go_out_waits_for_the_next_start():
    decision = decide(fp(text="other"), record(), T0 + timedelta(hours=2))

    assert decision.send is True
    assert decision.after(sent=False, now=T0 + timedelta(hours=2)) == record()  # the old reported one: due again


def test_a_report_that_did_not_go_out_leaves_no_report_time():
    assert decide(fp(), None, T0).after(sent=False, now=T0).reported_at is None
    reminder = decide(fp(), record(reported_at=None), T0 + timedelta(minutes=1))
    assert reminder.after(sent=False, now=T0 + timedelta(minutes=1)) == record(reported_at=None)


# ---- the whole round with the file ----------------------------------------

class Telegram:
    def __init__(self, answers_200: bool = True) -> None:
        self.headings: list[str] = []
        self.answers_200 = answers_200

    def __call__(self, heading: str) -> bool:
        self.headings.append(heading)
        return self.answers_200


NEW = "Бот не запустился"
STILL = "Бот всё ещё не запускается"


def test_failures_with_changing_text_go_by_the_sequence_of_the_spec(tmp_path):
    file = tmp_path / "startup_failure.json"
    telegram = Telegram()

    def met(exc: BaseException, minutes: int) -> int:
        before = len(telegram.headings)
        report_failure(exc, send=telegram, file=file, now=T0 + timedelta(minutes=minutes))
        return len(telegram.headings) - before

    assert met(caught(ValueError("cannot open tmpk3j9x_q")), 0) == 1  # the first one
    assert met(caught(ValueError("cannot open /tmp/zz9")), 1) == 0  # a temp name and a path differ: still the same
    assert met(caught(ValueError("cannot open lucky")), 10) == 0  # a random word within the hour
    assert met(caught(ValueError("cannot open lucky")), 60) == 1  # the hour is over, compared with the reported text
    assert telegram.headings[-1].startswith("⚠️ <b>" + NEW)
    assert met(caught(ValueError("cannot open lucky")), 61) == 0  # the text now in the record
    assert met(caught_elsewhere(ValueError("cannot open lucky")), 62) == 1  # another place: at once
    assert len(telegram.headings) == 3


def test_a_text_that_changes_every_minute_gives_one_report_an_hour(tmp_path):
    file = tmp_path / "startup_failure.json"
    telegram = Telegram()

    for minute in range(0, 3 * 60):
        exc = caught(ValueError(f"cannot open word{chr(97 + minute % 26)}{chr(97 + minute // 26)}x"))
        report_failure(exc, send=telegram, file=file, now=T0 + timedelta(minutes=minute))

    assert len(telegram.headings) == 3  # at minutes 0, 60 and 120


def test_the_reminder_after_24_hours_keeps_first_seen(tmp_path):
    file = tmp_path / "startup_failure.json"
    telegram = Telegram()
    exc = caught(ConnectionError("no network"))

    for minute in (0, 24 * 60):
        report_failure(exc, send=telegram, file=file, now=T0 + timedelta(minutes=minute))

    assert STILL in telegram.headings[1]
    assert read_record(file).first_seen == T0


def test_one_and_the_same_failure_every_minute_is_reported_once_a_day(tmp_path):
    file = tmp_path / "startup_failure.json"
    telegram = Telegram()
    exc = caught(ZoneInfoNotFoundError("No time zone found with key Europe/Moskva"))

    for minute in range(0, 24 * 60 + 1, 1):  # a day of restarts, one a minute, and one more
        report_failure(exc, send=telegram, file=file, now=T0 + timedelta(minutes=minute))

    assert len(telegram.headings) == 2
    assert NEW in telegram.headings[0] and STILL in telegram.headings[1]
    found = fingerprint(exc)
    assert read_record(file) == FailureRecord(found.code, found.full, T0, T0 + timedelta(hours=24))


def test_a_report_that_did_not_go_out_is_tried_again_at_the_next_start(tmp_path):
    file = tmp_path / "startup_failure.json"
    offline = Telegram(answers_200=False)
    exc = caught(ConnectionError("no network"))

    report_failure(exc, send=offline, file=file, now=T0)
    report_failure(exc, send=offline, file=file, now=T0 + timedelta(minutes=1))

    assert len(offline.headings) == 2
    found = fingerprint(exc)
    assert read_record(file) == FailureRecord(found.code, found.full, T0, None)


def test_a_failure_within_a_day_says_in_the_log_when_the_next_reminder_is(tmp_path, caplog):
    file = tmp_path / "startup_failure.json"
    exc = caught(ConnectionError("no network"))
    report_failure(exc, send=Telegram(), file=file, now=T0)

    with caplog.at_level(logging.INFO):
        report_failure(exc, send=Telegram(), file=file, now=T0 + timedelta(minutes=1))

    assert "отчёт о сбое запуска уже отправлен" in caplog.text and "следующее напоминание после" in caplog.text


def test_the_same_place_with_another_text_says_in_the_log_when_the_next_report_is(tmp_path, caplog):
    file = tmp_path / "startup_failure.json"
    report_failure(caught(ValueError("cannot open one")), send=Telegram(), file=file, now=T0)

    with caplog.at_level(logging.INFO):
        report_failure(caught(ValueError("cannot open two")), send=Telegram(), file=file, now=T0 + timedelta(minutes=1))

    assert "текст другой" in caplog.text and "следующий не раньше" in caplog.text


def valid(**changes) -> dict:
    data = {"code": "c", "fingerprint": "f", "first_seen": "2026-10-27T11:05:00+00:00", "reported_at": None}
    return {**data, **changes}


@pytest.mark.parametrize("content", [
    "", "not json", "[]", '{"code": "c", "fingerprint": "a"}',
    json.dumps(valid(fingerprint=5)), json.dumps(valid(code=5)), json.dumps(valid(first_seen="yesterday")),
    json.dumps(valid(first_seen="2026-10-27T11:05:00")),
])
def test_a_spoiled_record_counts_as_no_record(tmp_path, content):
    file = tmp_path / "startup_failure.json"
    file.write_text(content, encoding="utf-8")

    assert read_record(file) is None


def test_a_record_of_the_old_form_reads_as_no_record_and_the_failure_is_reported_at_once(tmp_path):
    file = tmp_path / "startup_failure.json"
    old = {"fingerprint": "a", "first_seen": "2026-10-27T11:05:00+00:00", "reported_at": "2026-10-27T11:05:00+00:00"}
    file.write_text(json.dumps(old), encoding="utf-8")
    telegram = Telegram()
    exc = caught(ConnectionError("no network"))
    assert read_record(file) is None and load_record(file) is None

    report_failure(exc, send=telegram, file=file, now=T0 + timedelta(minutes=1))

    assert len(telegram.headings) == 1 and NEW in telegram.headings[0]
    assert read_record(file).code == fingerprint(exc).code  # the record starts anew in the new form


def test_a_record_survives_the_round_through_the_file(tmp_path):
    file = tmp_path / "startup_failure.json"

    write_record(file, record(reported_at=None))
    assert read_record(file) == record(reported_at=None)
    write_record(file, record(reported_at=T0 + timedelta(hours=1)))
    assert read_record(file) == record(reported_at=T0 + timedelta(hours=1))


# ---- a record that cannot be saved (1.2) ----------------------------------

def unwritable(tmp_path: Path) -> Path:
    """A path under a plain file: making its folder fails with OSError on every system."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a folder", encoding="utf-8")
    return blocker / "startup_failure.json"


def test_when_data_is_unwritable_the_record_goes_to_the_temp_folder_and_the_next_decision_reads_it(tmp_path, caplog):
    file = unwritable(tmp_path)
    telegram = Telegram()
    exc = caught(ConnectionError("no network"))

    with caplog.at_level(logging.WARNING):
        report_failure(exc, send=telegram, file=file, now=T0)
    report_failure(exc, send=telegram, file=file, now=T0 + timedelta(minutes=1))

    assert len(telegram.headings) == 1  # the second start knows of the first report
    found = fingerprint(exc)
    assert read_record(temp_file()) == FailureRecord(found.code, found.full, T0, T0)
    assert caplog.text.count("запись о сбое запуска сохранена во временную папку") == 1
    assert str(temp_file()) in caplog.text and "data недоступна" in caplog.text


def test_the_temp_file_is_called_by_the_project_in_the_temp_folder():
    assert temp_file() == Path(tempfile.gettempdir()) / "release-tracker-startup_failure.json"


def test_when_both_files_cannot_be_written_it_is_a_warning_and_every_start_reports(tmp_path, monkeypatch, caplog):
    plain_file = tmp_path / "plain"
    plain_file.write_text("x", encoding="utf-8")
    monkeypatch.setattr(tempfile, "tempdir", str(plain_file))  # the temp folder is no folder either
    telegram = Telegram()

    with caplog.at_level(logging.WARNING):
        report_failure(caught(ConnectionError("no network")), send=telegram, file=unwritable(tmp_path), now=T0)
        report_failure(caught(ConnectionError("no network")), send=telegram, file=unwritable(tmp_path), now=T0)

    assert len(telegram.headings) == 2
    assert "запись о сбое запуска не сохранилась" in caplog.text


def test_a_record_that_cannot_be_saved_does_not_stop_the_report(tmp_path):
    telegram = Telegram()

    report_failure(caught(ConnectionError("no network")), send=telegram, file=unwritable(tmp_path), now=T0)

    assert len(telegram.headings) == 1


def test_when_both_files_hold_a_record_the_later_one_wins(tmp_path):
    file = tmp_path / "startup_failure.json"
    write_record(file, record("c", reported_at=T0))
    write_record(temp_file(), record("c", text="newer", reported_at=T0 + timedelta(hours=1)))

    assert load_record(file) == record("c", text="newer", reported_at=T0 + timedelta(hours=1))

    write_record(file, record("c", text="latest", first_seen=T0 + timedelta(hours=2), reported_at=None))

    assert load_record(file).fingerprint == "clatest"  # no report yet: the first sight counts


def test_one_of_two_files_alone_is_the_record(tmp_path):
    file = tmp_path / "startup_failure.json"

    assert load_record(file) is None
    write_record(temp_file(), record())
    assert load_record(file) == record()


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
    assert len(telegram.headings) == 2 and NEW in telegram.headings[1]


def test_a_successful_start_removes_both_files(tmp_path):
    file = tmp_path / "startup_failure.json"
    write_record(file, record())
    write_record(temp_file(), record())

    forget_failure(file)

    assert not file.exists() and not temp_file().exists()


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


# ---- the names (1.3) ------------------------------------------------------

def test_the_module_has_no_kind_and_the_decision_has_no_first_seen():
    source = Path(startup_report.__file__).read_text(encoding="utf-8")

    assert not re.search(r"\bkind\b", source)
    assert "first_seen" not in {field.name for field in dataclasses.fields(Decision)}
    assert "failure" not in decide.__code__.co_varnames[: decide.__code__.co_argcount]  # the parameter says what it is


# ---- the text -------------------------------------------------------------

def test_the_report_of_a_new_failure_says_docker_retries_and_when_it_reminds():
    text = heading(decide(fp(), None, T0))

    assert text == ("⚠️ <b>Бот не запустился.</b> Docker повторяет запуск каждую минуту. "
                    "Об этом же сбое напомню через сутки, если он не пройдёт; о другом сбое — сразу.")


def test_the_report_of_the_same_place_with_another_text_is_the_report_of_a_new_failure():
    text = heading(decide(fp(text="other"), record(), T0 + timedelta(hours=2)))

    assert text.startswith("⚠️ <b>Бот не запустился.</b>")


def test_the_reminder_says_since_when_by_the_container_clock():
    reminder = Decision(True, True, record(), fp())

    assert heading(reminder, MOSCOW) == ("⚠️ <b>Бот всё ещё не запускается</b> (с 27.10 14:05). "
                                         "Следующее напоминание — через сутки.")


def test_the_time_is_day_month_hours_minutes():
    assert local_text(datetime(2026, 3, 4, 5, 6, tzinfo=timezone.utc), timezone.utc) == "04.03 05:06"
