"""Names, defaults, and allowed settings forming the TOML schema contract."""

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
