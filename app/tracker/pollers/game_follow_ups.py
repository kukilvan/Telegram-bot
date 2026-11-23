"""The weekly check of games for expansions and sequels at the end of a polling pass: which games, the reconciliation, the due games, the queueing, the store, the failures.

Spec 5 of stage 6.3; spec 3 and 4 of stage 9.1b.

Each pass (every minute) the snapshots of source `igdb_follow_ups` are first brought in line with the rule «игра для
проверки» (`for_follow_ups`), in a constant number of reads: a game for the check without a snapshot gets an empty one
(`{}`: not checked yet), due now; the snapshot of a game that is no longer one goes. Of the own snapshot only the key
`expansion` is read; an unreadable one leaves the game to its status alone (KI-55: the snapshot made, never dropped, a
log line a day). The rule lives here; «Бросил» applies its «drop» at once in its write session (`drop_unchecked`,
KI-53), so «Вернуть в список» gets an empty snapshot at the next pass: a silent reference point. Only the
reconciliation makes snapshots.

Then at most `FOLLOW_UPS_PER_PASS` due games are asked about, the earliest first. Each game: its stored state and the
key `expansion` of its own snapshot are read strictly before IGDB is asked (unreadable — a failure, no request), IGDB is
asked with no database open, one read session reads what `follow_ups.check` needs. A game gone or no longer checked
while IGDB answered is skipped. The events are queued first, each in its own session while the snapshot exists
(`EventQueue.enqueue(…, due=game)`), then the state is stored, next check in 7 days, so a failed store finds the same
facts again and their keys drop them; that session also gives the own snapshot the game's type and parent when its own
check does not run (KI-52). A failure (IGDB, the game gone from IGDB, no keys, a spoiled state) waits 30 minutes and
joins the «could not check» messages of the pass.

What the owner reads (spec 7.1): `card_view` gives the expansions and the games of the series of a card, `parent` the
game an expansion belongs to; both in a number of reads that does not grow with the lists.
"""

import asyncio
import logging
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any

from sqlalchemy import or_, select

from app.tracker import failures, follow_ups, games, storage
from app.tracker.cards import FollowLine, FollowUpsView, ParentGame
from app.tracker.checks import POLLED_STATUSES
from app.tracker.context import PRIMARY_ROLE, CoreContext
from app.tracker.game_scope import GameScope
from app.tracker.models import ExternalId, SourceSnapshot, Title, TitleKind, TitleStatus
from app.tracker.moment_words import local_moment
from app.tracker.movie_events import RETRY_AFTER_FAILURE, DetectedEvent
from app.tracker.pollers.base import DueTitle
from app.tracker.queue import EventQueue
from app.tracker.settings_store import SettingsStore
from app.tracker.sources.igdb_follow_ups import SOURCE_KEY

FOLLOW_UPS_PER_PASS = 10  # games asked about in one pass; IGDB is asked once a game
FOLLOW_UP_INTERVAL = timedelta(days=7)  # after a check that worked; after a failure — `RETRY_AFTER_FAILURE`
FOLLOW_UP_STATUSES = (TitleStatus.WANT, TitleStatus.IN_PROGRESS, TitleStatus.COMPLETED)  # «Хочу», «В процессе», «Пройдено»

# id of the source → the title that has it in the list (`Poller.known_ids` of the game source)
KnownIds = Callable[[Any, Iterable[str]], Mapping[str, int]]


def for_follow_ups(status: TitleStatus, expansion: str | None) -> bool:
    """«Игра для проверки» (spec 5.1), the one place of the rule: the game is in «Хочу», «В процессе» or «Пройдено» and
    is not an expansion that needs its game (`expansion` — `GameState.expansion` of its own snapshot: a standalone
    expansion is checked as a game)."""
    return status in FOLLOW_UP_STATUSES and expansion != games.EXPANSION


