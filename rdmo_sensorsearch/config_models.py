from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

TOP_LEVEL_SECTIONS = frozenset(
    {
        "DeviceSearchProvider",
        "ConfigurationSearchProvider",
        "ProjectConfigurationDevicesProvider",
        "ProjectDataCollectionDevicesProvider",
        "DataCollectionVariableSync",
        "MetadataRefresh",
        "handlers",
    }
)

DEVICE_PROVIDER_NAMES = frozenset(
    {
        "O2ARegistryItemProvider",
        "SensorManagementSystemDeviceProvider",
        "GIPPInstrumentProvider",
    }
)
CONFIGURATION_PROVIDER_NAMES = frozenset(
    {
        "SensorManagementSystemConfigurationProvider",
        "O2ARegistryMissionProvider",
    }
)

PROVIDER_DEFAULT_ID_PREFIXES = {
    "O2ARegistryItemProvider": "o2aregistry",
    "O2ARegistryMissionProvider": "o2amission",
    "GIPPInstrumentProvider": "gfzgipp",
}
PROVIDER_HANDLER_NAMES = {
    "O2ARegistryItemProvider": "O2ARegistryItemHandler",
    "O2ARegistryMissionProvider": "O2ARegistryMissionHandler",
    "SensorManagementSystemDeviceProvider": "SensorManagementSystemDeviceHandler",
    "SensorManagementSystemConfigurationProvider": "SensorManagementSystemConfigurationHandler",
    "GIPPInstrumentProvider": "GIPPInstrumentHandler",
}
HANDLER_DEFAULT_ID_PREFIXES = {
    "O2ARegistryItemHandler": "o2aregistry",
    "O2ARegistryMissionHandler": "o2amission",
    "GIPPInstrumentHandler": "gfzgipp",
}

COMMON_PROVIDER_SETTINGS = frozenset({"id_prefix", "text_prefix", "base_url", "max_hits"})
PROVIDER_SETTINGS = {
    "O2ARegistryItemProvider": COMMON_PROVIDER_SETTINGS | {"query_url"},
    "O2ARegistryMissionProvider": COMMON_PROVIDER_SETTINGS
    | {"query_url", "where_template", "sorts", "offset", "option_id", "option_text"},
    "SensorManagementSystemDeviceProvider": COMMON_PROVIDER_SETTINGS | {"query_url", "option_id", "option_text"},
    "SensorManagementSystemConfigurationProvider": COMMON_PROVIDER_SETTINGS | {"query_url", "option_id", "option_text"},
    "GIPPInstrumentProvider": COMMON_PROVIDER_SETTINGS | {"instruments_url", "option_id", "option_text"},
}

