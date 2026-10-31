"""What a series and an anime share: their seasons decide when to look again, what the feed shows and what the card
lists. An anime's source gives the moment of an episode, so its days and hours are the owner's (`KINDS[…].local_times`)."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from app.tracker import feed_rows, series_events, storage
from app.tracker import seasons as season_logic
from app.tracker.cards import CardPart
from app.tracker.feed_rows import FeedBasis, FeedTitle, Piece
from app.tracker.kinds import KINDS
from app.tracker.models import Title
from app.tracker.pollers.base import Poller


class SeasonalPoller(Poller):
    def first_check(self, session, seasons: Sequence[season_logic.Season], state: dict[str, Any], now: datetime) -> datetime:
        return now + series_events.check_interval(series_events.ShowState.of(seasons, state), now)

    def feed_pieces(self, session, shown: Mapping[int, FeedTitle], basis: FeedBasis) -> list[Piece]:
        """The dated episodes of all the titles of the kind, by parts of seasons, from three reads."""
        local = basis.tz if KINDS[self.kind].local_times else None  # the source gives the moment, not only the day
        pieces: list[Piece] = []
        for title_id, seasons in storage.load_seasons_of(session, self._active()).items():
            if title_id in shown:
                pieces += feed_rows.season_pieces(shown[title_id], seasons, basis.gap, local, basis.today)
        return pieces

    def card_part(self, session, title: Title) -> CardPart:
        """Where the seasons have got, and a row per season with the owner's mark and score (the web)."""
        loaded = storage.load_seasons(session, title.id)
        watched = {record.number for record, _ in loaded if record.watched}
        marks = {record.number: season_logic.SeasonMark(record.id, record.watched, record.score) for record, _ in loaded}
        now, gap = self.ctx.now(), self.settings.part_gap(session)
        return CardPart(
            seasons=season_logic.summarize((season for _, season in loaded), watched, now, gap),
            season_rows=season_logic.rows((season for _, season in loaded), marks, now, gap),
            tz=self.settings.time_zone(session) if KINDS[self.kind].local_times else None,
        )
