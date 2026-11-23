"""The move of the next episode of a series or an anime between two looks, and the key of its event (pure).

Out of `series_events`, which queues the event. Moments are naive UTC, like everywhere in the tracker.

A move is a change of the moment of the next dated episode of the previous look that is still ahead. A change that only
says more or less about the same day is none (KI-84): a day-only or unknown moment and an exact one on the same day
(both ways), since one of them knows no hour. Both sides on the owner's clock (`Flavor.day`), as the message reads them.
"""

from datetime import datetime

from app.tracker.models import EpisodeTiming
from app.tracker.seasons import Episode, Season
from app.tracker.series_messages import Flavor

_NO_HOUR = (EpisodeTiming.DAY, EpisodeTiming.UNKNOWN)


def moment_key(moment: datetime) -> str:
    """The day for a source that knows only the day (midnight), the day and the minute for one that knows the hour,
    so that a second move of an episode within the same day is a new fact."""
    if moment.time() == datetime.min.time():
        return moment.date().isoformat()
    return moment.strftime("%Y-%m-%dT%H%M")


def same_day_one_without_hour(before: Episode, after: Episode, flavor: Flavor) -> bool:
    """One side knows the hour (exact), the other only the day (a day-only or unknown moment), and the day is the same:
    nothing was moved, whichever side is finer. (An exact moment at 00:00 UTC is a moment: a change of it is a move.)"""
    timings = {before.timing, after.timing}
    if EpisodeTiming.EXACT not in timings or not timings & set(_NO_HOUR):
        return False
    return flavor.day(before) == flavor.day(after)


def _episode(season: Season, number: int) -> Episode | None:
    return next((e for e in season.episodes if e.number == number), None)


def moved(
    old: Season | None, new: Season, observed_at: datetime, now: datetime, flavor: Flavor
) -> tuple[int, Episode, Episode] | None:
    """The next dated episode of the previous look that is still ahead, when its date changed.

    An episode that has come out meanwhile is skipped: it is reported as out, and the move of the one after
    it is still news."""
    if old is None:
        return None
    for before in sorted((e for e in old.episodes if e.air_at is not None and e.air_at > observed_at), key=lambda e: e.number):
        current = _episode(new, before.number)
        if current is None or current.air_at is None or current.air_at <= now:
            continue
        if current.air_at == before.air_at or same_day_one_without_hour(before, current, flavor):
            return None
        return before.number, before, current
    return None
