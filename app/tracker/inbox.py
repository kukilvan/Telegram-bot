"""«Входящие»: taking in what the owner sends to the bot, the states of an item and its moves, the 12 hours, the list,
the count and deleting.

A message joins the newest item when it is the same album or a forward that follows its comment, within 2 seconds.

An inbox item is written before the bot answers anything (KI-9: a restart in the middle loses no post). Every change is
one write session (rule 9): «move the waiting ones and write the new one» together, «read the state, change it»
together. A resolved, not saved or removed item is deleted; its number never comes back (`AUTOINCREMENT`). How the bot
reads a Telegram message into an `IncomingMessage` is the bot's (`app/bot/inbox_message.py`); this module gets it ready.
"""

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.tracker.context import CoreContext
from app.tracker.errors import UnknownInboxItem
from app.tracker.models import InboxReason, InboxRecord, InboxState, TitleKind
from app.tracker.results import IncomingMessage, InboxEntry, PauseOutcome, TakeIn

JOIN_WITHIN = timedelta(seconds=2)  # a message joins the newest item at most this long after its last message (1.2)
WAIT_FOR = timedelta(hours=12)  # an item that waits longer than this from its arrival goes to «Входящие» (7.2)
MAX_TEXT = 10_000  # characters of the joined text that are kept
QUERY_LENGTH = 60  # characters of the text «Найти» searches by, cut at a word
_PARAGRAPH = "\n\n"  # between the texts of the joined messages


def query_of(text: str) -> str:
    """What «Найти» of the web searches by: the first `QUERY_LENGTH` characters of the text, cut at a word (ticket 05 of
    stage 6.4 puts the first candidate first)."""
    flat = " ".join(text.split())
    if len(flat) <= QUERY_LENGTH:
        return flat
    head = flat[: QUERY_LENGTH + 1]
    head = head.rsplit(" ", 1)[0] if " " in head else flat[:QUERY_LENGTH]
    return head.rstrip(" ,.;:—-")


def _joins(item: InboxRecord, message: IncomingMessage, now: datetime) -> bool:
    """Whether `message` belongs to the newest item (1.2): within 2 seconds of its last message, and either the same
    album, or a forward that follows one message that was no forward (a comment: Telegram sends it first)."""
    if now - item.last_message_at > JOIN_WITHIN:
        return False
    same_album = message.media_group_id is not None and message.media_group_id == item.media_group_id
    after_comment = message.forwarded and not item.forwarded and item.media_group_id is None
    return same_album or after_comment


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _join(item: InboxRecord, message: IncomingMessage, now: datetime) -> None:
    """Add a message to the item: its text after the item's, its bold pieces, links and post link kept."""
    texts = [text for text in (item.text, message.text) if text.strip()]
    item.text = _PARAGRAPH.join(texts)[:MAX_TEXT]
    item.bold = _unique([*item.bold, *message.bold])
    item.links = _unique([*item.links, *message.links])
    item.media = item.media or message.media
    item.post_url = item.post_url or message.post_url
    item.forwarded = item.forwarded or message.forwarded
    item.media_group_id = item.media_group_id or message.media_group_id
    item.query = query_of(item.text)
    item.last_message_at = now


def _new_item(message: IncomingMessage, now: datetime) -> InboxRecord:
    text = message.text if message.text.strip() else ""
    return InboxRecord(
        state=InboxState.WAITING,
        text=text[:MAX_TEXT],
        media=message.media,
        bold=_unique(list(message.bold)),
        links=_unique(list(message.links)),
        post_url=message.post_url,
        forwarded=message.forwarded,
        media_group_id=message.media_group_id,
        query=query_of(text[:MAX_TEXT]),
        offers=[],
        received_at=now,
        last_message_at=now,
    )


def _move(item: InboxRecord, reason: InboxReason, now: datetime) -> None:
    """To «Входящие» with this reason; an item that is there already only gets the new reason."""
    item.state = InboxState.INBOX
    item.reason = reason
    item.moved_at = item.moved_at or now


def _entry(item: InboxRecord) -> InboxEntry:
    return InboxEntry(
        id=item.id,
        state=item.state,
        reason=item.reason,
        kind=item.kind,
        text=item.text,
        media=item.media,
        bold=tuple(item.bold),
        links=tuple(item.links),
        post_url=item.post_url,
        forwarded=item.forwarded,
        query=item.query,
        received_at=item.received_at,
        moved_at=item.moved_at,
    )


