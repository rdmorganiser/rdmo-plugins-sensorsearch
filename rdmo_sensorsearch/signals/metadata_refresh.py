import logging
from collections.abc import Callable

from django.db import transaction
from django.utils import timezone

from rdmo.core.constants import VALUE_TYPE_BOOLEAN
from rdmo.projects.models import Value

from rdmo_sensorsearch.client import deduplicate_json_requests
from rdmo_sensorsearch.config import catalog_matches, load_config
from rdmo_sensorsearch.naming import canonical_configuration_label, canonical_device_label
from rdmo_sensorsearch.persistence.value_reconciliation import replace_scalar_value_in_scopes, update_value_if_changed
from rdmo_sensorsearch.services.synchronization_context import mute_value_post_save
from rdmo_sensorsearch.signals.backend_value_sync import refresh_value_from_backend
from rdmo_sensorsearch.signals.refresh_types import (
    RefreshAction,
    RefreshError,
    RefreshKind,
    RefreshResult,
    combine_refresh_results,
    format_refresh_message,
)

logger = logging.getLogger(__name__)


def get_refresh_action(catalog_uri: str, attribute_uri: str) -> RefreshAction | None:
    return next(
        (action for action in _get_refresh_actions(catalog_uri) if action.trigger_attribute_uri == attribute_uri),
        None,
    )


def get_refresh_actions_for_source(catalog_uri: str, attribute_uri: str) -> tuple[RefreshAction, ...]:
    return tuple(action for action in _get_refresh_actions(catalog_uri) if action.source_attribute_uri == attribute_uri)


def get_refresh_actions_for_input(catalog_uri: str, attribute_uri: str) -> tuple[RefreshAction, ...]:
    return tuple(action for action in _get_refresh_actions(catalog_uri) if attribute_uri in action.input_attribute_uris)


def _get_refresh_actions(catalog_uri: str) -> tuple[RefreshAction, ...]:
    refresh_config = load_config().get("MetadataRefresh", {})
    configuration_search_attribute_uri = refresh_config.get("configuration_search_attribute_uri", "")
    device_search_attribute_uri = refresh_config.get("device_search_attribute_uri", "")
    actions = []

    for action_config in refresh_config.get("actions", []):
        if not catalog_matches(action_config, catalog_uri):
            continue

        try:
            kind = RefreshKind(action_config["kind"])
        except (KeyError, ValueError):
            logger.error("Invalid metadata refresh action kind: %r", action_config.get("kind"))
            continue

        trigger_attribute_uri = action_config.get("trigger_attribute_uri", "")
        if not trigger_attribute_uri:
            logger.error("Metadata refresh action %s has no trigger attribute URI", kind.value)
            continue

        actions.append(
            RefreshAction(
                kind=kind,
                trigger_attribute_uri=trigger_attribute_uri,
                configuration_search_attribute_uri=action_config.get(
                    "configuration_search_attribute_uri",
                    configuration_search_attribute_uri,
                ),
                device_search_attribute_uri=action_config.get(
                    "device_search_attribute_uri",
                    device_search_attribute_uri,
                ),
                status_attribute_uri=action_config.get("status_attribute_uri"),
                message_attribute_uri=action_config.get("message_attribute_uri"),
                timestamp_attribute_uri=action_config.get("timestamp_attribute_uri"),
                replace_existing_collections=bool(action_config.get("replace_existing_collections", False)),
                require_configuration_period=bool(action_config.get("require_configuration_period", False)),
                input_attribute_uris=tuple(
                    attribute_uri
                    for attribute_uri in action_config.get("input_attribute_uris", [])
                    if isinstance(attribute_uri, str) and attribute_uri
                ),
            )
        )

    return tuple(actions)


def clear_refresh_state_for_source(instance: Value, actions: tuple[RefreshAction, ...]) -> None:
    attribute_uris = {attribute_uri for action in actions for attribute_uri in action.state_attribute_uris}
    if not attribute_uris:
        return

    scope = (instance.set_prefix or "", instance.set_index)
    with transaction.atomic(), mute_value_post_save():
        deleted, _ = Value.objects.filter(
            project=instance.project,
            snapshot=None,
            attribute__uri__in=attribute_uris,
            set_prefix=scope[0],
            set_index=scope[1],
        ).delete()

    if deleted:
        logger.info(
            "Cleared %s metadata refresh state value(s) for source %s (set_prefix=%s, set_index=%s)",
            deleted,
            instance.attribute.uri,
            scope[0],
            scope[1],
        )


def run_metadata_refresh_action(instance: Value, auth_token: str | None = None) -> None:
    if instance.project is None or instance.project.catalog is None or instance.attribute is None:
        return

    action = get_refresh_action(instance.project.catalog.uri, instance.attribute.uri)
    if action is None or not _is_active_trigger(instance):
        return

    refreshed_label = ""
    with deduplicate_json_requests():
        if (
            action.kind in {RefreshKind.CONFIGURATION, RefreshKind.ALL_CONFIGURATIONS}
            and not action.configuration_search_attribute_uri
        ):
            result = _failed_result(instance, "The configuration search attribute is not configured.")
        elif action.kind in {RefreshKind.DEVICE, RefreshKind.ALL_DEVICES} and not action.device_search_attribute_uri:
            result = _failed_result(instance, "The device search attribute is not configured.")
        elif action.kind is RefreshKind.CONFIGURATION:
            result, refreshed_label = _refresh_current_configuration(instance, action, auth_token=auth_token)
        elif action.kind is RefreshKind.DEVICE:
            result, refreshed_label = _refresh_current_device(instance, action, auth_token=auth_token)
        elif action.kind is RefreshKind.ALL_CONFIGURATIONS:
            result = _refresh_all_configurations(instance, action, auth_token=auth_token)
        else:
            result = _refresh_all_devices(instance, action, auth_token=auth_token)

    logger.info(
        "Metadata refresh action %s refreshed %s of %s target(s)",
        action.kind.value,
        result.refreshed_count,
        result.requested_count,
    )
    _store_refresh_feedback(instance, action, result, refreshed_label=refreshed_label)
    _reset_trigger(instance)


