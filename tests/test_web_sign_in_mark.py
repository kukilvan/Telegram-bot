"""The mark of `data/web_login.json` (ticket 05 of stage 9.1c, spec 7, KI-75): a change of `WEB_PASSWORD` or of
`data/web_secret` ends the sign-ins at start, so the block «Вход» counts only the sign-ins that still work.

Every row of the table of spec 7 is a test; the mark is neither the password nor the fingerprint of the cookie."""

import asyncio
import json
import logging
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.web import create_web_app
from app.web.auth import fingerprint, login_mark
from app.web.sessions import SignIns

PASSWORD = "correct horse battery"
OTHER = "another horse battery"
NOW = datetime(2026, 11, 22, 11, 32, 5, tzinfo=timezone.utc)
KEY = b"k" * 32
MARK = login_mark(KEY, PASSWORD)
OTHER_MARK = login_mark(KEY, OTHER)
SID = "a" * 32
MOMENT = "2026-11-20T10:00:00Z"
CHANGED = "WEB_PASSWORD или data/web_secret сменились: закрыто старых входов — {count}"


class Clock:
    def __init__(self) -> None:
        self.now = NOW.timestamp()

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def file(tmp_path):
    return tmp_path / "web_login.json"


def write(file, *, mark=None, sessions=1, wrong=2, last=True):
    document = {
        "version": 1,
        "sessions": {
            str(n) * 32: {"since": MOMENT, "seen": MOMENT, "device": f"Windows, Edge {n}"} for n in range(1, sessions + 1)
        },
        "last_login": {"at": MOMENT, "device": "Windows, Edge", "address": None} if last else None,
        "guard": {"wrong": wrong, "locked_until": None},
    }
    if mark is not None:
        document["mark"] = mark
    file.write_text(json.dumps(document), encoding="utf-8")


def stored(file):
    return json.loads(file.read_text(encoding="utf-8"))


# ---- the mark ----------------------------------------------------------------------------------------------------

def test_the_mark_is_64_hex_characters_and_changes_with_either_input():
    assert len(MARK) == 64 and set(MARK) <= set("0123456789abcdef")
    assert login_mark(KEY, PASSWORD) == MARK
    assert login_mark(KEY, OTHER) != MARK  # the password
    assert login_mark(b"z" * 32, PASSWORD) != MARK  # the key


def test_the_mark_is_neither_the_password_nor_the_fingerprint_of_the_cookie():
    assert PASSWORD not in MARK and MARK != fingerprint(KEY, PASSWORD) and not MARK.startswith(fingerprint(KEY, PASSWORD))


# ---- the table of spec 7 -------------------------------------------------------------------------------------------

def test_a_file_without_a_mark_keeps_its_sign_ins_and_gets_the_mark_at_once(file, clock, caplog):
    write(file)  # a file of stage 7.2

    with caplog.at_level(logging.WARNING):
        store = SignIns(file, clock, MARK)

    assert store.count == 1 and store.last_login is not None and store.guard.state[0] == 2
    assert stored(file)["mark"] == MARK and len(stored(file)["sessions"]) == 1
    assert CHANGED.format(count=1) not in caplog.text and caplog.text == ""


def test_the_same_mark_changes_nothing(file, clock, caplog):
    write(file, mark=MARK)
    before = file.stat().st_mtime_ns

    with caplog.at_level(logging.WARNING):
        store = SignIns(file, clock, MARK)

    assert store.count == 1 and caplog.text == "" and file.stat().st_mtime_ns == before  # not even written


def test_another_mark_drops_every_sign_in_but_keeps_the_last_login_and_the_lock_count(file, clock, caplog):
    write(file, mark=MARK, sessions=3, wrong=4)

    with caplog.at_level(logging.WARNING):
        store = SignIns(file, clock, OTHER_MARK)

    assert CHANGED.format(count=3) in caplog.text
    assert store.count == 0 and store.last_login is not None and store.guard.state == (4, None)
    document = stored(file)  # written at once
    assert document["mark"] == OTHER_MARK and document["sessions"] == {}
    assert document["last_login"]["device"] == "Windows, Edge" and document["guard"]["wrong"] == 4


