"""Sign-ins kept on the server (ticket 03 of stage 7.2, spec 4): the store `data/web_login.json` (absent, spoiled,
unreadable, unwritable, the atomic rewrite, the hourly `seen`, 30 days, 20 sign-ins), the session middleware (who is a
stranger, the notice through a redirect, HTMX), login, «Выйти» (KI-8), «Выйти на всех устройствах», the lock across a
restart (KI-7), the spoiled key (KI-13) and the block «Вход» of Settings."""

import asyncio
import json
import logging
from base64 import b64decode, b64encode
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import itsdangerous
import pytest
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.web import create_web_app, pages
from app.web.auth import LOCK_SECONDS, fingerprint
from app.web.devices import UNKNOWN_DEVICE
from app.web.sessions import LIFE_SECONDS, MAX_SIGN_INS, SEEN_STEP_SECONDS, LastLogin, SignIns
from app.web.settings_sign_in import HINT, NO_LAST_LOGIN, SIGNED_OUT_EVERYWHERE, devices_line, last_login_line

PASSWORD = "correct horse battery"
WRONG = "not the password"
NOW = datetime(2026, 11, 17, 11, 32, 5, tzinfo=timezone.utc)  # 14:32 in Moscow
MOSCOW = ZoneInfo("Europe/Moscow")
POSIX = Path("/").anchor == "/"  # the rights of a file only mean something off Windows
SPOILED = "web_login.json испорчен — все входы закрыты, счётчик неверных паролей обнулён"


class FakeClock:
    """The wall clock in UTC seconds."""

    def __init__(self) -> None:
        self.now = NOW.timestamp()

    def __call__(self) -> float:
        return self.now


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def data(tmp_path):
    return tmp_path / "data"


def login_file(data):
    return data / "web_login.json"


def make_app(data, clock, password=PASSWORD, tracker=None):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    return create_web_app(
        health=health.report, password=password, secret_file=data / "web_secret", login_file=login_file(data),
        clock=clock, tracker=tracker, now=lambda: datetime.fromtimestamp(clock(), timezone.utc),
    )


def client_of(app):
    return TestClient(app, follow_redirects=False)


def sign_in(client):
    response = client.post("/login", data={"password": PASSWORD})
    assert response.status_code == 303, response.text
    return response


def is_signed_in(client):
    return client.get("/nowhere").status_code == 404  # the 404 page, not the way to the login


def stored(data):
    return json.loads(login_file(data).read_text(encoding="utf-8"))


def run(coro):
    return asyncio.run(coro)


# ---- the store ------------------------------------------------------------

def test_an_absent_file_is_empty_without_a_warning(data, clock, caplog):
    with caplog.at_level(logging.WARNING):
        store = SignIns(login_file(data), clock)

    assert store.count == 0 and store.last_login is None and store.guard.state == (0, None)
    assert caplog.text == "" and not login_file(data).exists()