COMMON_HANDLER_SETTINGS = frozenset(
    {
        "id_prefix",
        "base_url",
        "search_attribute_uri",
        "managed_attribute_uris",
        "period_start_attribute_uri",
        "period_end_attribute_uri",
    }
)
DEVICE_DETAIL_SETTINGS = frozenset(
    {
        "materialize_device_details",
        "device_collection_attribute_uri",
        "device_link_attribute_uri",
        "supports_mount_location_lookup",
        "supports_mount_period_lookup",
    }
)
CONFIGURATION_MEMBERSHIP_SETTINGS = frozenset(
    {
        "configuration_collection_attribute_uri",
        "selected_devices_attribute_uri",
        "selected_devices_page_uri",
        "device_collection_attribute_uri",
        "frontend_link_attribute_uri",
        "api_link_attribute_uri",
    }
)
HANDLER_SETTINGS = {
    "O2ARegistryItemHandler": COMMON_HANDLER_SETTINGS
    | DEVICE_DETAIL_SETTINGS
    | {
        "item_url",
        "contacts_url",
        "parameters_url",
        "units_url",
        "item_api_link_template",
        "item_frontend_link_template",
    },
    "SensorManagementSystemDeviceHandler": COMMON_HANDLER_SETTINGS
    | DEVICE_DETAIL_SETTINGS
    | {
        "device_url",
        "contact_url",
        "device_mount_actions_url",
        "configuration_device_mount_actions_url",
        "configuration_platform_mount_actions_url",
        "configuration_static_location_actions_url",
        "backend_link_marker",
    },
    "SensorManagementSystemConfigurationHandler": COMMON_HANDLER_SETTINGS
    | CONFIGURATION_MEMBERSHIP_SETTINGS
    | {
        "configuration_url",
        "device_url",
        "device_mount_action_url",
        "device_mount_actions_url",
        "platform_mount_actions_url",
        "mounting_action_timepoints_url",
        "static_location_actions_url",
        "device_mount_action_page_size",
        "platform_mount_action_page_size",
        "static_location_action_page_size",
        "max_collection_pages",
        "configuration_self_link_path",
        "configuration_start_date_path",
        "configuration_end_date_path",
        "frontend_link_suffix",
        "backend_link_marker",
        "device_id_prefix",
        "device_text_prefix",
        "location_attribute_uri",
        "latitude_attribute_uri",
        "longitude_attribute_uri",
    },
    "O2ARegistryMissionHandler": COMMON_HANDLER_SETTINGS
    | CONFIGURATION_MEMBERSHIP_SETTINGS
    | {
        "mission_url",
        "mission_items_url",
        "item_url",
        "mission_item_page_size",
        "max_collection_pages",
        "item_id_prefix",
        "item_text_prefix",
        "item_text_template",
        "mission_start_date_path",
        "mission_end_date_path",
        "date_mapping_paths",
        "datetime_output_format",
        "api_link_template",
        "frontend_link_template",
    },
    "GIPPInstrumentHandler": COMMON_HANDLER_SETTINGS | {"json_url"},
}

CATALOG_SCOPE_KEYS = frozenset({"catalog_uri", "catalog_uris"})
STRING_SEQUENCE_SETTINGS = frozenset({"managed_attribute_uris", "date_mapping_paths", "input_attribute_uris"})
BOOLEAN_SETTINGS = frozenset(
    {
        "filter_sms_devices_by_selected_configuration",
        "materialize_device_details",
        "supports_mount_location_lookup",
        "supports_mount_period_lookup",
        "replace_existing_collections",
        "require_configuration_period",
    }
)
POSITIVE_INTEGER_SETTINGS = frozenset(
    {
        "min_search_len",
        "max_hits",
        "device_mount_action_page_size",
        "platform_mount_action_page_size",
        "static_location_action_page_size",
        "mission_item_page_size",
        "max_collection_pages",
    }
)


class ConfigValidationError(ValueError):
    def __init__(self, path: str, message: str):
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


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
        root = _require_mapping(data, "config")
        _reject_unknown_keys(root, TOP_LEVEL_SECTIONS, "config")

        device_search = _parse_search_provider(
            root.get("DeviceSearchProvider", {}),
            "DeviceSearchProvider",
            DEVICE_PROVIDER_NAMES,
            allow_sms_filter=True,
        )
        configuration_search = _parse_search_provider(
            root.get("ConfigurationSearchProvider", {}),
            "ConfigurationSearchProvider",
            CONFIGURATION_PROVIDER_NAMES,
            allow_sms_filter=False,
        )
        project_configuration_devices = _parse_project_options_provider(
            root.get("ProjectConfigurationDevicesProvider", {}),
            "ProjectConfigurationDevicesProvider",
        )
        project_data_collection_devices = _parse_project_options_provider(
            root.get("ProjectDataCollectionDevicesProvider", {}),
            "ProjectDataCollectionDevicesProvider",
        )
        data_collection_variable_sync = _parse_data_collection_sync(root.get("DataCollectionVariableSync", {}))
        metadata_refresh = _parse_metadata_refresh(root.get("MetadataRefresh", {}))
        handlers = _parse_handlers(root.get("handlers", {}))

        config = cls(
            device_search=device_search,
            configuration_search=configuration_search,
            project_configuration_devices=project_configuration_devices,
            project_data_collection_devices=project_data_collection_devices,
            data_collection_variable_sync=data_collection_variable_sync,
            metadata_refresh=metadata_refresh,
            handlers=MappingProxyType(handlers),
            raw=_freeze(root),
        )
        _validate_prefix_contract(config)
        return config


