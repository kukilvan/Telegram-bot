"""The login report (ticket 05 of stage 7.2, spec 6): the two events `web_login` and `web_login_locked`, their texts, the
dedup keys, the send at once in the background (a hanging sender does not hold the answer, a failing one leaves the event
pending), the Feed that never shows them, and the sample «Вход в приложение» in the bot's list and in Settings.

On the real core and the real web app. The test client is used as a context manager: the send is a task of the app's own
event loop, which then lives as long as the client does."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.runtime import Health
from app.tracker.core import WEB_LOGIN, WEB_LOGIN_LOCKED, Tracker
from app.tracker.db import create_session_factory
from app.tracker.models import DeliveryItem, DeliveryStatus, Event
from app.web import create_web_app
from app.web.auth import LOCK_SECONDS

PASSWORD = "correct horse battery"
WRONG = "not the password"
NOW = datetime(2026, 11, 17, 11, 32, tzinfo=timezone.utc)
ANDROID_CHROME = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
)
WINDOWS_CHROME = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)
LOGIN_TEXT = (
    "🔐 Вход в приложение: Android, Chrome, сегодня в 11:32{address}.\n"
    "Если это были не вы — откройте Настройки и нажмите «Выйти на всех устройствах», затем смените WEB_PASSWORD в .env."
)
LOCKED_TEXT = (
    "⚠️ Вход в приложение закрыт на 15 минут: 5 неверных паролей подряд. "
    "Последняя попытка: Android, Chrome, сегодня в 11:32{address}.\n"
    "Если это были не вы — смените WEB_PASSWORD в .env."
)


class Clock:
    def __init__(self) -> None:
        self.now = NOW.timestamp()

    def __call__(self) -> float:
        return self.now


class Sender:
    """Records what it was asked to send; can fail or hang (until the loop ends)."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.attempts = 0
        self.failing = False
        self.hanging = False

    async def send(self, message, actions=()):
        self.attempts += 1
        if self.hanging:
            await asyncio.Event().wait()
        if self.failing:
            raise ConnectionError("telegram is down")
        self.messages.append(message)


