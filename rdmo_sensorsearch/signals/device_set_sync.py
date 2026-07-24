import logging
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone as dt_timezone
from typing import Any

from django.db import transaction
from django.db.models import Q

from rdmo.projects.models import Value

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.signals.collection_binding import CollectionBinding, CollectionScope
from rdmo_sensorsearch.signals.refresh_types import RefreshError, RefreshResult
from rdmo_sensorsearch.signals.utils import mute_value_post_save
from rdmo_sensorsearch.signals.value_updater import (
    _change_label,
    replace_scalar_value_in_scopes,
    update_values_from_mapped_data,
    upsert_value_if_changed,
)

logger = logging.getLogger(__name__)


DEVICE_DETAILS_PAGE_URI = "https://rdmo.nfdi4earth.de/terms/questions/instruments_general"
DEVICE_OPTIONAL_INFO_PAGE_URI = "https://rdmo.nfdi4earth.de/terms/questions/instruments/further-info"
CONFIGURATION_SET_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set"
CONFIGURATION_SEARCH_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-search"
SELECTED_DEVICES_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/selected-devices"
DEVICE_COLLECTION_ATTRIBUTE_URI = "https://rdmo-sandbox.gfz-potsdam.de/terms/domain/moses/instruments/id"
DEVICE_LINK_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/device-link"
USAGE_TECHNOLOGY_ATTRIBUTE_URI = "https://rdmorganiser.github.io/terms/domain/project/dataset/usage_technology"
INSTRUMENT_START_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/instrument-start-datetime"
INSTRUMENT_END_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/instrument-end-datetime"
SERIAL_NUMBER_ATTRIBUTE_URI = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/serial_number"
DEVICE_DETAIL_FETCH_WORKERS = 4


@dataclass(frozen=True)
class SelectedDevice:
    text: str
    external_id: str
    instrument_start: str | None = None
    instrument_end: str | None = None


@dataclass(frozen=True)
class ConfigurationContext:
    key: str
    label: str
    external_id: str | None


@dataclass(frozen=True)
class DeviceBlockPlan:
    device: SelectedDevice
    block_key: str
    set_index: int
    sensor_candidate: Any
    needs_metadata_write: bool
    needs_refresh: bool
    set_prefix: str = ""
    configuration_external_id: str | None = None


@dataclass(frozen=True)
class DeviceBlockInstance:
    project: Any
    set_prefix: str
    set_index: int
    attribute_id: int


@dataclass(frozen=True)
class DeviceFetchResult:
    mapped_data: dict[str, Any]
    scoped_scalar_values: dict[str, Any]


@dataclass(frozen=True)
class DeviceFetchFailure:
    message: str


@dataclass(frozen=True)
class DeviceFetchBatchResult:
    payloads: dict[str, DeviceFetchResult]
    errors: tuple[RefreshError, ...] = ()


def sync_device_detail_blocks_from_values(
    instance,
    selected_values: Iterable[Value],
    selected_devices_attribute_uri: str,
    device_collection_attribute_uri: str,
    configuration_search_attribute_uri: str,
    auth_token: str | None = None,
) -> RefreshResult:
    return sync_device_detail_blocks_from_configuration_values(
        project=instance.project,
        catalog=instance.project.catalog,
        scope_prefix=instance.set_prefix or "",
        source_set_index=instance.set_index,
        selected_values=selected_values,
        selected_devices_attribute_uri=selected_devices_attribute_uri,
        device_collection_attribute_uri=device_collection_attribute_uri,
        configuration_search_attribute_uri=configuration_search_attribute_uri,
        auth_token=auth_token,
    )


