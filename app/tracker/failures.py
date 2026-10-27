"""Source failure notices: why a title could not be checked, and how the message to the owner reads.

Pure functions, no database and no network. Keys, addresses and the text of the exception never reach the message:
the exception is only sorted into a reason (what the owner can do about it); the details stay in the log.
"""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import httpx

from app.tracker.cards import titles_word
from app.tracker.movie_events import RETRY_AFTER_FAILURE

SOURCE_FAILED = "source_failure"  # event type

COOLDOWN = timedelta(hours=24)  # one notice per title in this time, however often its check fails
MAX_NAMES = 5  # titles named in a notice about several; the rest are «…»

TIMEOUT = "timeout"
CONNECTION = "connection"
RATE_LIMIT = "rate_limit"
KEY_REJECTED = "key_rejected"
SOURCE_DOWN = "source_down"
GONE = "gone"
UNKNOWN = "unknown"

_SOURCE_NAMES = (("tmdb", "TMDb"), ("shikimori", "Shikimori"), ("anilist", "AniList"))

# {source} is the name of the source; each reason reads after «Не удалось проверить «…»: »
_REASONS = {
    TIMEOUT: "{source} не ответил вовремя",
    CONNECTION: "не удалось подключиться к {source}",
    RATE_LIMIT: "{source} просит подождать, слишком много запросов",
    KEY_REJECTED: "{source} не принял ключ — проверьте ключ в настройках",
    SOURCE_DOWN: "{source} недоступен — у него сейчас сбой",
    GONE: "{source} больше не знает этого тайтла",
    UNKNOWN: "у {source} неизвестная ошибка, подробности в журнале",
}


class TitleGone(LookupError):
    """The source answered, and it no longer knows the title."""


def source_name(source_key: str) -> str:
    """«tmdb_movie», «tmdb_tv», «tmdb_sequels» → TMDb; «shikimori» → Shikimori; an unknown key stands for itself."""
    for prefix, name in _SOURCE_NAMES:
        if source_key.startswith(prefix):
            return name
    return source_key


def _status(exc: BaseException) -> int | None:
    status = getattr(exc, "status", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)  # httpx.HTTPStatusError
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def reason_of(exc: BaseException) -> str:
    """Sort a failure into one of the reasons above. A source client's own cause (a timeout behind a
    `ShikimoriError`) counts as much as the exception itself."""
    for error in (exc, getattr(exc, "cause", None), exc.__cause__):
        if error is None:
            continue
        if isinstance(error, TitleGone):
            return GONE
        status = _status(error)
        if status == 429:
            return RATE_LIMIT
        if status in (401, 403):
            return KEY_REJECTED
        if status is not None and status >= 500:
            return SOURCE_DOWN
        if isinstance(error, (httpx.TimeoutException, TimeoutError)):
            return TIMEOUT
        if isinstance(error, (httpx.TransportError, OSError)):  # no connection, DNS, reset
            return CONNECTION
    return UNKNOWN


def _minutes(delay: timedelta) -> int:
    return int(delay.total_seconds() // 60)


def message_one(name: str, source: str, reason: str, retry: timedelta = RETRY_AFTER_FAILURE) -> str:
    """«⚠️ Не удалось проверить «Дюна»: TMDb не ответил вовремя. Повторю через 30 мин.»"""
    why = _REASONS[reason].format(source=source)
    return f"⚠️ Не удалось проверить «{name}»: {why}. Повторю через {_minutes(retry)} мин."


def message_many(source: str, reason: str, titles: Sequence[str], retry: timedelta = RETRY_AFTER_FAILURE) -> str:
    """«⚠️ Не удалось проверить 12 тайтлов: TMDb не ответил вовремя. Дюна, Укрытие, … Повторю через 30 мин.»"""
    why = _REASONS[reason].format(source=source)
    names = ", ".join(titles[:MAX_NAMES]) + (", …" if len(titles) > MAX_NAMES else ".")
    return (
        f"⚠️ Не удалось проверить {len(titles)} {titles_word(len(titles))}: {why}. {names} "
        f"Повторю через {_minutes(retry)} мин."
    )


def failure_payload(title_name: str, source: str, reason: str, stamp: str) -> dict[str, Any]:
    """The payload of a «source failure» event of one title. Delivery folds events with the same `source`, `reason`
    and `pass` (the stamp of the pass that found them) into one message."""
    return {
        "text": message_one(title_name, source, reason),
        "source": source,
        "reason": reason,
        "title_name": title_name,
        "pass": stamp,
    }


def foldable(data: dict[str, Any]) -> tuple[str, str, str] | None:
    """(source, reason, pass) of a failure event that may be folded with others; None for a title the source no
    longer knows (it gets its own message with a card button) and for old events that carry no such fields."""
    source, reason, stamp = data.get("source"), data.get("reason"), data.get("pass")
    if not (source and reason and stamp) or reason == GONE or "title_name" not in data:
        return None
    return source, reason, stamp


SAMPLE_TITLES = ["Дюна", "Укрытие", "Аркейн", "Оппенгеймер", "Барби", "Аватар"]


def sample_failure_events() -> list[tuple[str, dict[str, Any]]]:
    """Failures of several titles in one pass as real events (type and payload): delivery folds them into one message."""
    return [(SOURCE_FAILED, failure_payload(name, "TMDb", TIMEOUT, "sample")) for name in SAMPLE_TITLES]


SAMPLE_MANY_ID = "failure-many"
SAMPLE_MANY_LABEL = "Сбой источника: несколько тайтлов"

# (id, menu label, message text) of the sample events in «Тестовое событие»
TEST_SAMPLES: list[tuple[str, str, str]] = [
    ("failure-one", "Сбой источника: один тайтл", message_one("Дюна", "TMDb", TIMEOUT)),
]
