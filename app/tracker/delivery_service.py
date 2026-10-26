"""Delivery: sending what the queue holds to the owner, one message or one summary, and noting every attempt.

The rules (what goes out now, what waits, how a summary reads) are the pure functions of `delivery`; this module reads
the queue, sends through the sender and records what happened.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from sqlalchemy import select

from app.tracker import delivery
from app.tracker.actions import CARD, FOLLOW, WATCHED, Action, event_actions
from app.tracker.context import CoreContext, naive_utc
from app.tracker.models import DeliveryItem, DeliveryStatus, Event, Title
from app.tracker.results import DeliveryReport, SummaryResult
from app.tracker.settings_store import SettingsStore
from app.utils.secrets_mask import mask_secrets

MAX_SUMMARY_BUTTONS = 10  # buttons of the events inside a summary; «Следить» is shown whatever the limit
BUTTON_NAME_LIMIT = 30


def format_event(event: Event) -> str:
    """Text of the message the owner receives for an event."""
    if event.type == "test":
        return f"🧪 {event.payload['text']}"
    return event.payload.get("text", event.type)


class DeliveryService:
    def __init__(self, ctx: CoreContext, settings: SettingsStore) -> None:
        self.ctx = ctx
        self.settings = settings

    async def deliver_pending(
        self, *, now: datetime | None = None, only: frozenset[int] | None = None, force: bool = False
    ) -> DeliveryReport:
        """Send what the delivery rules let out at this moment. A failed send stays queued; the rest still go out.

        Events that arrived while the bot had to be silent wait and go out in one summary. `force` sends everything
        one by one regardless of the rules; `only` limits the pass to these event ids; `now` stands in for the clock."""
        report = DeliveryReport()
        async with self.ctx.delivery_lock:
            moment = naive_utc(now or self.ctx.clock())
            rules, pending, names = await asyncio.to_thread(self._load_queue, only)
            if force:
                single, summary = pending, []
            else:
                single, summary = rules.due(pending, moment)
            # episodes are folded only inside a summary; failures of one source and reason are folded everywhere
            for unit in delivery.fold(single, episodes=False):
                item = unit.single
                actions = event_actions(item.type, item.event_id, item.title_id, item.data) if item is not None else []
                await self._send(unit.members, unit.text, actions, report)
            if summary:
                await self._send_summary(summary, moment, rules, report, names)
        return report

    async def summary_now(self) -> SummaryResult:
        """«Сводка сейчас»: everything waiting goes out in one summary at once, whatever the hour, and is marked delivered."""
        report = DeliveryReport()
        async with self.ctx.delivery_lock:
            moment = self.ctx.now()
            rules, pending, names = await asyncio.to_thread(self._load_queue, None)
            if pending:
                await self._send_summary(pending, moment, rules, report, names)
        return SummaryResult(events=len(pending), delivered=bool(pending) and report.failed == 0)

    async def all_delivered(self, event_ids: frozenset[int]) -> bool:
        """Every one of these events has its queue entry, and each entry is delivered."""
        return await asyncio.to_thread(self._all_delivered, event_ids)

    def _all_delivered(self, event_ids: frozenset[int]) -> bool:
        with self.ctx.session_factory() as session:
            items = session.scalars(select(DeliveryItem).where(DeliveryItem.event_id.in_(event_ids))).all()
            return len(items) == len(event_ids) and all(item.status == DeliveryStatus.DELIVERED for item in items)

    def _load_queue(
        self, only: frozenset[int] | None
    ) -> tuple[delivery.DeliveryRules, list[delivery.Pending], dict[int, str]]:
        with self.ctx.session_factory() as session:
            query = (
                select(DeliveryItem.id, DeliveryItem.created_at, Event)
                .join(Event, Event.id == DeliveryItem.event_id)
                .where(DeliveryItem.status == DeliveryStatus.PENDING)
                .order_by(DeliveryItem.id)
            )
            if only is not None:
                query = query.where(Event.id.in_(only))
            pending = [
                delivery.Pending(item_id, event.id, event.type, event.title_id, format_event(event), event.payload, created)
                for item_id, created, event in session.execute(query)
            ]
            ids = {p.title_id for p in pending if p.title_id is not None}
            names = {t.id: t.name for t in session.scalars(select(Title).where(Title.id.in_(ids)))} if ids else {}
            return self.settings.rules(session), pending, names

    async def _send_summary(
        self,
        pending: list[delivery.Pending],
        moment: datetime,
        rules: delivery.DeliveryRules,
        report: DeliveryReport,
        names: dict[int, str],
    ) -> None:
        units = delivery.fold(pending, episodes=True)
        for text, held in delivery.summary_messages(units, moment, rules):
            members = tuple(m for unit in held for m in unit.members)
            await self._send(members, text, self._summary_actions(held, names), report)

    @staticmethod
    def _summary_actions(units: list[delivery.Unit], names: dict[int, str]) -> list[Action]:
        """The buttons of the events inside a summary, each saying which title it is for."""
        actions: list[Action] = []
        shown: set[tuple[str, int]] = set()  # one button per action and title, however many events of it the summary holds
        for unit in units:
            single = unit.single
            if single is None:
                continue
            name = single.data.get("sequel_title") or names.get(single.title_id, "")
            if len(name) > BUTTON_NAME_LIMIT:
                name = name[: BUTTON_NAME_LIMIT - 1] + "…"
            for action in event_actions(single.type, single.event_id, single.title_id, single.data):
                if (action.name, action.arg) in shown:
                    continue
                shown.add((action.name, action.arg))
                actions.append(replace(action, label=f"{action.label}: {name}") if name else action)
        # «Следить» is never cut: a sequel announcement has no card or list entry to follow from. The rest fill
        # what is left of the limit, «Посмотрел» before «Карточка», and are reached from «Мои тайтлы» if cut.
        follow = [a for a in actions if a.name == FOLLOW]
        rest = [a for name in (WATCHED, CARD) for a in actions if a.name == name]
        return follow + rest[: max(0, MAX_SUMMARY_BUTTONS - len(follow))]

    async def _send(
        self, members: Sequence[delivery.Pending], message: str, actions: Sequence[Action], report: DeliveryReport
    ) -> None:
        """Send one message that settles all `members`; they are marked delivered only if the send succeeded."""
        error: Exception | None = None
        try:
            await self.ctx.sender.send(message, actions)
        except Exception as exc:  # the sender is a network client: any failure means "try again later"
            error = exc
            logging.warning(
                "delivery of queue items %s failed: %s", [m.item_id for m in members], repr(exc)
            )

        await asyncio.to_thread(self._record_attempts, [m.item_id for m in members], error)
        if error is None:
            report.delivered += len(members)
        else:
            report.failed += len(members)

    def _record_attempts(self, item_ids: Sequence[int], error: Exception | None) -> None:
        now = self.ctx.now()
        with self.ctx.write_session() as session:
            for item_id in item_ids:
                item = session.get(DeliveryItem, item_id)
                if item is None:  # its title was deleted while the message was on its way: the entry is gone with it
                    continue
                item.attempts += 1
                if error is None:
                    item.status = DeliveryStatus.DELIVERED
                    item.last_error = None
                    item.delivered_at = now
                else:
                    item.last_error = mask_secrets(repr(error))[:500]
            session.commit()
