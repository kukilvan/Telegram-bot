"""Mask secrets (API keys, tokens) in any text that is about to be logged or sent anywhere."""

import os
import re

MASK = "***"
_SECRET_ENV_NAME = re.compile(r"TOKEN|SECRET|KEY|PASSWORD|PASSWD", re.IGNORECASE)
_MIN_SECRET_LEN = 8  # shorter values would mask ordinary words

_PATTERNS = [
    # Telegram bot token inside a URL path: /bot123456:ABC.../sendMessage
    (re.compile(r"(bot)\d{6,}:[A-Za-z0-9_-]{20,}"), r"\1" + MASK),
    # Telegram bot token anywhere else
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{30,}\b"), MASK),
    # query strings / form bodies: api_key=..., key=..., client_secret=...
    (
        re.compile(
            r"(?i)\b(api_key|apikey|access_token|refresh_token|client_secret|token|secret|password|key)=[^&\s\"'<>]+"
        ),
        r"\1=" + MASK,
    ),
    # JSON bodies: "access_token": "..."
    (
        re.compile(
            r"(?i)(\"(?:api_key|apikey|access_token|refresh_token|client_secret|token|secret|password)\"\s*:\s*\")[^\"]+"
        ),
        r"\1" + MASK,
    ),
    # Authorization: Bearer ...
    (re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1" + MASK),
]


def _secret_values() -> list[str]:
    """Values of secret-looking env vars (longest first, so overlaps are masked whole)."""
    values = {
        v
        for k, v in os.environ.items()
        if _SECRET_ENV_NAME.search(k) and len(v) >= _MIN_SECRET_LEN
    }
    return sorted(values, key=len, reverse=True)


_remembered: list[str] | None = None


def remember_secrets() -> None:
    """Collect the secret values of the environment once; `mask_secrets` uses them until this is called again.
    Call it after the environment changes (`get_settings` does, right after loading `.env`)."""
    global _remembered
    _remembered = _secret_values()


def mask_secrets(text: str) -> str:
    """Replace known secret values and secret-shaped fragments with ***."""
    if _remembered is None:
        remember_secrets()
    for value in _remembered:
        text = text.replace(value, MASK)
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text
