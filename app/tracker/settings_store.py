"""The owner's settings in the `settings` table: the break that splits a season into parts, the delivery rules and the
time zone. Each is read where it is needed, so a change applies at once. The settings page reads them all (`settings`)
and stores all of them at once (`save_settings`)."""

import asyncio
import logging
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace
from datetime import time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

from app.tracker import delivery, zones
from app.tracker import seasons as season_logic
from app.tracker.context import CoreContext
from app.tracker.errors import SettingsRefused
from app.tracker.models import SettingRecord
from app.tracker.results import SettingsView

logger = logging.getLogger(__name__)

PART_GAP_SETTING = "part_gap_weeks"
DEFAULT_PART_GAP_WEEKS = season_logic.DEFAULT_PART_GAP // timedelta(weeks=1)  # the default lives in `seasons`
MAX_PART_GAP_WEEKS = 52

# settings of the delivery rules (absent: the default of `delivery`; the time zone falls back to the one the core was given)
TIMEZONE_SETTING = "timezone"
WORKDAYS_SETTING = "workdays"  # weekday numbers, Monday is 0
SUMMARY_AT_SETTING = "summary_at"  # "15:00"
QUIET_FROM_SETTING = "quiet_from"
QUIET_UNTIL_SETTING = "quiet_until"
_TIME_FIELDS = {  # the settings that hold a time of day, and the field of `DeliveryRules` each one fills
    SUMMARY_AT_SETTING: "summary_at", QUIET_FROM_SETTING: "quiet_from", QUIET_UNTIL_SETTING: "quiet_until"
}
_CLOCK = re.compile(r"[0-9]{1,2}:[0-9]{2}")  # «7:30» or «07:30»: what a time field of the form sends
_WEEKS = re.compile(r"[0-9]{1,3}")


@dataclass(frozen=True)
class SettingsChange:
    """What the settings form sent, as it came: the core reads the texts, so the web has no part in the rules."""

    tz_name: str  # «»: the zone of the launch file
    workdays: Collection[int]
    summary_at: str
    quiet_from: str
    quiet_until: str
    part_gap_weeks: str


def check_part_gap_weeks(weeks: int) -> None:
    """The break between parts is from one week to `MAX_PART_GAP_WEEKS`; a ValueError otherwise."""
    if not 1 <= weeks <= MAX_PART_GAP_WEEKS:
        raise ValueError(f"the break between parts is from 1 to {MAX_PART_GAP_WEEKS} weeks")


def _clock(text: str) -> time:
    """«7:30» or «07:30» to a time; a ValueError for anything else («24:00», «15-00», «», «abc»)."""
    text = text.strip()
    if not _CLOCK.fullmatch(text):
        raise ValueError(f"time must look like 15:00, got {text!r}")
    return delivery.parse_time(text)


