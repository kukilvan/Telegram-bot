"""The state of the Google Drive copy's sending (pure): the content of `google_drive_state.json`, its strict reading and what a success or a failure makes of it.

Rules: sections 4.3, 4.5 and 4.6 of the spec of stage 7.1. The file is read and written by `google_drive.DriveFiles`;
this module only turns its JSON object into `DriveState` and back. All times are naive UTC. A field of the wrong kind
makes the whole file spoiled (`ValueError`): the caller treats it as «no attempts yet», with a warning.
"""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from app.tracker.backup_events import SIGN_IN

KEPT_IN_DRIVE = 30  # archives kept in the folder: the newest by the time in their names


@dataclass(frozen=True)
class DriveState:
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_success_name: str | None = None  # the copy of the database that went last, as named on the PC
    kept: int = 0  # the archives in the folder after the last success
    error: str | None = None  # the reason key of the last attempt; None — it went
    failures_in_row: int = 0

    @property
    def failed(self) -> bool:
        return self.error is not None

    def after_success(self, at: datetime, name: str, kept: int) -> "DriveState":
        return DriveState(at, at, name, kept, None, 0)

    def after_failure(self, at: datetime, reason: str) -> "DriveState":
        return replace(self, last_attempt_at=at, error=reason, failures_in_row=self.failures_in_row + 1)

    def waits_for_sign_in(self, connected_at: datetime) -> bool:
        """Google refused the sign-in at the last attempt and the token is the same (connected before that attempt):
        nothing is tried until the owner connects again (spec 4.6)."""
        return self.error == SIGN_IN and self.last_attempt_at is not None and connected_at <= self.last_attempt_at

    def to_json(self) -> dict[str, Any]:
        return {
            "last_attempt_at": _text(self.last_attempt_at),
            "last_success_at": _text(self.last_success_at),
            "last_success_name": self.last_success_name,
            "kept": self.kept,
            "error": self.error,
            "failures_in_row": self.failures_in_row,
        }


def _text(moment: datetime | None) -> str | None:
    return moment.isoformat(timespec="seconds") if moment else None


def _moment(data: dict[str, Any], key: str) -> datetime | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} is not a text")
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is not None:
        raise ValueError(f"{key} is not naive UTC")
    return moment


def _count(data: dict[str, Any], key: str) -> int:
    value = data.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} is not a count")
    return value


def _optional_text(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{key} is not a text")
    return value


def state_of(data: dict[str, Any]) -> DriveState:
    """The state of the file's JSON object; a field of the wrong kind — `ValueError`."""
    return DriveState(
        _moment(data, "last_attempt_at"), _moment(data, "last_success_at"), _optional_text(data, "last_success_name"),
        _count(data, "kept"), _optional_text(data, "error"), _count(data, "failures_in_row"),
    )
