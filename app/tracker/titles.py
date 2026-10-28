"""The owner's list: searching, adding and deleting titles and «Следить». What differs by kind (the first seasons, the
first check) is asked of the title's poller. The marks and statuses are in `statuses`, the rows and the card in `listing`."""

import asyncio
import logging
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select

from app.tracker import sequel_events, storage
from app.tracker.context import PRIMARY_ROLE, CoreContext
from app.tracker.errors import SourceFailed, TitleNotFound, UnknownEvent, UnknownKind, UnknownTitle
from app.tracker.models import ExternalId, Event, SourceSnapshot, Title, TitleKind, TitleStatus
from app.tracker.results import AddResult, DeleteResult

if TYPE_CHECKING:
    from app.tracker.pollers.base import Poller
    from app.tracker.polling import Pollers


class Titles:
    def __init__(self, ctx: CoreContext, pollers: "Pollers") -> None:
        self.ctx = ctx
        self.pollers = pollers

    # --- adding ---------------------------------------------------------------------------------

    async def search(self, kind: TitleKind, query: str) -> list[Any]:
        """Suggestions for `query` from the source of this kind, each with the number of its title when the title is in
        the list already (found after the source answered, in one read). Raises KeyError for an unknown kind and
        SourceFailed when the source fails."""
        poller = self.pollers.of(kind)
        try:
            suggestions = await poller.source.suggest(query)
        except Exception as exc:
            raise SourceFailed(poller.source.source_key) from exc
        if not suggestions:
            return suggestions
        known = await asyncio.to_thread(self._known_ids, poller, [s.external_id for s in suggestions])
        return [replace(s, title_id=known.get(s.external_id)) for s in suggestions]

    async def add_title(self, kind: TitleKind, external_id: str) -> AddResult:
        """Put a search result into the list with status «Хочу», or open the title that is already there: the one the
        id names, or the one any id of the fresh snapshot names (an anime by any entry of its chain, KI-2)."""
        poller = self.pollers.of(kind)
        known = await asyncio.to_thread(self._known_ids, poller, [external_id])
        if external_id in known:
            return AddResult(known[external_id], created=False)
        source = poller.source
        try:
            snapshot = await source.snapshot(external_id)
        except Exception as exc:
            raise SourceFailed(source.source_key) from exc
        if snapshot is None:
            raise TitleNotFound(f"{source.source_key}:{external_id}")
        return await asyncio.to_thread(self._store_title, kind, snapshot)

    def _known_ids(self, poller: "Poller", ids: list[str]) -> dict[str, int]:
        with self.ctx.session_factory() as session:
            return poller.known_ids(session, ids)

    def _store_title(self, kind: TitleKind, snapshot: Any) -> AddResult:
        now = self.ctx.now()
        poller = self.pollers.of(kind)
        source_key = poller.source.source_key
        with self.ctx.write_session() as session:
            # the same title may have been added by a second request while this one waited for the source, or long ago
            # under another id of the snapshot: the write session holds the database, so what is seen here stays true
            # until the commit
            known = sorted(set(poller.known_ids(session, poller.snapshot_ids(snapshot)).values()))
            if known:
                if len(known) > 1:
                    logging.warning(
                        "%s:%s names the titles %s; the first one is opened", source_key, snapshot.external_id, known
                    )
                return AddResult(known[0], created=False)
            title = Title(
                kind=kind,
                name=snapshot.name,
                original_name=snapshot.original_name,
                year=snapshot.year,
                genres=list(snapshot.genres),
                poster_path=snapshot.poster_path,
                overview=snapshot.overview,
                status=TitleStatus.WANT,
                tracking_enabled=True,
                added_at=now,
                status_changed_at=now,
            )
            session.add(title)
            session.flush()
            session.add(
                ExternalId(title_id=title.id, source=source_key, external_id=snapshot.external_id, role=PRIMARY_ROLE)
            )
            state = snapshot.state()
            seasons = poller.first_seasons(snapshot, now)
            session.add(
                SourceSnapshot(
                    title_id=title.id,
                    source=source_key,
                    state=state,
                    observed_at=now,
                    # the snapshot taken now is the baseline; the first poll compares against it
                    next_check_at=poller.first_check(seasons, state, now),
                )
            )
            records = storage.store_seasons(session, title.id, seasons)
            poller.store_extras(session, title.id, records, snapshot)
            storage.refresh_status(session, title, now)
            session.commit()
            return AddResult(title.id, created=True)

    # --- deleting -------------------------------------------------------------------------------

    async def delete_title(self, title_id: int) -> DeleteResult:
        """Remove a title and everything that belongs to it, in one transaction: all of it or nothing."""
        return await asyncio.to_thread(self._delete_title, title_id)

    def _delete_title(self, title_id: int) -> DeleteResult:
        with self.ctx.write_session() as session:
            name = session.scalar(select(Title.name).where(Title.id == title_id))
            if name is None:
                raise UnknownTitle(title_id)
            # the database cascades: seasons, ids, snapshots, events, and the queue entries of those events
            removed = session.execute(delete(Title).where(Title.id == title_id)).rowcount
            if not removed:  # deleted by someone else since the name was read
                session.rollback()
                raise UnknownTitle(title_id)
            session.commit()
            return DeleteResult(name)

    # --- sequels --------------------------------------------------------------------------------

    async def follow_sequel_of(self, kind: str, sequel_id: str) -> AddResult:
        """«Следить» under a sequel announcement: the sequel joins the list as «Хочу». Pressing twice opens it.
        The button names the sequel, so it works even when the announcement or its film is gone."""
        try:
            title_kind = TitleKind(kind)  # `kind` is text from a button or a stored event
        except ValueError:
            raise UnknownKind(kind) from None
        if self.pollers.sequels_of(title_kind) is None:
            raise UnknownKind(kind)
        return await self.add_title(title_kind, sequel_id)

    async def follow_sequel(self, event_id: int) -> AddResult:
        """The same for an old button, which holds only the number of the announcement: works while the event exists."""
        kind, sequel_id = await asyncio.to_thread(self._announced_sequel, event_id)
        return await self.follow_sequel_of(kind, sequel_id)

    def _announced_sequel(self, event_id: int) -> tuple[str, str]:
        with self.ctx.session_factory() as session:
            event = session.get(Event, event_id)
            if event is None or event.type != sequel_events.SEQUEL_ANNOUNCED:
                raise UnknownEvent(event_id)
            return event.payload["kind"], event.payload["sequel_id"]
