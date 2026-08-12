import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from enum import Enum
from typing import Any

from rdmo_sensorsearch.services.refresh import RefreshNotice

logger = logging.getLogger(__name__)


class IncompleteMountChainPolicy(str, Enum):
    STRICT = "strict"
    DIRECT_DEVICE_OFFSET = "direct_device_offset"


class MountChainStatus(str, Enum):
    COMPLETE = "complete"
    MISSING_PARENT = "missing_parent"
    CYCLE = "cycle"


class MountLocationNoticeCode(str, Enum):
    STATIC_LOCATION_NOT_FOUND = "static_location_not_found"
    STATIC_LOCATION_NOT_ACTIVE = "static_location_not_active_at_reference_time"
    STATIC_LOCATION_TOLERANCE_USED = "static_location_end_tolerance_used"
    STATIC_LOCATION_HEIGHT_MISSING = "static_location_height_missing"
    STATIC_LOCATION_LABEL_MISSING = "static_location_label_missing"
    PARENT_MOUNT_ACTION_MISSING = "parent_mount_action_missing"
    MOUNT_CHAIN_CYCLE = "mount_chain_cycle"
    DEVICE_OFFSET_MISSING = "device_offset_missing"
    DEVICE_OFFSET_INVALID = "device_offset_invalid"
    DIRECT_DEVICE_OFFSET_USED = "direct_device_offset_fallback_used"


@dataclass(frozen=True)
class MountChainResolution:
    actions: tuple[dict, ...]
    status: MountChainStatus
    missing_parent_type: str | None = None
    missing_parent_id: str | None = None


@dataclass(frozen=True)
class ResolvedMountLocation:
    station_height_amsl: float | None
    vertical_surface_offset: float | None
    site_name: str | None
    notices: tuple[RefreshNotice, ...] = ()


@dataclass(frozen=True)
class ResolvedMountPeriod:
    """The latest valid device mount action and its normalized time period."""

    action: dict
    start: datetime
    end: datetime | None

    def formatted(self) -> tuple[str, str | None]:
        return format_sms_timepoint(self.start), format_sms_timepoint(self.end)


def select_latest_device_mount_action(
    actions: list[dict],
    configuration_id: str,
    device_id: str,
) -> dict | None:
    matching_actions = [
        action
        for action in actions
        if _relationship_id(action, "configuration") == configuration_id and _relationship_id(action, "device") == device_id
    ]
    if not matching_actions:
        return None
    return max(matching_actions, key=_action_begin_sort_key)


def select_latest_device_mount_period(
    actions: list[dict],
    configuration_id: str,
    device_id: str,
    *,
    serial_number: str | None = None,
) -> ResolvedMountPeriod | None:
    """Select the latest valid mount period for one device in a configuration."""

    normalized_serial = serial_number.strip().casefold() if isinstance(serial_number, str) and serial_number.strip() else None
    periods = []
    for action in actions:
        if _relationship_id(action, "configuration") != configuration_id:
            continue
        if _relationship_id(action, "device") != device_id:
            continue

        attributes = action.get("attributes", {})
        action_serial = attributes.get("serial_number")
        if normalized_serial and isinstance(action_serial, str):
            if action_serial.strip().casefold() != normalized_serial:
                continue

        start = parse_sms_timepoint(attributes.get("begin_date"))
        if start is None:
            continue
        periods.append(
            ResolvedMountPeriod(
                action=action,
                start=start,
                end=parse_sms_timepoint(attributes.get("end_date")),
            )
        )

    if not periods:
        return None
    return max(periods, key=lambda period: period.start)


def format_sms_timepoint(value: datetime | None) -> str | None:
    """Format an SMS timestamp for the RDMO datetime text fields."""

    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_timezone.utc)
    return value.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M")


