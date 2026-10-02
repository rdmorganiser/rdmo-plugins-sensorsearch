"""Typed application settings, independent of backend connection definitions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class O2ARegistryItemCatalogSettings:
    device_collection_attribute_uri: str | None = None
    device_link_attribute_uri: str | None = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/device-link"
    managed_attribute_uris: tuple[str, ...] = ()
    materialize_device_details: bool = True
    supports_mount_location_lookup: bool = False
    supports_mount_period_lookup: bool = False


@dataclass(frozen=True)
class SensorManagementSystemDeviceCatalogSettings:
    device_collection_attribute_uri: str | None = None
    device_link_attribute_uri: str | None = None
    managed_attribute_uris: tuple[str, ...] = ()
    materialize_device_details: bool = True
    supports_mount_location_lookup: bool = True
    supports_mount_period_lookup: bool = True


@dataclass(frozen=True)
class SensorManagementSystemConfigurationCatalogSettings:
    api_link_attribute_uri: str | None = None
    configuration_collection_attribute_uri: str | None = None
    configuration_end_date_path: str | None = "data.attributes.end_date"
    configuration_start_date_path: str | None = "data.attributes.start_date"
    device_collection_attribute_uri: str | None = None
    frontend_link_attribute_uri: str | None = None
    latitude_attribute_uri: str | None = None
    location_attribute_uri: str | None = None
    longitude_attribute_uri: str | None = None
    managed_attribute_uris: tuple[str, ...] = ()
    membership_filter_enabled: bool = False
    membership_filter_end_attribute_uri: str | None = None
    membership_filter_start_attribute_uri: str | None = None
    selected_devices_attribute_uri: str | None = None
    selected_devices_page_uri: str | None = None


@dataclass(frozen=True)
class O2ARegistryMissionCatalogSettings:
    api_link_attribute_uri: str | None = None
    configuration_collection_attribute_uri: str | None = None
    date_mapping_paths: tuple[str, ...] = ("startDate", "endDate")
    datetime_output_format: str | None = "%Y-%m-%d %H:%M"
    device_collection_attribute_uri: str | None = None
    frontend_link_attribute_uri: str | None = None
    managed_attribute_uris: tuple[str, ...] = ()
    mission_end_date_path: str | None = "endDate"
    mission_start_date_path: str | None = "startDate"
    selected_devices_attribute_uri: str | None = None
    selected_devices_page_uri: str | None = None


@dataclass(frozen=True)
class GIPPInstrumentCatalogSettings:
    managed_attribute_uris: tuple[str, ...] = ()


HandlerCatalogSettings = (
    O2ARegistryItemCatalogSettings
    | SensorManagementSystemDeviceCatalogSettings
    | SensorManagementSystemConfigurationCatalogSettings
    | O2ARegistryMissionCatalogSettings
    | GIPPInstrumentCatalogSettings
)


@dataclass(frozen=True)
class SearchSettings:
    text_prefix: str
    max_hits: int = 10
    option_id: str | None = None
    option_text: str | None = None


@dataclass(frozen=True)
class O2AMissionSearchSettings(SearchSettings):
    where_template: str = 'name=ILIKE="*{query}*"'
    sorts: str = ""
    offset: int = 0


@dataclass(frozen=True)
class DataCollectionSyncSettings:
    devices_attribute_uri: str = "https://rdmorganiser.github.io/terms/domain/project/dataset/collaboration_tools"
    device_collection_attribute_uri: str = "https://rdmo-sandbox.gfz-potsdam.de/terms/domain/moses/instruments/id"
    parameter_name_attribute_uri: str = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/preservation/parameter/name"
    parameter_unit_attribute_uri: str = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/preservation/parameter/unit"
    variable_attribute_uri: str = "https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-variable"
    unit_attribute_uri: str = "https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-unit"
