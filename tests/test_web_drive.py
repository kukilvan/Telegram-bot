"""The Google Drive copy in Settings (stage 7.1, ticket 03; spec 4.2 and 4.7): the line of each state from prepared
`.env` values and files, the sentence of another host, «Подключить Google Drive» → Google → Settings with its notice,
«Отключить Google Drive», the return through the Feed's address under the switch `ROOT`, the secrets on no page."""

import html
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers.google_drive import GoogleDriveApi
from app.runtime import Health
from app.tracker import google_drive
from app.tracker.core import DriveSettings, Redirect, Tracker
from app.tracker.db import create_session_factory
from app.web import create_web_app
from app.web import feed as feed_page

PASSWORD = "correct horse battery"
NOW = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)
CLIENT_ID = "1234-abcd.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-fake-client-secret-value"
BACKUP_PASSWORD = "длинный пароль копий"
REFRESH = "1//0g-fake-refresh-token-value-abcdefghijklmnop"
ON = DriveSettings(CLIENT_ID, CLIENT_SECRET, BACKUP_PASSWORD, 8080)
HERE = "http://localhost:8080"


class FakeSender:
    async def send(self, message, actions=()):
        pass


class FakeGoogle:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/token":
            return httpx.Response(200, json={"access_token": "ya29.fake", "refresh_token": REFRESH, "expires_in": 3599})
        return httpx.Response(200, json={})


@pytest.fixture
def google():
    return FakeGoogle()


def make_client(tmp_path, google, drive=ON, base_url=HERE) -> TestClient:
    url = f"sqlite:///{(tmp_path / 'tracker.db').as_posix()}"
    api = GoogleDriveApi(drive.client_id, drive.client_secret, transport=httpx.MockTransport(google.handle))
    tracker = Tracker(
        create_session_factory(url), clock=lambda: NOW, sender=FakeSender(), default_tz=ZoneInfo("Europe/Moscow"),
        database_url=url, drive_settings=drive, drive_api=api,
    )
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    app = create_web_app(health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker)
    client = TestClient(app, base_url=base_url, follow_redirects=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


def block_text(page: str) -> str:
    start = page.index("<h2>Копии и выгрузка</h2>")
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page[start:page.index("</section>", start)])).split())


def token_file(tmp_path):
    return tmp_path / "google_drive_token.json"


def put_token(tmp_path, content: str | None = None) -> None:
    token_file(tmp_path).write_text(
        content or f'{{"refresh_token": "{REFRESH}", "connected_at": "2026-11-08T09:00:00", "folder_id": null}}',
        encoding="utf-8",
    )


def sign_in_at_google(client) -> str:
    """«Подключить Google Drive»: Google's address, and the `state` it carries."""
    answer = client.get("/settings/google-drive/connect")
    assert answer.status_code == 303
    location = answer.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    return parse_qs(urlsplit(location).query)["state"][0]


# ---- the lines ---------------------------------------------------------------------------

@pytest.mark.parametrize("drive, line", [
    (DriveSettings(), "Копия в Google Drive выключена. Как включить — docs/backups.md в папке трекера."),
    (DriveSettings(CLIENT_ID, "", BACKUP_PASSWORD), "Копия в Google Drive выключена."),
    (DriveSettings(CLIENT_ID, CLIENT_SECRET, ""),
     "Копия в Google Drive не включится: в .env нет пароля BACKUP_PASSWORD или он короче 12 знаков."),
    (DriveSettings(CLIENT_ID, CLIENT_SECRET, "x" * 11), "в .env нет пароля BACKUP_PASSWORD или он короче 12 знаков."),
])
def test_the_copy_off_or_without_a_password_has_a_line_and_no_button(tmp_path, google, drive, line):
    page = make_client(tmp_path, google, drive).get("/settings").text

    assert line in block_text(page)
    assert "Подключить Google Drive" not in page and "Отключить Google Drive" not in page


def test_on_and_not_connected_the_block_has_the_connect_button(tmp_path, google):
    page = make_client(tmp_path, google).get("/settings").text

    text = block_text(page)
    assert "Google Drive не подключён." in text and "Подключить Google Drive" in text
    assert 'href="/settings/google-drive/connect"' in page
    assert text.index("базы на этом ПК") < text.index("Google Drive не подключён.") < text.index("Сделать копию сейчас")
    assert "Копии зашифрованы паролем" not in text


