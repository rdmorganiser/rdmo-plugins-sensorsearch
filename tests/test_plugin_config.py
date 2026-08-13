import sys
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from rdmo_sensorsearch.config_models import PluginConfig

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


ROOT = Path(__file__).parents[1]
CONFIG_PATHS = (ROOT / "sensorsearch.toml",)
EARTH_SENSOR_CATALOG_URI = "https://rdmo.nfdi4earth.de/terms/questions/earth-sensor-with-refresh-feature-v1"


def _load_config(path):
    with path.open("rb") as config_file:
        return tomllib.load(config_file)


def test_deployment_configuration_passes_schema_validation():
    config = PluginConfig.from_mapping(_load_config(CONFIG_PATHS[0]))

    assert len(config.device_search.providers) == 5
    assert len(config.configuration_search.providers) == 4
    assert len(config.handlers) == 5


def test_wheel_build_packages_the_authoritative_deployment_configuration():
    build_config = _load_config(ROOT / "pyproject.toml")

    assert build_config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"] == {
        "sensorsearch.toml": "rdmo_sensorsearch/sensorsearch.toml"
    }


def _backend(config, section, id_prefix):
    entries = config[section]
    if isinstance(entries, dict):
        entries = entries["backends"]
    return next(backend for backend in entries if backend["id_prefix"] == id_prefix)


def test_gfz_sms_handlers_and_providers_use_the_same_current_host():
    for path in CONFIG_PATHS:
        config = _load_config(path)
        handler_urls = (
            _backend(config["handlers"], "SensorManagementSystemDeviceHandler", "gfzsms")["base_url"],
            _backend(config["handlers"], "SensorManagementSystemConfigurationHandler", "gfzcfg")["base_url"],
        )
        provider_urls = (
            _backend(config["DeviceSearchProvider"]["providers"], "SensorManagementSystemDeviceProvider", "gfzsms")["base_url"],
            _backend(
                config["ConfigurationSearchProvider"]["providers"],
                "SensorManagementSystemConfigurationProvider",
                "gfzcfg",
            )["base_url"],
        )

        assert {urlsplit(url).hostname for url in (*handler_urls, *provider_urls)} == {"sensors.gfz.de"}


def test_data_collection_variable_sync_is_explicitly_catalog_scoped():
    for path in CONFIG_PATHS:
        config = _load_config(path)
        catalog_configs = config["DataCollectionVariableSync"]["catalogs"]

        assert catalog_configs
        assert all(catalog_config.get("catalog_uri") or catalog_config.get("catalog_uris") for catalog_config in catalog_configs)
        assert any(
            EARTH_SENSOR_CATALOG_URI
            in ([catalog_config["catalog_uri"]] if catalog_config.get("catalog_uri") else catalog_config["catalog_uris"])
            for catalog_config in catalog_configs
        )


def test_handlers_declare_additional_owned_attributes_as_managed():
    for path in CONFIG_PATHS:
        config = _load_config(path)
        handler_configs = config["handlers"]

        def assert_managed(config_part):
            if isinstance(config_part, dict):
                assert "reset_attribute_uris" not in config_part
                if "managed_attribute_uris" in config_part:
                    assert all(config_part["managed_attribute_uris"])
                for value in config_part.values():
                    assert_managed(value)
            elif isinstance(config_part, list):
                for value in config_part:
                    assert_managed(value)

        assert_managed(handler_configs)


def test_configuration_providers_use_compact_backend_labels():
    expected_prefixes = {
        "gfzcfg": "GFZ Cfg",
        "kitcfg": "KIT Cfg",
        "ufzcfg": "UFZ Cfg",
        "o2amission": "O2A M",
    }

    for path in CONFIG_PATHS:
        config = _load_config(path)
        providers = config["ConfigurationSearchProvider"]["providers"]

        for id_prefix, expected_prefix in expected_prefixes.items():
            provider_name = (
                "O2ARegistryMissionProvider" if id_prefix == "o2amission" else "SensorManagementSystemConfigurationProvider"
            )
            assert _backend(providers, provider_name, id_prefix)["text_prefix"] == expected_prefix


def test_configuration_handlers_define_the_shared_tab_collection_attribute():
    expected_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set"

    for path in CONFIG_PATHS:
        config = _load_config(path)
        handlers = config["handlers"]

        assert (
            handlers["SensorManagementSystemConfigurationHandler"]["defaults"]["configuration_collection_attribute_uri"]
            == expected_uri
        )
        assert handlers["O2ARegistryMissionHandler"]["defaults"]["configuration_collection_attribute_uri"] == expected_uri


