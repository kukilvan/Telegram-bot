"""AniList adapter for anime: the airing schedule of one source entry (a season, or a part of it).

Pure (answer in, data out) and tested on saved real answers; the network client is `AniListProvider.get_schedules`.

AniList counts the episodes of one entry from 1, as Shikimori does, so the numbers are the entry's own; the core
puts them in the season's numbering. The number of the episode that comes out next minus one is the number of
those already out; a finished entry has all its episodes out. When AniList says neither, the entry has no
schedule here (`released` is None) and what the core already has stands: a gap in the answer is not «nothing is out».
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

FINISHED = "FINISHED"
NOT_YET_RELEASED = "NOT_YET_RELEASED"


@dataclass(frozen=True)
class PartSchedule:
    status: str
    released: int | None  # episodes out; None: AniList does not say
    next_episode: int | None  # the entry's own number of the episode that comes next
    next_at: datetime | None  # naive UTC; None: no moment known


def _moment(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def parse_schedule(raw: dict[str, Any]) -> PartSchedule:
    status = raw.get("status") or ""
    upcoming = raw.get("nextAiringEpisode") or {}
    next_episode = _count(upcoming.get("episode"))
    next_episode = next_episode if next_episode and next_episode >= 1 else None
    next_at = _moment(upcoming.get("airingAt")) if next_episode else None
    total = _count(raw.get("episodes"))

    released: int | None = None
    if next_episode:
        released = next_episode - 1
    elif status == FINISHED and total:
        released = total
    elif status == NOT_YET_RELEASED:
        released = 0
    return PartSchedule(status, released, next_episode, next_at)


def parse_schedules(media: Iterable[dict[str, Any]]) -> dict[str, PartSchedule]:
    """Schedules by AniList id (as text, like every id in the tracker)."""
    return {str(raw["id"]): parse_schedule(raw) for raw in media if raw.get("id")}