def _parse_search_provider(
    value: Any,
    path: str,
    allowed_provider_names: frozenset[str],
    *,
    allow_sms_filter: bool,
) -> SearchProviderConfig:
    data = _require_mapping(value, path)
    allowed_keys = {"min_search_len", "providers", "provider_defaults"}
    if allow_sms_filter:
        allowed_keys.add("filter_sms_devices_by_selected_configuration")
    _reject_unknown_keys(data, allowed_keys, path)

    minimum_search_length = _positive_integer(data.get("min_search_len", 3), f"{path}.min_search_len")
    filter_sms = _boolean(
        data.get("filter_sms_devices_by_selected_configuration", False),
        f"{path}.filter_sms_devices_by_selected_configuration",
    )
    provider_defaults_data = _require_mapping(data.get("provider_defaults", {}), f"{path}.provider_defaults")
    providers_data = _require_mapping(data.get("providers", {}), f"{path}.providers")

    provider_defaults: dict[str, Mapping[str, Any]] = {}
    for provider_name, settings in provider_defaults_data.items():
        _validate_provider_name(provider_name, allowed_provider_names, f"{path}.provider_defaults")
        provider_defaults[provider_name] = _parse_provider_settings(
            provider_name,
            settings,
            f"{path}.provider_defaults.{provider_name}",
        )

    providers = []
    for provider_name, definitions in providers_data.items():
        _validate_provider_name(provider_name, allowed_provider_names, f"{path}.providers")
        for index, settings in enumerate(_table_sequence(definitions, f"{path}.providers.{provider_name}")):
            parsed_settings = _parse_provider_settings(
                provider_name,
                settings,
                f"{path}.providers.{provider_name}[{index}]",
            )
            merged_settings = _merge(provider_defaults.get(provider_name), parsed_settings)
            if provider_name.startswith("SensorManagementSystem"):
                _require_string_settings(
                    merged_settings,
                    {"id_prefix", "text_prefix", "base_url"},
                    f"{path}.providers.{provider_name}[{index}]",
                )
            providers.append(
                ProviderInstanceConfig(
                    provider_name=provider_name,
                    settings=_freeze(merged_settings),
                )
            )

    return SearchProviderConfig(
        minimum_search_length=minimum_search_length,
        providers=tuple(providers),
        provider_defaults=MappingProxyType(provider_defaults),
        filter_sms_devices_by_selected_configuration=filter_sms,
    )


def _parse_project_options_provider(value: Any, path: str) -> ProjectOptionsProviderConfig:
    data = _require_mapping(value, path)
    _reject_unknown_keys(data, {"catalogs"}, path)
    catalogs = []
    for index, entry in enumerate(_table_sequence(data.get("catalogs", ()), f"{path}.catalogs")):
        entry_path = f"{path}.catalogs[{index}]"
        _reject_unknown_keys(entry, CATALOG_SCOPE_KEYS | {"source_attribute_uri"}, entry_path)
        catalogs.append(
            ProjectOptionsCatalogConfig(
                scope=_parse_catalog_scope(entry, entry_path),
                source_attribute_uri=_nonempty_string(entry.get("source_attribute_uri"), f"{entry_path}.source_attribute_uri"),
            )
        )
    return ProjectOptionsProviderConfig(catalogs=tuple(catalogs))


def _parse_data_collection_sync(value: Any) -> DataCollectionVariableSyncConfig:
    path = "DataCollectionVariableSync"
    data = _require_mapping(value, path)
    _reject_unknown_keys(data, {"catalogs"}, path)
    setting_keys = {
        "devices_attribute_uri",
        "device_collection_attribute_uri",
        "parameter_name_attribute_uri",
        "parameter_unit_attribute_uri",
        "variable_attribute_uri",
        "unit_attribute_uri",
    }
    catalogs = []
    for index, entry in enumerate(_table_sequence(data.get("catalogs", ()), f"{path}.catalogs")):
        entry_path = f"{path}.catalogs[{index}]"
        _reject_unknown_keys(entry, CATALOG_SCOPE_KEYS | setting_keys, entry_path)
        scope = _parse_catalog_scope(entry, entry_path)
        if not scope.catalog_uris:
            raise ConfigValidationError(entry_path, "catalog_uri or catalog_uris is required")
        settings = {key: _nonempty_string(entry[key], f"{entry_path}.{key}") for key in setting_keys if key in entry}
        catalogs.append(DataCollectionSyncCatalogConfig(scope=scope, settings=_freeze(settings)))
    return DataCollectionVariableSyncConfig(catalogs=tuple(catalogs))


