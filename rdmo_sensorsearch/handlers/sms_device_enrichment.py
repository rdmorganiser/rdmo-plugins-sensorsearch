from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, ClassVar

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.handlers.sms_mounting import (
    resolve_mount_location,
    select_latest_device_mount_action,
    select_latest_device_mount_period,
)
from rdmo_sensorsearch.services.device_details import DeviceBlockPlan, SelectedDevice, parse_external_id

logger = logging.getLogger(__name__)

INSTRUMENT_START_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/instrument-start-datetime"
INSTRUMENT_END_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/instrument-end-datetime"
INSTRUMENT_LOCATION_AMSL_ATTRIBUTE_URI = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/geo_location/height"
SURFACE_OFFSET_Z_ATTRIBUTE_URI = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/geo_location/depth"
SITE_NAME_ATTRIBUTE_URI = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/processing/location"
SERIAL_NUMBER_ATTRIBUTE_URI = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/serial_number"


@dataclass(frozen=True)
class SMSDeviceMetadataEnricher:
    """Add SMS mount-period and mount-location metadata to a device payload."""

    configuration_external_id: str | None
    auth_token: str | None = None

    scoped_attribute_uris: ClassVar[tuple[str, str]] = (
        INSTRUMENT_START_ATTRIBUTE_URI,
        INSTRUMENT_END_ATTRIBUTE_URI,
    )

    def __call__(self, mapped_values: dict[str, Any], plan: DeviceBlockPlan) -> None:
        configuration_external_id = plan.configuration_external_id or self.configuration_external_id
        self._merge_mount_period(
            mapped_values,
            plan.device,
            plan.handler_binding,
            configuration_external_id,
        )
        self._merge_mount_location(
            mapped_values,
            plan.device,
            plan.handler_binding,
            configuration_external_id,
        )

    def _merge_mount_period(
        self,
        mapped_values: dict[str, Any],
        device: SelectedDevice,
        handler_binding: Any,
        configuration_external_id: str | None,
    ) -> None:
        if INSTRUMENT_START_ATTRIBUTE_URI in mapped_values:
            mapped_values.setdefault(INSTRUMENT_END_ATTRIBUTE_URI, "")
            return
        if device.instrument_start:
            mapped_values[INSTRUMENT_START_ATTRIBUTE_URI] = device.instrument_start
            mapped_values[INSTRUMENT_END_ATTRIBUTE_URI] = device.instrument_end or ""
            return

        start_value, end_value = self._resolve_mount_period(
            mapped_values,
            device,
            handler_binding,
            configuration_external_id,
        )
        mapped_values[INSTRUMENT_START_ATTRIBUTE_URI] = start_value or ""
        mapped_values[INSTRUMENT_END_ATTRIBUTE_URI] = end_value or ""

    def _merge_mount_location(
        self,
        mapped_values: dict[str, Any],
        device: SelectedDevice,
        handler_binding: Any,
        configuration_external_id: str | None,
    ) -> None:
        if device.mount_location_resolved:
            height_amsl = device.height_amsl
            vertical_surface_offset = device.vertical_surface_offset
            site_name = device.site_name
        else:
            height_amsl, vertical_surface_offset, site_name = self._resolve_mount_location(
                device,
                handler_binding,
                configuration_external_id,
            )

        mapped_values[INSTRUMENT_LOCATION_AMSL_ATTRIBUTE_URI] = height_amsl if height_amsl is not None else ""
        mapped_values[SURFACE_OFFSET_Z_ATTRIBUTE_URI] = vertical_surface_offset if vertical_surface_offset is not None else ""
        mapped_values[SITE_NAME_ATTRIBUTE_URI] = site_name if site_name is not None else ""

    def _resolve_mount_period(
        self,
        mapped_values: dict[str, Any],
        device: SelectedDevice,
        handler_binding: Any,
        configuration_external_id: str | None,
    ) -> tuple[str | None, str | None]:
        if not configuration_external_id:
            return None, None

        configuration_id = parse_external_id(configuration_external_id)[1]
        device_id = parse_external_id(device.external_id)[1]
        handler = handler_binding.handler
        if configuration_id is None or device_id is None:
            return None, None
        if not getattr(handler, "supports_mount_period_lookup", False):
            return None, None

        mount_actions = self._fetch_device_mount_actions(handler, device_id)
        if not mount_actions:
            return None, None

        serial_number = mapped_values.get(SERIAL_NUMBER_ATTRIBUTE_URI)
        if not isinstance(serial_number, str) or not serial_number.strip():
            serial_number = _serial_number_from_text(device.text)

        period = select_latest_device_mount_period(
            mount_actions,
            configuration_id,
            device_id,
            serial_number=serial_number,
        )
        return period.formatted() if period is not None else (None, None)

    def _resolve_mount_location(
        self,
        device: SelectedDevice,
        handler_binding: Any,
        configuration_external_id: str | None,
    ) -> tuple[float | None, float | None, str | None]:
        if not configuration_external_id:
            return None, None, None

        handler = handler_binding.handler
        if not getattr(handler, "supports_mount_location_lookup", False):
            return None, None, None

        configuration_id = parse_external_id(configuration_external_id)[1]
        device_id = parse_external_id(device.external_id)[1]
        if configuration_id is None or device_id is None:
            return None, None, None

        device_actions = self._fetch_configuration_mount_actions(
            handler,
            "configuration_device_mount_actions_url",
            (
                "{base_url}/device-mount-actions?filter[configuration_id]={id}"
                "&page[size]=10000&include=parent_platform,parent_device,configuration"
            ),
            configuration_id,
        )
        device_action = select_latest_device_mount_action(
            device_actions,
            configuration_id,
            device_id,
        )
        if device_action is None:
            return None, None, None

        platform_actions = self._fetch_configuration_mount_actions(
            handler,
            "configuration_platform_mount_actions_url",
            "{base_url}/platform-mount-actions?filter[configuration_id]={id}&page[size]=10000",
            configuration_id,
        )
        static_location_actions = self._fetch_configuration_mount_actions(
            handler,
            "configuration_static_location_actions_url",
            "{base_url}/static-location-actions?filter[configuration_id]={id}&page[size]=10000",
            configuration_id,
        )
        mount_location = resolve_mount_location(
            device_action,
            device_actions,
            platform_actions,
            static_location_actions,
        )
        return mount_location.height_amsl, mount_location.vertical_surface_offset, mount_location.site_name

    def _fetch_device_mount_actions(self, handler: Any, device_id: str) -> list[dict]:
        template = getattr(
            handler,
            "device_mount_actions_url",
            "{base_url}/devices/{id}/device-mount-actions"
            "?page[size]=10000&include=begin_contact,end_contact,parent_platform,parent_device,configuration",
        )
        url = template.format(base_url=handler.base_url, id=device_id)
        payload = fetch_json(url, auth_token=self.auth_token)
        return _payload_data(payload, url, f"device mount actions for {device_id}")

    def _fetch_configuration_mount_actions(
        self,
        handler: Any,
        template_attribute: str,
        default_template: str,
        configuration_id: str,
    ) -> list[dict]:
        template = getattr(handler, template_attribute, default_template)
        url = template.format(base_url=handler.base_url, id=configuration_id)
        payload = fetch_json(url, auth_token=self.auth_token)
        return _payload_data(payload, url, "SMS configuration mount metadata")


def _payload_data(payload: Any, url: str, description: str) -> list[dict]:
    if isinstance(payload, dict) and "errors" in payload:
        logger.warning("Could not fetch %s from %s: %s", description, url, payload["errors"])
        return []
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", [])
    return data if isinstance(data, list) else []


def _serial_number_from_text(text: str) -> str | None:
    marker = "(s/n:"
    if marker not in text:
        return None
    serial_fragment = text.split(marker, 1)[1]
    return serial_fragment.split(")", 1)[0].strip() or None
