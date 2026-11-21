"""The link of a game in PlayStation Store, checked at a click: the page of its concept when the store has it, else the search.

The core reads the concept, the original name and the country of the stores without the network, then asks the store
once with `HEAD` (answer first, work, report — rule 8 of `docs/coding-standards.md`): `200` — the concept page; a
redirect to an address with `/error` — the search by the original name; a failure or any other answer — the concept page,
as before the check. An answer of the store is kept in memory a day per (locale, concept); a failure is not kept, so the
next click asks again. Without a source of the answers (`None`) nothing is asked and the link is the concept page.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.tracker import games, storage
from app.tracker.context import CoreContext
from app.tracker.game_rows import PlayStationLink, playstation_link
from app.tracker.game_scope import GameScope
from app.tracker.models import Title, TitleKind
from app.tracker.settings_store import SettingsStore

OK = 200
ERROR_MARK = "/error"  # in the address the store redirects a concept it does not have to
KEPT_FOR = timedelta(days=1)


@dataclass(frozen=True)
class _Kept:
    until: datetime
    missing: bool  # the store has no such concept


class PlayStationLinks:
    def __init__(self, ctx: CoreContext, settings: SettingsStore, store: Any = None) -> None:
        """`store`: the client of the store (`PlayStationProvider.head`), None — nothing is asked."""
        self.ctx = ctx
        self.settings = settings
        self.store = store
        self._kept: dict[tuple[str, str], _Kept] = {}

    def _read(self, title_id: int) -> PlayStationLink | None:
        """The link of the game, from the database alone; None — a title that is gone, no game, or a game without the
        link (no store in the country, PS5 not among «Мои платформы», not on PS5)."""
        with self.ctx.session_factory() as session:
            title = session.get(Title, title_id)
            if title is None or title.kind is not TitleKind.GAME:
                return None
            game = games.GameState.from_state(storage.own_state(session, title_id))
            scope = GameScope.read(self.settings, session)
            return playstation_link(game, scope.mine, scope.country, title.original_name or title.name)

    async def link(self, title_id: int) -> str | None:
        """Where the click on «Открыть в PlayStation Store» leads; None — the card is the place (see `_read`)."""
        found = await asyncio.to_thread(self._read, title_id)
        if found is None:
            return None
        if found.concept is None or self.store is None:
            return found.url  # no concept: the search, no request
        return found.search_url if await self._missing(found) else found.concept_url

    async def _missing(self, found: PlayStationLink) -> bool:
        """The store has no page of the concept: kept for a day when it answered, asked again after a failure."""
        key = (found.locale, found.concept)
        now = self.ctx.now()
        kept = self._kept.get(key)
        if kept is not None and kept.until > now:
            return kept.missing
        try:
            answer = await self.store.head(found.concept_url)
        except Exception as error:  # a timeout or no connection: the concept page, as before the check
            logging.info("PlayStation Store did not answer for %s: %r", key, error)
            return False
        if answer.status == OK:
            missing = False
        elif 300 <= answer.status < 400 and ERROR_MARK in answer.location:
            missing = True
        else:
            return False
        self._kept[key] = _Kept(now + KEPT_FOR, missing)
        return missing