def _parse_metadata_refresh(value: Any) -> MetadataRefreshConfig:
    path = "MetadataRefresh"
    data = _require_mapping(value, path)
    _reject_unknown_keys(
        data,
        {"configuration_search_attribute_uri", "device_search_attribute_uri", "actions"},
        path,
    )
    configuration_search_uri = _optional_nonempty_string(
        data.get("configuration_search_attribute_uri"),
        f"{path}.configuration_search_attribute_uri",
    )
    device_search_uri = _optional_nonempty_string(
        data.get("device_search_attribute_uri"),
        f"{path}.device_search_attribute_uri",
    )
    action_keys = CATALOG_SCOPE_KEYS | {
        "kind",
        "trigger_attribute_uri",
        "configuration_search_attribute_uri",
        "device_search_attribute_uri",
        "status_attribute_uri",
        "message_attribute_uri",
        "timestamp_attribute_uri",
        "replace_existing_collections",
        "require_configuration_period",
        "input_attribute_uris",
    }
    actions = []
    for index, entry in enumerate(_table_sequence(data.get("actions", ()), f"{path}.actions")):
        entry_path = f"{path}.actions[{index}]"
        _reject_unknown_keys(entry, action_keys, entry_path)
        kind = _nonempty_string(entry.get("kind"), f"{entry_path}.kind")
        if kind not in {"configuration", "device", "all_configurations", "all_devices"}:
            raise ConfigValidationError(f"{entry_path}.kind", f"unsupported refresh kind {kind!r}")
        action = MetadataRefreshActionConfig(
            scope=_parse_catalog_scope(entry, entry_path),
            kind=kind,
            trigger_attribute_uri=_nonempty_string(
                entry.get("trigger_attribute_uri"),
                f"{entry_path}.trigger_attribute_uri",
            ),
            configuration_search_attribute_uri=_optional_nonempty_string(
                entry.get("configuration_search_attribute_uri"),
                f"{entry_path}.configuration_search_attribute_uri",
            ),
            device_search_attribute_uri=_optional_nonempty_string(
                entry.get("device_search_attribute_uri"),
                f"{entry_path}.device_search_attribute_uri",
            ),
            status_attribute_uri=_optional_nonempty_string(
                entry.get("status_attribute_uri"),
                f"{entry_path}.status_attribute_uri",
            ),
            message_attribute_uri=_optional_nonempty_string(
                entry.get("message_attribute_uri"),
                f"{entry_path}.message_attribute_uri",
            ),
            timestamp_attribute_uri=_optional_nonempty_string(
                entry.get("timestamp_attribute_uri"),
                f"{entry_path}.timestamp_attribute_uri",
            ),
            replace_existing_collections=_boolean(
                entry.get("replace_existing_collections", False),
                f"{entry_path}.replace_existing_collections",
            ),
            require_configuration_period=_boolean(
                entry.get("require_configuration_period", False),
                f"{entry_path}.require_configuration_period",
            ),
            input_attribute_uris=_string_sequence(
                entry.get("input_attribute_uris", ()),
                f"{entry_path}.input_attribute_uris",
            ),
        )
        if kind in {"configuration", "all_configurations"} and not (
            action.configuration_search_attribute_uri or configuration_search_uri
        ):
            raise ConfigValidationError(entry_path, "configuration refresh action has no configuration search attribute URI")
        if kind in {"device", "all_devices"} and not (action.device_search_attribute_uri or device_search_uri):
            raise ConfigValidationError(entry_path, "device refresh action has no device search attribute URI")
        actions.append(action)

    return MetadataRefreshConfig(
        configuration_search_attribute_uri=configuration_search_uri,
        device_search_attribute_uri=device_search_uri,
        actions=tuple(actions),
    )