def resolve_mount_location(
    device_action: dict,
    device_actions: list[dict],
    platform_actions: list[dict],
    static_location_actions: list[dict],
    *,
    now: datetime | None = None,
    reference_time: datetime | None = None,
    static_location_end_tolerance_seconds: int = 0,
    incomplete_mount_chain_policy: str = IncompleteMountChainPolicy.STRICT.value,
) -> ResolvedMountLocation:
    policy = IncompleteMountChainPolicy(incomplete_mount_chain_policy)
    tolerance = timedelta(seconds=max(0, static_location_end_tolerance_seconds))
    if reference_time is None:
        reference_time = _action_reference_time(device_action, now=now)
    else:
        reference_time = _clamp_to_action_period(device_action, reference_time)
    mount_chain = _mount_chain(
        device_action,
        device_actions,
        platform_actions,
        reference_time,
    )
    notices = []

    vertical_surface_offset = None
    if mount_chain.status is MountChainStatus.COMPLETE:
        vertical_surface_offset = sum(_offset_z_or_zero(action) for action in mount_chain.actions)
    elif mount_chain.status is MountChainStatus.MISSING_PARENT:
        notices.append(
            _notice(
                MountLocationNoticeCode.PARENT_MOUNT_ACTION_MISSING,
                device_action,
                missing_parent_type=mount_chain.missing_parent_type,
                missing_parent_id=mount_chain.missing_parent_id,
            )
        )
        direct_offset = _number(device_action.get("attributes", {}).get("offset_z"))
        if policy is IncompleteMountChainPolicy.DIRECT_DEVICE_OFFSET and direct_offset is not None:
            vertical_surface_offset = direct_offset
            notices.append(_notice(MountLocationNoticeCode.DIRECT_DEVICE_OFFSET_USED, device_action))
        elif policy is IncompleteMountChainPolicy.DIRECT_DEVICE_OFFSET:
            raw_offset = device_action.get("attributes", {}).get("offset_z")
            code = (
                MountLocationNoticeCode.DEVICE_OFFSET_MISSING
                if raw_offset is None
                else MountLocationNoticeCode.DEVICE_OFFSET_INVALID
            )
            notices.append(_notice(code, device_action))
    else:
        notices.append(_notice(MountLocationNoticeCode.MOUNT_CHAIN_CYCLE, device_action))

    static_location, tolerance_used = _select_static_location_for_mount(
        static_location_actions,
        reference_time,
        device_action,
        tolerance,
    )
    station_height_amsl = None
    site_name = None
    if static_location is not None:
        static_location_attributes = static_location.get("attributes", {})
        station_height_amsl = _number(static_location_attributes.get("z"))
        if station_height_amsl is None:
            notices.append(_notice(MountLocationNoticeCode.STATIC_LOCATION_HEIGHT_MISSING, device_action))
        label = static_location_attributes.get("label")
        if isinstance(label, str):
            site_name = label
        else:
            notices.append(_notice(MountLocationNoticeCode.STATIC_LOCATION_LABEL_MISSING, device_action))
        if tolerance_used:
            gap = reference_time - parse_sms_timepoint(static_location_attributes.get("end_date"))
            notices.append(
                _notice(
                    MountLocationNoticeCode.STATIC_LOCATION_TOLERANCE_USED,
                    device_action,
                    location_action_id=static_location.get("id"),
                    gap_seconds=str(round(gap.total_seconds(), 6)),
                )
            )
    else:
        code = (
            MountLocationNoticeCode.STATIC_LOCATION_NOT_ACTIVE
            if static_location_actions and reference_time is not None
            else MountLocationNoticeCode.STATIC_LOCATION_NOT_FOUND
        )
        notices.append(_notice(code, device_action))

    _log_resolution_notices(notices, policy)

    return ResolvedMountLocation(
        station_height_amsl=station_height_amsl,
        vertical_surface_offset=vertical_surface_offset,
        site_name=site_name,
        notices=tuple(notices),
    )


def _select_static_location_for_mount(
    actions: list[dict],
    reference_time: datetime | None,
    device_action: dict,
    tolerance: timedelta,
) -> tuple[dict | None, bool]:
    exact = select_static_location_action(actions, reference_time)
    if exact is not None or reference_time is None or tolerance <= timedelta(0):
        return exact, False

    eligible = []
    for action in actions:
        end = parse_sms_timepoint(action.get("attributes", {}).get("end_date"))
        if end is None or end > reference_time:
            continue
        gap = reference_time - end
        if gap > tolerance or not _actions_overlap(action, device_action):
            continue
        eligible.append((gap, action))
    if not eligible:
        return None, False

    _, selected = min(
        eligible,
        key=lambda item: (item[0], -_action_begin_sort_key(item[1])),
    )
    return selected, True


def select_static_location_action(
    actions: list[dict],
    reference_time: datetime | None = None,
) -> dict | None:
    if not actions:
        return None

    if reference_time is not None:
        containing_actions = [action for action in actions if _action_contains(action, reference_time)]
        if containing_actions:
            return max(containing_actions, key=_action_begin_sort_key)
        return None

    active_actions = [action for action in actions if not action.get("attributes", {}).get("end_date")]
    if active_actions:
        return max(active_actions, key=_action_begin_sort_key)
    return max(actions, key=_action_begin_sort_key)


def _mount_chain(
    device_action: dict,
    device_actions: list[dict],
    platform_actions: list[dict],
    reference_time: datetime | None,
) -> MountChainResolution:
    chain = [device_action]
    visited = {_action_key(device_action)}
    current_action = device_action

    while True:
        parent_type, parent_id = _parent_ref(current_action)
        if parent_type is None or parent_id is None:
            return MountChainResolution(tuple(chain), MountChainStatus.COMPLETE)

        candidates = platform_actions if parent_type == "platform" else device_actions
        parent_action = _select_entity_action(candidates, parent_type, parent_id, reference_time)
        if parent_action is None:
            return MountChainResolution(
                tuple(chain),
                MountChainStatus.MISSING_PARENT,
                missing_parent_type=parent_type,
                missing_parent_id=parent_id,
            )

        action_key = _action_key(parent_action)
        if action_key in visited:
            return MountChainResolution(tuple(chain), MountChainStatus.CYCLE)
        visited.add(action_key)
        chain.append(parent_action)
        current_action = parent_action


