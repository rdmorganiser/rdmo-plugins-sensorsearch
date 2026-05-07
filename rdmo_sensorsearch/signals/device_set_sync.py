import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Iterable

from django.db import transaction

from rdmo.projects.models import Value

from rdmo_sensorsearch.handlers.handler_sms import SensorManagementSystemHandler
from rdmo_sensorsearch.signals.utils import mute_value_post_save
from rdmo_sensorsearch.signals.value_updater import update_values_from_mapped_data

logger = logging.getLogger(__name__)


DEVICE_DETAILS_PAGE_URI = "https://rdmo.nfdi4earth.de/terms/questions/instruments_general"


@dataclass(frozen=True)
class SelectedDevice:
    text: str
    external_id: str


def sync_device_detail_blocks_from_values(
    instance,
    selected_values: Iterable[Value],
    selected_devices_attribute_uri: str,
    device_collection_attribute_uri: str,
) -> None:
    scope_prefix = instance.set_prefix or ""
    selected_devices = [
        SelectedDevice(text=value.text or "", external_id=value.external_id)
        for value in selected_values
        if value.external_id
    ]
    sync_device_detail_blocks(
        project=instance.project,
        catalog=instance.project.catalog,
        scope_prefix=scope_prefix,
        selected_devices=selected_devices,
        selected_devices_attribute_uri=selected_devices_attribute_uri,
        device_collection_attribute_uri=device_collection_attribute_uri,
    )


def sync_device_detail_blocks_from_payload(
    project,
    catalog,
    scope_prefix: str,
    selected_devices: Iterable[SelectedDevice],
    selected_devices_attribute_uri: str,
    device_collection_attribute_uri: str,
) -> None:
    scope_prefix = scope_prefix or ""
    sync_device_detail_blocks(
        project=project,
        catalog=catalog,
        scope_prefix=scope_prefix,
        selected_devices=selected_devices,
        selected_devices_attribute_uri=selected_devices_attribute_uri,
        device_collection_attribute_uri=device_collection_attribute_uri,
    )


def sync_device_detail_blocks(
    project,
    catalog,
    scope_prefix: str,
    selected_devices: Iterable[SelectedDevice],
    selected_devices_attribute_uri: str,
    device_collection_attribute_uri: str,
) -> None:
    scope_prefix = scope_prefix or ""
    selected_devices = _unique_selected_devices(selected_devices)
    desired_external_ids = {device.external_id for device in selected_devices}

    root_attribute_ids = _device_detail_attribute_ids(catalog)
    if not root_attribute_ids:
        logger.warning("Could not resolve device detail attributes for %s", DEVICE_DETAILS_PAGE_URI)
        return

    root_attribute = _get_attribute_by_uri(device_collection_attribute_uri)
    if root_attribute is None:
        logger.warning("Device collection root attribute not found: %s", device_collection_attribute_uri)
        return

    existing_blocks = _existing_device_blocks(project, root_attribute, scope_prefix)
    next_index = _next_device_set_index(existing_blocks.values())

    with transaction.atomic(), mute_value_post_save():
        for external_id, block in list(existing_blocks.items()):
            if external_id in desired_external_ids:
                continue
            _delete_device_block(project, scope_prefix, block["set_index"], root_attribute_ids)

        existing_blocks = {
            external_id: block
            for external_id, block in existing_blocks.items()
            if external_id in desired_external_ids
        }

        for device in selected_devices:
            block = existing_blocks.get(device.external_id)
            if block is not None:
                continue

            sensor_candidate = _resolve_sensor_candidate(project.catalog.uri, device.external_id)
            if sensor_candidate is None:
                logger.warning("No sensor handler found for selected device %s", device.external_id)
                continue
            sensor_handler = sensor_candidate.handler

            set_index = next_index
            next_index += 1

            _upsert_root_device_value(
                project=project,
                attribute=root_attribute,
                scope_prefix=scope_prefix,
                set_index=set_index,
                device=device,
            )

            search_attribute_uri = sensor_candidate.auto_complete_field_uri
            _upsert_search_value(
                project=project,
                attribute_uri=search_attribute_uri,
                scope_prefix=scope_prefix,
                set_index=set_index,
                device=device,
            )

            device_id = _parse_external_id(device.external_id)[1]
            if device_id is None:
                logger.warning("Could not parse external ID %s", device.external_id)
                continue

            block_instance = SimpleNamespace(
                project=project,
                set_prefix=scope_prefix,
                set_index=set_index,
                attribute_id=root_attribute.id,
            )
            mapped_data = sensor_handler.handle(id_=device_id, instance=block_instance)
            if isinstance(mapped_data, dict) and "errors" in mapped_data:
                logger.error("Sensor handler returned errors for %s: %s", device.external_id, mapped_data["errors"])
                continue

            if isinstance(mapped_data, dict):
                update_values_from_mapped_data(block_instance, mapped_data)


