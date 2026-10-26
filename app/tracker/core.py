"""Tracker core facade: the only door the bot (and later the web app) uses.

Clock, sender and sources come from outside, so tests can replace all three. An event is marked
delivered only after the sender succeeded, and the dedup key guarantees one event per fact.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.tracker import (
    anime_events,
    delivery,
    failures,
    movie_events,
    progress,
    seasons as season_logic,
    sequel_events,
    series_events,
)
from app.tracker.actions import CARD, FOLLOW, WATCHED, Action, event_actions
from app.tracker.cards import MovieLine, TitleCard
from app.tracker.models import (
    STATUS_IN_PROGRESS,
    STATUS_WAITING,
    STATUS_WANT,
    STATUS_WATCHED,
    DeliveryItem,
    EpisodeRecord,
    Event,
    ExternalId,
    MovieRecord,
    PartRecord,
    SeasonRecord,
    SettingRecord,
    SourceSnapshot,
    Title,
)
from app.utils.secrets_mask import mask_secrets

Clock = Callable[[], datetime]  # returns an aware datetime

PRIMARY_ROLE = "primary"

SEASONAL_KINDS = ("series", "anime")  # titles whose status follows the owner's season marks
POLLED_STATUSES = (STATUS_WANT, STATUS_IN_PROGRESS, STATUS_WAITING)  # an own-release check runs for these, while tracking is on

PART_GAP_SETTING = "part_gap_weeks"
DEFAULT_PART_GAP_WEEKS = season_logic.DEFAULT_PART_GAP // timedelta(weeks=1)  # the default lives in `seasons`

# settings of the delivery rules (absent: the default of `delivery`; the time zone falls back to the one the core was given)
TIMEZONE_SETTING = "timezone"
WORKDAYS_SETTING = "workdays"  # weekday numbers, Monday is 0
DIGEST_AT_SETTING = "digest_at"  # "15:00"
QUIET_FROM_SETTING = "quiet_from"
QUIET_UNTIL_SETTING = "quiet_until"

MAX_DIGEST_BUTTONS = 10  # buttons of the events inside a summary; «Следить» is shown whatever the limit
BUTTON_NAME_LIMIT = 30


class Sender(Protocol):
    async def send(self, message: str, actions: Sequence[Action] = ()) -> None:
        """Deliver one message to the owner, with `actions` as buttons under it; raise on failure."""


class TitleNotFound(Exception):
    """The source has nothing at the chosen id (for example a series id picked as a movie)."""


class UnknownTitle(Exception):
    """There is no title with this id in the list."""


class UnknownEvent(Exception):
    """There is no «sequel announced» event with this id."""


class UnknownKind(Exception):
    """Sequels are not announced for this kind of title, so there is nothing to follow."""


class UnknownSeason(Exception):
    """The title has no season with this number (specials, season 0, are not seasons)."""


@dataclass(frozen=True)
class AddResult:
    title_id: int
    created: bool  # False: the title was already in the list and is simply opened


@dataclass(frozen=True)
class WatchedResult:
    changed: bool  # False: the movie was already watched


@dataclass(frozen=True)
class DeleteResult:
    name: str  # the title that was removed, for the message to the owner


@dataclass(frozen=True)
class TitleSummary:
    """One row of the list."""

    id: int
    kind: str
    name: str
    year: int | None
    status: str


@dataclass(frozen=True)
class WatchableSeason:
    """A season the owner can mark as watched: it has at least one released episode."""

    number: int
    watched: bool


@dataclass(frozen=True)
class TestEventKind:
    """One entry of the "Тестовое событие" menu. Later tickets register their own kinds."""

    __test__ = False  # not a pytest test class

    id: str
    label: str
    build: Callable[[], dict[str, Any]]  # payload of the sample event; must contain "text"
    # several events instead of one (event type and payload each); the summary folds them like real ones
    events: Callable[[], list[tuple[str, dict[str, Any]]]] | None = None


@dataclass(frozen=True)
class TestEventResult:
    __test__ = False

    delivered: bool  # every event of the sample reached the owner
    delivered_at_once: bool = False  # ... at the moment it was queued (false when the rules made it wait)
    held_until: datetime | None = None  # aware UTC; set when the rules made the sample wait for this moment


@dataclass(frozen=True)
class DigestResult:
    """«Сводка сейчас»: how many events were waiting and whether the summary went out."""

    events: int
    delivered: bool


@dataclass
class DeliveryReport:
    delivered: int = 0
    failed: int = 0


@dataclass
class PollReport:
    polled: int = 0
    failed: int = 0
    events: int = 0  # new events found (already queued for delivery)
    notices: int = 0  # «could not check» messages queued for the owner


@dataclass(frozen=True)
class _DueTitle:
    id: int
    kind: str
    name: str
    external_id: str
    snapshot_source: str  # which of the title's snapshots is due: its release source or its sequel source
    sequels: bool  # True: an archived movie, checked only for sequels


def _ping_payload() -> dict[str, Any]:
    return {"text": "если вы это видите, доставка работает."}


def format_event(event: Event) -> str:
    """Text of the message the owner receives for an event."""
    if event.type == "test":
        return f"🧪 {event.payload['text']}"
    return event.payload.get("text", event.type)


def _naive_utc(moment: datetime) -> datetime:
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


@dataclass
class Tracker:
    session_factory: sessionmaker
    clock: Clock
    sender: Sender
    sources: Mapping[str, Any] = field(default_factory=dict)
    sequel_sources: Mapping[str, Any] = field(default_factory=dict)  # by kind: where an archived title's sequels come from
    default_tz: tzinfo = timezone.utc  # the time zone when the owner has set none (BOT_TIMEZONE); the set one is read from the database
    _kinds: dict[str, TestEventKind] = field(init=False, default_factory=dict)
    _delivery_lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
    _poll_lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
    _write_lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)  # one «add» writes at a time

    def __post_init__(self) -> None:
        self.register_test_event_kind(TestEventKind("ping", "Проверка связи", _ping_payload))
        samples = (
            movie_events.TEST_SAMPLES
            + sequel_events.TEST_SAMPLES
            + series_events.TEST_SAMPLES
            + anime_events.TEST_SAMPLES
            + failures.TEST_SAMPLES
        )
        for kind_id, label, text in samples:
            self.register_test_event_kind(TestEventKind(kind_id, label, lambda text=text: {"text": text}))
        self.register_test_event_kind(
            TestEventKind(
                failures.SAMPLE_MANY_ID,
                failures.SAMPLE_MANY_LABEL,
                lambda: failures.sample_failure_events()[0][1],
                failures.sample_failure_events,
            )
        )
        self.register_test_event_kind(
            TestEventKind(
                series_events.SAMPLE_EPISODES_ID,
                series_events.SAMPLE_EPISODES_LABEL,
                lambda: series_events.sample_episode_events()[0][1],
                series_events.sample_episode_events,
            )
        )

    # --- events ---------------------------------------------------------------------------------

    async def record_event(
        self,
        type: str,
        payload: dict[str, Any],
        dedup_key: str,
        title_id: int | None = None,
        at: datetime | None = None,
    ) -> int | None:
        """Store an event and queue it for delivery. Returns its id, or None if this fact is already known.
        `at` stands in for the moment of detection (a test event with a substituted time). An event of a title that is
        no longer in the list (deleted while the poll was under way) is dropped."""
        return await asyncio.to_thread(self._record_event, type, payload, dedup_key, title_id, at)

    def _record_event(
        self,
        type: str,
        payload: dict[str, Any],
        dedup_key: str,
        title_id: int | None = None,
        at: datetime | None = None,
    ) -> int | None:
        now = _naive_utc(at or self.clock())
        with self.session_factory() as session:
            event_id = self._enqueue_event(session, type, payload, dedup_key, title_id, now)
            if event_id is not None:
                session.commit()
            return event_id

    @staticmethod
    def _enqueue_event(
        session, type: str, payload: dict[str, Any], dedup_key: str, title_id: int | None, now: datetime
    ) -> int | None:
        """Add an event and its delivery-queue entry (status «pending») to the session; the caller commits. None, with
        the session rolled back, if the fact is already known or its title is gone."""
        event = Event(type=type, title_id=title_id, payload=payload, dedup_key=dedup_key, detected_at=now)
        session.add(event)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            return None
        # the flush holds the write lock, so the title cannot be deleted between this check and the commit
        if title_id is not None and session.get(Title, title_id) is None:
            session.rollback()
            return None
        session.add(DeliveryItem(event_id=event.id, status="pending", attempts=0, created_at=now))
        return event.id

    # --- settings -------------------------------------------------------------------------------

    async def part_gap_weeks(self) -> int:
        """Weeks of break between two episodes of a season after which the season is split into parts."""
        return await asyncio.to_thread(self._load_part_gap_weeks)

    def _load_part_gap_weeks(self) -> int:
        with self.session_factory() as session:
            return self._part_gap_weeks(session)

    @staticmethod
    def _part_gap_weeks(session) -> int:
        record = session.get(SettingRecord, PART_GAP_SETTING)
        return record.value if record is not None else DEFAULT_PART_GAP_WEEKS

    @classmethod
    def _part_gap(cls, session) -> timedelta:
        return timedelta(weeks=cls._part_gap_weeks(session))

    async def set_part_gap_weeks(self, weeks: int) -> None:
        """Change the break that splits a season into parts. Parts are worked out from the dates, so the new
        value applies to cards and events from now on without touching the stored episodes."""
        if weeks < 1:
            raise ValueError("the break between parts is at least one week")
        async with self._write_lock:
            await asyncio.to_thread(self._set_part_gap_weeks, weeks)

    def _set_part_gap_weeks(self, weeks: int) -> None:
        self._store_settings({PART_GAP_SETTING: weeks})

    async def delivery_rules(self) -> delivery.DeliveryRules:
        """The owner's time zone, working days, summary hour and quiet hours; what is not set is the default."""
        return await asyncio.to_thread(self._load_delivery_rules)

    def _load_delivery_rules(self) -> delivery.DeliveryRules:
        with self.session_factory() as session:
            return self._delivery_rules(session)

    def _time_zone(self, session) -> tzinfo:
        """The owner's time zone: the stored setting, else the one the core was given. Read where it is needed, so a
        change applies at once."""
        record = session.get(SettingRecord, TIMEZONE_SETTING)
        return ZoneInfo(record.value) if record is not None else self.default_tz

    def _delivery_rules(self, session) -> delivery.DeliveryRules:
        keys = (WORKDAYS_SETTING, DIGEST_AT_SETTING, QUIET_FROM_SETTING, QUIET_UNTIL_SETTING)
        stored = {r.key: r.value for r in session.scalars(select(SettingRecord).where(SettingRecord.key.in_(keys)))}
        tz = self._time_zone(session)
        workdays = stored.get(WORKDAYS_SETTING, delivery.DEFAULT_WORKDAYS)
        return delivery.DeliveryRules(
            tz=tz,
            workdays=frozenset(workdays),
            digest_at=delivery.parse_time(stored.get(DIGEST_AT_SETTING, delivery.DEFAULT_DIGEST_AT)),
            quiet_from=delivery.parse_time(stored.get(QUIET_FROM_SETTING, delivery.DEFAULT_QUIET_FROM)),
            quiet_until=delivery.parse_time(stored.get(QUIET_UNTIL_SETTING, delivery.DEFAULT_QUIET_UNTIL)),
        )

    async def set_delivery_rules(
        self,
        *,
        tz_name: str | None = None,
        workdays: Sequence[int] | None = None,
        digest_at: time | str | None = None,
        quiet_from: time | str | None = None,
        quiet_until: time | str | None = None,
    ) -> None:
        """Change the given rules (the others stay). Nothing is stored when any value is wrong.

        `workdays` are weekday numbers, Monday is 0; none at all is allowed (every day is a day off). Equal
        `quiet_from` and `quiet_until` mean no quiet hours. The new rules apply to what is already queued."""
        new: dict[str, Any] = {}
        if tz_name is not None:
            try:
                ZoneInfo(tz_name)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError(f"unknown time zone {tz_name!r}") from exc
            new[TIMEZONE_SETTING] = tz_name
        if workdays is not None:
            days = sorted(set(workdays))
            if any(not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in days):
                raise ValueError("working days are weekday numbers from 0 (Monday) to 6 (Sunday)")
            new[WORKDAYS_SETTING] = days
        for key, value in (
            (DIGEST_AT_SETTING, digest_at), (QUIET_FROM_SETTING, quiet_from), (QUIET_UNTIL_SETTING, quiet_until)
        ):
            if value is not None:
                new[key] = delivery.format_time(delivery.parse_time(value))
        async with self._write_lock:
            await asyncio.to_thread(self._store_settings, new)

    def _store_settings(self, values: dict[str, Any]) -> None:
        with self.session_factory() as session:
            for key, value in values.items():
                record = session.get(SettingRecord, key)
                if record is None:
                    session.add(SettingRecord(key=key, value=value))
                else:
                    record.value = value
            session.commit()

    # --- titles ---------------------------------------------------------------------------------

    async def search(self, kind: str, query: str) -> list[Any]:
        """Suggestions for `query` from the source of this kind. Raises KeyError for an unknown kind."""
        return await self.sources[kind].suggest(query)

    async def add_title(self, kind: str, external_id: str) -> AddResult:
        """Put a search result into the list with status «Хочу», or open the title that is already there."""
        source = self.sources[kind]
        existing = await asyncio.to_thread(self._find_title_id, source.source_key, external_id)
        if existing is not None:
            return AddResult(existing, created=False)
        snapshot = await source.snapshot(external_id)
        if snapshot is None:
            raise TitleNotFound(f"{source.source_key}:{external_id}")
        if snapshot.external_id != external_id:  # the source named the title by another entry (any entry of an anime franchise)
            existing = await asyncio.to_thread(self._find_title_id, source.source_key, snapshot.external_id)
            if existing is not None:
                return AddResult(existing, created=False)
        async with self._write_lock:
            return await asyncio.to_thread(self._store_title, kind, source.source_key, snapshot)

    def _find_title_id(self, source_key: str, external_id: str) -> int | None:
        with self.session_factory() as session:
            return session.scalar(
                select(ExternalId.title_id).where(
                    ExternalId.source == source_key,
                    ExternalId.external_id == external_id,
                    ExternalId.role == PRIMARY_ROLE,
                )
            )

    def _store_title(self, kind: str, source_key: str, snapshot: Any) -> AddResult:
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            title = Title(
                kind=kind,
                title=snapshot.title,
                original_title=snapshot.original_title,
                year=snapshot.year,
                genres=list(snapshot.genres),
                poster_path=snapshot.poster_path,
                overview=snapshot.overview,
                status=STATUS_WANT,
                tracking_enabled=True,
                added_at=now,
                status_changed_at=now,
            )
            session.add(title)
            session.flush()
            session.add(
                ExternalId(title_id=title.id, source=source_key, external_id=snapshot.external_id, role=PRIMARY_ROLE)
            )
            state = snapshot.state()
            seasons = self._first_seasons(kind, snapshot, now)
            session.add(
                SourceSnapshot(
                    title_id=title.id,
                    source=source_key,
                    state=state,
                    observed_at=now,
                    # the snapshot taken now is the baseline; the first poll compares against it
                    next_check_at=self._first_check(kind, seasons, state, now),
                )
            )
            records = self._store_seasons(session, title.id, seasons)
            self._store_anime_entries(session, title.id, records, snapshot)
            self._refresh_status(session, title)
            try:
                session.commit()
            except IntegrityError:
                # the same movie was added by a second request while this one was waiting for the source
                session.rollback()
                existing = self._find_title_id(source_key, snapshot.external_id)
                if existing is None:
                    raise
                return AddResult(existing, created=False)
            return AddResult(title.id, created=True)

    @staticmethod
    def _first_seasons(kind: str, snapshot: Any, now: datetime) -> Sequence[season_logic.Season]:
        """The seasons to store with a new title; an anime's episodes are put together from both its sources."""
        if kind == "anime":
            return anime_events.assemble(snapshot.seasons, snapshot.parts, snapshot.schedules, None, now)
        return getattr(snapshot, "seasons", ())

    @staticmethod
    def _first_check(
        kind: str, seasons: Sequence[season_logic.Season], state: dict[str, Any], now: datetime
    ) -> datetime | None:
        if kind == "movie":
            return now + movie_events.check_interval_for_state(state, now.date())
        if kind in SEASONAL_KINDS:
            return now + series_events.check_interval(series_events.ShowState.of(seasons, state), now)
        return None

    @staticmethod
    def _store_seasons(session, title_id: int, seasons: Sequence[season_logic.Season]) -> dict[int, SeasonRecord]:
        records = {}
        for season in seasons:
            if season.number < 1:  # specials are not seasons, whatever the source adapter let through
                continue
            record = SeasonRecord(
                title_id=title_id, number=season.number, name=season.name, episode_count=season.expected, watched=False
            )
            session.add(record)
            session.flush()
            session.add_all(
                EpisodeRecord(season_id=record.id, number=e.number, air_at=e.air_at) for e in season.episodes
            )
            records[season.number] = record
        return records

    @staticmethod
    def _store_anime_entries(session, title_id: int, records: dict[int, SeasonRecord], snapshot: Any) -> None:
        """The source entries behind an anime's seasons (one per part, with their ids) and its franchise movies."""
        for part in getattr(snapshot, "parts", ()):
            record = records.get(part.season)
            if record is None:
                continue
            session.add(
                PartRecord(
                    title_id=title_id, season_id=record.id, number=part.number, first_episode=part.first_episode,
                    episode_count=part.episode_count, shikimori_id=part.ids.shikimori, mal_id=part.ids.mal,
                    anilist_id=part.ids.anilist,
                )
            )
        for movie in getattr(snapshot, "movies", ()):
            session.add(
                MovieRecord(
                    title_id=title_id, name=movie.name, aired_on=movie.aired_on, released=movie.released,
                    shikimori_id=movie.ids.shikimori, mal_id=movie.ids.mal, anilist_id=movie.ids.anilist,
                )
            )

    @staticmethod
    def _load_seasons(session, title_id: int) -> list[tuple[SeasonRecord, season_logic.Season]]:
        records = session.scalars(select(SeasonRecord).where(SeasonRecord.title_id == title_id).order_by(SeasonRecord.number))
        loaded = []
        for record in records:
            episodes = session.scalars(select(EpisodeRecord).where(EpisodeRecord.season_id == record.id))
            parts = session.scalars(
                select(PartRecord).where(PartRecord.season_id == record.id).order_by(PartRecord.number)
            ).all()
            season = season_logic.Season(
                number=record.number,
                name=record.name,
                expected=record.episode_count,
                episodes=tuple(sorted((season_logic.Episode(e.number, e.air_at) for e in episodes), key=lambda e: e.number)),
                cuts=tuple(season_logic.PartCut(p.first_episode, p.episode_count) for p in parts),
            )
            loaded.append((record, season))
        return loaded

    async def watchable_seasons(self, title_id: int) -> list[WatchableSeason]:
        """Seasons that can be marked as watched, with their marks. A season with nothing released cannot."""
        return await asyncio.to_thread(self._watchable_seasons, title_id)

    def _watchable_seasons(self, title_id: int) -> list[WatchableSeason]:
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            return [
                WatchableSeason(season.number, record.watched)
                for record, season in self._load_seasons(session, title_id)
                if season.released(now) > 0
            ]

    async def set_season_watched(self, title_id: int, number: int, watched: bool) -> None:
        """Mark a season as watched, or take the mark off. Marking twice changes nothing."""
        async with self._write_lock:
            await asyncio.to_thread(self._set_season_watched, title_id, number, watched)

    def _set_season_watched(self, title_id: int, number: int, watched: bool) -> None:
        with self.session_factory() as session:
            if session.get(Title, title_id) is None:
                raise UnknownTitle(title_id)
            record = session.scalar(
                select(SeasonRecord).where(SeasonRecord.title_id == title_id, SeasonRecord.number == number)
            )
            if record is None:
                raise UnknownSeason(f"{title_id}:{number}")
            record.watched = watched
            self._refresh_status(session, session.get(Title, title_id))
            session.commit()

    def _refresh_status(self, session, title: Title) -> None:
        """Give a series the status that follows from its season marks and the state of the show."""
        if title.kind not in SEASONAL_KINDS:
            return
        now = _naive_utc(self.clock())
        loaded = self._load_seasons(session, title.id)
        outcome = progress.series_status(
            title.status,
            (season for _, season in loaded),
            {record.number for record, _ in loaded if record.watched},
            series_events.is_closed(self._own_state(session, title.id).get("show_status")),
            now,
        )
        if outcome is None:
            return
        if outcome.status != title.status:
            title.status = outcome.status
            title.status_changed_at = now
        title.tracking_enabled = outcome.tracking

    @staticmethod
    def _own_state(session, title_id: int) -> dict[str, Any]:
        """State from the title's own source (the archive's sequel snapshot holds no dates)."""
        snapshot = session.scalar(
            select(SourceSnapshot)
            .join(ExternalId, ExternalId.title_id == SourceSnapshot.title_id)
            .where(
                SourceSnapshot.title_id == title_id,
                ExternalId.role == PRIMARY_ROLE,
                SourceSnapshot.source == ExternalId.source,
            )
        )
        return snapshot.state if snapshot else {}

    async def mark_watched(self, title_id: int) -> WatchedResult:
        """«Посмотрел»: the movie gets «Просмотрено» and moves to the archive, where only its sequels are watched."""
        async with self._write_lock:
            return await asyncio.to_thread(self._set_watched, title_id)

    def _set_watched(self, title_id: int) -> WatchedResult:
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            title = session.get(Title, title_id)
            if title is None:
                raise UnknownTitle(title_id)
            if title.status == STATUS_WATCHED:
                return WatchedResult(changed=False)
            title.status = STATUS_WATCHED
            title.status_changed_at = now
            title.tracking_enabled = False  # its own release is no longer followed
            sequel_source = self.sequel_sources.get(title.kind)
            if sequel_source is not None:
                # an empty state means "not looked at yet": the first check records the collection as it is,
                # so sequels that already exist are not announced as news
                session.add(
                    SourceSnapshot(
                        title_id=title.id, source=sequel_source.source_key, state={}, observed_at=now, next_check_at=now
                    )
                )
            session.commit()
            return WatchedResult(changed=True)

    async def delete_title(self, title_id: int) -> DeleteResult:
        """Remove a title and everything that belongs to it, in one transaction: all of it or nothing."""
        async with self._write_lock:
            return await asyncio.to_thread(self._delete_title, title_id)

    def _delete_title(self, title_id: int) -> DeleteResult:
        with self.session_factory() as session:
            name = session.scalar(select(Title.title).where(Title.id == title_id))
            if name is None:
                raise UnknownTitle(title_id)
            # the database cascades: seasons, ids, snapshots, events, and the queue entries of those events
            removed = session.execute(delete(Title).where(Title.id == title_id)).rowcount
            if not removed:  # deleted by someone else since the name was read
                session.rollback()
                raise UnknownTitle(title_id)
            session.commit()
            return DeleteResult(name)

    async def follow_sequel_of(self, kind: str, sequel_id: str) -> AddResult:
        """«Следить» under a sequel announcement: the sequel joins the list as «Хочу». Pressing twice opens it.
        The button names the sequel, so it works even when the announcement or its film is gone."""
        if kind not in self.sequel_sources:
            raise UnknownKind(kind)
        return await self.add_title(kind, sequel_id)

    async def follow_sequel(self, event_id: int) -> AddResult:
        """The same for an old button, which holds only the number of the announcement: works while the event exists."""
        kind, sequel_id = await asyncio.to_thread(self._announced_sequel, event_id)
        return await self.follow_sequel_of(kind, sequel_id)

    def _announced_sequel(self, event_id: int) -> tuple[str, str]:
        with self.session_factory() as session:
            event = session.get(Event, event_id)
            if event is None or event.type != sequel_events.SEQUEL_ANNOUNCED:
                raise UnknownEvent(event_id)
            return event.payload["kind"], event.payload["sequel_id"]

    async def list_titles(self) -> list[TitleSummary]:
        return await asyncio.to_thread(self._list_titles)

    def _list_titles(self) -> list[TitleSummary]:
        with self.session_factory() as session:
            rows = session.scalars(select(Title).order_by(Title.id))
            return [TitleSummary(t.id, t.kind, t.title, t.year, t.status) for t in rows]

    async def title_card(self, title_id: int) -> TitleCard | None:
        return await asyncio.to_thread(self._title_card, title_id)

    def _title_card(self, title_id: int) -> TitleCard | None:
        with self.session_factory() as session:
            title = session.get(Title, title_id)
            if title is None:
                return None
            state = self._own_state(session, title_id)
            seasons_view = None
            if title.kind in SEASONAL_KINDS:
                loaded = self._load_seasons(session, title_id)
                seasons_view = season_logic.summarize(
                    (season for _, season in loaded),
                    {record.number for record, _ in loaded if record.watched},
                    _naive_utc(self.clock()),
                    self._part_gap(session),
                )
            movies = session.scalars(
                select(MovieRecord).where(MovieRecord.title_id == title_id).order_by(MovieRecord.id)
            )
            return TitleCard(
                id=title.id,
                kind=title.kind,
                title=title.title,
                original_title=title.original_title,
                year=title.year,
                genres=list(title.genres),
                status=title.status,
                theatrical_date=_parse_date(state.get("theatrical_date")),
                digital_date=_parse_date(state.get("digital_date")),
                seasons=seasons_view,
                franchise_movies=tuple(MovieLine(m.name, m.aired_on, m.released) for m in movies),
                tz=self._time_zone(session) if title.kind == "anime" else None,
            )

    # --- polling --------------------------------------------------------------------------------

    async def poll_due(self) -> PollReport:
        """Look at every title whose check time has come and queue the events found.

        A failing source postpones only its own title; the others are still polled. Database work runs
        in a worker thread, so a slow disk never freezes the bot.
        """
        report = PollReport()
        broken: list[tuple[_DueTitle, Exception]] = []
        async with self._poll_lock:
            for due in await asyncio.to_thread(self._due_titles):
                await self._poll_one(due, report, broken)
            if broken:
                await self._tell_owner_about(broken, report)
        return report

    def _due_titles(self) -> list[_DueTitle]:
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            # a title's own source is the one of its primary id; any other snapshot is its sequel check
            own = SourceSnapshot.source == ExternalId.source
            rows = session.execute(
                select(Title.id, Title.kind, Title.title, ExternalId.external_id, SourceSnapshot.source, ~own)
                .join(SourceSnapshot, SourceSnapshot.title_id == Title.id)
                .join(
                    ExternalId,
                    (ExternalId.title_id == Title.id) & (ExternalId.role == PRIMARY_ROLE),
                )
                .where(
                    or_(
                        and_(
                            own,
                            Title.kind.in_(("movie", *SEASONAL_KINDS)),
                            Title.status.in_(POLLED_STATUSES),
                            Title.tracking_enabled.is_(True),
                        ),
                        and_(~own, Title.status == STATUS_WATCHED),
                    ),
                    (SourceSnapshot.next_check_at.is_(None)) | (SourceSnapshot.next_check_at <= now),
                )
                .order_by(Title.id)
            )
            return [_DueTitle(*row) for row in rows]

    async def _poll_one(self, due: _DueTitle, report: PollReport, broken: list[tuple[_DueTitle, Exception]]) -> None:
        try:
            source = (self.sequel_sources if due.sequels else self.sources)[due.kind]
            snapshot = await source.snapshot(due.external_id)
            if snapshot is None:
                raise failures.TitleGone(f"{due.kind}:{due.external_id} is no longer known to the source")
            apply = self._apply_sequels if due.sequels else self._applier(due.kind)
            found = await asyncio.to_thread(apply, due, snapshot)
        except Exception as exc:  # one broken title or source must not stop the pass
            if not await asyncio.to_thread(self._title_exists, due.id):
                logging.info("title %s was deleted while it was polled", due.id)  # nothing broke: it is simply gone
                return
            logging.warning("polling title %s failed: %s", due.id, mask_secrets(repr(exc)))
            report.failed += 1
            broken.append((due, exc))
            try:
                await asyncio.to_thread(self._postpone, due, movie_events.RETRY_AFTER_FAILURE)
            except Exception as postpone_exc:  # even a failed postponement leaves the other titles to the pass
                logging.warning("postponing title %s failed: %s", due.id, mask_secrets(repr(postpone_exc)))
            return
        report.polled += 1
        report.events += found

    def _title_exists(self, title_id: int) -> bool:
        with self.session_factory() as session:
            return session.get(Title, title_id) is not None

    async def _tell_owner_about(self, broken: list[tuple[_DueTitle, Exception]], report: PollReport) -> None:
        try:
            report.notices = await asyncio.to_thread(self._queue_failure_notices, broken)
        except Exception as exc:  # a notice that cannot be stored must not hide the pass; the next failure tries again
            logging.warning("queueing failure notices failed: %s", mask_secrets(repr(exc)))

    def _queue_failure_notices(self, broken: list[tuple[_DueTitle, Exception]]) -> int:
        """Queue the «could not check» events of one pass: one per title, and none for a title the owner was told about
        in the last 24 hours. Delivery folds the events of one source and reason into a message. The event and the time
        it was queued are stored together, so a restart neither repeats a notice nor loses one."""
        now = _naive_utc(self.clock())
        stamp = now.strftime("%Y%m%dT%H%M%S")  # the moment of the pass; it opens the 24-hour window of its titles
        queued = 0
        seen: set[int] = set()
        for due, exc in broken:
            if due.id in seen:  # two broken sources of one title are one failure
                continue
            seen.add(due.id)
            with self.session_factory() as session:
                title = session.get(Title, due.id)
                if title is None or (
                    title.failure_notified_at is not None and now - title.failure_notified_at < failures.COOLDOWN
                ):
                    continue
                payload = failures.failure_payload(
                    title.title, failures.source_name(due.snapshot_source), failures.reason_of(exc), stamp
                )
                title.failure_notified_at = now
                event_id = self._enqueue_event(
                    session, failures.SOURCE_FAILED, payload, f"failure:{title.id}:{stamp}", title.id, now
                )
                if event_id is not None:
                    queued += 1
                session.commit()
        return queued

    def _applier(self, kind: str) -> Callable[[_DueTitle, Any], int]:
        if kind == "anime":
            return self._apply_anime
        return self._apply_series if kind == "series" else self._apply_snapshot

    def _apply_snapshot(self, due: _DueTitle, snapshot: Any) -> int:
        """Compare the fresh snapshot with the stored one, queue events, store the new state."""
        now = _naive_utc(self.clock())
        today = now.date()
        with self.session_factory() as session:
            stored = self._stored_snapshot(session, due)
            old = movie_events.MovieDates.from_state(stored.state)
            new = movie_events.MovieDates.from_state(snapshot.state()).keeping_known(old)
            observed_on = stored.observed_at.date()
        found = 0
        # events first: if storing the state fails, the next poll finds the same facts and the dedup key drops them
        for event in movie_events.detect_events(due.id, due.name, old, new, observed_on, today):
            payload = {"text": event.text, **event.data}
            if self._record_event(event.type, payload, event.dedup_key, title_id=due.id) is not None:
                found += 1
        with self.session_factory() as session:
            stored = self._stored_snapshot(session, due)
            stored.state = new.to_state()
            stored.observed_at = now
            stored.next_check_at = now + movie_events.check_interval(new, today)
            session.commit()
        return found

    def _apply_series(self, due: _DueTitle, snapshot: Any) -> int:
        """Compare the fresh seasons with the stored ones, queue events, store the new seasons."""
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            stored = self._stored_snapshot(session, due)
            observed_at = stored.observed_at
            old = series_events.ShowState.of((season for _, season in self._load_seasons(session, due.id)), stored.state)
            gap = self._part_gap(session)
        new = series_events.ShowState.of(
            (s for s in snapshot.seasons if s.number >= 1), snapshot.state()
        ).keeping_known(old)
        found = 0
        # events first: if storing the state fails, the next poll finds the same facts and the dedup key drops them
        for event in series_events.detect_events(due.id, due.name, old, new, observed_at, now, gap):
            payload = {"text": event.text, **event.data}
            if self._record_event(event.type, payload, event.dedup_key, title_id=due.id) is not None:
                found += 1
        with self.session_factory() as session:
            self._sync_seasons(session, due.id, new.seasons)
            stored = self._stored_snapshot(session, due)
            stored.state = new.to_state()
            stored.observed_at = now
            stored.next_check_at = now + series_events.check_interval(new, now)
            self._refresh_status(session, session.get(Title, due.id))
            session.commit()
        return found

    @staticmethod
    def _sync_seasons(session, title_id: int, seasons: Sequence[season_logic.Season]) -> None:
        """Bring the stored seasons and episodes to the given ones; the owner's «watched» marks stay."""
        records = {r.number: r for r in session.scalars(select(SeasonRecord).where(SeasonRecord.title_id == title_id))}
        for season in seasons:
            record = records.get(season.number)
            if record is None:
                record = SeasonRecord(title_id=title_id, number=season.number, name=season.name,
                                      episode_count=season.expected, watched=False)
                session.add(record)
                session.flush()
            record.name = season.name
            record.episode_count = season.expected
            stored = {e.number: e for e in session.scalars(select(EpisodeRecord).where(EpisodeRecord.season_id == record.id))}
            for episode in season.episodes:
                if episode.number in stored:
                    stored[episode.number].air_at = episode.air_at
                else:
                    session.add(EpisodeRecord(season_id=record.id, number=episode.number, air_at=episode.air_at))
            listed = {e.number for e in season.episodes}
            for number, row in stored.items():
                if number not in listed:
                    session.delete(row)

    def _apply_anime(self, due: _DueTitle, snapshot: Any) -> int:
        """Put the anime's two sources together, compare with the stored seasons, queue events, store what is new."""
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            stored = self._stored_snapshot(session, due)
            observed_at = stored.observed_at
            previous = tuple(season for _, season in self._load_seasons(session, due.id))
            gap = self._part_gap(session)
            tz = self._time_zone(session)
            title = session.get(Title, due.id)
            name = title.title if title.original_title in ("", title.title) else f"{title.title} ({title.original_title})"
            known = set(
                session.scalars(
                    select(PartRecord.shikimori_id).where(PartRecord.title_id == due.id, PartRecord.anilist_id.is_not(None))
                )
            )
            films = {
                m.shikimori_id: m.released
                for m in session.scalars(select(MovieRecord).where(MovieRecord.title_id == due.id))
            }
        known.update(p.ids.shikimori for p in snapshot.parts if p.ids.anilist)
        old = series_events.ShowState.of(previous, {})
        assembled = anime_events.assemble(snapshot.seasons, snapshot.parts, snapshot.schedules, previous, now, known)
        new = series_events.ShowState.of(assembled, {}).keeping_known(old)
        detected = series_events.detect_events(
            due.id, name, old, new, observed_at, now, gap, anime_events.flavor(tz)
        )
        detected += anime_events.detect_movie_events(due.id, name, films, snapshot.movies, observed_at.date())
        found = 0
        # events first: if storing the state fails, the next poll finds the same facts and the dedup key drops them
        for event in detected:
            payload = {"text": event.text, **event.data}
            if self._record_event(event.type, payload, event.dedup_key, title_id=due.id) is not None:
                found += 1
        with self.session_factory() as session:
            self._sync_seasons(session, due.id, new.seasons)
            session.flush()
            self._sync_anime_entries(session, due.id, snapshot)
            stored = self._stored_snapshot(session, due)
            stored.state = {**stored.state, **{k: v for k, v in snapshot.state().items() if v is not None}}
            stored.observed_at = now
            stored.next_check_at = now + series_events.check_interval(new, now)
            self._refresh_status(session, session.get(Title, due.id))
            session.commit()
        return found

    @staticmethod
    def _sync_anime_entries(session, title_id: int, snapshot: Any) -> None:
        """The source entries behind the seasons and the franchise films: new ones are stored, known ones learn the
        counts and the AniList ids found since. What is stored is never emptied by a source that stays silent."""
        seasons = {r.number: r.id for r in session.scalars(select(SeasonRecord).where(SeasonRecord.title_id == title_id))}
        rows = {p.shikimori_id: p for p in session.scalars(select(PartRecord).where(PartRecord.title_id == title_id))}
        taken_anilist = {p.anilist_id for p in rows.values() if p.anilist_id}
        taken_slots = {(p.season_id, p.number) for p in rows.values()}
        for part in snapshot.parts:
            row = rows.get(part.ids.shikimori)
            if row is None:
                season_id = seasons.get(part.season)
                if season_id is None or (season_id, part.number) in taken_slots:
                    continue
                row = PartRecord(
                    title_id=title_id, season_id=season_id, number=part.number, first_episode=part.first_episode,
                    episode_count=part.episode_count, shikimori_id=part.ids.shikimori, mal_id=part.ids.mal,
                    anilist_id=None,
                )
                session.add(row)
                taken_slots.add((season_id, part.number))
            else:
                row.first_episode = part.first_episode
                row.episode_count = part.episode_count
            if row.anilist_id is None and part.ids.anilist and part.ids.anilist not in taken_anilist:
                row.anilist_id = part.ids.anilist
                taken_anilist.add(part.ids.anilist)

        films = {m.shikimori_id: m for m in session.scalars(select(MovieRecord).where(MovieRecord.title_id == title_id))}
        taken_anilist = {m.anilist_id for m in films.values() if m.anilist_id}
        for film in snapshot.movies:
            row = films.get(film.ids.shikimori)
            if row is None:
                row = MovieRecord(
                    title_id=title_id, name=film.name, aired_on=film.aired_on, released=film.released,
                    shikimori_id=film.ids.shikimori, mal_id=film.ids.mal, anilist_id=None,
                )
                session.add(row)
            else:
                row.name = film.name
                row.aired_on = film.aired_on or row.aired_on
                row.released = row.released or film.released  # a film does not become «announced» again
            if row.anilist_id is None and film.ids.anilist and film.ids.anilist not in taken_anilist:
                row.anilist_id = film.ids.anilist
                taken_anilist.add(film.ids.anilist)

    def _apply_sequels(self, due: _DueTitle, snapshot: Any) -> int:
        """Archived movie: announce the collection parts that were not there at the previous check."""
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            stored = self._stored_snapshot(session, due)
            first_look = "parts" not in stored.state
            old = sequel_events.Sequels.from_state(stored.state)
        new = sequel_events.Sequels.from_state(snapshot.state()).keeping_known(old)
        found = 0
        if not first_look:  # the first look only records what the collection holds now
            listed = self._listed_ids(self.sources[due.kind].source_key)
            for event in sequel_events.detect_sequel_events(due.name, due.kind, old, new):
                if event.data["sequel_id"] in listed:
                    continue  # the owner already follows it: nothing to offer
                payload = {"text": event.text, **event.data}
                if self._record_event(event.type, payload, event.dedup_key, title_id=due.id) is not None:
                    found += 1
        with self.session_factory() as session:
            stored = self._stored_snapshot(session, due)
            stored.state = new.to_state()
            stored.observed_at = now
            stored.next_check_at = now + sequel_events.INTERVAL
            session.commit()
        return found

    def _listed_ids(self, source_key: str) -> set[str]:
        with self.session_factory() as session:
            return set(session.scalars(select(ExternalId.external_id).where(ExternalId.source == source_key)))

    @staticmethod
    def _stored_snapshot(session, due: _DueTitle) -> SourceSnapshot:
        return session.scalars(
            select(SourceSnapshot).where(SourceSnapshot.title_id == due.id, SourceSnapshot.source == due.snapshot_source)
        ).one()

    def _postpone(self, due: _DueTitle, delay: timedelta) -> None:
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            stored = self._stored_snapshot(session, due)
            stored.next_check_at = now + delay
            session.commit()

    # --- test events ----------------------------------------------------------------------------

    def register_test_event_kind(self, kind: TestEventKind) -> None:
        self._kinds[kind.id] = kind

    def test_event_kinds(self) -> list[TestEventKind]:
        return list(self._kinds.values())

    async def send_test_event(self, kind_id: str, at: datetime | None = None) -> TestEventResult:
        """Create a fresh sample of the given kind and deliver it.

        Without `at` it goes out at once, whatever the hour: this checks that the channel works. With `at` (an aware
        moment) the sample is queued as if that moment were now and judged by the delivery rules of the owner. When
        the rules make it wait, the moment it would be released is played out too, so the owner sees the summary.
        Only the sample itself is touched: what really waits in the queue stays where it is."""
        kind = self._kinds[kind_id]
        built = kind.events() if kind.events is not None else [("test", kind.build())]
        prefix = f"Тестовое событие «{kind.label}»: "
        samples = [(event_type, {**payload, "text": prefix + payload["text"], "prefix": prefix}) for event_type, payload in built]
        run_id = uuid.uuid4().hex
        event_ids = await asyncio.to_thread(self._record_samples, kind.id, samples, run_id, at)
        only = frozenset(event_ids)
        if at is None:
            await self.deliver_pending(force=True, only=only)
            delivered = await asyncio.to_thread(self._all_delivered, only)
            return TestEventResult(delivered=delivered, delivered_at_once=delivered)

        await self.deliver_pending(now=at, only=only)
        if await asyncio.to_thread(self._all_delivered, only):
            return TestEventResult(delivered=True, delivered_at_once=True)
        rules = await self.delivery_rules()
        release, waited = rules.release(_naive_utc(at))
        if not waited:  # the rules let it go at once, so the sender failed
            return TestEventResult(delivered=False)
        released_at = release.replace(tzinfo=timezone.utc)
        await self.deliver_pending(now=released_at, only=only)
        return TestEventResult(
            delivered=await asyncio.to_thread(self._all_delivered, only), held_until=released_at
        )

    def _record_samples(
        self, kind_id: str, samples: list[tuple[str, dict[str, Any]]], run_id: str, at: datetime | None
    ) -> list[int]:
        return [
            self._record_event(event_type, payload, f"test:{kind_id}:{run_id}:{number}", at=at)
            for number, (event_type, payload) in enumerate(samples)
        ]

    def _all_delivered(self, event_ids: frozenset[int]) -> bool:
        with self.session_factory() as session:
            items = session.scalars(select(DeliveryItem).where(DeliveryItem.event_id.in_(event_ids))).all()
            return len(items) == len(event_ids) and all(item.status == "delivered" for item in items)

    async def window_test_moment(self, scenario: delivery.WindowScenario) -> datetime:
        """The next moment of the scenario on the owner's clock, as an aware moment."""
        rules = await self.delivery_rules()
        local = scenario.next_moment(rules.local(_naive_utc(self.clock())))
        return rules.utc(local).replace(tzinfo=timezone.utc)

    # --- delivery -------------------------------------------------------------------------------

    async def deliver_pending(
        self, *, now: datetime | None = None, only: frozenset[int] | None = None, force: bool = False
    ) -> DeliveryReport:
        """Send what the delivery rules let out at this moment. A failed send stays queued; the rest still go out.

        Events that arrived while the bot had to be silent wait and go out in one summary. `force` sends everything
        one by one regardless of the rules; `only` limits the pass to these event ids; `now` stands in for the clock."""
        report = DeliveryReport()
        async with self._delivery_lock:
            moment = _naive_utc(now or self.clock())
            rules, pending, names = await asyncio.to_thread(self._load_queue, only)
            if force:
                single, summary = pending, []
            else:
                single, summary = rules.due(pending, moment)
            # episodes are folded only inside a summary; failures of one source and reason are folded everywhere
            for unit in delivery.fold(single, episodes=False):
                item = unit.single
                actions = event_actions(item.type, item.event_id, item.title_id, item.data) if item is not None else []
                await self._send(unit.members, unit.text, actions, report)
            if summary:
                await self._send_summary(summary, moment, rules, report, names)
        return report

    async def digest_now(self) -> DigestResult:
        """«Сводка сейчас»: everything waiting goes out in one summary at once, whatever the hour, and is marked delivered."""
        report = DeliveryReport()
        async with self._delivery_lock:
            moment = _naive_utc(self.clock())
            rules, pending, names = await asyncio.to_thread(self._load_queue, None)
            if pending:
                await self._send_summary(pending, moment, rules, report, names)
        return DigestResult(events=len(pending), delivered=bool(pending) and report.failed == 0)

    def _load_queue(
        self, only: frozenset[int] | None
    ) -> tuple[delivery.DeliveryRules, list[delivery.Pending], dict[int, str]]:
        with self.session_factory() as session:
            query = (
                select(DeliveryItem.id, DeliveryItem.created_at, Event)
                .join(Event, Event.id == DeliveryItem.event_id)
                .where(DeliveryItem.status == "pending")
                .order_by(DeliveryItem.id)
            )
            if only is not None:
                query = query.where(Event.id.in_(only))
            pending = [
                delivery.Pending(item_id, event.id, event.type, event.title_id, format_event(event), event.payload, created)
                for item_id, created, event in session.execute(query)
            ]
            ids = {p.title_id for p in pending if p.title_id is not None}
            names = {t.id: t.title for t in session.scalars(select(Title).where(Title.id.in_(ids)))} if ids else {}
            return self._delivery_rules(session), pending, names

    async def _send_summary(
        self,
        pending: list[delivery.Pending],
        moment: datetime,
        rules: delivery.DeliveryRules,
        report: DeliveryReport,
        names: dict[int, str],
    ) -> None:
        units = delivery.fold(pending, episodes=True)
        for text, held in delivery.digest_messages(units, moment, rules):
            members = tuple(m for unit in held for m in unit.members)
            await self._send(members, text, self._summary_actions(held, names), report)

    @staticmethod
    def _summary_actions(units: list[delivery.Unit], names: dict[int, str]) -> list[Action]:
        """The buttons of the events inside a summary, each saying which title it is for."""
        actions: list[Action] = []
        shown: set[tuple[str, int]] = set()  # one button per action and title, however many events of it the summary holds
        for unit in units:
            single = unit.single
            if single is None:
                continue
            name = single.data.get("sequel_title") or names.get(single.title_id, "")
            if len(name) > BUTTON_NAME_LIMIT:
                name = name[: BUTTON_NAME_LIMIT - 1] + "…"
            for action in event_actions(single.type, single.event_id, single.title_id, single.data):
                if (action.name, action.arg) in shown:
                    continue
                shown.add((action.name, action.arg))
                actions.append(replace(action, label=f"{action.label}: {name}") if name else action)
        # «Следить» is never cut: a sequel announcement has no card or list entry to follow from. The rest fill
        # what is left of the limit, «Посмотрел» before «Карточка», and are reached from «Мои тайтлы» if cut.
        follow = [a for a in actions if a.name == FOLLOW]
        rest = [a for name in (WATCHED, CARD) for a in actions if a.name == name]
        return follow + rest[: max(0, MAX_DIGEST_BUTTONS - len(follow))]

    async def _send(
        self, members: Sequence[delivery.Pending], message: str, actions: Sequence[Action], report: DeliveryReport
    ) -> None:
        """Send one message that settles all `members`; they are marked delivered only if the send succeeded."""
        error: Exception | None = None
        try:
            await self.sender.send(message, actions)
        except Exception as exc:  # the sender is a network client: any failure means "try again later"
            error = exc
            logging.warning(
                "delivery of queue items %s failed: %s", [m.item_id for m in members], mask_secrets(repr(exc))
            )

        await asyncio.to_thread(self._record_attempts, [m.item_id for m in members], error)
        if error is None:
            report.delivered += len(members)
        else:
            report.failed += len(members)

    def _record_attempts(self, item_ids: Sequence[int], error: Exception | None) -> None:
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            for item_id in item_ids:
                item = session.get(DeliveryItem, item_id)
                if item is None:  # its title was deleted while the message was on its way: the entry is gone with it
                    continue
                item.attempts += 1
                if error is None:
                    item.status = "delivered"
                    item.last_error = None
                    item.delivered_at = now
                else:
                    item.last_error = mask_secrets(repr(error))[:500]
            session.commit()
