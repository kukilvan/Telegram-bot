"""The owner's page on ZoG for a game: «Страница на ZoG» saved from a pasted link, and «Не та игра».

Spec 5.7 of stage 9.1b, ADR 0016. Both are presses of the card for a game in «Хочу» or «В процессе» (`for_russian`).
`ZogPages.set` reads the link (`zog_pages.page_of`), asks ZoG for the page once (a press that goes to the network: the
client waits 10 s) and saves `{"page": …, "by": "owner", …}` with the fan support read now, without the name and year
check (the owner's choice wins). That first read is the reference point: no message, the next check in a week
(`game_zog.ZOG_INTERVAL`), and the undelivered fan events of the game are withdrawn (they were about another page). A
link that is no good raises `ZogPageRefused` with the text for the field and saves nothing: empty, not a game page of
ZoG, a page ZoG does not have («Ошибка»), ZoG that did not answer. A page whose layout cannot be read is still the
owner's page, saved with no support and marked unreadable (the card says so, the weekly check reads it again).
`ZogPages.reject` saves `{"page": null, "by": "rejected"}` (no request) and withdraws the same events; the check never
asks a rejected game, and a link saved after it is the owner's page. The same press twice leaves the same state.

A title that is gone raises `UnknownTitle`; one that is no game, or a game that left the two statuses (a card open from
before), or a core without the ZoG client, changes nothing (`ChangeResult(False)`). The status is read before the
request and once more in the write session that saves.
"""

import asyncio
import logging
from typing import Any

from app.tracker import russian, russian_events, storage
from app.tracker.context import CoreContext
from app.tracker.errors import UnknownTitle, ZogPageRefused
from app.tracker.models import SourceSnapshot, Title, TitleKind
from app.tracker.pollers.game_russian import for_russian
from app.tracker.pollers.game_zog import SOURCE_KEY, ZOG_INTERVAL
from app.tracker.queue import EventQueue
from app.tracker.results import ChangeResult
from app.tracker.russian import FanLook
from app.tracker.sources import zog_pages

# What the page says under the field (spec 5.7)
EMPTY = "Вставьте ссылку на страницу игры на ZoG"
NOT_A_PAGE = "Это не страница игры на ZoG. Нужна ссылка вида https://www.zoneofgames.ru/games/…/"
NO_SUCH_PAGE = "На ZoG нет такой страницы — проверьте ссылку"
NOT_ANSWERED = "ZoG не ответил — попробуйте позже"


class ZogPages:
    """The two presses of the form; `source` is the ZoG client (`ZogProvider`), None — no ZoG check, nothing to save."""

    def __init__(self, ctx: CoreContext, source: Any = None) -> None:
        self.ctx = ctx
        self.source = source

    async def set(self, title_id: int, link: str) -> ChangeResult:
        """Save the page of `link` as the owner's page of the game (see the module)."""
        if not await asyncio.to_thread(self._open, title_id):
            return ChangeResult(False)
        page = self._page_of(link)
        return ChangeResult(await asyncio.to_thread(self._save, title_id, await self._look_at(page)))

    async def reject(self, title_id: int) -> ChangeResult:
        """«Не та игра»: no page until the owner saves a link."""
        if not await asyncio.to_thread(self._open, title_id):
            return ChangeResult(False)
        return ChangeResult(await asyncio.to_thread(self._save, title_id, FanLook(None, russian.REJECTED)))

    # --- the link and the page ---

    @staticmethod
    def _page_of(link: str) -> str:
        """The page of the link; an empty one or one of another site is refused."""
        if not link.strip():
            raise ZogPageRefused(EMPTY)
        page = zog_pages.page_of(link)
        if page is None:
            raise ZogPageRefused(NOT_A_PAGE)
        return page

    async def _look_at(self, page: str) -> FanLook:
        """The owner's page as it reads now: its support, or unreadable when the layout cannot be read."""
        try:
            text = await self.source.page(page)
        except Exception as error:  # ZoG down, slow or answering with another status
            logging.info("ZoG page %s of the owner's link failed: %r", page, error)
            raise ZogPageRefused(NOT_ANSWERED) from error
        try:
            found = zog_pages.read_page(text)
        except zog_pages.UnreadablePage as unreadable:
            logging.warning("ZoG page %s of the owner's link cannot be read: %s", page, unreadable)
            return FanLook(page, russian.OWNER, None, True)
        if found is None:
            raise ZogPageRefused(NO_SUCH_PAGE)
        if found.support is None:
            logging.warning("ZoG page %s of the owner's link: no entry under «Переводы:»", page)
        return FanLook(page, russian.OWNER, found.support, found.support is None)

    # --- the database ---

    def _open(self, title_id: int) -> bool:
        """Whether the press can go on: a game for Russian and a core with the ZoG client; a title gone raises."""
        with self.ctx.session_factory() as session:
            title = session.get(Title, title_id)
        if title is None:
            raise UnknownTitle(title_id)
        return self.source is not None and title.kind is TitleKind.GAME and for_russian(title.status)

    def _save(self, title_id: int, look: FanLook) -> bool:
        """The state and the withdrawal of the undelivered fan events in one write session; True — the state changed."""
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            title = session.get(Title, title_id)
            if title is None:
                raise UnknownTitle(title_id)
            if title.kind is not TitleKind.GAME or not for_russian(title.status):
                return False
            stored = storage.snapshot_of(session, title_id, SOURCE_KEY)
            if stored is None:
                stored = SourceSnapshot(title_id=title_id, source=SOURCE_KEY, state={}, observed_at=now)
                session.add(stored)
            changed = stored.state != look.state()
            stored.state = look.state()
            stored.observed_at = now
            stored.next_check_at = now + ZOG_INTERVAL
            EventQueue.withdraw(session, title_id, (russian_events.FAN,))
            session.commit()
        return changed