def _parse_handlers(value: Any) -> dict[str, HandlerConfig]:
    data = _require_mapping(value, "handlers")
    _reject_unknown_keys(data, set(HANDLER_SETTINGS), "handlers")
    handlers = {}
    for handler_name, handler_value in data.items():
        path = f"handlers.{handler_name}"
        handler_data = _require_mapping(handler_value, path)
        _reject_unknown_keys(handler_data, {"defaults", "backend_defaults", "backends", "catalogs"}, path)
        defaults_data = _require_mapping(handler_data.get("defaults", {}), f"{path}.defaults")
        default_mapping = _parse_attribute_mapping(
            defaults_data.get("attribute_mapping", {}),
            f"{path}.defaults.attribute_mapping",
        )
        defaults = _parse_handler_settings(
            handler_name,
            {key: value for key, value in defaults_data.items() if key != "attribute_mapping"},
            f"{path}.defaults",
        )
        backend_defaults = _parse_handler_settings(
            handler_name,
            handler_data.get("backend_defaults", {}),
            f"{path}.backend_defaults",
        )
        backends = tuple(
            _parse_handler_settings(handler_name, entry, f"{path}.backends[{index}]")
            for index, entry in enumerate(_table_sequence(handler_data.get("backends", ()), f"{path}.backends"))
        )
        for index, backend in enumerate(backends):
            merged_backend = _merge(backend_defaults, backend)
            if handler_name.startswith("SensorManagementSystem"):
                required_settings = {"id_prefix", "base_url"}
                if handler_name == "SensorManagementSystemConfigurationHandler":
                    required_settings |= {"device_id_prefix", "device_text_prefix"}
                _require_string_settings(merged_backend, required_settings, f"{path}.backends[{index}]")
        catalogs = []
        for index, entry in enumerate(_table_sequence(handler_data.get("catalogs", ()), f"{path}.catalogs")):
            entry_path = f"{path}.catalogs[{index}]"
            _reject_unknown_keys(
                entry,
                CATALOG_SCOPE_KEYS | HANDLER_SETTINGS[handler_name] | {"attribute_mapping"},
                entry_path,
            )
            search_uri = _optional_nonempty_string(entry.get("search_attribute_uri"), f"{entry_path}.search_attribute_uri")
            catalogs.append(
                HandlerCatalogConfig(
                    scope=_parse_catalog_scope(entry, entry_path),
                    search_attribute_uri=search_uri,
                    attribute_mapping=_parse_attribute_mapping(
                        entry.get("attribute_mapping", {}),
                        f"{entry_path}.attribute_mapping",
                    ),
                    settings=_parse_handler_settings(
                        handler_name,
                        {
                            key: item
                            for key, item in entry.items()
                            if key not in CATALOG_SCOPE_KEYS | {"attribute_mapping", "search_attribute_uri"}
                        },
                        entry_path,
                    ),
                )
            )

        default_search_uri = defaults.get("search_attribute_uri")
        if not catalogs and not default_search_uri:
            raise ConfigValidationError(path, "at least one catalog or a default search_attribute_uri is required")
        if not catalogs:
            _validate_period_pair(defaults, f"{path}.defaults")
            _validate_membership_settings(defaults, f"{path}.defaults")
        for index, catalog in enumerate(catalogs):
            if not catalog.search_attribute_uri and not default_search_uri:
                raise ConfigValidationError(f"{path}.catalogs[{index}]", "search_attribute_uri is required")
            merged_catalog = _merge(defaults, catalog.settings)
            _validate_period_pair(merged_catalog, f"{path}.catalogs[{index}]")
            _validate_membership_settings(merged_catalog, f"{path}.catalogs[{index}]")
        if handler_name.startswith("SensorManagementSystem") and not backends:
            raise ConfigValidationError(path, "at least one backend is required for an SMS handler")

        handlers[handler_name] = HandlerConfig(
            handler_name=handler_name,
            defaults=_freeze(defaults),
            default_attribute_mapping=_freeze(default_mapping),
            backend_defaults=_freeze(backend_defaults),
            backends=tuple(_freeze(backend) for backend in backends),
            catalogs=tuple(catalogs),
        )
    return handlers


