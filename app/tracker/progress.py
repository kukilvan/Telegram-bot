"""The status a series takes by itself from the owner's season marks and the state of the show.

Pure function, no database and no network; the same rule serves series and anime. Moments are naive UTC.

What counts as «all watched» is every season with a released episode: a season that has not started cannot
be watched yet. A title with no released season (just announced) is left alone, so a new show does not look
«watched» only because there is nothing to watch.

| closed | marked of what is released | status         | followed              |
|--------|----------------------------|----------------|-----------------------|
| no     | all                        | «Жду»          | yes                   |
| no     | part                       | «В процессе»   | yes                   |
| no     | nothing                    | «Хочу»         | yes                   |
| yes    | all                        | «Просмотрено»  | no                    |
| yes    | part                       | «Досмотреть»   | no                    |
| yes    | nothing                    | «Хочу»         | yes (once a week)     |

Closed means ended or cancelled. A closed show the owner has not started stays «Хочу»: «Досмотреть» means started
and not finished, and a show that is still wanted keeps being checked, so a return of the show is not missed.

Only the statuses this rule hands out are rewritten; a status the owner sets by hand (a later ticket) is left as it is.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime

from app.tracker.models import (
    STATUS_IN_PROGRESS,
    STATUS_TO_FINISH,
    STATUS_WAITING,
    STATUS_WANT,
    STATUS_WATCHED,
)
from app.tracker.seasons import Season

AUTOMATIC_STATUSES = frozenset({STATUS_WANT, STATUS_IN_PROGRESS, STATUS_WAITING, STATUS_TO_FINISH, STATUS_WATCHED})


@dataclass(frozen=True)
class SeriesStatus:
    status: str
    tracking: bool  # whether the title's release is still followed


def series_status(
    current: str, seasons: Iterable[Season], watched: Collection[int], closed: bool, now: datetime
) -> SeriesStatus | None:
    """The status the title should have, or None when it should stay as it is."""
    if current not in AUTOMATIC_STATUSES:
        return None
    released = [s.number for s in seasons if s.number >= 1 and s.released(now) > 0]
    if not released:
        return None
    all_watched = all(number in watched for number in released)
    some_watched = any(number in watched for number in released)
    if closed and all_watched:
        return SeriesStatus(STATUS_WATCHED, tracking=False)
    if closed and some_watched:
        return SeriesStatus(STATUS_TO_FINISH, tracking=False)
    if all_watched and not closed:
        return SeriesStatus(STATUS_WAITING, tracking=True)
    if some_watched:
        return SeriesStatus(STATUS_IN_PROGRESS, tracking=True)
    return SeriesStatus(STATUS_WANT, tracking=True)