class SettingsStore:
    def __init__(self, ctx: CoreContext) -> None:
        self.ctx = ctx
        self._spoiled_zones: set[str] = set()  # stored zones that are not zones, as the log has told: once each

    # --- read inside a session someone else opened ----------------------------------------------

    @staticmethod
    def part_gap_weeks_in(session) -> int:
        record = session.get(SettingRecord, PART_GAP_SETTING)
        return record.value if record is not None else DEFAULT_PART_GAP_WEEKS

    @classmethod
    def part_gap(cls, session) -> timedelta:
        return timedelta(weeks=cls.part_gap_weeks_in(session))

    def stored_zone(self, session) -> str | None:
        """The name of the zone chosen in the settings; None when none is chosen. A stored value that is not a zone
        reads as «none chosen» (it would otherwise break the feed and the queue), and the log says so once."""
        record = session.get(SettingRecord, TIMEZONE_SETTING)
        if record is None:
            return None
        try:
            if not isinstance(record.value, str):
                raise ValueError("a time zone is a name")
            ZoneInfo(record.value)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            if repr(record.value) not in self._spoiled_zones:
                self._spoiled_zones.add(repr(record.value))
                logger.warning("the stored time zone %r is not a zone; the zone of the launch file works", record.value)
            return None
        return record.value

    def time_zone(self, session) -> tzinfo:
        """The owner's time zone: the stored setting, else the one the core was given. Read where it is needed, so a
        change applies at once."""
        name = self.stored_zone(session)
        return ZoneInfo(name) if name is not None else self.ctx.default_tz

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
        """Change the break that splits a season into parts (1 to 52 weeks, a ValueError otherwise). Parts are worked
        out from the dates, so the new value applies to cards and events from now on without touching the stored
        episodes."""
        check_part_gap_weeks(weeks)
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
        `quiet_from` and `quiet_until` mean no quiet hours. A summary hour inside the quiet hours is refused (the rules are
        checked whole, with what is stored): the bot would stay silent on working days. The new rules apply to what is
        already queued."""
        new: dict[str, Any] = {}  # the settings to store, as stored
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
        await asyncio.to_thread(self._check_and_store, new)

    # --- the settings page ----------------------------------------------------------------------

    async def settings(self) -> SettingsView:
        """Every setting in one read, with the zone list and the line «Сейчас» (by the stored rules)."""
        return await asyncio.to_thread(self._load_settings)

    def _load_settings(self) -> SettingsView:
        now = self.ctx.clock()
        with self.ctx.session_factory() as session:
            rules = self.rules(session)
            tz_name = self.stored_zone(session)
            weeks = self.part_gap_weeks_in(session)
        default_name = getattr(self.ctx.default_tz, "key", None) or zones.UTC
        return SettingsView(
            tz_name=tz_name,
            default_tz_name=default_name,
            zones=zones.options(now, tz_name),
            default_label=f"Как в файле настроек запуска: {zones.label(default_name, now)}",
            workdays=rules.workdays,
            summary_at=delivery.format_time(rules.summary_at),
            quiet_from=delivery.format_time(rules.quiet_from),
            quiet_until=delivery.format_time(rules.quiet_until),
            part_gap_weeks=weeks,
            now_line=delivery.now_line(rules, self.ctx.now()),
        )

    async def save_settings(self, change: SettingsChange) -> None:
        """Store the whole form: all six settings or, when a value is wrong, none (`SettingsRefused` names the first
        wrong one, in the order of the form). The new rules apply from the next pass of the delivery queue."""
        await asyncio.to_thread(self._save_settings, change)

    def _save_settings(self, change: SettingsChange) -> None:
        values = self._checked(change)
        with self.ctx.write_session() as session:  # one transaction: two forms at once never leave half of each
            self._put(session, values)
            session.commit()

    @staticmethod
    def _checked(change: SettingsChange) -> dict[str, Any]:
        """The settings to store, as stored (None: no record, the default works), or the first refusal."""
        if change.tz_name and change.tz_name not in zones.known_names():
            raise SettingsRefused("timezone", "Такого часового пояса нет — выберите его из списка")
        days = sorted(set(change.workdays))
        if any(not isinstance(d, int) or isinstance(d, bool) or not 0 <= d <= 6 for d in days):
            raise SettingsRefused("workdays", "Рабочие дни: выберите дни недели из списка")
        try:
            summary_at = _clock(change.summary_at)
        except ValueError:
            raise SettingsRefused("summary_at", "Час сводки: время пишется так — 15:00") from None
        try:
            quiet_from, quiet_until = _clock(change.quiet_from), _clock(change.quiet_until)
        except ValueError:
            raise SettingsRefused("quiet", "Тихие часы: время пишется так — 21:00") from None
        try:
            delivery.DeliveryRules(summary_at=summary_at, quiet_from=quiet_from, quiet_until=quiet_until).check()
        except ValueError as exc:
            clash = str(exc)
            raise SettingsRefused(
                "summary_at", f"{clash[:1].upper()}{clash[1:]} — сводка не придёт. Сдвиньте час сводки или тихие часы"
            ) from exc
        try:
            weeks = int(_WEEKS.fullmatch(change.part_gap_weeks.strip())[0])  # TypeError: not a whole number of weeks
            check_part_gap_weeks(weeks)
        except (TypeError, ValueError):
            raise SettingsRefused("part_gap_weeks", "Части сезона: число недель — целое, от 1 до 52") from None
        return {
            TIMEZONE_SETTING: change.tz_name or None,
            WORKDAYS_SETTING: days,
            SUMMARY_AT_SETTING: delivery.format_time(summary_at),
            QUIET_FROM_SETTING: delivery.format_time(quiet_from),
            QUIET_UNTIL_SETTING: delivery.format_time(quiet_until),
            PART_GAP_SETTING: weeks,
        }

    def _check_and_store(self, new: dict[str, Any]) -> None:
        """Store `new` only when the rules it makes (the stored ones with these values over them) can send a summary.
        Read, check and write are in one write session: two changes cannot both pass the check."""
        with self.ctx.write_session() as session:
            changes = {field: delivery.parse_time(new[key]) for key, field in _TIME_FIELDS.items() if key in new}
            if changes:  # rules stored before the check existed may clash; changing something else must still work
                replace(self.rules(session), **changes).check()
            self._put(session, new)
            session.commit()

    def _store(self, values: dict[str, Any]) -> None:
        with self.ctx.write_session() as session:
            self._put(session, values)
            session.commit()

    @staticmethod
    def _put(session, values: dict[str, Any]) -> None:
        for key, value in values.items():
            record = session.get(SettingRecord, key)
            if value is None:  # not set: the record goes and the default works again
                if record is not None:
                    session.delete(record)
            elif record is None:
                session.add(SettingRecord(key=key, value=value))
            else:
                record.value = value
