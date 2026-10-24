"""Source failure notices: why a title could not be checked, and how the message to the owner reads.

Pure functions, no database and no network. Keys, addresses and the text of the exception never reach the message:
the exception is only sorted into a reason (what the owner can do about it); the details stay in the log.
"""

from collections.abc import Sequence
from datetime import timedelta

import httpx

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
    UNKNOWN: "неизвестная ошибка, подробности в журнале",
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


def message_one(title: str, source: str, reason: str, retry: timedelta = RETRY_AFTER_FAILURE) -> str:
    """«⚠️ Не удалось проверить «Дюна»: TMDb не ответил вовремя. Повторю через 30 мин.»"""
    why = _REASONS[reason].format(source=source)
    return f"⚠️ Не удалось проверить «{title}»: {why}. Повторю через {_minutes(retry)} мин."


def _titles_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "тайтл"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "тайтла"
    return "тайтлов"


def message_many(source: str, titles: Sequence[str], retry: timedelta = RETRY_AFTER_FAILURE) -> str:
    """«⚠️ TMDb не отвечает. Не удалось проверить 12 тайтлов: Дюна, Укрытие, … Повторю через 30 мин.»"""
    names = ", ".join(titles[:MAX_NAMES]) + (", …" if len(titles) > MAX_NAMES else ".")
    return (
        f"⚠️ {source} не отвечает. Не удалось проверить {len(titles)} {_titles_word(len(titles))}: {names} "
        f"Повторю через {_minutes(retry)} мин."
    )


# (id, menu label, message text) of the sample events in «Тестовое событие»
TEST_SAMPLES: list[tuple[str, str, str]] = [
    ("failure-one", "Сбой источника: один тайтл", message_one("Дюна", "TMDb", TIMEOUT)),
    (
        "failure-many",
        "Сбой источника: несколько тайтлов",
        message_many("TMDb", ["Дюна", "Укрытие", "Аркейн", "Оппенгеймер", "Барби", "Аватар"]),
    ),
]
