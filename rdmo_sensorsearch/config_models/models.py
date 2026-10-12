from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from rdmo_sensorsearch.config_models.backend_settings import BackendSettings
from rdmo_sensorsearch.config_models.consumer_settings import DataCollectionSyncSettings, HandlerCatalogSettings, SearchSettings
from rdmo_sensorsearch.contracts import DeviceDetailSettings


@dataclass(frozen=True)
class CatalogScopeConfig:
    catalog_uris: tuple[str, ...] = ()

    def matches(self, catalog_uri: str) -> bool:
        return not self.catalog_uris or catalog_uri in self.catalog_uris


@dataclass(frozen=True)
class AuthConfig:
    source: Literal["sms_user_token"] = "sms_user_token"


@dataclass(frozen=True)
class BackendDefinition:
    name: str
    type: Literal["sms", "o2a", "gipp"]
    base_url: str
    settings: BackendSettings
    auth: AuthConfig | None = None
    device_id_prefix: str | None = None
    configuration_id_prefix: str | None = None

    def prefix(self, resource: Literal["device", "configuration"]) -> str:
        value = self.device_id_prefix if resource == "device" else self.configuration_id_prefix
        if value is None:
            raise ValueError(f"Backend {self.name!r} has no {resource} namespace")
        return value


@dataclass(frozen=True)
class ProviderInstanceConfig:
    provider_name: str
    backend: str
    settings: SearchSettings


@dataclass(frozen=True)
class SearchProviderConfig:
    minimum_search_length: int
    providers: tuple[ProviderInstanceConfig, ...]
    filter_sms_devices_by_selected_configuration: bool = False


@dataclass(frozen=True)
class ProjectOptionsCatalogConfig:
    scope: CatalogScopeConfig
    source_attribute_uri: str


@dataclass(frozen=True)
class ProjectOptionsProviderConfig:
    catalogs: tuple[ProjectOptionsCatalogConfig, ...]


@dataclass(frozen=True)
class DataCollectionSyncCatalogConfig:
    scope: CatalogScopeConfig
    settings: DataCollectionSyncSettings


@dataclass(frozen=True)
class DataCollectionVariableSyncConfig:
    catalogs: tuple[DataCollectionSyncCatalogConfig, ...]


@dataclass(frozen=True)
class DeviceDetailSyncCatalogConfig:
    scope: CatalogScopeConfig
    settings: DeviceDetailSettings


@dataclass(frozen=True)
class DeviceDetailSyncConfig:
    catalogs: tuple[DeviceDetailSyncCatalogConfig, ...]


@dataclass(frozen=True)
class MetadataRefreshActionConfig:
    scope: CatalogScopeConfig
    kind: str
    trigger_attribute_uri: str
    configuration_search_attribute_uri: str | None = None
    device_search_attribute_uri: str | None = None
    status_attribute_uri: str | None = None
    message_attribute_uri: str | None = None
    timestamp_attribute_uri: str | None = None
    replace_existing_collections: bool = False
    require_configuration_period: bool = False
    input_attribute_uris: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetadataRefreshConfig:
    configuration_search_attribute_uri: str | None
    device_search_attribute_uri: str | None
    actions: tuple[MetadataRefreshActionConfig, ...]


@dataclass(frozen=True)
class HandlerInstanceConfig:
    backend: str
    device_text_prefix: str | None = None
    item_text_prefix: str = "O2A Item"
    item_text_template: str = "{configuration} {prefix}({item_id}): {name}{serial}"


@dataclass(frozen=True)
class HandlerCatalogConfig:
    scope: CatalogScopeConfig
    search_attribute_uri: str
    attribute_mapping: Mapping[str, str]
    settings: HandlerCatalogSettings


@dataclass(frozen=True)
class HandlerConfig:
    handler_name: str
    instances: tuple[HandlerInstanceConfig, ...]
    catalogs: tuple[HandlerCatalogConfig, ...]


@dataclass(frozen=True)
class PluginConfig:
    backends: Mapping[str, BackendDefinition]
    device_search: SearchProviderConfig
    configuration_search: SearchProviderConfig
    project_configuration_devices: ProjectOptionsProviderConfig
    project_data_collection_devices: ProjectOptionsProviderConfig
    data_collection_variable_sync: DataCollectionVariableSyncConfig
    device_detail_sync: DeviceDetailSyncConfig
    metadata_refresh: MetadataRefreshConfig
    handlers: Mapping[str, HandlerConfig]

    def backend(self, name: str) -> BackendDefinition:
        return self.backends[name]

    def search_provider(self, section_name: str) -> SearchProviderConfig:
        return {"DeviceSearchProvider": self.device_search, "ConfigurationSearchProvider": self.configuration_search}[
            section_name
        ]

    def project_options(self, section_name: str) -> ProjectOptionsProviderConfig:
        return {
            "ProjectConfigurationDevicesProvider": self.project_configuration_devices,
            "ProjectDataCollectionDevicesProvider": self.project_data_collection_devices,
        }[section_name]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PluginConfig:
        from rdmo_sensorsearch.config_models.parsing import parse_plugin_config

        return parse_plugin_config(data)
