from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from rdmo_sensorsearch.contracts import SelectedDevice


@dataclass(frozen=True)
class ConfigurationIdentity:
    """Stable identity used to group materialized device blocks."""

    configuration_key: str
    label: str
    external_id: str | None


@dataclass(frozen=True)
class DeviceBlockReference:
    """Existing RDMO device-block index needed by the planner."""

    set_index: int


@dataclass(frozen=True)
class DeviceBlockPlan:
    """One device block to retain or create during reconciliation."""

    device: SelectedDevice
    block_key: str
    set_index: int
    handler_binding: Any
    needs_metadata_write: bool
    needs_refresh: bool
    set_prefix: str = ""
    configuration_external_id: str | None = None


@dataclass(frozen=True)
class DevicePlanningFailure:
    external_id: str
    message: str


@dataclass(frozen=True)
class DeviceDetailReconciliationPlan:
    """Pure reconciliation result consumed by the Django write adapter."""

    blocks: tuple[DeviceBlockPlan, ...]
    stale_blocks: tuple[DeviceBlockReference, ...]
    failures: tuple[DevicePlanningFailure, ...]


HandlerResolver = Callable[[str], Any | None]
MetadataStateReader = Callable[[SelectedDevice, str, int, Any], bool]
RefreshStateReader = Callable[[int], bool]


def plan_device_detail_reconciliation(
    *,
    selected_devices: Iterable[SelectedDevice],
    configuration_key: str,
    configuration_external_id: str | None,
    set_prefix: str,
    existing_blocks: Mapping[str, DeviceBlockReference],
    next_set_index: int,
    resolve_handler: HandlerResolver,
    metadata_is_current: MetadataStateReader,
    refresh_is_required: RefreshStateReader,
    force_refresh: bool = False,
) -> DeviceDetailReconciliationPlan:
    """Plan device-block changes without accessing Django or remote backends."""

    devices = unique_selected_devices(selected_devices)
    desired_block_keys = {compose_device_block_key(configuration_key, device.external_id) for device in devices}
    stale_blocks = tuple(block for block_key, block in existing_blocks.items() if block_key not in desired_block_keys)
    active_blocks = {block_key: block for block_key, block in existing_blocks.items() if block_key in desired_block_keys}

    plans = []
    failures = []
    available_set_index = next_set_index
    for device in devices:
        block_key = compose_device_block_key(configuration_key, device.external_id)
        block = active_blocks.get(block_key)
        handler_binding = resolve_handler(device.external_id)
        if handler_binding is None:
            failures.append(
                DevicePlanningFailure(
                    external_id=device.external_id,
                    message="No matching device handler is configured.",
                )
            )
            continue

        if block is None:
            set_index = available_set_index
            available_set_index += 1
            needs_metadata_write = True
            needs_refresh = True
        else:
            set_index = block.set_index
            needs_metadata_write = not metadata_is_current(
                device,
                block_key,
                set_index,
                handler_binding,
            )
            needs_refresh = force_refresh or refresh_is_required(set_index)

        plans.append(
            DeviceBlockPlan(
                device=device,
                block_key=block_key,
                set_index=set_index,
                handler_binding=handler_binding,
                needs_metadata_write=needs_metadata_write,
                needs_refresh=needs_refresh,
                set_prefix=set_prefix,
                configuration_external_id=configuration_external_id,
            )
        )

    return DeviceDetailReconciliationPlan(
        blocks=tuple(plans),
        stale_blocks=stale_blocks,
        failures=tuple(failures),
    )


def unique_selected_devices(selected_devices: Iterable[SelectedDevice]) -> tuple[SelectedDevice, ...]:
    """Deduplicate devices by external ID while retaining source order."""

    unique = []
    seen = set()
    for device in selected_devices:
        if not device.external_id or device.external_id in seen:
            continue
        seen.add(device.external_id)
        unique.append(device)
    return tuple(unique)


def parse_external_id(external_id: str) -> tuple[str | None, str | None]:
    if ":" not in external_id:
        return None, external_id or None
    prefix, value = external_id.split(":", 1)
    return prefix or None, value or None


def parse_device_block_key(external_id: str) -> tuple[str | None, str | None]:
    if "||" not in external_id:
        return None, None
    configuration_key, device_external_id = external_id.split("||", 1)
    return configuration_key or None, device_external_id or None


def configuration_key_from_device_block(external_id: str) -> str | None:
    configuration_key, device_external_id = parse_device_block_key(external_id)
    if not configuration_key or not device_external_id:
        return None
    return configuration_key


def compose_device_block_key(configuration_key: str, device_external_id: str) -> str:
    return f"{configuration_key}||{device_external_id}"


def base_device_text(text: str) -> str:
    if ": " in text:
        return text.split(": ", 1)[1]
    return text
