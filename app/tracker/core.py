"""Tracker core facade: the only door the bot (and later the web app) uses.

Clock, sender and sources come from outside, so tests can replace all three. An event is marked
delivered only after the sender succeeded, and the dedup key guarantees one event per fact.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.tracker import movie_events, seasons as season_logic, sequel_events, series_events
from app.tracker.actions import Action, event_actions
from app.tracker.cards import TitleCard
from app.tracker.models import (
    STATUS_WANT,
    STATUS_WATCHED,
    DeliveryItem,
    EpisodeRecord,
    Event,
    ExternalId,
    SeasonRecord,
    SourceSnapshot,
    Title,
)
from app.utils.secrets_mask import mask_secrets

Clock = Callable[[], datetime]  # returns an aware datetime

PRIMARY_ROLE = "primary"


class Sender(Protocol):
    async def send(self, message: str, actions: Sequence[Action] = ()) -> None:
        """Deliver one message to the owner, with `actions` as buttons under it; raise on failure."""


class TitleNotFound(Exception):
    """The source has nothing at the chosen id (for example a series id picked as a movie)."""


class UnknownTitle(Exception):
    """There is no title with this id in the list."""


class UnknownEvent(Exception):
    """There is no «sequel announced» event with this id."""


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


@dataclass(frozen=True)
class TestEventResult:
    __test__ = False

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
    _kinds: dict[str, TestEventKind] = field(init=False, default_factory=dict)
    _delivery_lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
    _poll_lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)
    _write_lock: asyncio.Lock = field(init=False, default_factory=asyncio.Lock)  # one «add» writes at a time

    def __post_init__(self) -> None:
        self.register_test_event_kind(TestEventKind("ping", "Проверка связи", _ping_payload))
        samples = movie_events.TEST_SAMPLES + sequel_events.TEST_SAMPLES + series_events.TEST_SAMPLES
        for kind_id, label, text in samples:
            self.register_test_event_kind(TestEventKind(kind_id, label, lambda text=text: {"text": text}))

    # --- events ---------------------------------------------------------------------------------

    def record_event(
        self, type: str, payload: dict[str, Any], dedup_key: str, title_id: int | None = None
    ) -> int | None:
        """Store an event and queue it for delivery. Returns its id, or None if this fact is already known."""
        now = _naive_utc(self.clock())
        with self.session_factory() as session:
            event = Event(type=type, title_id=title_id, payload=payload, dedup_key=dedup_key, detected_at=now)
            session.add(event)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                return None
            session.add(DeliveryItem(event_id=event.id, status="pending", attempts=0, created_at=now))
            session.commit()
            return event.id

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
            session.add(
                SourceSnapshot(
                    title_id=title.id,
                    source=source_key,
                    state=state,
                    observed_at=now,
                    # the snapshot taken now is the baseline; the first poll compares against it
                    next_check_at=self._first_check(kind, snapshot, state, now),
                )
            )
            self._store_seasons(session, title.id, getattr(snapshot, "seasons", ()))
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
    def _first_check(kind: str, snapshot: Any, state: dict[str, Any], now: datetime) -> datetime | None:
        if kind == "movie":
            return now + movie_events.check_interval_for_state(state, now.date())
        if kind == "series":
            return now + series_events.check_interval(series_events.ShowState.of(snapshot.seasons, state), now)
        return None

    @staticmethod
    def _store_seasons(session, title_id: int, seasons: Sequence[season_logic.Season]) -> None:
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

    @staticmethod
    def _load_seasons(session, title_id: int) -> list[tuple[SeasonRecord, season_logic.Season]]:
        records = session.scalars(select(SeasonRecord).where(SeasonRecord.title_id == title_id).order_by(SeasonRecord.number))
        loaded = []
        for record in records:
            episodes = session.scalars(select(EpisodeRecord).where(EpisodeRecord.season_id == record.id))
            season = season_logic.Season(
                number=record.number,
                name=record.name,
                expected=record.episode_count,
                episodes=tuple(sorted((season_logic.Episode(e.number, e.air_at) for e in episodes), key=lambda e: e.number)),
            )
            loaded.append((record, season))
        return loaded

    def watchable_seasons(self, title_id: int) -> list[WatchableSeason]:
        """Seasons that can be marked as watched, with their marks. A season with nothing released cannot."""
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
            session.commit()

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

    async def follow_sequel(self, event_id: int) -> AddResult:
        """«Следить» under a sequel announcement: the sequel joins the list as «Хочу». Pressing twice opens it."""
        kind, sequel_id = await asyncio.to_thread(self._announced_sequel, event_id)
        return await self.add_title(kind, sequel_id)

    def _announced_sequel(self, event_id: int) -> tuple[str, str]:
        with self.session_factory() as session:
            event = session.get(Event, event_id)
            if event is None or event.type != sequel_events.SEQUEL_ANNOUNCED:
                raise UnknownEvent(event_id)
            return event.payload["kind"], event.payload["sequel_id"]

    def list_titles(self) -> list[TitleSummary]:
        with self.session_factory() as session:
            rows = session.scalars(select(Title).order_by(Title.id))
            return [TitleSummary(t.id, t.kind, t.title, t.year, t.status) for t in rows]

    def title_card(self, title_id: int) -> TitleCard | None:
        with self.session_factory() as session:
            title = session.get(Title, title_id)
            if title is None:
                return None
            snapshot = session.scalar(
                select(SourceSnapshot)
                .join(ExternalId, ExternalId.title_id == SourceSnapshot.title_id)
                .where(
                    SourceSnapshot.title_id == title_id,
                    ExternalId.role == PRIMARY_ROLE,
                    SourceSnapshot.source == ExternalId.source,  # the archive's sequel snapshot holds no dates
                )
            )
            state = snapshot.state if snapshot else {}
            seasons_view = None
            if title.kind == "series":
                loaded = self._load_seasons(session, title_id)
                seasons_view = season_logic.summarize(
                    (season for _, season in loaded),
                    {record.number for record, _ in loaded if record.watched},
                    _naive_utc(self.clock()),
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
            )

    # --- polling --------------------------------------------------------------------------------

    async def poll_due(self) -> PollReport:
        """Look at every title whose check time has come and queue the events found.

        A failing source postpones only its own title; the others are still polled. Database work runs
        in a worker thread, so a slow disk never freezes the bot.
        """
        report = PollReport()
        async with self._poll_lock:
            for due in await asyncio.to_thread(self._due_titles):
                await self._poll_one(due, report)
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
                            Title.kind.in_(("movie", "series")),
                            Title.status == STATUS_WANT,
                            Title.tracking_enabled.is_(True),
                        ),
                        and_(~own, Title.status == STATUS_WATCHED),
                    ),
                    (SourceSnapshot.next_check_at.is_(None)) | (SourceSnapshot.next_check_at <= now),
                )
                .order_by(Title.id)
            )
            return [_DueTitle(*row) for row in rows]

    async def _poll_one(self, due: _DueTitle, report: PollReport) -> None:
        try:
            source = (self.sequel_sources if due.sequels else self.sources)[due.kind]
            snapshot = await source.snapshot(due.external_id)
            if snapshot is None:
                raise LookupError(f"{due.kind}:{due.external_id} is no longer known to the source")
            apply = self._apply_sequels if due.sequels else self._applier(due.kind)
            found = await asyncio.to_thread(apply, due, snapshot)
        except Exception as exc:  # one broken title or source must not stop the pass
            logging.warning("polling title %s failed: %s", due.id, mask_secrets(repr(exc)))
            report.failed += 1
            try:
                await asyncio.to_thread(self._postpone, due, movie_events.RETRY_AFTER_FAILURE)
            except Exception as postpone_exc:  # even a failed postponement leaves the other titles to the pass
                logging.warning("postponing title %s failed: %s", due.id, mask_secrets(repr(postpone_exc)))
            return
        report.polled += 1
        report.events += found

    def _applier(self, kind: str) -> Callable[[_DueTitle, Any], int]:
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
            if self.record_event(event.type, payload, event.dedup_key, title_id=due.id) is not None:
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
        new = series_events.ShowState.of(
            (s for s in snapshot.seasons if s.number >= 1), snapshot.state()
        ).keeping_known(old)
        found = 0
        # events first: if storing the state fails, the next poll finds the same facts and the dedup key drops them
        for event in series_events.detect_events(due.id, due.name, old, new, observed_at, now):
            payload = {"text": event.text, **event.data}
            if self.record_event(event.type, payload, event.dedup_key, title_id=due.id) is not None:
                found += 1
        with self.session_factory() as session:
            self._sync_seasons(session, due.id, new.seasons)
            stored = self._stored_snapshot(session, due)
            stored.state = new.to_state()
            stored.observed_at = now
            stored.next_check_at = now + series_events.check_interval(new, now)
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
                if self.record_event(event.type, payload, event.dedup_key, title_id=due.id) is not None:
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

    async def send_test_event(self, kind_id: str) -> TestEventResult:
        """Create a fresh sample event of the given kind and try to deliver it right away."""
        kind = self._kinds[kind_id]
        payload = kind.build()
        payload = {**payload, "text": f"Тестовое событие «{kind.label}»: {payload['text']}"}
        event_id = await asyncio.to_thread(
            self.record_event, "test", payload, f"test:{kind.id}:{uuid.uuid4().hex}"
        )
        await self.deliver_pending()
        return TestEventResult(delivered=await asyncio.to_thread(self._is_delivered, event_id))

    def _is_delivered(self, event_id: int) -> bool:
        with self.session_factory() as session:
            item = session.scalar(select(DeliveryItem).where(DeliveryItem.event_id == event_id))
            return item is not None and item.status == "delivered"

    # --- delivery -------------------------------------------------------------------------------

    async def deliver_pending(self) -> DeliveryReport:
        """Send everything waiting in the queue. A failed send stays queued; the rest still go out."""
        report = DeliveryReport()
        async with self._delivery_lock:
            pending = await asyncio.to_thread(self._pending_items)
            for item_id, event in pending:
                actions = event_actions(event.type, event.id, event.title_id)
                if await self._deliver_one(item_id, format_event(event), actions):
                    report.delivered += 1
                else:
                    report.failed += 1
        return report

    def _pending_items(self) -> list[tuple[int, Event]]:
        with self.session_factory() as session:
            return list(
                session.execute(
                    select(DeliveryItem.id, Event)
                    .join(Event, Event.id == DeliveryItem.event_id)
                    .where(DeliveryItem.status == "pending")
                    .order_by(DeliveryItem.id)
                )
            )

    async def _deliver_one(self, item_id: int, message: str, actions: Sequence[Action]) -> bool:
        error: Exception | None = None
        try:
            await self.sender.send(message, actions)
        except Exception as exc:  # the sender is a network client: any failure means "try again later"
            error = exc
            logging.warning("delivery of queue item %s failed: %s", item_id, mask_secrets(repr(exc)))

        await asyncio.to_thread(self._record_attempt, item_id, error)
        return error is None

    def _record_attempt(self, item_id: int, error: Exception | None) -> None:
        with self.session_factory() as session:
            item = session.get(DeliveryItem, item_id)
            item.attempts += 1
            if error is None:
                item.status = "delivered"
                item.last_error = None
                item.delivered_at = _naive_utc(self.clock())
            else:
                item.last_error = mask_secrets(repr(error))[:500]
            session.commit()
