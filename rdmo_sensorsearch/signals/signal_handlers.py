import logging

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from rdmo.projects.models import Value

from rdmo_sensorsearch.signals.data_collection_variable_sync import (
    DATA_COLLECTION_DEVICES_ATTRIBUTE_URI,
    remove_stale_data_collection_variables,
    sync_data_collection_variables_from_device_value,
)
from rdmo_sensorsearch.signals.device_set_sync import sync_device_detail_blocks_from_values
from rdmo_sensorsearch.signals.handler_post_save import handle_post_save
from rdmo_sensorsearch.signals.handler_post_save import _get_handler_candidates
from rdmo_sensorsearch.signals.utils import _is_muted

logger = logging.getLogger(__name__)


def _is_snapshot_value(instance) -> bool:
    return getattr(instance, "snapshot_id", None) is not None


@receiver(post_save, sender=Value)
def post_save_project_values(sender, instance, **kwargs):
    if _is_muted():
        return
    if instance is None:
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch post_save handling for snapshot value %s", instance.pk)
        return

    def handle_value_after_commit():
        logger.debug("Triggering post_save_project_values")
        handle_post_save(instance)

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

        def sync_selected_devices():
            selected_values = (
                Value.objects.filter(
                    project=instance.project,
                    snapshot=None,
                    attribute__uri=selected_devices_attribute_uri,
                    set_collection=True,
                    set_prefix=instance.set_prefix or "",
                    set_index=instance.set_index,
                )
                .exclude(external_id__isnull=True)
                .exclude(external_id__exact="")
                .order_by("collection_index", "id")
            )
            sync_device_detail_blocks_from_values(
                instance,
                selected_values,
                selected_devices_attribute_uri=selected_devices_attribute_uri,
                device_collection_attribute_uri=device_collection_attribute_uri,
                configuration_search_attribute_uri=candidate.auto_complete_field_uri,
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
