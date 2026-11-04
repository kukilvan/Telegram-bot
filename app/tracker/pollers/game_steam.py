"""What the owner reads of the Steam prices of games: the block of a card and the marks of the rows of the list.

The reads of part 6.2 (spec 6): the block of one card (its snapshot of prices, its price history) and the marks of all
the games of the list in a number of reads that does not grow with the number of games. What a line says is
`price_rows`; whether prices are told about a game is `game_prices.reports_prices` (one place, the rule of the check).
"""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select

from app.tracker import games, price_rows, storage
from app.tracker.cards import SteamView
from app.tracker.context import CoreContext
from app.tracker.game_scope import GameScope
from app.tracker.models import PriceRecord, SourceSnapshot, Title, TitleKind, TitleStatus
from app.tracker.pollers.game_prices import price_snapshot, reports_prices, steam_number
from app.tracker.settings_store import SettingsStore
from app.tracker.sources.steam_prices import SOURCE_KEY


class GameSteam:
    """The reads of the games of `kind`; `source` is the source of prices, None — the core has none, nothing is shown."""

    def __init__(self, kind: TitleKind, source: Any, ctx: CoreContext, settings: SettingsStore) -> None:
        self.kind = kind
        self.source = source
        self.ctx = ctx
        self.settings = settings

    def card_block(self, session, title: Title, game: games.GameState, scope: GameScope) -> SteamView | None:
        """The block «Steam» of the card of a game; None when there is none (spec 6.1): prices are not told about the
        game (`reports_prices`: «Хочу», PC marked) or the core has no source of prices."""
        if self.source is None or not reports_prices(title.status, game, scope.told(title.id)):
            return None
        stored = price_snapshot(session, title.id)
        look = price_rows.current_look(stored.state, game.steam_id, scope.country) if stored and game.steam_id else None
        records = list(session.scalars(select(PriceRecord).where(PriceRecord.title_id == title.id)))
        return price_rows.steam_view(
            scope.country, game.steam_id or None, look, stored.observed_at if look is not None else None, records,
            self.ctx.now(), self.settings.time_zone(session),
        )

    def marks(self, session, titles: Sequence[Title]) -> dict[int, str]:
        """The marks of the rows of these titles (spec 6.3): title → «−30 %» for the games of «Хочу» that prices are told
        about and that have a discount going; in four reads, however many games there are."""
        if self.source is None or not any(t.status == TitleStatus.WANT for t in titles):
            return {}
        wanted = select(Title.id).where(Title.kind == self.kind, Title.status == TitleStatus.WANT)
        states = storage.own_states_of(session, wanted)
        scope = GameScope.read(self.settings, session, wanted)
        snapshots = dict(
            session.execute(
                select(SourceSnapshot.title_id, SourceSnapshot.state).where(
                    SourceSnapshot.source == SOURCE_KEY, SourceSnapshot.title_id.in_(wanted)
                )
            ).all()
        )
        now = self.ctx.now()
        marks: dict[int, str] = {}
        for title_id, state in states.items():
            steam_id = steam_number(TitleStatus.WANT, games.GameState.from_state(state), scope.told(title_id))
            if steam_id is None or title_id not in snapshots:
                continue
            text = price_rows.mark(price_rows.current_look(snapshots[title_id], steam_id, scope.country), now)
            if text:
                marks[title_id] = text
        return marks
