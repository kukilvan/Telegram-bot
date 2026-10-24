"""Error reports to the owner: Telegram-safe text and the reason when Telegram rejects a report."""

import asyncio
import logging

from app.bot import error_handler


# ---- error report to the owner ------------------------------------------

def test_error_report_keeps_quotes_unescaped_so_telegram_can_parse_it():
    text = error_handler._format_error_for_telegram(NameError("name 'datetime' is not defined <x> & y"))
    assert "&#x27;" not in text and "'datetime'" in text
    assert "&lt;x&gt;" in text and "&amp;" in text


def test_rejected_error_report_logs_telegram_reason(monkeypatch, caplog):
    class FakeResponse:
        status_code = 400

        def json(self):
            return {"description": "Bad Request: can't parse entities"}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return FakeResponse()

    monkeypatch.setattr(error_handler.httpx, "AsyncClient", FakeClient)
    with caplog.at_level(logging.ERROR):
        ok = asyncio.run(error_handler._send_error_via_http("123456:TOKEN", "1", "text"))
    assert ok is False
    assert "can't parse entities" in caplog.text
