"""What the owner reads of the list: its rows, the numbers of the whole list and the card of a title."""

import asyncio
from collections.abc import Collection
from datetime import timezone
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.tracker import seasons as season_logic
from app.tracker import sequel_events, storage
from app.tracker.cards import MovieLine, SequelsView, TitleCard, sequel_view
from app.tracker.context import CoreContext
from app.tracker.kinds import KINDS, is_seasonal
from app.tracker.models import MovieRecord, SourceSnapshot, Title, TitleKind, TitleStatus
from app.tracker.results import ListOrder, Overview, TitleSummary
from app.tracker.settings_store import SettingsStore
from app.tracker.sources.dates import parse_date

if TYPE_CHECKING:
    from app.tracker.polling import Pollers


def _name_key(name: str) -> str:
    """Case does not matter and «ё» is «е»; the code points then put digits first, Latin letters next, Cyrillic last."""
    return name.casefold().replace("ё", "е")


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
    ) -> list[TitleSummary]:
        """The rows of the list. `kind` None: every kind; `statuses` None: every status (an empty set: no row). Without
        an `order` the titles come as they were added, the first one first (the bot's list)."""
        return await asyncio.to_thread(self._list_titles, kind, statuses, order)

    def _list_titles(
        self, kind: TitleKind | None, statuses: Collection[TitleStatus] | None, order: ListOrder | None
    ) -> list[TitleSummary]:
        query = select(Title)
        if kind is not None:
            query = query.where(Title.kind == kind)
        if statuses is not None:
            query = query.where(Title.status.in_(list(statuses)))
        if order == ListOrder.ADDED:
            query = query.order_by(Title.added_at.desc(), Title.id.desc())
        else:
            query = query.order_by(Title.id)
        with self.ctx.session_factory() as session:
            titles = list(session.scalars(query))
        if order == ListOrder.NAME:
            titles.sort(key=lambda t: (_name_key(t.name), t.id))
        return [TitleSummary(t.id, t.kind, t.name, t.year, t.status, t.poster_path) for t in titles]

    async def overview(self) -> Overview:
        return await asyncio.to_thread(self._overview)

    def _overview(self) -> Overview:
        with self.ctx.session_factory() as session:
            count = session.scalar(select(func.count(Title.id))) or 0
            # only a successful check writes `observed_at`, so a failed one does not move it
            last = session.scalar(select(func.max(SourceSnapshot.observed_at)))
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
            state = storage.own_state(session, title_id)
            seasons_view = None
            season_rows = ()
            if is_seasonal(title.kind):
                loaded = storage.load_seasons(session, title_id)
                watched = {record.number for record, _ in loaded if record.watched}
                now, gap = self.ctx.now(), self.settings.part_gap(session)
                seasons_view = season_logic.summarize((season for _, season in loaded), watched, now, gap)
                season_rows = season_logic.rows((season for _, season in loaded), watched, now, gap)
            movies = session.scalars(
                select(MovieRecord).where(MovieRecord.title_id == title_id).order_by(MovieRecord.id)
            )
            return TitleCard(
                id=title.id,
                kind=title.kind,
                name=title.name,
                original_name=title.original_name,
                year=title.year,
                genres=list(title.genres),
                status=title.status,
                theatrical_date=parse_date(state.get("theatrical_date")),
                digital_date=parse_date(state.get("digital_date")),
                seasons=seasons_view,
                franchise_movies=tuple(MovieLine(m.name, m.aired_on, m.released) for m in movies),
                tz=self.settings.time_zone(session) if KINDS[title.kind].local_times else None,
                poster_path=title.poster_path,
                overview=title.overview or "",
                season_rows=season_rows,
                sequels=self._sequels(session, title),
            )

    def _sequels(self, session, title: Title) -> SequelsView | None:
        """The sequels of a watched title whose sequel check is on (a movie), with the ones the list already has."""
        snapshot = storage.sequel_snapshot(session, title.id) if title.status == TitleStatus.WATCHED else None
        if snapshot is None:
            return None
        sequels = sequel_events.Sequels.from_state(snapshot.state)
        listed = self.pollers.of(title.kind).known_ids(session, (part.id for part in sequels.parts))
        return sequel_view(sequels, "parts" in snapshot.state, listed)
