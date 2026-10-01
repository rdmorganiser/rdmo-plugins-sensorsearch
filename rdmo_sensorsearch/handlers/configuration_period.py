from datetime import datetime
from datetime import timezone as dt_timezone

from rdmo_sensorsearch.contracts import ConfigurationPeriod
from rdmo_sensorsearch.handlers.parser import parse_datetime


def parse_configuration_period(
    start_value: str | None,
    end_value: str | None,
) -> tuple[ConfigurationPeriod | None, str | None]:
    start_text = start_value.strip() if isinstance(start_value, str) else ""
    end_text = end_value.strip() if isinstance(end_value, str) else ""

    if not start_text:
        return None, "Enter a membership filter start date before applying the date range."

    start = _parse_timepoint(start_text)
    if start is None:
        return None, "The membership filter start date is invalid. Use YYYY-MM-DD hh:mm."

    end = _parse_timepoint(end_text) if end_text else None
    if end_text and end is None:
        return None, "The membership filter end date is invalid. Use YYYY-MM-DD hh:mm."
    if end is not None and start > end:
        return None, "The membership filter end date must not be earlier than its start date."

    return ConfigurationPeriod(start=start, end=end), None


def _parse_timepoint(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt_timezone.utc)
    return parsed.astimezone(dt_timezone.utc)
