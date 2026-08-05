import sys
from pathlib import Path
from urllib.parse import urlsplit

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


ROOT = Path(__file__).parents[1]
CONFIG_PATHS = (ROOT / "sensorsearch.toml", ROOT / "rdmo_sensorsearch" / "config.toml")
EARTH_SENSOR_CATALOG_URI = "https://rdmo.nfdi4earth.de/terms/questions/earth-sensor-with-refresh-feature-v1"


def _load_config(path):
    with path.open("rb") as config_file:
        return tomllib.load(config_file)


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


def test_configuration_date_range_inputs_are_enabled_for_sms_and_o2a():
    expected_start_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-start-datetime"
    expected_end_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configurations-end-datetime"

    for path in CONFIG_PATHS:
        config = _load_config(path)
        handlers = config["handlers"]

        for handler_name in (
            "SensorManagementSystemConfigurationHandler",
            "O2ARegistryMissionHandler",
        ):
            catalog_config = handlers[handler_name]["catalogs"][0]
            defaults = handlers[handler_name]["defaults"]

            assert catalog_config["period_start_attribute_uri"] == expected_start_uri
            assert catalog_config["period_end_attribute_uri"] == expected_end_uri
            assert expected_start_uri not in defaults["managed_attribute_uris"]
            assert expected_end_uri not in defaults["managed_attribute_uris"]
            assert expected_start_uri not in defaults["attribute_mapping"].values()
            assert expected_end_uri not in defaults["attribute_mapping"].values()


def test_apply_date_range_action_is_explicit_and_replaces_collections():
    expected_inputs = {
        "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-start-datetime",
        "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configurations-end-datetime",
    }

    for path in CONFIG_PATHS:
        config = _load_config(path)
        action = next(
            action
            for action in config["MetadataRefresh"]["actions"]
            if action["trigger_attribute_uri"].endswith("/apply-date-range")
        )

        assert action["kind"] == "configuration"
        assert action["replace_existing_collections"] is True
        assert action["require_configuration_period"] is True
        assert set(action["input_attribute_uris"]) == expected_inputs
