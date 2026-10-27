"""The line at the top of every page: how many titles are in the list and when the sources were last checked."""

from datetime import datetime

from app.tracker.cards import format_past_moment, titles_word

NO_DATA = "нет данных из базы"


def status_text(title_count: int, last_check_at: datetime | None, now: datetime) -> str:
    """«В списке 12 тайтлов · последняя проверка источников в 14:05». `last_check_at` is aware and on the owner's
    clock (`Tracker.overview`); `now` is any aware moment."""
    if title_count == 0:
        return "В списке пока нет тайтлов"
    count = f"В списке {title_count} {titles_word(title_count)}"
    if last_check_at is None:
        return f"{count} · источники ещё не проверялись"
    when = format_past_moment(last_check_at, now.astimezone(last_check_at.tzinfo))
    return f"{count} · последняя проверка источников {when}"
