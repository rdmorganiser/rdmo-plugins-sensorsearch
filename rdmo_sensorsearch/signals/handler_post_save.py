import logging

from django.db import transaction

from rdmo_sensorsearch.handlers.base import HandlerResult
from rdmo_sensorsearch.handlers.factory import WILDCARD_CATALOG_URI, build_handlers_by_catalog
from rdmo_sensorsearch.handlers.handler_sms import (
    INSTRUMENT_END_ATTRIBUTE_URI,
    INSTRUMENT_START_ATTRIBUTE_URI,
)
from rdmo_sensorsearch.signals.refresh_types import (
    RefreshError,
    RefreshResult,
    combine_refresh_results,
)
from rdmo_sensorsearch.signals.value_updater import (
    build_clear_payload,
    clear_attribute_values,
    clear_collection_attribute,
    replace_scalar_value_in_scopes,
    update_values_from_handler_result,
    update_values_from_mapped_data,
)

logger = logging.getLogger(__name__)

ALL_HANDLER_MAP = build_handlers_by_catalog()


def _get_handler_candidates(catalog_uri: str) -> list:
    specific_candidates = ALL_HANDLER_MAP.get(catalog_uri, [])
    wildcard_candidates = ALL_HANDLER_MAP.get(WILDCARD_CATALOG_URI, [])

    seen = {
        (candidate.id_prefix, candidate.auto_complete_field_uri, type(candidate.handler)) for candidate in specific_candidates
    }

    merged_candidates = list(specific_candidates)
    for candidate in wildcard_candidates:
        key = (candidate.id_prefix, candidate.auto_complete_field_uri, type(candidate.handler))
        if key not in seen:
            merged_candidates.append(candidate)

    return merged_candidates


def _clear_handler_targets(
    instance,
    handler,
    preserved_collection_attribute_uris: set[str] | None = None,
) -> None:
    preserved_collection_attribute_uris = preserved_collection_attribute_uris or set()
    reset_attribute_uris = set(getattr(handler, "reset_attribute_uris", []))
    member_sensors_attribute_uri = getattr(handler, "member_sensors_attribute_uri", None)
    selected_devices_page_uri = getattr(handler, "selected_devices_page_uri", None)

    for attribute_uri_to_clear in getattr(handler, "reset_attribute_uris", []):
        if attribute_uri_to_clear == member_sensors_attribute_uri:
            continue
        clear_attribute_values(instance, attribute_uri_to_clear)

    clear_payload = {
        attribute_uri: value
        for attribute_uri, value in build_clear_payload(handler.attribute_mapping).items()
        if attribute_uri not in reset_attribute_uris
    }
    update_values_from_mapped_data(instance, clear_payload)

    if (
        member_sensors_attribute_uri
        and member_sensors_attribute_uri not in preserved_collection_attribute_uris
        and selected_devices_page_uri
    ):
        clear_collection_attribute(instance, member_sensors_attribute_uri, selected_devices_page_uri)


def _clear_handler_signature(handler) -> tuple:
    reset_attribute_uris = tuple(sorted(getattr(handler, "reset_attribute_uris", [])))
    mapped_attribute_uris = tuple(sorted(set(handler.attribute_mapping.values())))
    member_sensors_attribute_uri = getattr(handler, "member_sensors_attribute_uri", None)
    selected_devices_page_uri = getattr(handler, "selected_devices_page_uri", None)
    return reset_attribute_uris, mapped_attribute_uris, member_sensors_attribute_uri, selected_devices_page_uri


def _device_nested_questionset_scope(instance) -> tuple[str, int]:
    return str(instance.set_index), 0


def _update_mapped_data(instance, mapped_data: dict) -> None:
    mapped_data = dict(mapped_data)
    scoped_scalar_values = {
        INSTRUMENT_START_ATTRIBUTE_URI: mapped_data.pop(INSTRUMENT_START_ATTRIBUTE_URI, ""),
        INSTRUMENT_END_ATTRIBUTE_URI: mapped_data.pop(INSTRUMENT_END_ATTRIBUTE_URI, ""),
    }
    update_values_from_mapped_data(instance, mapped_data)
    for attribute_uri, value in scoped_scalar_values.items():
        if attribute_uri not in {INSTRUMENT_START_ATTRIBUTE_URI, INSTRUMENT_END_ATTRIBUTE_URI}:
            continue
        replace_scalar_value_in_scopes(
            instance,
            attribute_uri,
            value,
            scopes_to_set=[_device_nested_questionset_scope(instance)],
            scopes_to_clear=[(instance.set_prefix or "", instance.set_index)],
        )


