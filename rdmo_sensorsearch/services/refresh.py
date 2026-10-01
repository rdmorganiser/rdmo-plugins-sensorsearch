"""Structured results shared by synchronization workflows and signal adapters."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class RefreshKind(str, Enum):
    CONFIGURATION = "configuration"
    DEVICE = "device"
    ALL_CONFIGURATIONS = "all_configurations"
    ALL_DEVICES = "all_devices"


@dataclass(frozen=True)
class RefreshAction:
    kind: RefreshKind
    trigger_attribute_uri: str
    configuration_search_attribute_uri: str
    device_search_attribute_uri: str
    status_attribute_uri: str | None = None
    message_attribute_uri: str | None = None
    timestamp_attribute_uri: str | None = None
    replace_existing_collections: bool = False
    require_configuration_period: bool = False
    input_attribute_uris: tuple[str, ...] = ()

    @property
    def source_attribute_uri(self) -> str | None:
        if self.kind is RefreshKind.CONFIGURATION:
            return self.configuration_search_attribute_uri
        if self.kind is RefreshKind.DEVICE:
            return self.device_search_attribute_uri
        return None

    @property
    def state_attribute_uris(self) -> tuple[str, ...]:
        return tuple(
            attribute_uri
            for attribute_uri in (
                self.trigger_attribute_uri,
                self.status_attribute_uri,
                self.message_attribute_uri,
                self.timestamp_attribute_uri,
            )
            if attribute_uri
        )


@dataclass(frozen=True)
class RefreshError:
    external_id: str
    message: str


@dataclass(frozen=True)
class RefreshNotice:
    """Nonfatal synchronization detail suitable for logs and aggregated feedback."""

    code: str
    external_id: str = ""
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RefreshResult:
    requested_count: int
    refreshed_count: int
    errors: tuple[RefreshError, ...] = ()
    device_requested_count: int = 0
    device_refreshed_count: int = 0
    notices: tuple[RefreshNotice, ...] = ()

    @property
    def status(self) -> str:
        if not self.errors:
            return "success"
        if self.refreshed_count:
            return "partial"
        return "failed"


def combine_refresh_results(results: Iterable[RefreshResult]) -> RefreshResult:
    results = tuple(results)
    return RefreshResult(
        requested_count=sum(result.requested_count for result in results),
        refreshed_count=sum(result.refreshed_count for result in results),
        errors=tuple(error for result in results for error in result.errors),
        device_requested_count=sum(result.device_requested_count for result in results),
        device_refreshed_count=sum(result.device_refreshed_count for result in results),
        notices=tuple(notice for result in results for notice in result.notices),
    )


def format_refresh_message(kind: RefreshKind, result: RefreshResult, refreshed_label: str = "") -> str:
    target_name = {
        RefreshKind.CONFIGURATION: "configuration",
        RefreshKind.DEVICE: "device",
        RefreshKind.ALL_CONFIGURATIONS: "configurations",
        RefreshKind.ALL_DEVICES: "devices",
    }[kind]

    if not result.errors:
        if kind in {RefreshKind.CONFIGURATION, RefreshKind.DEVICE} and refreshed_label:
            message = f"Success: {refreshed_label} was refreshed."
            if kind is RefreshKind.CONFIGURATION:
                message = f"{message} {_format_device_refresh_count(result.device_refreshed_count)}"
            return _truncate_message(_append_notice_summary(message, result.notices))
        if result.requested_count == 0:
            return f"Success: No {target_name} were available to refresh."
        message = f"Success: {result.refreshed_count} of {result.requested_count} {target_name} refreshed."
        if kind is RefreshKind.ALL_CONFIGURATIONS:
            message = f"{message} {_format_device_refresh_count(result.device_refreshed_count)}"
        return _truncate_message(_append_notice_summary(message, result.notices))

    prefix = f"{result.status.capitalize()}: {result.refreshed_count} of {result.requested_count} {target_name} refreshed."
    if kind is RefreshKind.ALL_CONFIGURATIONS:
        prefix = f"{prefix} {_format_device_refresh_count(result.device_refreshed_count)}"
    details = "; ".join(
        f"{error.external_id}: {error.message}" if error.external_id else error.message for error in result.errors
    )
    return _truncate_message(_append_notice_summary(f"{prefix} {details}", result.notices))


def _truncate_message(message: str, max_length: int = 1000) -> str:
    if len(message) <= max_length:
        return message
    return f"{message[: max_length - 3]}..."


def _format_device_refresh_count(count: int) -> str:
    if count == 1:
        return "1 device was refreshed."
    return f"{count} devices were refreshed."


def _append_notice_summary(message: str, notices: tuple[RefreshNotice, ...]) -> str:
    summaries = _summarize_notices(notices)
    if summaries:
        message = f"{message} Location metadata: {'; '.join(summaries)}."
    owner_devices = {notice.external_id or notice.details for notice in notices if notice.code == "owner_contact_unresolved"}
    if owner_devices:
        summary = _format_notice_count("owner contact unavailable", len(owner_devices))
        message = f"{message} Owner metadata: {summary}."
    return message


def _summarize_notices(notices: tuple[RefreshNotice, ...]) -> list[str]:
    labels = {
        "static_location_end_tolerance_used": "static-location time fallback used",
        "static_location_not_found": "static location unavailable",
        "static_location_not_active_at_reference_time": "static location unavailable at the selected time",
        "static_location_height_missing": "station height unavailable",
        "static_location_label_missing": "site name unavailable",
        "parent_mount_action_missing": "parent mount unavailable",
        "mount_chain_cycle": "cyclic mount chain found",
        "device_offset_missing": "device offset unavailable",
        "device_offset_invalid": "invalid device offset ignored",
        "direct_device_offset_fallback_used": "direct device offset fallback used",
    }
    unique_notices = {
        (notice.code, notice.external_id, () if notice.external_id else notice.details)
        for notice in notices
        if notice.code in labels
    }
    counts: dict[str, int] = {}
    for code, _external_id, _details in unique_notices:
        counts[code] = counts.get(code, 0) + 1
    return [_format_notice_count(label, counts[code]) for code, label in labels.items() if code in counts]


def _format_notice_count(label: str, count: int) -> str:
    device_label = "device" if count == 1 else "devices"
    return f"{label} for {count} {device_label}"