def sync_device_detail_blocks_from_configuration_values(
    project,
    catalog,
    scope_prefix: str,
    source_set_index: int,
    selected_values: Iterable[Value],
    selected_devices_attribute_uri: str,
    device_collection_attribute_uri: str,
    configuration_search_attribute_uri: str,
    auth_token: str | None = None,
) -> RefreshResult:
    selected_devices = [
        SelectedDevice(text=value.text or "", external_id=value.external_id) for value in selected_values if value.external_id
    ]
    return sync_device_detail_blocks(
        project=project,
        catalog=catalog,
        scope_prefix=scope_prefix,
        source_set_index=source_set_index,
        selected_devices=selected_devices,
        selected_devices_attribute_uri=selected_devices_attribute_uri,
        device_collection_attribute_uri=device_collection_attribute_uri,
        configuration_search_attribute_uri=configuration_search_attribute_uri,
        configuration_external_id=_resolve_configuration_external_id_from_values(
            project=project,
            scope_prefix=scope_prefix,
            source_set_index=source_set_index,
            configuration_search_attribute_uri=configuration_search_attribute_uri,
        ),
        auth_token=auth_token,
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
    auth_token: str | None = None,
    force_refresh: bool = False,
) -> RefreshResult:
    scope_prefix = scope_prefix or ""
    return sync_device_detail_blocks(
        project=project,
        catalog=catalog,
        scope_prefix=scope_prefix,
        source_set_index=source_set_index,
        selected_devices=selected_devices,
        selected_devices_attribute_uri=selected_devices_attribute_uri,
        device_collection_attribute_uri=device_collection_attribute_uri,
        configuration_search_attribute_uri=configuration_search_attribute_uri,
        configuration_external_id=configuration_external_id,
        auth_token=auth_token,
        force_refresh=force_refresh,
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
    auth_token: str | None = None,
    force_refresh: bool = False,
) -> RefreshResult:
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
        return _failed_device_sync(
            configuration_external_id or "",
            "Could not resolve the configuration context for device synchronization.",
            requested_count=len(selected_devices),
        )

    config_key = config_context.key
    config_label = config_context.label
    desired_block_keys = {_compose_device_block_key(config_key, device.external_id) for device in selected_devices}
    device_detail_attribute_ids = _device_detail_attribute_ids(catalog)
    if not device_detail_attribute_ids:
        logger.warning("Could not resolve device detail attributes for %s", DEVICE_DETAILS_PAGE_URI)
        return _failed_device_sync(
            config_key,
            f"Could not resolve device detail attributes for {DEVICE_DETAILS_PAGE_URI}.",
            requested_count=len(selected_devices),
        )
    related_attribute_ids = _device_detail_related_attribute_ids(catalog) or device_detail_attribute_ids

    root_attribute = _get_attribute_by_uri(device_collection_attribute_uri)
    if root_attribute is None:
        logger.warning("Device collection root attribute not found: %s", device_collection_attribute_uri)
        return _failed_device_sync(
            config_key,
            f"Device collection root attribute not found: {device_collection_attribute_uri}.",
            requested_count=len(selected_devices),
        )

    existing_blocks = _existing_device_blocks(project, root_attribute, scope_prefix, config_key)
    next_index = _next_device_set_index(project, root_attribute, scope_prefix)

    stale_blocks = [block for block_key, block in existing_blocks.items() if block_key not in desired_block_keys]
    existing_blocks = {block_key: block for block_key, block in existing_blocks.items() if block_key in desired_block_keys}

    plans: list[DeviceBlockPlan] = []
    planning_errors: list[RefreshError] = []
    for device in selected_devices:
        block_key = _compose_device_block_key(config_key, device.external_id)
        block = existing_blocks.get(block_key)
        sensor_candidate = _resolve_sensor_candidate(project.catalog.uri, device.external_id)
        if sensor_candidate is None:
            logger.warning("No sensor handler found for selected device %s", device.external_id)
            planning_errors.append(
                RefreshError(
                    external_id=device.external_id,
                    message="No matching sensor handler is configured.",
                )
            )
            continue

        if block is not None:
            set_index = block["set_index"]
        else:
            set_index = next_index
            next_index += 1
        search_attribute_uri = sensor_candidate.auto_complete_field_uri
        needs_metadata_write = block is None or not _device_block_metadata_is_current(
            project=project,
            root_attribute=root_attribute,
            search_attribute_uri=search_attribute_uri,
            scope_prefix=scope_prefix,
            set_index=set_index,
            block_key=block_key,
            device=device,
            config_label=config_label,
        )

        plans.append(
            DeviceBlockPlan(
                device=device,
                block_key=block_key,
                set_index=set_index,
                sensor_candidate=sensor_candidate,
                needs_metadata_write=needs_metadata_write,
                needs_refresh=force_refresh
                or block is None
                or _device_block_needs_refresh(
                    project=project,
                    scope_prefix=scope_prefix,
                    set_index=set_index,
                ),
                set_prefix=scope_prefix,
                configuration_external_id=config_context.external_id,
            )
        )

    fetch_batch = _fetch_device_detail_payloads(
        plans,
        root_attribute.id,
        config_context.external_id,
        auth_token=auth_token,
    )
    fetched_payloads = fetch_batch.payloads

    with transaction.atomic(), mute_value_post_save():
        for block in stale_blocks:
            _delete_device_block(project, scope_prefix, block["set_index"], related_attribute_ids)

        for plan in plans:
            block_instance = _device_block_instance(project, root_attribute.id, scope_prefix, plan.set_index)

            if plan.needs_metadata_write:
                _upsert_root_device_value(
                    project=project,
                    attribute=root_attribute,
                    scope_prefix=scope_prefix,
                    set_index=plan.set_index,
                    device=plan.device,
                    config_label=config_label,
                    block_key=plan.block_key,
                )

                search_attribute_uri = plan.sensor_candidate.auto_complete_field_uri
                _upsert_search_value(
                    project=project,
                    attribute_uri=search_attribute_uri,
                    scope_prefix=scope_prefix,
                    set_index=plan.set_index,
                    device=plan.device,
                )

            fetched_payload = fetched_payloads.get(plan.block_key)
            if fetched_payload is None:
                continue

            _write_device_fetch_payload(block_instance, fetched_payload, scope_prefix, plan.set_index)

        if stale_blocks:
            _compact_device_detail_blocks(project, catalog, scope_prefix, device_collection_attribute_uri)

    return RefreshResult(
        requested_count=sum(plan.needs_refresh for plan in plans) + len(planning_errors),
        refreshed_count=len(fetched_payloads),
        errors=tuple(planning_errors) + fetch_batch.errors,
    )


