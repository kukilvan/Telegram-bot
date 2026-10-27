"""The web part as ticket 01 leaves it: `/health` only, no self-description, uvicorn writing to the process's log."""

import logging
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.runtime import Health
from app.utils.logging_config import setup_logging
from app.web import create_web_app, web_server

BOT_TOKEN = "123456789:AAH-secretTokenValue_abcdefghijklmnopqrstuv"


def client_of(health: Health) -> TestClient:
    return TestClient(create_web_app(health=health.report))


def running_health() -> Health:
    health = Health()
    health.bot_running = health.scheduler_running = True
    health.scheduler_mark = health.clock()
    return health


def test_health_answers_200_ok_when_the_parts_are_in_order():
    response = client_of(running_health()).get("/health")

    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_health_answers_503_with_the_failed_parts():
    health = running_health()
    health.scheduler_running = False

    response = client_of(health).get("/health")

    assert response.status_code == 503 and response.json() == {"status": "fail", "failed": ["scheduler"]}


def test_health_answers_503_stopping_during_the_stop():
    health = running_health()
    health.stopping = True

    response = client_of(health).get("/health")

    assert response.status_code == 503 and response.json() == {"status": "stopping"}


def test_health_tells_nothing_about_the_app():
    response = client_of(running_health()).get("/health")

    assert set(response.json()) == {"status"}
    assert "server" not in {name.lower() for name in response.headers}


def test_the_api_description_pages_are_not_served():
    client = client_of(running_health())  # no password: closed with 503; the signed-in get 404 (`test_web_login`)

    for address in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(address).status_code != 200, address


def test_the_web_server_has_no_request_log_and_writes_through_the_masking_formatter(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        with patch("app.utils.logging_config.LOG_DIR", tmp_path):
            setup_logging(level="INFO")
        server = web_server(create_web_app(health=Health().report), host="127.0.0.1", port=0, stop_grace=5)

        assert server.config.access_log is False
        assert not logging.getLogger("uvicorn.access").hasHandlers()  # nothing would write `GET /health 200`
        for name in ("uvicorn", "uvicorn.error"):  # no handlers of their own: their records reach ours
            assert logging.getLogger(name).handlers == []
        logging.getLogger("uvicorn.error").error("Exception in ASGI application: token %s", BOT_TOKEN)
        for handler in root.handlers:
            handler.flush()

        text = (tmp_path / "bot.log").read_text(encoding="utf-8")
        assert "Exception in ASGI application" in text and BOT_TOKEN not in text
    finally:
        for handler in root.handlers[:]:
            if handler not in before:
                root.removeHandler(handler)
                handler.close()
