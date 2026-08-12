from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from rdmo_sensorsearch.config_models.contracts import (
    BOOLEAN_SETTINGS,
    CATALOG_SCOPE_KEYS,
    CONFIGURATION_PROVIDER_NAMES,
    DEVICE_PROVIDER_NAMES,
    HANDLER_SETTINGS,
    NON_NEGATIVE_INTEGER_SETTINGS,
    POSITIVE_INTEGER_SETTINGS,
    PROVIDER_SETTINGS,
    STRING_SEQUENCE_SETTINGS,
    TOP_LEVEL_SECTIONS,
)
from rdmo_sensorsearch.config_models.models import (
    CatalogScopeConfig,
    DataCollectionSyncCatalogConfig,
    DataCollectionVariableSyncConfig,
    HandlerCatalogConfig,
    HandlerConfig,
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
    freeze,
    integer,
    merge,
    non_negative_integer,
    nonempty_string,
    optional_nonempty_string,
    positive_integer,
    reject_unknown_keys,
    require_mapping,
    require_string_settings,
    string,
    string_sequence,
    table_sequence,
    validate_id_prefix,
    validate_membership_settings,
    validate_period_pair,
    validate_prefix_contract,
    validate_provider_name,
)


def parse_plugin_config(data: Mapping[str, Any]) -> PluginConfig:
    root = require_mapping(data, "config")
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
    metadata_refresh = _parse_metadata_refresh(root.get("MetadataRefresh", {}))
    handlers = _parse_handlers(root.get("handlers", {}))

    config = PluginConfig(
        device_search=device_search,
        configuration_search=configuration_search,
        project_configuration_devices=project_configuration_devices,
        project_data_collection_devices=project_data_collection_devices,
        data_collection_variable_sync=data_collection_variable_sync,
        metadata_refresh=metadata_refresh,
        handlers=MappingProxyType(handlers),
        raw=freeze(root),
    )
    validate_prefix_contract(config)
    return config


