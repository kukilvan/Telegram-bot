"""Normalized domain events produced by comparing old vs new source states."""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DomainEvent:
    """A normalized event detected from state comparison.

    Attributes:
        event_type: stable string name (e.g. DIGITAL_DATE_ANNOUNCED).
        media_item_id: UUID of the MediaItem this applies to.
        source: which provider/source produced it (tmdb, kinopub, ...).
        payload: normalized data relevant to rendering a notification.
    """

    event_type: str
    media_item_id: str | None = None
    source: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        """Stable hash used for deduplication (see sent_notifications)."""
        raw = json.dumps(
            {
                "event_type": self.event_type,
                "media_item_id": self.media_item_id,
                "source": self.source,
            },
            sort_keys=True,
        ).encode()
        return hashlib.sha256(raw).hexdigest()


# Event type constants (stable strings; used in notification_rules + release_events)
DIGITAL_DATE_ANNOUNCED = "DIGITAL_DATE_ANNOUNCED"
DIGITAL_RELEASED = "DIGITAL_RELEASED"
RUSSIAN_AUDIO_AVAILABLE = "RUSSIAN_AUDIO_AVAILABLE"
KINOPUB_AVAILABLE = "KINOPUB_AVAILABLE"
STEAM_STORE_PAGE_AVAILABLE = "STEAM_STORE_PAGE_AVAILABLE"
NEW_EPISODE = "NEW_EPISODE"
RELEASE_DATE_CHANGED = "RELEASE_DATE_CHANGED"
READY_TO_WATCH = "READY_TO_WATCH"


def compare_states(old: dict, new: dict) -> list[DomainEvent]:
    """Compare two normalized states and return detected domain events.

    This is the core of the status engine: notifications are built from these
    events, not directly inside HTTP adapters.
    """
    events = []
    # Digital release date appeared (was unknown/None, now known).
    if old.get("digital_release") is None and new.get("digital_release"):
        events.append(
            DomainEvent(
                event_type=DIGITAL_DATE_ANNOUNCED,
                source="tmdb",
                payload={"date": str(new["digital_release"])},
            )
        )
    # Russian audio track appeared.
    if not old.get("rus_audio") and new.get("rus_audio"):
        events.append(
            DomainEvent(
                event_type=RUSSIAN_AUDIO_AVAILABLE,
                source="kinopub",
                payload={},
            )
        )
    # Steam store page appeared.
    if not old.get("store_page") and new.get("store_page"):
        events.append(
            DomainEvent(
                event_type=STEAM_STORE_PAGE_AVAILABLE,
                source="steam",
                payload={},
            )
        )
    return events