def _resolve_sensor_candidate(catalog_uri: str, external_id: str) -> Any | None:
    id_prefix, _ = _parse_external_id(external_id)
    if id_prefix is None:
        return None

    from rdmo_sensorsearch.signals.handler_post_save import _get_handler_candidates

    for candidate in _get_handler_candidates(catalog_uri):
        if isinstance(candidate.handler, SensorManagementSystemHandler) and candidate.id_prefix == id_prefix:
            return candidate
    return None


def _existing_device_blocks(project, root_attribute, scope_prefix: str) -> dict[str, dict]:
    blocks: dict[str, dict] = {}
    queryset = (
        Value.objects.filter(
            project=project,
            attribute=root_attribute,
            set_collection=True,
            set_prefix=scope_prefix,
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id__exact="")
        .order_by("set_index", "id")
    )

    for value in queryset:
        blocks[value.external_id] = {
            "set_index": value.set_index,
            "value_id": value.id,
        }

    return blocks


def _next_device_set_index(existing_blocks: Iterable[dict]) -> int:
    existing_indexes = [block["set_index"] for block in existing_blocks]
    if not existing_indexes:
        return 0
    return max(existing_indexes) + 1


def _delete_device_block(project, scope_prefix: str, set_index: int, attribute_ids: set[int]) -> None:
    deleted, _ = Value.objects.filter(
        project=project,
        attribute_id__in=attribute_ids,
        set_prefix=scope_prefix,
        set_index=set_index,
    ).delete()
    if deleted:
        logger.info(
            "Deleted device detail block at set_prefix=%s set_index=%s (%s rows)",
            scope_prefix,
            set_index,
            deleted,
        )


def _upsert_root_device_value(project, attribute, scope_prefix: str, set_index: int, device: SelectedDevice) -> None:
    _, created = Value.objects.update_or_create(
        project=project,
        attribute=attribute,
        set_collection=True,
        set_prefix=scope_prefix,
        set_index=set_index,
        defaults={
            "text": device.text,
            "external_id": device.external_id,
        },
    )
    logger.info(
        "%s device block root for %s at set_prefix=%s set_index=%s",
        "Created" if created else "Updated",
        device.external_id,
        scope_prefix,
        set_index,
    )


def _upsert_search_value(project, attribute_uri: str, scope_prefix: str, set_index: int, device: SelectedDevice) -> None:
    attribute = _get_attribute_by_uri(attribute_uri)
    if attribute is None:
        logger.warning("Search attribute not found: %s", attribute_uri)
        return

    _, created = Value.objects.update_or_create(
        project=project,
        attribute=attribute,
        set_collection=False,
        set_prefix=scope_prefix,
        set_index=set_index,
        defaults={
            "text": device.text,
            "external_id": device.external_id,
        },
    )
    logger.info(
        "%s device search value for %s at set_prefix=%s set_index=%s",
        "Created" if created else "Updated",
        device.external_id,
        scope_prefix,
        set_index,
    )


def _device_detail_attribute_ids(catalog) -> set[int]:
    catalog.prefetch_elements()
    for page in catalog.pages:
        if page.uri == DEVICE_DETAILS_PAGE_URI:
            return _collect_attribute_ids(page)
    return set()


def _collect_attribute_ids(element) -> set[int]:
    attribute_ids: set[int] = set()
    attribute_id = getattr(element, "attribute_id", None)
    if attribute_id:
        attribute_ids.add(attribute_id)

    for child in getattr(element, "elements", []):
        attribute_ids.update(_collect_attribute_ids(child))

    return attribute_ids


def _get_attribute_by_uri(attribute_uri: str):
    from rdmo.domain.models import Attribute

    try:
        return Attribute.objects.get(uri=attribute_uri)
    except Attribute.DoesNotExist:
        return None


def _parse_external_id(external_id: str) -> tuple[str | None, str | None]:
    if ":" not in external_id:
        return None, external_id or None
    prefix, value = external_id.split(":", 1)
    return prefix or None, value or None


def _unique_selected_devices(selected_devices: Iterable[SelectedDevice]) -> list[SelectedDevice]:
    unique: list[SelectedDevice] = []
    seen: set[str] = set()
    for device in selected_devices:
        if not device.external_id or device.external_id in seen:
            continue
        seen.add(device.external_id)
        unique.append(device)
    return unique
