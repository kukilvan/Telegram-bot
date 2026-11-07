"""The block «Копии и выгрузка» of the settings page and «Сделать копию сейчас» (spec 2 of stage 7.1): the lines for each
state of the copies, the notice of every outcome of the press, the page behind the sign-in, a block that fails leaves the
rest of the page. On the real core with a file database in a temporary folder."""

import html
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.runtime import Health
from app.tracker.core import Tracker
from app.tracker.db import create_session_factory
from app.utils import backup
from app.web import create_web_app

PASSWORD = "correct horse battery"
MOSCOW = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 10, 29, 19, 10, tzinfo=timezone.utc)  # Thursday 22:10 in Moscow
WALL = datetime(2026, 10, 29, 22, 10, 5)
SAME_SECOND = "Копия уже делается — подождите несколько секунд."


class FakeSender:
    async def send(self, message, actions=()):
        pass


@pytest.fixture
def folder(tmp_path):
    return tmp_path / "backups"


@pytest.fixture
def tracker(tmp_path):
    url = f"sqlite:///{(tmp_path / 'tracker.db').as_posix()}"
    core = Tracker(create_session_factory(url), clock=lambda: NOW, sender=FakeSender(), default_tz=MOSCOW, database_url=url)
    core._backups.wall_clock = lambda: WALL
    return core


def sign_in(tracker, tmp_path):
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    app = create_web_app(health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker)
    client = TestClient(app, follow_redirects=False)
    assert client.post("/login", data={"password": PASSWORD}).status_code == 303
    return client


@pytest.fixture
def client(tracker, tmp_path):
    return sign_in(tracker, tmp_path)


def put(folder: Path, name: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"copy")


def block_text(page: str) -> str:
    """The text of the block, from its heading to the end of the card."""
    start = page.index("<h2>Копии и выгрузка</h2>")
    return html.unescape(re.sub(r"<[^>]+>", " ", page[start:page.index("</section>", start)]))


def words(text: str) -> str:
    return " ".join(text.split())


def test_the_block_is_the_last_one_on_the_page_under_the_bot_in_telegram(client, folder):
    put(folder, "tracker_db_20261029_075800.db")

    page = client.get("/settings").text

    assert page.index("<h2>Бот в Telegram</h2>") < page.index("<h2>Копии и выгрузка</h2>")
    assert page.index('class="telegram-state"') < page.index('class="backup-line"') < page.index("Сделать копию сейчас")
    assert words(block_text(page)).startswith("Копии и выгрузка Копии базы на этом ПК: 1, последняя — сегодня в 07:58.")
    assert "Копия делается сама раз в сутки и перед каждым обновлением базы" in block_text(page)
    assert ".\\restore-bot.ps1" in block_text(page)


def test_the_block_without_copies(client):
    assert "Копий базы на этом ПК пока нет: первая сделается в течение часа." in block_text(client.get("/settings").text)


def test_the_block_when_the_folder_cannot_be_read_and_the_rest_of_the_page_stays(client, folder):
    put(folder, "tracker_db_20261029_075800.db")

    with patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
        response = client.get("/settings")

    assert response.status_code == 200
    page = response.text
    assert "Копии базы на этом ПК не прочитать — подробности в журнале." in block_text(page)
    assert "Сделать копию сейчас" in page and 'id="timezone"' in page and "Сохранить" in page


def test_the_block_is_not_lost_when_a_form_is_refused(client, folder):
    put(folder, "tracker_db_20261029_075800.db")

    response = client.post("/settings", data={"timezone": "Nowhere/Land", "summary_at": "16:00"})

    assert response.status_code == 400
    assert "Копии базы на этом ПК: 1" in block_text(response.text)


def test_the_press_makes_a_copy_and_the_page_says_so_once(client, folder):
    response = client.post("/settings/backup")

    assert response.status_code == 303 and response.headers["location"] == "/settings"
    page = client.get("/settings").text
    assert "Копия сделана: сегодня в 22:10." in page
    assert "Копии базы на этом ПК: 1, последняя — сегодня в 22:10." in block_text(page)
    assert [p.name for p in folder.iterdir()] == ["tracker_db_20261029_221005_manual.db"]
    assert "Копия сделана" not in client.get("/settings").text  # a notice is shown once


def test_a_press_in_the_same_second_says_it_is_already_working(client, folder):
    client.post("/settings/backup")
    client.get("/settings")

    client.post("/settings/backup")

    assert SAME_SECOND in client.get("/settings").text
    assert len(list(folder.iterdir())) == 1


def test_a_failed_press_says_why_and_the_page_still_opens(client, folder):
    with patch.object(backup, "create_manual_backup", side_effect=sqlite3.OperationalError("boom")):
        assert client.post("/settings/backup").status_code == 303

    page = client.get("/settings")
    assert page.status_code == 200
    assert "Копия не сделана: ошибка, подробности в журнале." in page.text


def test_the_press_is_closed_without_a_sign_in(tracker, tmp_path):
    health = Health()
    app = create_web_app(health=health.report, password=PASSWORD, secret_file=tmp_path / "web_secret", tracker=tracker)
    anonymous = TestClient(app, follow_redirects=False)

    response = anonymous.post("/settings/backup")

    assert response.status_code in (303, 401) and not Path(tmp_path / "backups").exists()
