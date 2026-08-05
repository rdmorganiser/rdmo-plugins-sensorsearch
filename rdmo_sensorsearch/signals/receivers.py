import logging
from functools import partial

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from rdmo.projects.models import Value

from rdmo_sensorsearch.auth import get_sms_auth_token
from rdmo_sensorsearch.handlers.catalog_registry import get_handler_bindings_for_catalog
from rdmo_sensorsearch.persistence.collection_binding import (
    CollectionBinding,
    CollectionBindingError,
    CollectionScope,
)
from rdmo_sensorsearch.services.synchronization_context import is_value_post_save_muted
from rdmo_sensorsearch.signals.backend_value_sync import sync_backend_value_after_save
from rdmo_sensorsearch.signals.configuration_tab_sync import (
    sync_configuration_tab_from_root,
    sync_configuration_tab_from_source,
)
from rdmo_sensorsearch.signals.data_collection_variable_sync import (
    get_data_collection_variable_sync_settings,
    reconcile_data_collection_variables_for_selected_device,
    remove_stale_generated_data_collection_variables,
)
from rdmo_sensorsearch.signals.metadata_refresh import (
    clear_refresh_state_for_source,
    get_refresh_action,
    get_refresh_actions_for_input,
    get_refresh_actions_for_source,
    run_metadata_refresh_action,
)
from rdmo_sensorsearch.workflows.device_details import (
    get_configuration_scope_for_value,
    get_selected_device_values_for_configuration_scope,
    reconcile_device_details_from_selected_values,
    remove_device_detail_block_for_selected_device,
    remove_orphaned_device_detail_blocks,
)

logger = logging.getLogger(__name__)


def _is_snapshot_value(instance) -> bool:
    return getattr(instance, "snapshot_id", None) is not None


def _schedule_orphaned_device_block_cleanup(instance) -> None:
    source_uris_by_device_collection = {}
    affected_device_collections = set()
    for candidate in get_handler_bindings_for_catalog(instance.project.catalog.uri):
        handler = candidate.handler
        selected_devices_attribute_uri = getattr(handler, "selected_devices_attribute_uri", None)
        device_collection_attribute_uri = getattr(handler, "device_collection_attribute_uri", None)
        if not selected_devices_attribute_uri or not device_collection_attribute_uri:
            continue

        source_uris_by_device_collection.setdefault(device_collection_attribute_uri, set()).add(candidate.search_attribute_uri)
        if candidate.search_attribute_uri == instance.attribute.uri:
            affected_device_collections.add(device_collection_attribute_uri)

    for device_collection_attribute_uri in affected_device_collections:
        transaction.on_commit(
            partial(
                remove_orphaned_device_detail_blocks,
                project=instance.project,
                catalog=instance.project.catalog,
                configuration_search_attribute_uris=tuple(
                    sorted(source_uris_by_device_collection[device_collection_attribute_uri])
                ),
                device_collection_attribute_uri=device_collection_attribute_uri,
            )
        )


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


@receiver(post_save, sender=Value)
def sync_backend_value_on_save(sender, instance, **kwargs):
    if is_value_post_save_muted():
        return
    if instance is None:
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch post_save handling for snapshot value %s", instance.pk)
        return

    auth_token = get_sms_auth_token()

    def handle_value_after_commit():
        logger.debug("Synchronizing saved backend value")
        sync_backend_value_after_save(instance, auth_token=auth_token)

    transaction.on_commit(handle_value_after_commit)


