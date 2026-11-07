"""A moment in words for the owner (pure): «сегодня в 07:58», «вчера в 18:32», «4 ноября в 07:58», «4 ноября 2025 в 07:58».

One function for everything that names the time of a copy: the Settings block, its notices, the failure text and the
restore list. It lives in a module of its own (rule 7) so that all of them reach it without the database.
"""

from datetime import datetime, timedelta

_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def moment_in_words(moment: datetime, now: datetime) -> str:
    """`moment` (naive, as written) in words, counted against `now`, the owner's wall clock (naive). Today and yesterday
    are named by the day on that clock; another day gives its date, with the year when it is not this year's. The time of
    a copy is read as it stands in its name (the container's clock, KI-66): the zone of the owner changes `now`, not it."""
    today = now.date()
    day = moment.date()
    clock = moment.strftime("%H:%M")
    if day == today:
        return f"сегодня в {clock}"
    if day == today - timedelta(days=1):
        return f"вчера в {clock}"
    year = "" if day.year == today.year else f" {day.year}"
    return f"{day.day} {_MONTHS[day.month - 1]}{year} в {clock}"
