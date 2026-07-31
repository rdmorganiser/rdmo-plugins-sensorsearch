from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any


@dataclass(frozen=True)
class ResolvedMountLocation:
    height_amsl: float | None
    vertical_surface_offset: float | None
    site_name: str | None


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


def resolve_mount_location(
    device_action: dict,
    device_actions: list[dict],
    platform_actions: list[dict],
    static_location_actions: list[dict],
    *,
    now: datetime | None = None,
    reference_time: datetime | None = None,
) -> ResolvedMountLocation:
    if reference_time is None:
        reference_time = _action_reference_time(device_action, now=now)
    else:
        reference_time = _clamp_to_action_period(device_action, reference_time)
    mount_chain, chain_complete = _mount_chain(
        device_action,
        device_actions,
        platform_actions,
        reference_time,
    )

    vertical_surface_offset = sum(_offset_z(action) for action in mount_chain) if chain_complete else None

    offset_below_anchor = 0.0
    height_amsl = None
    for action in mount_chain:
        explicit_height = _number(action.get("attributes", {}).get("z"))
        if explicit_height is not None:
            height_amsl = explicit_height + offset_below_anchor
            break
        offset_below_anchor += _offset_z(action)

    static_location = select_static_location_action(static_location_actions, reference_time)
    if height_amsl is None and chain_complete and static_location is not None:
        base_height = _number(static_location.get("attributes", {}).get("z"))
        if base_height is not None and vertical_surface_offset is not None:
            height_amsl = base_height + vertical_surface_offset

    site_name = None
    if static_location is not None:
        label = static_location.get("attributes", {}).get("label")
        if isinstance(label, str):
            site_name = label

    return ResolvedMountLocation(
        height_amsl=height_amsl,
        vertical_surface_offset=vertical_surface_offset,
        site_name=site_name,
    )


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
) -> tuple[list[dict], bool]:
    chain = [device_action]
    visited = {_action_key(device_action)}
    current_action = device_action

    while True:
        parent_type, parent_id = _parent_ref(current_action)
        if parent_type is None or parent_id is None:
            return chain, True

        candidates = platform_actions if parent_type == "platform" else device_actions
        parent_action = _select_entity_action(candidates, parent_type, parent_id, reference_time)
        if parent_action is None:
            return chain, False

        action_key = _action_key(parent_action)
        if action_key in visited:
            return chain, False
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
    begin = _parse_timepoint(attrs.get("begin_date"))
    end = _parse_timepoint(attrs.get("end_date"))
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
    begin = _parse_timepoint(attrs.get("begin_date"))
    end = _parse_timepoint(attrs.get("end_date"))
    if begin is not None and reference_time < begin:
        return begin
    if end is not None and reference_time >= end:
        if begin is None or end > begin:
            return end - timedelta(microseconds=1)
        return end
    return reference_time


def _action_contains(action: dict, reference_time: datetime) -> bool:
    attrs = action.get("attributes", {})
    begin = _parse_timepoint(attrs.get("begin_date"))
    end = _parse_timepoint(attrs.get("end_date"))
    if begin is not None and reference_time < begin:
        return False
    return end is None or reference_time < end


def _action_begin_sort_key(action: dict) -> float:
    begin = _parse_timepoint(action.get("attributes", {}).get("begin_date"))
    return begin.timestamp() if begin is not None else float("-inf")


def _action_key(action: dict) -> tuple[str | None, str | None]:
    return action.get("type"), action.get("id")


def _offset_z(action: dict) -> float:
    return _number(action.get("attributes", {}).get("offset_z")) or 0.0


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _parse_timepoint(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt_timezone.utc)
    return parsed