def _failed_device_sync(external_id: str, message: str, requested_count: int) -> RefreshResult:
    return RefreshResult(
        requested_count=requested_count,
        refreshed_count=0,
        errors=(RefreshError(external_id=external_id, message=message),),
    )


def get_configuration_scope_for_value(value: Value, binding: CollectionBinding) -> tuple[str, int]:
    scope = binding.parent_scope_for_value(value)
    return scope.set_prefix, scope.set_index


def get_selected_device_values_for_configuration_scope(
    binding: CollectionBinding,
    scope_prefix: str,
    source_set_index: int,
) -> list[Value]:
    return list(
        binding.values_for_scope(
            CollectionScope(
                set_prefix=scope_prefix,
                set_index=source_set_index,
            )
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id__exact="")
    )


def remove_orphaned_device_detail_blocks(
    project,
    catalog,
    configuration_search_attribute_uris: Iterable[str],
    device_collection_attribute_uri: str,
) -> int:
    root_attribute = _get_attribute_by_uri(device_collection_attribute_uri)
    if root_attribute is None:
        logger.warning("Device collection root attribute not found: %s", device_collection_attribute_uri)
        return 0

    related_attribute_ids = _device_detail_related_attribute_ids(catalog)
    if not related_attribute_ids:
        logger.warning("Could not resolve device detail attributes for %s", DEVICE_DETAILS_PAGE_URI)
        return 0

    active_configuration_keys = {
        value.external_id or value.text
        for value in Value.objects.filter(
            project=project,
            snapshot=None,
            attribute__uri__in=configuration_search_attribute_uris,
        )
        if value.external_id or value.text
    }
    root_values = (
        Value.objects.filter(
            project=project,
            snapshot=None,
            attribute=root_attribute,
            set_collection=True,
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id__exact="")
    )
    orphaned_scopes = set()
    for value in root_values:
        configuration_key = _device_block_configuration_key(value.external_id)
        if configuration_key and configuration_key not in active_configuration_keys:
            orphaned_scopes.add((value.set_prefix or "", value.set_index))
    if not orphaned_scopes:
        return 0

    with transaction.atomic(), mute_value_post_save():
        for scope_prefix, set_index in orphaned_scopes:
            _delete_device_block(project, scope_prefix, set_index, related_attribute_ids)
        for scope_prefix in {scope_prefix for scope_prefix, _ in orphaned_scopes}:
            _compact_device_detail_blocks(
                project,
                catalog,
                scope_prefix,
                device_collection_attribute_uri,
            )

    logger.info(
        "Removed %s orphaned device detail block(s) after configuration cleanup",
        len(orphaned_scopes),
    )
    return len(orphaned_scopes)


def _device_block_instance(project, root_attribute_id: int, set_prefix: str, set_index: int) -> DeviceBlockInstance:
    return DeviceBlockInstance(
        project=project,
        set_prefix=set_prefix,
        set_index=set_index,
        attribute_id=root_attribute_id,
    )


