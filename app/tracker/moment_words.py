"""Dates and moments in words for the owner (pure): «15 декабря 2026», «пн, 12 окт», «сегодня в 07:58», «вчера в 18:32».

Also «4 ноября в 07:58» and «4 ноября 2025 в 07:58»; the owner's clock of a stored moment (`local_moment`) and the one
rule of how the moment of an episode reads (`episode_when`).

One home for everything that names a day or a time — the cards, the Feed, the messages, the copies of the database and
the last Russian check of a game (rule 7, so all of them reach it without the database).
"""

from datetime import date, datetime, time, timedelta, timezone, tzinfo

from app.tracker.models import EpisodeTiming
from app.tracker.seasons import Episode

_WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")

_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)
_SHORT_MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
NOT_ANNOUNCED = "не объявлена"


def format_date(value: date | None) -> str:
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}" if value else NOT_ANNOUNCED


def format_short_date(value: date) -> str:
    """«15 дек 2026»: the form used when two dates stand side by side."""
    return f"{value.day} {_SHORT_MONTHS[value.month - 1]} {value.year}"


def format_weekday_date(value: date) -> str:
    """«пн, 12 окт»: a near day, as the next episode is announced."""
    return f"{_WEEKDAYS[value.weekday()]}, {value.day} {_SHORT_MONTHS[value.month - 1]}"


def local_moment(moment: datetime, tz: tzinfo | None) -> datetime:
    """A naive UTC moment as the owner's clock shows it (naive); without a time zone it stays as it is."""
    if tz is None:
        return moment
    return moment.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)


def episode_when(episode: Episode, tz: tzinfo | None) -> tuple[date, time | None]:
    """The day and the hour of a dated episode; `tz`: the owner's zone for a kind with local times (anime), else None.
    The hour only for an exact moment with a zone; the day on the owner's clock, but a day-only one as stored."""
    if tz is None or episode.timing == EpisodeTiming.DAY:
        return episode.air_at.date(), None
    local = local_moment(episode.air_at, tz)
    return local.date(), local.time() if episode.timing == EpisodeTiming.EXACT else None


def format_episode_when(episode: Episode, tz: tzinfo | None) -> str:
    """«пн, 12 окт»; with the hour where `episode_when` gives one: «пн, 12 окт в 18:00»."""
    day, hour = episode_when(episode, tz)
    return format_weekday_date(day) + (f" в {hour:%H:%M}" if hour is not None else "")


def format_past_moment(moment: datetime, now: datetime) -> str:
    """When something last happened, on the owner's clock (both moments aware, in the same zone): «в 14:05» today,
    «вчера в 23:10», «26 окт в 09:05» before that, «26 окт 2025 в 09:05» in another year."""
    local = moment.astimezone(now.tzinfo)
    days = (now.date() - local.date()).days
    if days <= 0:
        return f"в {local:%H:%M}"
    if days == 1:
        return f"вчера в {local:%H:%M}"
    day = f"{local.day} {_SHORT_MONTHS[local.month - 1]}"
    return f"{day} {local.year} в {local:%H:%M}" if local.year != now.year else f"{day} в {local:%H:%M}"


def format_day_month(value: date) -> str:
    """«27 марта»: the day a part starts, as the card says «часть 2 — с 27 марта»."""
    return f"{value.day} {_MONTHS[value.month - 1]}"


def moment_in_words(moment: datetime, now: datetime) -> str:
    """`moment` (naive, on the owner's wall clock) in words, counted against `now`, the owner's wall clock (naive). Today and yesterday
    are named by the day on that clock; another day gives its date, with the year when it is not this year's. Both are on
    the same wall clock: a stored moment goes through `local_moment` (a copy's through `DeliveryRules.local`) first."""
    today = now.date()
    day = moment.date()
    clock = moment.strftime("%H:%M")
    if day == today:
        return f"сегодня в {clock}"
    if day == today - timedelta(days=1):
        return f"вчера в {clock}"
    year = "" if day.year == today.year else f" {day.year}"
    return f"{format_day_month(day)}{year} в {clock}"
