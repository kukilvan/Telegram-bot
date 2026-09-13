"""Manual tests for domain events + state comparison (pure logic, no network)."""

from app.domain.events import (
    DIGITAL_DATE_ANNOUNCED,
    DomainEvent,
    compare_states,
)


def test_fingerprint_stable():
    a = DomainEvent(event_type="X", media_item_id="m1", source="tmdb")
    b = DomainEvent(event_type="X", media_item_id="m1", source="tmdb")
    assert a.fingerprint() == b.fingerprint(), "fingerprint must be stable"


def test_compare_detects_digital_date():
    old = {"digital_release": None}
    new = {"digital_release": "2026-09-10"}
    events = compare_states(old, new)
    assert any(e.event_type == DIGITAL_DATE_ANNOUNCED for e in events), (
        "expected DIGITAL_DATE_ANNOUNCED when date appears"
    )


def test_compare_no_change():
    old = {"digital_release": None}
    new = {"digital_release": None}
    assert compare_states(old, new) == [], "no event when nothing changed"


if __name__ == "__main__":
    test_fingerprint_stable()
    test_compare_detects_digital_date()
    test_compare_no_change()
    print("domain events tests passed")
