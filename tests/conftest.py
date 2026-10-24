"""Shared test setup.

The tracker tests are about *what* is reported, not *when* it is delivered, and they run at arbitrary clock times.
So by default every window of the delivery rules is open there: no working days, no quiet hours. The tests of the
rules themselves (`test_tracker_delivery.py`) set their own rules and do not depend on the defaults.
"""

from datetime import time

import pytest

from app.tracker import delivery


@pytest.fixture(autouse=True)
def delivery_windows_open(monkeypatch):
    monkeypatch.setattr(delivery, "DEFAULT_WORKDAYS", frozenset())
    monkeypatch.setattr(delivery, "DEFAULT_QUIET_FROM", time(0, 0))
    monkeypatch.setattr(delivery, "DEFAULT_QUIET_UNTIL", time(0, 0))
