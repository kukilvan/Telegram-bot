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
        """Stable hash used for deduplication (see sent_notifications).

        The payload is included so per-season TV events can be re-detected
        (e.g. ALL_EPISODES_OUT for season 1, then again for season 2), while
        identical payloads still dedup to a single notification.
        """
        raw = json.dumps(
            {
                "event_type": self.event_type,
                "media_item_id": self.media_item_id,
                "source": self.source,
                "payload": dict(self.payload),
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
NEW_SEASON_ANNOUNCED = "NEW_SEASON_ANNOUNCED"
ALL_EPISODES_OUT = "ALL_EPISODES_OUT"
NEW_EPISODE = "NEW_EPISODE"
SEASON_PROGRESSED = "SEASON_PROGRESSED"
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
    # TV season tracking (Phase 7).
    old_season = old.get("latest_season")
    new_season = new.get("latest_season")
    if new_season is not None and (old_season is None or new_season > old_season):
        events.append(
            DomainEvent(
                event_type=NEW_SEASON_ANNOUNCED,
                source="tmdb",
                payload={"season": new_season},
            )
        )
    # TV season progressed WITHIN the same season number (episode count or aired
    # changed). Suppressed on a season transition: NEW_SEASON_ANNOUNCED already
    # carries that change, so we do not double-notify.
    if old_season is not None and new_season == old_season and (
        old.get("total_episodes_current_season") != new.get("total_episodes_current_season")
        or old.get("episodes_aired_current_season") != new.get("episodes_aired_current_season")
    ):
        events.append(
            DomainEvent(
                event_type=SEASON_PROGRESSED,
                source="tmdb",
                payload={"season": new_season},
            )
        )
    if (
        new_season is not None
        and new.get("total_episodes_current_season")
        and new.get("episodes_aired_current_season") == new.get("total_episodes_current_season")
        and not (
            old.get("latest_season") == new_season
            and old.get("total_episodes_current_season") == new.get("total_episodes_current_season")
            and old.get("episodes_aired_current_season") == new.get("total_episodes_current_season")
        )
    ):
        events.append(
            DomainEvent(
                event_type=ALL_EPISODES_OUT,
                source="tmdb",
                payload={"season": new_season},
            )
        )
    return events


@dataclass(frozen=True)
class PreAddCheck:
    """Classification of a media item state BEFORE adding it to the watchlist.

    code is one of:
      "released"       - movie/game: known digital release date in the past (out)
      "upcoming"       - movie/game: known digital release date, still in the future
      "season_complete"- TV/anime: all episodes of the latest season are out
                         (covers finished shows too — their final season is aired)
      "airing"         - TV/anime: a season exists but is not fully out yet
      "no_data"        - no relevant TMDb state available yet
    """

    code: str
    date: str | None = None   # known digital release date (movie)
    season: int | None = None  # latest season number (TV/anime)
    aired: int = 0            # episodes of the latest season already out
    total: int = 0            # episodes in the latest season


def pre_add_check(state: dict, media_type: str, today: str) -> PreAddCheck:
    """Pure classification of a normalized TMDb state (no network).

    `today` is an ISO date string 'YYYY-MM-DD' (injected for testability).
    A known digital release date in the PAST means "already released" — the bot
    must ask before tracking; a FUTURE date means upcoming — normal add.
    """
    if media_type in ("tv", "anime"):
        season = state.get("latest_season")
        total = int(state.get("total_episodes_current_season") or 0)
        aired = int(state.get("episodes_aired_current_season") or 0)
        if season is not None and total > 0 and aired >= total:
            return PreAddCheck(code="season_complete", season=season, aired=aired, total=total)
        if season is not None:
            return PreAddCheck(code="airing", season=season, aired=aired, total=total)
        return PreAddCheck(code="no_data")
    release = state.get("digital_release")
    if release:
        day = str(release)[:10]
        code = "released" if day <= today else "upcoming"
        return PreAddCheck(code=code, date=day)
    return PreAddCheck(code="no_data")
