import logging
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace
from typing import Any, Iterable

from django.db import transaction
from django.db.models import Q

from rdmo.projects.models import Value

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.handlers.handler_sms import SensorManagementSystemHandler
from rdmo_sensorsearch.signals.utils import mute_value_post_save
from rdmo_sensorsearch.signals.value_updater import (
    replace_scalar_value_in_scopes,
    update_values_from_mapped_data,
)

logger = logging.getLogger(__name__)


DEVICE_DETAILS_PAGE_URI = "https://rdmo.nfdi4earth.de/terms/questions/instruments_general"
DEVICE_OPTIONAL_INFO_PAGE_URI = "https://rdmo.nfdi4earth.de/terms/questions/instruments/further-info"
CONFIGURATION_SET_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set"
DEVICE_COLLECTION_ATTRIBUTE_URI = "https://rdmo-sandbox.gfz-potsdam.de/terms/domain/moses/instruments/id"
DEVICE_LINK_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/device-link"
INSTRUMENT_START_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/instrument-start-datetime"
INSTRUMENT_END_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/instrument-end-datetime"
SERIAL_NUMBER_ATTRIBUTE_URI = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/serial_number"


@dataclass(frozen=True)
class SelectedDevice:
    text: str
    external_id: str


@dataclass(frozen=True)
class ConfigurationContext:
    key: str
    label: str
    external_id: str | None


def sync_device_detail_blocks_from_values(
    instance,
    selected_values: Iterable[Value],
    selected_devices_attribute_uri: str,
    device_collection_attribute_uri: str,
    configuration_search_attribute_uri: str,
) -> None:
    scope_prefix = instance.set_prefix or ""
    source_set_index = instance.set_index
    selected_devices = [
        SelectedDevice(text=value.text or "", external_id=value.external_id)
        for value in selected_values
        if value.external_id
    ]
    sync_device_detail_blocks(
        project=instance.project,
        catalog=instance.project.catalog,
        scope_prefix=scope_prefix,
        source_set_index=source_set_index,
        selected_devices=selected_devices,
        selected_devices_attribute_uri=selected_devices_attribute_uri,
        device_collection_attribute_uri=device_collection_attribute_uri,
        configuration_search_attribute_uri=configuration_search_attribute_uri,
        configuration_external_id=_resolve_configuration_external_id_from_values(
            project=instance.project,
            scope_prefix=scope_prefix,
            source_set_index=source_set_index,
            configuration_search_attribute_uri=configuration_search_attribute_uri,
        ),
    )


def sync_device_detail_blocks_from_payload(
    project,
    catalog,
    scope_prefix: str,
    source_set_index: int,
    selected_devices: Iterable[SelectedDevice],
    selected_devices_attribute_uri: str,
    device_collection_attribute_uri: str,
    configuration_search_attribute_uri: str,
    configuration_external_id: str | None = None,
) -> None:
    scope_prefix = scope_prefix or ""
    sync_device_detail_blocks(
        project=project,
        catalog=catalog,
        scope_prefix=scope_prefix,
        source_set_index=source_set_index,
        selected_devices=selected_devices,
        selected_devices_attribute_uri=selected_devices_attribute_uri,
        device_collection_attribute_uri=device_collection_attribute_uri,
        configuration_search_attribute_uri=configuration_search_attribute_uri,
        configuration_external_id=configuration_external_id,
    )


