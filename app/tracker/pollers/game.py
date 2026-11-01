"""A game: the dates of its platforms are compared for the country of the stores, the owner is told only about the
platforms of «Мои платформы» marked «играю здесь», and the platforms of the game are kept beside it with that mark.

A game is added with the Russian texts of Steam (`snapshot_to_add`); the polls take IGDB alone, and the name and the
description stay as they were added (like a film's). Every platform of the tracker the game is on gets its row; the
mark is set where the platform is one of «Мои платформы» at that moment (spec 6.3 of part 6.1). The feed and the card
show the dates of the country of the stores as it is now: the feed only the platforms the owner is told about, the
card every platform of «Мои платформы» the game is on, with its mark (spec 8 and 9.1).
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.tracker import game_events, game_rows, games, storage
from app.tracker import seasons as season_logic
from app.tracker.cards import CardPart, local_moment
from app.tracker.feed_rows import FeedBasis, FeedTitle, Piece
from app.tracker.game_scope import GameScope
from app.tracker.models import GamePlatformRecord, SeasonRecord, Title
from app.tracker.platforms import Platform
from app.tracker.pollers.base import DueTitle, Poller


def _new_rows(session, title_id: int, game: games.GameState, mine: Sequence[Platform]) -> None:
    """A row for every platform of the tracker the game is on and has no row of yet (a cancelled one too), with the
    mark where the platform is one of the owner's."""
    stored = set(session.scalars(select(GamePlatformRecord.platform).where(GamePlatformRecord.title_id == title_id)))
    for platform in Platform:
        if platform.value not in stored and games.has_platform(game, platform):
            session.add(GamePlatformRecord(title_id=title_id, platform=platform.value, playing=platform in mine))


class GamePoller(Poller):
    async def snapshot_to_add(self, external_id: str) -> Any:
        return await self.source.snapshot_to_add(external_id)

    def first_check(
        self, session, seasons: Sequence[season_logic.Season], state: dict[str, Any], now: datetime
    ) -> datetime:
        scope = GameScope.read(self.settings, session)
        return now + games.check_interval(games.GameState.from_state(state), scope.country, now.date())

    def store_extras(self, session, title_id: int, records: dict[int, SeasonRecord], snapshot: Any) -> None:
        """The platforms of the game, each with the mark «играю здесь» where it is one of «Мои платформы» now."""
        _new_rows(session, title_id, snapshot.game, GameScope.read(self.settings, session).mine)

    def feed_pieces(self, session, shown: Mapping[int, FeedTitle], basis: FeedBasis) -> list[Piece]:
        scope = GameScope.read(self.settings, session, self._active())
        pieces: list[Piece] = []
        for title_id, state in storage.own_states_of(session, self._active()).items():
            if title_id in shown:
                game = games.GameState.from_state(state)
                pieces += game_rows.feed_pieces(shown[title_id], game, scope.told(title_id), scope.country, basis.today)
        return pieces

    def card_part(self, session, title: Title) -> CardPart:
        game = games.GameState.from_state(storage.own_state(session, title.id))
        scope = GameScope.read(self.settings, session, [title.id])
        today = local_moment(self.ctx.now(), self.settings.time_zone(session)).date()
        rows = game_rows.platform_rows(game, scope.mine, scope.marks_of(title.id), scope.country, today)
        return CardPart(
            platforms=rows,
            store_links=game_rows.store_links(game, scope.mine, scope.country, title.original_name or title.name),
            platform_note=game_rows.platform_note(game, rows),
        )

    def apply(self, due: DueTitle, snapshot: Any) -> int:
        now = self.ctx.now()
        today = now.date()
        with self.ctx.session_factory() as session:
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            old = games.GameState.from_state(stored.state)
            observed_at = stored.observed_at
            # the marks as they are when IGDB has answered: one set while the events are queued counts from the next
            # check (as KI-22); one set while IGDB was answering counts already in this one
            scope = GameScope.read(self.settings, session, [due.id])
        new = games.carry_over(old, snapshot.game)
        # events first: if storing the state fails, the next poll finds the same facts and the dedup key drops them
        found = self.record_all(
            due,
            game_events.detect_events(
                due.id, due.name, old, new, scope.country, scope.told(due.id), observed_at, today
            ),
            previous_look=observed_at,
        )
        with self.ctx.write_session() as session:
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            storage.refresh_poster(session, due.id, snapshot.poster_path)
            _new_rows(session, due.id, new, scope.mine)  # a platform IGDB added: marked as the events counted it
            stored.state = new.state()
            stored.observed_at = now
            stored.next_check_at = now + games.check_interval(new, scope.country, today)
            session.commit()
        return found
