"""Reading a date from text. Two readers, and which one to use depends on who wrote the text.

- `parse_response_date`: what a service on the internet sent. It may be garbage, so it is read softly: garbage is
  «no date».
- `parse_date`: what the tracker itself stored (a snapshot, an event). Garbage there is a bug, so it is read strictly
  and raises.

Without a network and without the database; the pure modules of the core import it, which is why it is not in
`context`.
"""

from datetime import date
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


def parse_date(value: str | None) -> date | None:
    """A date the tracker stored (an ISO day): None for nothing, a ValueError for garbage. Strict: for what we wrote
    ourselves, where garbage means a bug. For what a service sent, use `parse_response_date`, which is soft."""
    return date.fromisoformat(value) if value else None