def sync_device_detail_blocks(
    project,
    catalog,
    scope_prefix: str,
    source_set_index: int,
    selected_devices: Iterable[SelectedDevice],
    selected_devices_attribute_uri: str,
    device_collection_attribute_uri: str,
    configuration_search_attribute_uri: str,
    configuration_external_id: str | None = None,
) -> None:
    scope_prefix = scope_prefix or ""
    source_set_index = source_set_index or 0
    selected_devices = _unique_selected_devices(selected_devices)
    config_context = _resolve_configuration_context(
        project=project,
        scope_prefix=scope_prefix,
        source_set_index=source_set_index,
        configuration_search_attribute_uri=configuration_search_attribute_uri,
        configuration_external_id=configuration_external_id,
    )
    if config_context is None:
        logger.warning(
            "Could not resolve configuration context for selected devices attribute %s",
            selected_devices_attribute_uri,
        )
        return

    config_key = config_context.key
    config_label = config_context.label
    desired_block_keys = {
        _compose_device_block_key(config_key, device.external_id)
        for device in selected_devices
    }
    root_attribute_ids = _device_detail_attribute_ids(catalog)
    if not root_attribute_ids:
        logger.warning("Could not resolve device detail attributes for %s", DEVICE_DETAILS_PAGE_URI)
        return

    root_attribute = _get_attribute_by_uri(device_collection_attribute_uri)
    if root_attribute is None:
        logger.warning("Device collection root attribute not found: %s", device_collection_attribute_uri)
        return

    existing_blocks = _existing_device_blocks(project, root_attribute, scope_prefix, config_key)
    next_index = _next_device_set_index(project, root_attribute, scope_prefix)

    with transaction.atomic(), mute_value_post_save():
        for block_key, block in list(existing_blocks.items()):
            if block_key in desired_block_keys:
                continue
            _delete_device_block(project, scope_prefix, block["set_index"], root_attribute_ids)

        existing_blocks = {
            block_key: block
            for block_key, block in existing_blocks.items()
            if block_key in desired_block_keys
        }

        for device in selected_devices:
            block_key = _compose_device_block_key(config_key, device.external_id)
            block = existing_blocks.get(block_key)
            sensor_candidate = _resolve_sensor_candidate(project.catalog.uri, device.external_id)
            if sensor_candidate is None:
                logger.warning("No sensor handler found for selected device %s", device.external_id)
                continue
            sensor_handler = sensor_candidate.handler

            if block is not None:
                set_index = block["set_index"]
            else:
                set_index = next_index
                next_index += 1

            block_instance = SimpleNamespace(
                project=project,
                set_prefix=scope_prefix,
                set_index=set_index,
                attribute_id=root_attribute.id,
            )

            _upsert_root_device_value(
                project=project,
                attribute=root_attribute,
                scope_prefix=scope_prefix,
                set_index=set_index,
                device=device,
                config_label=config_label,
                block_key=block_key,
            )

            search_attribute_uri = sensor_candidate.auto_complete_field_uri
            _upsert_search_value(
                project=project,
                attribute_uri=search_attribute_uri,
                scope_prefix=scope_prefix,
                set_index=set_index,
                device=device,
            )

            if block is not None and not _device_block_needs_refresh(project, scope_prefix, set_index):
                continue

            device_id = _parse_external_id(device.external_id)[1]
            if device_id is None:
                logger.warning("Could not parse external ID %s", device.external_id)
                continue

            mapped_data = sensor_handler.handle(id_=device_id, instance=block_instance)
            if isinstance(mapped_data, dict) and "errors" in mapped_data:
                logger.error("Sensor handler returned errors for %s: %s", device.external_id, mapped_data["errors"])
                continue

            if isinstance(mapped_data, dict):
                _merge_mounting_period_values(
                    mapped_data,
                    device,
                    sensor_candidate,
                    config_context.external_id,
                )
                scoped_scalar_values = {
                    INSTRUMENT_START_ATTRIBUTE_URI: mapped_data.pop(INSTRUMENT_START_ATTRIBUTE_URI, ""),
                    INSTRUMENT_END_ATTRIBUTE_URI: mapped_data.pop(INSTRUMENT_END_ATTRIBUTE_URI, ""),
                }
                update_values_from_mapped_data(block_instance, mapped_data)
                for attribute_uri, value in scoped_scalar_values.items():
                    replace_scalar_value_in_scopes(
                        block_instance,
                        attribute_uri,
                        value,
                        scopes_to_set=[_device_nested_questionset_scope(set_index)],
                        scopes_to_clear=[("", set_index)],
                    )

        _compact_device_detail_blocks(project, catalog, scope_prefix)


def _resolve_sensor_candidate(catalog_uri: str, external_id: str) -> Any | None:
    id_prefix, _ = _parse_external_id(external_id)
    if id_prefix is None:
        return None

    from rdmo_sensorsearch.signals.handler_post_save import _get_handler_candidates

    for candidate in _get_handler_candidates(catalog_uri):
        if isinstance(candidate.handler, SensorManagementSystemHandler) and candidate.id_prefix == id_prefix:
            return candidate
    return None


