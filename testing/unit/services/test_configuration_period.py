"""Period validation is pure logic shared by interview context readers."""

from datetime import datetime, timezone

import pytest

from rdmo_sensorsearch.contracts import ConfigurationPeriod
from rdmo_sensorsearch.services.configuration_period import parse_configuration_period


@pytest.mark.parametrize("end", [None, "", " \t "])
def test_period_supports_an_optional_end_and_trims_input(end):
    period, error = parse_configuration_period(" 2025-01-01 12:00 \t", end)

    assert error is None
    assert period == ConfigurationPeriod(datetime(2025, 1, 1, 12, tzinfo=timezone.utc))


@pytest.mark.parametrize(
    "start,expected",
    [
        ("2025-01-01", "2025-01-01T00:00:00+00:00"),
        ("2025-01-01 12:00", "2025-01-01T12:00:00+00:00"),
        ("2025-01-01T12:00:30.123456", "2025-01-01T12:00:30.123456+00:00"),
        ("2025-01-01T12:00:00Z", "2025-01-01T12:00:00+00:00"),
        ("2025-01-01T14:00:00+02:00", "2025-01-01T12:00:00+00:00"),
        ("2025-01-01T07:00:00-05:00", "2025-01-01T12:00:00+00:00"),
    ],
)
def test_period_preserves_accepted_iso_formats_and_normalizes_to_utc(start, expected):
    period, error = parse_configuration_period(start, None)

    assert error is None
    assert period.start.isoformat() == expected
    assert period.start.tzinfo is timezone.utc


def test_period_accepts_equal_endpoints_after_utc_normalization():
    period, error = parse_configuration_period("2025-01-01T14:00:00+02:00", " 2025-01-01T12:00:00Z ")

    assert error is None
    assert period.start == period.end == datetime(2025, 1, 1, 12, tzinfo=timezone.utc)
    assert period.end.tzinfo is timezone.utc


@pytest.mark.parametrize(
    "start,end,expected_error",
    [
        (None, None, "Enter a membership filter start date before applying the date range."),
        ("", None, "Enter a membership filter start date before applying the date range."),
        (" \t ", "invalid", "Enter a membership filter start date before applying the date range."),
        (42, None, "Enter a membership filter start date before applying the date range."),
        ("not a date", None, "The membership filter start date is invalid. Use YYYY-MM-DD hh:mm."),
        ("2025-02-30", "invalid", "The membership filter start date is invalid. Use YYYY-MM-DD hh:mm."),
        ("2025-01-01", "not a date", "The membership filter end date is invalid. Use YYYY-MM-DD hh:mm."),
        ("2025-01-01", "2025-02-30", "The membership filter end date is invalid. Use YYYY-MM-DD hh:mm."),
        (
            "2025-02-01 00:00",
            "2025-01-01 00:00",
            "The membership filter end date must not be earlier than its start date.",
        ),
        (
            "2025-01-01T12:00:00Z",
            "2025-01-01T13:00:00+02:00",
            "The membership filter end date must not be earlier than its start date.",
        ),
    ],
)
def test_period_validation_fails_closed_with_existing_error_messages(start, end, expected_error):
    assert parse_configuration_period(start, end) == (None, expected_error)