def test_connected_the_block_has_the_hint_and_the_disconnect_button(tmp_path, google):
    put_token(tmp_path)

    page = make_client(tmp_path, google).get("/settings").text

    text = block_text(page)
    assert "Google Drive подключён; первая копия уйдёт в течение часа." in text
    assert ("Копии зашифрованы паролем BACKUP_PASSWORD из .env. Храните его и вне этого ПК: без него копии из Google "
            "Drive не открыть. Новый пароль действует только для новых копий.") in text
    assert 'action="/settings/google-drive/disconnect"' in page and "Подключить Google Drive" not in text


def test_a_spoiled_token_file_reads_as_not_connected(tmp_path, google):
    put_token(tmp_path, "{ spoiled")

    assert "Google Drive не подключён." in block_text(make_client(tmp_path, google).get("/settings").text)


def test_on_another_host_the_button_is_the_sentence(tmp_path, google):
    page = make_client(tmp_path, google, base_url="http://192.168.1.5:8080").get("/settings").text

    text = block_text(page)
    assert "Подключить Google Drive можно только на этом ПК: откройте http://localhost:8080/settings." in text
    assert 'href="/settings/google-drive/connect"' not in page


def test_127_0_0_1_counts_as_this_pc(tmp_path, google):
    page = make_client(tmp_path, google, base_url="http://127.0.0.1:8080").get("/settings").text

    assert 'href="/settings/google-drive/connect"' in page


def test_the_secrets_are_on_no_page(tmp_path, google):
    client = make_client(tmp_path, google)
    state = sign_in_at_google(client)
    client.get("/settings/google-drive/callback", params={"code": "4/0Acode", "state": state})

    page = client.get("/settings").text

    for secret in (CLIENT_SECRET, BACKUP_PASSWORD, REFRESH):
        assert secret not in page


# ---- the sign-in and the sign-out -----------------------------------------------------------

def test_the_whole_sign_in_from_the_button_back_to_settings(tmp_path, google):
    client = make_client(tmp_path, google)
    state = sign_in_at_google(client)

    answer = client.get("/settings/google-drive/callback", params={"code": "4/0Acode", "state": state, "scope": "x"})

    assert answer.status_code == 303 and answer.headers["location"] == "/settings"
    page = client.get("/settings").text
    assert "Google Drive подключён. Первая копия отправляется — итог появится здесь через минуту." in page
    assert "Отключить Google Drive" in page and token_file(tmp_path).exists()
    assert "Первая копия отправляется" not in client.get("/settings").text  # the notice is shown once


def test_the_connect_on_another_host_goes_back_with_the_sentence(tmp_path, google):
    client = make_client(tmp_path, google, base_url="http://192.168.1.5:8080")

    answer = client.get("/settings/google-drive/connect")

    assert answer.status_code == 303 and answer.headers["location"] == "/settings"
    assert "Подключить Google Drive можно только на этом ПК" in client.get("/settings").text


def test_the_connect_with_the_copy_off_goes_back_without_a_notice(tmp_path, google):
    client = make_client(tmp_path, google, DriveSettings())

    answer = client.get("/settings/google-drive/connect")

    assert answer.headers["location"] == "/settings"
    assert 'class="notice"' not in client.get("/settings").text and google.requests == []


@pytest.mark.parametrize("params, notice", [
    ({"error": "access_denied"}, "Вы не дали доступ к Google Drive — копия туда не включена."),
    ({"code": "4/0Acode", "state": "stale"}, "Вход в Google не завершён — нажмите «Подключить Google Drive» ещё раз."),
])
def test_a_failed_return_shows_its_notice_and_stores_nothing(tmp_path, google, params, notice):
    client = make_client(tmp_path, google)
    sign_in_at_google(client)

    client.get("/settings/google-drive/callback", params=params)

    assert notice in client.get("/settings").text and not token_file(tmp_path).exists()


def test_the_return_without_the_sign_in_to_the_web_stores_nothing(tmp_path, google):
    client = make_client(tmp_path, google)
    state = sign_in_at_google(client)
    client.cookies.clear()

    answer = client.get("/settings/google-drive/callback", params={"code": "4/0Acode", "state": state})

    assert answer.status_code == 303 and answer.headers["location"].startswith("/login")
    assert not token_file(tmp_path).exists() and google.requests == []


