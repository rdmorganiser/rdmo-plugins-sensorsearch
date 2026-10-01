from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from rdmo_sensorsearch.config_models.backend_parsing import parse_backends, parse_settings
from rdmo_sensorsearch.config_models.consumer_settings import (
    DataCollectionSyncSettings,
    GIPPInstrumentCatalogSettings,
    O2AMissionSearchSettings,
    O2ARegistryItemCatalogSettings,
    O2ARegistryMissionCatalogSettings,
    SearchSettings,
    SensorManagementSystemConfigurationCatalogSettings,
    SensorManagementSystemDeviceCatalogSettings,
)
from rdmo_sensorsearch.config_models.contracts import (
    CATALOG_SCOPE_KEYS,
    CONFIGURATION_PROVIDER_NAMES,
    DEVICE_DETAIL_SYNC_SETTINGS,
    DEVICE_PROVIDER_NAMES,
    HANDLER_SETTINGS,
    PROVIDER_SETTINGS,
    TOP_LEVEL_SECTIONS,
)
from rdmo_sensorsearch.config_models.models import (
    CatalogScopeConfig,
    DataCollectionSyncCatalogConfig,
    DataCollectionVariableSyncConfig,
    DeviceDetailSyncCatalogConfig,
    DeviceDetailSyncConfig,
    HandlerCatalogConfig,
    HandlerConfig,
    HandlerInstanceConfig,
    MetadataRefreshActionConfig,
    MetadataRefreshConfig,
    PluginConfig,
    ProjectOptionsCatalogConfig,
    ProjectOptionsProviderConfig,
    ProviderInstanceConfig,
    SearchProviderConfig,
)
from rdmo_sensorsearch.config_models.validation import (
    ConfigValidationError,
    boolean,
    merge,
    nonempty_string,
    optional_nonempty_string,
    positive_integer,
    reject_unknown_keys,
    require_mapping,
    string_sequence,
    table_sequence,
    validate_backend_references,
    validate_membership_filter_settings,
    validate_membership_settings,
    validate_provider_name,
)
from rdmo_sensorsearch.contracts import DeviceDetailSettings

HANDLER_CATALOG_TYPES = {
    "O2ARegistryItemHandler": O2ARegistryItemCatalogSettings,
    "O2ARegistryMissionHandler": O2ARegistryMissionCatalogSettings,
    "SensorManagementSystemDeviceHandler": SensorManagementSystemDeviceCatalogSettings,
    "SensorManagementSystemConfigurationHandler": SensorManagementSystemConfigurationCatalogSettings,
    "GIPPInstrumentHandler": GIPPInstrumentCatalogSettings,
}
SMS_PROVIDER_NAMES = {"SensorManagementSystemDeviceProvider", "SensorManagementSystemConfigurationProvider"}
PROVIDER_TEXT_DEFAULTS = {
    "O2ARegistryItemProvider": "O2A Item",
    "O2ARegistryMissionProvider": "O2A M",
    "GIPPInstrumentProvider": "GFZ GIPP Instrument",
}
PROVIDER_OPTION_DEFAULTS = {
    "SensorManagementSystemDeviceProvider": {
        "option_id": "{id_prefix}:{id}",
        "option_text": "{prefix}({id}): {name}{serial}",
    },
    "SensorManagementSystemConfigurationProvider": {
        "option_id": "{id_prefix}:{id}",
        "option_text": "{prefix}({id}): {label}{project}{pid}",
    },
    "O2ARegistryMissionProvider": {"option_id": "{id_prefix}:{id}", "option_text": "{prefix}({id}): {name}"},
    "GIPPInstrumentProvider": {"option_id": "{prefix}:{id}", "option_text": "{prefix}({id}): {code}"},
}


def parse_plugin_config(data: Mapping[str, Any]) -> PluginConfig:
    root = require_mapping(data, "config")
    backends = parse_backends(root.get("backends", ()))
    reject_unknown_keys(root, TOP_LEVEL_SECTIONS, "config")

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
    device_detail_sync = _parse_device_detail_sync(root.get("DeviceDetailSync", {}))
    metadata_refresh = _parse_metadata_refresh(root.get("MetadataRefresh", {}))
    handlers = _parse_handlers(root.get("handlers", {}))

    config = PluginConfig(
        device_search=device_search,
        configuration_search=configuration_search,
        project_configuration_devices=project_configuration_devices,
        project_data_collection_devices=project_data_collection_devices,
        data_collection_variable_sync=data_collection_variable_sync,
        device_detail_sync=device_detail_sync,
        metadata_refresh=metadata_refresh,
        handlers=MappingProxyType(handlers),
        backends=backends,
    )
    validate_backend_references(config)
    return config


