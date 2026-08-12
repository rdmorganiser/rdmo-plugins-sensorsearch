from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rdmo_sensorsearch.handlers.configuration_period import ConfigurationPeriod
from rdmo_sensorsearch.handlers.sms_mounting import (
    format_sms_timepoint,
    parse_sms_timepoint,
    resolve_mount_location,
)
from rdmo_sensorsearch.naming import configuration_short_label
from rdmo_sensorsearch.services.device_details import SelectedDevice
from rdmo_sensorsearch.services.refresh import RefreshNotice

DeviceFetcher = Callable[[str], tuple[dict | None, list[str]]]
MountActionFetcher = Callable[[str], tuple[dict | None, list[str]]]


@dataclass(frozen=True)
class SMSConfigurationMember:
    text: str
    external_id: str
    instrument_start: str | None
    instrument_end: str | None
    station_height_amsl: float | None
    vertical_surface_offset: float | None
    site_name: str | None
    mount_location_notices: tuple[RefreshNotice, ...] = ()

    def as_collection_value(self) -> dict[str, object]:
        return {
            "text": self.text,
            "external_id": self.external_id,
            "instrument_start": self.instrument_start,
            "instrument_end": self.instrument_end,
            "station_height_amsl": self.station_height_amsl,
            "vertical_surface_offset": self.vertical_surface_offset,
            "site_name": self.site_name,
            "mount_location_notices": self.mount_location_notices,
        }

    def as_selected_device(self) -> SelectedDevice:
        return SelectedDevice(
            text=self.text,
            external_id=self.external_id,
            instrument_start=self.instrument_start,
            instrument_end=self.instrument_end,
            station_height_amsl=self.station_height_amsl,
            vertical_surface_offset=self.vertical_surface_offset,
            site_name=self.site_name,
            mount_location_resolved=True,
            mount_location_notices=self.mount_location_notices,
        )


@dataclass(frozen=True)
class SMSConfigurationMembershipResolver:
    configuration_id_prefix: str
    device_id_prefix: str
    device_text_prefix: str
    fetch_device: DeviceFetcher
    fetch_mount_action: MountActionFetcher
    static_location_end_tolerance_seconds: int = 0
    incomplete_mount_chain_policy: str = "strict"

    def resolve(
        self,
        *,
        configuration_data: dict,
        mount_action_data: dict,
        platform_mount_action_data: dict | None = None,
        static_location_action_data: dict | None = None,
        configuration_period: ConfigurationPeriod | None = None,
    ) -> tuple[tuple[SMSConfigurationMember, ...], tuple[str, ...]]:
        mount_actions, errors = self._mount_actions(configuration_data, mount_action_data)
        if errors:
            return (), tuple(errors)

        included_devices = {item["id"]: item for item in mount_action_data.get("included", []) if item.get("type") == "device"}
        platform_mount_actions = (
            platform_mount_action_data.get("data", []) if isinstance(platform_mount_action_data, dict) else []
        )
        static_location_actions = (
            static_location_action_data.get("data", []) if isinstance(static_location_action_data, dict) else []
        )
        selected_mount_actions = select_member_mount_actions(mount_actions, configuration_period)
        reference_time = configuration_period.end if configuration_period is not None else None

        members = []
        for mount_action in selected_mount_actions:
            device_ref = mount_action.get("relationships", {}).get("device", {}).get("data")
            if not isinstance(device_ref, dict) or not device_ref.get("id"):
                continue
            device_id = device_ref["id"]
            device = included_devices.get(device_id)
            if device is None:
                device, device_errors = self.fetch_device(device_id)
                if device_errors:
                    errors.extend(device_errors)
                    continue
            if device is None:
                continue

            attributes = mount_action.get("attributes", {})
            mount_location = resolve_mount_location(
                mount_action,
                mount_actions,
                platform_mount_actions,
                static_location_actions,
                reference_time=reference_time,
                static_location_end_tolerance_seconds=self.static_location_end_tolerance_seconds,
                incomplete_mount_chain_policy=self.incomplete_mount_chain_policy,
            )
            members.append(
                SMSConfigurationMember(
                    text=self.format_device_text(
                        configuration_id=configuration_data.get("data", {}).get("id"),
                        device_id=device["id"],
                        attributes=device.get("attributes", {}),
                    ),
                    external_id=f"{self.device_id_prefix}:{device['id']}",
                    instrument_start=_format_mount_timepoint(attributes.get("begin_date")),
                    instrument_end=_format_mount_timepoint(attributes.get("end_date")),
                    station_height_amsl=mount_location.station_height_amsl,
                    vertical_surface_offset=mount_location.vertical_surface_offset,
                    site_name=mount_location.site_name,
                    mount_location_notices=mount_location.notices,
                )
            )
        return tuple(members), tuple(errors)

    def format_device_text(self, configuration_id: str | None, device_id: str, attributes: dict) -> str:
        name = attributes.get("long_name") or attributes.get("short_name", "")
        serial = f" (s/n: {attributes['serial_number']})" if attributes.get("serial_number") else ""
        configuration_label = (
            configuration_short_label(f"{self.configuration_id_prefix}:{configuration_id}") if configuration_id else None
        )
        configuration_prefix = f"{configuration_label} " if configuration_label else ""
        return f"{configuration_prefix}{self.device_text_prefix}({device_id}): {name}{serial}"

    def _mount_actions(self, configuration_data: dict, mount_action_data: dict) -> tuple[list[dict], list[str]]:
        mount_actions = mount_action_data.get("data", [])
        if mount_actions:
            return mount_actions, []

        action_refs = configuration_data.get("data", {}).get("relationships", {}).get("device_mount_actions", {}).get("data", [])
        resolved_actions = []
        errors = []
        for action_ref in action_refs:
            action_id = action_ref.get("id")
            if not action_id:
                continue
            action, action_errors = self.fetch_mount_action(action_id)
            errors.extend(action_errors)
            if action is not None:
                resolved_actions.append(action)
        return resolved_actions, errors


def select_member_mount_actions(
    mount_actions: list[dict],
    configuration_period: ConfigurationPeriod | None,
) -> list[dict]:
    selected_by_device: dict[str, dict] = {}
    for mount_action in mount_actions:
        if configuration_period is not None and not mount_action_overlaps_period(mount_action, configuration_period):
            continue
        device_ref = mount_action.get("relationships", {}).get("device", {}).get("data")
        if not isinstance(device_ref, dict) or not isinstance(device_ref.get("id"), str):
            continue
        device_id = device_ref["id"]
        selected = selected_by_device.get(device_id)
        if selected is None or _mount_action_begin_sort_key(mount_action) > _mount_action_begin_sort_key(selected):
            selected_by_device[device_id] = mount_action
    return list(selected_by_device.values())


def mount_action_overlaps_period(mount_action: dict, configuration_period: ConfigurationPeriod) -> bool:
    attributes = mount_action.get("attributes", {})
    mount_start = parse_sms_timepoint(attributes.get("begin_date"))
    if mount_start is None:
        return False

    raw_end = attributes.get("end_date")
    mount_end = parse_sms_timepoint(raw_end) if raw_end else None
    if raw_end and mount_end is None:
        return False
    if configuration_period.end is not None and mount_start > configuration_period.end:
        return False
    return mount_end is None or mount_end > configuration_period.start


def _mount_action_begin_sort_key(mount_action: dict) -> float:
    parsed = parse_sms_timepoint(mount_action.get("attributes", {}).get("begin_date"))
    return parsed.timestamp() if parsed is not None else float("-inf")


def _format_mount_timepoint(value) -> str | None:
    return format_sms_timepoint(parse_sms_timepoint(value))
