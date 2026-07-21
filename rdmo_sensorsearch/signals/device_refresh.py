import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from rdmo.core.constants import VALUE_TYPE_BOOLEAN
from rdmo.projects.models import Value

from rdmo_sensorsearch.config import catalog_matches, load_config
from rdmo_sensorsearch.signals.device_set_sync import (
    CONFIGURATION_SEARCH_ATTRIBUTE_URI,
    DEVICE_COLLECTION_ATTRIBUTE_URI,
    SELECTED_DEVICES_ATTRIBUTE_URI,
    DeviceRefreshError,
    DeviceRefreshResult,
    refresh_device_detail_blocks_with_result,
    resolve_refresh_target_from_selected_device_row,
)
from rdmo_sensorsearch.signals.utils import mute_value_post_save
from rdmo_sensorsearch.signals.value_updater import replace_scalar_value_in_scopes, update_value_if_changed

logger = logging.getLogger(__name__)

DEFAULT_REFRESH_TRIGGER_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-devices"


@dataclass(frozen=True)
class DeviceRefreshConfig:
    trigger_attribute_uri: str
    source_attribute_uri: str = DEVICE_COLLECTION_ATTRIBUTE_URI
    selected_devices_attribute_uri: str = SELECTED_DEVICES_ATTRIBUTE_URI
    configuration_search_attribute_uri: str = CONFIGURATION_SEARCH_ATTRIBUTE_URI
    clear_trigger_value: bool = False
    status_attribute_uri: str | None = None
    error_attribute_uri: str | None = None
    timestamp_attribute_uri: str | None = None


def get_device_refresh_config(catalog_uri: str, attribute_uri: str) -> DeviceRefreshConfig | None:
    configuration = load_config()
    catalogs = configuration.get("ProjectDeviceRefreshProvider", {}).get("catalogs", [])

    for catalog in catalogs:
        if not catalog_matches(catalog, catalog_uri):
            continue

        trigger_attribute_uri = catalog.get("trigger_attribute_uri", DEFAULT_REFRESH_TRIGGER_ATTRIBUTE_URI)
        if trigger_attribute_uri != attribute_uri:
            continue

        return DeviceRefreshConfig(
            trigger_attribute_uri=trigger_attribute_uri,
            source_attribute_uri=catalog.get("source_attribute_uri", DEVICE_COLLECTION_ATTRIBUTE_URI),
            selected_devices_attribute_uri=catalog.get("selected_devices_attribute_uri", SELECTED_DEVICES_ATTRIBUTE_URI),
            configuration_search_attribute_uri=catalog.get(
                "configuration_search_attribute_uri",
                CONFIGURATION_SEARCH_ATTRIBUTE_URI,
            ),
            clear_trigger_value=catalog.get("clear_trigger_value", False),
            status_attribute_uri=catalog.get("status_attribute_uri"),
            error_attribute_uri=catalog.get("error_attribute_uri"),
            timestamp_attribute_uri=catalog.get("timestamp_attribute_uri"),
        )

    return None


def handle_device_refresh_value(instance: Value, auth_token: str | None = None) -> None:
    if instance.project is None or instance.project.catalog is None or instance.attribute is None:
        return

    refresh_config = get_device_refresh_config(instance.project.catalog.uri, instance.attribute.uri)
    if refresh_config is None:
        return

    if not instance.external_id and not _is_truthy_trigger_value(instance):
        logger.debug("Skipping inactive row-local device refresh trigger %s", instance.pk)
        return

    block_external_id = _resolve_refresh_block_external_id(instance, refresh_config)
    if block_external_id is None:
        result = _failed_refresh_result(instance, "Could not resolve selected device for this refresh trigger.")
        _store_refresh_result(instance, refresh_config, result)
        _finalize_refresh_trigger(instance, refresh_config)
        return

    result = refresh_device_detail_blocks_with_result(
        project=instance.project,
        catalog=instance.project.catalog,
        block_external_ids=[block_external_id],
        device_collection_attribute_uri=refresh_config.source_attribute_uri,
        auth_token=auth_token,
    )
    logger.info(
        "Device refresh trigger %s refreshed %s of %s device detail block(s)",
        instance.pk,
        result.refreshed_count,
        result.requested_count,
    )
    _store_refresh_result(instance, refresh_config, result)
    _finalize_refresh_trigger(instance, refresh_config)