def _parse_search_provider(
    value: Any,
    path: str,
    allowed_provider_names: frozenset[str],
    *,
    allow_sms_filter: bool,
) -> SearchProviderConfig:
    data = require_mapping(value, path)
    allowed_keys = {"min_search_len", "providers", "provider_defaults"}
    if allow_sms_filter:
        allowed_keys.add("filter_sms_devices_by_selected_configuration")
    reject_unknown_keys(data, allowed_keys, path)

    minimum_search_length = positive_integer(data.get("min_search_len", 3), f"{path}.min_search_len")
    filter_sms = boolean(
        data.get("filter_sms_devices_by_selected_configuration", False),
        f"{path}.filter_sms_devices_by_selected_configuration",
    )
    provider_defaults_data = require_mapping(data.get("provider_defaults", {}), f"{path}.provider_defaults")
    providers_data = require_mapping(data.get("providers", {}), f"{path}.providers")

    provider_defaults: dict[str, Mapping[str, Any]] = {}
    for provider_name, settings in provider_defaults_data.items():
        validate_provider_name(provider_name, allowed_provider_names, f"{path}.provider_defaults")
        provider_defaults[provider_name] = _parse_provider_settings(
            provider_name,
            settings,
            f"{path}.provider_defaults.{provider_name}",
        )

    providers = []
    for provider_name, definitions in providers_data.items():
        validate_provider_name(provider_name, allowed_provider_names, f"{path}.providers")
        for index, settings in enumerate(table_sequence(definitions, f"{path}.providers.{provider_name}")):
            parsed_settings = _parse_provider_settings(
                provider_name,
                settings,
                f"{path}.providers.{provider_name}[{index}]",
            )
            merged_settings = merge(provider_defaults.get(provider_name), parsed_settings)
            if provider_name.startswith("SensorManagementSystem"):
                require_string_settings(
                    merged_settings,
                    {"id_prefix", "text_prefix", "base_url"},
                    f"{path}.providers.{provider_name}[{index}]",
                )
            providers.append(
                ProviderInstanceConfig(
                    provider_name=provider_name,
                    settings=freeze(merged_settings),
                )
            )

    return SearchProviderConfig(
        minimum_search_length=minimum_search_length,
        providers=tuple(providers),
        provider_defaults=MappingProxyType(provider_defaults),
        filter_sms_devices_by_selected_configuration=filter_sms,
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
        catalogs.append(DataCollectionSyncCatalogConfig(scope=scope, settings=freeze(settings)))
    return DataCollectionVariableSyncConfig(catalogs=tuple(catalogs))


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
    for handler_name, handler_value in data.items():
        path = f"handlers.{handler_name}"
        handler_data = require_mapping(handler_value, path)
        reject_unknown_keys(handler_data, {"defaults", "backend_defaults", "backends", "catalogs"}, path)
        defaults_data = require_mapping(handler_data.get("defaults", {}), f"{path}.defaults")
        default_mapping = _parse_attribute_mapping(
            defaults_data.get("attribute_mapping", {}),
            f"{path}.defaults.attribute_mapping",
        )
        defaults = _parse_handler_settings(
            handler_name,
            {key: setting for key, setting in defaults_data.items() if key != "attribute_mapping"},
            f"{path}.defaults",
        )
        backend_defaults = _parse_handler_settings(
            handler_name,
            handler_data.get("backend_defaults", {}),
            f"{path}.backend_defaults",
        )
        backends = tuple(
            _parse_handler_settings(handler_name, entry, f"{path}.backends[{index}]")
            for index, entry in enumerate(table_sequence(handler_data.get("backends", ()), f"{path}.backends"))
        )
        for index, backend in enumerate(backends):
            merged_backend = merge(backend_defaults, backend)
            if handler_name.startswith("SensorManagementSystem"):
                required_settings = {"id_prefix", "base_url"}
                if handler_name == "SensorManagementSystemConfigurationHandler":
                    required_settings |= {"device_id_prefix", "device_text_prefix"}
                require_string_settings(merged_backend, required_settings, f"{path}.backends[{index}]")

        catalogs = []
        for index, entry in enumerate(table_sequence(handler_data.get("catalogs", ()), f"{path}.catalogs")):
            entry_path = f"{path}.catalogs[{index}]"
            reject_unknown_keys(
                entry,
                CATALOG_SCOPE_KEYS | HANDLER_SETTINGS[handler_name] | {"attribute_mapping"},
                entry_path,
            )
            search_uri = optional_nonempty_string(
                entry.get("search_attribute_uri"),
                f"{entry_path}.search_attribute_uri",
            )
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
            validate_period_pair(defaults, f"{path}.defaults")
            validate_membership_settings(defaults, f"{path}.defaults")
        for index, catalog in enumerate(catalogs):
            if not catalog.search_attribute_uri and not default_search_uri:
                raise ConfigValidationError(f"{path}.catalogs[{index}]", "search_attribute_uri is required")
            merged_catalog = merge(defaults, catalog.settings)
            validate_period_pair(merged_catalog, f"{path}.catalogs[{index}]")
            validate_membership_settings(merged_catalog, f"{path}.catalogs[{index}]")
        if handler_name.startswith("SensorManagementSystem") and not backends:
            raise ConfigValidationError(path, "at least one backend is required for an SMS handler")

        handlers[handler_name] = HandlerConfig(
            handler_name=handler_name,
            defaults=freeze(defaults),
            default_attribute_mapping=freeze(default_mapping),
            backend_defaults=freeze(backend_defaults),
            backends=tuple(freeze(backend) for backend in backends),
            catalogs=tuple(catalogs),
        )
    return handlers


def _parse_provider_settings(provider_name: str, value: Any, path: str) -> Mapping[str, Any]:
    data = require_mapping(value, path)
    reject_unknown_keys(data, PROVIDER_SETTINGS[provider_name], path)
    parsed = dict(data)
    _validate_setting_values(parsed, path)
    if "id_prefix" in parsed:
        validate_id_prefix(parsed["id_prefix"], f"{path}.id_prefix")
    return freeze(parsed)


def _parse_handler_settings(handler_name: str, value: Any, path: str) -> Mapping[str, Any]:
    data = require_mapping(value, path)
    reject_unknown_keys(data, HANDLER_SETTINGS[handler_name], path)
    parsed = dict(data)
    _validate_setting_values(parsed, path)
    if "id_prefix" in parsed:
        validate_id_prefix(parsed["id_prefix"], f"{path}.id_prefix")
    return freeze(parsed)


def _validate_setting_values(settings: Mapping[str, Any], path: str) -> None:
    for key, value in settings.items():
        setting_path = f"{path}.{key}"
        if key in BOOLEAN_SETTINGS:
            boolean(value, setting_path)
        elif key in POSITIVE_INTEGER_SETTINGS:
            positive_integer(value, setting_path)
        elif key in NON_NEGATIVE_INTEGER_SETTINGS:
            non_negative_integer(value, setting_path)
        elif key == "offset":
            integer(value, setting_path)
        elif key in STRING_SEQUENCE_SETTINGS:
            string_sequence(value, setting_path)
        else:
            string(value, setting_path, allow_empty=key == "sorts")
        if key == "incomplete_mount_chain_policy" and value not in {"strict", "direct_device_offset"}:
            raise ConfigValidationError(setting_path, "must be one of: direct_device_offset, strict")


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
