"""The price check at the end of a polling pass: which games have their Steam prices checked, the requests in packs of
100, the reference point, the price history and the failures (spec 4 of part 6.2).

Stage 9.1b (spec 2) added a spoiled snapshot as a failure, the three phases of a check and the press's «drop».

Each pass (every minute) the price snapshots (source `steam`) are first brought in line with the rule «игра для цен»
(`steam_number`), in a number of reads that does not grow with the number of games: a game for prices without a
snapshot gets an empty one, due now; a snapshot that looked at another Steam number or store country becomes empty,
due now (a failure of that check waits 30 minutes, as any); the snapshot of a game that is no longer one goes, and with
it the undelivered events of Steam of that game (the price history stays). A snapshot that cannot be read is left
alone while its game is for prices: each time it is due it is a failure of the check (KI-50). The rule lives here; a
press that can end a price check («Прошёл», «Начал играть», «Бросил», the mark «играю здесь», a save of Settings)
applies its «drop» at once in its own write session (`drop_unpriced`, KI-47); only the reconciliation makes snapshots.
Then the due games are asked about, all in the country of the stores of now; the request holds no database. The check
works in three phases (KI-51): every pack asked and the events of every game found in a read session; the events of
all the games queued in one write session (`EventQueue.enqueue_all`: a game whose snapshot went meanwhile queues
nothing, a new discount takes the undelivered one of the game out only when it is queued itself); then each look and
its history stored in a write session of its own, so a failed store finds the same facts again and their keys drop
them.
"""

import asyncio
import logging
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.providers.steam import MAX_ITEMS
from app.tracker import failures, games, price_events, storage
from app.tracker.context import CoreContext
from app.tracker.game_scope import GameScope
from app.tracker.models import PriceRecord, SourceSnapshot, Title, TitleKind, TitleStatus
from app.tracker.movie_events import RETRY_AFTER_FAILURE, DetectedEvent
from app.tracker.platforms import Platform
from app.tracker.pollers.base import DueTitle
from app.tracker.prices import Lowest, PriceLook, lowest
from app.tracker.queue import EventQueue, Queued
from app.tracker.settings_store import SettingsStore
from app.tracker.sources.steam_prices import SOURCE_KEY, UnreadAnswer

PRICE_INTERVAL = timedelta(hours=6)  # after a price check that worked; after a failure — `RETRY_AFTER_FAILURE`


def reports_prices(status: TitleStatus, game: games.GameState, told: Collection[Platform]) -> bool:
    """Prices are told about in a game (spec 4.1 and 6.1): it is in «Хочу», it is on PC and the owner is told about PC
    in it (`GameScope.told`: PC among «Мои платформы» and marked «играю здесь»). The card has its block of Steam by it,
    whether IGDB gave the Steam number or not. Whether the core has a source of prices is not this rule's business."""
    return status == TitleStatus.WANT and Platform.PC in told and games.has_platform(game, Platform.PC)


def steam_number(status: TitleStatus, game: games.GameState, told: Collection[Platform]) -> str | None:
    """The Steam number whose prices are checked for a game (spec 4.1) — «игра для цен»: a game prices are told about
    (`reports_prices`) that IGDB gave a Steam number to; None — its prices are not checked."""
    return game.steam_id if game.steam_id and reports_prices(status, game, told) else None


def is_baseline(old: PriceLook | None, new: PriceLook) -> bool:
    """The check is the reference point (spec 4.3): nothing was looked at before (the snapshot was just made), or the
    previous look asked about another Steam number or in another country. Its look is stored, no event comes of it."""
    return old is None or not old.is_of(new.appid, new.country)


def priced_games(session, kind: TitleKind, settings: SettingsStore) -> tuple[GameScope, dict[int, str]]:
    """The games for prices (`steam_number`) among the games of «Хочу», title → Steam number, with the scope they are
    told by; the number of reads does not grow with the number of games."""
    wanted = select(Title.id).where(Title.kind == kind, Title.status == TitleStatus.WANT)
    states = storage.own_states_of(session, wanted)
    scope = GameScope.read(settings, session, wanted)
    priced = {}
    for title_id in sorted(states):
        appid = steam_number(TitleStatus.WANT, games.GameState.from_state(states[title_id]), scope.told(title_id))
        if appid is not None:
            priced[title_id] = appid
    return scope, priced