class Inbox:
    def __init__(self, ctx: CoreContext) -> None:
        self.ctx = ctx

    # --- taking in ------------------------------------------------------------------------------

    async def take_in(self, message: IncomingMessage) -> TakeIn:
        return await asyncio.to_thread(self._take_in, message)

    def _take_in(self, message: IncomingMessage) -> TakeIn:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            newest = session.scalars(select(InboxRecord).order_by(InboxRecord.id.desc()).limit(1)).first()
            if newest is not None and _joins(newest, message, now):
                _join(newest, message, now)
                session.commit()
                return TakeIn(newest.id, joined=True, moved=0)
            waiting = list(session.scalars(select(InboxRecord).where(InboxRecord.state == InboxState.WAITING)))
            for item in waiting:
                _move(item, InboxReason.NO_ANSWER, now)
            item = _new_item(message, now)
            session.add(item)
            session.flush()
            item_id = item.id
            session.commit()
        return TakeIn(item_id, joined=False, moved=len(waiting))

    async def pause_over(self, item_id: int) -> PauseOutcome:
        return await asyncio.to_thread(self._pause_over, item_id)

    def _pause_over(self, item_id: int) -> PauseOutcome:
        with self.ctx.write_session() as session:
            item = session.get(InboxRecord, item_id)
            if item is None or item.state != InboxState.WAITING:
                return PauseOutcome.NOTHING
            if item.text:
                return PauseOutcome.ASK
            _move(item, InboxReason.NO_TEXT, self.ctx.now())
            session.commit()
        return PauseOutcome.NO_TEXT

    # --- answers --------------------------------------------------------------------------------

    async def answer_kind(self, item_id: int, kind: TitleKind) -> None:
        await asyncio.to_thread(self._answer_kind, item_id, kind)

    def _answer_kind(self, item_id: int, kind: TitleKind) -> None:
        # until the analysis comes (ticket 04 of stage 6.4) the kind is stored and the item goes to «Входящие»
        with self.ctx.write_session() as session:
            item = self._existing(session, item_id)
            item.kind = kind
            _move(item, InboxReason.NOT_FOUND, self.ctx.now())
            session.commit()

    async def forget(self, item_id: int) -> bool:
        """Delete the item. False: there was none (resolved, not saved or removed already)."""
        return await asyncio.to_thread(self._delete, item_id)

    def _delete(self, item_id: int) -> bool:
        with self.ctx.write_session() as session:
            deleted = session.execute(delete(InboxRecord).where(InboxRecord.id == item_id)).rowcount
            session.commit()
        return bool(deleted)

    async def expire(self) -> int:
        """Items that waited 12 hours from their arrival go to «Входящие» «без ответа», silently. Returns how many."""
        return await asyncio.to_thread(self._expire)

    def _expire(self) -> int:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            overdue = list(session.scalars(
                select(InboxRecord).where(
                    InboxRecord.state == InboxState.WAITING, InboxRecord.received_at <= now - WAIT_FOR
                )
            ))
            for item in overdue:
                _move(item, InboxReason.NO_ANSWER, now)
            session.commit()
        return len(overdue)

    # --- reading --------------------------------------------------------------------------------

    async def item(self, item_id: int) -> InboxEntry | None:
        return await asyncio.to_thread(self._item, item_id)

    def _item(self, item_id: int) -> InboxEntry | None:
        with self.ctx.session_factory() as session:
            item = session.get(InboxRecord, item_id)
            return None if item is None else _entry(item)

    async def items(self) -> list[InboxEntry]:
        """The items in «Входящие» (not the waiting one: it is in the chat), the newest arrival first."""
        return await asyncio.to_thread(self._items)

    def _items(self) -> list[InboxEntry]:
        with self.ctx.session_factory() as session:
            rows = session.scalars(
                select(InboxRecord)
                .where(InboxRecord.state == InboxState.INBOX)
                .order_by(InboxRecord.received_at.desc(), InboxRecord.id.desc())
            )
            return [_entry(item) for item in rows]

    async def count(self) -> int:
        """How many items are in «Входящие»: the number of the menu of the web."""
        return await asyncio.to_thread(self._count)

    def _count(self) -> int:
        with self.ctx.session_factory() as session:
            return session.scalar(
                select(func.count()).select_from(InboxRecord).where(InboxRecord.state == InboxState.INBOX)
            ) or 0

    @staticmethod
    def _existing(session: Session, item_id: int) -> InboxRecord:
        item = session.get(InboxRecord, item_id)
        if item is None:
            raise UnknownInboxItem(item_id)
        return item
