"""The ZoG check at the end of a polling pass: the fan Russian of the games read from their pages on ZoG, and the card's part of it.

The reconciliation, two games a pass, finding a page, the reference point, the events and the store. Spec 5.3, 5.6, 5.9 of stage 9.1b, ADR 0016. What a page says and how one is found — the pure `sources/zog_pages`; the
state and its news — `russian.FanLook`, `russian.fan_news`; the texts — `russian_events`; the client —
`app/providers/zog.py`.

After the official check (`pollers/game_russian`), for the same games («Хочу» or «В процессе», `for_russian`): the
snapshots `zog` are reconciled as the official ones (an empty one, due now, for a game without one; none dropped). At
most two games are asked a pass (`ZOG_PER_PASS`), never-checked first, then the earliest, one request at a time with a
pause of a second between them. A game rejected by the owner is never asked: its next check is set a week on. A game
with a page asks it: a game page gives its support; «Ошибка» (the page renamed on ZoG) — the page is found again; an
unreadable layout keeps the last support of the page (`unreadable`, a log line a day). A game without a page finds one:
the addresses of its original name in order (at most four, each once); the first game page is taken when its name and
year match the game (`zog_pages.matches`), else refused; nothing taken — «not found». A week after a check; after a
failure six hours and a log line, no message to the owner (ZoG is a small community site, the card shows when it was
read).

The owner's page (a link pasted, «Не та игра») is `zog_page`; a state it saved while ZoG was being asked stays: the
look that was asked is dropped with its events (`_moved`).

The events of a game queue in one write session that also reads the official part now (decision 1: a fan part the
official has is not told) and asks `still_checked` with `DueTitle.statuses`; then the state is stored. The first read
of a page and the first check after «Вернуть в список» are the reference point (`russian.fan_news`).
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo

from app.tracker import failures, games, russian, russian_events, storage
from app.tracker.context import CoreContext
from app.tracker.game_scope import GameScope
from app.tracker.models import Title, TitleKind
from app.tracker.pollers.base import DueTitle
from app.tracker.pollers.game_russian import (
    SOURCE_KEY as OFFICIAL_KEY, FanCard, checked_hint, for_russian, played_elsewhere, reconcile,
)
from app.tracker.queue import EventQueue, Queued
from app.tracker.russian import FanLook, Look
from app.tracker.settings_store import SettingsStore
from app.tracker.sources import zog_pages

SOURCE_KEY = "zog"
ZOG_PER_PASS = 2  # games asked a pass
ZOG_INTERVAL = timedelta(days=7)  # after a check; a rejected page is passed by for as long
ZOG_RETRY = timedelta(hours=6)  # after a failure
PAUSE_SECONDS = 1.0  # between two requests to ZoG
sleep = asyncio.sleep  # the pause; a test puts a fake clock here

# The hints of the page under the line of the web card (spec 5.3)
HINT_NOT_FOUND = "Страница на ZoG не найдена — вставьте ссылку, если перевод есть"
HINT_REJECTED = "Страница на ZoG не указана — вставьте ссылку, если перевод есть"
HINT_UNREADABLE = "Страницу на ZoG не удалось прочитать — народный перевод пока неизвестен"
ZOG_WORD = "ZoG"


@dataclass(frozen=True)
class _Game:
    """A due game as its check reads it: the check, the stored state and its moment, whether this is the first check
    after «Вернуть в список», the names and the year a found page must match, whether the owner plays elsewhere too."""

    due: DueTitle
    previous: FanLook | None
    observed_at: datetime
    restored: bool
    names: tuple[str, ...]  # the original name first (the addresses are made of it), then the Russian one
    year: int | None
    elsewhere: bool
    stored: dict  # the state as it was read: another one at the end means the owner saved a page meanwhile


class _Keep(Exception):
    """The check read something it cannot use (an unreadable page while finding one): the state stays, next check in a
    week."""


class GameZog:
    """The ZoG check of the games of `kind`; `source` is the ZoG client (`ZogProvider`), None — no check (and no fan
    part on the card)."""

    def __init__(self, kind: TitleKind, source, ctx: CoreContext, settings: SettingsStore) -> None:
        self.kind = kind
        self.source = source
        self.ctx = ctx
        self.settings = settings
        self._log = failures.DailyLog()  # «a spoiled state», «an unreadable layout»: once a day per game
        self._asked = False  # a request was made in this pass: the next one waits `PAUSE_SECONDS`

    async def check(self) -> list[tuple[DueTitle, Exception]]:
        """Reconcile the snapshots and check at most two due games. Never returns a failure: ZoG failures are not told
        to the owner (a log line, the next check in six hours)."""
        if self.source is None:
            return []
        due = await asyncio.to_thread(reconcile, self.ctx, self.kind, SOURCE_KEY)
        self._asked = False
        asked = 0
        for title in due:
            if asked >= ZOG_PER_PASS:
                break
            game = await asyncio.to_thread(self._read, title)
            if game is None:
                continue
            if game.previous is not None and game.previous.by == russian.REJECTED:
                await asyncio.to_thread(self._next_check, title, ZOG_INTERVAL)  # never asked
                continue
            asked += 1
            try:
                new = await self._look(game)
            except _Keep:
                await asyncio.to_thread(self._next_check, title, ZOG_INTERVAL)
                continue
            except Exception as exc:  # ZoG did not answer, or a bug in reading one game: the others go on
                logging.warning("ZoG check of title %s failed, again in 6 hours: %r", title.id, exc)
                await asyncio.to_thread(self._next_check, title, ZOG_RETRY)
                continue
            await asyncio.to_thread(self._queue_and_store, game, new)
        if asked:
            logging.info("ZoG check: %s games asked", asked)
        return []

    # --- read and ask ---

    def _read(self, due: DueTitle) -> _Game | None:
        """The game as the check needs it, in one read session; None — its snapshot went, or its state is spoiled (a
        log line a day, again in six hours)."""
        now = self.ctx.now()
        with self.ctx.session_factory() as session:
            stored = storage.snapshot_of(session, due.id, SOURCE_KEY)
            title = session.get(Title, due.id)
            if stored is None or title is None:
                return None
            own = storage.own_state(session, due.id)
            scope = GameScope.read(self.settings, session, [due.id])
            state, observed_at, restored_at = stored.state, stored.observed_at, title.restored_at
            names = tuple(dict.fromkeys(name for name in (title.original_name or title.name, title.name) if name))
            year = title.year
        try:
            previous = FanLook.from_state(state)
        except ValueError as spoiled:
            self._log.warning(("state", due.id), now, "title %s: its ZoG state cannot be read: %r", due.id, spoiled)
            self._next_check(due, ZOG_RETRY)
            return None
        try:
            elsewhere = played_elsewhere(scope, due.id, games.GameState.from_state(own))
        except (ValueError, TypeError, KeyError, AttributeError):  # its own poll reports it; ZoG's data is about PC
            elsewhere = False
        restored = restored_at is not None and observed_at < restored_at
        return _Game(due, previous, observed_at, restored, names, year, elsewhere, state)

    async def _get(self, page: str) -> zog_pages.GamePage | None:
        """One page of ZoG, read; the second request of a pass and later ones wait a second first."""
        if self._asked:
            await sleep(PAUSE_SECONDS)
        self._asked = True
        return zog_pages.read_page(await self.source.page(page))

    async def _look(self, game: _Game) -> FanLook:
        """The new state: the stored page read, or a page found. A failure of ZoG raises; an unreadable page while
        finding raises `_Keep`."""
        previous = game.previous
        tried: list[str] = []
        if previous is not None and previous.page is not None:
            tried.append(previous.page)
            try:
                page = await self._get(previous.page)
            except zog_pages.UnreadablePage as unreadable:
                return self._unreadable(game, previous, unreadable)
            if page is not None:
                if page.support is None:
                    return self._unreadable(game, previous, "no entry under «Переводы:»")
                return FanLook(previous.page, previous.by, page.support)
            logging.info("title %s: its ZoG page %s answers «Ошибка», finding it again", game.due.id, previous.page)
        for address in zog_pages.addresses(game.names[0]):
            if address in tried:
                continue
            tried.append(address)
            try:
                page = await self._get(address)
            except zog_pages.UnreadablePage as unreadable:
                self._log.warning(
                    ("layout", game.due.id), self.ctx.now(), "title %s: ZoG page %s cannot be read: %s",
                    game.due.id, address, unreadable,
                )
                raise _Keep() from unreadable
            if page is None:
                continue
            if not zog_pages.matches(page, game.names, game.year):
                logging.info("title %s: ZoG page %s (%s, %s) is another game", game.due.id, address, page.name, page.year)
                break
            if page.support is None:
                self._log.warning(("layout", game.due.id), self.ctx.now(), "title %s: ZoG page %s: no entry", game.due.id, address)
            return FanLook(address, russian.FOUND, page.support, page.support is None)
        return FanLook(None, russian.NOT_FOUND)

    def _unreadable(self, game: _Game, previous: FanLook, reason) -> FanLook:
        """The stored page could not be read: its last support stays, a log line a day."""
        self._log.warning(
            ("layout", game.due.id), self.ctx.now(), "title %s: ZoG page %s cannot be read: %s",
            game.due.id, previous.page, reason,
        )
        return FanLook(previous.page, previous.by, previous.support, True)

    # --- queue, then store ---

    def _queue_and_store(self, game: _Game, new: FanLook) -> None:
        """The events of the game in one write session that reads the official part now; then the state, next check in
        a week. A failed queueing stores nothing (again in six hours, the keys drop what is found again)."""
        now = self.ctx.now()
        try:
            with self.ctx.write_session() as session:
                if self._moved(session, game):
                    return
                parts = russian.fan_news(game.previous, new, self._official(session, game.due.id), game.restored)
                if parts is None:
                    logging.info("title %s: ZoG check, nothing to tell (%s)", game.due.id, new.page or new.by)
                else:
                    event = russian_events.fan_event(
                        game.due.id, game.due.name, parts, new.page, game.elsewhere, game.observed_at
                    )
                    EventQueue.enqueue_all(session, [Queued(game.due, event)], now)
                    session.commit()
        except Exception:
            logging.exception("queueing the fan Russian event of title %s failed", game.due.id)
            self._next_check(game.due, ZOG_RETRY)
            return
        with self.ctx.write_session() as session:
            stored = storage.snapshot_of(session, game.due.id, SOURCE_KEY)
            if stored is None:
                logging.info("title %s: its ZoG snapshot went while it was checked", game.due.id)
                return
            if stored.state != game.stored:
                logging.info("title %s: its ZoG page was changed by the owner while it was checked", game.due.id)
                return
            stored.state = new.state()
            stored.observed_at = now
            stored.next_check_at = now + ZOG_INTERVAL
            session.commit()

    @staticmethod
    def _moved(session, game: _Game) -> bool:
        """The owner saved a page or said «Не та игра» while ZoG was asked (`zog_page`): his state stays, this look
        is dropped with its events (they would be about the other page)."""
        stored = storage.snapshot_of(session, game.due.id, SOURCE_KEY)
        if stored is not None and stored.state == game.stored:
            return False
        logging.info("title %s: its ZoG page was changed by the owner while it was checked", game.due.id)
        return True

    @staticmethod
    def _official(session, title_id: int) -> russian.Support | None:
        """The official part as the line reads it now (the stored look, else IGDB); unreadable — no data."""
        stored = storage.snapshot_of(session, title_id, OFFICIAL_KEY)
        try:
            look = Look.from_state(stored.state) if stored is not None else None
            igdb = russian.igdb_from_state(storage.own_state(session, title_id))
        except ValueError:
            return None
        return russian.official_of(look, igdb)[0]

    def _next_check(self, due: DueTitle, after: timedelta) -> None:
        with self.ctx.write_session() as session:
            stored = storage.snapshot_of(session, due.id, SOURCE_KEY)
            if stored is not None:
                stored.next_check_at = self.ctx.now() + after
                session.commit()

    # --- what the card reads (spec 5.3) ---

    def card_fan(self, session, title: Title, tz: tzinfo) -> FanCard | None:
        """The ZoG part of the card of `title`: its state, «ZoG — проверено …» when a page was read, the hint about the
        page (not found and rejected only in «Хочу» and «В процессе», where a link can be pasted). None — no check, or
        a spoiled state (the check reports it). One read: the snapshot."""
        if self.source is None:
            return None
        stored = storage.snapshot_of(session, title.id, SOURCE_KEY)
        try:
            look = FanLook.from_state(stored.state) if stored is not None else None
        except ValueError as spoiled:
            logging.warning("title %s: a spoiled ZoG state, no fan part on its card: %r", title.id, spoiled)
            return None
        if look is None:
            return FanCard(None)
        checked = checked_hint(ZOG_WORD, stored.observed_at, self.ctx.now(), tz) if look.page is not None else ""
        active = for_russian(title.status)
        if look.unreadable:
            hint = HINT_UNREADABLE
        elif look.by == russian.NOT_FOUND and active:
            hint = HINT_NOT_FOUND
        elif look.by == russian.REJECTED and active:
            hint = HINT_REJECTED
        else:
            hint = ""
        return FanCard(look, checked, hint)
