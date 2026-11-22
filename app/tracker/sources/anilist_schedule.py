"""AniList adapter for anime: the airing schedule of one source entry (a season, or a part of it).

Pure (answer in, data out) and tested on saved real answers; the network client is `AniListProvider.get_schedules`.

AniList counts the episodes of one entry from 1, as Shikimori does, so the numbers are the entry's own; the core
puts them in the season's numbering. The number of the episode that comes out next minus one is the number of
those already out; a finished entry has all its episodes out. When AniList says neither, the entry has no
schedule here (`released` is None) and what the core already has stands: a gap in the answer is not «nothing is out».

The record of an entry may also carry the airings of the last 8 days (`recentAirings`, put there by the client from
the second root of its request): the moments at which episodes already out really aired, read strictly into
`PartSchedule.aired`. An entry without them, or with a broken list, has `aired == {}` and its schedule is used as before.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.tracker.sources.dates import response_moment_of_timestamp

FINISHED = "FINISHED"
NOT_YET_RELEASED = "NOT_YET_RELEASED"
RECENT_KEY = "recentAirings"  # where the client puts the airings of the last days in the record of an entry


@dataclass(frozen=True)
class PartSchedule:
    status: str
    released: int | None  # episodes out; None: AniList does not say
    next_episode: int | None  # the entry's own number of the episode that comes next
    next_at: datetime | None  # naive UTC; None: no moment known
    aired: Mapping[int, datetime] = field(default_factory=dict)  # the entry's own number -> the moment it aired (last 8 days)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _count(value: Any) -> int | None:
    return value if _is_int(value) and value >= 0 else None


def _airings(raw: dict[str, Any], total: int | None) -> dict[int, datetime]:
    """The airings of the last days of one entry, read strictly: a node without an `int` `mediaId` of this entry, a
    positive `int` `episode` or an `int` `airingAt` is skipped, so is a number beyond the entry's announced count."""
    nodes = raw.get(RECENT_KEY)
    if not isinstance(nodes, list):
        return {}
    aired: dict[int, datetime] = {}
    for node in nodes:
        if not isinstance(node, dict) or not _is_int(node.get("mediaId")) or node.get("mediaId") != raw.get("id"):
            continue
        episode, at = node.get("episode"), node.get("airingAt")
        if not _is_int(episode) or episode < 1 or not _is_int(at):
            continue
        moment = response_moment_of_timestamp(at)
        if moment is None:
            continue
        if total and episode > total:
            continue
        aired[episode] = moment
    return aired


def parse_schedule(raw: dict[str, Any]) -> PartSchedule:
    status = raw.get("status") or ""
    upcoming = raw.get("nextAiringEpisode") or {}
    next_episode = _count(upcoming.get("episode"))
    next_episode = next_episode if next_episode and next_episode >= 1 else None
    next_at = response_moment_of_timestamp(upcoming.get("airingAt")) if next_episode else None
    total = _count(raw.get("episodes"))

    released: int | None = None
    if next_episode:
        released = next_episode - 1
    elif status == FINISHED and total:
        released = total
    elif status == NOT_YET_RELEASED:
        released = 0
    return PartSchedule(status, released, next_episode, next_at, _airings(raw, total))


def parse_schedules(media: Iterable[dict[str, Any]]) -> dict[str, PartSchedule]:
    """Schedules by AniList id (as text, like every id in the tracker)."""
    return {str(raw["id"]): parse_schedule(raw) for raw in media if raw.get("id")}