def test_the_disconnect_removes_the_files_and_says_so(tmp_path, google):
    put_token(tmp_path)
    (tmp_path / "google_drive_state.json").write_text("{}", encoding="utf-8")
    client = make_client(tmp_path, google)

    answer = client.post("/settings/google-drive/disconnect")

    assert answer.status_code == 303 and answer.headers["location"] == "/settings"
    page = client.get("/settings").text
    assert "Google Drive отключён. Копии, которые уже там, остались в папке «Трекер — копии»." in page
    assert "Google Drive не подключён." in block_text(page)
    assert not token_file(tmp_path).exists() and not (tmp_path / "google_drive_state.json").exists()
    assert [request.url.path for request in google.requests] == ["/revoke"]


def test_the_disconnect_from_a_foreign_page_is_refused(tmp_path, google):
    put_token(tmp_path)
    client = make_client(tmp_path, google)

    answer = client.post("/settings/google-drive/disconnect", headers={"Origin": "https://evil.example"})

    assert answer.status_code == 403 and token_file(tmp_path).exists()


# ---- the switch: Google returns to the Feed's address --------------------------------------

def test_under_the_root_switch_the_feeds_address_takes_googles_answer(tmp_path, google, monkeypatch):
    monkeypatch.setattr(google_drive, "REDIRECT", Redirect.ROOT)
    monkeypatch.setattr(feed_page, "DRIVE_REDIRECT", Redirect.ROOT)
    client = make_client(tmp_path, google)
    state = sign_in_at_google(client)

    answer = client.get("/", params={"code": "4/0Acode", "state": state, "scope": "x"})

    assert answer.status_code == 303 and answer.headers["location"] == "/settings"
    assert token_file(tmp_path).exists()
    assert client.get("/").status_code == 200  # the Feed itself is still there


def test_with_the_callback_switch_the_feed_ignores_such_a_query(tmp_path, google):
    client = make_client(tmp_path, google)
    state = sign_in_at_google(client)

    answer = client.get("/", params={"code": "4/0Acode", "state": state})

    assert answer.status_code == 200 and not token_file(tmp_path).exists()


# ---- the lines of a copy sent or failed, and the press (ticket 04) --------------------------------

def put_state(tmp_path, content: str) -> None:
    (tmp_path / "google_drive_state.json").write_text(content, encoding="utf-8")


def test_the_block_shows_the_copy_that_works(tmp_path, google):
    put_token(tmp_path)
    put_state(tmp_path, '{"last_attempt_at": "2026-11-08T04:58:00", "last_success_at": "2026-11-08T04:58:00", '
                        '"last_success_name": "tracker_db_20261108_075800.db", "kept": 3, "error": null, '
                        '"failures_in_row": 0}')

    page = make_client(tmp_path, google).get("/settings").text

    text = block_text(page)
    assert "Копия в Google Drive: сегодня в 07:58, там 3 копии из 30 хранимых." in text
    assert "Копии зашифрованы паролем" in text and "Подключить Google Drive" not in text


def test_the_block_of_a_refused_sign_in_has_both_buttons(tmp_path, google):
    put_token(tmp_path)
    put_state(tmp_path, '{"last_attempt_at": "2026-11-08T08:00:00", "error": "sign_in", "failures_in_row": 1}')

    page = make_client(tmp_path, google).get("/settings").text

    text = block_text(page)
    assert ("Копия в Google Drive не ушла: сегодня в 11:00 — Google Drive не принял вход — подключите его заново в "
            "Настройках. Удачных ещё не было.") in text
    assert 'href="/settings/google-drive/connect"' in page and 'action="/settings/google-drive/disconnect"' in page


def test_a_press_whose_copy_did_not_go_says_why(tmp_path, google):
    put_token(tmp_path)
    client = make_client(tmp_path, google)  # the fake Google answers a listing without files: an unknown failure

    assert client.post("/settings/backup").status_code == 303

    page = client.get("/settings").text
    assert ("Копия сделана, но в Google Drive не ушла: неизвестная ошибка, подробности в журнале. Попробую снова через "
            "час.") in html.unescape(page)
    assert "Копия в Google Drive не ушла: сегодня в 12:00 — неизвестная ошибка" in block_text(page)