def price_history(session, title_id: int) -> list[PriceRecord]:
    """The records of the price history of a game, in one read."""
    return list(session.scalars(select(PriceRecord).where(PriceRecord.title_id == title_id)))


def lowest_seen(session, title_id: int, look: PriceLook) -> Lowest | None:
    """«Самая низкая с добавления» of a game by its price history, for the number, the country and the currency of
    `look` (`prices.lowest`); None — no record of them, or the look has no currency."""
    if look.currency is None:
        return None
    return lowest(price_history(session, title_id), look.appid, look.country, look.currency)


def _same_record(record: PriceRecord, look: PriceLook) -> bool:
    price = look.price
    return (record.appid, record.country, record.currency, record.final, record.original, record.pct) == (
        look.appid, look.country, look.currency, price.final, price.original, price.pct
    )


def _add_to_history(session, title_id: int, look: PriceLook, now: datetime) -> None:
    """A record of the price history when the look has a price that differs from the latest record in anything."""
    if look.price is None:
        return
    latest = session.scalars(
        select(PriceRecord)
        .where(PriceRecord.title_id == title_id)
        .order_by(PriceRecord.seen_at.desc(), PriceRecord.id.desc())
        .limit(1)
    ).first()
    if latest is not None and _same_record(latest, look):
        return
    price = look.price
    session.add(PriceRecord(
        title_id=title_id, seen_at=now, appid=look.appid, country=look.country, currency=look.currency,
        final=price.final, original=price.original, pct=price.pct,
    ))


@dataclass
class _Plan:
    """What the reconciliation found: the games to get a snapshot, the snapshots to go, the snapshots whose look is of
    another Steam number or country (they become empty, so the next check is the reference point), the games to ask
    now, and the due games whose snapshot cannot be read (a failure of their check, not asked)."""

    country: str
    create: list[int] = field(default_factory=list)
    drop: list[SourceSnapshot] = field(default_factory=list)
    reset: list[SourceSnapshot] = field(default_factory=list)
    due: list[DueTitle] = field(default_factory=list)
    spoiled: list[tuple[DueTitle, Exception]] = field(default_factory=list)


@dataclass
class _Answered:
    """A game Steam answered about: its look and the events found by it (none for the reference point)."""

    game: DueTitle
    look: PriceLook
    events: list[DetectedEvent]