@receiver(post_save, sender=Value)
@receiver(post_delete, sender=Value)
def sync_configuration_tab_labels(sender, instance, **kwargs):
    if is_value_post_save_muted() or _is_snapshot_value(instance):
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return

    signal = kwargs.get("signal")
    attribute_uri = instance.attribute.uri
    for source_attribute_uri, collection_attribute_uri in _configuration_tab_bindings(instance.project.catalog.uri):
        if attribute_uri == source_attribute_uri:
            clear = signal is post_delete or not instance.external_id or getattr(instance, "is_empty", False)
            transaction.on_commit(
                partial(
                    sync_configuration_tab_from_source,
                    source_value=instance,
                    collection_attribute_uri=collection_attribute_uri,
                    clear=clear,
                )
            )
        elif signal is post_save and attribute_uri == collection_attribute_uri and instance.set_collection is True:
            transaction.on_commit(
                partial(
                    sync_configuration_tab_from_root,
                    root_value=instance,
                    source_attribute_uri=source_attribute_uri,
                )
            )


@receiver(post_save, sender=Value)
@receiver(post_delete, sender=Value)
def sync_device_details_from_selected_devices(sender, instance, **kwargs):
    if is_value_post_save_muted():
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch selected-device sync for snapshot value %s", instance.pk)
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return

    catalog_uri = instance.project.catalog.uri
    for candidate in get_handler_bindings_for_catalog(catalog_uri):
        selected_devices_attribute_uri = getattr(candidate.handler, "selected_devices_attribute_uri", None)
        selected_devices_page_uri = getattr(candidate.handler, "selected_devices_page_uri", None)
        device_collection_attribute_uri = getattr(candidate.handler, "device_collection_attribute_uri", None)
        if not selected_devices_attribute_uri or not selected_devices_page_uri or not device_collection_attribute_uri:
            continue

        if instance.attribute.uri != selected_devices_attribute_uri:
            continue

        try:
            binding = CollectionBinding.resolve(instance.project, instance.attribute, selected_devices_page_uri)
            scope_prefix, source_set_index = get_configuration_scope_for_value(instance, binding)
        except CollectionBindingError as error:
            logger.warning("Cannot synchronize selected devices: %s", error)
            return

        inactive_values = binding.opposite_values_for_scope(CollectionScope(set_prefix=scope_prefix, set_index=source_set_index))
        if _has_meaningful_collection_values(inactive_values):
            logger.warning(
                "Skipping selected-device synchronization for project %s, set_prefix=%r, set_index=%s because "
                "inactive %s layout values still exist. Refresh the configuration to normalize its selected devices.",
                instance.project_id,
                scope_prefix,
                source_set_index,
                binding.opposite_layout.value,
            )
            return

        configuration_search_attribute_uri = candidate.search_attribute_uri

        if kwargs.get("signal") is post_delete:
            remaining_values = get_selected_device_values_for_configuration_scope(
                binding=binding,
                scope_prefix=scope_prefix,
                source_set_index=source_set_index,
            )
            if any(value.external_id == instance.external_id for value in remaining_values):
                break
            transaction.on_commit(
                partial(
                    remove_device_detail_block_for_selected_device,
                    project=instance.project,
                    catalog=instance.project.catalog,
                    scope_prefix=scope_prefix,
                    source_set_index=source_set_index,
                    device_external_id=instance.external_id or "",
                    device_collection_attribute_uri=device_collection_attribute_uri,
                    configuration_search_attribute_uri=configuration_search_attribute_uri,
                )
            )
            break

        auth_token = get_sms_auth_token()

        def sync_selected_devices(
            binding=binding,
            scope_prefix=scope_prefix,
            source_set_index=source_set_index,
            selected_devices_attribute_uri=selected_devices_attribute_uri,
            device_collection_attribute_uri=device_collection_attribute_uri,
            configuration_search_attribute_uri=configuration_search_attribute_uri,
            auth_token=auth_token,
        ):
            selected_values = get_selected_device_values_for_configuration_scope(
                binding=binding,
                scope_prefix=scope_prefix,
                source_set_index=source_set_index,
            )
            reconcile_device_details_from_selected_values(
                project=instance.project,
                catalog=instance.project.catalog,
                scope_prefix=scope_prefix,
                source_set_index=source_set_index,
                selected_values=selected_values,
                selected_devices_attribute_uri=selected_devices_attribute_uri,
                device_collection_attribute_uri=device_collection_attribute_uri,
                configuration_search_attribute_uri=configuration_search_attribute_uri,
                auth_token=auth_token,
            )

        transaction.on_commit(sync_selected_devices)
        break


