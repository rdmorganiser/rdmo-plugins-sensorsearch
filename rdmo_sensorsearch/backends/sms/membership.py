from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from rdmo_sensorsearch.backends.sms.mounting import (
    format_sms_timepoint,
    parse_sms_timepoint,
    resolve_mount_location,
)
from rdmo_sensorsearch.contracts import (
    BackendFailure,
    BackendResult,
    BackendSuccess,
    ConfigurationMember,
    ConfigurationPeriod,
    MountLocation,
)

DeviceFetcher = Callable[[str], BackendResult[dict | None]]
MountActionFetcher = Callable[[str], BackendResult[dict | None]]


@dataclass(frozen=True)
class SMSConfigurationMembershipResolver:
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
    ) -> BackendResult[tuple[ConfigurationMember, ...]]:
        mount_actions, errors = self._mount_actions(configuration_data, mount_action_data)
        if errors:
            return BackendFailure(tuple(errors))

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
                response = self.fetch_device(device_id)
                if isinstance(response, BackendFailure):
                    errors.extend(response.errors)
                    continue
                device = response.value
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
                ConfigurationMember(
                    identifier=device["id"],
                    attributes=device.get("attributes", {}),
                    instrument_start=_format_mount_timepoint(attributes.get("begin_date")),
                    instrument_end=_format_mount_timepoint(attributes.get("end_date")),
                    location=MountLocation(
                        mount_location.station_height_amsl, mount_location.vertical_surface_offset, mount_location.site_name
                    ),
                    notices=mount_location.notices,
                )
            )
        return BackendFailure(tuple(errors)) if errors else BackendSuccess(tuple(members))

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
            response = self.fetch_mount_action(action_id)
            if isinstance(response, BackendFailure):
                errors.extend(response.errors)
            elif response.value is not None:
                resolved_actions.append(response.value)
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
