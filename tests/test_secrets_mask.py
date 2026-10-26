"""Secrets must never reach logs, error reports to Telegram, or the failure dump file."""

import io
import logging
from logging.handlers import RotatingFileHandler
from unittest.mock import patch

from app.bot import error_handler
from app.config import get_settings
from app.utils import secrets_mask
from app.utils.logging_config import MaskingFormatter, setup_logging
from app.utils.secrets_mask import mask_secrets, remember_secrets

TMDB_KEY = "0123456789abcdef0123456789abcdef"
BOT_TOKEN = "123456789:AAH_fake-token_for-tests_0123456789abc"


def test_masks_tmdb_url_as_httpx_logs_it():
    line = f'HTTP Request: GET https://api.themoviedb.org/3/search/movie?api_key={TMDB_KEY}&language=ru&query=witcher "HTTP/1.1 200 OK"'
    out = mask_secrets(line)
    assert TMDB_KEY not in out
    assert "api_key=***" in out
    assert "query=witcher" in out  # the useful part stays readable


def test_masks_telegram_token_in_url_path():
    out = mask_secrets(f"POST https://api.telegram.org/bot{BOT_TOKEN}/sendMessage 400")
    assert BOT_TOKEN not in out and "AAH_fake" not in out
    assert "/sendMessage" in out


def test_masks_bare_telegram_token():
    assert BOT_TOKEN not in mask_secrets(f"token was {BOT_TOKEN} here")


def test_masks_bearer_and_json_tokens():
    assert "abc.def-ghi" not in mask_secrets("Authorization: Bearer abc.def-ghi")
    assert "s3cr3tvalue" not in mask_secrets('{"access_token": "s3cr3tvalue", "expires_in": 3600}')


def test_masks_env_secret_values_even_without_a_pattern(monkeypatch):
    monkeypatch.setenv("SOME_SERVICE_API_KEY", "plain-value-12345")
    remember_secrets()
    out = mask_secrets("failed for plain-value-12345 (retry)")
    assert "plain-value-12345" not in out


def test_leaves_ordinary_text_and_short_env_values_alone(monkeypatch):
    monkeypatch.setenv("MY_TINY_KEY", "abc")  # too short to be treated as a secret
    remember_secrets()
    text = "Steam search 'witcher': got 10 apps abc"
    assert mask_secrets(text) == text


def test_the_first_mask_remembers_the_secrets_when_nobody_did(monkeypatch):
    monkeypatch.setenv("SOME_SERVICE_API_KEY", "plain-value-12345")

    assert "plain-value-12345" not in mask_secrets("failed for plain-value-12345")


def test_the_environment_is_scanned_once_for_many_lines(monkeypatch):
    monkeypatch.setenv("SOME_SERVICE_API_KEY", "plain-value-12345")
    scans = []
    real_scan = secrets_mask._secret_values
    monkeypatch.setattr(secrets_mask, "_secret_values", lambda: scans.append(1) or real_scan())

    for number in range(200):
        assert "plain-value-12345" not in mask_secrets(f"line {number}: plain-value-12345")

    assert len(scans) == 1


def test_the_remembered_secrets_do_not_follow_later_changes_of_the_environment(monkeypatch):
    monkeypatch.setenv("SOME_SERVICE_API_KEY", "plain-value-12345")
    remember_secrets()
    monkeypatch.delenv("SOME_SERVICE_API_KEY")
    monkeypatch.setenv("OTHER_SERVICE_API_KEY", "another-value-67890")

    assert "plain-value-12345" not in mask_secrets("failed for plain-value-12345")
    assert "another-value-67890" in mask_secrets("failed for another-value-67890")  # not remembered: by design


def test_a_token_read_from_dotenv_after_logging_was_set_up_is_masked(monkeypatch):
    def load_dotenv_stub(*args, **kwargs):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "dotenv-only-token-0123456789")
        monkeypatch.setenv("TMDB_API_KEY", "dotenv-only-tmdb-0123456789")

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    monkeypatch.setattr("app.config.load_dotenv", load_dotenv_stub)
    mask_secrets("the logging started: nothing of .env is known yet")  # remembers the environment as it is now

    get_settings()  # reads .env

    out = mask_secrets("GET /bot dotenv-only-token-0123456789 and dotenv-only-tmdb-0123456789")
    assert "dotenv-only" not in out


def _logger_with(formatter):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger = logging.getLogger("test_secrets_mask.logger")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    return logger, stream


def test_formatter_masks_message_and_traceback():
    logger, stream = _logger_with(MaskingFormatter("%(levelname)s %(message)s"))
    try:
        raise RuntimeError(f"GET https://api.themoviedb.org/3/tv/1?api_key={TMDB_KEY} failed")
    except RuntimeError:
        logger.exception("poll failed for %s", f"bot{BOT_TOKEN}")
    text = stream.getvalue()
    assert TMDB_KEY not in text
    assert BOT_TOKEN not in text
    assert "RuntimeError" in text  # the traceback itself is still there


def test_setup_logging_installs_masking_on_console_and_file(tmp_path):
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        with patch("app.utils.logging_config.LOG_DIR", tmp_path):
            setup_logging(level="INFO")
        added = [h for h in root.handlers if h not in before]
        assert len(added) == 2
        assert all(isinstance(h.formatter, MaskingFormatter) for h in added)
        assert any(isinstance(h, RotatingFileHandler) for h in added)
    finally:
        for h in root.handlers[:]:
            if h not in before:
                h.close()
                root.removeHandler(h)


def test_error_report_for_telegram_is_masked():
    exc = RuntimeError(f"GET https://api.themoviedb.org/3/movie/1?api_key={TMDB_KEY}")
    text = error_handler._format_error_for_telegram(exc)
    assert TMDB_KEY not in text


def test_error_dump_file_is_masked(tmp_path):
    dump = tmp_path / "temp_failure.txt"
    exc = RuntimeError(f"POST https://api.telegram.org/bot{BOT_TOKEN}/sendMessage")
    with patch.object(error_handler, "ERROR_LOG_FILE", str(dump)):
        error_handler._save_error_to_file(exc)
    content = dump.read_text(encoding="utf-8")
    assert BOT_TOKEN not in content
    assert "RuntimeError" in content