def _resolve_configuration_candidate(catalog_uri: str, external_id: str) -> Any | None:
    id_prefix, _ = _parse_external_id(external_id)
    if id_prefix is None:
        return None

    from rdmo_sensorsearch.handlers.handler_sms_configurations import (
        SensorManagementSystemConfigurationsHandler,
    )
    from rdmo_sensorsearch.signals.handler_post_save import _get_handler_candidates

    for candidate in _get_handler_candidates(catalog_uri):
        if isinstance(candidate.handler, SensorManagementSystemConfigurationsHandler) and candidate.id_prefix == id_prefix:
            return candidate
    return None


def _resolve_configuration_context(
    project,
    scope_prefix: str,
    source_set_index: int,
    configuration_search_attribute_uri: str,
    configuration_external_id: str | None = None,
) -> ConfigurationContext | None:
    if not configuration_search_attribute_uri:
        return None

    config_search_value = (
        Value.objects.filter(
            project=project,
            attribute__uri=configuration_search_attribute_uri,
            set_prefix=scope_prefix,
            set_index=source_set_index,
        )
        .exclude(text__isnull=True)
        .exclude(text__exact="")
        .order_by("-id")
        .first()
    )
    configuration_set_value = (
        Value.objects.filter(
            project=project,
            attribute__uri=CONFIGURATION_SET_ATTRIBUTE_URI,
            set_collection=True,
            set_prefix=scope_prefix,
            set_index=source_set_index,
        )
        .exclude(text__isnull=True)
        .exclude(text__exact="")
        .order_by("id")
        .first()
    )
    if config_search_value is None and configuration_set_value is None:
        return None

    config_key = _configuration_key(config_search_value, configuration_set_value, scope_prefix, source_set_index)
    return ConfigurationContext(
        key=config_key,
        label=_configuration_label(config_search_value, configuration_set_value, source_set_index),
        external_id=configuration_external_id or _configuration_external_id(config_search_value),
    )


def _existing_device_blocks(project, root_attribute, scope_prefix: str, config_key: str) -> dict[str, dict]:
    all_blocks = _all_existing_device_blocks(project, root_attribute, scope_prefix)
    return {
        block_key: block
        for block_key, block in all_blocks.items()
        if _parse_block_external_id(block_key)[0] == config_key
    }


def _all_existing_device_blocks(project, root_attribute, scope_prefix: str) -> dict[str, dict]:
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
        block_key = value.external_id or ""
        parsed_config_key, device_external_id = _parse_block_external_id(block_key)
        if not parsed_config_key or not device_external_id:
            continue
        blocks[block_key] = {
            "set_index": value.set_index,
            "value_id": value.id,
        }

    return blocks


def _next_device_set_index(project, root_attribute, scope_prefix: str) -> int:
    existing_indexes = list(
        Value.objects.filter(
            project=project,
            attribute=root_attribute,
            set_collection=True,
            set_prefix=scope_prefix,
        ).values_list("set_index", flat=True)
    )
    if not existing_indexes:
        return 0
    return max(existing_indexes) + 1


def _delete_device_block(project, scope_prefix: str, set_index: int, attribute_ids: set[int]) -> None:
    deleted, _ = Value.objects.filter(
        project=project,
        attribute_id__in=attribute_ids,
    ).filter(
        Q(set_prefix=scope_prefix, set_index=set_index) |
        Q(set_prefix=str(set_index))
    ).delete()
    if deleted:
        logger.info(
            "Deleted device detail block at set_prefix=%s set_index=%s (%s rows)",
            scope_prefix,
            set_index,
            deleted,
        )


