"""Reading a date from text: two readers, and which one to use depends on who wrote the text.

- `parse_response_date`: what a service on the internet sent. It may be garbage, so it is read softly: garbage is
  «no date».
- `parse_date`: what the tracker itself stored (a snapshot, an event). Garbage there is a bug, so it is read strictly
  and raises.

The same two kinds for a moment (naive UTC, as the database keeps it): `response_moment_of_timestamp` and
`parse_moment`. An adapter that must not take garbage for «no moment» (the end of a Steam discount) turns None into
its own failure.

Without a network and without the database; the pure modules of the core import it, which is why it is not in
`context`.
"""

from datetime import date, datetime, timezone
from typing import Any


def parse_response_date(value: Any) -> date | None:
    """A date from a service's answer: its first ten characters («2026-10-24» or «2026-10-24T09:00:00.000Z»).
    Nothing, an empty text or a text that is no date is None. Soft: for what the service sent. For what the tracker
    stored, use `parse_date`, which raises on garbage."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def response_year(value: Any) -> int | None:
    """The year of a date from a service's answer (soft, like `parse_response_date`)."""
    parsed = parse_response_date(value)
    return parsed.year if parsed else None


def response_day_of_timestamp(value: Any) -> date | None:
    """The UTC day of a Unix time from a service's answer (IGDB: `first_release_date`, the `date` of a release).
    Nothing or garbage is None (soft, like `parse_response_date`)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None


def response_moment_of_timestamp(value: Any) -> datetime | None:
    """The moment (naive UTC) of a Unix time from a service's answer (AniList: `airingAt`; Steam: the end of a
    discount). Nothing or garbage is None (soft, like `parse_response_date`)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None


def parse_date(value: str | None) -> date | None:
    """A date the tracker stored (an ISO day): None for nothing, a ValueError for garbage. Strict: for what we wrote
    ourselves, where garbage means a bug. For what a service sent, use `parse_response_date`, which is soft."""
    return date.fromisoformat(value) if value else None


def parse_moment(value: str | None) -> datetime | None:
    """A moment the tracker stored (naive UTC in ISO, «2026-11-03T18:00:00»): None for nothing, a ValueError for garbage
    or for a moment with a time zone. Strict, like `parse_date`."""
    if value is None:
        return None
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is not None:
        raise ValueError(f"a stored moment has a time zone: {value!r}")
    return moment
