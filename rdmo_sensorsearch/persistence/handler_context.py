"""Read interview state before invoking backend record handlers."""

from rdmo.projects.models import Value

from rdmo_sensorsearch.contracts import ConfigurationPeriod
from rdmo_sensorsearch.services.configuration_period import parse_configuration_period
from rdmo_sensorsearch.services.device_details import parse_device_block_key

DEFAULT_DEVICE_COLLECTION_ATTRIBUTE_URI = "https://rdmo-sandbox.gfz-potsdam.de/terms/domain/moses/instruments/id"


def _get_scoped_project_value(instance, attribute_uri: str) -> str | None:
    """Return a scalar answer from exactly the same interview collection row."""
    value = (
        Value.objects.filter(
            project=instance.project,
            snapshot=None,
            attribute__uri=attribute_uri,
            set_prefix=instance.set_prefix or "",
            set_index=instance.set_index,
            set_collection=False,
        )
        .order_by("-id")
        .first()
    )
    if value is None:
        return None
    return value.text or value.value or None


def device_configuration_reference(
    instance, device_collection_attribute_uri: str = DEFAULT_DEVICE_COLLECTION_ATTRIBUTE_URI
) -> str | None:
    root_value = (
        Value.objects.filter(
            project=instance.project,
            snapshot=None,
            attribute__uri=device_collection_attribute_uri,
            set_prefix=instance.set_prefix or "",
            set_index=instance.set_index,
            set_collection=True,
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id__exact="")
        .order_by("-id")
        .first()
    )
    if root_value is None or not isinstance(root_value.external_id, str):
        return None
    configuration, _device = parse_device_block_key(root_value.external_id)
    return configuration or None


def read_configuration_period(
    instance, start_attribute_uri: str, end_attribute_uri: str
) -> tuple[ConfigurationPeriod | None, str | None]:
    return parse_configuration_period(
        _get_scoped_project_value(instance, start_attribute_uri),
        _get_scoped_project_value(instance, end_attribute_uri),
    )
