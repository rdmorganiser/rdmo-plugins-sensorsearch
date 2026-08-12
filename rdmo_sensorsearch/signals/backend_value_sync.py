import logging
from dataclasses import replace

from django.db import transaction

from rdmo.domain.models import Attribute

from rdmo_sensorsearch.handlers.base import CollectionAssignment, HandlerExecutionContext, HandlerResult
from rdmo_sensorsearch.handlers.catalog_registry import (
    get_handler_bindings_for_catalog,
    handler_bindings_by_catalog,
)
from rdmo_sensorsearch.handlers.sms_device_enrichment import (
    INSTRUMENT_END_ATTRIBUTE_URI,
    INSTRUMENT_START_ATTRIBUTE_URI,
)
from rdmo_sensorsearch.naming import canonical_device_label
from rdmo_sensorsearch.persistence.collection_binding import CollectionBinding, CollectionBindingError, CollectionScope
from rdmo_sensorsearch.persistence.value_reconciliation import (
    reconcile_handler_result,
    replace_scalar_value_in_scopes,
)
from rdmo_sensorsearch.services.refresh import (
    RefreshError,
    RefreshResult,
    combine_refresh_results,
)
from rdmo_sensorsearch.workflows.device_details import (
    get_selected_device_values_for_configuration_scope,
    reconcile_device_details_from_selected_values,
)

logger = logging.getLogger(__name__)


def _empty_handler_result(handler) -> HandlerResult:
    selected_devices_attribute_uri = getattr(handler, "selected_devices_attribute_uri", None)
    selected_devices_page_uri = getattr(handler, "selected_devices_page_uri", None)
    collections = ()
    if selected_devices_attribute_uri and selected_devices_page_uri:
        collections = (
            CollectionAssignment(
                attribute_uri=selected_devices_attribute_uri,
                page_uri=selected_devices_page_uri,
                values=(),
            ),
        )
    return HandlerResult(collections=collections)


def _handler_ownership_signature(handler) -> tuple:
    managed_attribute_uris = tuple(sorted(handler.managed_attribute_uris))
    mapped_attribute_uris = tuple(sorted(set(handler.attribute_mapping.values())))
    selected_devices_attribute_uri = getattr(handler, "selected_devices_attribute_uri", None)
    selected_devices_page_uri = getattr(handler, "selected_devices_page_uri", None)
    return managed_attribute_uris, mapped_attribute_uris, selected_devices_attribute_uri, selected_devices_page_uri


def _device_nested_questionset_scope(instance) -> tuple[str, int]:
    return str(instance.set_index), 0


def _reconcile_result(instance, handler, result: HandlerResult) -> tuple:
    scoped_attribute_uris = {
        attribute_uri
        for attribute_uri in (INSTRUMENT_START_ATTRIBUTE_URI, INSTRUMENT_END_ATTRIBUTE_URI)
        if attribute_uri in handler.managed_attribute_uris or attribute_uri in result.mapped_values
    }
    input_attribute_uris = {
        attribute_uri
        for attribute_uri in (
            getattr(handler, "period_start_attribute_uri", None),
            getattr(handler, "period_end_attribute_uri", None),
        )
        if attribute_uri
    }
    post_actions = reconcile_handler_result(
        instance,
        handler,
        result,
        excluded_attribute_uris=scoped_attribute_uris | input_attribute_uris,
    )

    scoped_scalar_values = {attribute_uri: result.mapped_values.get(attribute_uri, "") for attribute_uri in scoped_attribute_uris}
    for attribute_uri, value in scoped_scalar_values.items():
        replace_scalar_value_in_scopes(
            instance,
            attribute_uri,
            value,
            scopes_to_set=[_device_nested_questionset_scope(instance)],
            scopes_to_clear=[(instance.set_prefix or "", instance.set_index)],
        )
    return post_actions


def sync_backend_value_after_save(instance, auth_token: str | None = None) -> None:
    if not handler_bindings_by_catalog():
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

    handler_bindings = get_handler_bindings_for_catalog(catalog_uri)
    matching_bindings = [binding for binding in handler_bindings if binding.search_attribute_uri == attribute_uri]

    if not matching_bindings:
        logger.debug(
            "Skipping post_save handling for attribute_uri=%s in catalog=%s because no handler is configured for it",
            attribute_uri,
            catalog_uri,
        )
        return

    if not instance.external_id and getattr(instance, "is_empty", False):
        reconciled_signatures = set()
        for binding in matching_bindings:
            signature = _handler_ownership_signature(binding.handler)
            if signature in reconciled_signatures:
                continue
            reconciled_signatures.add(signature)
            with transaction.atomic():
                _reconcile_result(instance, binding.handler, _empty_handler_result(binding.handler))
        return

    result = refresh_value_from_backend(instance, auth_token=auth_token)
    for error in result.errors:
        logger.error("Backend update failed for %s: %s", error.external_id, error.message)


