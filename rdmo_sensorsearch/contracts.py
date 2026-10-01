"""Framework-independent data exchanged by handlers, services and workflows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from datetime import timezone as dt_timezone
from typing import Any, Generic, Protocol, TypeVar


class ScalarScopeResolver(Protocol):
    def resolve(
        self, source_attribute_id: int, target_attribute_id: int, source_scope: tuple[str, int]
    ) -> list[tuple[str, int]]: ...


@dataclass(frozen=True)
class RefreshNotice:
    """Nonfatal synchronization detail suitable for logs and aggregated feedback."""

    code: str
    external_id: str = ""
    details: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class SelectedDevice:
    """A backend-neutral device selected as part of a configuration."""

    text: str
    external_id: str
    instrument_start: str | None = None
    instrument_end: str | None = None
    station_height_amsl: float | None = None
    vertical_surface_offset: float | None = None
    site_name: str | None = None
    mount_location_resolved: bool = False
    mount_location_notices: tuple[RefreshNotice, ...] = ()


@dataclass(frozen=True)
class DeviceDetailSettings:
    device_details_page_uri: str
    device_optional_info_page_uri: str
    configuration_collection_attribute_uri: str
    device_link_attribute_uri: str
    usage_technology_attribute_uri: str
    instrument_start_attribute_uri: str
    instrument_end_attribute_uri: str
    instrument_location_amsl_attribute_uri: str
    surface_offset_z_attribute_uri: str
    site_name_attribute_uri: str
    serial_number_attribute_uri: str


@dataclass(frozen=True)
class ConfigurationPeriod:
    start: datetime
    end: datetime | None = None

    @property
    def formatted(self) -> tuple[str, str | None]:
        return (
            self.start.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M"),
            self.end.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M") if self.end else None,
        )


@dataclass(frozen=True)
class CollectionAssignment:
    attribute_uri: str
    page_uri: str
    values: tuple[dict[str, Any], ...] = ()
    replace_existing: bool = True


@dataclass(frozen=True)
class MergedTextScalar:
    """Append names to a creatable option answer; an empty tuple preserves it."""

    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class RefreshDeviceDetails:
    """Describe follow-up work; workflows supply storage and authentication."""

    selected_devices: tuple[SelectedDevice, ...]
    selected_devices_attribute_uri: str
    device_collection_attribute_uri: str


@dataclass(frozen=True)
class HandlerResult:
    mapped_values: Mapping[str, Any] = field(default_factory=dict)
    collections: tuple[CollectionAssignment, ...] = ()
    effects: tuple[RefreshDeviceDetails, ...] = ()
    notices: tuple[RefreshNotice, ...] = ()


@dataclass(frozen=True)
class HandlerExecutionContext:
    preserve_existing_collections: bool = False
    require_configuration_period: bool = False
    device_detail_settings: DeviceDetailSettings | None = None
    configuration_external_id: str | None = None
    configuration_period: ConfigurationPeriod | None = None


T = TypeVar("T")


@dataclass(frozen=True)
class BackendSuccess(Generic[T]):
    value: T
    notices: tuple[RefreshNotice, ...] = ()
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class BackendFailure:
    errors: tuple[str, ...]


BackendResult = BackendSuccess[T] | BackendFailure


@dataclass(frozen=True)
class SearchRecord:
    identifier: str
    attributes: Mapping[str, Any]


@dataclass(frozen=True)
class DeviceMetadata:
    document: dict[str, Any]
    owner_organizations: tuple[str, ...] = ()
    frontend_link: str | None = None


@dataclass(frozen=True)
class ConfigurationMetadata:
    document: dict[str, Any]
    api_link: str | None = None
    frontend_link: str | None = None
    identifier: str | None = None


@dataclass(frozen=True)
class MountPeriod:
    start: str
    end: str | None
    action: dict[str, Any]
    device_actions: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class MountLocation:
    station_height_amsl: float | None = None
    vertical_surface_offset: float | None = None
    site_name: str | None = None


@dataclass(frozen=True)
class ConfigurationMember:
    identifier: str
    attributes: Mapping[str, Any]
    instrument_start: str | None
    instrument_end: str | None
    location: MountLocation
    notices: tuple[RefreshNotice, ...] = ()


@dataclass(frozen=True)
class StaticLocation:
    latitude: Any
    longitude: Any


@dataclass(frozen=True)
class ConfigurationMembership:
    members: tuple[ConfigurationMember, ...]
    static_location: StaticLocation | None = None


class DeviceSearch(Protocol):
    def search_devices(
        self, query: str, *, limit: int, auth_token: str | None = None
    ) -> BackendResult[tuple[SearchRecord, ...]]: ...


class ConfigurationSearch(Protocol):
    def search_configurations(
        self, query: str, *, limit: int, auth_token: str | None = None
    ) -> BackendResult[tuple[SearchRecord, ...]]: ...


class DeviceMetadataSource(Protocol):
    def get_device(self, device_id: str, *, auth_token: str | None = None) -> BackendResult[DeviceMetadata]: ...


class ConfigurationMetadataSource(Protocol):
    def get_configuration(
        self, configuration_id: str, *, auth_token: str | None = None
    ) -> BackendResult[ConfigurationMetadata]: ...


class DeviceMountSource(Protocol):
    def get_mount_period(
        self, device_id: str, configuration_id: str, *, serial_number: str | None = None, auth_token: str | None = None
    ) -> BackendResult[MountPeriod | None]: ...

    def get_mount_location(
        self,
        device_id: str,
        configuration_id: str,
        *,
        period: MountPeriod | None = None,
        best_effort: bool = False,
        auth_token: str | None = None,
    ) -> BackendResult[MountLocation | None]: ...


class DeviceSource(DeviceMetadataSource, DeviceMountSource, Protocol):
    pass


class ConfigurationSource(ConfigurationMetadataSource, Protocol):
    def get_configuration_members(
        self, configuration: ConfigurationMetadata, *, period: ConfigurationPeriod | None = None, auth_token: str | None = None
    ) -> BackendResult[ConfigurationMembership]: ...

    def get_static_location(
        self, configuration_id: str, *, auth_token: str | None = None
    ) -> BackendResult[StaticLocation | None]: ...