def _clear_trigger_value(instance: Value) -> None:
    with transaction.atomic(), mute_value_post_save():
        Value.objects.filter(pk=instance.pk).delete()


def _finalize_refresh_trigger(instance: Value, refresh_config: DeviceRefreshConfig) -> None:
    if refresh_config.clear_trigger_value:
        _clear_trigger_value(instance)
    else:
        _reset_boolean_trigger_value(instance)


def _reset_boolean_trigger_value(instance: Value) -> None:
    if instance.value_type != VALUE_TYPE_BOOLEAN or instance.text != "1":
        return

    with transaction.atomic(), mute_value_post_save():
        current = Value.objects.filter(pk=instance.pk).first()
        if current is not None and current.value_type == VALUE_TYPE_BOOLEAN and current.text == "1":
            update_value_if_changed(current, text="0")


def _resolve_refresh_block_external_id(instance: Value, refresh_config: DeviceRefreshConfig) -> str | None:
    if instance.external_id:
        return instance.external_id

    target = resolve_refresh_target_from_selected_device_row(
        instance,
        selected_devices_attribute_uri=refresh_config.selected_devices_attribute_uri,
        configuration_search_attribute_uri=refresh_config.configuration_search_attribute_uri,
    )
    return target.block_external_id if target is not None else None


def _is_truthy_trigger_value(instance: Value) -> bool:
    if instance.option_id is not None:
        return True
    if instance.external_id:
        return True
    if instance.text is None:
        return False
    return instance.text.strip().lower() not in {"", "0", "false", "no"}


def _failed_refresh_result(instance: Value, message: str) -> DeviceRefreshResult:
    return DeviceRefreshResult(
        requested_count=1,
        refreshed_count=0,
        errors=(
            DeviceRefreshError(
                external_id=f"value:{instance.pk}",
                message=message,
            ),
        ),
    )


def _store_refresh_result(instance: Value, refresh_config: DeviceRefreshConfig, result: DeviceRefreshResult) -> None:
    payload = {}
    if refresh_config.status_attribute_uri:
        payload[refresh_config.status_attribute_uri] = "failed" if result.errors else "success"
    if refresh_config.error_attribute_uri:
        payload[refresh_config.error_attribute_uri] = _format_refresh_errors(result)
    if refresh_config.timestamp_attribute_uri:
        payload[refresh_config.timestamp_attribute_uri] = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M")

    if payload:
        _write_refresh_feedback_values(instance, payload)


def _write_refresh_feedback_values(instance: Value, payload: dict[str, str]) -> None:
    target_scope = (instance.set_prefix or "", instance.set_index)
    logger.info(
        "Writing refresh feedback for trigger %s to set_prefix=%r, set_index=%s",
        instance.pk,
        target_scope[0],
        target_scope[1],
    )

    for attribute_uri, text in payload.items():
        replace_scalar_value_in_scopes(instance, attribute_uri, text, scopes_to_set=[target_scope])


def _format_refresh_errors(result: DeviceRefreshResult) -> str:
    if not result.errors:
        return ""

    prefix = f"Refresh failed ({result.refreshed_count}/{result.requested_count} device detail blocks refreshed)."
    details = "; ".join(
        f"{error.external_id}: {error.message}" if error.external_id else error.message for error in result.errors
    )
    return _truncate_refresh_error(f"{prefix} {details}")


def _truncate_refresh_error(message: str, max_length: int = 1000) -> str:
    if len(message) <= max_length:
        return message
    return f"{message[: max_length - 3]}..."
