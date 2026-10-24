"""Error reporting to bot owner via Telegram Bot API.

Sends traceback on unhandled exceptions (runtime) and startup crashes.
Uses HTTP requests directly — no bot object needed for startup errors.
Errors are also logged to a temp file for debugging.
"""

import asyncio
import html
import logging
import os
import traceback
from typing import Any

import httpx

from app.config import get_settings
from app.utils.secrets_mask import mask_secrets

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
MAX_ERROR_MSG_SIZE = 3500
ERROR_LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "data", "temp_failure.txt")


def _format_error_for_telegram(exc: Exception) -> str:
    """Format an exception with traceback for Telegram <pre> message.

    - HTML-escapes all special characters
    - Keeps the END of the traceback (most important part)
    - Truncates to ~3500 chars to stay under Telegram's 4096 limit
    """
    tb_text = traceback.format_exception(type(exc), exc, exc.__traceback__)
    full_text = mask_secrets("".join(tb_text))

    # HTML-escape
    escaped = html.escape(full_text)

    # Keep the end (most important part) and truncate
    if len(escaped) > MAX_ERROR_MSG_SIZE:
        escaped = "... (truncated) ...\n" + escaped[-(MAX_ERROR_MSG_SIZE - 20):]

    return escaped


def _save_error_to_file(exc: Exception) -> None:
    """Save full error traceback to a temp file for debugging."""
    try:
        os.makedirs(os.path.dirname(ERROR_LOG_FILE), exist_ok=True)
        tb_text = traceback.format_exception(type(exc), exc, exc.__traceback__)
        with open(ERROR_LOG_FILE, "w", encoding="utf-8") as f:
            f.write(mask_secrets("".join(tb_text)))
    except Exception:
        pass  # Best effort


async def _send_error_via_http(token: str, chat_id: str, text: str) -> bool:
    """Send error message via Telegram Bot API HTTP endpoint.

    Does NOT depend on bot object being initialized.
    Returns True if sent successfully, False otherwise.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                TELEGRAM_API_URL.format(token=token),
                json={
                    "chat_id": chat_id,
                    "text": f"⚠️ <b>Bot Error</b>\n\n<pre>{text}</pre>",
                    "parse_mode": "HTML",
                },
            )
            if resp.status_code == 200:
                return True
            logger.error("Failed to send error to Telegram: HTTP %s", resp.status_code)
            return False
    except Exception as send_err:
        logger.error("Failed to send error to Telegram: %s", send_err)
        return False


def send_startup_error_sync(token: str, chat_id: str, exc: Exception) -> None:
    """Synchronously send startup error via HTTP (blocking, for use in sys.excepthook)."""
    _save_error_to_file(exc)
    text = _format_error_for_telegram(exc)
    try:
        asyncio.run(_send_error_via_http(token, chat_id, text))
    except Exception:
        pass  # Best effort — don't crash


async def send_runtime_error(token: str, chat_id: str, exc: Exception) -> None:
    """Send runtime error via Telegram Bot API."""
    _save_error_to_file(exc)
    text = _format_error_for_telegram(exc)
    try:
        await _send_error_via_http(token, chat_id, text)
    except Exception:
        pass  # Best effort


class ErrorMiddleware:
    """aiogram middleware that catches all unhandled exceptions and reports to owner."""

    def __init__(self) -> None:
        self._settings = get_settings()

    async def __call__(self, handler, event, data):
        try:
            return await handler(event, data)
        except Exception as e:
            token = self._settings.telegram_bot_token
            chat_id = self._settings.owner_chat_id
            if token and chat_id:
                await send_runtime_error(token, chat_id, e)
            # Re-raise so aiogram's default error handling still works
            raise