def _has_meaningful_collection_values(queryset) -> bool:
    return (
        queryset.exclude(text__exact="").exists()
        or queryset.exclude(external_id__exact="").exists()
        or queryset.filter(option__isnull=False).exists()
        or queryset.exclude(file__exact="").exists()
    )


@receiver(post_save, sender=Value)
def sync_data_collection_variables_from_selected_device(sender, instance, **kwargs):
    if is_value_post_save_muted():
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch data collection variable sync for snapshot value %s", instance.pk)
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return
    sync_settings = get_data_collection_variable_sync_settings(instance.project.catalog.uri)
    if sync_settings is None or instance.attribute.uri != sync_settings.devices_attribute_uri:
        return

    transaction.on_commit(lambda: reconcile_data_collection_variables_for_selected_device(instance, sync_settings))


@receiver(post_save, sender=Value)
def refresh_metadata_from_trigger(sender, instance, **kwargs):
    if is_value_post_save_muted():
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch metadata refresh for snapshot value %s", instance.pk)
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return
    if get_refresh_action(instance.project.catalog.uri, instance.attribute.uri) is None:
        return

    auth_token = get_sms_auth_token()
    transaction.on_commit(lambda: run_metadata_refresh_action(instance, auth_token=auth_token))


@receiver(post_save, sender=Value)
def clear_metadata_refresh_state_from_cleared_source(sender, instance, **kwargs):
    if is_value_post_save_muted() or _is_snapshot_value(instance):
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return
    if instance.external_id or not getattr(instance, "is_empty", False):
        return

    actions = get_refresh_actions_for_source(instance.project.catalog.uri, instance.attribute.uri)
    if actions:
        transaction.on_commit(lambda: clear_refresh_state_for_source(instance, actions))


@receiver(post_delete, sender=Value)
def clear_metadata_refresh_state_from_deleted_source(sender, instance, **kwargs):
    if is_value_post_save_muted() or _is_snapshot_value(instance):
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return

    actions = get_refresh_actions_for_source(instance.project.catalog.uri, instance.attribute.uri)
    if actions:
        transaction.on_commit(lambda: clear_refresh_state_for_source(instance, actions))


@receiver(post_save, sender=Value)
@receiver(post_delete, sender=Value)
def clear_metadata_refresh_state_from_changed_input(sender, instance, **kwargs):
    if is_value_post_save_muted() or _is_snapshot_value(instance):
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return

    actions = get_refresh_actions_for_input(instance.project.catalog.uri, instance.attribute.uri)
    if actions:
        transaction.on_commit(lambda: clear_refresh_state_for_source(instance, actions))


@receiver(post_save, sender=Value)
def reconcile_device_blocks_from_saved_configuration(sender, instance, **kwargs):
    if is_value_post_save_muted() or _is_snapshot_value(instance):
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return

    _schedule_orphaned_device_block_cleanup(instance)


@receiver(post_delete, sender=Value)
def remove_orphaned_device_blocks_from_deleted_configuration(sender, instance, **kwargs):
    if is_value_post_save_muted() or _is_snapshot_value(instance):
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return

    _schedule_orphaned_device_block_cleanup(instance)


@receiver(post_delete, sender=Value)
def remove_data_collection_variables_from_deleted_device(sender, instance, **kwargs):
    if is_value_post_save_muted():
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch data collection variable cleanup for snapshot value %s", instance.pk)
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return
    sync_settings = get_data_collection_variable_sync_settings(instance.project.catalog.uri)
    if sync_settings is None or instance.attribute.uri != sync_settings.devices_attribute_uri:
        return

    transaction.on_commit(lambda: remove_stale_generated_data_collection_variables(instance, sync_settings))