def wait_for(condition, seconds: float = 5.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def settle() -> None:
    time.sleep(0.3)  # long enough for a send that should not happen to have happened


@pytest.fixture(autouse=True)
def login_reports_off():
    """Overrides the fixture of `conftest.py` of the same name: here the reports are what is tested."""


@pytest.fixture
def sender():
    return Sender()


@pytest.fixture
def tracker(sender):
    return Tracker(create_session_factory("sqlite://"), clock=lambda: NOW, sender=sender, sources={})


@pytest.fixture
def clock():
    return Clock()


def app_of(tracker, tmp_path, clock):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    return create_web_app(
        health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", login_file=tmp_path / "web_login.json",
        clock=clock, tracker=tracker, now=lambda: NOW,
    )


@pytest.fixture
def client(tracker, tmp_path, clock):
    with TestClient(app_of(tracker, tmp_path, clock), follow_redirects=False, headers={"user-agent": ANDROID_CHROME}) as client:
        yield client


def events(tracker) -> list[Event]:
    with tracker.session_factory() as session:
        return list(session.scalars(select(Event).order_by(Event.id)))


def statuses(tracker) -> list[DeliveryStatus]:
    with tracker.session_factory() as session:
        return [item.status for item in session.scalars(select(DeliveryItem).order_by(DeliveryItem.id))]


def log_in(client, password=PASSWORD):
    return client.post("/login", data={"password": password})


def wrong_tries(client, count: int):
    return [log_in(client, WRONG) for _ in range(count)]


# ---- a right password ------------------------------------------------------

def test_a_right_password_queues_one_login_event_and_sends_it_at_once(client, tracker, sender):
    response = log_in(client)

    assert response.status_code == 303
    assert wait_for(lambda: sender.messages)
    assert sender.messages == [LOGIN_TEXT.format(address="")]
    [event] = events(tracker)
    assert (event.type, event.title_id) == (WEB_LOGIN, None)
    assert event.payload == {"text": LOGIN_TEXT.format(address="")}
    assert wait_for(lambda: statuses(tracker) == [DeliveryStatus.DELIVERED])


def test_the_address_is_in_the_message_only_when_it_is_public(tracker, sender, tmp_path, clock):
    app = app_of(tracker, tmp_path, clock)
    with TestClient(app, follow_redirects=False, headers={"user-agent": ANDROID_CHROME}, client=("8.8.8.8", 50000)) as client:
        log_in(client)
        assert wait_for(lambda: sender.messages)

    assert sender.messages == [LOGIN_TEXT.format(address=", адрес 8.8.8.8")]


def test_a_private_address_is_not_named(tracker, sender, tmp_path, clock):
    app = app_of(tracker, tmp_path, clock)
    with TestClient(app, follow_redirects=False, headers={"user-agent": ANDROID_CHROME}, client=("172.18.0.1", 50000)) as client:
        log_in(client)
        assert wait_for(lambda: sender.messages)

    assert "адрес" not in sender.messages[0]


def test_the_device_of_the_message_comes_from_the_user_agent(tracker, sender, tmp_path, clock):
    app = app_of(tracker, tmp_path, clock)
    with TestClient(app, follow_redirects=False, headers={"user-agent": WINDOWS_CHROME}) as client:
        log_in(client)
        assert wait_for(lambda: sender.messages)

    assert sender.messages[0].startswith("🔐 Вход в приложение: Windows, Chrome, сегодня в 11:32.")


def test_a_wrong_password_alone_sends_nothing(client, tracker, sender):
    assert log_in(client, WRONG).status_code == 401

    settle()
    assert sender.messages == [] and events(tracker) == []


def test_the_message_is_sent_whatever_the_delivery_rules_say(client, tracker, sender):
    # 11:32 of a work day with quiet hours around it: the rules would hold a message, the report is sent at once
    asyncio.run(tracker.set_delivery_rules(workdays=[0, 1, 2, 3, 4], quiet_from="10:00", quiet_until="13:00"))

    log_in(client)

    assert wait_for(lambda: sender.messages)


# ---- the lock --------------------------------------------------------------

def test_the_fifth_wrong_password_queues_the_lock_event_and_the_four_before_send_nothing(client, tracker, sender):
    first_four = wrong_tries(client, 4)
    settle()

    assert [r.status_code for r in first_four] == [401] * 4
    assert sender.messages == [] and events(tracker) == []

    fifth = log_in(client, WRONG)

    assert fifth.status_code == 429
    assert wait_for(lambda: sender.messages)
    assert sender.messages == [LOCKED_TEXT.format(address="")]
    [event] = events(tracker)
    assert (event.type, event.title_id) == (WEB_LOGIN_LOCKED, None)


def test_a_locked_try_sends_nothing_more_even_with_the_right_password(client, tracker, sender):
    wrong_tries(client, 5)
    assert wait_for(lambda: sender.messages)

    sixth = log_in(client, WRONG)
    seventh = log_in(client)

    assert sixth.status_code == seventh.status_code == 429
    settle()
    assert len(sender.messages) == 1 and [e.type for e in events(tracker)] == [WEB_LOGIN_LOCKED]


def test_two_locks_in_a_row_have_their_own_keys_and_both_come(client, tracker, sender, clock):
    wrong_tries(client, 5)
    assert wait_for(lambda: len(sender.messages) == 1)

    clock.now += LOCK_SECONDS + 1  # the first lock is over
    wrong_tries(client, 5)

    assert wait_for(lambda: len(sender.messages) == 2)
    keys = [event.dedup_key for event in events(tracker)]
    assert len(set(keys)) == 2 and all(key.startswith("web_login_locked:") for key in keys)


def test_the_key_of_a_lock_is_the_end_of_the_lock(client, tracker, clock):
    wrong_tries(client, 5)

    [event] = events(tracker)
    assert event.dedup_key == f"web_login_locked:{int(NOW.timestamp()) + LOCK_SECONDS}"


# ---- the send does not hold the answer, a failure leaves the event ----------

def test_a_sender_that_hangs_does_not_hold_the_answer_of_the_login(client, sender):
    sender.hanging = True

    with ThreadPoolExecutor(max_workers=1) as pool:
        response = pool.submit(log_in, client).result(timeout=5)  # a hang would raise here

    assert response.status_code == 303
    assert wait_for(lambda: sender.attempts == 1)  # the send was tried and is still under way
    assert sender.messages == []


def test_a_failing_sender_leaves_the_event_pending_and_a_later_delivery_sends_it(client, tracker, sender):
    sender.failing = True

    assert log_in(client).status_code == 303
    assert wait_for(lambda: sender.attempts >= 1)
    settle()

    assert sender.messages == [] and statuses(tracker) == [DeliveryStatus.PENDING]
    sender.failing = False
    asyncio.run(tracker.deliver_pending())
    assert sender.messages == [LOGIN_TEXT.format(address="")]
    assert statuses(tracker) == [DeliveryStatus.DELIVERED]


def test_a_report_that_cannot_be_recorded_never_stops_the_login(client, tracker, monkeypatch, caplog):
    async def broken(*args, **kwargs):
        raise RuntimeError("the database is busy")

    monkeypatch.setattr(tracker, "record_login_report", broken)

    response = log_in(client)

    assert response.status_code == 303
    assert client.get("/settings").status_code == 200  # signed in all the same
    assert "login report could not be recorded" in caplog.text


def test_a_login_report_waits_in_the_queue_by_the_rules_when_the_send_failed_at_night(client, tracker, sender):
    asyncio.run(tracker.set_delivery_rules(quiet_from="10:00", quiet_until="13:00"))  # 11:32 is quiet
    sender.failing = True
    log_in(client)
    assert wait_for(lambda: sender.attempts >= 1)
    settle()
    sender.failing = False

    asyncio.run(tracker.deliver_pending())  # by the rules: held

    assert sender.messages == [] and statuses(tracker) == [DeliveryStatus.PENDING]  # KI-73


# ---- the core: one method, the facts in, the text out ----------------------

def record(tracker, event_type=WEB_LOGIN, unique="a" * 32, device="Android, Chrome", address=None, moment=NOW):
    return asyncio.run(tracker.record_login_report(event_type, unique, device, address, moment))


def test_the_same_login_never_reports_twice(tracker):
    first = record(tracker)
    again = record(tracker)

    assert first is not None and again is None
    assert [event.dedup_key for event in events(tracker)] == ["web_login:" + "a" * 32]


def test_a_login_and_a_lock_with_the_same_unique_part_are_two_facts(tracker):
    assert record(tracker, WEB_LOGIN, "1") is not None
    assert record(tracker, WEB_LOGIN_LOCKED, "1") is not None


def test_the_moment_is_in_words_on_the_owners_clock(tracker):
    asyncio.run(tracker.set_delivery_rules(tz_name="Asia/Jerusalem"))  # UTC+2 in November

    record(tracker, moment=NOW)
    record(tracker, unique="b" * 32, moment=NOW - timedelta(days=1))

    texts = [event.payload["text"] for event in events(tracker)]
    assert "Android, Chrome, сегодня в 13:32." in texts[0]
    assert "Android, Chrome, вчера в 13:32." in texts[1]


def test_a_type_that_is_no_report_is_refused(tracker):
    with pytest.raises(ValueError):
        record(tracker, "backup_failed")
    assert events(tracker) == []


# ---- the Feed, the sample --------------------------------------------------

def test_the_feed_shows_neither_event(client, tracker, sender):
    record(tracker)
    record(tracker, WEB_LOGIN_LOCKED, "1")
    log_in(client)
    assert wait_for(lambda: sender.messages)

    feed = asyncio.run(tracker.feed())
    page = client.get("/")

    assert feed.recent == () and feed.upcoming == () and page.status_code == 200
    assert "Вход в приложение" not in page.text and "web_login" not in page.text


def test_the_sample_is_listed_with_the_others(tracker):
    samples = {sample.id: sample for sample in tracker.test_samples()}

    assert samples["web-login"].label == "Вход в приложение"
    assert "backup-failed-local" in samples  # the others stay


def test_the_sample_is_sent_with_the_example_device_and_address(tracker, sender):
    result = asyncio.run(tracker.send_test_event("web-login"))

    assert result.delivered
    [text] = sender.messages
    assert "Тестовое событие «Вход в приложение»: 🔐 Вход в приложение: Android, Chrome, " in text
    assert ", адрес 203.0.113.5." in text
    assert "«Выйти на всех устройствах»" in text


def test_the_sample_is_in_the_settings_list(client):
    log_in(client)
    page = client.get("/settings")

    assert 'value="web-login"' in page.text and "Вход в приложение" in page.text
