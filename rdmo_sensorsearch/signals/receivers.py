"""Django signal adapters for committed RDMO Value synchronization."""

import logging
from functools import partial

from django.db import transaction
from django.db.models import QuerySet
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from rdmo.projects.models import Project, Value

from rdmo_sensorsearch.auth import get_sms_auth_token
from rdmo_sensorsearch.services.performance import count_event, measure_phase
from rdmo_sensorsearch.services.synchronization_context import is_value_sync_muted
from rdmo_sensorsearch.workflows.event_routing import route_value
from rdmo_sensorsearch.workflows.value_events import (
    DeletedValueContext,
    handle_value_deleted,
    handle_value_saved,
)

logger = logging.getLogger(__name__)
_ROUTING_UNAVAILABLE = object()


def _route_value(instance):
    try:
        return route_value(instance)
    except Exception:
        # Routing used to run only inside a robust commit callback. A broken
        # configuration must not turn the new early gate into a failed save.
        logger.exception("Sensorsearch early routing failed; retaining commit-time handling")
        return _ROUTING_UNAVAILABLE


def _is_snapshot_value(instance: Value) -> bool:
    return getattr(instance, "snapshot_id", None) is not None


def _is_project_delete(origin: object) -> bool:
    return isinstance(origin, Project) or (isinstance(origin, QuerySet) and origin.model is Project)


@receiver(
    post_save,
    sender=Value,
    dispatch_uid="rdmo_sensorsearch.value.post_save",
)
@measure_phase("signal.save")
def value_saved(sender, instance, *, raw, **kwargs):
    count_event("value.created" if kwargs.get("created") else "value.saved")
    if raw or is_value_sync_muted() or instance is None:
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch post_save handling for snapshot value %s", instance.pk)
        return

    if _route_value(instance) is None:
        return
    count_event("signal.save.relevant")
    with measure_phase("auth"):
        auth_token = get_sms_auth_token()
    count_event("callback.save.scheduled")
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
@measure_phase("signal.delete")
def value_deleted(sender, instance, **kwargs):
    count_event("value.deleted")
    if is_value_sync_muted() or instance is None:
        return
    if _is_snapshot_value(instance):
        logger.debug("Skipping sensorsearch post_delete handling for snapshot value %s", instance.pk)
        return
    if _is_project_delete(kwargs.get("origin")):
        logger.debug("Skipping sensorsearch post_delete handling during project deletion for value %s", instance.pk)
        return

    routing = _route_value(instance)
    if routing is None:
        return
    count_event("signal.delete.relevant")
    context = DeletedValueContext.from_value(instance, routing=None if routing is _ROUTING_UNAVAILABLE else routing)
    if context is None:
        return
    count_event("callback.delete.scheduled")
    transaction.on_commit(
        partial(handle_value_deleted, context=context),
        robust=True,
    )
