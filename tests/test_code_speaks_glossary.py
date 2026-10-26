"""The code speaks the glossary of `CONTEXT.md`: one English name per term, and the forbidden words stay out."""

import pathlib
import re

from app.bot.tracker_handlers import SUMMARY_BUTTON
from app.tracker import delivery, test_samples
from app.tracker import core
from app.tracker.core import Tracker
from app.tracker.models import Title

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
MIGRATION_0009 = "0009_code_speaks_glossary.py"


def app_files():
    return [path for path in APP.rglob("*.py") if path.name != MIGRATION_0009]


def test_the_word_digest_is_not_in_the_code():
    offenders = [str(p.relative_to(APP)) for p in app_files() if re.search("digest", p.read_text(encoding="utf-8"), re.I)]
    assert offenders == []


def test_a_title_keeps_its_name_in_name_and_original_name():
    columns = Title.__table__.columns.keys()
    assert "name" in columns and "original_name" in columns
    assert "title" not in columns and "original_title" not in columns


def test_the_summary_has_one_name_everywhere():
    assert SUMMARY_BUTTON == "📋 Сводка сейчас"
    assert hasattr(Tracker, "summary_now") and not hasattr(Tracker, "digest_now")
    assert hasattr(delivery.DeliveryRules(), "summary_at")
    assert hasattr(delivery, "summary_messages") and hasattr(delivery, "DEFAULT_SUMMARY_AT")


def test_samples_and_delivery_checks_have_their_own_words():
    assert hasattr(Tracker, "test_samples") and hasattr(Tracker, "register_test_sample")
    assert hasattr(Tracker, "delivery_check_moment")
    assert hasattr(test_samples, "DELIVERY_CHECKS") and hasattr(test_samples, "delivery_check_by_id")
    assert hasattr(core, "TestSample") and hasattr(test_samples, "DeliveryCheck")
    gone = ("TestEventKind", "test_event_kinds", "register_test_event_kind", "window_test_moment")
    assert not any(hasattr(Tracker, name) or hasattr(core, name) for name in gone)
    assert not hasattr(delivery, "WindowScenario") and not hasattr(delivery, "scenario_by_id")