def test_configuration_period_is_backend_owned_for_sms_and_o2a():
    expected_start_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-start-datetime"
    expected_end_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configurations-end-datetime"
    source_paths = {
        "SensorManagementSystemConfigurationHandler": (
            "data.attributes.start_date",
            "data.attributes.end_date",
        ),
        "O2ARegistryMissionHandler": ("startDate", "endDate"),
    }

    for path in CONFIG_PATHS:
        config = _load_config(path)
        handlers = config["handlers"]

        for handler_name, (start_path, end_path) in source_paths.items():
            defaults = handlers[handler_name]["defaults"]

            assert expected_start_uri in defaults["managed_attribute_uris"]
            assert expected_end_uri in defaults["managed_attribute_uris"]
            assert defaults["attribute_mapping"][start_path] == expected_start_uri
            assert defaults["attribute_mapping"][end_path] == expected_end_uri


def test_baseline_has_no_membership_filter_action():
    for path in CONFIG_PATHS:
        config = _load_config(path)
        assert not any(action.get("require_configuration_period", False) for action in config["MetadataRefresh"]["actions"])
        assert not any(
            action["trigger_attribute_uri"].endswith(("/apply-date-range", "/apply-member-filter"))
            for action in config["MetadataRefresh"]["actions"]
        )


def test_sms_membership_filter_can_be_enabled_as_an_explicit_extension():
    config = deepcopy(_load_config(CONFIG_PATHS[0]))
    start_uri = "https://example.com/member-filter-start"
    end_uri = "https://example.com/member-filter-end"
    catalog = config["handlers"]["SensorManagementSystemConfigurationHandler"]["catalogs"][0]
    catalog.update(
        membership_filter_enabled=True,
        membership_filter_start_attribute_uri=start_uri,
        membership_filter_end_attribute_uri=end_uri,
    )
    config["MetadataRefresh"]["actions"].append(
        {
            "kind": "configuration",
            "trigger_attribute_uri": "https://example.com/apply-member-filter",
            "replace_existing_collections": True,
            "require_configuration_period": True,
            "input_attribute_uris": [start_uri, end_uri],
        }
    )

    parsed = PluginConfig.from_mapping(config)

    sms_catalog = parsed.handlers["SensorManagementSystemConfigurationHandler"].catalogs[0]
    assert sms_catalog.settings["membership_filter_enabled"] is True
    assert parsed.metadata_refresh.actions[-1].require_configuration_period is True


def test_sms_handlers_share_mount_location_resolution_settings():
    config = _load_config(CONFIG_PATHS[0])
    handlers = config["handlers"]

    for handler_name in (
        "SensorManagementSystemDeviceHandler",
        "SensorManagementSystemConfigurationHandler",
    ):
        defaults = handlers[handler_name]["defaults"]
        assert defaults["static_location_end_tolerance_seconds"] == 120
        assert defaults["incomplete_mount_chain_policy"] == "direct_device_offset"


@pytest.mark.parametrize("invalid_value", (-1, True, "120", 1.5))
def test_mount_location_tolerance_validation_rejects_invalid_values(invalid_value):
    config = deepcopy(_load_config(CONFIG_PATHS[0]))
    config["handlers"]["SensorManagementSystemDeviceHandler"]["defaults"]["static_location_end_tolerance_seconds"] = invalid_value

    with pytest.raises(ValueError, match="static_location_end_tolerance_seconds"):
        PluginConfig.from_mapping(config)


def test_mount_location_tolerance_validation_accepts_zero():
    config = deepcopy(_load_config(CONFIG_PATHS[0]))
    config["handlers"]["SensorManagementSystemDeviceHandler"]["defaults"]["static_location_end_tolerance_seconds"] = 0

    PluginConfig.from_mapping(config)


def test_incomplete_mount_chain_policy_validation_rejects_unknown_value():
    config = deepcopy(_load_config(CONFIG_PATHS[0]))
    config["handlers"]["SensorManagementSystemConfigurationHandler"]["defaults"]["incomplete_mount_chain_policy"] = "guess"

    with pytest.raises(ValueError, match=r"incomplete_mount_chain_policy.*direct_device_offset, strict"):
        PluginConfig.from_mapping(config)


@pytest.mark.parametrize("policy", ("strict", "direct_device_offset"))
def test_incomplete_mount_chain_policy_validation_accepts_supported_values(policy):
    config = deepcopy(_load_config(CONFIG_PATHS[0]))
    config["handlers"]["SensorManagementSystemConfigurationHandler"]["defaults"]["incomplete_mount_chain_policy"] = policy

    parsed = PluginConfig.from_mapping(config)

    assert parsed.handlers["SensorManagementSystemConfigurationHandler"].defaults["incomplete_mount_chain_policy"] == policy