def _write_device_fetch_payload(
    block_instance,
    fetched_payload: DeviceFetchResult,
    scope_prefix: str,
    set_index: int,
) -> None:
    update_values_from_mapped_data(block_instance, fetched_payload.mapped_data)
    for attribute_uri, value in fetched_payload.scoped_scalar_values.items():
        replace_scalar_value_in_scopes(
            block_instance,
            attribute_uri,
            value,
            scopes_to_set=[_device_nested_questionset_scope(set_index)],
            scopes_to_clear=[(scope_prefix, set_index)],
        )


def _fetch_device_detail_payloads(
    plans: list[DeviceBlockPlan],
    root_attribute_id: int,
    configuration_external_id: str | None = None,
    auth_token: str | None = None,
) -> DeviceFetchBatchResult:
    refresh_plans = [plan for plan in plans if plan.needs_refresh]
    if not refresh_plans:
        return DeviceFetchBatchResult(payloads={})

    max_workers = min(DEVICE_DETAIL_FETCH_WORKERS, len(refresh_plans))
    results: dict[str, DeviceFetchResult] = {}
    errors: list[RefreshError] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_plan = {
            executor.submit(
                _fetch_device_detail_payload,
                plan,
                root_attribute_id,
                configuration_external_id,
                auth_token,
            ): plan
            for plan in refresh_plans
        }

        for future in as_completed(future_to_plan):
            plan = future_to_plan[future]
            try:
                result = future.result()
            except Exception as e:
                message = str(e) or e.__class__.__name__
                logger.exception("Failed to fetch device detail payload for %s", plan.device.external_id)
                errors.append(RefreshError(external_id=plan.block_key, message=message))
                continue

            if isinstance(result, DeviceFetchFailure):
                errors.append(RefreshError(external_id=plan.block_key, message=result.message))
            elif result is not None:
                results[plan.block_key] = result

    return DeviceFetchBatchResult(payloads=results, errors=tuple(errors))


def _fetch_device_detail_payload(
    plan: DeviceBlockPlan,
    root_attribute_id: int,
    configuration_external_id: str | None,
    auth_token: str | None = None,
) -> DeviceFetchResult | DeviceFetchFailure | None:
    device_id = _parse_external_id(plan.device.external_id)[1]
    if device_id is None:
        logger.warning("Could not parse external ID %s", plan.device.external_id)
        return DeviceFetchFailure(message="Could not parse external device ID.")

    fetch_instance = _device_block_instance(None, root_attribute_id, "", plan.set_index)
    if getattr(plan.sensor_candidate.handler, "uses_auth_token", False):
        mapped_data = plan.sensor_candidate.handler.handle(
            id_=device_id,
            instance=fetch_instance,
            auth_token=auth_token,
        )
    else:
        mapped_data = plan.sensor_candidate.handler.handle(id_=device_id, instance=fetch_instance)
    if isinstance(mapped_data, dict) and "errors" in mapped_data:
        logger.error("Sensor handler returned errors for %s: %s", plan.device.external_id, mapped_data["errors"])
        return DeviceFetchFailure(message=_format_handler_errors(mapped_data["errors"]))
    if not isinstance(mapped_data, dict):
        message = f"Sensor handler returned unexpected payload type: {type(mapped_data).__name__}."
        logger.warning(
            "Sensor handler returned unexpected payload for %s: %s",
            plan.device.external_id,
            type(mapped_data).__name__,
        )
        return DeviceFetchFailure(message=message)

    mapped_data = dict(mapped_data)
    _merge_mounting_period_values(
        mapped_data,
        plan.device,
        plan.sensor_candidate,
        plan.configuration_external_id or configuration_external_id,
        auth_token=auth_token,
    )
    scoped_scalar_values = {
        INSTRUMENT_START_ATTRIBUTE_URI: mapped_data.pop(INSTRUMENT_START_ATTRIBUTE_URI, ""),
        INSTRUMENT_END_ATTRIBUTE_URI: mapped_data.pop(INSTRUMENT_END_ATTRIBUTE_URI, ""),
    }
    return DeviceFetchResult(
        mapped_data=mapped_data,
        scoped_scalar_values=scoped_scalar_values,
    )


def _format_handler_errors(errors: Any) -> str:
    if isinstance(errors, list):
        return "; ".join(str(error) for error in errors)
    return str(errors)