class GamePrices:
    """The price check of the games of `kind`; `source` is the source of prices (`SteamPriceSource`), None — none."""

    def __init__(self, kind: TitleKind, source: Any, ctx: CoreContext, settings: SettingsStore) -> None:
        self.kind = kind
        self.source = source
        self.ctx = ctx
        self.settings = settings
        self._spoiled_log = failures.DailyLog()  # «its price snapshot cannot be read», once a day per game

    async def check(self) -> list[tuple[DueTitle, Exception]]:
        """Reconcile the snapshots, ask Steam about the due games, queue the events of all of them in one write
        session, then store each look (spec 2.5 of stage 9.1b). Returns the failures of the games (for the «could not
        check» messages); each of them is looked at again in 30 minutes."""
        if self.source is None:
            return []
        plan = await asyncio.to_thread(self._reconcile)
        broken: list[tuple[DueTitle, Exception]] = list(plan.spoiled)
        if plan.due:
            answered = await self._ask(plan, broken)
            await asyncio.to_thread(self._queue_and_store, answered)
            logging.info("price check: %s games, %s failed", len(plan.due), len(broken))
        return [(game, exc) for game, exc in broken if await asyncio.to_thread(self._postpone, game)]

    async def _ask(self, plan: _Plan, broken: list[tuple[DueTitle, Exception]]) -> list[_Answered]:
        """Phase 1: every pack asked; for every game answered the events are found in a read session. The failures of
        the games join `broken`."""
        answered: list[_Answered] = []
        # the same number of two games (two records of IGDB for one game) is asked about once and serves both
        appids = list(dict.fromkeys(game.external_id for game in plan.due))
        for start in range(0, len(appids), MAX_ITEMS):
            pack = appids[start:start + MAX_ITEMS]
            asked = set(pack)
            games_of_pack = [game for game in plan.due if game.external_id in asked]
            try:
                looks = await self.source.price_looks(pack, plan.country)
            except Exception as exc:  # the whole request failed: a failure of every game of the pack
                logging.warning("price check of %s Steam apps failed: %r", len(pack), exc)
                broken += [(game, exc) for game in games_of_pack]
                continue
            for game in games_of_pack:
                answer = looks.get(game.external_id, UnreadAnswer(f"Steam app {game.external_id}: not in the answer"))
                if isinstance(answer, UnreadAnswer):
                    logging.warning("price check of title %s: %s", game.id, answer)
                    broken.append((game, answer))
                    continue
                try:
                    found = await asyncio.to_thread(self._detect, game, answer)
                except Exception:  # a bug in one game leaves the others to the check
                    logging.exception("finding the Steam events of title %s failed", game.id)
                    await asyncio.to_thread(self._postpone, game)
                    continue
                if found is not None:
                    answered.append(found)
        return answered

    def _queue_and_store(self, answered: list[_Answered]) -> None:
        """Phase 2: the events of every game in one write session (`EventQueue.enqueue_all`); phase 3: each look in a
        write session of its own. A failed queueing stores no look: the games are asked again in 30 minutes and find
        the same facts; a failed store finds them again next time, and their keys drop them."""
        now = self.ctx.now()
        batch = [
            Queued(item.game, event, (price_events.DISCOUNT,) if event.type == price_events.DISCOUNT else ())
            for item in answered for event in item.events
        ]
        if batch:
            try:
                with self.ctx.write_session() as session:
                    queued = EventQueue.enqueue_all(session, batch, now)
                    session.commit()
            except Exception:
                logging.exception("queueing the Steam events of %s games failed", len(answered))
                for item in answered:
                    self._postpone(item.game)
                return
            if queued:
                logging.info("price check: %s events of Steam queued", len(queued))
        for item in answered:
            try:
                self._store(item.game, item.look, now)
            except Exception:  # a bug in storing one game leaves the others
                logging.exception("storing the prices of title %s failed", item.game.id)
                self._postpone(item.game)

    # --- the reconciliation (spec 4.1) ---

    def _reconcile(self) -> _Plan:
        """Bring the price snapshots in line with the rule; returns the plan of the check (the country of the stores,
        the games to ask, the spoiled ones). A change is decided again in the write session that makes it, so a button
        pressed meanwhile is not undone."""
        now = self.ctx.now()
        with self.ctx.session_factory() as session:
            plan = self._plan(session, now)
        if not (plan.create or plan.drop or plan.reset):
            return plan
        with self.ctx.write_session() as session:
            plan = self._plan(session, now)
            for stored in plan.drop:
                _drop(session, stored)
            for stored in plan.reset:
                # a look of another number or country says nothing of now: checked at once, then as any snapshot
                logging.info("title %s: another Steam number or store country, prices looked at anew", stored.title_id)
                stored.state = {}
                stored.next_check_at = None
            for title_id in plan.create:
                session.add(SourceSnapshot(title_id=title_id, source=SOURCE_KEY, state={}, observed_at=now, next_check_at=None))
            session.commit()
        return plan

    def _plan(self, session, now: datetime) -> _Plan:
        """The reconciliation in six reads, however many games there are. Each snapshot is read on its own: one that
        cannot be read is neither reset nor asked (KI-50); while its game is for prices it is a failure each time it
        is due, else it goes as any."""
        scope, priced = priced_games(session, self.kind, self.settings)
        names = dict(session.execute(select(Title.id, Title.name).where(Title.id.in_(list(priced)))).all())
        snapshots = _snapshots(session, self.kind)
        plan = _Plan(scope.country)
        plan.drop = _unpriced(snapshots, priced)
        for title_id, appid in priced.items():
            stored = snapshots.get(title_id)
            game = DueTitle(title_id, self.kind, names[title_id], appid, SOURCE_KEY, sequels=False)
            try:
                another = stored is not None and _of_another(stored, appid, scope.country)
            except ValueError as spoiled:
                self._spoiled_log.warning(
                    title_id, now, "title %s: its price snapshot cannot be read: %r", title_id, spoiled
                )
                if _due(stored, now):
                    plan.spoiled.append((game, spoiled))
                continue
            if stored is None:
                plan.create.append(title_id)
            elif another:
                plan.reset.append(stored)
            if stored is None or another or _due(stored, now):
                plan.due.append(game)
        return plan

    # --- a press (spec 3.1 of stage 9.1b) ---

    def drop_unpriced(self, session, title_ids: Collection[int] | None) -> None:
        """In the write session of a press: the price snapshots of the games `title_ids` (None — every game of the
        kind) that are no longer «игра для цен» go with their undelivered Steam events — the reconciliation's own drop,
        applied at once, so a check answering after the press finds no snapshot and queues nothing (KI-47). A press
        never makes a snapshot: only the reconciliation does, at the start of a pass."""
        _, priced = priced_games(session, self.kind, self.settings)
        for stored in _unpriced(_snapshots(session, self.kind, title_ids), priced):
            _drop(session, stored)

    # --- storing (spec 4.3–4.5) ---

    def _detect(self, game: DueTitle, look: PriceLook) -> _Answered | None:
        """The events of the look, read against the stored one (none for the reference point). None — the snapshot is
        gone while Steam was answering (a press or a deletion): nothing to queue or store, and no failure."""
        now = self.ctx.now()
        with self.ctx.session_factory() as session:
            stored = storage.snapshot_of(session, game.id, SOURCE_KEY)
            if stored is None:
                logging.info("title %s: its price snapshot went while Steam was answering", game.id)
                return None
            old = PriceLook.from_state(stored.state)
            if is_baseline(old, look):
                logging.info("title %s: first price check of Steam app %s in %s, the baseline", game.id, look.appid, look.country)
                return _Answered(game, look, [])
            # «самая низкая» by the history before this check; the end of a discount on the owner's clock
            events = price_events.detect_events(
                game.id, game.name, old, look, now, self.settings.time_zone(session),
                lowest_seen(session, game.id, look), stored.observed_at,
            )
        return _Answered(game, look, events)

    def _store(self, game: DueTitle, look: PriceLook, now: datetime) -> None:
        """The look becomes the snapshot, a changed price a record of the history. A snapshot gone meanwhile (a press,
        a deletion) is no failure: nothing is written."""
        with self.ctx.write_session() as session:
            stored = storage.snapshot_of(session, game.id, SOURCE_KEY)
            if stored is None:
                logging.info("title %s: its price snapshot went while its prices were checked", game.id)
                return
            _add_to_history(session, game.id, look, now)
            stored.state = look.state()
            stored.observed_at = now
            stored.next_check_at = now + PRICE_INTERVAL
            session.commit()

    def _postpone(self, game: DueTitle) -> bool:
        """The next price check of the game in 30 minutes. False — its snapshot is gone (a press, or the game was
        deleted while Steam was answering): nothing failed then."""
        with self.ctx.write_session() as session:
            stored = storage.snapshot_of(session, game.id, SOURCE_KEY)
            if stored is None:
                return False
            stored.next_check_at = self.ctx.now() + RETRY_AFTER_FAILURE
            session.commit()
            return True


