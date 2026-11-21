"""Whether a check of a title still runs: the one rule every write of a poll asks before it queues what it found.

A polling pass picks its titles once, at its start; the owner may press «Бросил», «Вернуть в список» or delete a title
before the title's turn (KI-22). So an event of a check, and a «could not check» notice, is queued only if, in the write
session that queues it, the title is still checked by that check. The poll itself never changes the status.
"""

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.tracker.context import PRIMARY_ROLE
from app.tracker.models import ExternalId, SourceSnapshot, Title, TitleStatus

if TYPE_CHECKING:
    from app.tracker.pollers.base import DueTitle

# an own-release check runs for these, while tracking is on
POLLED_STATUSES = (TitleStatus.WANT, TitleStatus.IN_PROGRESS, TitleStatus.WAITING)


def still_checked(session, due: "DueTitle") -> bool:
    """The title exists and the snapshot of `due.snapshot_source` exists; with `due.statuses` the title's status is
    one of them (the Russian checks); a sequel check — the title is «Просмотрено»; an own-release check (the snapshot of
    the title's primary source) — its status is polled and tracking is on; a check at the end of a pass (the Steam
    prices, the follow-ups of a game) — the snapshot is enough."""
    title = session.get(Title, due.id)
    if title is None:
        return False
    snapshot = session.scalar(
        select(SourceSnapshot.id).where(SourceSnapshot.title_id == due.id, SourceSnapshot.source == due.snapshot_source)
    )
    if snapshot is None:
        return False
    if due.statuses is not None and title.status not in due.statuses:
        return False
    if due.sequels:
        return title.status == TitleStatus.WATCHED
    primary = session.scalar(
        select(ExternalId.source).where(ExternalId.title_id == due.id, ExternalId.role == PRIMARY_ROLE)
    )
    if primary == due.snapshot_source:
        return title.status in POLLED_STATUSES and bool(title.tracking_enabled)
    return True
