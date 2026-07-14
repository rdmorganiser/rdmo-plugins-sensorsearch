import logging
from dataclasses import dataclass

from django.db import transaction

from rdmo.projects.models import Value

from rdmo_sensorsearch.config import load_config
from rdmo_sensorsearch.signals.device_set_sync import (
    DEVICE_COLLECTION_ATTRIBUTE_URI,
    refresh_device_detail_blocks,
)
from rdmo_sensorsearch.signals.utils import mute_value_post_save

logger = logging.getLogger(__name__)

DEFAULT_REFRESH_TRIGGER_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-devices"


@dataclass(frozen=True)
class DeviceRefreshConfig:
    trigger_attribute_uri: str
    source_attribute_uri: str = DEVICE_COLLECTION_ATTRIBUTE_URI
    clear_trigger_value: bool = False


def get_device_refresh_config(catalog_uri: str, attribute_uri: str) -> DeviceRefreshConfig | None:
    configuration = load_config()
    catalogs = configuration.get("ProjectDeviceRefreshProvider", {}).get("catalogs", [])

    for catalog in catalogs:
        if catalog.get("catalog_uri") != catalog_uri:
            continue

        trigger_attribute_uri = catalog.get("trigger_attribute_uri", DEFAULT_REFRESH_TRIGGER_ATTRIBUTE_URI)
        if trigger_attribute_uri != attribute_uri:
            continue

        return DeviceRefreshConfig(
            trigger_attribute_uri=trigger_attribute_uri,
            source_attribute_uri=catalog.get("source_attribute_uri", DEVICE_COLLECTION_ATTRIBUTE_URI),
            clear_trigger_value=catalog.get("clear_trigger_value", False),
        )

    return None


def handle_device_refresh_value(instance: Value, auth_token: str | None = None) -> None:
    if instance.project is None or instance.project.catalog is None or instance.attribute is None:
        return

    refresh_config = get_device_refresh_config(instance.project.catalog.uri, instance.attribute.uri)
    if refresh_config is None:
        return

    if not instance.external_id:
        logger.debug("Skipping device refresh trigger without external_id for value %s", instance.pk)
        return

    refreshed_count = refresh_device_detail_blocks(
        project=instance.project,
        catalog=instance.project.catalog,
        block_external_ids=[instance.external_id],
        device_collection_attribute_uri=refresh_config.source_attribute_uri,
        auth_token=auth_token,
    )
    logger.info(
        "Device refresh trigger %s refreshed %s device detail block(s)",
        instance.pk,
        refreshed_count,
    )

    if refresh_config.clear_trigger_value:
        _clear_trigger_value(instance)


def _clear_trigger_value(instance: Value) -> None:
    with transaction.atomic(), mute_value_post_save():
        Value.objects.filter(pk=instance.pk).delete()