def _title_checked(session, title_id: int) -> Title | None:
    """The title while it is still a game for the check (`for_follow_ups` on its own snapshot); None — it is gone or
    no longer checked. A spoiled own snapshot raises ValueError."""
    title = session.get(Title, title_id)
    if title is None or not for_follow_ups(title.status, games.expansion_of(storage.own_state(session, title_id))):
        return None
    return title


class _UnreadableOwn(ValueError):
    """The game's own snapshot cannot be read (`games.expansion_of` raised): its follow-up check fails before IGDB."""


@dataclass
class _Plan:
    """What the reconciliation found: the games to get a snapshot, the snapshots to go, the games whose own snapshot
    cannot be read (title → the error; judged by their status alone)."""

    create: list[int] = field(default_factory=list)
    drop: list[SourceSnapshot] = field(default_factory=list)
    unreadable: dict[int, ValueError] = field(default_factory=dict)


class GameFollowUps:
    """The follow-up check of the games of `kind`; `source` is the source of the check (`IgdbFollowUpSource`), None —
    none. `known_ids` tells which IGDB ids are games of the list (the game poller's own)."""

    def __init__(
        self, kind: TitleKind, source: Any, ctx: CoreContext, settings: SettingsStore, known_ids: KnownIds
    ) -> None:
        self.kind = kind
        self.source = source
        self.ctx = ctx
        self.settings = settings
        self.known_ids = known_ids
        self._unreadable_log = failures.DailyLog()  # «its own snapshot cannot be read», once a day per game

    async def check(self) -> list[tuple[DueTitle, Exception]]:
        """Reconcile the snapshots, check the due games and store what IGDB answered. Returns the failures of the games
        (for the «could not check» messages); each of them is looked at again in 30 minutes."""
        if self.source is None:
            return []
        due = await asyncio.to_thread(self._reconcile)
        broken: list[tuple[DueTitle, Exception]] = []
        for game in due:
            try:
                failure = await self._check_one(game)
            except Exception:  # a bug in one game leaves the others to the check
                logging.exception("the follow-up check of title %s failed", game.id)
                await asyncio.to_thread(self._postpone, game)
                continue
            if failure is not None and await asyncio.to_thread(self._postpone, game):
                broken.append((game, failure))
        if due:
            logging.info("follow-up check: %s games, %s failed", len(due), len(broken))
        return broken

    # --- what the card reads (spec 7.1) ---

    def parent(self, session, game: games.GameState) -> ParentGame | None:
        """The game an expansion belongs to: its name in the list when the list has it, else the name IGDB gave. None —
        the game is no expansion. At most two reads."""
        if game.parent is None:
            return None
        title_id = self.known_ids(session, [game.parent.id]).get(game.parent.id)
        if title_id is None:
            return ParentGame(game.parent.name)
        return ParentGame(session.scalar(select(Title.name).where(Title.id == title_id)) or game.parent.name, title_id)

    def card_view(
        self, session, title: Title, game: games.GameState, scope: GameScope, tz: tzinfo
    ) -> FollowUpsView | None:
        """The expansions and the games of the series for the card of `title` (`game`: its own state): None when the game
        is not one for the check or the core has no source of it; «not checked yet» while its snapshot is empty or not
        made yet. A spoiled stored state shows no blocks (the check reports it). The number of reads does not grow
        with the lists: the snapshot, and one for the titles of the rows."""
        if self.source is None or not for_follow_ups(title.status, game.expansion):
            return None
        stored = storage.snapshot_of(session, title.id, SOURCE_KEY)
        if stored is None:
            return FollowUpsView(checked=False)
        try:
            state = follow_ups.FollowUps.from_state(stored.state)
        except ValueError as spoiled:
            logging.warning("title %s: a spoiled state of the follow-up check, no blocks on its card: %r", title.id, spoiled)
            return None
        if state.snapshot is None:
            return FollowUpsView(checked=False)
        today = local_moment(self.ctx.now(), tz).date()
        expansions = follow_ups.expansions_shown(state.snapshot, scope.mine, scope.country)
        sequels = follow_ups.sequels_shown(state.snapshot, scope.mine, scope.country, today)
        listed = self.known_ids(session, [follow_up.id for follow_up in expansions + sequels])

        def lines(items: list[follow_ups.FollowUp]) -> tuple[FollowLine, ...]:
            return tuple(
                FollowLine(
                    follow_up.id, follow_up.name,
                    follow_ups.follow_up_date(follow_up, scope.mine, scope.country).label, listed.get(follow_up.id),
                )
                for follow_up in items
            )

        return FollowUpsView(
            True, stored.observed_at.replace(tzinfo=timezone.utc).astimezone(tz), lines(expansions), lines(sequels),
            state.snapshot.collections,
        )

    # --- the reconciliation (spec 5.2) ---

    def _reconcile(self) -> list[DueTitle]:
        """Bring the snapshots in line with the rule; returns the due games. A change is decided again in the write
        session that makes it, so a button pressed meanwhile is not undone."""
        now = self.ctx.now()
        with self.ctx.session_factory() as session:
            plan = self._plan(session)
        for title_id, error in plan.unreadable.items():
            self._unreadable_log.warning(
                title_id, now, "title %s: its own snapshot cannot be read, checked for follow-ups by its status: %r",
                title_id, error,
            )
        if plan.create or plan.drop:
            with self.ctx.write_session() as session:
                plan = self._plan(session)
                for stored in plan.drop:
                    logging.info("title %s: no longer checked for expansions and sequels, the snapshot goes", stored.title_id)
                    session.delete(stored)
                for title_id in plan.create:
                    session.add(SourceSnapshot(title_id=title_id, source=SOURCE_KEY, state={}, observed_at=now, next_check_at=now))
                session.commit()
        with self.ctx.session_factory() as session:
            return self._due(session, now)

    def _plan(self, session) -> _Plan:
        """The reconciliation in three reads, however many games there are."""
        checked, unreadable = _games_for_check(session, self.kind)
        snapshots = _snapshots(session, self.kind)
        return _Plan(sorted(checked - snapshots.keys()), _unchecked(snapshots, checked), unreadable)

    # --- a press (spec 3.1 of stage 9.1b) ---

    def drop_unchecked(self, session, title_ids: Collection[int] | None) -> None:
        """In the write session of a press: the follow-up snapshots of the games `title_ids` (None — every game of the
        kind) that are no longer «игра для проверки» go — the reconciliation's own drop, applied at once (KI-53), so a
        check answering after the press finds no snapshot and queues nothing, and «Вернуть в список» starts anew. A
        press never makes a snapshot: only the reconciliation does, at the start of a pass."""
        checked, _ = _games_for_check(session, self.kind, title_ids)
        for stored in _unchecked(_snapshots(session, self.kind, title_ids), checked):
            logging.info("title %s: no longer checked for expansions and sequels, the snapshot goes", stored.title_id)
            session.delete(stored)

    def _due(self, session, now: datetime) -> list[DueTitle]:
        """At most `FOLLOW_UPS_PER_PASS` games whose check time has come, the earliest first, then by title (spec 5.3)."""
        rows = session.execute(
            select(Title.id, Title.name, ExternalId.external_id)
            .join(SourceSnapshot, SourceSnapshot.title_id == Title.id)
            .join(ExternalId, (ExternalId.title_id == Title.id) & (ExternalId.role == PRIMARY_ROLE))
            .where(
                Title.kind == self.kind,
                SourceSnapshot.source == SOURCE_KEY,
                or_(SourceSnapshot.next_check_at.is_(None), SourceSnapshot.next_check_at <= now),
            )
            .order_by(SourceSnapshot.next_check_at, Title.id)
            .limit(FOLLOW_UPS_PER_PASS)
        )
        return [
            DueTitle(title_id, self.kind, name, external_id, SOURCE_KEY, sequels=False)
            for title_id, name, external_id in rows
        ]

    # --- one game (spec 5.3–5.6) ---

    async def _check_one(self, game: DueTitle) -> Exception | None:
        """Check one due game; returns the failure to tell about, None when it was checked or skipped."""
        try:
            previous = await asyncio.to_thread(self._stored, game)
        except _UnreadableOwn as unreadable:
            spoiled = unreadable.__cause__
            self._unreadable_log.warning(
                game.id, self.ctx.now(), "title %s: its own snapshot cannot be read, its follow-up check fails: %r",
                game.id, spoiled,
            )
            return spoiled
        except ValueError as spoiled:
            logging.warning("title %s: a spoiled state of the follow-up check: %r", game.id, spoiled)
            return spoiled
        if previous is None:
            return None
        try:
            snapshot = await self.source.follow_ups(game.external_id)
        except Exception as exc:  # IGDB failed, no longer knows the game, or has no keys
            logging.warning("follow-up check of title %s failed: %r", game.id, exc)
            return exc
        try:
            result = await asyncio.to_thread(self._decide, game, previous, snapshot)
        except ValueError as spoiled:
            logging.warning("title %s: its own snapshot cannot be read for the follow-up check: %r", game.id, spoiled)
            return spoiled
        if result is None:
            return None
        now = self.ctx.now()
        if not previous.checked:
            logging.info("title %s: first follow-up check, the reference point", game.id)
        found = sum([await asyncio.to_thread(self._queue, game, event, now) for event in result.events])
        if found:
            logging.info("title %s: %s announcements of expansions and sequels", game.id, found)
        await asyncio.to_thread(self._store, game, result.state, snapshot, now)
        return None

    def _stored(self, game: DueTitle) -> follow_ups.FollowUps | None:
        """The stored state, read strictly (a spoiled one raises ValueError); None — the snapshot is gone. The key
        `expansion` of the own snapshot is read first: unreadable raises `_UnreadableOwn` (KI-55), so IGDB is not asked."""
        with self.ctx.session_factory() as session:
            stored = storage.snapshot_of(session, game.id, SOURCE_KEY)
            if stored is None:
                return None
            try:
                games.expansion_of(storage.own_state(session, game.id))
            except ValueError as error:
                raise _UnreadableOwn(str(error)) from error
            return follow_ups.FollowUps.from_state(stored.state)

    def _decide(
        self, game: DueTitle, previous: follow_ups.FollowUps, snapshot: follow_ups.FollowUpsSnapshot
    ) -> follow_ups.CheckResult | None:
        """What the answer brings, by the rules of `follow_ups`, with everything they need read in one session. None —
        the game is gone or no longer for the check: nothing is queued or stored."""
        with self.ctx.session_factory() as session:
            title = _title_checked(session, game.id)
            if title is None:
                logging.info("title %s was deleted or is no longer checked for follow-ups, nothing is stored", game.id)
                return None
            scope = GameScope.read(self.settings, session)
            today = local_moment(self.ctx.now(), self.settings.time_zone(session)).date()
            listed = self.known_ids(session, [follow_up.id for follow_up in snapshot.expansions + snapshot.games])
            name = title.name
        return follow_ups.check(previous, snapshot, name, scope.mine, scope.country, today, listed.keys())

    def _queue(self, game: DueTitle, event: DetectedEvent, now: datetime) -> bool:
        """Queue an announcement while the game's snapshot exists (`checks.still_checked`: «Бросил» drops it at once,
        so a message never comes after the press took the others out); False — its fact is known already, or the
        game is no longer checked (no dedup key is spent then)."""
        with self.ctx.write_session() as session:
            payload = {"text": event.text, **event.data}
            if EventQueue.enqueue(session, event.type, payload, event.dedup_key, game.id, now, due=game) is None:
                return False
            session.commit()
            return True

    def _store(
        self, game: DueTitle, state: follow_ups.FollowUps, snapshot: follow_ups.FollowUpsSnapshot, now: datetime
    ) -> None:
        with self.ctx.write_session() as session:
            stored = storage.snapshot_of(session, game.id, SOURCE_KEY)
            if stored is None:
                logging.info("title %s was deleted or dropped while its follow-ups were checked", game.id)
                return
            stored.state = state.state()
            stored.observed_at = now
            stored.next_check_at = now + FOLLOW_UP_INTERVAL
            _learn_own_kind(session, game.id, snapshot)
            session.commit()

    def _postpone(self, game: DueTitle) -> bool:
        """The next check of the game in 30 minutes. False — nothing failed for the owner: the snapshot is gone, or the
        game is no longer for the check (status or expansion) while IGDB answered (the next pass removes the snapshot)."""
        with self.ctx.write_session() as session:
            stored = storage.snapshot_of(session, game.id, SOURCE_KEY)
            if stored is None:
                return False
            stored.next_check_at = self.ctx.now() + RETRY_AFTER_FAILURE
            try:
                still_checked = _title_checked(session, game.id) is not None
            except ValueError:  # its own snapshot is spoiled: that is the failure to tell about
                still_checked = True
            session.commit()
            return still_checked


