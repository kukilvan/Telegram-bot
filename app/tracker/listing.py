"""What the owner reads of the list: its rows, the numbers of the whole list and the card of a title."""

import asyncio
from datetime import timezone

from sqlalchemy import func, select

from app.tracker import seasons as season_logic
from app.tracker import storage
from app.tracker.cards import MovieLine, TitleCard
from app.tracker.context import CoreContext
from app.tracker.kinds import KINDS, is_seasonal
from app.tracker.models import MovieRecord, SourceSnapshot, Title
from app.tracker.results import Overview, TitleSummary
from app.tracker.settings_store import SettingsStore
from app.tracker.sources.dates import parse_date


class Listing:
    def __init__(self, ctx: CoreContext, settings: SettingsStore) -> None:
        self.ctx = ctx
        self.settings = settings

    async def list_titles(self) -> list[TitleSummary]:
        return await asyncio.to_thread(self._list_titles)

    def _list_titles(self) -> list[TitleSummary]:
        with self.ctx.session_factory() as session:
            rows = session.scalars(select(Title).order_by(Title.id))
            return [TitleSummary(t.id, t.kind, t.name, t.year, t.status) for t in rows]

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
            )
