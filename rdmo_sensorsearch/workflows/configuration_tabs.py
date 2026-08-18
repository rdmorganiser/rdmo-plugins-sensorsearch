"""Keep configuration collection labels aligned with their source values."""

import logging

from django.db import transaction

from rdmo.projects.models import Value

from rdmo_sensorsearch.naming import configuration_tab_label
from rdmo_sensorsearch.persistence.value_reconciliation import update_value_if_changed
from rdmo_sensorsearch.services.synchronization_context import mute_value_sync

logger = logging.getLogger(__name__)


def sync_configuration_tab_from_source(
    source_value: Value,
    collection_attribute_uri: str,
    clear: bool = False,
) -> bool:
    root_value = _configuration_root_value(
        project=source_value.project,
        set_prefix=source_value.set_prefix or "",
        set_index=source_value.set_index,
        collection_attribute_uri=collection_attribute_uri,
    )
    if root_value is None:
        logger.warning(
            "Configuration tab root not found for attribute %s (set_prefix=%r, set_index=%s)",
            collection_attribute_uri,
            source_value.set_prefix or "",
            source_value.set_index,
        )
        return False

    external_id = None if clear else source_value.external_id or None
    source_label = "" if clear else source_value.text or ""
    return _update_configuration_tab(root_value, external_id, source_label)


def clear_configuration_tab_from_deleted_source(
    *,
    project,
    set_prefix: str,
    set_index: int,
    collection_attribute_uri: str,
) -> bool:
    root_value = _configuration_root_value(
        project=project,
        set_prefix=set_prefix,
        set_index=set_index,
        collection_attribute_uri=collection_attribute_uri,
    )
    if root_value is None:
        logger.warning(
            "Configuration tab root not found for attribute %s (set_prefix=%r, set_index=%s)",
            collection_attribute_uri,
            set_prefix,
            set_index,
        )
        return False
    return _update_configuration_tab(root_value, None, "")


def sync_configuration_tab_from_root(
    root_value: Value,
    source_attribute_uri: str,
) -> bool:
    source_value = (
        Value.objects.filter(
            project=root_value.project,
            snapshot=None,
            attribute__uri=source_attribute_uri,
            set_prefix=root_value.set_prefix or "",
            set_index=root_value.set_index,
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id__exact="")
        .order_by("-id")
        .first()
    )
    if source_value is None:
        return False
    return _update_configuration_tab(
        root_value,
        source_value.external_id,
        source_value.text,
    )


def _configuration_root_value(
    *,
    project,
    set_prefix: str,
    set_index: int,
    collection_attribute_uri: str,
) -> Value | None:
    return (
        Value.objects.filter(
            project=project,
            snapshot=None,
            attribute__uri=collection_attribute_uri,
            set_prefix=set_prefix,
            set_index=set_index,
            set_collection=True,
        )
        .order_by("id")
        .first()
    )


def _update_configuration_tab(
    root_value: Value,
    configuration_external_id: str | None,
    source_label: str,
) -> bool:
    text = configuration_tab_label(
        root_value.text or "",
        configuration_external_id,
        source_label,
    )
    with transaction.atomic(), mute_value_sync():
        changed = update_value_if_changed(root_value, text=text)

    if changed:
        logger.info(
            "Updated configuration tab label at set_prefix=%r set_index=%s: %r",
            root_value.set_prefix or "",
            root_value.set_index,
            text,
        )
    return changed
