"""What a series and an anime share: their seasons decide when to look again, what the feed shows and what the card
lists, and what came out in the days of «Недавно». An anime's source gives the moment of an episode, so its days and hours are the owner's (`KINDS[…].local_times`)."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from app.tracker import feed_released, feed_rows, series_events, storage
from app.tracker import seasons as season_logic
from app.tracker.cards import CardPart
from app.tracker.feed_released import FeedParts
from app.tracker.feed_rows import FeedBasis, FeedTitle
from app.tracker.kinds import KINDS
from app.tracker.models import Title
from app.tracker.pollers.base import Poller


class SeasonalPoller(Poller):
    def first_check(self, session, seasons: Sequence[season_logic.Season], state: dict[str, Any], now: datetime) -> datetime:
        return now + series_events.check_interval(series_events.ShowState.of(seasons, state), now)

    def feed(self, session, shown: Mapping[int, FeedTitle], basis: FeedBasis, now: datetime) -> FeedParts:
        """The dated episodes of all the titles of the kind, by parts of seasons: the pieces from today on and the
        episodes out in the days of «Недавно» (the films of an anime franchise are never among them), both cut from one
        read of the seasons (three reads)."""
        local = basis.tz if KINDS[self.kind].local_times else None  # the source gives the moment, not only the day
        parts = FeedParts()
        for title_id, seasons in storage.load_seasons_of(session, self._active()).items():
            if title_id in shown:
                parts.pieces.extend(feed_rows.season_pieces(shown[title_id], seasons, basis.gap, local, basis.today))
                parts.outs.extend(feed_released.season_outs(shown[title_id], seasons, basis.gap, local, basis.today, now))
        return parts

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