def _upsert_root_device_value(
    project,
    attribute,
    scope_prefix: str,
    set_index: int,
    device: SelectedDevice,
    config_label: str,
    block_key: str,
) -> None:
    _, created = Value.objects.update_or_create(
        project=project,
        attribute=attribute,
        set_collection=True,
        set_prefix=scope_prefix,
        set_index=set_index,
        defaults={
            "text": device.text or f"{config_label}: {_base_device_text(device.text)}",
            "external_id": block_key,
        },
    )
    logger.info(
        "%s device block root for %s at set_prefix=%s set_index=%s",
        "Created" if created else "Updated",
        block_key,
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
            "text": _base_device_text(device.text),
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


def _device_detail_related_attribute_ids(catalog) -> set[int]:
    catalog.prefetch_elements()
    attribute_ids: set[int] = set()
    for page in catalog.pages:
        if page.uri in {DEVICE_DETAILS_PAGE_URI, DEVICE_OPTIONAL_INFO_PAGE_URI}:
            attribute_ids.update(_collect_attribute_ids(page))
    return attribute_ids


def _compact_device_detail_blocks(project, catalog, scope_prefix: str) -> None:
    root_attribute = _get_attribute_by_uri(DEVICE_COLLECTION_ATTRIBUTE_URI)
    if root_attribute is None:
        return

    root_values = list(
        Value.objects.filter(
            project=project,
            attribute=root_attribute,
            set_collection=True,
            set_prefix=scope_prefix,
        ).order_by("set_index", "id")
    )
    current_indices = [value.set_index for value in root_values]
    target_indices = list(range(len(root_values)))
    if current_indices == target_indices:
        return

    remap = {old: new for new, old in enumerate(current_indices)}
    temp_offset = max(current_indices, default=-1) + 1000
    attribute_ids = _device_detail_related_attribute_ids(catalog)
    if not attribute_ids:
        return

    for old_index in current_indices:
        temp_index = old_index + temp_offset
        Value.objects.filter(
            project=project,
            attribute_id__in=attribute_ids,
            set_prefix=scope_prefix,
            set_index=old_index,
        ).update(set_index=temp_index)
        Value.objects.filter(
            project=project,
            attribute_id__in=attribute_ids,
            set_prefix=str(old_index),
        ).update(set_prefix=str(temp_index))

    for old_index, new_index in remap.items():
        temp_index = old_index + temp_offset
        Value.objects.filter(
            project=project,
            attribute_id__in=attribute_ids,
            set_prefix=scope_prefix,
            set_index=temp_index,
        ).update(set_index=new_index)
        Value.objects.filter(
            project=project,
            attribute_id__in=attribute_ids,
            set_prefix=str(temp_index),
        ).update(set_prefix=str(new_index))


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


def _device_block_needs_refresh(project, scope_prefix: str, set_index: int) -> bool:
    return not (
        _has_nonempty_scalar_value(project, DEVICE_LINK_ATTRIBUTE_URI, scope_prefix, set_index)
        and _has_nonempty_scalar_value(project, INSTRUMENT_START_ATTRIBUTE_URI, scope_prefix, set_index)
    )


def _has_nonempty_scalar_value(project, attribute_uri: str, scope_prefix: str, set_index: int) -> bool:
    return Value.objects.filter(
        project=project,
        attribute__uri=attribute_uri,
        set_prefix=scope_prefix,
        set_index=set_index,
        set_collection=False,
    ).exclude(text__isnull=True).exclude(text__exact="").exists()


def _device_nested_questionset_scope(parent_set_index: int) -> tuple[str, int]:
    return str(parent_set_index), 0


def _parse_external_id(external_id: str) -> tuple[str | None, str | None]:
    if ":" not in external_id:
        return None, external_id or None
    prefix, value = external_id.split(":", 1)
    return prefix or None, value or None


def _parse_block_external_id(external_id: str) -> tuple[str | None, str | None]:
    if "||" not in external_id:
        return None, None
    config_key, device_external_id = external_id.split("||", 1)
    return config_key or None, device_external_id or None


def _compose_device_block_key(config_key: str, device_external_id: str) -> str:
    return f"{config_key}||{device_external_id}"


def _base_device_text(text: str) -> str:
    if ": " in text:
        return text.split(": ", 1)[1]
    return text


def _configuration_key(
    config_search_value: Value | None,
    configuration_set_value: Value | None,
    scope_prefix: str,
    source_set_index: int,
) -> str:
    if config_search_value is not None:
        return config_search_value.external_id or config_search_value.text or f"{scope_prefix}:{source_set_index}"
    if configuration_set_value is not None and configuration_set_value.text:
        return configuration_set_value.text
    return f"{scope_prefix}:{source_set_index}"


def _configuration_external_id(config_search_value: Value | None) -> str | None:
    if config_search_value is None:
        return None
    if config_search_value.external_id:
        return config_search_value.external_id
    if isinstance(config_search_value.text, str) and ":" in config_search_value.text:
        return config_search_value.text
    return None


def _resolve_configuration_external_id_from_values(
    project,
    scope_prefix: str,
    source_set_index: int,
    configuration_search_attribute_uri: str,
) -> str | None:
    if not configuration_search_attribute_uri:
        return None

    value = (
        Value.objects.filter(
            project=project,
            attribute__uri=configuration_search_attribute_uri,
            set_prefix=scope_prefix,
            set_index=source_set_index,
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id__exact="")
        .order_by("-id")
        .first()
    )
    return value.external_id if value is not None else None


def _configuration_label(
    config_search_value: Value | None,
    configuration_set_value: Value | None,
    source_set_index: int,
) -> str:
    if configuration_set_value is not None and configuration_set_value.text:
        return configuration_set_value.text.strip()

    raw_label = None
    if config_search_value is not None:
        raw_label = config_search_value.external_id or config_search_value.text

    if isinstance(raw_label, str) and ":" in raw_label:
        return raw_label.split(":", 1)[1].strip() or str(source_set_index)
    if isinstance(raw_label, str) and raw_label.strip():
        return raw_label.strip()
    return str(source_set_index)


def _merge_mounting_period_values(
    mapped_data: dict[str, Any],
    device: SelectedDevice,
    sensor_candidate: Any,
    configuration_external_id: str | None,
) -> None:
    start_value, end_value = _resolve_mounting_period_values(
        mapped_data,
        device,
        sensor_candidate,
        configuration_external_id,
    )
    mapped_data[INSTRUMENT_START_ATTRIBUTE_URI] = start_value or ""
    mapped_data[INSTRUMENT_END_ATTRIBUTE_URI] = end_value or ""


def _resolve_mounting_period_values(
    mapped_data: dict[str, Any],
    device: SelectedDevice,
    sensor_candidate: Any,
    configuration_external_id: str | None,
) -> tuple[str | None, str | None]:
    if not configuration_external_id:
        return None, None

    _, configuration_id = _parse_external_id(configuration_external_id)
    device_id = _parse_external_id(device.external_id)[1]
    if configuration_id is None or device_id is None:
        return None, None

    mount_actions = _fetch_device_mount_actions(sensor_candidate, device_id)
    if not mount_actions:
        return None, None

    serial_number = mapped_data.get(SERIAL_NUMBER_ATTRIBUTE_URI)
    if not isinstance(serial_number, str) or not serial_number.strip():
        serial_number = _serial_number_from_text(device.text)

    matching_actions = []
    normalized_serial = serial_number.strip().casefold() if isinstance(serial_number, str) and serial_number.strip() else None
    for item in mount_actions:
        relationships = item.get("relationships", {})
        config_ref = relationships.get("configuration", {}).get("data", {})
        if config_ref.get("id") != configuration_id:
            continue

        action_device_ref = relationships.get("device", {}).get("data", {})
        if action_device_ref.get("id") != device_id:
            continue

        attrs = item.get("attributes", {})
        action_serial = attrs.get("serial_number")
        if normalized_serial and isinstance(action_serial, str):
            if action_serial.strip().casefold() != normalized_serial:
                continue

        begin_date = _parse_timepoint(attrs.get("begin_date"))
        if begin_date is None:
            continue
        end_date = _parse_timepoint(attrs.get("end_date"))
        matching_actions.append((begin_date, end_date))

    if not matching_actions:
        return None, None

    latest_start, latest_end = max(matching_actions, key=lambda item: item[0])
    return _format_timepoint(latest_start), _format_timepoint(latest_end)


def _fetch_device_mount_actions(sensor_candidate: Any, device_id: str) -> list[dict]:
    url = (
        f"{sensor_candidate.handler.base_url}/devices/{device_id}/device-mount-actions"
        "?page[size]=10000&include=begin_contact,end_contact,parent_platform,parent_device,configuration"
    )
    action_data = fetch_json(url)
    if isinstance(action_data, dict) and "errors" in action_data:
        logger.warning(
            "Could not fetch device mount actions for %s: %s",
            device_id,
            action_data["errors"],
        )
        return []
    if not isinstance(action_data, dict):
        return []
    data = action_data.get("data", [])
    return data if isinstance(data, list) else []


def _parse_timepoint(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_timepoint(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_timezone.utc)
    return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M")


def _serial_number_from_text(text: str) -> str | None:
    marker = "(s/n:"
    if marker not in text:
        return None
    serial_fragment = text.split(marker, 1)[1]
    return serial_fragment.split(")", 1)[0].strip() or None


def _unique_selected_devices(selected_devices: Iterable[SelectedDevice]) -> list[SelectedDevice]:
    unique: list[SelectedDevice] = []
    seen: set[str] = set()
    for device in selected_devices:
        if not device.external_id or device.external_id in seen:
            continue
        seen.add(device.external_id)
        unique.append(device)
    return unique
