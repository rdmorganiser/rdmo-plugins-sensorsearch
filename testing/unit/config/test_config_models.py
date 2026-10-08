from copy import deepcopy

import pytest

from rdmo_sensorsearch.config_models import ConfigValidationError, PluginConfig
from rdmo_sensorsearch.config_models.models import PluginConfig as InternalPluginConfig
from rdmo_sensorsearch.config_models.validation import ConfigValidationError as InternalConfigValidationError
from testing.paths import PRODUCTION_CONFIG_PATH

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


CONFIG_PATH = PRODUCTION_CONFIG_PATH


def test_config_models_package_preserves_public_model_and_error_exports():
    assert PluginConfig is InternalPluginConfig
    assert ConfigValidationError is InternalConfigValidationError


def _config_data():
    with CONFIG_PATH.open("rb") as config_file:
        return tomllib.load(config_file)


def test_configuration_model_exposes_typed_sections_and_read_only_backend_definitions():
    config = PluginConfig.from_mapping(_config_data())

    assert config.device_search.minimum_search_length == 3
    assert config.device_search.filter_sms_devices_by_selected_configuration is False
    assert not any(action.require_configuration_period for action in config.metadata_refresh.actions)
    assert tuple(
        config.backend(instance.backend).configuration_id_prefix
        for instance in config.handlers["SensorManagementSystemConfigurationHandler"].instances
    ) == (
        "gfzcfg",
        "kitcfg",
        "ufzcfg",
    )

    with pytest.raises(TypeError):
        config.backends["unexpected"] = None


def test_unknown_top_level_section_is_rejected_with_its_path():
    data = _config_data()
    data["UnsupportedProviderSection"] = {}

    with pytest.raises(ConfigValidationError, match=r"^config: unknown setting\(s\): UnsupportedProviderSection$"):
        PluginConfig.from_mapping(data)


def test_unknown_handler_setting_is_rejected_instead_of_becoming_an_unused_attribute():
    data = _config_data()
    defaults = data["handlers"]["SensorManagementSystemConfigurationHandler"]["defaults"]
    defaults["selected_device_attribute_uri"] = defaults["selected_devices_attribute_uri"]

    with pytest.raises(
        ConfigValidationError,
        match=r"handlers\.SensorManagementSystemConfigurationHandler\.defaults: unknown setting\(s\): "
        r"selected_device_attribute_uri",
    ):
        PluginConfig.from_mapping(data)


def test_invalid_setting_type_is_rejected():
    data = _config_data()
    data["DeviceSearchProvider"]["filter_sms_devices_by_selected_configuration"] = "false"

    with pytest.raises(
        ConfigValidationError,
        match=r"DeviceSearchProvider\.filter_sms_devices_by_selected_configuration: expected a boolean",
    ):
        PluginConfig.from_mapping(data)


def test_duplicate_provider_prefix_is_rejected():
    data = _config_data()
    providers = data["DeviceSearchProvider"]["providers"]["SensorManagementSystemDeviceProvider"]
    providers[1]["backend"] = providers[0]["backend"]

    with pytest.raises(ConfigValidationError, match=r"duplicate backend binding 'gfz'"):
        PluginConfig.from_mapping(data)


def test_provider_prefix_without_matching_handler_is_rejected():
    data = _config_data()
    data["handlers"]["SensorManagementSystemDeviceHandler"]["instances"].pop(0)

    with pytest.raises(
        ConfigValidationError,
        match=r"providers\.SensorManagementSystemDeviceProvider: backend 'gfz' has no matching",
    ):
        PluginConfig.from_mapping(data)


def test_handler_catalog_requires_a_search_attribute():
    data = deepcopy(_config_data())
    gipp_catalog = data["handlers"]["GIPPInstrumentHandler"]["catalogs"][0]
    del gipp_catalog["search_attribute_uri"]

    with pytest.raises(
        ConfigValidationError,
        match=r"handlers\.GIPPInstrumentHandler\.catalogs\[0\]: search_attribute_uri is required",
    ):
        PluginConfig.from_mapping(data)


@pytest.mark.parametrize("scope", [None, []])
def test_data_collection_sync_requires_explicit_catalog_scope(scope):
    data = _config_data()
    catalog = data["DataCollectionVariableSync"]["catalogs"][0]
    if scope is None:
        catalog.pop("catalog_uris")
    else:
        catalog["catalog_uris"] = scope

    with pytest.raises(
        ConfigValidationError,
        match=r"DataCollectionVariableSync\.catalogs\[0\]: catalog_uris is required",
    ):
        PluginConfig.from_mapping(data)


SCOPED_SECTIONS = (
    "ProjectConfigurationDevicesProvider",
    "ProjectDataCollectionDevicesProvider",
    "DataCollectionVariableSync",
    "DeviceDetailSync",
    "MetadataRefresh",
    "handlers",
)


