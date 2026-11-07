"""A moment in words (spec 2.1 of stage 7.1): today, yesterday, this year, another year; around midnight; the owner's
clock decides which day «now» is, the time of the copy is read as written."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.tracker.delivery import DeliveryRules
from app.tracker.moment_words import moment_in_words

NOW = datetime(2026, 11, 7, 16, 20)


def test_today_and_yesterday_are_named():
    assert moment_in_words(datetime(2026, 11, 7, 7, 58), NOW) == "сегодня в 07:58"
    assert moment_in_words(datetime(2026, 11, 6, 18, 32), NOW) == "вчера в 18:32"


def test_another_day_of_this_year_has_its_date_without_the_year():
    assert moment_in_words(datetime(2026, 11, 4, 7, 58), NOW) == "4 ноября в 07:58"
    assert moment_in_words(datetime(2026, 1, 31, 23, 5), NOW) == "31 января в 23:05"


def test_another_year_has_the_year():
    assert moment_in_words(datetime(2025, 11, 4, 7, 58), NOW) == "4 ноября 2025 в 07:58"
    assert moment_in_words(datetime(2025, 12, 31, 12, 0), datetime(2026, 1, 1, 0, 5)) == "вчера в 12:00"
    assert moment_in_words(datetime(2025, 12, 30, 12, 0), datetime(2026, 1, 1, 0, 5)) == "30 декабря 2025 в 12:00"


def test_around_midnight_the_day_decides_not_the_hours_between():
    just_after = datetime(2026, 11, 7, 0, 1)
    assert moment_in_words(datetime(2026, 11, 6, 23, 59), just_after) == "вчера в 23:59"
    assert moment_in_words(datetime(2026, 11, 7, 0, 0), datetime(2026, 11, 7, 23, 59)) == "сегодня в 00:00"


def test_the_day_is_counted_on_the_owners_clock_not_on_utc():
    moment_utc = datetime(2026, 11, 7, 22, 30, tzinfo=timezone.utc)  # 8 November, 01:30 in Moscow
    for zone, expected in (("Europe/Moscow", "вчера в 07:58"), ("UTC", "сегодня в 07:58")):
        rules = DeliveryRules(tz=ZoneInfo(zone))
        owner_now = rules.local(moment_utc.replace(tzinfo=None))
        assert moment_in_words(datetime(2026, 11, 7, 7, 58), owner_now) == expected
