"""A release date that may be approximate: a day, a month, a quarter or a year (pure).

`ReleaseDate` is what IGDB says about the release of a game (its `date_format`), as the tracker stores it
(`ReleaseDate.parse`, `.text`), reads it from IGDB (`from_igdb`) and names it («12 марта 2027», «март 2027»,
«4 квартал 2026», «2027», «дата не объявлена»). Only a day is exact; the rest is approximate and gives no messages.
"""

import calendar
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.tracker.moment_words import format_date
from app.tracker.sources.dates import parse_date, response_day_of_timestamp

_MONTHS = (
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
)
NOT_ANNOUNCED_LABEL = "дата не объявлена"

# `date_format` of IGDB: 0 a day, 1 a month, 2 a year, 3–6 the quarters 1–4, 7 «TBD»
_IGDB_DAY, _IGDB_MONTH, _IGDB_YEAR = 0, 1, 2
_IGDB_QUARTERS = range(3, 7)
_IGDB_TBD = 7
_QUARTER_SHIFT = 2  # quarter = format − 2

_MONTH_TEXT = re.compile(r"(\d{4})-(\d{2})")
_QUARTER_TEXT = re.compile(r"(\d{4})-Q([1-4])")
_YEAR_TEXT = re.compile(r"\d{4}")
_DAY_TEXT = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class ReleaseDate:
    """A year and one of: a day, a month, a quarter or nothing (only the year). No year at all — «not announced»."""

    year: int | None = None
    month: int | None = None
    day: int | None = None
    quarter: int | None = None

    @classmethod
    def parse(cls, text: str | None) -> "ReleaseDate":
        """What the tracker stored: «2027-03-12», «2027-03», «2027-Q4», «2027» or None. Strict: garbage raises
        ValueError (rule 9); the day is read by `parse_date`."""
        if text is None:
            return NOT_ANNOUNCED
        if not isinstance(text, str):
            raise ValueError(f"not the text of a game date: {text!r}")
        if match := _QUARTER_TEXT.fullmatch(text):
            return cls(year=int(match[1]), quarter=int(match[2]))
        if match := _MONTH_TEXT.fullmatch(text):
            month = int(match[2])
            if not 1 <= month <= 12:
                raise ValueError(f"no such month: {text!r}")
            return cls(year=int(match[1]), month=month)
        if _YEAR_TEXT.fullmatch(text):
            return cls(year=int(text))
        if not _DAY_TEXT.fullmatch(text):
            raise ValueError(f"not the text of a game date: {text!r}")
        day = parse_date(text)
        return cls(year=day.year, month=day.month, day=day.day)

    @classmethod
    def from_igdb(cls, release: Mapping[str, Any]) -> "ReleaseDate":
        """A record of `release_dates` as IGDB sent it. Soft: garbage is «not announced». `y` and `m` are read, and only
        when they are missing — from `date` (UTC): for a date without a day `date` is not the start of the period (a
        year is its 31 December, a quarter its last day), but its year and the month of a month are right. A record
        whose `date_format` is missing or unknown is a year, never a month or a day (KI-38): in the answers of IGDB a
        year record carries `m: 12`, so `m` cannot tell a month from them."""
        form = release.get("date_format")
        day = response_day_of_timestamp(release.get("date"))
        if form == _IGDB_TBD:
            return NOT_ANNOUNCED
        if form == _IGDB_DAY:
            return cls(year=day.year, month=day.month, day=day.day) if day else NOT_ANNOUNCED
        year = _whole(release.get("y"), 1, 9999) or (day.year if day else None)
        if year is None:
            return NOT_ANNOUNCED
        if form == _IGDB_MONTH:
            month = _whole(release.get("m"), 1, 12) or (day.month if day else None)
            return cls(year=year, month=month) if month else NOT_ANNOUNCED
        if form == _IGDB_YEAR:
            return cls(year=year)
        if form in _IGDB_QUARTERS:
            return cls(year=year, quarter=form - _QUARTER_SHIFT)
        return cls(year=year)  # no `date_format` or one IGDB has not had before: only the year is sure

    @property
    def announced(self) -> bool:
        return self.year is not None

    @property
    def exact(self) -> bool:
        """Only a day is exact; a month, a quarter and a year are an approximate date: seen, but no messages."""
        return self.day is not None

    @property
    def text(self) -> str | None:
        """As the snapshot stores it."""
        if self.year is None:
            return None
        if self.day is not None:
            return date(self.year, self.month, self.day).isoformat()
        if self.month is not None:
            return f"{self.year:04d}-{self.month:02d}"
        if self.quarter is not None:
            return f"{self.year:04d}-Q{self.quarter}"
        return f"{self.year:04d}"

    @property
    def label(self) -> str:
        """«12 марта 2027», «март 2027», «4 квартал 2026», «2027», «дата не объявлена»."""
        if self.year is None:
            return NOT_ANNOUNCED_LABEL
        if self.day is not None:
            return format_date(date(self.year, self.month, self.day))
        if self.month is not None:
            return f"{_MONTHS[self.month - 1]} {self.year}"
        if self.quarter is not None:
            return f"{self.quarter} квартал {self.year}"
        return str(self.year)

    @property
    def start(self) -> date | None:
        """The first day of the period; None — not announced."""
        if self.year is None:
            return None
        if self.day is not None:
            return date(self.year, self.month, self.day)
        if self.month is not None:
            return date(self.year, self.month, 1)
        if self.quarter is not None:
            return date(self.year, 3 * self.quarter - 2, 1)
        return date(self.year, 1, 1)

    @property
    def end(self) -> date | None:
        """The last day of the period; None — not announced."""
        if self.year is None:
            return None
        if self.day is not None:
            return date(self.year, self.month, self.day)
        last_month = self.month or (3 * self.quarter if self.quarter else 12)
        return date(self.year, last_month, calendar.monthrange(self.year, last_month)[1])


NOT_ANNOUNCED = ReleaseDate()


def _whole(value: Any, low: int, high: int) -> int | None:
    """A whole number from a service's answer within its bounds; anything else is None."""
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        return None
    return value