def _parse_search_provider(
    value: Any, path: str, allowed_provider_names: frozenset[str], *, allow_sms_filter: bool
) -> SearchProviderConfig:
    data = require_mapping(value, path)
    allowed_keys = {"min_search_len", "providers", "provider_defaults"}
    if allow_sms_filter:
        allowed_keys.add("filter_sms_devices_by_selected_configuration")
    reject_unknown_keys(data, allowed_keys, path)
    defaults = require_mapping(data.get("provider_defaults", {}), f"{path}.provider_defaults")
    for name, entry in defaults.items():
        validate_provider_name(name, allowed_provider_names, f"{path}.provider_defaults")
        reject_unknown_keys(
            require_mapping(entry, f"{path}.provider_defaults.{name}"),
            PROVIDER_SETTINGS[name] - {"backend"},
            f"{path}.provider_defaults.{name}",
        )
        cls = O2AMissionSearchSettings if name == "O2ARegistryMissionProvider" else SearchSettings
        parse_settings(cls, {"text_prefix": "Default", **entry}, f"{path}.provider_defaults.{name}")
    providers = []
    for name, entries in require_mapping(data.get("providers", {}), f"{path}.providers").items():
        validate_provider_name(name, allowed_provider_names, f"{path}.providers")
        for index, entry in enumerate(table_sequence(entries, f"{path}.providers.{name}")):
            entry_path = f"{path}.providers.{name}[{index}]"
            reject_unknown_keys(entry, PROVIDER_SETTINGS[name], entry_path)
            backend = nonempty_string(entry.get("backend"), f"{entry_path}.backend")
            values = merge(PROVIDER_OPTION_DEFAULTS.get(name), defaults.get(name))
            values = merge(values, {key: item for key, item in entry.items() if key != "backend"})
            if name in SMS_PROVIDER_NAMES and "text_prefix" not in values:
                raise ConfigValidationError(entry_path, "missing required setting(s): text_prefix")
            values.setdefault("text_prefix", PROVIDER_TEXT_DEFAULTS.get(name, ""))
            cls = O2AMissionSearchSettings if name == "O2ARegistryMissionProvider" else SearchSettings
            providers.append(ProviderInstanceConfig(name, backend, parse_settings(cls, values, entry_path)))
    return SearchProviderConfig(
        minimum_search_length=positive_integer(data.get("min_search_len", 3), f"{path}.min_search_len"),
        providers=tuple(providers),
        filter_sms_devices_by_selected_configuration=boolean(
            data.get("filter_sms_devices_by_selected_configuration", False),
            f"{path}.filter_sms_devices_by_selected_configuration",
        ),
    )


def _parse_project_options_provider(value: Any, path: str) -> ProjectOptionsProviderConfig:
    data = require_mapping(value, path)
    reject_unknown_keys(data, {"catalogs"}, path)
    catalogs = []
    for index, entry in enumerate(table_sequence(data.get("catalogs", ()), f"{path}.catalogs")):
        entry_path = f"{path}.catalogs[{index}]"
        reject_unknown_keys(entry, CATALOG_SCOPE_KEYS | {"source_attribute_uri"}, entry_path)
        catalogs.append(
            ProjectOptionsCatalogConfig(
                scope=_parse_catalog_scope(entry, entry_path),
                source_attribute_uri=nonempty_string(
                    entry.get("source_attribute_uri"),
                    f"{entry_path}.source_attribute_uri",
                ),
            )
        )
    return ProjectOptionsProviderConfig(catalogs=tuple(catalogs))


