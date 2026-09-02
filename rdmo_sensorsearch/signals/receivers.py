"""Django signal adapters for committed RDMO Value synchronization."""

import logging
from functools import partial

from django.db import transaction
from django.db.models import QuerySet
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from rdmo.projects.models import Project, Value

from rdmo_sensorsearch.auth import get_sms_auth_token
from rdmo_sensorsearch.services.synchronization_context import is_value_sync_muted
from rdmo_sensorsearch.workflows.value_events import (
    DeletedValueContext,
    handle_value_deleted,
    handle_value_saved,
)

logger = logging.getLogger(__name__)


def _is_snapshot_value(instance: Value) -> bool:
    return getattr(instance, "snapshot_id", None) is not None


def _is_project_delete(origin: object) -> bool:
    return isinstance(origin, Project) or (isinstance(origin, QuerySet) and origin.model is Project)


@receiver(
    post_save,
    sender=Value,
    dispatch_uid="rdmo_sensorsearch.value.post_save",
)
def value_saved(sender, instance, *, raw, **kwargs):
    if raw or is_value_sync_muted() or instance is None:
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch post_save handling for snapshot value %s", instance.pk)
        return

    auth_token = get_sms_auth_token()
    transaction.on_commit(
        partial(
            handle_value_saved,
            value_id=instance.pk,
            auth_token=auth_token,
        ),
        robust=True,
    )


@receiver(
    post_delete,
    sender=Value,
    dispatch_uid="rdmo_sensorsearch.value.post_delete",
)
def value_deleted(sender, instance, **kwargs):
    if is_value_sync_muted() or instance is None:
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch post_delete handling for snapshot value %s", instance.pk)
        return
    if _is_project_delete(kwargs.get("origin")):
        logger.debug("Skipping sensorsearch post_delete handling during project deletion for value %s", instance.pk)
        return

    context = DeletedValueContext.from_value(instance)
    if context is None:
        return
    transaction.on_commit(
        partial(handle_value_deleted, context=context),
        robust=True,
    )
