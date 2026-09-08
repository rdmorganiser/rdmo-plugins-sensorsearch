import logging
from collections.abc import Iterable
from functools import partial
from typing import Any

from django.db import transaction

from rdmo.projects.models import Value

from rdmo_sensorsearch.handlers.catalog_registry import get_handler_bindings_for_catalog
from rdmo_sensorsearch.handlers.sms_device_enrichment import SMSDeviceMetadataEnricher
from rdmo_sensorsearch.naming import configuration_short_label
from rdmo_sensorsearch.persistence.catalog_context import workflow_catalog_context
from rdmo_sensorsearch.persistence.collection_binding import CollectionBinding, CollectionScope
from rdmo_sensorsearch.persistence.device_details import (
    RDMODeviceDetailStore,
    catalog_attribute_ids,
    get_attribute_by_uri,
)
from rdmo_sensorsearch.services.device_detail_profile import get_device_detail_settings
from rdmo_sensorsearch.services.device_details import (
    ConfigurationIdentity,
    SelectedDevice,
    compose_device_block_key,
    parse_external_id,
    plan_device_detail_reconciliation,
    unique_selected_devices,
)
from rdmo_sensorsearch.services.device_metadata import fetch_device_metadata_batch
from rdmo_sensorsearch.services.refresh import RefreshError, RefreshResult
from rdmo_sensorsearch.services.synchronization_context import mute_value_sync

logger = logging.getLogger(__name__)


def reconcile_device_details_from_selected_values(
    project,
    catalog,
    scope_prefix: str,
    source_set_index: int,
    selected_values: Iterable[Value],
    selected_devices_attribute_uri: str,
    device_collection_attribute_uri: str,
    configuration_search_attribute_uri: str,
    auth_token: str | None = None,
    force_refresh: bool = False,
    instrument_start: str | None = None,
    instrument_end: str | None = None,
) -> RefreshResult:
    selected_devices = [
        SelectedDevice(
            text=value.text or "",
            external_id=value.external_id,
            instrument_start=instrument_start,
            instrument_end=instrument_end,
        )
        for value in selected_values
        if value.external_id
    ]
    return reconcile_device_details(
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
        force_refresh=force_refresh,
    )