def _parse_data_collection_sync(value: Any) -> DataCollectionVariableSyncConfig:
    path = "DataCollectionVariableSync"
    data = require_mapping(value, path)
    reject_unknown_keys(data, {"catalogs"}, path)
    setting_keys = {
        "devices_attribute_uri",
        "device_collection_attribute_uri",
        "parameter_name_attribute_uri",
        "parameter_unit_attribute_uri",
        "variable_attribute_uri",
        "unit_attribute_uri",
    }
    catalogs = []
    for index, entry in enumerate(table_sequence(data.get("catalogs", ()), f"{path}.catalogs")):
        entry_path = f"{path}.catalogs[{index}]"
        reject_unknown_keys(entry, CATALOG_SCOPE_KEYS | setting_keys, entry_path)
        scope = _parse_catalog_scope(entry, entry_path)
        if not scope.catalog_uris:
            raise ConfigValidationError(entry_path, "catalog_uri or catalog_uris is required")
        settings = {key: nonempty_string(entry[key], f"{entry_path}.{key}") for key in setting_keys if key in entry}
        catalogs.append(
            DataCollectionSyncCatalogConfig(
                scope=scope, settings=parse_settings(DataCollectionSyncSettings, settings, entry_path)
            )
        )
    return DataCollectionVariableSyncConfig(catalogs=tuple(catalogs))


def _parse_device_detail_sync(value: Any) -> DeviceDetailSyncConfig:
    path = "DeviceDetailSync"
    data = require_mapping(value, path)
    reject_unknown_keys(data, {"catalogs"}, path)
    setting_keys = DEVICE_DETAIL_SYNC_SETTINGS
    catalogs = []
    for index, entry in enumerate(table_sequence(data.get("catalogs", ()), f"{path}.catalogs")):
        entry_path = f"{path}.catalogs[{index}]"
        reject_unknown_keys(entry, CATALOG_SCOPE_KEYS | setting_keys, entry_path)
        settings = {key: nonempty_string(entry.get(key), f"{entry_path}.{key}") for key in setting_keys}
        catalogs.append(
            DeviceDetailSyncCatalogConfig(
                scope=_parse_catalog_scope(entry, entry_path),
                settings=DeviceDetailSettings(**settings),
            )
        )
    return DeviceDetailSyncConfig(catalogs=tuple(catalogs))


