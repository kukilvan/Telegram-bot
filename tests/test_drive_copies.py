"""The sending of the Google Drive copy (stage 7.1, ticket 04; spec 4.3–4.7 and 2.2): the archive, every step of the
sending against a fake Google Drive (`httpx.MockTransport`), the reasons of a failure, the report, the hourly job, the
press «Сделать копию сейчас» and the lines of Settings — on the real core with a file database in a temporary folder."""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
import py7zr
import pytest
from sqlalchemy import select

from app.providers.google_drive import GoogleDriveApi
from app.tracker import backup_events, drive_copies, drive_rows
from app.tracker.core import DriveButton, DriveSettings, Tracker
from app.tracker.db import create_session_factory
from app.tracker.drive_state import DriveState, state_of
from app.tracker.google_drive import DriveFiles, DriveToken
from app.tracker.models import Event
from app.utils import backup
from app.utils.archive import archive_name, make_archive

MOSCOW = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)  # Sunday 12:00 in Moscow
WALL = datetime(2026, 11, 8, 12, 0, 5)  # the container's clock at that moment
CLIENT_ID = "1234-abcd.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-fake-client-secret-value"
PASSWORD = "Тест-пароль копий 123"
REFRESH = "1//0g-fake-refresh-token-value-abcdefghijklmnop"
DRIVE = DriveSettings(CLIENT_ID, CLIENT_SECRET, PASSWORD, 8080)
HERE = "localhost:8080"
UPLOAD_ADDRESS = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=fake-session"
FOLDER = "Трекер — копии"
SENT = "Копия сделана и отправлена в Google Drive."


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeDrive:
    """Google's token address and the Drive API in memory. `answers[step]` is a list of answers given before the normal
    one, popped in order: an `(status, body)` pair or an exception to raise. Steps: token, alive, find, list, create,
    start, put, delete."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.answers: dict[str, list] = {}
        self.folders: dict[str, dict] = {}  # id → {"name", "trashed"}
        self.files: dict[str, dict] = {}  # id → {"name", "size", "parent", "content"}
        self.refreshes = 0
        self.dead_tokens: set[str] = set()  # access tokens that Google answers 401 to
        self._next = 0

    def new_id(self, prefix: str) -> str:
        self._next += 1
        return f"{prefix}{self._next}"

    def put_file(self, name: str, size: int = 100, parent: str | None = None) -> str:
        file_id = self.new_id("file-")
        self.files[file_id] = {"name": name, "size": size, "parent": parent, "content": b""}
        return file_id

    def put_folder(self, name: str = FOLDER, trashed: bool = False) -> str:
        folder_id = self.new_id("folder-")
        self.folders[folder_id] = {"name": name, "trashed": trashed}
        return folder_id

    def names_in(self, folder_id: str) -> list[str]:
        return sorted(file["name"] for file in self.files.values() if file["parent"] == folder_id)

    def steps(self) -> list[str]:
        return [self.step_of(request) for request in self.requests]

    @staticmethod
    def step_of(request: httpx.Request) -> str:
        path, method = request.url.path, request.method
        if request.url.host == "oauth2.googleapis.com":
            return "token"
        if path.startswith("/upload/"):
            return "start" if method == "POST" else "put"
        if method == "DELETE":
            return "delete"
        if method == "POST":
            return "create"
        if path == "/drive/v3/files":
            return "find" if "mimeType" in request.url.params.get("q", "") else "list"
        return "alive"

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.step_of(request)
        waiting = self.answers.get(step)
        if waiting:
            answer = waiting.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            if callable(answer):
                return await answer(request)
            status, body = answer
            return httpx.Response(status, json=body)
        if step == "token":
            self.refreshes += 1
            return httpx.Response(200, json={"access_token": f"ya29.access-{self.refreshes}", "expires_in": 3599})
        if request.headers.get("authorization", "").removeprefix("Bearer ") in self.dead_tokens:
            return httpx.Response(401, json={"error": {"code": 401, "status": "UNAUTHENTICATED", "errors": []}})
        return getattr(self, f"_{step}")(request)

    def _alive(self, request):
        folder = self.folders.get(request.url.path.rsplit("/", 1)[-1])
        if folder is None:
            return httpx.Response(404, json={"error": {"code": 404, "errors": [{"reason": "notFound"}]}})
        return httpx.Response(200, json={"id": request.url.path.rsplit("/", 1)[-1], "trashed": folder["trashed"]})

    def _find(self, request):
        name = re.search(r"name='(.*?)'", request.url.params["q"]).group(1)
        found = [{"id": i, "name": f["name"]} for i, f in self.folders.items() if f["name"] == name and not f["trashed"]]
        return httpx.Response(200, json={"files": found})

    def _list(self, request):
        parent = re.search(r"'(.*?)' in parents", request.url.params["q"]).group(1)
        found = [
            {"id": i, "name": f["name"], "size": str(f["size"]), "createdTime": "2026-11-08T09:00:00Z"}
            for i, f in self.files.items() if f["parent"] == parent
        ]
        return httpx.Response(200, json={"files": found})

    def _create(self, request):
        body = json.loads(request.content)
        assert body["mimeType"] == "application/vnd.google-apps.folder"
        folder_id = self.put_folder(body["name"])
        return httpx.Response(200, json={"id": folder_id, "name": body["name"]})

    def _start(self, request):
        self.metadata = json.loads(request.content)
        return httpx.Response(200, headers={"Location": UPLOAD_ADDRESS})

    def _put(self, request):
        file_id = self.put_file(self.metadata["name"], len(request.content), self.metadata["parents"][0])
        self.files[file_id]["content"] = request.content
        return httpx.Response(200, json={"id": file_id, "name": self.metadata["name"], "size": str(len(request.content))})

    def _delete(self, request):
        self.files.pop(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(204)


@pytest.fixture
def google():
    return FakeDrive()


@pytest.fixture
def clock():
    return Clock()


def make_tracker(tmp_path, google, clock, drive=DRIVE) -> Tracker:
    url = f"sqlite:///{(tmp_path / 'tracker.db').as_posix()}"
    api = GoogleDriveApi(drive.client_id, drive.client_secret, transport=httpx.MockTransport(google.handle))
    core = Tracker(
        create_session_factory(url), clock=clock, sender=FakeSender(), default_tz=MOSCOW, database_url=url,
        drive_settings=drive, drive_api=api,
    )
    core._backups.wall_clock = lambda: WALL
    return core


@pytest.fixture
def tracker(tmp_path, google, clock):
    return make_tracker(tmp_path, google, clock)


def connect(tmp_path, folder_id: str | None = None, at: datetime = datetime(2026, 11, 8, 8, 0)) -> None:
    DriveFiles(tmp_path).write_token(DriveToken(REFRESH, at, folder_id))


def copy_on_pc(tmp_path, moment: datetime = datetime(2026, 11, 8, 11, 30), suffix: str = "") -> Path:
    folder = tmp_path / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"tracker_db_{moment:%Y%m%d_%H%M%S}{'_' + suffix if suffix else ''}.db"
    path.write_bytes(b"SQLite format 3\x00" + bytes(range(256)) * 40)
    return path


def state(tmp_path) -> DriveState | None:
    return DriveFiles(tmp_path).state()


def token(tmp_path) -> DriveToken | None:
    return DriveFiles(tmp_path).token()


def events(tracker):
    with tracker.session_factory() as session:
        return list(session.scalars(select(Event).where(Event.type == backup_events.BACKUP_FAILED).order_by(Event.id)))


def send(tracker) -> str | None:
    """One attempt with the newest copy, as the hourly job would make it."""
    async def scenario():
        copies = tracker._backups.copies
        return await copies.send(await asyncio.to_thread(copies.newest))
    return run(scenario())


# ---- the archive -------------------------------------------------------------------------------


def test_the_archive_opens_by_its_cyrillic_password_and_holds_the_copy_under_its_name(tmp_path):
    copy = copy_on_pc(tmp_path, suffix="manual")
    archive = make_archive(copy, tmp_path / "upload" / archive_name(copy), PASSWORD)

    assert archive.name == "tracker_db_20261108_113000_manual.7z"
    with py7zr.SevenZipFile(archive, "r", password=PASSWORD) as opened:
        assert opened.getnames() == [copy.name]
        opened.extractall(tmp_path / "out")
    assert (tmp_path / "out" / copy.name).read_bytes() == copy.read_bytes()


def test_the_archive_hides_its_names_without_the_password(tmp_path):
    copy = copy_on_pc(tmp_path)
    archive = make_archive(copy, tmp_path / "a.7z", PASSWORD)

    with pytest.raises(py7zr.exceptions.PasswordRequired):
        with py7zr.SevenZipFile(archive, "r") as opened:
            opened.getnames()


def test_a_failed_archive_leaves_no_half_made_file(tmp_path):
    with pytest.raises(OSError):
        make_archive(tmp_path / "missing.db", tmp_path / "a.7z", PASSWORD)

    assert not (tmp_path / "a.7z").exists()


@pytest.mark.parametrize("fail", [False, True])
def test_the_archive_is_deleted_after_the_attempt_sent_or_not(tracker, tmp_path, google, fail):
    connect(tmp_path)
    copy_on_pc(tmp_path)
    if fail:
        google.answers["put"] = [(500, {})]

    send(tracker)

    assert list((tmp_path / "backups" / "upload").iterdir()) == []


# ---- a copy goes end to end ---------------------------------------------------------------------


def test_the_first_copy_makes_the_folder_sends_the_archive_and_writes_the_state(tracker, tmp_path, google):
    connect(tmp_path)
    copy = copy_on_pc(tmp_path, suffix="manual")

    assert send(tracker) is None

    [folder_id] = google.folders
    assert google.folders[folder_id]["name"] == FOLDER
    assert google.names_in(folder_id) == ["tracker_db_20261108_113000_manual.7z"]
    assert token(tmp_path).folder_id == folder_id and token(tmp_path).refresh_token == REFRESH
    assert state(tmp_path) == DriveState(
        datetime(2026, 11, 8, 9, 0), datetime(2026, 11, 8, 9, 0), copy.name, 1, None, 0
    )
    assert google.steps() == ["token", "find", "create", "list", "start", "put"]


def test_the_archive_in_drive_opens_by_the_password(tracker, tmp_path, google):
    connect(tmp_path)
    copy = copy_on_pc(tmp_path)
    send(tracker)

    [file] = google.files.values()
    (tmp_path / "got.7z").write_bytes(file["content"])
    with py7zr.SevenZipFile(tmp_path / "got.7z", "r", password=PASSWORD) as opened:
        opened.extractall(tmp_path / "out")
    assert (tmp_path / "out" / copy.name).read_bytes() == copy.read_bytes()


def test_the_requests_carry_what_the_spec_says(tracker, tmp_path, google):
    connect(tmp_path)
    copy_on_pc(tmp_path)
    send(tracker)

    token_form = parse_qs(google.requests[0].content.decode())
    assert token_form["grant_type"] == ["refresh_token"] and token_form["refresh_token"] == [REFRESH]
    start = next(r for r in google.requests if google.step_of(r) == "start")
    assert start.url.params["uploadType"] == "resumable"
    assert json.loads(start.content)["parents"] == [next(iter(google.folders))]
    put = next(r for r in google.requests if google.step_of(r) == "put")
    assert str(put.url) == UPLOAD_ADDRESS and put.headers["content-type"] == "application/x-7z-compressed"
    for request in google.requests[1:]:
        assert request.headers["authorization"] == "Bearer ya29.access-1"
        assert "access-1" not in str(request.url)


def test_a_folder_of_the_app_is_found_by_its_name(tracker, tmp_path, google):
    folder_id = google.put_folder()
    connect(tmp_path)
    copy_on_pc(tmp_path)

    send(tracker)

    assert list(google.folders) == [folder_id] and token(tmp_path).folder_id == folder_id
    assert "create" not in google.steps()


def test_the_folder_of_the_token_file_is_used_while_it_is_there(tracker, tmp_path, google):
    folder_id = google.put_folder()
    connect(tmp_path, folder_id)
    copy_on_pc(tmp_path)

    send(tracker)

    assert google.steps() == ["token", "alive", "list", "start", "put"]
    assert len(google.names_in(folder_id)) == 1


@pytest.mark.parametrize("trashed", [False, True])
def test_a_deleted_folder_is_made_anew(tracker, tmp_path, google, trashed):
    old = google.put_folder(trashed=True) if trashed else "folder-gone"
    connect(tmp_path, old)
    copy_on_pc(tmp_path)

    assert send(tracker) is None

    [new] = [i for i, f in google.folders.items() if not f["trashed"]]
    assert new != old and token(tmp_path).folder_id == new and len(google.names_in(new)) == 1


def test_a_file_of_the_same_name_and_size_counts_as_sent(tracker, tmp_path, google):
    folder_id = google.put_folder()
    connect(tmp_path, folder_id)
    copy = copy_on_pc(tmp_path)
    size = make_archive(copy, tmp_path / "probe.7z", PASSWORD).stat().st_size
    google.put_file(archive_name(copy), size, folder_id)

    assert send(tracker) is None

    assert "start" not in google.steps() and google.names_in(folder_id) == [archive_name(copy)]
    assert state(tmp_path).last_success_name == copy.name and state(tmp_path).kept == 1


def test_a_file_of_the_same_name_but_another_size_is_sent_again(tracker, tmp_path, google):
    folder_id = google.put_folder()
    connect(tmp_path, folder_id)
    copy = copy_on_pc(tmp_path)
    google.put_file(archive_name(copy), 3, folder_id)

    send(tracker)

    assert "put" in google.steps()


# ---- the rotation -------------------------------------------------------------------------------


def stamped(day: int, hour: int = 4, suffix: str = "") -> str:
    return f"tracker_db_202610{day:02d}_{hour:02d}0000{suffix}.7z"


def test_the_rotation_keeps_the_30_newest_of_its_own_names_only(tracker, tmp_path, google):
    folder_id = google.put_folder()
    connect(tmp_path, folder_id)
    for day in range(1, 31):  # 30 old ones, the manual ones among them
        google.put_file(stamped(day, suffix="_manual" if day % 7 == 0 else ""), parent=folder_id)
    others = ["notes.txt", "tracker_db_20261001_040000.7z.bak", "tracker_db_20261399_000000.7z", "фото.jpg"]
    for name in others:
        google.put_file(name, parent=folder_id)
    copy_on_pc(tmp_path)

    send(tracker)

    names = google.names_in(folder_id)
    assert stamped(1) not in names and stamped(2) in names
    assert set(others) <= set(names) and len(names) == 30 + len(others)
    assert state(tmp_path).kept == 30


def test_a_failed_delete_is_a_warning_and_the_copy_counts_as_sent(tracker, tmp_path, google, caplog):
    folder_id = google.put_folder()
    connect(tmp_path, folder_id)
    for day in range(1, 31):  # with the new one, one too many
        google.put_file(stamped(day), parent=folder_id)
    google.answers["delete"] = [(500, {})]
    copy_on_pc(tmp_path)

    with caplog.at_level(logging.WARNING):
        assert send(tracker) is None

    assert "was not deleted: tracker_db_20261001_040000.7z" in caplog.text
    assert state(tmp_path).error is None and state(tmp_path).kept == 31


# ---- the access token -----------------------------------------------------------------------


def test_a_401_renews_the_access_token_once_and_repeats_the_request(tracker, tmp_path, google):
    connect(tmp_path)
    copy_on_pc(tmp_path)
    google.dead_tokens.add("ya29.access-1")

    assert send(tracker) is None

    assert google.steps()[:3] == ["token", "find", "token"] and google.refreshes == 2


def test_a_401_after_a_new_access_token_is_the_refused_sign_in(tracker, tmp_path, google):
    connect(tmp_path)
    copy_on_pc(tmp_path)
    google.dead_tokens.update({"ya29.access-1", "ya29.access-2"})

    assert send(tracker) == backup_events.SIGN_IN
    assert google.steps() == ["token", "find", "token", "find"]


def test_the_access_token_is_kept_until_a_minute_before_it_ends(tracker, tmp_path, google, clock):
    connect(tmp_path)
    copy_on_pc(tmp_path)
    send(tracker)
    copy_on_pc(tmp_path, datetime(2026, 11, 8, 11, 40))
    send(tracker)
    assert google.refreshes == 1

    clock.now = NOW + timedelta(seconds=3599 - 59)
    copy_on_pc(tmp_path, datetime(2026, 11, 8, 11, 50))
    send(tracker)
    assert google.refreshes == 2


# ---- the reasons ---------------------------------------------------------------------------------


def drive_error(status: int, reason: str) -> tuple[int, dict]:
    return status, {"error": {"code": status, "message": "…", "errors": [{"domain": "usageLimits", "reason": reason}]}}


@pytest.mark.parametrize("step, answer, reason", [
    ("token", (400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}), "sign_in"),
    ("put", drive_error(403, "storageQuotaExceeded"), "full"),
    ("put", (500, {"error": {"code": 500, "errors": [{"reason": "backendError"}]}}), "down"),
    ("put", (503, {}), "down"),
    ("list", (429, {}), "down"),
    ("start", drive_error(403, "rateLimitExceeded"), "down"),
    ("start", drive_error(403, "userRateLimitExceeded"), "down"),
    ("find", httpx.ConnectError("[Errno -3] Temporary failure in name resolution"), "connection"),
    ("put", httpx.ReadTimeout("timed out"), "connection"),
    ("token", (400, {"error": "invalid_client"}), "unknown"),
    ("put", drive_error(403, "insufficientFilePermissions"), "unknown"),
    ("put", (200, {"no": "id"}), "unknown"),
])
def test_each_reason_comes_from_its_answer(tracker, tmp_path, google, step, answer, reason):
    connect(tmp_path)
    copy_on_pc(tmp_path)
    google.answers[step] = [answer]

    assert send(tracker) == reason
    assert state(tmp_path).error == reason


def test_no_copy_on_the_pc_is_its_own_reason(tracker, tmp_path, google):
    connect(tmp_path)

    assert send(tracker) == backup_events.NO_COPY
    assert google.requests == []


def test_a_copy_before_an_update_is_not_sent(tracker, tmp_path):
    copy_on_pc(tmp_path, datetime(2026, 11, 8, 11, 0))
    copy_on_pc(tmp_path, datetime(2026, 11, 8, 11, 59), suffix="before-0014")

    assert tracker._backups.copies.newest().path.name == "tracker_db_20261108_110000.db"


def test_a_failed_archive_is_unknown(tracker, tmp_path, monkeypatch):
    connect(tmp_path)
    copy_on_pc(tmp_path)

    def broken(*args):
        raise RuntimeError("py7zr broke")

    monkeypatch.setattr(drive_copies, "make_archive", broken)
    assert send(tracker) == backup_events.UNKNOWN


def test_the_token_file_gone_is_the_refused_sign_in(tracker, tmp_path):
    copy_on_pc(tmp_path)

    assert send(tracker) == backup_events.SIGN_IN


def test_an_attempt_over_five_minutes_is_cut_as_no_connection(tracker, tmp_path, google, monkeypatch):
    connect(tmp_path)
    copy_on_pc(tmp_path)
    monkeypatch.setattr(drive_copies, "ATTEMPT_SECONDS", 0.05)

    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json={"files": []})

    google.answers["find"] = [slow]
    assert send(tracker) == backup_events.CONNECTION
    assert list((tmp_path / "backups" / "upload").iterdir()) == []


# ---- the state and the report -------------------------------------------------------------------


def test_failures_count_in_a_row_and_a_success_clears_them(tracker, tmp_path, google, clock):
    connect(tmp_path)
    copy_on_pc(tmp_path)
    google.answers["find"] = [httpx.ConnectError("down"), httpx.ConnectError("down")]

    send(tracker)
    clock.now = NOW + timedelta(hours=1)
    send(tracker)
    assert state(tmp_path) == DriveState(datetime(2026, 11, 8, 10, 0), None, None, 0, "connection", 2)

    clock.now = NOW + timedelta(hours=2)
    send(tracker)
    assert state(tmp_path).error is None and state(tmp_path).failures_in_row == 0
    assert state(tmp_path).last_success_at == datetime(2026, 11, 8, 11, 0)


def test_a_failure_keeps_the_last_success(tracker, tmp_path, google, clock):
    connect(tmp_path)
    copy = copy_on_pc(tmp_path)
    send(tracker)
    google.answers["list"] = [(503, {})]
    clock.now = NOW + timedelta(hours=1)

    send(tracker)

    assert state(tmp_path) == DriveState(
        datetime(2026, 11, 8, 10, 0), datetime(2026, 11, 8, 9, 0), copy.name, 1, "down", 1
    )


@pytest.mark.parametrize("reason_answer, at_once", [
    (httpx.ConnectError("down"), False),
    ((503, {}), False),
    ((400, {"error": "invalid_client"}), False),
    ((400, {"error": "invalid_grant"}), True),
    (drive_error(403, "storageQuotaExceeded"), True),
])
def test_a_reason_is_reported_at_once_or_at_the_second_failure_in_a_row(tracker, tmp_path, google, clock, reason_answer, at_once):
    connect(tmp_path)
    copy_on_pc(tmp_path)
    step = "token" if isinstance(reason_answer, tuple) and "invalid" in str(reason_answer) else "put"
    google.answers[step] = [reason_answer, reason_answer]

    send(tracker)
    assert len(events(tracker)) == (1 if at_once else 0)

    clock.now = NOW + timedelta(hours=1)
    send(tracker)
    assert len(events(tracker)) == 1


def test_no_copy_is_reported_at_once(tracker, tmp_path):
    connect(tmp_path)

    send(tracker)

    [event] = events(tracker)
    assert event.payload["text"] == (
        "⚠️ Копия в Google Drive не ушла: на этом ПК нет копии базы. Удачных копий там ещё не было. Попробую снова через час."
    )


def test_one_report_of_the_kind_a_day_on_the_owners_date(tracker, tmp_path, google, clock):
    connect(tmp_path)
    copy_on_pc(tmp_path)
    google.answers["put"] = [drive_error(403, "storageQuotaExceeded")] * 3

    send(tracker)
    clock.now = NOW + timedelta(hours=5)
    send(tracker)
    clock.now = datetime(2026, 11, 8, 21, 30, tzinfo=timezone.utc)  # 00:30 on the 9th in Moscow
    send(tracker)

    assert [e.dedup_key for e in events(tracker)] == ["backup_failed:drive:2026-11-08", "backup_failed:drive:2026-11-09"]
    assert all(e.title_id is None for e in events(tracker))


def test_the_report_names_the_last_success_in_words(tracker, tmp_path, google, clock):
    connect(tmp_path)
    copy_on_pc(tmp_path)
    send(tracker)  # 12:00 in Moscow
    google.answers["put"] = [drive_error(403, "storageQuotaExceeded")]
    copy_on_pc(tmp_path, datetime(2026, 11, 9, 4, 0))
    clock.now = NOW + timedelta(days=1)

    send(tracker)

    [event] = events(tracker)
    assert event.payload["text"] == (
        "⚠️ Копия в Google Drive не ушла: в Google Drive нет места. Последняя удачная — вчера в 12:00. Попробую снова "
        "через час."
    )


def test_the_report_of_a_refused_sign_in_promises_no_retry(tracker, tmp_path, google):
    connect(tmp_path)
    copy_on_pc(tmp_path)
    google.answers["token"] = [(400, {"error": "invalid_grant"})]

    send(tracker)

    [event] = events(tracker)
    assert event.payload["text"] == (
        "⚠️ Копия в Google Drive не ушла: Google Drive не принял вход — подключите его заново в Настройках. Удачных "
        "копий там ещё не было."
    )


def test_the_sample_of_the_report_is_in_the_test_event_list(tracker):
    sample = next(s for s in tracker.test_samples() if s.id == "backup-failed-drive")

    assert sample.label == "Копия в Google Drive не ушла"


@pytest.mark.parametrize("content", [
    '{"kept": "many"}', '{"failures_in_row": -1}', '{"last_attempt_at": "yesterday"}', '{"error": 5}',
    '{"last_success_at": "2026-11-08T09:00:00+00:00"}', '{"kept": true}',
])
def test_a_spoiled_state_reads_as_no_attempts_with_a_warning(tmp_path, caplog, content):
    (tmp_path / "google_drive_state.json").write_text(content, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert state(tmp_path) is None

    assert "google_drive_state.json" in caplog.text


def test_the_state_is_written_as_it_reads_back(tmp_path):
    written = DriveState(datetime(2026, 11, 8, 10, 0), datetime(2026, 11, 8, 9, 0), "tracker_db_x.db", 3, "down", 1)

    DriveFiles(tmp_path).write_state(written)

    assert state(tmp_path) == written and state_of(written.to_json()) == written


def test_no_secret_reaches_the_log(tracker, tmp_path, google, caplog):
    connect(tmp_path)
    copy_on_pc(tmp_path)
    google.dead_tokens.add("ya29.access-1")
    google.answers["put"] = [(500, {"error": {"code": 500, "message": "access_token ya29.access-2"}})]

    with caplog.at_level(logging.DEBUG):
        send(tracker)
        send(tracker)

    for secret in (REFRESH, CLIENT_SECRET, PASSWORD, "ya29.access-1", "ya29.access-2", "ya29.access-3"):
        assert secret not in caplog.text


# ---- when copies go: the hourly job and the sign-in --------------------------------------------


def test_the_hourly_job_sends_the_new_daily_copy_in_the_same_run(tracker, tmp_path, google):
    connect(tmp_path)

    run(tracker.backup_database())

    [daily] = backup.daily_backups(tmp_path / "backups")
    [folder_id] = google.folders
    assert google.names_in(folder_id) == [archive_name(daily[1])]
    assert state(tmp_path).last_success_name == daily[1].name


def test_the_hourly_job_sends_nothing_when_the_newest_copy_went(tracker, tmp_path, google):
    connect(tmp_path)
    run(tracker.backup_database())
    google.requests.clear()

    run(tracker.backup_database())

    assert google.requests == []


def test_the_hourly_job_retries_a_failed_copy_and_a_manual_one(tracker, tmp_path, google, clock):
    connect(tmp_path)
    google.answers["put"] = [(503, {})]
    run(tracker.backup_database())
    assert state(tmp_path).error == "down"

    clock.now = NOW + timedelta(hours=1)
    run(tracker.backup_database())
    assert state(tmp_path).error is None

    manual = copy_on_pc(tmp_path, datetime.now() + timedelta(minutes=1), suffix="manual")  # newer than the daily one
    run(tracker.backup_database())
    assert state(tmp_path).last_success_name == manual.name


def test_the_pc_that_was_off_sends_at_its_start(tracker, tmp_path, google):
    connect(tmp_path)
    copy_on_pc(tmp_path, datetime(2026, 11, 2, 4, 0))
    DriveFiles(tmp_path).write_state(
        DriveState(datetime(2026, 11, 2, 1, 0), datetime(2026, 11, 2, 1, 0), "tracker_db_20261101_040000.db", 5)
    )

    run(tracker.backup_database())  # the first run of the job is at the start

    assert state(tmp_path).last_success_name.startswith("tracker_db_20261108_")


def test_after_a_refused_sign_in_the_hourly_job_waits_for_a_new_one(tracker, tmp_path, google, clock):
    connect(tmp_path)
    google.answers["token"] = [(400, {"error": "invalid_grant"})]
    run(tracker.backup_database())
    google.requests.clear()

    clock.now = NOW + timedelta(hours=1)
    run(tracker.backup_database())
    assert google.requests == []

    connect(tmp_path, at=datetime(2026, 11, 8, 10, 30))  # «Подключить Google Drive» again
    clock.now = NOW + timedelta(hours=2)
    run(tracker.backup_database())
    assert state(tmp_path).error is None


@pytest.mark.parametrize("drive, connected", [(DriveSettings(), True), (DRIVE, False)])
def test_the_hourly_job_does_not_send_when_off_or_not_connected(tmp_path, google, clock, drive, connected):
    core = make_tracker(tmp_path, google, clock, drive)
    if connected:
        connect(tmp_path)

    run(core.backup_database())

    assert google.requests == [] and state(tmp_path) is None


def test_the_sign_in_sends_the_newest_copy_in_the_background(tracker, tmp_path, google):
    copy_on_pc(tmp_path)

    async def scenario():
        step = await tracker.drive_sign_in(HERE)
        the_state = parse_qs(urlsplit(step.address).query)["state"][0]
        google.answers["token"] = [(200, {"refresh_token": REFRESH, "access_token": "ya29.first", "expires_in": 3599})]
        await tracker.drive_signed_in({"code": "4/0Afake-code", "state": the_state})
        for _ in range(100):
            if state(tmp_path) is not None:
                return
            await asyncio.sleep(0.02)

    run(scenario())

    assert state(tmp_path).error is None and state(tmp_path).kept == 1


# ---- «Сделать копию сейчас» -------------------------------------------------------------------------


def press(tracker) -> str:
    return run(tracker.make_backup_now())


def test_the_press_sends_its_manual_copy(tracker, tmp_path, google):
    connect(tmp_path)

    assert press(tracker) == SENT

    [folder_id] = google.folders
    assert google.names_in(folder_id) == ["tracker_db_20261108_120005_manual.7z"]


@pytest.mark.parametrize("answer, notice", [
    (httpx.ConnectError("down"),
     "Копия сделана, но в Google Drive не ушла: нет связи с Google Drive. Попробую снова через час."),
    (drive_error(403, "storageQuotaExceeded"),
     "Копия сделана, но в Google Drive не ушла: в Google Drive нет места. Попробую снова через час."),
])
def test_a_press_whose_sending_failed_says_why(tracker, tmp_path, google, answer, notice):
    connect(tmp_path)
    google.answers["put"] = [answer]

    assert press(tracker) == notice
    assert (tmp_path / "backups" / "tracker_db_20261108_120005_manual.db").exists()


def test_a_press_refused_by_google_asks_to_connect_and_promises_no_retry(tracker, tmp_path, google):
    connect(tmp_path)
    google.answers["token"] = [(400, {"error": "invalid_grant"})]

    assert press(tracker) == (
        "Копия сделана, но в Google Drive не ушла: Google Drive не принял вход — подключите его заново в Настройках."
    )


@pytest.mark.parametrize("drive, connected", [(DriveSettings(), True), (DRIVE, False)])
def test_a_press_without_the_google_drive_copy_only_makes_the_copy(tmp_path, google, clock, drive, connected):
    core = make_tracker(tmp_path, google, clock, drive)
    if connected:
        connect(tmp_path)

    assert run(core.make_backup_now()) == "Копия сделана: сегодня в 12:00."
    assert google.requests == []


def test_a_slow_sending_goes_on_in_the_background_holding_the_lock(tracker, tmp_path, google, monkeypatch):
    from app.tracker import backups as backups_module

    monkeypatch.setattr(backups_module, "SEND_WAITS_SECONDS", 0.05)
    connect(tmp_path)
    release = asyncio.Event()

    async def slow(request):
        await release.wait()
        return google._find(request)

    google.answers["find"] = [slow]

    async def scenario():
        notice = await tracker.make_backup_now()
        locked = tracker._backups.ctx.backup_lock.locked()
        release.set()
        for _ in range(200):
            if not tracker._backups.ctx.backup_lock.locked():
                break
            await asyncio.sleep(0.01)
        return notice, locked

    notice, locked = run(scenario())

    assert notice == "Копия сделана; в Google Drive она ещё отправляется — итог появится здесь."
    assert locked
    assert state(tmp_path).error is None and state(tmp_path).kept == 1


def test_a_press_while_the_sending_of_the_hourly_job_goes_waits_for_it(tracker, tmp_path, google):
    connect(tmp_path)
    copy_on_pc(tmp_path)

    async def scenario():
        hourly = asyncio.create_task(tracker.backup_database())
        await asyncio.sleep(0)
        notice = await tracker.make_backup_now()
        await hourly
        return notice

    assert run(scenario()) == SENT
    [folder_id] = google.folders
    assert "tracker_db_20261108_120005_manual.7z" in google.names_in(folder_id)
    assert state(tmp_path).error is None and not tracker._backups.ctx.backup_lock.locked()


# ---- the line of Settings -----------------------------------------------------------------------


def line_of(tracker, host: str = HERE):
    return run(tracker.backup_block(host)).drive


def write_state(tmp_path, **fields) -> None:
    DriveFiles(tmp_path).write_state(DriveState(**fields))


def test_the_line_of_a_copy_that_works(tracker, tmp_path):
    connect(tmp_path)
    write_state(tmp_path, last_attempt_at=datetime(2026, 11, 8, 4, 58), last_success_at=datetime(2026, 11, 8, 4, 58),
                last_success_name="tracker_db_20261108_075800.db", kept=12)

    part = line_of(tracker)

    assert part.line == "Копия в Google Drive: сегодня в 07:58, там 12 копий из 30 хранимых."
    assert part.buttons == (DriveButton.DISCONNECT,) and part.hint == drive_rows.PASSWORD_HINT


@pytest.mark.parametrize("kept, word", [(1, "копия"), (2, "копии"), (5, "копий"), (21, "копия"), (30, "копий")])
def test_the_word_after_the_number_of_copies(kept, word):
    assert drive_rows.copies_word(kept) == word


def test_the_line_of_a_copy_that_failed_last_time(tracker, tmp_path):
    connect(tmp_path)
    write_state(tmp_path, last_attempt_at=datetime(2026, 11, 8, 8, 0), last_success_at=datetime(2026, 11, 7, 15, 32),
                last_success_name="x", kept=3, error="connection", failures_in_row=1)

    part = line_of(tracker)

    assert part.line == (
        "Копия в Google Drive не ушла: сегодня в 11:00 — нет связи с Google Drive. Последняя удачная — вчера в 18:32."
    )
    assert part.buttons == (DriveButton.DISCONNECT,)


def test_the_line_of_a_copy_that_never_went(tracker, tmp_path):
    connect(tmp_path)
    write_state(tmp_path, last_attempt_at=datetime(2026, 11, 8, 8, 0), error="full", failures_in_row=1)

    assert line_of(tracker).line == (
        "Копия в Google Drive не ушла: сегодня в 11:00 — в Google Drive нет места. Удачных ещё не было."
    )


def test_a_refused_sign_in_offers_to_connect_again(tracker, tmp_path):
    connect(tmp_path)
    write_state(tmp_path, last_attempt_at=datetime(2026, 11, 8, 8, 0), error="sign_in", failures_in_row=1)

    assert line_of(tracker).buttons == (DriveButton.CONNECT, DriveButton.DISCONNECT)
    elsewhere = line_of(tracker, "192.168.1.5:8080")
    assert elsewhere.buttons == (DriveButton.DISCONNECT,) and "http://localhost:8080/settings" in elsewhere.elsewhere


def test_a_connection_with_no_attempt_yet_says_the_first_copy_goes_within_the_hour(tracker, tmp_path):
    connect(tmp_path)

    assert line_of(tracker).line == drive_rows.CONNECTED_LINE


def test_an_unknown_reason_key_reads_as_the_unknown_one(tracker, tmp_path):
    connect(tmp_path)
    write_state(tmp_path, last_attempt_at=datetime(2026, 11, 8, 8, 0), error="from_a_newer_version", failures_in_row=1)

    assert "неизвестная ошибка, подробности в журнале" in line_of(tracker).line
