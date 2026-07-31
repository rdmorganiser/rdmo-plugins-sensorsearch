from dataclasses import dataclass
from datetime import datetime
from datetime import timezone as dt_timezone

from rdmo_sensorsearch.handlers.parser import parse_datetime
from rdmo_sensorsearch.utils import get_scoped_project_value

APPLY_DATE_RANGE_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/apply-date-range"


@dataclass(frozen=True)
class ConfigurationPeriod:
    start: datetime
    end: datetime | None = None

    @property
    def formatted(self) -> tuple[str, str | None]:
        return _format_timepoint(self.start), _format_timepoint(self.end)


def catalog_uses_explicit_configuration_period(instance) -> bool:
    """Return whether the active catalog actually contains the apply trigger."""
    project = getattr(instance, "project", None)
    catalog = getattr(project, "catalog", None)
    if catalog is None:
        return False

    catalog.prefetch_elements()
    return any(_element_contains_attribute(page, APPLY_DATE_RANGE_ATTRIBUTE_URI) for page in catalog.pages)


def read_configuration_period(
    instance,
    start_attribute_uri: str,
    end_attribute_uri: str,
) -> tuple[ConfigurationPeriod | None, str | None]:
    return parse_configuration_period(
        get_scoped_project_value(instance, start_attribute_uri),
        get_scoped_project_value(instance, end_attribute_uri),
    )


def _element_contains_attribute(element, attribute_uri: str) -> bool:
    attribute = getattr(element, "attribute", None)
    if getattr(attribute, "uri", None) == attribute_uri:
        return True
    return any(_element_contains_attribute(child, attribute_uri) for child in getattr(element, "elements", []))


def parse_configuration_period(
    start_value: str | None,
    end_value: str | None,
) -> tuple[ConfigurationPeriod | None, str | None]:
    start_text = start_value.strip() if isinstance(start_value, str) else ""
    end_text = end_value.strip() if isinstance(end_value, str) else ""

    if not start_text:
        return None, "Enter a configuration or mission start date before applying the date range."

    start = _parse_timepoint(start_text)
    if start is None:
        return None, "The configuration or mission start date is invalid. Use YYYY-MM-DD hh:mm."

    end = _parse_timepoint(end_text) if end_text else None
    if end_text and end is None:
        return None, "The configuration or mission end date is invalid. Use YYYY-MM-DD hh:mm."
    if end is not None and start > end:
        return None, "The configuration or mission end date must not be earlier than its start date."

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


def _format_timepoint(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M")