def _select_entity_action(
    actions: list[dict],
    entity_type: str,
    entity_id: str,
    reference_time: datetime | None,
) -> dict | None:
    relationship_name = "platform" if entity_type == "platform" else "device"
    candidates = [action for action in actions if _relationship_id(action, relationship_name) == entity_id]
    if not candidates:
        return None
    if reference_time is None:
        return max(candidates, key=_action_begin_sort_key)

    containing_actions = [action for action in candidates if _action_contains(action, reference_time)]
    if not containing_actions:
        return None
    return max(containing_actions, key=_action_begin_sort_key)


def _parent_ref(action: dict) -> tuple[str | None, str | None]:
    parent_device_id = _relationship_id(action, "parent_device")
    if parent_device_id:
        return "device", parent_device_id

    parent_platform_id = _relationship_id(action, "parent_platform")
    if parent_platform_id:
        return "platform", parent_platform_id
    return None, None


def _relationship_id(action: dict, name: str) -> str | None:
    relationship = action.get("relationships", {}).get(name, {}).get("data")
    if not isinstance(relationship, dict):
        return None
    value = relationship.get("id")
    return value if isinstance(value, str) and value else None


def _action_reference_time(action: dict, now: datetime | None = None) -> datetime | None:
    attrs = action.get("attributes", {})
    begin = parse_sms_timepoint(attrs.get("begin_date"))
    end = parse_sms_timepoint(attrs.get("end_date"))
    if end is not None:
        if begin is None or end > begin:
            return end - timedelta(microseconds=1)
        return end

    current = now or datetime.now(dt_timezone.utc)
    if begin is not None and current < begin:
        return begin
    return current


def _clamp_to_action_period(action: dict, reference_time: datetime) -> datetime:
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=dt_timezone.utc)
    else:
        reference_time = reference_time.astimezone(dt_timezone.utc)

    attrs = action.get("attributes", {})
    begin = parse_sms_timepoint(attrs.get("begin_date"))
    end = parse_sms_timepoint(attrs.get("end_date"))
    if begin is not None and reference_time < begin:
        return begin
    if end is not None and reference_time >= end:
        if begin is None or end > begin:
            return end - timedelta(microseconds=1)
        return end
    return reference_time


def _action_contains(action: dict, reference_time: datetime) -> bool:
    attrs = action.get("attributes", {})
    begin = parse_sms_timepoint(attrs.get("begin_date"))
    end = parse_sms_timepoint(attrs.get("end_date"))
    if begin is not None and reference_time < begin:
        return False
    return end is None or reference_time < end


def _actions_overlap(first: dict, second: dict) -> bool:
    first_start, first_end = _action_interval(first)
    second_start, second_end = _action_interval(second)
    if first_end is not None and second_start is not None and first_end <= second_start:
        return False
    return second_end is None or first_start is None or second_end > first_start


def _action_interval(action: dict) -> tuple[datetime | None, datetime | None]:
    attributes = action.get("attributes", {})
    return parse_sms_timepoint(attributes.get("begin_date")), parse_sms_timepoint(attributes.get("end_date"))


def _action_begin_sort_key(action: dict) -> float:
    begin = parse_sms_timepoint(action.get("attributes", {}).get("begin_date"))
    return begin.timestamp() if begin is not None else float("-inf")


def _action_key(action: dict) -> tuple[str | None, str | None]:
    return action.get("type"), action.get("id")


def _offset_z_or_zero(action: dict) -> float:
    return _number(action.get("attributes", {}).get("offset_z")) or 0.0


def _notice(code: MountLocationNoticeCode, device_action: dict, **details: Any) -> RefreshNotice:
    device_id = _relationship_id(device_action, "device") or ""
    configuration_id = _relationship_id(device_action, "configuration") or ""
    normalized_details = {
        "configuration_id": configuration_id,
        "device_id": device_id,
        "mount_action_id": str(device_action.get("id") or ""),
        **{key: str(value) for key, value in details.items() if value is not None},
    }
    return RefreshNotice(
        code=code.value,
        external_id=device_id,
        details=tuple(sorted(normalized_details.items())),
    )


def _log_resolution_notices(
    notices: list[RefreshNotice],
    policy: IncompleteMountChainPolicy,
) -> None:
    for notice in notices:
        details = dict(notice.details)
        if notice.code in {
            MountLocationNoticeCode.STATIC_LOCATION_TOLERANCE_USED.value,
            MountLocationNoticeCode.DIRECT_DEVICE_OFFSET_USED.value,
        }:
            logger.info("SMS mount-location fallback %s: %s", notice.code, details)
        elif notice.code in {
            MountLocationNoticeCode.PARENT_MOUNT_ACTION_MISSING.value,
            MountLocationNoticeCode.MOUNT_CHAIN_CYCLE.value,
            MountLocationNoticeCode.STATIC_LOCATION_NOT_ACTIVE.value,
        }:
            logger.warning(
                "SMS mount-location resolution notice %s (policy=%s): %s",
                notice.code,
                policy.value,
                details,
            )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_sms_timepoint(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt_timezone.utc)
    return parsed
