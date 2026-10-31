"""A movie: its own release dates are compared, and its snapshot says when to look again; the feed and the card show
the same two dates."""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from app.tracker import feed_rows, movie_events
from app.tracker import seasons as season_logic
from app.tracker import storage
from app.tracker.cards import CardPart
from app.tracker.feed_rows import FeedBasis, FeedTitle, Piece
from app.tracker.models import Title
from app.tracker.pollers.base import DueTitle, Poller
from app.tracker.sources.dates import parse_date


class MoviePoller(Poller):
    def first_check(self, session, seasons: Sequence[season_logic.Season], state: dict[str, Any], now: datetime) -> datetime:
        return now + movie_events.check_interval_for_state(state, now.date())

    def feed_pieces(self, session, shown: Mapping[int, FeedTitle], basis: FeedBasis) -> list[Piece]:
        pieces: list[Piece] = []
        for title_id, state in storage.own_states_of(session, self._active()).items():
            if title_id in shown:
                dates = movie_events.MovieDates.from_state(state)
                pieces += feed_rows.movie_pieces(shown[title_id], dates.theatrical, dates.digital, basis.today)
        return pieces

    def card_part(self, session, title: Title) -> CardPart:
        state = storage.own_state(session, title.id)
        return CardPart(
            theatrical_date=parse_date(state.get("theatrical_date")), digital_date=parse_date(state.get("digital_date"))
        )

    def apply(self, due: DueTitle, snapshot: Any) -> int:
        now = self.ctx.now()
        today = now.date()
        with self.ctx.session_factory() as session:
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            old = movie_events.MovieDates.from_state(stored.state)
            new = movie_events.MovieDates.from_state(snapshot.state()).keeping_known(old)
            observed_at = stored.observed_at
        # events first: if storing the state fails, the next poll finds the same facts and the dedup key drops them
        found = self.record_all(
            due, movie_events.detect_events(due.id, due.name, old, new, observed_at, today), previous_look=observed_at
        )
        with self.ctx.write_session() as session:
            stored = storage.stored_snapshot(session, due.id, due.snapshot_source)
            storage.refresh_poster(session, due.id, snapshot.poster_path)
            stored.state = new.to_state()
            stored.observed_at = now
            stored.next_check_at = now + movie_events.check_interval(new, today)
            session.commit()
        return found
