"""The answers to an inbox item: the end of its pause, the analysis by its links or by the kind the owner chose, the
offer cards, «Да» and «Нет» (spec 1.3, 2.3, 6 and 7 of stage 6.4).

The searches (`offers`) take seconds and run outside any session; what they found is written in one write session
that reads the item again (rule 9): an item removed meanwhile is UnknownInboxItem, an item a new post moved to
«Входящие» meanwhile still gets its offers (7.4). An item in «Входящие» keeps its state: an offer found for it is sent,
it never becomes `waiting` again (7.3). Whether an offer is in the list is checked again each time its card is shown;
in the list, the item is resolved — deleted. «Да» adds as the web does (`Titles.add_title`).
"""

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.tracker.candidates import Candidate, SourceLink, candidates, is_name_message, source_links, years
from app.tracker.cards import local_moment
from app.tracker.context import CoreContext
from app.tracker.errors import SourceFailed, SourceNotConfigured, TitleNotFound, UnknownInboxItem
from app.tracker.inbox import existing, move
from app.tracker.models import InboxReason, InboxRecord, InboxState, TitleKind
from app.tracker.offers import Found, Offer, OfferSearch, card_text, new_from, shown
from app.tracker.results import InboxOutcome, InboxReply, OfferCard
from app.tracker.settings_store import SettingsStore

if TYPE_CHECKING:
    from app.tracker.polling import Pollers
    from app.tracker.titles import Titles

_REASONS = {  # the analysis without an offer: why the item went to «Входящие», and what the bot says
    InboxOutcome.NOT_FOUND: InboxReason.NOT_FOUND,
    InboxOutcome.SOURCE_FAILED: InboxReason.SOURCE_FAILED,
    InboxOutcome.NOT_CONNECTED: InboxReason.NOT_CONNECTED,
}


@dataclass(frozen=True)
class _Look:
    """What the analysis of an item reads of it."""

    has_text: bool
    links: tuple[SourceLink, ...]
    candidates: tuple[Candidate, ...]
    name_message: bool
    years: tuple[int, ...]
    new_since: date


def _offers(item: InboxRecord) -> list[Offer]:
    return [Offer.read(raw) for raw in item.offers]


def _without_offer(found: Found) -> InboxOutcome:
    if found.not_connected:
        return InboxOutcome.NOT_CONNECTED
    return InboxOutcome.SOURCE_FAILED if found.failed else InboxOutcome.NOT_FOUND