def handle_post_save(instance, auth_token: str | None = None) -> None:
    if not ALL_HANDLER_MAP:
        logger.warning("No handlers found for %s", __name__)
        return
    if getattr(instance, "snapshot_id", None) is not None:
        logger.debug("Skipping post_save handling for snapshot value %s", instance.pk)
        return

    project = instance.project
    attribute = instance.attribute

    if project is None or attribute is None or project.catalog is None:
        logger.debug("Skipping post_save handling for incomplete value instance: %r", instance)
        return

    catalog_uri = project.catalog.uri
    attribute_uri = attribute.uri

    if not catalog_uri or not attribute_uri:
        logger.warning("Missing catalog or attribute URI")
        return

    handler_candidates = _get_handler_candidates(catalog_uri)
    attribute_handler_candidates = [
        candidate for candidate in handler_candidates if candidate.auto_complete_field_uri == attribute_uri
    ]

    if not attribute_handler_candidates:
        logger.debug(
            "Skipping post_save handling for attribute_uri=%s in catalog=%s because no handler is configured for it",
            attribute_uri,
            catalog_uri,
        )
        return

    if not instance.external_id and getattr(instance, "is_empty", False):
        cleared_signatures = set()
        for candidate in attribute_handler_candidates:
            signature = _clear_handler_signature(candidate.handler)
            if signature in cleared_signatures:
                continue
            cleared_signatures.add(signature)
            _clear_handler_targets(instance, candidate.handler)
        return

    result = refresh_value_from_backend(instance, auth_token=auth_token)
    for error in result.errors:
        logger.error("Backend update failed for %s: %s", error.external_id, error.message)


def refresh_value_from_backend(instance, auth_token: str | None = None) -> RefreshResult:
    external_id = getattr(instance, "external_id", None) or ""
    if not external_id:
        return _failed_refresh(external_id, "Value has no external ID.")

    project = getattr(instance, "project", None)
    attribute = getattr(instance, "attribute", None)
    catalog = getattr(project, "catalog", None)
    if project is None or attribute is None or catalog is None:
        return _failed_refresh(external_id, "Value has no complete project, catalog, and attribute context.")

    try:
        id_prefix, backend_id = external_id.split(":", 1)
    except ValueError:
        return _failed_refresh(external_id, "External ID must contain a backend prefix.")

    candidates = [
        candidate
        for candidate in _get_handler_candidates(catalog.uri)
        if candidate.id_prefix == id_prefix and candidate.auto_complete_field_uri == attribute.uri
    ]
    if not candidates:
        return _failed_refresh(external_id, "No matching backend handler is configured.")
    if len(candidates) > 1:
        return _failed_refresh(external_id, "Multiple matching backend handlers are configured.")

    candidate = candidates[0]
    try:
        if getattr(candidate.handler, "uses_auth_token", False):
            mapped_data = candidate.handler.handle(id_=backend_id, instance=instance, auth_token=auth_token)
        else:
            mapped_data = candidate.handler.handle(id_=backend_id, instance=instance)
    except Exception as error:
        logger.exception(
            "Handler %s failed while processing external_id=%s for catalog=%s",
            candidate.id_prefix,
            backend_id,
            catalog.uri,
        )
        return _failed_refresh(external_id, str(error) or type(error).__name__)

    if isinstance(mapped_data, dict) and "errors" in mapped_data:
        return _failed_refresh(external_id, _format_handler_errors(mapped_data["errors"]))
    if not isinstance(mapped_data, (dict, HandlerResult)):
        return _failed_refresh(external_id, f"Handler returned {type(mapped_data).__name__}, expected mapped data.")

    post_actions = ()
    try:
        preserved_collection_attribute_uris = (
            {collection.attribute_uri for collection in mapped_data.collections}
            if isinstance(mapped_data, HandlerResult)
            else set()
        )
        with transaction.atomic():
            _clear_handler_targets(
                instance,
                candidate.handler,
                preserved_collection_attribute_uris=preserved_collection_attribute_uris,
            )
            if isinstance(mapped_data, HandlerResult):
                post_actions = update_values_from_handler_result(instance, mapped_data)
            else:
                _update_mapped_data(instance, mapped_data)
    except Exception as error:
        logger.exception("Failed to apply backend data for external_id=%s", external_id)
        return _failed_refresh(external_id, f"Could not store backend data: {error}")

    try:
        post_action_results = tuple(post_action() for post_action in post_actions)
    except Exception as error:
        logger.exception("Failed to run post-update actions for external_id=%s", external_id)
        return _failed_refresh(external_id, f"Could not complete backend update: {error}")

    device_result = combine_refresh_results(result for result in post_action_results if isinstance(result, RefreshResult))
    return RefreshResult(
        requested_count=1,
        refreshed_count=1,
        errors=device_result.errors,
        device_requested_count=device_result.requested_count,
        device_refreshed_count=device_result.refreshed_count,
    )


def _failed_refresh(external_id: str, message: str) -> RefreshResult:
    return RefreshResult(
        requested_count=1,
        refreshed_count=0,
        errors=(RefreshError(external_id=external_id, message=message),),
    )


def _format_handler_errors(errors) -> str:
    if isinstance(errors, (list, tuple)):
        return "; ".join(str(error) for error in errors)
    return str(errors)