def _parse_provider_settings(provider_name: str, value: Any, path: str) -> Mapping[str, Any]:
    data = _require_mapping(value, path)
    _reject_unknown_keys(data, PROVIDER_SETTINGS[provider_name], path)
    parsed = dict(data)
    _validate_setting_values(parsed, path)
    if "id_prefix" in parsed:
        _validate_id_prefix(parsed["id_prefix"], f"{path}.id_prefix")
    return _freeze(parsed)


def _parse_handler_settings(handler_name: str, value: Any, path: str) -> Mapping[str, Any]:
    data = _require_mapping(value, path)
    _reject_unknown_keys(data, HANDLER_SETTINGS[handler_name], path)
    parsed = dict(data)
    _validate_setting_values(parsed, path)
    if "id_prefix" in parsed:
        _validate_id_prefix(parsed["id_prefix"], f"{path}.id_prefix")
    return _freeze(parsed)


def _validate_setting_values(settings: Mapping[str, Any], path: str) -> None:
    for key, value in settings.items():
        setting_path = f"{path}.{key}"
        if key in BOOLEAN_SETTINGS:
            _boolean(value, setting_path)
        elif key in POSITIVE_INTEGER_SETTINGS:
            _positive_integer(value, setting_path)
        elif key == "offset":
            _integer(value, setting_path)
        elif key in STRING_SEQUENCE_SETTINGS:
            _string_sequence(value, setting_path)
        else:
            _string(value, setting_path, allow_empty=key == "sorts")


def _parse_attribute_mapping(value: Any, path: str) -> Mapping[str, str]:
    data = _require_mapping(value, path)
    result = {}
    for source_path, attribute_uri in data.items():
        source_path = _nonempty_string(source_path, f"{path}.<source>")
        result[source_path] = _nonempty_string(attribute_uri, f"{path}.{source_path}")
    return MappingProxyType(result)


def _parse_catalog_scope(data: Mapping[str, Any], path: str) -> CatalogScopeConfig:
    values = []
    catalog_uri = data.get("catalog_uri")
    if catalog_uri is not None:
        values.append(_nonempty_string(catalog_uri, f"{path}.catalog_uri"))
    values.extend(_string_sequence(data.get("catalog_uris", ()), f"{path}.catalog_uris"))
    return CatalogScopeConfig(catalog_uris=tuple(dict.fromkeys(values)))


def _validate_prefix_contract(config: PluginConfig) -> None:
    handler_prefixes: dict[str, set[str]] = {name: set(handler.id_prefixes) for name, handler in config.handlers.items()}
    all_handler_prefixes = [prefix for prefixes in handler_prefixes.values() for prefix in prefixes]
    _reject_duplicate_prefixes(all_handler_prefixes, "handlers")

    provider_instances = (*config.device_search.providers, *config.configuration_search.providers)
    provider_prefixes = [provider.id_prefix for provider in provider_instances if provider.id_prefix]
    _reject_duplicate_prefixes(provider_prefixes, "providers")
    for provider in provider_instances:
        prefix = provider.id_prefix
        handler_name = PROVIDER_HANDLER_NAMES[provider.provider_name]
        if prefix not in handler_prefixes.get(handler_name, set()):
            raise ConfigValidationError(
                f"providers.{provider.provider_name}",
                f"id_prefix {prefix!r} has no matching {handler_name}",
            )

    sms_device_prefixes = handler_prefixes.get("SensorManagementSystemDeviceHandler", set())
    sms_configuration = config.handlers.get("SensorManagementSystemConfigurationHandler")
    if sms_configuration:
        for index, backend in enumerate(sms_configuration.backends):
            merged = _merge(sms_configuration.backend_defaults, backend)
            device_prefix = merged.get("device_id_prefix")
            if device_prefix not in sms_device_prefixes:
                raise ConfigValidationError(
                    f"handlers.SensorManagementSystemConfigurationHandler.backends[{index}].device_id_prefix",
                    f"{device_prefix!r} has no matching SMS device handler backend",
                )

    mission_handler = config.handlers.get("O2ARegistryMissionHandler")
    item_prefixes = handler_prefixes.get("O2ARegistryItemHandler", set())
    if mission_handler:
        item_prefix = mission_handler.defaults.get("item_id_prefix")
        if item_prefix not in item_prefixes:
            raise ConfigValidationError(
                "handlers.O2ARegistryMissionHandler.defaults.item_id_prefix",
                f"{item_prefix!r} has no matching O2A item handler",
            )


