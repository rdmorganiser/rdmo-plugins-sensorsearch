from copy import deepcopy
from pathlib import Path

import pytest

from rdmo_sensorsearch.config_models import ConfigValidationError, PluginConfig
from rdmo_sensorsearch.config_models.models import PluginConfig as InternalPluginConfig
from rdmo_sensorsearch.config_models.validation import ConfigValidationError as InternalConfigValidationError

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


CONFIG_PATH = Path(__file__).parents[1] / "sensorsearch.toml"


def test_config_models_package_preserves_public_model_and_error_exports():
    assert PluginConfig is InternalPluginConfig
    assert ConfigValidationError is InternalConfigValidationError


def _config_data():
    with CONFIG_PATH.open("rb") as config_file:
        return tomllib.load(config_file)


def test_configuration_model_exposes_typed_sections_and_read_only_raw_data():
    config = PluginConfig.from_mapping(_config_data())

    assert config.device_search.minimum_search_length == 3
    assert config.device_search.filter_sms_devices_by_selected_configuration is False
    assert config.metadata_refresh.actions[1].require_configuration_period is True
    assert config.handlers["SensorManagementSystemConfigurationHandler"].id_prefixes == (
        "gfzcfg",
        "kitcfg",
        "ufzcfg",
    )

    with pytest.raises(TypeError):
        config.raw["unexpected"] = {}


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
    providers[1]["id_prefix"] = providers[0]["id_prefix"]

    with pytest.raises(ConfigValidationError, match=r"providers: duplicate id_prefix 'gfzsms'"):
        PluginConfig.from_mapping(data)


def test_provider_prefix_without_matching_handler_is_rejected():
    data = _config_data()
    providers = data["DeviceSearchProvider"]["providers"]["SensorManagementSystemDeviceProvider"]
    providers[0]["id_prefix"] = "unmatchedsms"

    with pytest.raises(
        ConfigValidationError,
        match=r"providers\.SensorManagementSystemDeviceProvider: id_prefix 'unmatchedsms' has no matching",
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


def test_data_collection_sync_requires_explicit_catalog_scope():
    data = _config_data()
    catalog = data["DataCollectionVariableSync"]["catalogs"][0]
    del catalog["catalog_uris"]

    with pytest.raises(
        ConfigValidationError,
        match=r"DataCollectionVariableSync\.catalogs\[0\]: catalog_uri or catalog_uris is required",
    ):
        PluginConfig.from_mapping(data)


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


def test_configuration_period_attributes_must_be_configured_as_a_pair():
    data = _config_data()
    catalog = data["handlers"]["O2ARegistryMissionHandler"]["catalogs"][0]
    del catalog["period_end_attribute_uri"]

    with pytest.raises(
        ConfigValidationError,
        match=r"handlers\.O2ARegistryMissionHandler\.catalogs\[0\]: "
        r"period_start_attribute_uri and period_end_attribute_uri must be configured together",
    ):
        PluginConfig.from_mapping(data)


def test_o2a_mission_member_prefix_must_match_the_item_handler():
    data = _config_data()
    data["handlers"]["O2ARegistryMissionHandler"]["defaults"]["item_id_prefix"] = "unknownitems"

    with pytest.raises(
        ConfigValidationError,
        match=r"handlers\.O2ARegistryMissionHandler\.defaults\.item_id_prefix: "
        r"'unknownitems' has no matching O2A item handler",
    ):
        PluginConfig.from_mapping(data)
