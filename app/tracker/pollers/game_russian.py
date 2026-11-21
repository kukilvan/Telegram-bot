"""The official Russian check at the end of a polling pass: which games, the reconciliation, the due games, Steam in packs of 100, the reference point, the events, the store and the card's view.

Spec 5.3–5.5, 5.9 and 3.1 of stage 9.1b (idea 002). What a look is and what it means — the pure `russian`; the texts —
`russian_events`; Steam's answer — `sources/steam_languages`.

Each pass (every minute), after the prices and the follow-ups, the snapshots `russian_official` are brought in line with
the rule «игра для русского» (`for_russian`: «Хочу» or «В процессе», any platforms) in a constant number of reads: such
a game without a snapshot gets an empty one (`{}`), due now. A snapshot is never dropped (the card keeps the line;
deleting a title deletes it), so a press makes none and drops none: it only withdraws the undelivered Russian events of
the games that left «Хочу» and «В процессе» (`withdraw_left`). The due games are the games for Russian whose time has
come, never-checked ones first; a game that left the two statuses is not due, so its check stops.

The check works in three phases, as the prices. First, in one read session, each due game: its stored look (spoiled — a
failure), its own state (unreadable — skipped, a log line a day: its own poll reports it), its Steam number and what
IGDB says. Then Steam is asked about the games with a Steam number, in packs of 100, in the store of the United States
(the same number of two games asked once); a failed request is a failure of every game of the pack, an unreadable
answer of one game a failure of that game. The look of each game (`russian.next_look`) and its events: none for the
reference point (`russian.is_reference`: an empty snapshot, another Steam number, the first check after «Вернуть в
список» — the stored look older than `restored_at`), else one event of the parts that appeared. Second, the events of
all the games in one write session (`EventQueue.enqueue_all`, the check of each game ending when its status leaves the
two: `DueTitle.statuses`). Third, each look stored in a write session of its own, next check in 6 hours; while Steam
has none and IGDB is «not asked yet» nothing is stored (the snapshot stays `{}`). A failure waits 30 minutes and joins
the «could not check» messages of the pass, with the source «Steam».
"""

import asyncio
import logging
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from sqlalchemy import or_, select

from app.providers.steam import MAX_ITEMS
from app.tracker import failures, games, russian, russian_events, storage
from app.tracker.cards import RussianView, local_moment
from app.tracker.context import PRIMARY_ROLE, CoreContext
from app.tracker.game_scope import GameScope
from app.tracker.models import DeliveryItem, DeliveryStatus, Event, ExternalId, SourceSnapshot, Title, TitleKind, TitleStatus
from app.tracker.moment_words import moment_in_words
from app.tracker.movie_events import RETRY_AFTER_FAILURE, DetectedEvent
from app.tracker.pollers.base import DueTitle
from app.tracker.queue import EventQueue, Queued
from app.tracker.russian import Look, Support
from app.tracker.settings_store import SettingsStore
from app.tracker.sources.steam_prices import UnreadAnswer

SOURCE_KEY = "russian_official"
RUSSIAN_STATUSES = (TitleStatus.WANT, TitleStatus.IN_PROGRESS)  # «Хочу», «В процессе»
RUSSIAN_INTERVAL = timedelta(hours=6)  # after a check that worked; after a failure — `RETRY_AFTER_FAILURE`

# The hints under the line of the web card (spec 5.3), in this order
HINT_CHECKED = "{source} — проверено {moment}"
HINT_NOT_CHECKED = "Ещё не проверяли — строка появится через минуту-другую"
HINT_PC = "(ПК) — данные о версии для ПК, а вы играете ещё и на другой платформе"
HINT_NO_DATA_STEAM = "Языки ещё не объявлены. Проверяю: Steam — каждые 6 часов, ZoG — раз в неделю"
HINT_NO_DATA_IGDB = "Языки ещё не объявлены. Проверяю: IGDB — вместе с датами игры, ZoG — раз в неделю"
HINT_OTHER_STATUS = "Игра не в «Хочу» и не «В процессе» — русский язык больше не проверяется"
_SOURCE_WORDS = {russian.STEAM: "Steam", russian.IGDB: "IGDB"}


def for_russian(status: TitleStatus) -> bool:
    """«Игра для русского» (spec 5.5), the one place of the rule: the game is in «Хочу» or «В процессе»."""
    return status in RUSSIAN_STATUSES