def _parse_metadata_refresh(value: Any) -> MetadataRefreshConfig:
    path = "MetadataRefresh"
    data = require_mapping(value, path)
    reject_unknown_keys(
        data,
        {"configuration_search_attribute_uri", "device_search_attribute_uri", "actions"},
        path,
    )
    configuration_search_uri = optional_nonempty_string(
        data.get("configuration_search_attribute_uri"),
        f"{path}.configuration_search_attribute_uri",
    )
    device_search_uri = optional_nonempty_string(
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
    for index, entry in enumerate(table_sequence(data.get("actions", ()), f"{path}.actions")):
        entry_path = f"{path}.actions[{index}]"
        reject_unknown_keys(entry, action_keys, entry_path)
        kind = nonempty_string(entry.get("kind"), f"{entry_path}.kind")
        if kind not in {"configuration", "device", "all_configurations", "all_devices"}:
            raise ConfigValidationError(f"{entry_path}.kind", f"unsupported refresh kind {kind!r}")
        action = MetadataRefreshActionConfig(
            scope=_parse_catalog_scope(entry, entry_path),
            kind=kind,
            trigger_attribute_uri=nonempty_string(
                entry.get("trigger_attribute_uri"),
                f"{entry_path}.trigger_attribute_uri",
            ),
            configuration_search_attribute_uri=optional_nonempty_string(
                entry.get("configuration_search_attribute_uri"),
                f"{entry_path}.configuration_search_attribute_uri",
            ),
            device_search_attribute_uri=optional_nonempty_string(
                entry.get("device_search_attribute_uri"),
                f"{entry_path}.device_search_attribute_uri",
            ),
            status_attribute_uri=optional_nonempty_string(
                entry.get("status_attribute_uri"),
                f"{entry_path}.status_attribute_uri",
            ),
            message_attribute_uri=optional_nonempty_string(
                entry.get("message_attribute_uri"),
                f"{entry_path}.message_attribute_uri",
            ),
            timestamp_attribute_uri=optional_nonempty_string(
                entry.get("timestamp_attribute_uri"),
                f"{entry_path}.timestamp_attribute_uri",
            ),
            replace_existing_collections=boolean(
                entry.get("replace_existing_collections", False),
                f"{entry_path}.replace_existing_collections",
            ),
            require_configuration_period=boolean(
                entry.get("require_configuration_period", False),
                f"{entry_path}.require_configuration_period",
            ),
            input_attribute_uris=string_sequence(
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
    data = require_mapping(value, "handlers")
    reject_unknown_keys(data, set(HANDLER_SETTINGS), "handlers")
    handlers = {}
    for name, entry in data.items():
        path = f"handlers.{name}"
        entry = require_mapping(entry, path)
        if "backends" in entry or "backend_defaults" in entry:
            raise ConfigValidationError(
                path,
                "old backend layout is unsupported; migrate to top-level [[backends]] "
                "and handler instances (see docs/configuration-reference.md)",
            )
        reject_unknown_keys(entry, {"defaults", "instances", "catalogs"}, path)
        defaults = require_mapping(entry.get("defaults", {}), f"{path}.defaults")
        allowed = HANDLER_SETTINGS[name] | {"attribute_mapping"}
        reject_unknown_keys(defaults, allowed, f"{path}.defaults")
        parse_settings(
            HANDLER_CATALOG_TYPES[name],
            {key: item for key, item in defaults.items() if key not in {"attribute_mapping", "search_attribute_uri"}},
            f"{path}.defaults",
        )
        instances = []
        instance_keys = {"backend"}
        if name == "SensorManagementSystemConfigurationHandler":
            instance_keys.add("device_text_prefix")
        elif name == "O2ARegistryMissionHandler":
            instance_keys |= {"item_text_prefix", "item_text_template"}
        for index, instance in enumerate(table_sequence(entry.get("instances", ()), f"{path}.instances")):
            instance_path = f"{path}.instances[{index}]"
            reject_unknown_keys(instance, instance_keys, instance_path)
            parsed = parse_settings(HandlerInstanceConfig, instance, instance_path)
            if name == "SensorManagementSystemConfigurationHandler" and not parsed.device_text_prefix:
                raise ConfigValidationError(instance_path, "device_text_prefix is required")
            instances.append(parsed)
        if not instances:
            raise ConfigValidationError(path, "at least one named backend instance is required")
        catalogs = []
        entries = table_sequence(entry.get("catalogs", ()), f"{path}.catalogs")
        if not entries and defaults:
            entries = ({},)
        if not entries:
            raise ConfigValidationError(path, "at least one catalog or a default search_attribute_uri is required")
        for index, catalog in enumerate(entries):
            catalog_path = f"{path}.catalogs[{index}]"
            reject_unknown_keys(catalog, CATALOG_SCOPE_KEYS | allowed, catalog_path)
            effective = merge(defaults, catalog)
            scope = _parse_catalog_scope(effective, catalog_path)
            search = optional_nonempty_string(effective.get("search_attribute_uri"), f"{catalog_path}.search_attribute_uri")
            if not search:
                raise ConfigValidationError(catalog_path, "search_attribute_uri is required")
            mapping = merge(
                _parse_attribute_mapping(defaults.get("attribute_mapping", {}), f"{path}.defaults.attribute_mapping"),
                _parse_attribute_mapping(catalog.get("attribute_mapping", {}), f"{catalog_path}.attribute_mapping"),
            )
            options = {
                key: item
                for key, item in effective.items()
                if key not in CATALOG_SCOPE_KEYS | {"attribute_mapping", "search_attribute_uri"}
            }
            validate_membership_filter_settings(options, catalog_path)
            validate_membership_settings(options, catalog_path)
            settings = parse_settings(HANDLER_CATALOG_TYPES[name], options, catalog_path)
            catalogs.append(HandlerCatalogConfig(scope, search, MappingProxyType(mapping), settings))
        handlers[name] = HandlerConfig(name, tuple(instances), tuple(catalogs))
    return handlers


def _parse_attribute_mapping(value: Any, path: str) -> Mapping[str, str]:
    data = require_mapping(value, path)
    result = {}
    for source_path, attribute_uri in data.items():
        source_path = nonempty_string(source_path, f"{path}.<source>")
        result[source_path] = nonempty_string(attribute_uri, f"{path}.{source_path}")
    return MappingProxyType(result)


def _parse_catalog_scope(data: Mapping[str, Any], path: str) -> CatalogScopeConfig:
    values = []
    catalog_uri = data.get("catalog_uri")
    if catalog_uri is not None:
        values.append(nonempty_string(catalog_uri, f"{path}.catalog_uri"))
    values.extend(string_sequence(data.get("catalog_uris", ()), f"{path}.catalog_uris"))
    return CatalogScopeConfig(catalog_uris=tuple(dict.fromkeys(values)))