def _snapshots(session, kind: TitleKind, title_ids: Collection[int] | None = None) -> dict[int, SourceSnapshot]:
    """The price snapshots of the games of the kind (or of `title_ids` among them), title → snapshot, in one read."""
    query = select(SourceSnapshot).where(
        SourceSnapshot.source == SOURCE_KEY, SourceSnapshot.title_id.in_(select(Title.id).where(Title.kind == kind))
    )
    if title_ids is not None:
        query = query.where(SourceSnapshot.title_id.in_(list(title_ids)))
    return {stored.title_id: stored for stored in session.scalars(query)}


def _unpriced(snapshots: dict[int, SourceSnapshot], priced: Collection[int]) -> list[SourceSnapshot]:
    """The snapshots of the games that are no longer «игра для цен» (`priced`: the games that are): they go. The one
    place of the rule «drop», for the reconciliation and for a press."""
    return [stored for title_id, stored in snapshots.items() if title_id not in priced]


def _drop(session, stored: SourceSnapshot) -> None:
    """A price snapshot goes, and with it the undelivered events of Steam of its game (the price history stays)."""
    logging.info("title %s: its prices are no longer checked, the price snapshot goes", stored.title_id)
    session.delete(stored)
    EventQueue.withdraw(session, stored.title_id, price_events.TYPES)


def _due(stored: SourceSnapshot, now: datetime) -> bool:
    """The snapshot's time has come. An empty one that is not due yet waits: its first check failed, the next one is
    in 30 minutes."""
    return stored.next_check_at is None or stored.next_check_at <= now


def _of_another(stored: SourceSnapshot, appid: str, country: str) -> bool:
    """The snapshot keeps a look of another Steam number or store country than now (IGDB changed the number, the owner
    changed the country): the reconciliation empties it, so its next check is now and is the reference point."""
    look = PriceLook.from_state(stored.state)
    return look is not None and not look.is_of(appid, country)

