"""Shared test setup.

The tracker tests are about *what* is reported, not *when* it is delivered, and they run at arbitrary clock times.
So by default every window of the delivery rules is open there: no working days, no quiet hours. The tests of the
rules themselves (`test_tracker_delivery.py`) set their own rules and do not depend on the defaults.
"""

from datetime import time

import pytest
from fastapi.testclient import TestClient

from app.tracker import delivery
from app.utils import secrets_mask


@pytest.fixture(autouse=True)
def secrets_not_remembered(monkeypatch):
    """The secrets are remembered once per run; a test that changes the environment starts with nothing remembered."""
    monkeypatch.setattr(secrets_mask, "_remembered", None)


@pytest.fixture(autouse=True)
def delivery_windows_open(monkeypatch):
    monkeypatch.setattr(delivery, "DEFAULT_WORKDAYS", frozenset())
    monkeypatch.setattr(delivery, "DEFAULT_QUIET_FROM", time(0, 0))
    monkeypatch.setattr(delivery, "DEFAULT_QUIET_UNTIL", time(0, 0))


@pytest.fixture(autouse=True)
def web_tests_come_as_localhost(monkeypatch):
    """The web answers only under its own names (`app/web/hosts.py`), and the test client's default name `testserver` is
    not one of them: every test client comes as `localhost` unless the test names another address itself."""
    original = TestClient.__init__

    def init(self, app, base_url="http://localhost", *args, **kwargs):
        original(self, app, base_url, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", init)
