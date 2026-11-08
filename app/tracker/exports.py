"""The export of the owner's data, download only: the CSV list and the JSON of everything (spec 3 of stage 7.1).

Each file is built in a worker thread (rule 1) from one read session, so it is one picture of the database; the dates
are on the owner's clock (the zone is read in that same session, rule 2). The formats are the pure `export_rows`, the
JSON document is `export_all`. There is no import: the data comes back from a copy of the database.
"""

import asyncio
from collections import defaultdict

from sqlalchemy import select

from app.tracker import export_all, export_rows, scores
from app.tracker.cards import STATUS_LABELS
from app.tracker.context import CoreContext
from app.tracker.export_rows import ExportFile, ListLine
from app.tracker.kinds import KINDS
from app.tracker.models import ARCHIVE_STATUSES, SeasonRecord, Title
from app.tracker.settings_store import SettingsStore
from app.tracker.text import by_name


class Exports:
    def __init__(self, ctx: CoreContext, settings: SettingsStore) -> None:
        self.ctx = ctx
        self.settings = settings

    async def list_file(self) -> ExportFile:
        """`tracker-list-<date>.csv`: every title, the archive too, in the order «по названию» of the List."""
        return await asyncio.to_thread(self._list_file)

    async def all_file(self) -> ExportFile:
        """`tracker-all-<date>.json`: the owner's data, whole."""
        return await asyncio.to_thread(self._all_file)

    def _list_file(self) -> ExportFile:
        now = self.ctx.now()
        with self.ctx.session_factory() as session:
            tz = self.settings.time_zone(session)
            titles = sorted(session.scalars(select(Title)), key=lambda t: by_name(t.name, t.id))
            marks: dict[int, list[tuple[bool, int | None]]] = defaultdict(list)
            for title_id, watched, score in session.execute(
                select(SeasonRecord.title_id, SeasonRecord.watched, SeasonRecord.score)
            ):
                marks[title_id].append((watched, score))
            lines = []
            for title in titles:
                view = scores.visible(title, marks.get(title.id, []))
                lines.append(
                    ListLine(
                        title.name, title.original_name or "", KINDS[title.kind].label, STATUS_LABELS[title.status],
                        scores.label(view.shown) if view is not None and view.shown is not None else None, title.year,
                        title.added_at, title.status_changed_at if title.status in ARCHIVE_STATUSES else None,
                    )
                )
        name = export_rows.list_file_name(export_rows.file_day(now, tz))
        return ExportFile(name, export_rows.CSV_TYPE, export_rows.csv_bytes(lines, tz))

    def _all_file(self) -> ExportFile:
        now = self.ctx.now()
        with self.ctx.session_factory() as session:
            tz = self.settings.time_zone(session)
            content = export_rows.json_bytes(export_all.document(session, tz, now))
        return ExportFile(export_rows.all_file_name(export_rows.file_day(now, tz)), export_rows.JSON_TYPE, content)
