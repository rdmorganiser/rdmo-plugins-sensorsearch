import logging
from functools import partial

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from rdmo.projects.models import Value

from rdmo_sensorsearch.auth import get_sms_auth_token
from rdmo_sensorsearch.signals.data_collection_variable_sync import (
    DATA_COLLECTION_DEVICES_ATTRIBUTE_URI,
    remove_stale_data_collection_variables,
    sync_data_collection_variables_from_device_value,
)
from rdmo_sensorsearch.signals.device_set_sync import (
    get_configuration_scope_for_value,
    get_selected_device_values_for_configuration_scope,
    remove_orphaned_device_detail_blocks,
    sync_device_detail_blocks_from_configuration_values,
)
from rdmo_sensorsearch.signals.handler_post_save import _get_handler_candidates, handle_post_save
from rdmo_sensorsearch.signals.metadata_refresh import (
    clear_refresh_state_for_source,
    get_refresh_action,
    get_refresh_actions_for_source,
    handle_metadata_refresh_value,
)
from rdmo_sensorsearch.signals.utils import _is_muted

logger = logging.getLogger(__name__)


def _is_snapshot_value(instance) -> bool:
    return getattr(instance, "snapshot_id", None) is not None


def _schedule_orphaned_device_block_cleanup(instance) -> None:
    source_uris_by_device_collection = {}
    affected_device_collections = set()
    for candidate in _get_handler_candidates(instance.project.catalog.uri):
        handler = candidate.handler
        member_sensors_attribute_uri = getattr(handler, "member_sensors_attribute_uri", None)
        device_collection_attribute_uri = getattr(handler, "device_collection_attribute_uri", None)
        if not member_sensors_attribute_uri or not device_collection_attribute_uri:
            continue

        source_uris_by_device_collection.setdefault(device_collection_attribute_uri, set()).add(candidate.auto_complete_field_uri)
        if candidate.auto_complete_field_uri == instance.attribute.uri:
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


@receiver(post_save, sender=Value)
def post_save_project_values(sender, instance, **kwargs):
    if _is_muted():
        return
    if instance is None:
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch post_save handling for snapshot value %s", instance.pk)
        return

    auth_token = get_sms_auth_token()

    def handle_value_after_commit():
        logger.debug("Triggering post_save_project_values")
        handle_post_save(instance, auth_token=auth_token)

    transaction.on_commit(handle_value_after_commit)


@receiver(post_save, sender=Value)
@receiver(post_delete, sender=Value)
def sync_device_details_from_selected_devices(sender, instance, **kwargs):
    if _is_muted():
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch selected-device sync for snapshot value %s", instance.pk)
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return

    catalog_uri = instance.project.catalog.uri
    for candidate in _get_handler_candidates(catalog_uri):
        selected_devices_attribute_uri = getattr(candidate.handler, "member_sensors_attribute_uri", None)
        device_collection_attribute_uri = getattr(candidate.handler, "device_collection_attribute_uri", None)
        if not selected_devices_attribute_uri or not device_collection_attribute_uri:
            continue

        if instance.attribute.uri != selected_devices_attribute_uri:
            continue

        configuration_search_attribute_uri = candidate.auto_complete_field_uri

        auth_token = get_sms_auth_token()

        def sync_selected_devices(
            selected_devices_attribute_uri=selected_devices_attribute_uri,
            device_collection_attribute_uri=device_collection_attribute_uri,
            configuration_search_attribute_uri=configuration_search_attribute_uri,
            auth_token=auth_token,
        ):
            scope_prefix, source_set_index = get_configuration_scope_for_value(instance)
            selected_values = get_selected_device_values_for_configuration_scope(
                project=instance.project,
                selected_devices_attribute_uri=selected_devices_attribute_uri,
                scope_prefix=scope_prefix,
                source_set_index=source_set_index,
            )
            sync_device_detail_blocks_from_configuration_values(
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


@receiver(post_save, sender=Value)
def sync_data_collection_variables_from_selected_device(sender, instance, **kwargs):
    if _is_muted():
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch data collection variable sync for snapshot value %s", instance.pk)
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return
    if instance.attribute.uri != DATA_COLLECTION_DEVICES_ATTRIBUTE_URI:
        return

    transaction.on_commit(lambda: sync_data_collection_variables_from_device_value(instance))


@receiver(post_save, sender=Value)
def refresh_metadata_from_trigger(sender, instance, **kwargs):
    if _is_muted():
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch metadata refresh for snapshot value %s", instance.pk)
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return
    if get_refresh_action(instance.project.catalog.uri, instance.attribute.uri) is None:
        return

    auth_token = get_sms_auth_token()
    transaction.on_commit(lambda: handle_metadata_refresh_value(instance, auth_token=auth_token))


@receiver(post_save, sender=Value)
def clear_metadata_refresh_state_from_cleared_source(sender, instance, **kwargs):
    if _is_muted() or _is_snapshot_value(instance):
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
    if _is_muted() or _is_snapshot_value(instance):
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return

    actions = get_refresh_actions_for_source(instance.project.catalog.uri, instance.attribute.uri)
    if actions:
        transaction.on_commit(lambda: clear_refresh_state_for_source(instance, actions))


@receiver(post_save, sender=Value)
def reconcile_device_blocks_from_saved_configuration(sender, instance, **kwargs):
    if _is_muted() or _is_snapshot_value(instance):
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return

    _schedule_orphaned_device_block_cleanup(instance)


@receiver(post_delete, sender=Value)
def remove_orphaned_device_blocks_from_deleted_configuration(sender, instance, **kwargs):
    if _is_muted() or _is_snapshot_value(instance):
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return

    _schedule_orphaned_device_block_cleanup(instance)


@receiver(post_delete, sender=Value)
def remove_data_collection_variables_from_deleted_device(sender, instance, **kwargs):
    if _is_muted():
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch data collection variable cleanup for snapshot value %s", instance.pk)
        return
    if instance is None or instance.project is None or instance.attribute is None or instance.project.catalog is None:
        return
    if instance.attribute.uri != DATA_COLLECTION_DEVICES_ATTRIBUTE_URI:
        return

    transaction.on_commit(lambda: remove_stale_data_collection_variables(instance))
