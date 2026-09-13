"""No-network unit tests for digital release normalization (Phase 6).

Uses the real TMDb nested per-region structure + integer type codes so the
tests match live API shape (not just flat/string assumptions).
"""

from app.scheduler.polling import _earliest_digital_date


def test_earliest_digital_date():
    regions = [
        {"iso_3166_1": "US", "release_dates": [{"type": 3, "release_date": "2021-10-01T00:00:00.000Z"}]},
        {"iso_3166_1": "RU", "release_dates": [{"type": 4, "release_date": "2021-12-01T00:00:00.000Z"}, {"type": 5, "release_date": "2022-01-01T00:00:00.000Z"}]},
        {"iso_3166_1": "DE", "release_dates": [{"type": 4, "release_date": "2021-12-15T00:00:00.000Z"}]},
    ]
    assert _earliest_digital_date(regions) == "2021-12-01"


def test_no_digital_type():
    assert _earliest_digital_date([]) is None
    regions = [{"iso_3166_1": "US", "release_dates": [{"type": 3, "release_date": "2021-10-01T00:00:00.000Z"}]}]
    assert _earliest_digital_date(regions) is None


if __name__ == "__main__":
    test_earliest_digital_date()
    test_no_digital_type()
    print("release state tests passed")
