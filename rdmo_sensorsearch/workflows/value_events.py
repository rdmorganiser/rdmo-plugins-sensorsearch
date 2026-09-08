"""Orchestrate synchronization triggered by committed RDMO Value events."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import perf_counter

from django.db.models import Q

from rdmo.domain.models import Attribute
from rdmo.projects.models import Project, Value

from rdmo_sensorsearch.client import deduplicate_json_requests
from rdmo_sensorsearch.handlers.catalog_registry import get_handler_bindings_for_catalog
from rdmo_sensorsearch.persistence.catalog_context import workflow_catalog_context
from rdmo_sensorsearch.persistence.collection_binding import (
    CollectionBinding,
    CollectionBindingError,
    CollectionScope,
)
from rdmo_sensorsearch.services.performance import measure_phase
from rdmo_sensorsearch.workflows.backend_value_sync import sync_backend_value_after_save
from rdmo_sensorsearch.workflows.configuration_tabs import (
    clear_configuration_tab_from_deleted_source,
    sync_configuration_tab_from_root,
    sync_configuration_tab_from_source,
)
from rdmo_sensorsearch.workflows.data_collection_variables import (
    get_data_collection_variable_sync_settings,
    reconcile_data_collection_variables_for_selected_device,
    remove_stale_generated_data_collection_variables_for_deleted_device,
)
from rdmo_sensorsearch.workflows.device_details import (
    get_configuration_scope_for_value,
    get_selected_device_values_for_configuration_scope,
    reconcile_device_details_from_selected_values,
    remove_device_detail_block_for_selected_device,
    remove_orphaned_device_detail_blocks,
)
from rdmo_sensorsearch.workflows.event_routing import is_relevant_attribute
from rdmo_sensorsearch.workflows.metadata_refresh import (
    clear_refresh_state,
    clear_refresh_state_for_source,
    get_refresh_action,
    get_refresh_actions_for_input,
    get_refresh_actions_for_source,
    run_metadata_refresh_action,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeletedValueContext:
    """Database-independent fields needed after a Value row has been deleted."""

    value_id: int | None
    project_id: int
    catalog_uri: str
    attribute_id: int
    attribute_uri: str
    set_prefix: str
    set_index: int
    external_id: str

    @classmethod
    def from_value(cls, instance: Value, *, routing: tuple[str, str] | None = None) -> DeletedValueContext | None:
        if instance.project_id is None or instance.attribute_id is None:
            return None
        if routing is None:
            project = Project.objects.select_related("catalog").filter(pk=instance.project_id).first()
            attribute = Attribute.objects.filter(pk=instance.attribute_id).first()
            if project is None or project.catalog is None or attribute is None:
                return None
            routing = project.catalog.uri, attribute.uri
        return cls(
            value_id=instance.pk,
            project_id=instance.project_id,
            catalog_uri=routing[0],
            attribute_id=instance.attribute_id,
            attribute_uri=routing[1],
            set_prefix=instance.set_prefix or "",
            set_index=instance.set_index,
            external_id=instance.external_id or "",
        )


@measure_phase("callback.save.executed")
def handle_value_saved(value_id: int, auth_token: str | None = None) -> None:
    instance = Value.objects.select_related("project__catalog", "attribute").filter(pk=value_id).first()
    if instance is None:
        logger.debug("Skipping sensorsearch save handling because value %s no longer exists", value_id)
        return
    if getattr(instance, "snapshot_id", None) is not None:
        return
    if instance.project is None or instance.project.catalog is None or instance.attribute is None:
        return
    if not is_relevant_attribute(instance.project.catalog.uri, instance.attribute.uri):
        return

    stages = _save_stages(instance, auth_token)
    with deduplicate_json_requests():
        _run_stages("save", value_id, instance.project_id, stages)


@measure_phase("callback.delete.executed")
def handle_value_deleted(context: DeletedValueContext) -> None:
    project = Project.objects.select_related("catalog").filter(pk=context.project_id).first()
    if project is None or project.catalog is None:
        logger.debug(
            "Skipping sensorsearch delete handling because project %s no longer exists",
            context.project_id,
        )
        return
    if not is_relevant_attribute(project.catalog.uri, context.attribute_uri):
        return
    attribute = Attribute.objects.filter(pk=context.attribute_id).first()

    stages = (
        ("configuration-tab", lambda: _sync_configuration_tab_after_delete(context, project)),
        ("selected-device-details", lambda: _sync_selected_device_details_after_delete(context, project, attribute)),
        ("metadata-source-state", lambda: _clear_metadata_source_state_after_delete(context, project)),
        ("metadata-input-state", lambda: _clear_metadata_input_state_after_delete(context, project)),
        (
            "orphaned-device-details",
            lambda: _remove_orphaned_device_details(project, context.attribute_uri, context.catalog_uri),
        ),
        ("data-collection-variables", lambda: _sync_data_collection_variables_after_delete(context, project)),
    )
    _run_stages("delete", context.value_id, context.project_id, stages)


@workflow_catalog_context()
def _run_stages(
    event: str,
    value_id: int | None,
    project_id: int,
    stages: Iterable[tuple[str, Callable[[], object]]],
) -> None:
    event_started = perf_counter()
    for stage_name, stage in stages:
        stage_started = perf_counter()
        try:
            with measure_phase(f"stage.{event}.{stage_name}"):
                stage()
        except Exception:
            logger.exception(
                "Sensorsearch %s stage %s failed for value=%s project=%s",
                event,
                stage_name,
                value_id,
                project_id,
            )
        finally:
            logger.debug(
                "Sensorsearch %s stage %s completed for value=%s project=%s duration_ms=%.1f",
                event,
                stage_name,
                value_id,
                project_id,
                (perf_counter() - stage_started) * 1000,
            )
    logger.debug(
        "Sensorsearch %s workflow completed for value=%s project=%s duration_ms=%.1f",
        event,
        value_id,
        project_id,
        (perf_counter() - event_started) * 1000,
    )


def _save_stages(instance: Value, auth_token: str | None) -> tuple[tuple[str, Callable[[], object]], ...]:
    catalog_uri = instance.project.catalog.uri
    attribute_uri = instance.attribute.uri
    bindings = get_handler_bindings_for_catalog(catalog_uri)
    stages: list[tuple[str, Callable[[], object]]] = []

    if any(candidate.search_attribute_uri == attribute_uri for candidate in bindings):
        stages.append(("backend-value", lambda: sync_backend_value_after_save(instance, auth_token=auth_token)))

    configuration_bindings = {
        (candidate.search_attribute_uri, collection_attribute_uri)
        for candidate in bindings
        if (
            collection_attribute_uri := getattr(
                candidate.handler,
                "configuration_collection_attribute_uri",
                None,
            )
        )
    }
    if any(attribute_uri in binding for binding in configuration_bindings):
        stages.append(("configuration-tab", lambda: _sync_configuration_tab_after_save(instance)))

    if any(attribute_uri == getattr(candidate.handler, "selected_devices_attribute_uri", None) for candidate in bindings):
        stages.append(("selected-device-details", lambda: _sync_selected_device_details_after_save(instance, auth_token)))

    variable_settings = get_data_collection_variable_sync_settings(catalog_uri)
    if variable_settings is not None and attribute_uri == variable_settings.devices_attribute_uri:
        stages.append(("data-collection-variables", lambda: _sync_data_collection_variables_after_save(instance)))

    if get_refresh_action(catalog_uri, attribute_uri) is not None:
        stages.append(("metadata-refresh", lambda: run_metadata_refresh_action(instance, auth_token=auth_token)))

    if (not instance.external_id and instance.is_empty) and get_refresh_actions_for_source(catalog_uri, attribute_uri):
        stages.append(("metadata-source-state", lambda: _clear_metadata_source_state_after_save(instance)))

    if get_refresh_actions_for_input(catalog_uri, attribute_uri):
        stages.append(("metadata-input-state", lambda: _clear_metadata_input_state_after_save(instance)))

    if any(
        candidate.search_attribute_uri == attribute_uri and getattr(candidate.handler, "device_collection_attribute_uri", None)
        for candidate in bindings
    ):
        stages.append(
            (
                "orphaned-device-details",
                lambda: _remove_orphaned_device_details(instance.project, attribute_uri),
            )
        )

    return tuple(stages)


def _configuration_tab_bindings(catalog_uri: str) -> set[tuple[str, str]]:
    return {
        (candidate.search_attribute_uri, collection_attribute_uri)
        for candidate in get_handler_bindings_for_catalog(catalog_uri)
        if (
            collection_attribute_uri := getattr(
                candidate.handler,
                "configuration_collection_attribute_uri",
                None,
            )
        )
    }


def _sync_configuration_tab_after_save(instance: Value) -> None:
    attribute_uri = instance.attribute.uri
    for source_attribute_uri, collection_attribute_uri in _configuration_tab_bindings(instance.project.catalog.uri):
        if attribute_uri == source_attribute_uri:
            sync_configuration_tab_from_source(
                source_value=instance,
                collection_attribute_uri=collection_attribute_uri,
                clear=not instance.external_id or instance.is_empty,
            )
        elif attribute_uri == collection_attribute_uri and instance.set_collection is True:
            sync_configuration_tab_from_root(
                root_value=instance,
                source_attribute_uri=source_attribute_uri,
            )


def _sync_configuration_tab_after_delete(context: DeletedValueContext, project: Project) -> None:
    for source_attribute_uri, collection_attribute_uri in _configuration_tab_bindings(context.catalog_uri):
        if context.attribute_uri == source_attribute_uri:
            clear_configuration_tab_from_deleted_source(
                project=project,
                set_prefix=context.set_prefix,
                set_index=context.set_index,
                collection_attribute_uri=collection_attribute_uri,
            )


def _sync_selected_device_details_after_save(instance: Value, auth_token: str | None) -> None:
    for candidate in get_handler_bindings_for_catalog(instance.project.catalog.uri):
        selected_devices_attribute_uri = getattr(candidate.handler, "selected_devices_attribute_uri", None)
        selected_devices_page_uri = getattr(candidate.handler, "selected_devices_page_uri", None)
        device_collection_attribute_uri = getattr(candidate.handler, "device_collection_attribute_uri", None)
        if not selected_devices_attribute_uri or not selected_devices_page_uri or not device_collection_attribute_uri:
            continue
        if instance.attribute.uri != selected_devices_attribute_uri:
            continue

        binding, scope = _selected_device_binding_and_scope(
            project=instance.project,
            attribute=instance.attribute,
            value=instance,
            selected_devices_page_uri=selected_devices_page_uri,
        )
        if binding is None or scope is None:
            return
        if _has_meaningful_collection_values(binding.opposite_values_for_scope(scope)):
            _log_inactive_selected_device_layout(instance.project_id, scope, binding)
            return

        selected_values = get_selected_device_values_for_configuration_scope(
            binding=binding,
            scope_prefix=scope.set_prefix,
            source_set_index=scope.set_index,
        )
        reconcile_device_details_from_selected_values(
            project=instance.project,
            catalog=instance.project.catalog,
            scope_prefix=scope.set_prefix,
            source_set_index=scope.set_index,
            selected_values=selected_values,
            selected_devices_attribute_uri=selected_devices_attribute_uri,
            device_collection_attribute_uri=device_collection_attribute_uri,
            configuration_search_attribute_uri=candidate.search_attribute_uri,
            auth_token=auth_token,
        )
        return


def _sync_selected_device_details_after_delete(
    context: DeletedValueContext,
    project: Project,
    attribute: Attribute | None,
) -> None:
    if attribute is None:
        return
    for candidate in get_handler_bindings_for_catalog(context.catalog_uri):
        selected_devices_attribute_uri = getattr(candidate.handler, "selected_devices_attribute_uri", None)
        selected_devices_page_uri = getattr(candidate.handler, "selected_devices_page_uri", None)
        device_collection_attribute_uri = getattr(candidate.handler, "device_collection_attribute_uri", None)
        if not selected_devices_attribute_uri or not selected_devices_page_uri or not device_collection_attribute_uri:
            continue
        if context.attribute_uri != selected_devices_attribute_uri:
            continue

        binding, scope = _selected_device_binding_and_scope(
            project=project,
            attribute=attribute,
            value=context,
            selected_devices_page_uri=selected_devices_page_uri,
        )
        if binding is None or scope is None:
            return
        if _has_meaningful_collection_values(binding.opposite_values_for_scope(scope)):
            _log_inactive_selected_device_layout(context.project_id, scope, binding)
            return

        remaining_values = get_selected_device_values_for_configuration_scope(
            binding=binding,
            scope_prefix=scope.set_prefix,
            source_set_index=scope.set_index,
        )
        if any(value.external_id == context.external_id for value in remaining_values):
            return
        remove_device_detail_block_for_selected_device(
            project=project,
            catalog=project.catalog,
            scope_prefix=scope.set_prefix,
            source_set_index=scope.set_index,
            device_external_id=context.external_id,
            device_collection_attribute_uri=device_collection_attribute_uri,
            configuration_search_attribute_uri=candidate.search_attribute_uri,
        )
        return


def _selected_device_binding_and_scope(
    *,
    project: Project,
    attribute: Attribute,
    value,
    selected_devices_page_uri: str,
) -> tuple[CollectionBinding | None, CollectionScope | None]:
    try:
        binding = CollectionBinding.resolve(project, attribute, selected_devices_page_uri)
        scope_prefix, source_set_index = get_configuration_scope_for_value(value, binding)
    except CollectionBindingError as error:
        logger.warning("Cannot synchronize selected devices: %s", error)
        return None, None
    return binding, CollectionScope(set_prefix=scope_prefix, set_index=source_set_index)


def _has_meaningful_collection_values(queryset) -> bool:
    return queryset.filter(~Q(text__exact="") | ~Q(external_id__exact="") | Q(option__isnull=False) | ~Q(file__exact="")).exists()


def _log_inactive_selected_device_layout(
    project_id: int,
    scope: CollectionScope,
    binding: CollectionBinding,
) -> None:
    logger.warning(
        "Skipping selected-device synchronization for project %s, set_prefix=%r, set_index=%s because "
        "inactive %s layout values still exist. Refresh the configuration to normalize its selected devices.",
        project_id,
        scope.set_prefix,
        scope.set_index,
        binding.opposite_layout.value,
    )


def _sync_data_collection_variables_after_save(instance: Value) -> None:
    settings = get_data_collection_variable_sync_settings(instance.project.catalog.uri)
    if settings is None or instance.attribute.uri != settings.devices_attribute_uri:
        return
    reconcile_data_collection_variables_for_selected_device(instance, settings)


def _sync_data_collection_variables_after_delete(context: DeletedValueContext, project: Project) -> None:
    settings = get_data_collection_variable_sync_settings(context.catalog_uri)
    if settings is None or context.attribute_uri != settings.devices_attribute_uri:
        return
    remove_stale_generated_data_collection_variables_for_deleted_device(
        project=project,
        attribute_uri=context.attribute_uri,
        set_prefix=context.set_prefix,
        set_index=context.set_index,
        external_id=context.external_id,
        settings=settings,
    )


def _clear_metadata_source_state_after_save(instance: Value) -> None:
    if instance.external_id or not instance.is_empty:
        return
    actions = get_refresh_actions_for_source(instance.project.catalog.uri, instance.attribute.uri)
    if actions:
        clear_refresh_state_for_source(instance, actions)


def _clear_metadata_source_state_after_delete(context: DeletedValueContext, project: Project) -> None:
    actions = get_refresh_actions_for_source(context.catalog_uri, context.attribute_uri)
    if actions:
        _clear_refresh_state_for_deleted_value(context, project, actions)


def _clear_metadata_input_state_after_save(instance: Value) -> None:
    actions = get_refresh_actions_for_input(instance.project.catalog.uri, instance.attribute.uri)
    if actions:
        clear_refresh_state_for_source(instance, actions)


def _clear_metadata_input_state_after_delete(context: DeletedValueContext, project: Project) -> None:
    actions = get_refresh_actions_for_input(context.catalog_uri, context.attribute_uri)
    if actions:
        _clear_refresh_state_for_deleted_value(context, project, actions)


def _clear_refresh_state_for_deleted_value(context, project, actions) -> None:
    clear_refresh_state(
        project=project,
        source_attribute_uri=context.attribute_uri,
        set_prefix=context.set_prefix,
        set_index=context.set_index,
        actions=actions,
    )


def _remove_orphaned_device_details(
    project: Project,
    attribute_uri: str,
    catalog_uri: str | None = None,
) -> None:
    source_uris_by_device_collection: dict[str, set[str]] = {}
    affected_device_collections = set()
    for candidate in get_handler_bindings_for_catalog(catalog_uri or project.catalog.uri):
        selected_devices_attribute_uri = getattr(candidate.handler, "selected_devices_attribute_uri", None)
        device_collection_attribute_uri = getattr(candidate.handler, "device_collection_attribute_uri", None)
        if not selected_devices_attribute_uri or not device_collection_attribute_uri:
            continue

        source_uris_by_device_collection.setdefault(device_collection_attribute_uri, set()).add(candidate.search_attribute_uri)
        if candidate.search_attribute_uri == attribute_uri:
            affected_device_collections.add(device_collection_attribute_uri)

    for device_collection_attribute_uri in affected_device_collections:
        remove_orphaned_device_detail_blocks(
            project=project,
            catalog=project.catalog,
            configuration_search_attribute_uris=tuple(sorted(source_uris_by_device_collection[device_collection_attribute_uri])),
            device_collection_attribute_uri=device_collection_attribute_uri,
        )
