"""Names, defaults, and allowed settings forming the TOML schema contract."""

TOP_LEVEL_SECTIONS = frozenset(
    {
        "DeviceSearchProvider",
        "ConfigurationSearchProvider",
        "ProjectConfigurationDevicesProvider",
        "ProjectDataCollectionDevicesProvider",
        "DataCollectionVariableSync",
        "DeviceDetailSync",
        "MetadataRefresh",
        "handlers",
        "backends",
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

PROVIDER_HANDLER_NAMES = {
    "O2ARegistryItemProvider": "O2ARegistryItemHandler",
    "O2ARegistryMissionProvider": "O2ARegistryMissionHandler",
    "SensorManagementSystemDeviceProvider": "SensorManagementSystemDeviceHandler",
    "SensorManagementSystemConfigurationProvider": "SensorManagementSystemConfigurationHandler",
    "GIPPInstrumentProvider": "GIPPInstrumentHandler",
}
DEVICE_DETAIL_SYNC_SETTINGS = frozenset(
    {
        "device_details_page_uri",
        "device_optional_info_page_uri",
        "configuration_collection_attribute_uri",
        "device_link_attribute_uri",
        "usage_technology_attribute_uri",
        "instrument_start_attribute_uri",
        "instrument_end_attribute_uri",
        "instrument_location_amsl_attribute_uri",
        "surface_offset_z_attribute_uri",
        "site_name_attribute_uri",
        "serial_number_attribute_uri",
    }
)
# Explicit consumer discriminators: configuration names are wiring, not backend identity.
CONSUMER_CAPABILITIES = {
    "O2ARegistryItemProvider": ("o2a", "device"),
    "O2ARegistryItemHandler": ("o2a", "device"),
    "O2ARegistryMissionProvider": ("o2a", "configuration"),
    "O2ARegistryMissionHandler": ("o2a", "configuration"),
    "SensorManagementSystemDeviceProvider": ("sms", "device"),
    "SensorManagementSystemDeviceHandler": ("sms", "device"),
    "SensorManagementSystemConfigurationProvider": ("sms", "configuration"),
    "SensorManagementSystemConfigurationHandler": ("sms", "configuration"),
    "GIPPInstrumentProvider": ("gipp", "device"),
    "GIPPInstrumentHandler": ("gipp", "device"),
}

PROVIDER_SETTINGS = {
    "O2ARegistryItemProvider": frozenset(["backend", "max_hits", "text_prefix"]),
    "O2ARegistryMissionProvider": frozenset(
        ["backend", "max_hits", "offset", "option_id", "option_text", "sorts", "text_prefix", "where_template"]
    ),
    "SensorManagementSystemDeviceProvider": frozenset(["backend", "max_hits", "option_id", "option_text", "text_prefix"]),
    "SensorManagementSystemConfigurationProvider": frozenset(["backend", "max_hits", "option_id", "option_text", "text_prefix"]),
    "GIPPInstrumentProvider": frozenset(["backend", "max_hits", "option_id", "option_text", "text_prefix"]),
}
HANDLER_SETTINGS = {
    "O2ARegistryItemHandler": frozenset(
        [
            "device_collection_attribute_uri",
            "device_link_attribute_uri",
            "managed_attribute_uris",
            "materialize_device_details",
            "search_attribute_uri",
            "supports_mount_location_lookup",
            "supports_mount_period_lookup",
        ]
    ),
    "SensorManagementSystemDeviceHandler": frozenset(
        [
            "device_collection_attribute_uri",
            "device_link_attribute_uri",
            "managed_attribute_uris",
            "materialize_device_details",
            "search_attribute_uri",
            "supports_mount_location_lookup",
            "supports_mount_period_lookup",
        ]
    ),
    "SensorManagementSystemConfigurationHandler": frozenset(
        [
            "api_link_attribute_uri",
            "configuration_collection_attribute_uri",
            "configuration_end_date_path",
            "configuration_start_date_path",
            "device_collection_attribute_uri",
            "frontend_link_attribute_uri",
            "latitude_attribute_uri",
            "location_attribute_uri",
            "longitude_attribute_uri",
            "managed_attribute_uris",
            "membership_filter_enabled",
            "membership_filter_end_attribute_uri",
            "membership_filter_start_attribute_uri",
            "search_attribute_uri",
            "selected_devices_attribute_uri",
            "selected_devices_page_uri",
        ]
    ),
    "O2ARegistryMissionHandler": frozenset(
        [
            "api_link_attribute_uri",
            "configuration_collection_attribute_uri",
            "date_mapping_paths",
            "datetime_output_format",
            "device_collection_attribute_uri",
            "frontend_link_attribute_uri",
            "managed_attribute_uris",
            "mission_end_date_path",
            "mission_start_date_path",
            "search_attribute_uri",
            "selected_devices_attribute_uri",
            "selected_devices_page_uri",
        ]
    ),
    "GIPPInstrumentHandler": frozenset(["managed_attribute_uris", "search_attribute_uri"]),
}

CATALOG_SCOPE_KEYS = frozenset({"catalog_uris"})
STRING_SEQUENCE_SETTINGS = frozenset({"managed_attribute_uris", "date_mapping_paths", "input_attribute_uris"})
BOOLEAN_SETTINGS = frozenset(
    {
        "filter_sms_devices_by_selected_configuration",
        "materialize_device_details",
        "supports_mount_location_lookup",
        "supports_mount_period_lookup",
        "replace_existing_collections",
        "require_configuration_period",
        "membership_filter_enabled",
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
NON_NEGATIVE_INTEGER_SETTINGS = frozenset({"static_location_end_tolerance_seconds"})
