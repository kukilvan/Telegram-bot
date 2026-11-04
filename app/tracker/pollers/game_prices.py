"""The price check at the end of a polling pass: which games have their Steam prices checked, the requests in packs of
100, the reference point, the price history and the failures (spec 4 of part 6.2).

Each pass (every minute) the price snapshots (source `steam`) are first brought in line with the rule «игра для цен»
(`steam_number`), in a number of reads that does not grow with the number of games: a game for prices without a
snapshot gets an empty one, due now; the snapshot of a game that is no longer one goes, and with it the undelivered
events of Steam of that game (the price history stays). No button touches the price snapshots: the rule lives here.
Then the due games are asked about, all in the country of the stores of now; the request holds no database, and each
game is written in a write session of its own (rule 9). Unless the check is the reference point, the previous look and
the new one are compared (`price_events`) and the events are queued first, each in a session of its own (a new
discount takes the undelivered one of the game out of the queue); then the look and the history are stored, so a
failed store finds the same facts again and their keys drop them.
"""

import asyncio
import logging
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.providers.steam import MAX_ITEMS
from app.tracker import games, price_events, storage
from app.tracker.context import CoreContext
from app.tracker.game_scope import GameScope
from app.tracker.models import PriceRecord, SourceSnapshot, Title, TitleKind, TitleStatus
from app.tracker.movie_events import RETRY_AFTER_FAILURE, DetectedEvent
from app.tracker.platforms import Platform
from app.tracker.pollers.base import DueTitle
from app.tracker.prices import Lowest, PriceLook, lowest
from app.tracker.queue import EventQueue
from app.tracker.settings_store import SettingsStore
from app.tracker.sources.steam_prices import SOURCE_KEY, UnreadAnswer

PRICE_INTERVAL = timedelta(hours=6)  # after a price check that worked; after a failure — `RETRY_AFTER_FAILURE`

# the types of the events of Steam (spec 5.1): what goes out of the queue when a game's prices are no longer checked
STEAM_EVENTS = price_events.TYPES


def steam_number(status: TitleStatus, game: games.GameState, told: Collection[Platform]) -> str | None:
    """The Steam number whose prices are checked for a game (spec 4.1); None — its prices are not checked. The game is
    in «Хочу», IGDB gave its Steam number, it is on PC and the owner is told about PC in it (`GameScope.told`: PC among
    «Мои платформы» and marked «играю здесь»). Whether the core has a source of prices is not this rule's business."""
    if status != TitleStatus.WANT or not game.steam_id:
        return None
    if Platform.PC not in told or not games.has_platform(game, Platform.PC):
        return None
    return game.steam_id


def is_baseline(old: PriceLook | None, new: PriceLook) -> bool:
    """The check is the reference point (spec 4.3): nothing was looked at before (the snapshot was just made), or the
    previous look asked about another Steam number or in another country. Its look is stored, no event comes of it."""
    return old is None or (old.appid, old.country) != (new.appid, new.country)


def lowest_seen(session, title_id: int, look: PriceLook) -> Lowest | None:
    """«Самая низкая с добавления» of a game by its price history, for the number, the country and the currency of
    `look` (`prices.lowest`); None — no record of them, or the look has no currency."""
    if look.currency is None:
        return None
    records = session.scalars(select(PriceRecord).where(PriceRecord.title_id == title_id))
    return lowest(records, look.appid, look.country, look.currency)


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


def _snapshot(session, title_id: int) -> SourceSnapshot | None:
    return session.scalar(
        select(SourceSnapshot).where(SourceSnapshot.title_id == title_id, SourceSnapshot.source == SOURCE_KEY)
    )


@dataclass
class _Plan:
    """What the reconciliation found: the games to get a snapshot, the snapshots to go, the games to ask now."""

    country: str
    create: list[int] = field(default_factory=list)
    drop: list[SourceSnapshot] = field(default_factory=list)
    due: list[DueTitle] = field(default_factory=list)


