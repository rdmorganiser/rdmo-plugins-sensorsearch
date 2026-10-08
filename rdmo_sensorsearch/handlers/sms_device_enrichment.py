from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from rdmo_sensorsearch.contracts import (
    BackendFailure,
    BackendSuccess,
    DeviceDetailSettings,
    MountLocation,
    RefreshNotice,
    SelectedDevice,
)
from rdmo_sensorsearch.services.device_detail_profile import DEFAULT_DEVICE_DETAIL_SETTINGS
from rdmo_sensorsearch.services.device_details import DeviceBlockPlan, parse_external_id

logger = logging.getLogger(__name__)

INSTRUMENT_START_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.instrument_start_attribute_uri
INSTRUMENT_END_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.instrument_end_attribute_uri
INSTRUMENT_LOCATION_AMSL_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.instrument_location_amsl_attribute_uri
SURFACE_OFFSET_Z_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.surface_offset_z_attribute_uri
SITE_NAME_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.site_name_attribute_uri
SERIAL_NUMBER_ATTRIBUTE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.serial_number_attribute_uri


@dataclass(frozen=True)
class SMSDeviceMetadataEnricher:
    """Add SMS mount-period and mount-location metadata to a device payload."""

    configuration_external_id: str | None
    auth_token: str | None = None
    detail_settings: DeviceDetailSettings = DEFAULT_DEVICE_DETAIL_SETTINGS

    @property
    def scoped_attribute_uris(self) -> tuple[str, str]:
        return (
            self.detail_settings.instrument_start_attribute_uri,
            self.detail_settings.instrument_end_attribute_uri,
        )

    def __call__(self, mapped_values: dict[str, Any], plan: DeviceBlockPlan) -> tuple[RefreshNotice, ...]:
        configuration_external_id = plan.configuration_external_id or self.configuration_external_id
        self._merge_mount_period(
            mapped_values,
            plan.device,
            plan.handler_binding,
            configuration_external_id,
        )
        return self._merge_mount_location(
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
        if self.detail_settings.instrument_start_attribute_uri in mapped_values:
            mapped_values.setdefault(self.detail_settings.instrument_end_attribute_uri, "")
            return
        if device.instrument_start:
            mapped_values[self.detail_settings.instrument_start_attribute_uri] = device.instrument_start
            mapped_values[self.detail_settings.instrument_end_attribute_uri] = device.instrument_end or ""
            return

        start_value, end_value = self._resolve_mount_period(
            mapped_values,
            device,
            handler_binding,
            configuration_external_id,
        )
        mapped_values[self.detail_settings.instrument_start_attribute_uri] = start_value or ""
        mapped_values[self.detail_settings.instrument_end_attribute_uri] = end_value or ""

    def _merge_mount_location(
        self,
        mapped_values: dict[str, Any],
        device: SelectedDevice,
        handler_binding: Any,
        configuration_external_id: str | None,
    ) -> tuple[RefreshNotice, ...]:
        if device.mount_location_resolved:
            station_height_amsl = device.station_height_amsl
            vertical_surface_offset = device.vertical_surface_offset
            site_name = device.site_name
            notices = device.mount_location_notices
        else:
            location = self._resolve_mount_location(
                device,
                handler_binding,
                configuration_external_id,
            )
            station_height_amsl = location.value.station_height_amsl if location is not None else None
            vertical_surface_offset = location.value.vertical_surface_offset if location is not None else None
            site_name = location.value.site_name if location is not None else None
            notices = location.notices if location is not None else ()

        mapped_values[self.detail_settings.instrument_location_amsl_attribute_uri] = (
            station_height_amsl if station_height_amsl is not None else ""
        )
        mapped_values[self.detail_settings.surface_offset_z_attribute_uri] = (
            vertical_surface_offset if vertical_surface_offset is not None else ""
        )
        mapped_values[self.detail_settings.site_name_attribute_uri] = site_name if site_name is not None else ""
        return notices

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

        serial_number = mapped_values.get(self.detail_settings.serial_number_attribute_uri)
        if not isinstance(serial_number, str) or not serial_number.strip():
            serial_number = _serial_number_from_text(device.text)

        period = handler.backend.get_mount_period(
            device_id, configuration_id, serial_number=serial_number, auth_token=self.auth_token
        )
        if isinstance(period, BackendFailure):
            logger.warning("Could not fetch device mount actions for %s: %s", device_id, period.errors)
            return None, None
        return (period.value.start, period.value.end) if period.value is not None else (None, None)

    def _resolve_mount_location(
        self,
        device: SelectedDevice,
        handler_binding: Any,
        configuration_external_id: str | None,
    ) -> BackendSuccess[MountLocation] | None:
        if not configuration_external_id:
            return None

        handler = handler_binding.handler
        if not getattr(handler, "supports_mount_location_lookup", False):
            return None

        configuration_id = parse_external_id(configuration_external_id)[1]
        device_id = parse_external_id(device.external_id)[1]
        if configuration_id is None or device_id is None:
            return None

        location = handler.backend.get_mount_location(device_id, configuration_id, best_effort=True, auth_token=self.auth_token)
        if isinstance(location, BackendFailure):
            logger.warning("Could not fetch SMS configuration mount metadata: %s", location.errors)
            return None
        for diagnostic in location.diagnostics:
            logger.warning("Could not fetch SMS configuration mount metadata: %s", diagnostic)
        return location if location.value is not None else None


def _serial_number_from_text(text: str) -> str | None:
    marker = "(s/n:"
    if marker not in text:
        return None
    serial_fragment = text.split(marker, 1)[1]
    return serial_fragment.split(")", 1)[0].strip() or None