class InboxAnswers:
    def __init__(
        self, ctx: CoreContext, settings: SettingsStore, pollers: "Pollers", titles: "Titles", imdb_source: Any = None
    ) -> None:
        self.ctx = ctx
        self.settings = settings
        self.pollers = pollers
        self.titles = titles
        self.search = OfferSearch(titles, pollers, imdb_source)

    # --- the pause ------------------------------------------------------------------------------

    async def pause_over(self, item_id: int) -> InboxReply:
        """An item with links of sources is looked up by them, no question; one they give nothing for goes on as one
        without links: «Что это?», or «нет текста» without text."""
        look = await asyncio.to_thread(self._pause_look, item_id)
        if isinstance(look, InboxReply):
            return look
        if look.links:
            found = await self.search.by_links(look.links, look.candidates, years=look.years, new_since=look.new_since)
            try:
                if found.offers:
                    return await asyncio.to_thread(self._finish, item_id, found.kind, found, found.offers[0].name)
                if found.not_connected:
                    return await asyncio.to_thread(self._finish, item_id, None, found, None)
            except UnknownInboxItem:  # removed on the web while the links were looked up
                return InboxReply(InboxOutcome.NOTHING)
        if look.has_text:
            return InboxReply(InboxOutcome.ASK)
        return await asyncio.to_thread(self._no_text, item_id)

    def _pause_look(self, item_id: int) -> _Look | InboxReply:
        with self.ctx.write_session() as session:
            item = session.get(InboxRecord, item_id)
            if item is None or item.state != InboxState.WAITING:
                return InboxReply(InboxOutcome.NOTHING)
            look = self._look(session, item)
            if not look.links and not look.has_text:
                move(item, InboxReason.NO_TEXT, self.ctx.now())
                session.commit()
                return InboxReply(InboxOutcome.NO_TEXT)
            return look

    def _no_text(self, item_id: int) -> InboxReply:
        with self.ctx.write_session() as session:
            item = session.get(InboxRecord, item_id)
            if item is None:
                return InboxReply(InboxOutcome.NOTHING)
            move(item, InboxReason.NO_TEXT, self.ctx.now())
            session.commit()
        return InboxReply(InboxOutcome.NO_TEXT)

    def _look(self, session: Session, item: InboxRecord) -> _Look:
        found = candidates(item.text, bold=tuple(item.bold), links=tuple(item.links), forwarded=item.forwarded)
        return _Look(
            has_text=bool(item.text.strip()),
            links=source_links(item.text, tuple(item.links)),
            candidates=tuple(found),
            name_message=is_name_message(item.text, forwarded=item.forwarded),
            years=years(item.text),
            new_since=new_from(self._today(session)),
        )

    def _today(self, session: Session) -> date:
        return local_moment(self.ctx.now(), self.settings.time_zone(session)).date()  # the zone read here (rule 2)

    # --- the kind ---------------------------------------------------------------------------------

    async def answer_kind(self, item_id: int, kind: TitleKind) -> InboxReply:
        """The analysis of the name candidates in the source of the kind. UnknownInboxItem when the item is gone."""
        look = await asyncio.to_thread(self._read_look, item_id)
        found = await self.search.by_kind(
            kind, look.candidates, name_message=look.name_message, years=look.years, new_since=look.new_since
        )
        return await asyncio.to_thread(self._finish, item_id, kind, found, None)

    def _read_look(self, item_id: int) -> _Look:
        with self.ctx.session_factory() as session:
            return self._look(session, existing(session, item_id))

    def _finish(self, item_id: int, kind: TitleKind | None, found: Found, query: str | None) -> InboxReply:
        """Store what the analysis found and say it: the first offer, or the item goes to «Входящие» with the reason."""
        with self.ctx.write_session() as session:
            item = existing(session, item_id)
            item.kind = kind or item.kind
            item.offers = [offer.stored() for offer in found.offers]
            item.query = query or item.query
            if found.offers:
                return self._show(session, item, 0)
            outcome = _without_offer(found)
            move(item, _REASONS[outcome], self.ctx.now())
            session.commit()
        return InboxReply(outcome, kind)

    def _show(self, session: Session, item: InboxRecord, number: int) -> InboxReply:
        """The card of offer `number`, or «Уже в списке» when its title is in the list (looked at now): the item is
        resolved. Commits."""
        offers = _offers(item)
        offer = offers[number]
        try:
            listed = self.pollers.of(offer.kind).known_ids(session, [offer.external_id]).get(offer.external_id)
        except KeyError:  # the core has no source of that kind: nothing of it can be in the list
            listed = None
        if listed is not None:
            session.delete(item)
            session.commit()
            return InboxReply(InboxOutcome.IN_LIST, offer.kind, title_id=listed)
        item.offers = [o.stored() for o in shown(offers, number)]
        card = OfferCard(item.id, number, card_text(offer, self._today(session)), offer.poster)
        session.commit()
        return InboxReply(InboxOutcome.OFFER, offer.kind, offer=card)

    # --- «Да» и «Нет» -----------------------------------------------------------------------------

    async def answer_offer(self, item_id: int, number: int, accepted: bool) -> InboxReply:
        """«Да»: the title is added as on the web and the item resolved; «Нет»: the next offer, or «Входящие» «не нашёл»
        after the last one. UnknownInboxItem when the item is gone."""
        if not accepted:
            return await asyncio.to_thread(self._decline, item_id, number)
        offer = await asyncio.to_thread(self._offer, item_id, number)
        if offer is None:
            return InboxReply(InboxOutcome.DEAD)
        try:
            added = await self.titles.add_title(offer.kind, offer.external_id)
        except SourceNotConfigured:
            return InboxReply(InboxOutcome.ADD_NOT_CONNECTED, offer.kind)
        except TitleNotFound:  # the source no longer has it: as «Нет» on this offer
            return await asyncio.to_thread(self._decline, item_id, number)
        except (SourceFailed, KeyError):
            return InboxReply(InboxOutcome.ADD_FAILED, offer.kind)
        await asyncio.to_thread(self._resolve, item_id)
        outcome = InboxOutcome.ADDED if added.created else InboxOutcome.IN_LIST
        return InboxReply(outcome, offer.kind, title_id=added.title_id)

    def _offer(self, item_id: int, number: int) -> Offer | None:
        with self.ctx.session_factory() as session:
            offers = _offers(existing(session, item_id))
        return offers[number] if 0 <= number < len(offers) else None

    def _decline(self, item_id: int, number: int) -> InboxReply:
        """The next offer not shown yet (a second «Нет» on the same card goes past the one the first showed), or the
        item goes to «Входящие» «не нашёл»."""
        with self.ctx.write_session() as session:
            item = existing(session, item_id)
            offers = _offers(item)
            if not 0 <= number < len(offers):
                return InboxReply(InboxOutcome.DEAD)
            following = [index for index in range(number + 1, len(offers)) if not offers[index].shown]
            if following:
                return self._show(session, item, following[0])
            move(item, InboxReason.NOT_FOUND, self.ctx.now())
            session.commit()
        return InboxReply(InboxOutcome.NOT_FOUND, offers[number].kind)

    def _resolve(self, item_id: int) -> None:
        with self.ctx.write_session() as session:
            item = session.get(InboxRecord, item_id)
            if item is not None:  # removed on the web meanwhile: nothing to resolve
                session.delete(item)
                session.commit()