def refresh_value_from_backend(
    instance,
    auth_token: str | None = None,
    preserve_existing_collections: bool = False,
    require_configuration_period: bool = False,
) -> RefreshResult:
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

    bindings = [
        binding
        for binding in get_handler_bindings_for_catalog(catalog.uri)
        if binding.id_prefix == id_prefix and binding.search_attribute_uri == attribute.uri
    ]
    if not bindings:
        return _failed_refresh(external_id, "No matching backend handler is configured.")
    if len(bindings) > 1:
        return _failed_refresh(external_id, "Multiple matching backend handlers are configured.")

    binding = bindings[0]
    context = HandlerExecutionContext(
        preserve_existing_collections=preserve_existing_collections,
        require_configuration_period=require_configuration_period,
    )
    try:
        if getattr(binding.handler, "uses_auth_token", False):
            handler_output = binding.handler.handle(
                backend_id=backend_id,
                instance=instance,
                auth_token=auth_token,
                context=context,
            )
        else:
            handler_output = binding.handler.handle(backend_id=backend_id, instance=instance, context=context)
    except Exception as error:
        logger.exception(
            "Handler %s failed while processing external_id=%s for catalog=%s",
            binding.id_prefix,
            backend_id,
            catalog.uri,
        )
        return _failed_refresh(external_id, str(error) or type(error).__name__)

    if isinstance(handler_output, dict) and "errors" in handler_output:
        return _failed_refresh(external_id, _format_handler_errors(handler_output["errors"]))
    if not isinstance(handler_output, HandlerResult):
        return _failed_refresh(external_id, f"Handler returned {type(handler_output).__name__}, expected HandlerResult.")

    try:
        if preserve_existing_collections:
            handler_output = replace(
                handler_output,
                collections=_preserved_collection_assignments(instance, binding.handler),
            )
        with transaction.atomic():
            post_actions = _reconcile_result(instance, binding.handler, handler_output)
    except Exception as error:
        logger.exception("Failed to apply backend data for external_id=%s", external_id)
        return _failed_refresh(external_id, f"Could not store backend data: {error}")

    try:
        post_action_results = [post_action() for post_action in post_actions]
        if preserve_existing_collections:
            post_action_results.append(
                _refresh_selected_configuration_devices(
                    instance,
                    binding.handler,
                    handler_output.mapped_values,
                    auth_token=auth_token,
                )
            )
    except Exception as error:
        logger.exception("Failed to run post-update actions for external_id=%s", external_id)
        return _failed_refresh(external_id, f"Could not complete backend update: {error}")

    device_result = combine_refresh_results(result for result in post_action_results if isinstance(result, RefreshResult))
    notices = tuple(handler_output.notices) + tuple(device_result.notices)
    for notice in notices:
        logger.info(
            "Backend synchronization notice for %s: %s %s",
            notice.external_id or external_id,
            notice.code,
            dict(notice.details),
        )
    return RefreshResult(
        requested_count=1,
        refreshed_count=1,
        errors=device_result.errors,
        device_requested_count=device_result.requested_count,
        device_refreshed_count=device_result.refreshed_count,
        notices=notices,
    )


def _refresh_selected_configuration_devices(
    instance,
    handler,
    configuration_values,
    auth_token: str | None = None,
) -> RefreshResult:
    selected_devices_attribute_uri = getattr(handler, "selected_devices_attribute_uri", None)
    selected_devices_page_uri = getattr(handler, "selected_devices_page_uri", None)
    device_collection_attribute_uri = getattr(handler, "device_collection_attribute_uri", None)
    if not selected_devices_attribute_uri or not selected_devices_page_uri or not device_collection_attribute_uri:
        return RefreshResult(requested_count=0, refreshed_count=0)

    try:
        binding = CollectionBinding.resolve(
            instance.project,
            _get_attribute(selected_devices_attribute_uri),
            selected_devices_page_uri,
        )
    except (CollectionBindingError, ValueError) as error:
        return RefreshResult(
            requested_count=0,
            refreshed_count=0,
            errors=(
                RefreshError(
                    external_id=instance.external_id or "",
                    message=f"Could not resolve the selected Device Set: {error}",
                ),
            ),
        )

    scope = CollectionScope(set_prefix=instance.set_prefix or "", set_index=instance.set_index)
    selected_values = get_selected_device_values_for_configuration_scope(
        binding,
        scope.set_prefix,
        scope.set_index,
    )
    period_resolver = getattr(handler, "get_member_device_period", None)
    instrument_start, instrument_end = (
        period_resolver(instance, configuration_values) if callable(period_resolver) else (None, None)
    )
    return reconcile_device_details_from_selected_values(
        project=instance.project,
        catalog=instance.project.catalog,
        scope_prefix=scope.set_prefix,
        source_set_index=scope.set_index,
        selected_values=selected_values,
        selected_devices_attribute_uri=selected_devices_attribute_uri,
        device_collection_attribute_uri=device_collection_attribute_uri,
        configuration_search_attribute_uri=instance.attribute.uri,
        auth_token=auth_token,
        force_refresh=True,
        instrument_start=instrument_start,
        instrument_end=instrument_end,
    )


def _preserved_collection_assignments(instance, handler) -> tuple[CollectionAssignment, ...]:
    selected_devices_attribute_uri = getattr(handler, "selected_devices_attribute_uri", None)
    selected_devices_page_uri = getattr(handler, "selected_devices_page_uri", None)
    if not selected_devices_attribute_uri or not selected_devices_page_uri:
        return ()

    attribute = _get_attribute(selected_devices_attribute_uri)
    binding = CollectionBinding.resolve(
        instance.project,
        attribute,
        selected_devices_page_uri,
    )
    scope = CollectionScope(set_prefix=instance.set_prefix or "", set_index=instance.set_index)
    active_values = list(binding.values_for_scope(scope))
    inactive_values = list(binding.opposite_values_for_scope(scope))
    source_values = active_values if _has_collection_content(active_values) else inactive_values

    return (
        CollectionAssignment(
            attribute_uri=selected_devices_attribute_uri,
            page_uri=selected_devices_page_uri,
            values=tuple(
                {
                    "text": canonical_device_label(value.text or "", value.external_id),
                    "external_id": value.external_id or "",
                }
                for value in source_values
                if value.text or value.external_id
            ),
        ),
    )


def _has_collection_content(values) -> bool:
    return any(value.text or value.external_id for value in values)


def _get_attribute(attribute_uri: str):
    try:
        return Attribute.objects.get(uri=attribute_uri)
    except Attribute.DoesNotExist as error:
        raise ValueError(f"Attribute not found: {attribute_uri}") from error


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