def _refresh_current_configuration(
    trigger: Value,
    action: RefreshAction,
    auth_token: str | None = None,
) -> tuple[RefreshResult, str]:
    return _refresh_current_value(
        trigger,
        action.configuration_search_attribute_uri,
        "No backend configuration exists in this configuration scope.",
        canonical_configuration_label,
        auth_token=auth_token,
        preserve_existing_collections=not action.replace_existing_collections,
        require_configuration_period=action.require_configuration_period,
    )


def _refresh_current_device(
    trigger: Value,
    action: RefreshAction,
    auth_token: str | None = None,
) -> tuple[RefreshResult, str]:
    return _refresh_current_value(
        trigger,
        action.device_search_attribute_uri,
        "No backend device exists in this device scope.",
        canonical_device_label,
        auth_token=auth_token,
    )


def _refresh_current_value(
    trigger: Value,
    source_attribute_uri: str,
    missing_value_message: str,
    label_formatter: Callable[[str, str | None], str],
    auth_token: str | None = None,
    preserve_existing_collections: bool = False,
    require_configuration_period: bool = False,
) -> tuple[RefreshResult, str]:
    source_value = (
        Value.objects.filter(
            project=trigger.project,
            snapshot=None,
            attribute__uri=source_attribute_uri,
            set_prefix=trigger.set_prefix or "",
            set_index=trigger.set_index,
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id__exact="")
        .order_by("-id")
        .first()
    )
    if source_value is None:
        return _failed_result(trigger, missing_value_message), ""

    return (
        refresh_value_from_backend(
            source_value,
            auth_token=auth_token,
            preserve_existing_collections=preserve_existing_collections,
            require_configuration_period=require_configuration_period,
        ),
        label_formatter(source_value.text or source_value.external_id, source_value.external_id),
    )


def _refresh_all_configurations(
    trigger: Value,
    action: RefreshAction,
    auth_token: str | None = None,
) -> RefreshResult:
    values = (
        Value.objects.filter(
            project=trigger.project,
            snapshot=None,
            attribute__uri=action.configuration_search_attribute_uri,
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id__exact="")
        .order_by("set_prefix", "set_index", "id")
    )
    configurations_by_scope = {(value.set_prefix or "", value.set_index): value for value in values}
    return combine_refresh_results(
        refresh_value_from_backend(
            value,
            auth_token=auth_token,
            preserve_existing_collections=True,
        )
        for value in configurations_by_scope.values()
    )


def _refresh_all_devices(
    trigger: Value,
    action: RefreshAction,
    auth_token: str | None = None,
) -> RefreshResult:
    values = (
        Value.objects.filter(
            project=trigger.project,
            snapshot=None,
            attribute__uri=action.device_search_attribute_uri,
        )
        .exclude(external_id__isnull=True)
        .exclude(external_id__exact="")
        .order_by("set_prefix", "set_index", "id")
    )
    devices_by_scope = {(value.set_prefix or "", value.set_index): value for value in values}
    return combine_refresh_results(
        refresh_value_from_backend(value, auth_token=auth_token) for value in devices_by_scope.values()
    )


def _failed_result(trigger: Value, message: str) -> RefreshResult:
    return RefreshResult(
        requested_count=1,
        refreshed_count=0,
        errors=(RefreshError(external_id=f"value:{trigger.pk}", message=message),),
    )


def _is_active_trigger(instance: Value) -> bool:
    return instance.value_type == VALUE_TYPE_BOOLEAN and instance.text == "1"


def _reset_trigger(instance: Value) -> None:
    with transaction.atomic(), mute_value_post_save():
        current = Value.objects.filter(pk=instance.pk).first()
        if current is not None and current.value_type == VALUE_TYPE_BOOLEAN and current.text == "1":
            update_value_if_changed(current, text="0")


def _store_refresh_feedback(
    trigger: Value,
    action: RefreshAction,
    result: RefreshResult,
    refreshed_label: str = "",
) -> None:
    payload = {}
    if action.status_attribute_uri:
        payload[action.status_attribute_uri] = result.status
    if action.message_attribute_uri:
        payload[action.message_attribute_uri] = format_refresh_message(action.kind, result, refreshed_label)
    if action.timestamp_attribute_uri:
        payload[action.timestamp_attribute_uri] = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")

    target_scope = (trigger.set_prefix or "", trigger.set_index)
    for attribute_uri, text in payload.items():
        replace_scalar_value_in_scopes(trigger, attribute_uri, text, scopes_to_set=[target_scope])