def reconcile_device_details_from_selected_devices(
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
    return reconcile_device_details(
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


@workflow_catalog_context()
def reconcile_device_details(
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
    detail_settings = get_device_detail_settings(catalog.uri)
    selected_devices = unique_selected_devices(selected_devices)
    configuration_identity = _resolve_configuration_identity(
        project=project,
        scope_prefix=scope_prefix,
        source_set_index=source_set_index,
        configuration_search_attribute_uri=configuration_search_attribute_uri,
        configuration_collection_attribute_uri=detail_settings.configuration_collection_attribute_uri,
        configuration_external_id=configuration_external_id,
    )
    if configuration_identity is None:
        logger.warning(
            "Could not resolve configuration context for selected devices attribute %s",
            selected_devices_attribute_uri,
        )
        return _failed_device_sync(
            configuration_external_id or "",
            "Could not resolve the configuration context for device synchronization.",
            requested_count=len(selected_devices),
        )

    configuration_key = configuration_identity.configuration_key
    configuration_label = configuration_identity.label
    device_detail_attribute_ids = catalog_attribute_ids(catalog, {detail_settings.device_details_page_uri})
    if not device_detail_attribute_ids:
        logger.warning("Could not resolve device detail attributes for %s", detail_settings.device_details_page_uri)
        return _failed_device_sync(
            configuration_key,
            f"Could not resolve device detail attributes for {detail_settings.device_details_page_uri}.",
            requested_count=len(selected_devices),
        )
    related_attribute_ids = (
        catalog_attribute_ids(
            catalog,
            {detail_settings.device_details_page_uri, detail_settings.device_optional_info_page_uri},
        )
        or device_detail_attribute_ids
    )

    root_attribute = get_attribute_by_uri(device_collection_attribute_uri)
    if root_attribute is None:
        logger.warning("Device collection root attribute not found: %s", device_collection_attribute_uri)
        return _failed_device_sync(
            configuration_key,
            f"Device collection root attribute not found: {device_collection_attribute_uri}.",
            requested_count=len(selected_devices),
        )

    store = RDMODeviceDetailStore(project, root_attribute, scope_prefix)
    planning_state = store.load_planning_state(
        {
            *(binding.search_attribute_uri for binding in get_handler_bindings_for_catalog(catalog.uri)),
            detail_settings.device_link_attribute_uri,
            detail_settings.usage_technology_attribute_uri,
            detail_settings.instrument_start_attribute_uri,
        }
    )

    reconciliation_plan = plan_device_detail_reconciliation(
        selected_devices=selected_devices,
        configuration_key=configuration_key,
        configuration_external_id=configuration_identity.external_id,
        set_prefix=scope_prefix,
        existing_blocks=planning_state.existing_blocks(configuration_key),
        next_set_index=planning_state.next_index,
        resolve_handler=lambda external_id: _resolve_device_handler_binding(project.catalog.uri, external_id),
        metadata_is_current=partial(
            planning_state.block_metadata_is_current,
            configuration_label=configuration_label,
        ),
        refresh_is_required=partial(
            planning_state.block_needs_refresh,
            device_link_attribute_uri=detail_settings.device_link_attribute_uri,
            usage_technology_attribute_uri=detail_settings.usage_technology_attribute_uri,
            instrument_start_attribute_uri=detail_settings.instrument_start_attribute_uri,
        ),
        force_refresh=force_refresh,
    )
    del planning_state
    plans = list(reconciliation_plan.blocks)
    stale_blocks = reconciliation_plan.stale_blocks
    planning_errors = [
        RefreshError(external_id=failure.external_id, message=failure.message) for failure in reconciliation_plan.failures
    ]
    for failure in reconciliation_plan.failures:
        logger.warning("No device handler found for selected device %s", failure.external_id)

    metadata_enricher = SMSDeviceMetadataEnricher(
        configuration_external_id=configuration_identity.external_id,
        auth_token=auth_token,
        detail_settings=detail_settings,
    )
    fetch_batch = fetch_device_metadata_batch(
        plans,
        root_attribute_id=root_attribute.id,
        scoped_attribute_uris=metadata_enricher.scoped_attribute_uris,
        auth_token=auth_token,
        enrich_payload=metadata_enricher,
    )
    fetched_payloads = fetch_batch.payloads
    fetch_errors = tuple(RefreshError(external_id=error.external_id, message=error.message) for error in fetch_batch.errors)

    with transaction.atomic(), mute_value_sync():
        for block in stale_blocks:
            store.delete_block(block.set_index, related_attribute_ids)

        for plan in plans:
            if plan.needs_metadata_write:
                store.upsert_block_identity(plan, configuration_label)

            fetched_payload = fetched_payloads.get(plan.block_key)
            if fetched_payload is None:
                continue

            store.write_fetch_payload(
                plan,
                fetched_payload,
                excluded_attribute_uris={
                    detail_settings.instrument_start_attribute_uri,
                    detail_settings.instrument_end_attribute_uri,
                },
            )

        if stale_blocks:
            store.compact(related_attribute_ids)

    return RefreshResult(
        requested_count=sum(plan.needs_refresh for plan in plans) + len(planning_errors),
        refreshed_count=len(fetched_payloads),
        errors=tuple(planning_errors) + fetch_errors,
        notices=tuple(notice for payload in fetched_payloads.values() for notice in payload.notices),
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


def remove_device_detail_block_for_selected_device(
    project,
    catalog,
    scope_prefix: str,
    source_set_index: int,
    device_external_id: str,
    device_collection_attribute_uri: str,
    configuration_search_attribute_uri: str,
) -> bool:
    if not device_external_id:
        return False

    detail_settings = get_device_detail_settings(catalog.uri)
    configuration_identity = _resolve_configuration_identity(
        project=project,
        scope_prefix=scope_prefix,
        source_set_index=source_set_index,
        configuration_search_attribute_uri=configuration_search_attribute_uri,
        configuration_collection_attribute_uri=detail_settings.configuration_collection_attribute_uri,
    )
    if configuration_identity is None:
        logger.warning(
            "Could not resolve configuration context while removing selected device %s",
            device_external_id,
        )
        return False

    root_attribute = get_attribute_by_uri(device_collection_attribute_uri)
    if root_attribute is None:
        logger.warning("Device collection root attribute not found: %s", device_collection_attribute_uri)
        return False

    block_key = compose_device_block_key(configuration_identity.configuration_key, device_external_id)
    store = RDMODeviceDetailStore(project, root_attribute, scope_prefix)
    block = store.find_block(block_key)
    if block is None:
        logger.debug("No device detail block exists for removed selected device %s", block_key)
        return False

    related_attribute_ids = catalog_attribute_ids(
        catalog,
        {detail_settings.device_details_page_uri, detail_settings.device_optional_info_page_uri},
    )
    if not related_attribute_ids:
        logger.warning("Could not resolve device detail attributes for %s", detail_settings.device_details_page_uri)
        return False

    with transaction.atomic(), mute_value_sync():
        deleted = store.delete_block(block.set_index, related_attribute_ids)

    if deleted:
        logger.info("Removed device detail block for deselected device %s", block_key)
    return bool(deleted)


def remove_orphaned_device_detail_blocks(
    project,
    catalog,
    configuration_search_attribute_uris: Iterable[str],
    device_collection_attribute_uri: str,
) -> int:
    detail_settings = get_device_detail_settings(catalog.uri)
    root_attribute = get_attribute_by_uri(device_collection_attribute_uri)
    if root_attribute is None:
        logger.warning("Device collection root attribute not found: %s", device_collection_attribute_uri)
        return 0

    related_attribute_ids = catalog_attribute_ids(
        catalog,
        {detail_settings.device_details_page_uri, detail_settings.device_optional_info_page_uri},
    )
    if not related_attribute_ids:
        logger.warning("Could not resolve device detail attributes for %s", detail_settings.device_details_page_uri)
        return 0

    store = RDMODeviceDetailStore(project, root_attribute)
    orphaned_scopes = store.orphaned_scopes(configuration_search_attribute_uris)
    if not orphaned_scopes:
        return 0

    with transaction.atomic(), mute_value_sync():
        for scope_prefix, set_index in orphaned_scopes:
            store.for_scope(scope_prefix).delete_block(set_index, related_attribute_ids)
        for scope_prefix in {scope_prefix for scope_prefix, _ in orphaned_scopes}:
            store.for_scope(scope_prefix).compact(related_attribute_ids)

    logger.info(
        "Removed %s orphaned device detail block(s) after configuration cleanup",
        len(orphaned_scopes),
    )
    return len(orphaned_scopes)


def _resolve_device_handler_binding(catalog_uri: str, external_id: str) -> Any | None:
    id_prefix, _ = parse_external_id(external_id)
    if id_prefix is None:
        return None

    for binding in get_handler_bindings_for_catalog(catalog_uri):
        if binding.id_prefix == id_prefix and getattr(binding.handler, "materialize_device_details", False):
            return binding
    return None


def _resolve_configuration_identity(
    project,
    scope_prefix: str,
    source_set_index: int,
    configuration_search_attribute_uri: str,
    configuration_collection_attribute_uri: str,
    configuration_external_id: str | None = None,
) -> ConfigurationIdentity | None:
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
            attribute__uri=configuration_collection_attribute_uri,
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

    configuration_key = _configuration_key(config_search_value, configuration_set_value, scope_prefix, source_set_index)
    return ConfigurationIdentity(
        configuration_key=configuration_key,
        label=_configuration_label(config_search_value, configuration_set_value, source_set_index),
        external_id=configuration_external_id or _configuration_external_id(config_search_value),
    )


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
    backend_label = configuration_short_label(_configuration_external_id(config_search_value))
    if backend_label:
        return backend_label

    if configuration_set_value is not None and configuration_set_value.text:
        return configuration_set_value.text.strip()

    if config_search_value is not None and isinstance(config_search_value.text, str):
        text = config_search_value.text.strip()
        if text:
            return text.split(":", 1)[0].strip() or str(source_set_index)
    return str(source_set_index)
