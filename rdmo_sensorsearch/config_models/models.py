from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rdmo_sensorsearch.config_models.contracts import (
    HANDLER_DEFAULT_ID_PREFIXES,
    PROVIDER_DEFAULT_ID_PREFIXES,
)


@dataclass(frozen=True)
class CatalogScopeConfig:
    catalog_uris: tuple[str, ...] = ()

    def matches(self, catalog_uri: str) -> bool:
        return not self.catalog_uris or catalog_uri in self.catalog_uris


@dataclass(frozen=True)
class ProviderInstanceConfig:
    provider_name: str
    settings: Mapping[str, Any]

    @property
    def id_prefix(self) -> str | None:
        value = self.settings.get("id_prefix", PROVIDER_DEFAULT_ID_PREFIXES.get(self.provider_name))
        return value if isinstance(value, str) else None


@dataclass(frozen=True)
class SearchProviderConfig:
    minimum_search_length: int
    providers: tuple[ProviderInstanceConfig, ...]
    provider_defaults: Mapping[str, Mapping[str, Any]]
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
    settings: Mapping[str, Any]


@dataclass(frozen=True)
class DataCollectionVariableSyncConfig:
    catalogs: tuple[DataCollectionSyncCatalogConfig, ...]


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
class HandlerCatalogConfig:
    scope: CatalogScopeConfig
    search_attribute_uri: str | None
    attribute_mapping: Mapping[str, str]
    settings: Mapping[str, Any]


@dataclass(frozen=True)
class HandlerConfig:
    handler_name: str
    defaults: Mapping[str, Any]
    default_attribute_mapping: Mapping[str, str]
    backend_defaults: Mapping[str, Any]
    backends: tuple[Mapping[str, Any], ...]
    catalogs: tuple[HandlerCatalogConfig, ...]

    @property
    def id_prefixes(self) -> tuple[str, ...]:
        if self.backends:
            return tuple(
                prefix
                for backend in self.backends
                if isinstance((prefix := backend.get("id_prefix", self.backend_defaults.get("id_prefix"))), str)
            )
        prefix = self.defaults.get("id_prefix", HANDLER_DEFAULT_ID_PREFIXES.get(self.handler_name))
        return (prefix,) if isinstance(prefix, str) else ()


@dataclass(frozen=True)
class PluginConfig:
    device_search: SearchProviderConfig
    configuration_search: SearchProviderConfig
    project_configuration_devices: ProjectOptionsProviderConfig
    project_data_collection_devices: ProjectOptionsProviderConfig
    data_collection_variable_sync: DataCollectionVariableSyncConfig
    metadata_refresh: MetadataRefreshConfig
    handlers: Mapping[str, HandlerConfig]
    raw: Mapping[str, Any]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PluginConfig:
        from rdmo_sensorsearch.config_models.parsing import parse_plugin_config

        return parse_plugin_config(data)
