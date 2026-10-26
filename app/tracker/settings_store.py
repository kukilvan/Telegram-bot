"""The owner's settings in the `settings` table: the break that splits a season into parts, the delivery rules and the
time zone. Each is read where it is needed, so a change applies at once."""

import asyncio
from collections.abc import Sequence
from datetime import time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from app.tracker import delivery
from app.tracker import seasons as season_logic
from app.tracker.context import CoreContext
from app.tracker.models import SettingRecord

PART_GAP_SETTING = "part_gap_weeks"
DEFAULT_PART_GAP_WEEKS = season_logic.DEFAULT_PART_GAP // timedelta(weeks=1)  # the default lives in `seasons`

# settings of the delivery rules (absent: the default of `delivery`; the time zone falls back to the one the core was given)
TIMEZONE_SETTING = "timezone"
WORKDAYS_SETTING = "workdays"  # weekday numbers, Monday is 0
SUMMARY_AT_SETTING = "summary_at"  # "15:00"
QUIET_FROM_SETTING = "quiet_from"
QUIET_UNTIL_SETTING = "quiet_until"


class SettingsStore:
    def __init__(self, ctx: CoreContext) -> None:
        self.ctx = ctx

    # --- read inside a session someone else opened ----------------------------------------------

    @staticmethod
    def part_gap_weeks_in(session) -> int:
        record = session.get(SettingRecord, PART_GAP_SETTING)
        return record.value if record is not None else DEFAULT_PART_GAP_WEEKS

    @classmethod
    def part_gap(cls, session) -> timedelta:
        return timedelta(weeks=cls.part_gap_weeks_in(session))

    def time_zone(self, session) -> tzinfo:
        """The owner's time zone: the stored setting, else the one the core was given. Read where it is needed, so a
        change applies at once."""
        record = session.get(SettingRecord, TIMEZONE_SETTING)
        return ZoneInfo(record.value) if record is not None else self.ctx.default_tz

    def rules(self, session) -> delivery.DeliveryRules:
        keys = (WORKDAYS_SETTING, SUMMARY_AT_SETTING, QUIET_FROM_SETTING, QUIET_UNTIL_SETTING)
        stored = {r.key: r.value for r in session.scalars(select(SettingRecord).where(SettingRecord.key.in_(keys)))}
        workdays = stored.get(WORKDAYS_SETTING, delivery.DEFAULT_WORKDAYS)
        return delivery.DeliveryRules(
            tz=self.time_zone(session),
            workdays=frozenset(workdays),
            summary_at=delivery.parse_time(stored.get(SUMMARY_AT_SETTING, delivery.DEFAULT_SUMMARY_AT)),
            quiet_from=delivery.parse_time(stored.get(QUIET_FROM_SETTING, delivery.DEFAULT_QUIET_FROM)),
            quiet_until=delivery.parse_time(stored.get(QUIET_UNTIL_SETTING, delivery.DEFAULT_QUIET_UNTIL)),
        )

    # --- the public settings --------------------------------------------------------------------

    async def part_gap_weeks(self) -> int:
        """Weeks of break between two episodes of a season after which the season is split into parts."""
        return await asyncio.to_thread(self._load_part_gap_weeks)

    def _load_part_gap_weeks(self) -> int:
        with self.ctx.session_factory() as session:
            return self.part_gap_weeks_in(session)

    async def set_part_gap_weeks(self, weeks: int) -> None:
        """Change the break that splits a season into parts. Parts are worked out from the dates, so the new
        value applies to cards and events from now on without touching the stored episodes."""
        if weeks < 1:
            raise ValueError("the break between parts is at least one week")
        async with self.ctx.write_lock:
            await asyncio.to_thread(self._store, {PART_GAP_SETTING: weeks})

    async def delivery_rules(self) -> delivery.DeliveryRules:
        """The owner's time zone, working days, summary hour and quiet hours; what is not set is the default."""
        return await asyncio.to_thread(self._load_delivery_rules)

    def _load_delivery_rules(self) -> delivery.DeliveryRules:
        with self.ctx.session_factory() as session:
            return self.rules(session)

    async def set_delivery_rules(
        self,
        *,
        tz_name: str | None = None,
        workdays: Sequence[int] | None = None,
        summary_at: time | str | None = None,
        quiet_from: time | str | None = None,
        quiet_until: time | str | None = None,
    ) -> None:
        """Change the given rules (the others stay). Nothing is stored when any value is wrong.

        `workdays` are weekday numbers, Monday is 0; none at all is allowed (every day is a day off). Equal
        `quiet_from` and `quiet_until` mean no quiet hours. The new rules apply to what is already queued."""
        new: dict[str, Any] = {}
        if tz_name is not None:
            try:
                ZoneInfo(tz_name)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError(f"unknown time zone {tz_name!r}") from exc
            new[TIMEZONE_SETTING] = tz_name
        if workdays is not None:
            days = sorted(set(workdays))
            if any(not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in days):
                raise ValueError("working days are weekday numbers from 0 (Monday) to 6 (Sunday)")
            new[WORKDAYS_SETTING] = days
        for key, value in (
            (SUMMARY_AT_SETTING, summary_at), (QUIET_FROM_SETTING, quiet_from), (QUIET_UNTIL_SETTING, quiet_until)
        ):
            if value is not None:
                new[key] = delivery.format_time(delivery.parse_time(value))
        async with self.ctx.write_lock:
            await asyncio.to_thread(self._store, new)

    def _store(self, values: dict[str, Any]) -> None:
        with self.ctx.session_factory() as session:
            for key, value in values.items():
                record = session.get(SettingRecord, key)
                if record is None:
                    session.add(SettingRecord(key=key, value=value))
                else:
                    record.value = value
            session.commit()