@dataclass(frozen=True)
class _Game:
    """A due game as its check reads it: the check, the stored look and its moment, whether this is the first check
    after «Вернуть в список», the Steam number, what IGDB says, whether the owner plays on another platform too."""

    due: DueTitle
    previous: Look | None
    observed_at: datetime
    restored: bool
    appid: str | None
    igdb: russian.IgdbRussian
    elsewhere: bool


@dataclass(frozen=True)
class _Answered:
    """A game checked: its look (None — nothing to store) and the events found by it."""

    game: _Game
    look: Look | None
    events: list[DetectedEvent]


class GameRussian:
    """The official Russian check of the games of `kind`; `source` is the source of Steam's languages
    (`SteamLanguageSource`), None — no check (and no block on the card)."""

    def __init__(self, kind: TitleKind, source, ctx: CoreContext, settings: SettingsStore) -> None:
        self.kind = kind
        self.source = source
        self.ctx = ctx
        self.settings = settings
        self._unreadable_log = failures.DailyLog()  # «its own snapshot / its look cannot be read», once a day per game

    async def check(self) -> list[tuple[DueTitle, Exception]]:
        """Reconcile the snapshots, read the due games, ask Steam, queue the events of all of them in one write session,
        then store each look. Returns the failures of the games (for the «could not check» messages); each of them is
        looked at again in 30 minutes."""
        if self.source is None:
            return []
        due = await asyncio.to_thread(self._reconcile)
        if not due:
            return []
        read, broken = await asyncio.to_thread(self._read, due)
        answered = await self._ask(read, broken)
        await asyncio.to_thread(self._queue_and_store, answered)
        logging.info("Russian check: %s games, %s failed", len(due), len(broken))
        return [(game, exc) for game, exc in broken if await asyncio.to_thread(self._postpone, game)]

    # --- the reconciliation and the due games ---

    def _reconcile(self) -> list[DueTitle]:
        """An empty snapshot for every game for Russian without one (decided again in the write session that makes
        them); returns the due games, never-checked first, then the earliest, then by title."""
        now = self.ctx.now()
        with self.ctx.session_factory() as session:
            missing = self._missing(session)
        if missing:
            with self.ctx.write_session() as session:
                for title_id in self._missing(session):
                    session.add(SourceSnapshot(title_id=title_id, source=SOURCE_KEY, state={}, observed_at=now, next_check_at=None))
                session.commit()
        with self.ctx.session_factory() as session:
            rows = session.execute(
                select(Title.id, Title.name, ExternalId.external_id)
                .join(SourceSnapshot, SourceSnapshot.title_id == Title.id)
                .join(ExternalId, (ExternalId.title_id == Title.id) & (ExternalId.role == PRIMARY_ROLE))
                .where(
                    Title.kind == self.kind,
                    Title.status.in_(RUSSIAN_STATUSES),
                    SourceSnapshot.source == SOURCE_KEY,
                    or_(SourceSnapshot.next_check_at.is_(None), SourceSnapshot.next_check_at <= now),
                )
                .order_by(SourceSnapshot.next_check_at.is_not(None), SourceSnapshot.next_check_at, Title.id)
            )
            return [
                DueTitle(title_id, self.kind, name, external_id, SOURCE_KEY, sequels=False, statuses=RUSSIAN_STATUSES)
                for title_id, name, external_id in rows
            ]

    def _missing(self, session) -> list[int]:
        """The games for Russian without a snapshot, in one read."""
        have = select(SourceSnapshot.title_id).where(SourceSnapshot.source == SOURCE_KEY)
        return list(session.scalars(
            select(Title.id)
            .where(Title.kind == self.kind, Title.status.in_(RUSSIAN_STATUSES), Title.id.not_in(have))
            .order_by(Title.id)
        ))

    # --- phase 1: read and ask ---

    def _read(self, due: list[DueTitle]) -> tuple[list[_Game], list[tuple[DueTitle, Exception]]]:
        """Each due game read in one session (a constant number of reads); a spoiled look is a failure of the game, an
        unreadable own state skips the game (a log line a day)."""
        now = self.ctx.now()
        ids = [game.id for game in due]
        with self.ctx.session_factory() as session:
            owns = storage.own_states_of(session, select(Title.id).where(Title.id.in_(ids)))
            snapshots = {
                stored.title_id: stored for stored in session.scalars(
                    select(SourceSnapshot).where(SourceSnapshot.source == SOURCE_KEY, SourceSnapshot.title_id.in_(ids))
                )
            }
            restored_at = dict(session.execute(select(Title.id, Title.restored_at).where(Title.id.in_(ids))).all())
            scope = GameScope.read(self.settings, session, ids)
        read: list[_Game] = []
        broken: list[tuple[DueTitle, Exception]] = []
        for game in due:
            stored = snapshots.get(game.id)
            if stored is None:  # deleted between the two reads
                continue
            try:
                own = games.GameState.from_state(owns.get(game.id, {}))
            except (ValueError, TypeError, KeyError, AttributeError) as spoiled:
                self._unreadable_log.warning(
                    ("own", game.id), now, "title %s: its own snapshot cannot be read, Russian not checked: %r",
                    game.id, spoiled,
                )
                continue
            try:
                previous = Look.from_state(stored.state)
            except ValueError as spoiled:
                self._unreadable_log.warning(
                    ("look", game.id), now, "title %s: its official Russian look cannot be read: %r", game.id, spoiled
                )
                broken.append((game, spoiled))
                continue
            back = restored_at.get(game.id)
            read.append(_Game(
                game, previous, stored.observed_at, back is not None and stored.observed_at < back, own.steam_id or None,
                own.russian, _played_elsewhere(scope, game.id, own),
            ))
        return read, broken

    async def _ask(self, read: list[_Game], broken: list[tuple[DueTitle, Exception]]) -> list[_Answered]:
        """Steam asked about the games with a Steam number, in packs of 100; the look and the events of every game
        answered. The failures of the games join `broken`."""
        answers: dict[str, Support | None | Exception] = {}
        appids = list(dict.fromkeys(game.appid for game in read if game.appid))
        for start in range(0, len(appids), MAX_ITEMS):
            pack = appids[start:start + MAX_ITEMS]
            try:
                answers.update(await self.source.russian(pack))
            except Exception as exc:  # the whole request failed: a failure of every game of the pack
                logging.warning("Russian check of %s Steam apps failed: %r", len(pack), exc)
                answers.update(dict.fromkeys(pack, exc))
        answered: list[_Answered] = []
        for game in read:
            steam = answers.get(game.appid, UnreadAnswer(f"Steam app {game.appid}: not in the answer")) if game.appid else None
            if isinstance(steam, Exception):
                if isinstance(steam, UnreadAnswer):
                    logging.warning("Russian check of title %s: %s", game.due.id, steam)
                broken.append((game.due, steam))
                continue
            answered.append(_decide(game, steam))
        return answered

    # --- phases 2 and 3: queue, then store ---

    def _queue_and_store(self, answered: list[_Answered]) -> None:
        """The events of every game in one write session; then each look in a write session of its own. A failed
        queueing stores no look: the games are asked again in 30 minutes and find the same facts; a failed store finds
        them again next time, and their keys drop them."""
        now = self.ctx.now()
        batch = [Queued(item.game.due, event) for item in answered for event in item.events]
        if batch:
            try:
                with self.ctx.write_session() as session:
                    queued = EventQueue.enqueue_all(session, batch, now)
                    session.commit()
            except Exception:
                logging.exception("queueing the Russian events of %s games failed", len(answered))
                for item in answered:
                    self._postpone(item.game.due)
                return
            if queued:
                logging.info("Russian check: %s events queued", len(queued))
        for item in answered:
            try:
                self._store(item, now)
            except Exception:  # a bug in storing one game leaves the others
                logging.exception("storing the Russian look of title %s failed", item.game.due.id)
                self._postpone(item.game.due)

    def _store(self, item: _Answered, now: datetime) -> None:
        """The look becomes the snapshot, next check in 6 hours. No look (Steam silent, IGDB «not asked yet») — the
        snapshot stays as it was: a game with a Steam page waits 6 hours (Steam is not asked every minute), one without
        stays due, so the first pass after its own poll records the look (no request is made for it). A snapshot gone
        meanwhile (a deletion) is no failure: nothing is written."""
        with self.ctx.write_session() as session:
            stored = storage.snapshot_of(session, item.game.due.id, SOURCE_KEY)
            if stored is None:
                logging.info("title %s: its Russian snapshot went while it was checked", item.game.due.id)
                return
            if item.look is not None:
                stored.state = item.look.state()
                stored.observed_at = now
            if item.look is not None or item.game.appid is not None:
                stored.next_check_at = now + RUSSIAN_INTERVAL
            session.commit()

    def _postpone(self, game: DueTitle) -> bool:
        """The next check of the game in 30 minutes. False — nothing failed for the owner: the snapshot is gone, or the
        game left «Хочу» and «В процессе» while Steam answered."""
        with self.ctx.write_session() as session:
            stored = storage.snapshot_of(session, game.id, SOURCE_KEY)
            title = session.get(Title, game.id)
            if stored is None or title is None:
                return False
            stored.next_check_at = self.ctx.now() + RETRY_AFTER_FAILURE
            session.commit()
            return for_russian(title.status)

    # --- a press (spec 3.1 and 5.9) ---

    def withdraw_left(self, session, title_ids: Collection[int] | None) -> None:
        """In the write session of a press: the undelivered Russian events of the games `title_ids` (None — every game
        of the kind) that are no longer in «Хочу» or «В процессе» are withdrawn; their snapshots stay (the card keeps
        the line), and «Вернуть в список» makes the next check the reference point."""
        query = (
            select(Event.title_id)
            .join(DeliveryItem, DeliveryItem.event_id == Event.id)
            .join(Title, Title.id == Event.title_id)
            .where(
                Event.type.in_(russian_events.TYPES),
                DeliveryItem.status == DeliveryStatus.PENDING,
                Title.kind == self.kind,
                Title.status.not_in(RUSSIAN_STATUSES),
            )
            .distinct()
        )
        if title_ids is not None:
            query = query.where(Title.id.in_(list(title_ids)))
        for title_id in list(session.scalars(query)):
            logging.info("title %s: no longer checked for Russian, its undelivered Russian events go", title_id)
            EventQueue.withdraw(session, title_id, russian_events.TYPES)

    # --- what the card reads (spec 5.3, 5.4) ---

    def card_view(
        self, session, title: Title, game: games.GameState, scope: GameScope, tz: tzinfo
    ) -> RussianView | None:
        """Russian on the card of `title` (`game`: its own state): the line and the hints. None — the core has no source
        of the check; the game is in another status with nothing known; its look cannot be read (the check reports it).
        Before the first check the line reads by what IGDB gave. One read: the snapshot."""
        if self.source is None:
            return None
        stored = storage.snapshot_of(session, title.id, SOURCE_KEY)
        try:
            look = Look.from_state(stored.state) if stored is not None else None
        except ValueError as spoiled:
            logging.warning("title %s: a spoiled official Russian look, no block on its card: %r", title.id, spoiled)
            return None
        active = for_russian(title.status)
        if look is not None and look.support is not None:
            official, pc, source = look.support, look.pc_only, look.source
        elif isinstance(game.russian, Support):  # nothing checked yet, or checked with no data: IGDB has some now
            official, pc, source = game.russian, False, russian.IGDB
        else:
            official, pc, source = None, False, russian.STEAM if (look and look.appid) else russian.IGDB
        line = russian.line(official, pc, None, _played_elsewhere(scope, title.id, game))
        if not active and line.no_data:
            return None
        hints: list[str] = []
        if look is not None:
            now = local_moment(self.ctx.now(), tz)
            moment = moment_in_words(local_moment(stored.observed_at, tz), now)
            hints.append(HINT_CHECKED.format(source=_SOURCE_WORDS[source], moment=moment))
        elif active:
            hints.append(HINT_NOT_CHECKED)
        if line.pc:
            hints.append(HINT_PC)
        if line.no_data and look is not None:
            hints.append(HINT_NO_DATA_STEAM if game.steam_id else HINT_NO_DATA_IGDB)
        if not active:
            hints.append(HINT_OTHER_STATUS)
        return RussianView(line.text, tuple(hints))


def _played_elsewhere(scope: GameScope, title_id: int, game: games.GameState) -> bool:
    """The owner has «играю здесь» in the game on a platform other than PC that the game is on (`GameScope.told`
    counts a platform without a row as marked; here only the game's own platforms count)."""
    return russian.elsewhere([platform for platform in scope.told(title_id) if games.has_platform(game, platform)])


def _decide(game: _Game, steam: Support | None) -> _Answered:
    """The look of the check and its events (none for the reference point; one event of the parts that appeared)."""
    look = russian.next_look(game.previous, steam, game.igdb, game.appid)
    if look is None:
        return _Answered(game, None, [])
    if russian.is_reference(game.previous, look, game.restored):
        logging.info("title %s: official Russian check, the reference point (%s)", game.due.id, look.source)
        return _Answered(game, look, [])
    parts = russian.appeared(game.previous.support, look.support)
    if parts is None:
        return _Answered(game, look, [])
    event = russian_events.official_event(
        game.due.id, game.due.name, parts, look.source, look.appid, look.pc_only and game.elsewhere, game.observed_at
    )
    return _Answered(game, look, [event])
