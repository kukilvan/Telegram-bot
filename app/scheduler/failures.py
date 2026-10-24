"""Owner notices about items whose polling fails (throttled: an outage must not spam the chat)."""

from datetime import datetime, timedelta

from app.scheduler.polling import RETRY_AFTER_FAILURE_SECONDS

NOTICE_COOLDOWN = timedelta(hours=24)


def new_failure_notices(failures: list, told: dict, now: datetime, cooldown: timedelta = NOTICE_COOLDOWN) -> list:
    """Pick the failures worth telling the owner about.

    `failures` is [(item_id, title, source, error_name)]. An item is announced at most once per
    `cooldown`, even if several of its sources failed in the same scan; `told` (item_id -> when)
    is updated in place. Returns [(title, source, error_name)].
    """
    notices = []
    for item_id, title, source, error_name in failures:
        last = told.get(item_id)
        if last is not None and now - last < cooldown:
            continue
        told[item_id] = now
        notices.append((title, source, error_name))
    return notices


def format_failure_notice(title: str, source: str, error_name: str) -> str:
    """Short, secret-free text: details (which may hold URLs) stay in the log."""
    return (
        f"⚠️ Не удалось проверить «{title}» (источник: {source}, {error_name}). "
        f"Повторю через {RETRY_AFTER_FAILURE_SECONDS // 60} мин."
    )