def _games_for_check(
    session, kind: TitleKind, title_ids: Collection[int] | None = None
) -> tuple[set[int], dict[int, ValueError]]:
    """The games of the kind (or of `title_ids` among them) that are «игра для проверки» now, in two reads, and the
    ones whose own snapshot cannot be read (title → the error): those are judged by their status alone, so they count
    (KI-55: a snapshot made and never dropped, so the check fails and reports)."""
    query = select(Title.id, Title.status).where(Title.kind == kind, Title.status.in_(FOLLOW_UP_STATUSES))
    if title_ids is not None:
        query = query.where(Title.id.in_(list(title_ids)))
    statuses = dict(session.execute(query).all())
    states = storage.own_states_of(session, select(Title.id).where(Title.id.in_(list(statuses))))
    checked: set[int] = set()
    unreadable: dict[int, ValueError] = {}
    for title_id, status in sorted(statuses.items()):
        try:
            expansion = games.expansion_of(states.get(title_id, {}))
        except ValueError as error:
            unreadable[title_id] = error
            expansion = None
        if for_follow_ups(status, expansion):
            checked.add(title_id)
    return checked, unreadable


def _snapshots(session, kind: TitleKind, title_ids: Collection[int] | None = None) -> dict[int, SourceSnapshot]:
    """The follow-up snapshots of the games of the kind (or of `title_ids` among them), title → snapshot, in one read."""
    query = select(SourceSnapshot).where(
        SourceSnapshot.source == SOURCE_KEY, SourceSnapshot.title_id.in_(select(Title.id).where(Title.kind == kind))
    )
    if title_ids is not None:
        query = query.where(SourceSnapshot.title_id.in_(list(title_ids)))
    return {stored.title_id: stored for stored in session.scalars(query)}


