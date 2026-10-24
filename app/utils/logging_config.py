import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.utils.secrets_mask import mask_secrets

LOG_DIR = Path(__file__).parent.parent / "logs"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5


class MaskingFormatter(logging.Formatter):
    """Formatter that masks secrets in the whole line, tracebacks included.

    Third-party loggers (httpx logs full URLs with api_key=..., aiogram logs tracebacks)
    propagate to the root handlers, so masking at the formatter covers them all.
    """

    def format(self, record: logging.LogRecord) -> str:
        return mask_secrets(super().format(record))


_formatter = MaskingFormatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging with console + rotated file handler."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE = LOG_DIR / "bot.log"

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG)
    console.setFormatter(_formatter)
    root.addHandler(console)

    # File handler with rotation
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_formatter)
    root.addHandler(file_handler)
