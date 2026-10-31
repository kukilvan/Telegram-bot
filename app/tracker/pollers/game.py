"""A game: the dates of its platforms are compared for the country of the stores, the owner is told only about the
platforms of «Мои платформы» marked «играю здесь», and the platforms of the game are kept beside it with that mark.

A game is added with the Russian texts of Steam (`snapshot_to_add`); the polls take IGDB alone, and the name and the
description stay as they were added (like a film's). Every platform of the tracker the game is on gets its row; the
mark is set where the platform is one of «Мои платформы» at that moment (spec 6.3 of part 6.1).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.tracker import game_events, games, storage
from app.tracker import seasons as season_logic
from app.tracker.models import GamePlatformRecord, SeasonRecord
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
        country = self.settings.store_country_in(session)
        return now + games.check_interval(games.GameState.from_state(state), country, now.date())

    def store_extras(self, session, title_id: int, records: dict[int, SeasonRecord], snapshot: Any) -> None:
        """The platforms of the game, each with the mark «играю здесь» where it is one of «Мои платформы» now."""
        _new_rows(session, title_id, snapshot.game, self.settings.my_platforms_in(session))

    def apply(self, due: DueTitle, snapshot: Any) -> int:
        now = self.ctx.now()
        today = now.date()
        with self.ctx.session_factory() as session:
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            old = games.GameState.from_state(stored.state)
            observed_at = stored.observed_at
            country = self.settings.store_country_in(session)
            mine = self.settings.my_platforms_in(session)
            # the marks as they are when the check starts: one set while it runs counts from the next check (as KI-22)
            playing = dict(
                session.execute(
                    select(GamePlatformRecord.platform, GamePlatformRecord.playing).where(
                        GamePlatformRecord.title_id == due.id
                    )
                ).all()
            )
        new = games.carry_over(old, snapshot.game)
        told = game_events.reported(mine, playing)
        # events first: if storing the state fails, the next poll finds the same facts and the dedup key drops them
        found = self.record_all(
            due,
            game_events.detect_events(due.id, due.name, old, new, country, told, observed_at, today),
            previous_look=observed_at,
        )
        with self.ctx.write_session() as session:
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            storage.refresh_poster(session, due.id, snapshot.poster_path)
            _new_rows(session, due.id, new, mine)  # a platform IGDB added: marked as the events counted it
            stored.state = new.state()
            stored.observed_at = now
            stored.next_check_at = now + games.check_interval(new, country, today)
            session.commit()
        return found
