"""The connection of the Google Drive copy (stage 7.1, ticket 03; spec 4.1–4.3): the launch settings and the one rule
«on», the masking of the new secrets, the files of the connection, the sign-in with PKCE only on this PC, every case of
Google's return and the sign-out — on the real core with a fake Google (`httpx.MockTransport`)."""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.config import Settings
from app.providers.google_drive import GoogleDriveApi
from app.tracker import drive_rows, google_drive
from app.tracker.core import DriveSettings, DriveSetup, Redirect, Tracker
from app.tracker.db import create_session_factory
from app.tracker.google_drive import DriveFiles, DriveToken, challenge_of
from app.utils.logging_config import MaskingFormatter
from app.utils.secrets_mask import remember_secrets

MOSCOW = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)
CLIENT_ID = "1234-abcd.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-fake-client-secret-value"
PASSWORD = "длинный пароль копий"
REFRESH = "1//0g-fake-refresh-token-value-abcdefghijklmnop"
CODE = "4/0Afake-authorization-code-value"
DRIVE = DriveSettings(CLIENT_ID, CLIENT_SECRET, PASSWORD, 8080)
HERE = "localhost:8080"
CALLBACK = "http://localhost:8080/settings/google-drive/callback"


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeGoogle:
    """Answers the token and the revoke requests as told, and keeps every request."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.token_answer: object = (200, {"access_token": "ya29.fake", "expires_in": 3599, "refresh_token": REFRESH,
                                           "scope": "https://www.googleapis.com/auth/drive.file", "token_type": "Bearer"})
        self.revoke_answer: object = (200, {})

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.token_answer if request.url.path == "/token" else self.revoke_answer
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        if isinstance(body, bytes):
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=body)

    def form(self, number: int = -1) -> dict[str, str]:
        return {key: values[0] for key, values in parse_qs(self.requests[number].content.decode()).items()}


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def google():
    return FakeGoogle()


@pytest.fixture
def clock():
    return Clock()


def make_tracker(tmp_path, google, clock, drive=DRIVE) -> Tracker:
    url = f"sqlite:///{(tmp_path / 'tracker.db').as_posix()}"
    api = GoogleDriveApi(drive.client_id, drive.client_secret, transport=httpx.MockTransport(google.handle))
    return Tracker(
        create_session_factory(url), clock=clock, sender=FakeSender(), default_tz=MOSCOW, database_url=url,
        drive_settings=drive, drive_api=api,
    )


@pytest.fixture
def tracker(tmp_path, google, clock):
    return make_tracker(tmp_path, google, clock)


def query_of(address: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlsplit(address).query).items()}


def press(tracker, host: str = HERE) -> dict[str, str]:
    step = asyncio.run(tracker.drive_sign_in(host))
    assert step.address.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    return query_of(step.address)


def come_back(tracker, **answer: str) -> str:
    return asyncio.run(tracker.drive_signed_in(answer))


def token_file(tmp_path):
    return tmp_path / "google_drive_token.json"


# ---- the launch settings -------------------------------------------------------------------

@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr("app.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:AAH-secretTokenValue_abcdefghijklmnopqrstuv")
    monkeypatch.setenv("TMDB_API_KEY", "tmdb-test-key")
    for name in ("BACKUP_PASSWORD", "GOOGLE_DRIVE_CLIENT_ID", "GOOGLE_DRIVE_CLIENT_SECRET", "WEB_PORT"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_none_of_the_three_is_required_and_the_copy_is_off_without_them(env):
    settings = Settings()

    assert (settings.backup_password, settings.google_drive_client_id, settings.google_drive_client_secret) == ("", "", "")
    assert DriveSettings(settings.google_drive_client_id, settings.google_drive_client_secret).setup is DriveSetup.OFF


def test_the_values_are_stripped(env):
    env.setenv("BACKUP_PASSWORD", "  двенадцать знаков  ")
    env.setenv("GOOGLE_DRIVE_CLIENT_ID", f" {CLIENT_ID}\t")
    env.setenv("GOOGLE_DRIVE_CLIENT_SECRET", f"  {CLIENT_SECRET} ")

    settings = Settings()

    assert settings.backup_password == "двенадцать знаков"
    assert (settings.google_drive_client_id, settings.google_drive_client_secret) == (CLIENT_ID, CLIENT_SECRET)


@pytest.mark.parametrize("client_id, secret, password, setup", [
    ("", "", "", DriveSetup.OFF),
    (CLIENT_ID, "", PASSWORD, DriveSetup.OFF),
    ("", CLIENT_SECRET, PASSWORD, DriveSetup.OFF),
    (CLIENT_ID, CLIENT_SECRET, "", DriveSetup.NO_PASSWORD),
    (CLIENT_ID, CLIENT_SECRET, "x" * 11, DriveSetup.NO_PASSWORD),
    (CLIENT_ID, CLIENT_SECRET, "x" * 12, DriveSetup.ON),
    (CLIENT_ID, CLIENT_SECRET, "ё" * 12, DriveSetup.ON),  # letters, not bytes
])
def test_the_copy_is_on_with_the_client_and_a_password_of_twelve(client_id, secret, password, setup):
    assert DriveSettings(client_id, secret, password).setup is setup


def test_a_password_of_spaces_around_eleven_characters_is_short(env):
    env.setenv("BACKUP_PASSWORD", "   " + "x" * 11 + "   ")

    settings = Settings()

    assert DriveSettings(CLIENT_ID, CLIENT_SECRET, settings.backup_password).setup is DriveSetup.NO_PASSWORD


@pytest.mark.parametrize("value, port", [("8081", 8081), ("", 8080), (" 9000 ", 9000), ("abc", 8080), ("70000", 8080)])
def test_the_web_port_for_the_sentence_of_another_host(env, value, port):
    env.setenv("WEB_PORT", value)

    assert Settings().web_port_number == port


def test_the_password_and_the_secret_are_masked_by_their_names(env):
    env.setenv("BACKUP_PASSWORD", PASSWORD)
    env.setenv("GOOGLE_DRIVE_CLIENT_SECRET", CLIENT_SECRET)
    remember_secrets()
    record = logging.LogRecord(
        "t", logging.WARNING, __file__, 1, "values %s and %s", (PASSWORD, CLIENT_SECRET), None
    )

    line = MaskingFormatter("%(message)s").format(record)

    assert PASSWORD not in line and CLIENT_SECRET not in line


@pytest.mark.parametrize("text, secret", [
    (f"GET /settings/google-drive/callback?state=abc&code={CODE}&scope=x", CODE),
    (f"grant_type=authorization_code&code={CODE}&code_verifier=verifier-value-0123", "verifier-value-0123"),
    (f'{{"access_token": "ya29.fake", "refresh_token": "{REFRESH}", "id_token": "eyJfake"}}', REFRESH),
    ('{"id_token": "eyJfake.id.token"}', "eyJfake.id.token"),
])
def test_the_codes_and_tokens_of_a_google_sign_in_are_masked(text, secret):
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "%s", (text,), None)

    assert secret not in MaskingFormatter("%(message)s").format(record)


def test_a_status_code_stays_readable():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "status_code=400 error_code=7", (), None)

    assert MaskingFormatter("%(message)s").format(record) == "status_code=400 error_code=7"


# ---- the files -----------------------------------------------------------------------------

def test_the_token_file_is_written_whole_and_read_back(tmp_path):
    files = DriveFiles(tmp_path / "data")
    token = DriveToken(REFRESH, datetime(2026, 11, 8, 9, 0, 5), None)

    files.write_token(token)

    assert files.token() == token
    assert [path.name for path in (tmp_path / "data").iterdir()] == ["google_drive_token.json"]  # no temporary left
    stored = json.loads((tmp_path / "data" / "google_drive_token.json").read_text(encoding="utf-8"))
    assert stored == {"refresh_token": REFRESH, "connected_at": "2026-11-08T09:00:05", "folder_id": None}


@pytest.mark.skipif(sys.platform == "win32", reason="the rights of a file are POSIX's (the container)")
def test_the_token_file_has_the_rights_of_the_apps_user_only(tmp_path):
    (tmp_path / "google_drive_token.json.tmp").write_text("old")
    os.chmod(tmp_path / "google_drive_token.json.tmp", 0o644)

    DriveFiles(tmp_path).write_token(DriveToken(REFRESH, datetime(2026, 11, 8)))

    assert (tmp_path / "google_drive_token.json").stat().st_mode & 0o777 == 0o600


def test_a_failure_while_writing_leaves_the_old_token_file(tmp_path, monkeypatch):
    files = DriveFiles(tmp_path)
    files.write_token(DriveToken(REFRESH, datetime(2026, 11, 8)))

    def broken(*args):
        raise OSError("disk full")

    monkeypatch.setattr(google_drive.os, "replace", broken)
    with pytest.raises(OSError):
        files.write_token(DriveToken("1//another", datetime(2026, 11, 9)))

    assert files.token().refresh_token == REFRESH


@pytest.mark.parametrize("content", [
    "not json", "[1, 2]", '{"connected_at": "2026-11-08T09:00:00"}', '{"refresh_token": "", "connected_at": "2026-11-08"}',
    '{"refresh_token": 5, "connected_at": "2026-11-08"}', '{"refresh_token": "x", "connected_at": "yesterday"}',
    '{"refresh_token": "x", "connected_at": "2026-11-08", "folder_id": 7}',
])
def test_a_spoiled_token_file_reads_as_absent_with_a_warning(tmp_path, caplog, content):
    token_file(tmp_path).write_text(content, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert DriveFiles(tmp_path).token() is None

    assert "google_drive_token.json" in caplog.text


def test_a_token_file_not_in_utf8_reads_as_absent(tmp_path, caplog):
    token_file(tmp_path).write_bytes(b"\xff\xfe\x00")

    with caplog.at_level(logging.WARNING):
        assert DriveFiles(tmp_path).token() is None

    assert "google_drive_token.json" in caplog.text


@pytest.mark.parametrize("content", ["{broken", '"text"'])
def test_a_spoiled_state_file_reads_as_no_attempts_with_a_warning(tmp_path, caplog, content):
    (tmp_path / "google_drive_state.json").write_text(content, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert DriveFiles(tmp_path).state() is None

    assert "google_drive_state.json" in caplog.text


def test_missing_files_read_as_absent_without_a_warning(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert DriveFiles(tmp_path).token() is None and DriveFiles(tmp_path).state() is None

    assert caplog.text == ""


def test_the_state_file_is_read_as_written(tmp_path):
    (tmp_path / "google_drive_state.json").write_text('{"error": null, "failures_in_row": 0}', encoding="utf-8")

    assert DriveFiles(tmp_path).state() == {"error": None, "failures_in_row": 0}


# ---- the sign-in ---------------------------------------------------------------------------

def test_the_sign_in_address_has_every_parameter_and_pkce(tracker):
    query = press(tracker)

    pending = tracker._drive._pending
    assert query == {
        "client_id": CLIENT_ID, "redirect_uri": CALLBACK, "response_type": "code",
        "scope": "https://www.googleapis.com/auth/drive.file", "access_type": "offline", "prompt": "consent",
        "state": pending.state, "code_challenge": challenge_of(pending.verifier), "code_challenge_method": "S256",
    }
    assert len(pending.state) == 43  # 32 random bytes in base64url
    assert 43 <= len(pending.verifier) <= 128 and query["code_challenge"] != pending.verifier


def test_the_challenge_is_the_s256_of_the_verifier():
    # RFC 7636, appendix B
    assert challenge_of("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


@pytest.mark.parametrize("host, redirect", [
    ("localhost:8080", CALLBACK),
    ("127.0.0.1:8080", "http://127.0.0.1:8080/settings/google-drive/callback"),
    ("LOCALHOST:8081", "http://localhost:8081/settings/google-drive/callback"),
])
def test_the_sign_in_returns_to_the_host_and_port_of_the_page(tracker, host, redirect):
    assert press(tracker, host)["redirect_uri"] == redirect


@pytest.mark.parametrize("host", ["192.168.1.5:8080", "tracker.example:8080", "localhost.evil:8080", "", "[::1]:8080"])
def test_on_another_host_the_sign_in_only_says_where_to_open_it(tracker, google, host):
    step = asyncio.run(tracker.drive_sign_in(host))

    assert step.address == ""
    assert step.notice == "Подключить Google Drive можно только на этом ПК: откройте http://localhost:8080/settings."
    assert tracker._drive._pending is None and google.requests == []


def test_the_sentence_of_another_host_has_the_port_of_web_port(tmp_path, google, clock):
    tracker = make_tracker(tmp_path, google, clock, DriveSettings(CLIENT_ID, CLIENT_SECRET, PASSWORD, 8081))

    assert asyncio.run(tracker.drive_sign_in("192.168.1.5:8081")).notice.endswith("http://localhost:8081/settings.")


@pytest.mark.parametrize("drive", [DriveSettings(), DriveSettings(CLIENT_ID, CLIENT_SECRET, "short")])
def test_with_the_copy_not_on_the_sign_in_and_the_return_do_nothing(tmp_path, google, clock, drive):
    tracker = make_tracker(tmp_path, google, clock, drive)

    assert asyncio.run(tracker.drive_sign_in(HERE)) == google_drive.SignInStep()
    assert come_back(tracker, code=CODE, state="anything") == ""
    assert google.requests == [] and not token_file(tmp_path).exists()


def test_a_successful_return_stores_the_refresh_token_and_says_the_first_copy_goes(tracker, google, tmp_path, clock):
    state = press(tracker)["state"]
    verifier = tracker._drive._pending.verifier
    clock.now = NOW + timedelta(minutes=3)

    notice = come_back(tracker, code=CODE, state=state, scope="https://www.googleapis.com/auth/drive.file")

    assert notice == "Google Drive подключён. Первая копия отправляется — итог появится здесь через минуту."
    assert str(google.requests[0].url) == "https://oauth2.googleapis.com/token"
    assert google.form() == {
        "grant_type": "authorization_code", "code": CODE, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "redirect_uri": CALLBACK, "code_verifier": verifier,
    }
    assert DriveFiles(tmp_path).token() == DriveToken(REFRESH, datetime(2026, 11, 8, 9, 3), None)


def test_a_pending_sign_in_is_used_up_by_its_return(tracker, google):
    state = press(tracker)["state"]
    come_back(tracker, code=CODE, state=state)

    assert come_back(tracker, code=CODE, state=state) == drive_rows.NOT_FINISHED
    assert len(google.requests) == 1


@pytest.mark.parametrize("minutes, stored", [(10, True), (10.02, False)])
def test_a_sign_in_waits_ten_minutes(tracker, tmp_path, clock, minutes, stored):
    state = press(tracker)["state"]
    clock.now = NOW + timedelta(minutes=minutes)

    notice = come_back(tracker, code=CODE, state=state)

    assert (notice == drive_rows.CONNECTED) is stored and token_file(tmp_path).exists() is stored
    if not stored:
        assert notice == "Вход в Google не завершён — нажмите «Подключить Google Drive» ещё раз."


def test_a_new_press_replaces_the_pending_sign_in(tracker, tmp_path):
    first = press(tracker)["state"]
    second = press(tracker)["state"]

    assert first != second
    assert come_back(tracker, code=CODE, state=first) == drive_rows.NOT_FINISHED
    assert come_back(tracker, code=CODE, state=second) == drive_rows.CONNECTED


def test_a_foreign_state_is_refused_and_leaves_the_pending_one(tracker, google, tmp_path):
    state = press(tracker)["state"]

    assert come_back(tracker, code=CODE, state="foreign-" + state) == drive_rows.NOT_FINISHED
    assert come_back(tracker, code=CODE) == drive_rows.NOT_FINISHED
    assert google.requests == [] and not token_file(tmp_path).exists()
    assert come_back(tracker, code=CODE, state=state) == drive_rows.CONNECTED


def test_a_return_after_a_restart_is_refused(tmp_path, google, clock):
    state = press(make_tracker(tmp_path, google, clock))["state"]

    assert come_back(make_tracker(tmp_path, google, clock), code=CODE, state=state) == drive_rows.NOT_FINISHED


@pytest.mark.parametrize("error, notice", [
    ("access_denied", "Вы не дали доступ к Google Drive — копия туда не включена."),
    ("invalid_scope", "Google не подтвердил вход (invalid_scope). Попробуйте ещё раз."),
    ("<b>x</b> y", "Google не подтвердил вход (bxby). Попробуйте ещё раз."),
])
def test_an_error_from_google_stores_nothing(tracker, google, tmp_path, error, notice):
    state = press(tracker)["state"]

    assert come_back(tracker, error=error, state=state) == notice
    assert google.requests == [] and not token_file(tmp_path).exists()
    assert tracker._drive._pending is None  # the sign-in is over


@pytest.mark.parametrize("answer", [
    (400, {"error": "invalid_grant", "error_description": "Bad Request"}),
    (401, {"error": "invalid_client"}),
    (500, b"<html>down</html>"),
    (200, b"not json"),
    (200, {"access_token": "ya29.fake", "expires_in": 3599}),  # no refresh token
    (200, {"refresh_token": ""}),
    httpx.ConnectError("no route"),
    httpx.ReadTimeout("slow"),
])
def test_a_failed_token_request_stores_nothing(tracker, google, tmp_path, caplog, answer):
    google.token_answer = answer
    state = press(tracker)["state"]

    with caplog.at_level(logging.WARNING):
        notice = come_back(tracker, code=CODE, state=state)

    assert notice == "Google не подтвердил вход. Попробуйте ещё раз; если повторится — подробности в журнале."
    assert not token_file(tmp_path).exists() and "Google sign-in" in caplog.text


def test_a_return_without_a_code_stores_nothing(tracker, google, tmp_path):
    state = press(tracker)["state"]

    assert come_back(tracker, state=state) == drive_rows.NOT_CONFIRMED
    assert google.requests == [] and not token_file(tmp_path).exists()


def test_a_token_file_that_cannot_be_written_is_a_failure(tracker, tmp_path, monkeypatch, caplog):
    state = press(tracker)["state"]

    def broken(self, token):
        raise OSError("read-only")

    monkeypatch.setattr(DriveFiles, "write_token", broken)
    with caplog.at_level(logging.WARNING):
        assert come_back(tracker, code=CODE, state=state) == drive_rows.NOT_CONFIRMED

    assert "cannot be written" in caplog.text


def test_after_a_sign_in_the_seam_of_the_first_copy_runs_in_the_background(tracker):
    ran = []

    async def first_copy():
        ran.append("sent")

    async def scenario():
        tracker._drive.on_connected = first_copy
        step = await tracker.drive_sign_in(HERE)
        notice = await tracker.drive_signed_in({"code": CODE, "state": query_of(step.address)["state"]})
        assert ran == []  # not waited for
        await asyncio.sleep(0)
        return notice

    assert asyncio.run(scenario()) == drive_rows.CONNECTED and ran == ["sent"]


def test_no_secret_reaches_the_log(tracker, google, caplog):
    google.token_answer = (400, {"error": "invalid_grant", "error_description": f"bad {CODE}"})
    with caplog.at_level(logging.DEBUG):
        state = press(tracker)["state"]
        come_back(tracker, code=CODE, state=state)
        google.token_answer = FakeGoogle().token_answer
        state = press(tracker)["state"]
        come_back(tracker, code=CODE, state=state)
        google.revoke_answer = (400, {"error": "invalid_token"})
        asyncio.run(tracker.drive_sign_out())

    verifier_seen = google.form(1)["code_verifier"]
    for secret in (CLIENT_SECRET, REFRESH, CODE, verifier_seen, state):
        assert secret not in caplog.text


# ---- the switch of the return address --------------------------------------------------------

def test_under_the_loopback_ip_switch_localhost_is_sent_to_127_0_0_1_first(tracker, monkeypatch):
    monkeypatch.setattr(google_drive, "REDIRECT", Redirect.LOOPBACK_IP)

    step = asyncio.run(tracker.drive_sign_in("localhost:8080"))

    assert step == google_drive.SignInStep(address="http://127.0.0.1:8080/settings")
    assert tracker._drive._pending is None
    assert press(tracker, "127.0.0.1:8080")["redirect_uri"] == "http://127.0.0.1:8080/settings/google-drive/callback"


def test_under_the_root_switch_google_returns_to_the_feeds_address(tracker, google, monkeypatch):
    monkeypatch.setattr(google_drive, "REDIRECT", Redirect.ROOT)

    state = press(tracker)["state"]
    come_back(tracker, code=CODE, state=state)

    assert google.form()["redirect_uri"] == "http://localhost:8080/"


# ---- the sign-out --------------------------------------------------------------------------

def connect(tracker) -> None:
    assert come_back(tracker, code=CODE, state=press(tracker)["state"]) == drive_rows.CONNECTED


def test_the_sign_out_revokes_the_token_and_removes_both_files(tracker, google, tmp_path):
    connect(tracker)
    (tmp_path / "google_drive_state.json").write_text("{}", encoding="utf-8")

    notice = asyncio.run(tracker.drive_sign_out())

    assert notice == "Google Drive отключён. Копии, которые уже там, остались в папке «Трекер — копии»."
    assert str(google.requests[-1].url) == "https://oauth2.googleapis.com/revoke"
    assert google.form() == {"token": REFRESH}
    assert not token_file(tmp_path).exists() and not (tmp_path / "google_drive_state.json").exists()


@pytest.mark.parametrize("answer", [(400, {"error": "invalid_token"}), httpx.ConnectError("offline")])
def test_a_failed_revoke_is_only_logged(tracker, google, tmp_path, caplog, answer):
    connect(tracker)
    google.revoke_answer = answer

    with caplog.at_level(logging.WARNING):
        assert asyncio.run(tracker.drive_sign_out()) == drive_rows.DISCONNECTED

    assert not token_file(tmp_path).exists() and "could not be revoked" in caplog.text


def test_the_sign_out_without_a_token_asks_google_nothing(tracker, google, tmp_path):
    token_file(tmp_path).write_text("spoiled", encoding="utf-8")

    assert asyncio.run(tracker.drive_sign_out()) == drive_rows.DISCONNECTED
    assert google.requests == [] and not token_file(tmp_path).exists()


def test_the_sign_out_ends_a_pending_sign_in(tracker):
    state = press(tracker)["state"]
    asyncio.run(tracker.drive_sign_out())

    assert come_back(tracker, code=CODE, state=state) == drive_rows.NOT_FINISHED


# ---- the part of the Settings block ----------------------------------------------------------

@pytest.mark.parametrize("setup, connected, here, line, buttons", [
    (DriveSetup.OFF, False, True, "Копия в Google Drive выключена. Как включить — docs/backups.md в папке трекера.", ()),
    (DriveSetup.OFF, True, True, drive_rows.OFF_LINE, ()),
    (DriveSetup.NO_PASSWORD, False, True,
     "Копия в Google Drive не включится: в .env нет пароля BACKUP_PASSWORD или он короче 12 знаков.", ()),
    (DriveSetup.ON, False, True, "Google Drive не подключён.", (drive_rows.DriveButton.CONNECT,)),
    (DriveSetup.ON, False, False, "Google Drive не подключён.", ()),
    (DriveSetup.ON, True, True, "Google Drive подключён; первая копия уйдёт в течение часа.",
     (drive_rows.DriveButton.DISCONNECT,)),
    (DriveSetup.ON, True, False, drive_rows.CONNECTED_LINE, (drive_rows.DriveButton.DISCONNECT,)),
])
def test_the_line_and_the_buttons_of_each_state(setup, connected, here, line, buttons):
    part = drive_rows.drive_part(setup, connected, here, 8080)

    assert (part.line, part.buttons) == (line, buttons)
    assert (part.hint == drive_rows.PASSWORD_HINT) is (setup is DriveSetup.ON and connected)
    assert bool(part.elsewhere) is (setup is DriveSetup.ON and not connected and not here)


def test_the_hint_under_a_connected_line():
    assert drive_rows.drive_part(DriveSetup.ON, True, True, 8080).hint == (
        "Копии зашифрованы паролем BACKUP_PASSWORD из .env. Храните его и вне этого ПК: без него копии из Google Drive "
        "не открыть. Новый пароль действует только для новых копий."
    )


def test_the_block_reads_the_connection_from_the_token_file(tracker, tmp_path):
    assert asyncio.run(tracker.backup_block(HERE)).drive.line == drive_rows.NOT_CONNECTED_LINE

    connect(tracker)
    assert asyncio.run(tracker.backup_block(HERE)).drive.line == drive_rows.CONNECTED_LINE

    token_file(tmp_path).write_text("{", encoding="utf-8")
    assert asyncio.run(tracker.backup_block(HERE)).drive.line == drive_rows.NOT_CONNECTED_LINE


def test_a_part_that_cannot_be_built_leaves_the_copies_line(tracker, monkeypatch, caplog):
    async def broken(host):
        raise RuntimeError("boom")

    monkeypatch.setattr(tracker._drive, "part", broken)
    with caplog.at_level(logging.WARNING):
        block = asyncio.run(tracker.backup_block(HERE))

    assert block.drive is None and block.copies_line and "Google Drive part" in caplog.text