class GamePrices:
    """The price check of the games of `kind`; `source` is the source of prices (`SteamPriceSource`), None — none."""

    def __init__(self, kind: TitleKind, source: Any, ctx: CoreContext, settings: SettingsStore) -> None:
        self.kind = kind
        self.source = source
        self.ctx = ctx
        self.settings = settings

    async def check(self) -> list[tuple[DueTitle, Exception]]:
        """Reconcile the snapshots, ask Steam about the due games and store what it answered. Returns the failures of
        the games (for the «could not check» messages); each of them is looked at again in 30 minutes."""
        if self.source is None:
            return []
        country, due = await asyncio.to_thread(self._reconcile)
        if not due:
            return []
        broken: list[tuple[DueTitle, Exception]] = []
        # the same number of two games (two records of IGDB for one game) is asked about once and serves both
        appids = list(dict.fromkeys(game.external_id for game in due))
        for start in range(0, len(appids), MAX_ITEMS):
            pack = appids[start:start + MAX_ITEMS]
            asked = set(pack)
            games_of_pack = [game for game in due if game.external_id in asked]
            try:
                looks = await self.source.price_looks(pack, country)
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
                    await asyncio.to_thread(self._store, game, answer)
                except Exception:  # a bug in storing one game leaves the others to the check
                    logging.exception("storing the prices of title %s failed", game.id)
                    await asyncio.to_thread(self._postpone, game)
        logging.info("price check: %s games, %s Steam apps, %s failed", len(due), len(appids), len(broken))
        return [(game, exc) for game, exc in broken if await asyncio.to_thread(self._postpone, game)]

    # --- the reconciliation (spec 4.1) ---

    def _reconcile(self) -> tuple[str, list[DueTitle]]:
        """Bring the price snapshots in line with the rule; returns the country of the stores and the games to ask.
        A change is decided again in the write session that makes it, so a button pressed meanwhile is not undone."""
        now = self.ctx.now()
        with self.ctx.session_factory() as session:
            plan = self._plan(session, now)
        if not (plan.create or plan.drop):
            return plan.country, plan.due
        with self.ctx.write_session() as session:
            plan = self._plan(session, now)
            for stored in plan.drop:
                logging.info("title %s: its prices are no longer checked, the price snapshot goes", stored.title_id)
                session.delete(stored)
                EventQueue.withdraw(session, stored.title_id, STEAM_EVENTS)
            for title_id in plan.create:
                session.add(SourceSnapshot(title_id=title_id, source=SOURCE_KEY, state={}, observed_at=now, next_check_at=None))
            session.commit()
        return plan.country, plan.due

    def _plan(self, session, now: datetime) -> _Plan:
        """The reconciliation in six reads, however many games there are."""
        of_kind = select(Title.id).where(Title.kind == self.kind)
        wanted = of_kind.where(Title.status == TitleStatus.WANT)
        names = dict(session.execute(select(Title.id, Title.name).where(Title.id.in_(wanted))).all())
        states = storage.own_states_of(session, wanted)
        scope = GameScope.read(self.settings, session, wanted)
        snapshots = {
            stored.title_id: stored
            for stored in session.scalars(
                select(SourceSnapshot).where(SourceSnapshot.source == SOURCE_KEY, SourceSnapshot.title_id.in_(of_kind))
            )
        }
        priced = {}
        for title_id in sorted(states):
            appid = steam_number(TitleStatus.WANT, games.GameState.from_state(states[title_id]), scope.told(title_id))
            if appid is not None:
                priced[title_id] = appid
        plan = _Plan(scope.country)
        plan.drop = [stored for title_id, stored in snapshots.items() if title_id not in priced]
        for title_id, appid in priced.items():
            stored = snapshots.get(title_id)
            if stored is None:
                plan.create.append(title_id)
            if stored is None or _due(stored, appid, scope.country, now):
                plan.due.append(DueTitle(title_id, self.kind, names[title_id], appid, SOURCE_KEY, sequels=False))
        return plan

    # --- storing (spec 4.3–4.5) ---

    def _store(self, game: DueTitle, look: PriceLook) -> None:
        """The events of the look, then the look becomes the snapshot, a changed price a record of the history. A
        snapshot gone while Steam was answering (the game was deleted) is no failure: nothing is written."""
        now = self.ctx.now()
        with self.ctx.session_factory() as session:
            stored = _snapshot(session, game.id)
            if stored is None:
                logging.info("title %s was deleted while its prices were checked", game.id)
                return
            old = PriceLook.from_state(stored.state)
            if is_baseline(old, look):
                logging.info("title %s: first price check of Steam app %s in %s, the baseline", game.id, look.appid, look.country)
                events = []
            else:
                # «самая низкая» by the history before this check; the end of a discount on the owner's clock
                events = price_events.detect_events(
                    game.id, game.name, old, look, now, self.settings.time_zone(session),
                    lowest_seen(session, game.id, look), stored.observed_at,
                )
        found = sum(self._queue(game.id, event, now) for event in events)
        if found:
            logging.info("title %s: %s events of Steam", game.id, found)
        with self.ctx.write_session() as session:
            stored = _snapshot(session, game.id)
            if stored is None:
                logging.info("title %s was deleted while its prices were checked", game.id)
                return
            _add_to_history(session, game.id, look, now)
            stored.state = look.state()
            stored.observed_at = now
            stored.next_check_at = now + PRICE_INTERVAL
            session.commit()

    def _queue(self, title_id: int, event: DetectedEvent, now: datetime) -> bool:
        """Queue an event of Steam; False — its fact is known already, or the game's prices are no longer checked. A
        new discount takes the undelivered one of the game out of the queue: one line about it in a summary."""
        with self.ctx.write_session() as session:
            if _snapshot(session, title_id) is None:
                return False
            if event.type == price_events.DISCOUNT:
                EventQueue.withdraw(session, title_id, (price_events.DISCOUNT,))
            payload = {"text": event.text, **event.data}
            if EventQueue.enqueue(session, event.type, payload, event.dedup_key, title_id, now) is None:
                return False  # rolled back: the undelivered discount stays too
            session.commit()
            return True

    def _postpone(self, game: DueTitle) -> bool:
        """The next price check of the game in 30 minutes. False — its snapshot is gone (the game was deleted while
        Steam was answering): nothing failed then."""
        with self.ctx.write_session() as session:
            stored = _snapshot(session, game.id)
            if stored is None:
                return False
            stored.next_check_at = self.ctx.now() + RETRY_AFTER_FAILURE
            session.commit()
            return True


def _due(stored: SourceSnapshot, appid: str, country: str, now: datetime) -> bool:
    """The snapshot's time has come, or it asked about another number or country than now (a check now, the baseline).
    An empty one that is not due yet waits: its first check failed."""
    if stored.next_check_at is None or stored.next_check_at <= now:
        return True
    look = PriceLook.from_state(stored.state)
    return look is not None and (look.appid, look.country) != (appid, country)