def _resolve_sensor_candidate(catalog_uri: str, external_id: str) -> Any | None:
    id_prefix, _ = _parse_external_id(external_id)
    if id_prefix is None:
        return None

    from rdmo_sensorsearch.signals.handler_post_save import _get_handler_candidates

    for candidate in _get_handler_candidates(catalog_uri):
        if candidate.id_prefix == id_prefix and getattr(candidate.handler, "sync_device_detail_blocks", False):
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
            snapshot=None,
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
            snapshot=None,
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
    return {block_key: block for block_key, block in all_blocks.items() if _parse_block_external_id(block_key)[0] == config_key}


def _all_existing_device_blocks(project, root_attribute, scope_prefix: str) -> dict[str, dict]:
    blocks: dict[str, dict] = {}
    queryset = (
        Value.objects.filter(
            project=project,
            snapshot=None,
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
            snapshot=None,
            attribute=root_attribute,
            set_collection=True,
            set_prefix=scope_prefix,
        ).values_list("set_index", flat=True)
    )
    if not existing_indexes:
        return 0
    return max(existing_indexes) + 1


def _delete_device_block(project, scope_prefix: str, set_index: int, attribute_ids: set[int]) -> None:
    value_ids = list(
        Value.objects.filter(
            project=project,
            snapshot=None,
            attribute_id__in=attribute_ids,
        )
        .filter(Q(set_prefix=scope_prefix, set_index=set_index) | Q(set_prefix=str(set_index)))
        .order_by("id")
        .values_list("id", flat=True)
        .distinct()
    )
    if not value_ids:
        return

    deleted, _ = Value.objects.filter(
        project=project,
        snapshot=None,
        id__in=value_ids,
    ).delete()
    if deleted:
        logger.info(
            "Deleted device detail block at set_prefix=%s set_index=%s (%s rows, ids=%s)",
            scope_prefix,
            set_index,
            deleted,
            value_ids,
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
    _, created, changed = upsert_value_if_changed(
        {
            "project": project,
            "attribute": attribute,
            "snapshot": None,
            "set_collection": True,
            "set_prefix": scope_prefix,
            "set_index": set_index,
        },
        {
            "text": _device_root_text(config_label, device),
            "external_id": block_key,
        },
    )
    logger.info(
        "%s device block root for %s at set_prefix=%s set_index=%s",
        _change_label(created, changed),
        block_key,
        scope_prefix,
        set_index,
    )


def _upsert_search_value(project, attribute_uri: str, scope_prefix: str, set_index: int, device: SelectedDevice) -> None:
    attribute = _get_attribute_by_uri(attribute_uri)
    if attribute is None:
        logger.warning("Search attribute not found: %s", attribute_uri)
        return

    _, created, changed = upsert_value_if_changed(
        {
            "project": project,
            "attribute": attribute,
            "snapshot": None,
            "set_collection": False,
            "set_prefix": scope_prefix,
            "set_index": set_index,
        },
        {
            "text": _base_device_text(device.text),
            "external_id": device.external_id,
        },
    )
    logger.info(
        "%s device search value for %s at set_prefix=%s set_index=%s",
        _change_label(created, changed),
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


def _compact_device_detail_blocks(
    project,
    catalog,
    scope_prefix: str,
    device_collection_attribute_uri: str = DEVICE_COLLECTION_ATTRIBUTE_URI,
) -> None:
    root_attribute = _get_attribute_by_uri(device_collection_attribute_uri)
    if root_attribute is None:
        return

    root_values = list(
        Value.objects.filter(
            project=project,
            snapshot=None,
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
            snapshot=None,
            attribute_id__in=attribute_ids,
            set_prefix=scope_prefix,
            set_index=old_index,
        ).update(set_index=temp_index)
        Value.objects.filter(
            project=project,
            snapshot=None,
            attribute_id__in=attribute_ids,
            set_prefix=str(old_index),
        ).update(set_prefix=str(temp_index))

    for old_index, new_index in remap.items():
        temp_index = old_index + temp_offset
        Value.objects.filter(
            project=project,
            snapshot=None,
            attribute_id__in=attribute_ids,
            set_prefix=scope_prefix,
            set_index=temp_index,
        ).update(set_index=new_index)
        Value.objects.filter(
            project=project,
            snapshot=None,
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


def _device_block_metadata_is_current(
    project,
    root_attribute,
    search_attribute_uri: str,
    scope_prefix: str,
    set_index: int,
    block_key: str,
    device: SelectedDevice,
    config_label: str,
) -> bool:
    return _has_matching_value(
        project=project,
        attribute=root_attribute,
        scope_prefix=scope_prefix,
        set_index=set_index,
        set_collection=True,
        text=_device_root_text(config_label, device),
        external_id=block_key,
    ) and _has_matching_value(
        project=project,
        attribute_uri=search_attribute_uri,
        scope_prefix=scope_prefix,
        set_index=set_index,
        set_collection=False,
        text=_base_device_text(device.text),
        external_id=device.external_id,
    )


def _device_block_needs_refresh(
    project,
    scope_prefix: str,
    set_index: int,
) -> bool:
    return not (
        _has_nonempty_scalar_value(project, DEVICE_LINK_ATTRIBUTE_URI, scope_prefix, set_index)
        and _has_nonempty_scalar_value(project, USAGE_TECHNOLOGY_ATTRIBUTE_URI, scope_prefix, set_index)
        and _has_nonempty_scalar_value(
            project,
            INSTRUMENT_START_ATTRIBUTE_URI,
            *_device_nested_questionset_scope(set_index),
        )
    )


def _has_matching_value(
    project,
    scope_prefix: str,
    set_index: int,
    set_collection: bool,
    attribute=None,
    attribute_uri: str | None = None,
    text: str | None = None,
    external_id: str | None = None,
) -> bool:
    queryset = Value.objects.filter(
        project=project,
        snapshot=None,
        set_prefix=scope_prefix,
        set_index=set_index,
        set_collection=set_collection,
    )
    if attribute is not None:
        queryset = queryset.filter(attribute=attribute)
    elif attribute_uri:
        queryset = queryset.filter(attribute__uri=attribute_uri)
    else:
        return False

    if text is not None:
        queryset = queryset.filter(text=text)
    if external_id is not None:
        queryset = queryset.filter(external_id=external_id)
    return queryset.exists()


def _has_nonempty_scalar_value(project, attribute_uri: str, scope_prefix: str, set_index: int) -> bool:
    return (
        Value.objects.filter(
            project=project,
            snapshot=None,
            attribute__uri=attribute_uri,
            set_prefix=scope_prefix,
            set_index=set_index,
            set_collection=False,
        )
        .exclude(text__isnull=True)
        .exclude(text__exact="")
        .exists()
    )


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


def _device_block_configuration_key(external_id: str) -> str | None:
    configuration_key, device_external_id = _parse_block_external_id(external_id)
    if not configuration_key or not device_external_id:
        return None
    return configuration_key


def _compose_device_block_key(config_key: str, device_external_id: str) -> str:
    return f"{config_key}||{device_external_id}"


def _device_root_text(config_label: str, device: SelectedDevice) -> str:
    return device.text or f"{config_label}: {_base_device_text(device.text)}"


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
            snapshot=None,
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
    auth_token: str | None = None,
) -> None:
    if INSTRUMENT_START_ATTRIBUTE_URI in mapped_data:
        mapped_data.setdefault(INSTRUMENT_END_ATTRIBUTE_URI, "")
        return
    if device.instrument_start:
        mapped_data[INSTRUMENT_START_ATTRIBUTE_URI] = device.instrument_start
        mapped_data[INSTRUMENT_END_ATTRIBUTE_URI] = device.instrument_end or ""
        return

    start_value, end_value = _resolve_mounting_period_values(
        mapped_data,
        device,
        sensor_candidate,
        configuration_external_id,
        auth_token=auth_token,
    )
    mapped_data[INSTRUMENT_START_ATTRIBUTE_URI] = start_value or ""
    mapped_data[INSTRUMENT_END_ATTRIBUTE_URI] = end_value or ""


def _resolve_mounting_period_values(
    mapped_data: dict[str, Any],
    device: SelectedDevice,
    sensor_candidate: Any,
    configuration_external_id: str | None,
    auth_token: str | None = None,
) -> tuple[str | None, str | None]:
    if not configuration_external_id:
        return None, None

    _, configuration_id = _parse_external_id(configuration_external_id)
    device_id = _parse_external_id(device.external_id)[1]
    if configuration_id is None or device_id is None:
        return None, None

    if not getattr(sensor_candidate.handler, "supports_mount_action_period_lookup", False):
        return None, None

    mount_actions = _fetch_device_mount_actions(sensor_candidate, device_id, auth_token=auth_token)
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


def _fetch_device_mount_actions(sensor_candidate: Any, device_id: str, auth_token: str | None = None) -> list[dict]:
    url = (
        f"{sensor_candidate.handler.base_url}/devices/{device_id}/device-mount-actions"
        "?page[size]=10000&include=begin_contact,end_contact,parent_platform,parent_device,configuration"
    )
    action_data = fetch_json(url, auth_token=auth_token)
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