@pytest.mark.parametrize("text", [
    "not json",
    "",
    '{"version": 2, "sessions": {}, "last_login": null, "guard": {"wrong": 0, "locked_until": null}}',
    '{"version": 1, "sessions": [], "last_login": null, "guard": {"wrong": 0, "locked_until": null}}',
    '{"version": 1, "sessions": {"short": {"since": "2026-11-15T11:32:05Z", "seen": "2026-11-15T11:32:05Z", "device": "x"}},'
    ' "last_login": null, "guard": {"wrong": 0, "locked_until": null}}',
    '{"version": 1, "sessions": {}, "last_login": {"at": "yesterday", "device": "x", "address": null},'
    ' "guard": {"wrong": 0, "locked_until": null}}',
    '{"version": 1, "sessions": {}, "last_login": null, "guard": {"wrong": true, "locked_until": null}}',
    '{"version": 1, "sessions": {}, "last_login": null}',
    '[1, 2]',
])
def test_a_spoiled_file_is_empty_with_the_warning_and_is_rewritten_at_the_next_change(data, clock, caplog, text):
    data.mkdir()
    login_file(data).write_text(text, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        store = SignIns(login_file(data), clock)

    assert SPOILED in caplog.text
    assert store.count == 0 and store.last_login is None and store.guard.state == (0, None)
    run(store.sign_in("x", None))
    assert stored(data)["version"] == 1 and len(stored(data)["sessions"]) == 1


def test_a_spoiled_file_closes_every_sign_in_of_the_app(data, clock):
    first = client_of(make_app(data, clock))
    sign_in(first)
    login_file(data).write_text("{broken", encoding="utf-8")

    second = client_of(make_app(data, clock))  # the restart reads the spoiled file
    second.cookies.set("tracker_session", first.cookies["tracker_session"])

    assert not is_signed_in(second)


def test_an_unreadable_file_leaves_everything_in_memory(data, clock, caplog):
    login_file(data).mkdir(parents=True)  # a folder where the file should be: reading it fails

    with caplog.at_level(logging.WARNING):
        client = client_of(make_app(data, clock))
        sign_in(client)

    assert "web_login.json не прочитать" in caplog.text
    assert "web_login.json не записать" in caplog.text
    assert is_signed_in(client)


def test_an_unwritable_file_keeps_the_sign_ins_in_memory_and_warns_once(tmp_path, clock, caplog):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the folder should be")
    store = SignIns(blocker / "web_login.json", clock)

    with caplog.at_level(logging.WARNING):
        first = run(store.sign_in("x", None))
        second = run(store.sign_in("y", None))

    assert store.live(first) and store.live(second) and store.count == 2
    assert caplog.text.count("web_login.json не записать") == 1


def test_a_change_is_written_by_a_temporary_file_moved_over_the_old_one(data, clock):
    store = SignIns(login_file(data), clock)
    sid = run(store.sign_in("Android, Chrome", None))
    run(store.sign_in("Windows, Edge", None))

    assert sorted(path.name for path in data.iterdir()) == ["web_login.json"]  # no temporary file left
    document = stored(data)
    assert document["version"] == 1 and len(document["sessions"]) == 2
    assert document["sessions"][sid] == {
        "since": "2026-11-17T11:32:05Z", "seen": "2026-11-17T11:32:05Z", "device": "Android, Chrome"}
    assert document["last_login"] == {"at": "2026-11-17T11:32:05Z", "device": "Windows, Edge", "address": None}
    assert document["guard"] == {"wrong": 0, "locked_until": None}
    assert len(sid) == 32 and all(char in "0123456789abcdef" for char in sid)
    if POSIX:
        assert login_file(data).stat().st_mode & 0o777 == 0o600


def test_the_store_reads_back_what_it_wrote(data, clock):
    store = SignIns(login_file(data), clock)
    sid = run(store.sign_in("Android, Chrome", None))

    again = SignIns(login_file(data), clock)

    assert again.live(sid) and again.count == 1 and again.last_login == store.last_login


def test_seen_is_written_at_most_once_an_hour(data, clock):
    store = SignIns(login_file(data), clock)
    sid = run(store.sign_in("x", None))

    clock.now += SEEN_STEP_SECONDS - 1
    run(store.touch(sid))
    assert stored(data)["sessions"][sid]["seen"] == "2026-11-17T11:32:05Z"

    clock.now += 1
    run(store.touch(sid))
    assert stored(data)["sessions"][sid]["seen"] == "2026-11-17T12:32:05Z"


def test_the_requests_of_a_signed_in_browser_move_seen_once_an_hour(data, clock):
    client = client_of(make_app(data, clock))
    sign_in(client)
    clock.now += SEEN_STEP_SECONDS + 5

    assert is_signed_in(client)

    (record,) = stored(data)["sessions"].values()
    assert record["seen"] == "2026-11-17T12:32:10Z" and record["since"] == "2026-11-17T11:32:05Z"


def test_30_days_without_a_request_end_a_sign_in_and_it_is_dropped_at_the_next_write(data, clock):
    store = SignIns(login_file(data), clock)
    old = run(store.sign_in("x", None))
    clock.now += LIFE_SECONDS - 1
    assert store.live(old)

    clock.now += 1
    assert not store.live(old) and store.count == 0
    run(store.sign_in("y", None))
    assert old not in stored(data)["sessions"]


def test_a_browser_unused_for_30_days_is_a_stranger(data, clock):
    client = client_of(make_app(data, clock))
    sign_in(client)
    clock.now += LIFE_SECONDS  # the cookie's own signature is still fresh: only the store says no

    assert not is_signed_in(client)


def test_the_21st_sign_in_drops_the_one_used_least_recently(data, clock):
    store = SignIns(login_file(data), clock)
    sids = []
    for _ in range(MAX_SIGN_INS):
        sids.append(run(store.sign_in("x", None)))
        clock.now += 1
    clock.now += SEEN_STEP_SECONDS
    run(store.touch(sids[0]))  # the first one was used a moment ago: the second is the least recently used

    newest = run(store.sign_in("y", None))

    assert store.count == MAX_SIGN_INS and len(stored(data)["sessions"]) == MAX_SIGN_INS
    assert store.live(sids[0]) and not store.live(sids[1]) and store.live(newest)


def test_a_session_written_by_hand_does_not_work_without_a_cookie_signed_by_the_key(data, clock):
    client = client_of(make_app(data, clock))
    sign_in(client)
    document = stored(data)
    forged = "f" * 32
    document["sessions"][forged] = {"since": "2026-11-17T11:00:00Z", "seen": "2026-11-17T11:00:00Z", "device": "x"}
    login_file(data).write_text(json.dumps(document), encoding="utf-8")
    stranger = client_of(make_app(data, clock))
    key = itsdangerous.TimestampSigner("0" * 64)  # not the key of data/web_secret
    body = b64encode(json.dumps({"pw": "whatever", "sid": forged}).encode("utf-8"))
    stranger.cookies.set("tracker_session", key.sign(body).decode("utf-8"))

    assert not is_signed_in(stranger)


# ---- the middleware: who is a stranger ------------------------------------

def signed_cookie(data, session):
    """A cookie signed by the real key, as the middleware makes it."""
    key = (data / "web_secret").read_bytes()
    body = b64encode(json.dumps(session).encode("utf-8"))
    return itsdangerous.TimestampSigner(key.hex()).sign(body).decode("utf-8")


def test_an_old_cookie_without_a_sid_is_a_stranger_who_signs_in_once(data, clock):
    app = make_app(data, clock)
    client = client_of(app)
    key = (data / "web_secret").read_bytes()
    client.cookies.set("tracker_session", signed_cookie(data, {"pw": fingerprint(key, PASSWORD)}))  # before the update

    assert client.get("/").headers["location"] == "/login?next=/"
    sign_in(client)
    assert is_signed_in(client)


def test_a_cookie_whose_sid_is_not_in_the_file_is_a_stranger(data, clock):
    client = client_of(make_app(data, clock))
    key = (data / "web_secret").read_bytes()
    client.cookies.set("tracker_session", signed_cookie(data, {"pw": fingerprint(key, PASSWORD), "sid": "a" * 32}))

    assert not is_signed_in(client)


def test_a_cookie_with_a_wrong_fingerprint_is_a_stranger_even_with_a_live_sid(data, clock):
    client = client_of(make_app(data, clock))
    sign_in(client)
    (sid,) = stored(data)["sessions"]
    client.cookies.set("tracker_session", signed_cookie(data, {"pw": "0" * 32, "sid": sid}))

    assert not is_signed_in(client)


def test_the_cookie_carries_the_sid_of_the_file_and_the_fingerprint_only(data, clock):
    client = client_of(make_app(data, clock))
    sign_in(client)
    value = client.cookies["tracker_session"]
    key = (data / "web_secret").read_bytes()
    session = json.loads(b64decode(itsdangerous.TimestampSigner(key.hex()).unsign(value)))

    assert session == {"pw": fingerprint(key, PASSWORD), "sid": next(iter(stored(data)["sessions"]))}


def test_the_notice_of_a_page_survives_the_redirect(data, clock):
    app = make_app(data, clock)

    @app.post("/note")
    async def note(request: Request):
        pages.notify(request, "Сохранено")
        return RedirectResponse("/nowhere", status_code=303)

    client = client_of(app)
    sign_in(client)
    assert client.post("/note").headers["location"] == "/nowhere"

    page = client.get("/nowhere")
    assert "Сохранено" in page.text and "Сохранено" not in client.get("/nowhere").text  # once, then gone
    assert is_signed_in(client)  # the notice gone, the sign-in stays


# ---- login, «Выйти», «Выйти на всех устройствах» --------------------------

def test_the_login_makes_a_sign_in_in_the_file_and_replaces_the_last_login(data, clock):
    client = client_of(make_app(data, clock))

    sign_in(client)

    document = stored(data)
    (record,) = document["sessions"].values()
    assert record == {"since": "2026-11-17T11:32:05Z", "seen": "2026-11-17T11:32:05Z", "device": UNKNOWN_DEVICE}
    assert document["last_login"] == {"at": "2026-11-17T11:32:05Z", "device": UNKNOWN_DEVICE, "address": None}


def test_a_new_login_in_the_same_browser_ends_its_previous_sign_in(data, clock):
    client = client_of(make_app(data, clock))
    sign_in(client)
    sign_in(client)

    assert len(stored(data)["sessions"]) == 1


def test_the_sign_out_ends_only_its_own_sign_in_and_its_copied_cookie(data, clock):
    app = make_app(data, clock)
    phone, laptop = client_of(app), client_of(app)
    sign_in(phone)
    sign_in(laptop)
    copied = phone.cookies["tracker_session"]

    response = phone.post("/logout")

    assert response.status_code == 303 and response.headers["location"] == "/login"
    assert "tracker_session=null" in response.headers["set-cookie"]
    assert not is_signed_in(phone) and is_signed_in(laptop)
    thief = client_of(app)
    thief.cookies.set("tracker_session", copied)
    assert not is_signed_in(thief)  # KI-8: a copy taken before «Выйти» no longer works
    assert len(stored(data)["sessions"]) == 1


def test_sign_out_everywhere_ends_every_sign_in_and_keeps_the_last_login_and_the_lock(data, clock, caplog):
    app = make_app(data, clock)
    phone, laptop = client_of(app), client_of(app)
    sign_in(phone)
    sign_in(laptop)
    for _ in range(2):
        client_of(app).post("/login", data={"password": WRONG})
    before = stored(data)

    with caplog.at_level(logging.INFO):
        response = laptop.post("/settings/sign-out-everywhere")

    assert response.status_code == 303 and response.headers["location"] == "/login?out=everywhere"
    assert "tracker_session=null" in response.headers["set-cookie"]
    assert "web: signed out everywhere (2 sessions)" in caplog.text
    assert not is_signed_in(phone) and not is_signed_in(laptop)
    after = stored(data)
    assert after["sessions"] == {}
    assert after["last_login"] == before["last_login"] and after["guard"] == {"wrong": 2, "locked_until": None}


def test_after_sign_out_everywhere_an_htmx_request_of_another_tab_goes_to_the_login(data, clock):
    app = make_app(data, clock)
    tab, other = client_of(app), client_of(app)
    sign_in(tab)
    sign_in(other)
    other.post("/settings/sign-out-everywhere")

    response = tab.get("/status-line", headers={"HX-Request": "true"})

    assert response.status_code == 401 and response.headers["HX-Redirect"] == "/login"


def test_sign_out_everywhere_is_closed_to_a_stranger(data, clock):
    app = make_app(data, clock)
    signed = client_of(app)
    sign_in(signed)

    response = client_of(app).post("/settings/sign-out-everywhere")

    assert response.status_code == 303 and response.headers["location"] == "/login"
    assert is_signed_in(signed)


def test_the_login_page_says_so_only_after_sign_out_everywhere(data, clock):
    client = client_of(make_app(data, clock))

    assert SIGNED_OUT_EVERYWHERE in client.get("/login?out=everywhere").text
    for other in ("/login", "/login?out=all", "/login?out=Everywhere", "/login?out=everywhere%20"):
        assert SIGNED_OUT_EVERYWHERE not in client.get(other).text, other


# ---- the lock survives a restart (KI-7) -----------------------------------

def lock(client):
    for _ in range(5):
        client.post("/login", data={"password": WRONG})


def test_the_lock_survives_a_new_app_on_the_same_file(data, clock):
    lock(client_of(make_app(data, clock)))
    assert stored(data)["guard"] == {"wrong": 5, "locked_until": "2026-11-17T11:47:05Z"}

    restarted = client_of(make_app(data, clock))
    response = restarted.post("/login", data={"password": PASSWORD})

    assert response.status_code == 429 and response.headers["Retry-After"] == str(LOCK_SECONDS)
    assert "set-cookie" not in response.headers


def test_the_count_of_wrong_tries_survives_a_restart(data, clock):
    for _ in range(3):
        client_of(make_app(data, clock)).post("/login", data={"password": WRONG})

    response = client_of(make_app(data, clock)).post("/login", data={"password": WRONG})

    assert "осталось попыток: 1" in response.text


def test_the_lock_ends_on_the_wall_clock_after_a_restart(data, clock):
    lock(client_of(make_app(data, clock)))
    clock.now += LOCK_SECONDS

    restarted = client_of(make_app(data, clock))

    assert "осталось попыток: 4" in restarted.post("/login", data={"password": WRONG}).text  # the count starts anew
    sign_in(restarted)
    assert stored(data)["guard"] == {"wrong": 0, "locked_until": None}


def test_a_locked_try_does_not_extend_the_lock_across_a_restart(data, clock):
    lock(client_of(make_app(data, clock)))
    clock.now += 600
    client_of(make_app(data, clock)).post("/login", data={"password": PASSWORD})

    clock.now += LOCK_SECONDS - 600 - 1
    still = client_of(make_app(data, clock)).post("/login", data={"password": PASSWORD})
    clock.now += 1
    open_again = client_of(make_app(data, clock)).post("/login", data={"password": PASSWORD})

    assert still.status_code == 429 and still.headers["Retry-After"] == "1"
    assert open_again.status_code == 303
    assert stored(data)["guard"]["locked_until"] is None


def test_one_count_for_the_whole_app(data, clock):
    app = make_app(data, clock)
    for _ in range(4):
        client_of(app).post("/login", data={"password": WRONG})  # each try from a browser of its own

    assert client_of(app).post("/login", data={"password": WRONG}).status_code == 429


# ---- the key (KI-13) ------------------------------------------------------

def test_a_short_key_file_is_replaced_and_a_sign_in_survives_the_next_start(data, clock, caplog):
    data.mkdir()
    (data / "web_secret").write_bytes(b"")
    with caplog.at_level(logging.WARNING):
        first = client_of(make_app(data, clock))
    sign_in(first)
    assert "web_secret был испорчен и создан заново: на всех устройствах нужен новый вход" in caplog.text
    assert len((data / "web_secret").read_bytes()) == 32

    second = client_of(make_app(data, clock))  # the next start reads the new key
    second.cookies.set("tracker_session", first.cookies["tracker_session"])

    assert is_signed_in(second)


# ---- the block «Вход» -----------------------------------------------------

@pytest.mark.parametrize(("count", "line"), [
    (1, "Вход открыт на 1 устройстве."),
    (2, "Вход открыт на 2 устройствах."),
    (5, "Вход открыт на 5 устройствах."),
    (11, "Вход открыт на 11 устройствах."),
    (21, "Вход открыт на 21 устройстве."),
    (111, "Вход открыт на 111 устройствах."),
    (101, "Вход открыт на 101 устройстве."),
])
def test_the_devices_line_has_the_plural(count, line):
    assert devices_line(count) == line


def test_the_last_login_line_with_and_without_an_address():
    login = LastLogin(0, "Android, Chrome", None)

    assert last_login_line(None, "") == NO_LAST_LOGIN == "Последний вход: сведений нет."
    assert last_login_line(login, "сегодня в 14:32") == "Последний вход: сегодня в 14:32, Android, Chrome."
    assert last_login_line(LastLogin(0, "Android, Chrome", "203.0.113.5"), "вчера в 09:00") == (
        "Последний вход: вчера в 09:00, Android, Chrome, адрес 203.0.113.5.")


@pytest.fixture
def tracker():
    return Tracker(create_session_factory("sqlite://"), clock=lambda: NOW, sender=FakeSender(), sources={}, default_tz=MOSCOW)


def test_the_block_at_the_bottom_of_settings_on_the_owners_clock(data, clock, tracker):
    app = make_app(data, clock, tracker=tracker)
    client, other = client_of(app), client_of(app)
    sign_in(client)

    html = client.get("/settings").text

    assert html.index("Копии и выгрузка") < html.index("<h2>Вход</h2>")
    assert "Последний вход: сегодня в 14:32, неизвестное устройство." in html
    assert "Вход открыт на 1 устройстве." in html
    assert 'action="/settings/sign-out-everywhere"' in html and "Выйти на всех устройствах</button>" in html
    assert HINT in html
    sign_in(other)
    assert "Вход открыт на 2 устройствах." in client.get("/settings").text