def _unchecked(snapshots: dict[int, SourceSnapshot], checked: Collection[int]) -> list[SourceSnapshot]:
    """The snapshots of the games that are no longer «игра для проверки» (`checked`: the games that are): they go. The
    one place of the rule «drop», for the reconciliation and for a press."""
    return [stored for title_id, stored in sorted(snapshots.items()) if title_id not in checked]


def _learn_own_kind(session, title_id: int, snapshot: follow_ups.FollowUpsSnapshot) -> None:
    """KI-52: when the game's own check does not run (its status is not polled or tracking is off — a game in
    «Пройдено»), the kind of expansion and the parent IGDB gave now are written into its own snapshot if they differ,
    so its card and its List mark know it. A game whose own check runs leaves them to it; a spoiled own state is left
    alone (the check reports it, KI-55)."""
    title = session.get(Title, title_id)
    if title is None or (title.status in POLLED_STATUSES and title.tracking_enabled):
        return
    own = storage.own_snapshot(session, title_id)
    if own is None:
        return
    try:
        state = games.GameState.from_state(own.state)
    except (ValueError, TypeError, KeyError, AttributeError):
        return
    kind, parent = snapshot.own_expansion, snapshot.own_parent
    if (state.expansion, state.parent) == (kind, parent):
        return
    logging.info("title %s: IGDB gives its own kind of expansion %s, written into its own snapshot", title_id, kind)
    own.state = replace(state, expansion=kind, parent=parent).state()