def _scoped_entry(data, section):
    if section == "handlers":
        return data["handlers"]["SensorManagementSystemDeviceHandler"]["catalogs"][0]
    if section == "MetadataRefresh":
        return data[section]["actions"][0]
    return data[section]["catalogs"][0]


def _parsed_scope(config, section):
    if section == "handlers":
        return config.handlers["SensorManagementSystemDeviceHandler"].catalogs[0].scope
    if section == "MetadataRefresh":
        return config.metadata_refresh.actions[0].scope
    sections = {
        "ProjectConfigurationDevicesProvider": config.project_configuration_devices,
        "ProjectDataCollectionDevicesProvider": config.project_data_collection_devices,
        "DataCollectionVariableSync": config.data_collection_variable_sync,
        "DeviceDetailSync": config.device_detail_sync,
    }
    return sections[section].catalogs[0].scope


@pytest.mark.parametrize("section", SCOPED_SECTIONS)
def test_singular_catalog_scope_is_rejected_in_every_scoped_section(section):
    data = _config_data()
    _scoped_entry(data, section)["catalog_uri"] = "catalog:a"
    with pytest.raises(ConfigValidationError, match=r"unknown setting\(s\): catalog_uri$"):
        PluginConfig.from_mapping(data)


@pytest.mark.parametrize("section", SCOPED_SECTIONS)
@pytest.mark.parametrize("uris", [["catalog:a"], ["catalog:a", "catalog:b", "catalog:a"]])
def test_plural_catalog_scope_matches_and_deduplicates(section, uris):
    data = _config_data()
    _scoped_entry(data, section)["catalog_uris"] = uris
    scope = _parsed_scope(PluginConfig.from_mapping(data), section)
    assert scope.catalog_uris == tuple(dict.fromkeys(uris))
    assert scope.matches("catalog:a")
    assert scope.matches("catalog:b") == ("catalog:b" in uris)
    assert not scope.matches("catalog:other")


@pytest.mark.parametrize("section", [name for name in SCOPED_SECTIONS if name != "DataCollectionVariableSync"])
@pytest.mark.parametrize("scope", [None, []])
def test_omitted_or_empty_catalog_scope_remains_wildcard(section, scope):
    data = _config_data()
    entry = _scoped_entry(data, section)
    if scope is None:
        entry.pop("catalog_uris", None)
    else:
        entry["catalog_uris"] = scope
    parsed = _parsed_scope(PluginConfig.from_mapping(data), section)
    assert parsed.catalog_uris == ()
    assert parsed.matches("catalog:any")


def test_sms_provider_requires_routing_and_request_settings():
    data = _config_data()
    provider = data["DeviceSearchProvider"]["providers"]["SensorManagementSystemDeviceProvider"][0]
    del provider["text_prefix"]

    with pytest.raises(
        ConfigValidationError,
        match=r"DeviceSearchProvider\.providers\.SensorManagementSystemDeviceProvider\[0\]: "
        r"missing required setting\(s\): text_prefix",
    ):
        PluginConfig.from_mapping(data)


def test_membership_filter_attributes_must_be_configured_as_a_pair():
    data = _config_data()
    catalog = data["handlers"]["SensorManagementSystemConfigurationHandler"]["catalogs"][0]
    catalog["membership_filter_enabled"] = True
    catalog["membership_filter_start_attribute_uri"] = "https://example.com/member-filter-start"

    with pytest.raises(
        ConfigValidationError,
        match=r"handlers\.SensorManagementSystemConfigurationHandler\.catalogs\[0\]: "
        r"membership_filter_start_attribute_uri and membership_filter_end_attribute_uri "
        r"must be configured together",
    ):
        PluginConfig.from_mapping(data)


def test_membership_filter_attributes_require_explicit_enablement():
    data = _config_data()
    catalog = data["handlers"]["SensorManagementSystemConfigurationHandler"]["catalogs"][0]
    catalog["membership_filter_start_attribute_uri"] = "https://example.com/member-filter-start"
    catalog["membership_filter_end_attribute_uri"] = "https://example.com/member-filter-end"

    with pytest.raises(
        ConfigValidationError,
        match=r"membership filter attribute URIs require membership_filter_enabled = true",
    ):
        PluginConfig.from_mapping(data)


def test_o2a_membership_filter_settings_are_rejected_until_supported():
    data = _config_data()
    catalog = data["handlers"]["O2ARegistryMissionHandler"]["catalogs"][0]
    catalog["membership_filter_enabled"] = True

    with pytest.raises(
        ConfigValidationError,
        match=r"O2ARegistryMissionHandler\.catalogs\[0\]: unknown setting\(s\): membership_filter_enabled",
    ):
        PluginConfig.from_mapping(data)


def test_o2a_mission_requires_an_item_handler_for_the_same_backend():
    data = _config_data()
    del data["handlers"]["O2ARegistryItemHandler"]
    del data["DeviceSearchProvider"]["providers"]["O2ARegistryItemProvider"]
    with pytest.raises(ConfigValidationError, match="has no matching O2ARegistryItemHandler"):
        PluginConfig.from_mapping(data)
