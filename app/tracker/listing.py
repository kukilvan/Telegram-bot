"""What the owner reads of the list: its rows, the numbers of the whole list and the card of a title. The part of a card
that depends on the kind (a film's dates, the seasons, a game's platforms) is given by the poller of the kind."""

import asyncio
from collections.abc import Collection
from datetime import timezone
from fractions import Fraction
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.tracker import scores
from app.tracker import sequel_events, storage
from app.tracker.cards import SequelsView, TitleCard, sequel_view
from app.tracker.genres import key_of as genre_key
from app.tracker.genres import keys_of as genre_keys
from app.tracker.genres import merge as merge_genres
from app.tracker.text import key as text_key
from app.tracker.context import CoreContext
from app.tracker.models import SeasonRecord, SourceSnapshot, Title, TitleKind, TitleStatus
from app.tracker.results import ListOrder, Overview, TitleSummary
from app.tracker.settings_store import SettingsStore

if TYPE_CHECKING:
    from app.tracker.polling import Pollers


def _exact(view: scores.ScoreView | None) -> int | Fraction | None:
    """The exact value that orders the rows by score: the own score, else the exact average; None: none shown."""
    if view is None:
        return None
    return view.own if view.own is not None else view.average


class Listing:
    def __init__(self, ctx: CoreContext, settings: SettingsStore, pollers: "Pollers") -> None:
        self.ctx = ctx
        self.settings = settings
        self.pollers = pollers

    async def list_titles(
        self,
        kind: TitleKind | None = None,
        statuses: Collection[TitleStatus] | None = None,
        order: ListOrder | None = None,
        query: str | None = None,
        genre: str | None = None,
    ) -> list[TitleSummary]:
        """The rows of the list. `kind` None: every kind; `statuses` None: every status (an empty set: no row); `query`:
        a part of the name or of the original name (case and «ё» do not matter; empty: no search); `genre`: a merged
        genre as `genres` names it. Without an `order` the titles come as they were added, the first one first (the
        bot's list)."""
        return await asyncio.to_thread(self._list_titles, kind, statuses, order, query, genre)

    async def genres(self, kind: TitleKind | None = None, statuses: Collection[TitleStatus] | None = None) -> list[str]:
        """The merged genres of the titles under these filters, by name in alphabetical order."""
        return await asyncio.to_thread(self._genres, kind, statuses)

    @staticmethod
    def _select(kind: TitleKind | None, statuses: Collection[TitleStatus] | None):
        query = select(Title)
        if kind is not None:
            query = query.where(Title.kind == kind)
        if statuses is not None:
            query = query.where(Title.status.in_(list(statuses)))
        return query

    def _genres(self, kind: TitleKind | None, statuses: Collection[TitleStatus] | None) -> list[str]:
        with self.ctx.session_factory() as session:
            lists = list(session.scalars(self._select(kind, statuses).with_only_columns(Title.genres)))
        return merge_genres(lists)

    def _list_titles(
        self,
        kind: TitleKind | None,
        statuses: Collection[TitleStatus] | None,
        order: ListOrder | None,
        query: str | None,
        genre: str | None,
    ) -> list[TitleSummary]:
        selected = self._select(kind, statuses)
        if order == ListOrder.ADDED:
            selected = selected.order_by(Title.added_at.desc(), Title.id.desc())
        else:
            selected = selected.order_by(Title.id)
        with self.ctx.session_factory() as session:
            titles = list(session.scalars(selected))
            titles = self._matching(titles, query, genre)
            views = self._scores(session, titles)  # one reading for every row, not one for each title
        if order == ListOrder.NAME:
            titles.sort(key=lambda t: (text_key(t.name), t.id))
        elif order == ListOrder.ARCHIVED:
            titles.sort(key=lambda t: (t.status_changed_at, t.id), reverse=True)
        elif order == ListOrder.SCORE:
            titles.sort(key=lambda t: (t.status_changed_at, t.id), reverse=True)  # the order of the same scores
            scored = sorted((t for t in titles if _exact(views[t.id]) is not None), key=lambda t: _exact(views[t.id]), reverse=True)
            titles = scored + [t for t in titles if _exact(views[t.id]) is None]
        return [
            TitleSummary(
                t.id, t.kind, t.name, t.year, t.status, t.poster_path,
                views[t.id].shown if views[t.id] else None, bool(views[t.id] and views[t.id].by_seasons),
            )
            for t in titles
        ]

    @staticmethod
    def _matching(titles: list[Title], query: str | None, genre: str | None) -> list[Title]:
        needle = text_key(query.strip()) if query else ""
        wanted = genre_key(genre) if genre else ""
        if needle:
            titles = [t for t in titles if needle in text_key(t.name) or needle in text_key(t.original_name or "")]
        if wanted:
            titles = [t for t in titles if wanted in genre_keys(t.genres)]
        return titles

    @staticmethod
    def _scores(session, titles: list[Title]) -> dict[int, scores.ScoreView | None]:
        """The score each title shows, from one reading of the seasons of all of them."""
        seasons: dict[int, list[tuple[bool, int | None]]] = {}
        rows = session.execute(
            select(SeasonRecord.title_id, SeasonRecord.watched, SeasonRecord.score).where(
                SeasonRecord.title_id.in_([t.id for t in titles])
            )
        )
        for title_id, watched, score in rows:
            seasons.setdefault(title_id, []).append((watched, score))
        return {t.id: scores.visible(t, seasons.get(t.id, [])) for t in titles}

    async def overview(self) -> Overview:
        return await asyncio.to_thread(self._overview)

    def _overview(self) -> Overview:
        with self.ctx.session_factory() as session:
            count = session.scalar(select(func.count(Title.id))) or 0
            # only a successful check writes `observed_at`, so a failed one does not move it. The empty state «Посмотрел»
            # stores for the sequel check before its source has answered (`Sequels.checked`) is no check (KI-10)
            last = session.scalar(
                select(func.max(SourceSnapshot.observed_at)).where(func.json(SourceSnapshot.state) != "{}")
            )
            tz = self.settings.time_zone(session)  # read here, where it is needed (coding standard 2)
        local = last.replace(tzinfo=timezone.utc).astimezone(tz) if last is not None else None
        return Overview(count, local)

    async def title_card(self, title_id: int) -> TitleCard | None:
        return await asyncio.to_thread(self._title_card, title_id)

    def _title_card(self, title_id: int) -> TitleCard | None:
        with self.ctx.session_factory() as session:
            title = session.get(Title, title_id)
            if title is None:
                return None
            part = self.pollers.reader_of(title.kind).card_part(session, title)
            return TitleCard(
                id=title.id,
                kind=title.kind,
                name=title.name,
                original_name=title.original_name,
                year=title.year,
                genres=list(title.genres),
                status=title.status,
                poster_path=title.poster_path,
                overview=title.overview or "",
                sequels=self._sequels(session, title),
                score=self._scores(session, [title])[title.id],
                **part.fields(),
            )

    def _sequels(self, session, title: Title) -> SequelsView | None:
        """The sequels of a watched title whose sequel check is on (a movie), with the ones the list already has."""
        snapshot = storage.sequel_snapshot(session, title.id) if title.status == TitleStatus.WATCHED else None
        if snapshot is None:
            return None
        sequels = sequel_events.Sequels.from_state(snapshot.state)
        listed = self.pollers.of(title.kind).known_ids(session, (part.id for part in sequels.parts))
        return sequel_view(sequels, sequels.checked, listed)
