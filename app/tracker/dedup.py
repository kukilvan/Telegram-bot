"""Pieces of dedup keys that several kinds of events share. Pure: no database and no network."""

from datetime import datetime


def moved_key(earlier_key: str, previous_look: datetime) -> str:
    """The key of a «date moved» event: the key it had when it held only the new date, and the moment of the previous
    look to the second.

    A move found again after a failed save is seen from the same stored look, so its key repeats and the second message
    is dropped; a new move to a date that was reported before is seen from a later look, so its key is new."""
    return f"{earlier_key}:from:{previous_look.strftime('%Y%m%dT%H%M%S')}"