def _validate_period_pair(settings: Mapping[str, Any], path: str) -> None:
    start_uri = settings.get("period_start_attribute_uri")
    end_uri = settings.get("period_end_attribute_uri")
    if bool(start_uri) != bool(end_uri):
        raise ConfigValidationError(
            path,
            "period_start_attribute_uri and period_end_attribute_uri must be configured together",
        )


def _validate_membership_settings(settings: Mapping[str, Any], path: str) -> None:
    if not settings.get("selected_devices_attribute_uri"):
        return
    _require_string_settings(
        settings,
        {"selected_devices_page_uri", "configuration_collection_attribute_uri"},
        path,
    )


def _require_string_settings(settings: Mapping[str, Any], required_keys: set[str], path: str) -> None:
    missing = sorted(key for key in required_keys if not isinstance(settings.get(key), str) or not settings[key].strip())
    if missing:
        raise ConfigValidationError(path, f"missing required setting(s): {', '.join(missing)}")


def _validate_provider_name(name: Any, allowed_names: frozenset[str], path: str) -> None:
    if not isinstance(name, str) or name not in allowed_names:
        raise ConfigValidationError(path, f"unknown provider {name!r}; expected one of {sorted(allowed_names)}")


def _reject_duplicate_prefixes(prefixes: Sequence[str], path: str) -> None:
    seen = set()
    for prefix in prefixes:
        if prefix in seen:
            raise ConfigValidationError(path, f"duplicate id_prefix {prefix!r}")
        seen.add(prefix)


def _validate_id_prefix(value: Any, path: str) -> str:
    prefix = _nonempty_string(value, path)
    if ":" in prefix or "||" in prefix:
        raise ConfigValidationError(path, "must not contain ':' or '||'")
    return prefix


def _reject_unknown_keys(data: Mapping[str, Any], allowed: set[str] | frozenset[str], path: str) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ConfigValidationError(path, f"unknown setting(s): {', '.join(unknown)}")


def _require_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ConfigValidationError(path, f"expected a table, got {type(value).__name__}")
    if not all(isinstance(key, str) for key in value):
        raise ConfigValidationError(path, "table keys must be strings")
    return value


def _table_sequence(value: Any, path: str) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        raise ConfigValidationError(path, f"expected an array of tables, got {type(value).__name__}")
    return tuple(_require_mapping(item, f"{path}[{index}]") for index, item in enumerate(value))


def _string(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ConfigValidationError(path, f"expected a string, got {type(value).__name__}")
    if not allow_empty and not value.strip():
        raise ConfigValidationError(path, "must not be empty")
    return value


def _nonempty_string(value: Any, path: str) -> str:
    return _string(value, path)


def _optional_nonempty_string(value: Any, path: str) -> str | None:
    return None if value is None else _nonempty_string(value, path)


def _string_sequence(value: Any, path: str) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ConfigValidationError(path, f"expected an array of strings, got {type(value).__name__}")
    return tuple(_nonempty_string(item, f"{path}[{index}]") for index, item in enumerate(value))


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigValidationError(path, f"expected a boolean, got {type(value).__name__}")
    return value


def _integer(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigValidationError(path, f"expected an integer, got {type(value).__name__}")
    return value


def _positive_integer(value: Any, path: str) -> int:
    value = _integer(value, path)
    if value <= 0:
        raise ConfigValidationError(path, "must be greater than zero")
    return value


def _merge(base: Mapping[str, Any] | None, override: Mapping[str, Any] | None) -> dict[str, Any]:
    merged = dict(base or {})
    merged.update(override or {})
    return merged


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    return value