@pytest.mark.parametrize("mark", ["abc", "G" * 64, "A" * 64, "a" * 63, "a" * 65, "", None, 5, ["a" * 64]])
def test_a_mark_that_is_not_64_hex_characters_spoils_the_file(file, clock, caplog, mark):
    write(file)
    document = stored(file)
    document["mark"] = mark
    file.write_text(json.dumps(document), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        store = SignIns(file, clock, MARK)

    assert "испорчен" in caplog.text
    assert store.count == 0 and store.last_login is None and store.guard.state == (0, None)


def test_no_file_is_empty_and_the_mark_goes_into_the_first_write(file, clock):
    store = SignIns(file, clock, MARK)
    assert not file.exists() and store.count == 0

    asyncio.run(store.sign_in("Windows, Edge", None))

    assert stored(file)["mark"] == MARK and len(stored(file)["sessions"]) == 1


def test_a_spoiled_file_is_empty_and_the_mark_goes_into_the_next_write(file, clock):
    file.write_text("not json", encoding="utf-8")

    store = SignIns(file, clock, MARK)
    asyncio.run(store.sign_in("Windows, Edge", None))

    assert stored(file)["mark"] == MARK


def test_a_file_that_cannot_be_written_at_start_keeps_the_state_in_memory(tmp_path, clock, caplog):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder", encoding="utf-8")
    file = blocker / "web_login.json"  # nothing can be read or written there

    with caplog.at_level(logging.WARNING):
        store = SignIns(file, clock, MARK)

    assert store.count == 0  # in memory, no crash


def test_without_a_mark_the_file_is_as_before(file, clock):
    write(file, mark=OTHER_MARK)

    store = SignIns(file, clock)  # the password is not configured: no mark is kept or checked

    assert store.count == 1
    asyncio.run(store.sign_in("x", None))
    assert "mark" not in stored(file)


def test_the_file_with_a_mark_keeps_the_keys_and_the_version_an_older_app_reads(file, clock):
    write(file)
    SignIns(file, clock, MARK)

    document = stored(file)

    assert document["version"] == 1 and {"sessions", "last_login", "guard", "mark"} == set(document) - {"version"}


# ---- the app: the block «Вход» and the cookie --------------------------------------------------------------------

class Sender:
    async def send(self, message, actions=()):
        pass


def make_app(tmp_path, clock, password):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    return create_web_app(
        health=health.report, password=password, secret_file=tmp_path / "web_secret", login_file=tmp_path / "web_login.json",
        clock=clock, tracker=Tracker(create_session_factory("sqlite://"), clock=lambda: NOW, sender=Sender(), sources={}),
        now=lambda: datetime.fromtimestamp(clock(), timezone.utc),
    )


def sign_in(app, password):
    client = TestClient(app, follow_redirects=False)
    assert client.post("/login", data={"password": password}).status_code == 303
    return client


def test_after_a_change_of_the_password_the_block_counts_only_the_new_sign_in(tmp_path, clock):
    sign_in(make_app(tmp_path, clock, PASSWORD), PASSWORD)
    other_browser = sign_in(make_app(tmp_path, clock, PASSWORD), PASSWORD)
    assert len(json.loads((tmp_path / "web_login.json").read_text(encoding="utf-8"))["sessions"]) == 2
    assert "Вход открыт на 2 устройствах." in other_browser.get("/settings").text

    app = make_app(tmp_path, clock, OTHER)  # WEB_PASSWORD changed, `.\start-bot.ps1`
    assert json.loads((tmp_path / "web_login.json").read_text(encoding="utf-8"))["sessions"] == {}
    new = sign_in(app, OTHER)

    assert "Вход открыт на 1 устройстве." in new.get("/settings").text


def test_the_same_password_and_key_again_drop_nothing(tmp_path, clock):
    sign_in(make_app(tmp_path, clock, PASSWORD), PASSWORD)

    make_app(tmp_path, clock, OTHER)  # changed ...
    make_app(tmp_path, clock, PASSWORD)  # ... and changed back: the first change dropped what it dropped, nothing more
    client = sign_in(make_app(tmp_path, clock, PASSWORD), PASSWORD)
    again = make_app(tmp_path, clock, PASSWORD)

    assert len(json.loads((tmp_path / "web_login.json").read_text(encoding="utf-8"))["sessions"]) == 1
    assert client.get("/nowhere").status_code == 404 and again is not None


def test_a_deleted_web_secret_makes_a_new_key_and_drops_every_sign_in(tmp_path, clock):
    sign_in(make_app(tmp_path, clock, PASSWORD), PASSWORD)
    (tmp_path / "web_secret").unlink()

    make_app(tmp_path, clock, PASSWORD)

    document = json.loads((tmp_path / "web_login.json").read_text(encoding="utf-8"))
    assert document["sessions"] == {} and document["mark"] != MARK


def test_the_file_never_holds_the_password(tmp_path, clock):
    sign_in(make_app(tmp_path, clock, PASSWORD), PASSWORD)

    assert PASSWORD not in (tmp_path / "web_login.json").read_text(encoding="utf-8")


def test_the_cap_of_20_holds_only_the_live_sign_ins(tmp_path, clock):
    app = make_app(tmp_path, clock, PASSWORD)
    for _ in range(3):
        sign_in(app, PASSWORD)

    app = make_app(tmp_path, clock, OTHER)  # the three are gone
    for _ in range(20):
        sign_in(app, OTHER)

    assert len(json.loads((tmp_path / "web_login.json").read_text(encoding="utf-8"))["sessions"]) == 20
