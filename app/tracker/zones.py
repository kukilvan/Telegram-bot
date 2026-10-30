"""The time zones the owner can choose from, and how each one reads in the list.

Pure: no database, no network. The names are read from the system once per process; the offset in a label is worked
out for the moment it is asked for, so a zone with daylight saving shows today's offset.
"""

import functools
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from app.tracker.results import ZoneOption

UTC = "UTC"
MINUS = "−"  # U+2212, as in the scores
_AREAS = frozenset(
    {"Africa", "America", "Antarctica", "Asia", "Atlantic", "Australia", "Europe", "Indian", "Pacific"}
)  # the first part of a name of the list; the old synonyms (`US/Eastern`, `Etc/GMT+3`, `posixrules`) are not in it


@functools.cache
def known_names() -> frozenset[str]:
    """Every name the system knows, the synonyms included: a stored zone is accepted if it is one of them."""
    return frozenset(available_timezones())


@functools.cache
def listed_names() -> tuple[str, ...]:
    """The names of the list, by name."""
    return tuple(sorted(n for n in known_names() if n == UTC or ("/" in n and n.split("/", 1)[0] in _AREAS)))


def offset_text(offset: timedelta) -> str:
    """«UTC+2», «UTC+5:30», «UTC−3»."""
    minutes = round(offset.total_seconds() / 60)
    hours, rest = divmod(abs(minutes), 60)
    sign = "+" if minutes >= 0 else MINUS
    return f"UTC{sign}{hours}" + (f":{rest:02d}" if rest else "")


def label(name: str, now: datetime) -> str:
    """«Asia/Jerusalem (UTC+2)» for the offset at `now` (aware); `UTC` is just «UTC»."""
    if name == UTC:
        return UTC
    try:
        offset = now.astimezone(ZoneInfo(name)).utcoffset()
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return name
    return f"{name} ({offset_text(offset)})" if offset is not None else name


def options(now: datetime, chosen: str | None = None) -> tuple[ZoneOption, ...]:
    """The choices of the list at `now`. A `chosen` zone that is not in the list (a stored one, written by hand) is
    one of the choices, in its place by name: the page must not change it silently."""
    names = listed_names()
    if chosen is not None and chosen not in names:
        names = tuple(sorted((*names, chosen)))
    return tuple(ZoneOption(name, label(name, now)) for name in names)
