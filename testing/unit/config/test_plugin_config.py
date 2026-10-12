import sys
from copy import deepcopy
from dataclasses import fields
from urllib.parse import urlsplit
from xml.etree import ElementTree

import pytest

from rdmo_sensorsearch.config_models import PluginConfig
from rdmo_sensorsearch.services.device_detail_profile import get_device_detail_settings
from testing.paths import CATALOGS_ROOT, FIXTURES_ROOT, PRODUCTION_CONFIG_PATH, REPOSITORY_ROOT

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


CONFIG_PATHS = (PRODUCTION_CONFIG_PATH,)
MIRROR_CONFIG_PATH = FIXTURES_ROOT / "sensorsearch-plugin-dev.toml"
MIRROR_CATALOG_PATH = CATALOGS_ROOT / "example_catalog_sensorsearch.xml"
MIRROR_CATALOG_URI = "https://example.com/terms/questions/plugin-dev/sensorsearch"
EARTH_SENSOR_CATALOG_URI = "https://rdmo.nfdi4earth.de/terms/questions/earth-sensor-with-refresh-feature-v1"
ORIGINAL_EARTH_SENSOR_CATALOG_PATH = CATALOGS_ROOT / "earth-sensor+original.xml"
DC_URI = "{http://purl.org/dc/elements/1.1/}uri"


def _load_config(path):
    with path.open("rb") as config_file:
        return tomllib.load(config_file)


def _attribute_uris(settings):
    return {
        value
        for field in fields(settings)
        if field.name.endswith("_attribute_uri") and isinstance(value := getattr(settings, field.name), str)
    }


@pytest.mark.parametrize(
    "config_path,catalog_path",
    [(PRODUCTION_CONFIG_PATH, ORIGINAL_EARTH_SENSOR_CATALOG_PATH), (MIRROR_CONFIG_PATH, MIRROR_CATALOG_PATH)],
)
def test_catalog_matches_effective_deployment_configuration(config_path, catalog_path):
    root = ElementTree.parse(catalog_path).getroot()
    catalog_uri = root.find("catalog").attrib[DC_URI]
    attribute_uris = {attribute.attrib[DC_URI] for attribute in root.findall("attribute")}
    config = PluginConfig.from_mapping(_load_config(config_path))

    configured_attribute_uris = set()
    for handler in config.handlers.values():
        for catalog in handler.catalogs:
            if not catalog.scope.matches(catalog_uri):
                continue
            configured_attribute_uris.add(catalog.search_attribute_uri)
            configured_attribute_uris.update(catalog.settings.managed_attribute_uris)
            configured_attribute_uris.update(catalog.attribute_mapping.values())
            configured_attribute_uris.update(_attribute_uris(catalog.settings))

    refresh = config.metadata_refresh
    configured_attribute_uris.update(_attribute_uris(refresh))
    for action in refresh.actions:
        if action.scope.matches(catalog_uri):
            configured_attribute_uris.update(_attribute_uris(action))
            configured_attribute_uris.update(action.input_attribute_uris)
    for section in (config.data_collection_variable_sync, config.device_detail_sync):
        for catalog in section.catalogs:
            if catalog.scope.matches(catalog_uri):
                configured_attribute_uris.update(_attribute_uris(catalog.settings))
    for section in (config.project_configuration_devices, config.project_data_collection_devices):
        for catalog in section.catalogs:
            if catalog.scope.matches(catalog_uri):
                configured_attribute_uris.add(catalog.source_attribute_uri)

    assert configured_attribute_uris - attribute_uris == set()
    assert any(catalog.scope.matches(catalog_uri) for catalog in config.data_collection_variable_sync.catalogs)


def test_deployment_configuration_passes_schema_validation():
    config = PluginConfig.from_mapping(_load_config(CONFIG_PATHS[0]))

    assert len(config.device_search.providers) == 5
    assert len(config.configuration_search.providers) == 4
    assert len(config.handlers) == 5


def test_plugin_development_catalog_has_an_isolated_complete_test_profile():
    parsed = PluginConfig.from_mapping(_load_config(MIRROR_CONFIG_PATH))
    mirror_attributes = {
        attribute.attrib[DC_URI] for attribute in ElementTree.parse(MIRROR_CATALOG_PATH).getroot().findall("attribute")
    }

    assert "example.com" not in CONFIG_PATHS[0].read_text(encoding="utf-8")
    detail_settings = get_device_detail_settings(MIRROR_CATALOG_URI, config=parsed)
    assert detail_settings.device_details_page_uri == "https://example.com/terms/questions/plugin-dev/instruments_general"
    assert detail_settings.configuration_collection_attribute_uri in mirror_attributes
    assert any(catalog.scope.matches(MIRROR_CATALOG_URI) for catalog in parsed.data_collection_variable_sync.catalogs)


def test_wheel_build_packages_the_authoritative_deployment_configuration():
    build_config = _load_config(REPOSITORY_ROOT / "pyproject.toml")

    assert build_config["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"] == {
        "sensorsearch.toml": "rdmo_sensorsearch/sensorsearch.toml"
    }


def test_gfz_sms_connection_is_defined_once():
    for path in CONFIG_PATHS:
        config = PluginConfig.from_mapping(_load_config(path))
        backend = config.backend("gfz")
        assert urlsplit(backend.base_url).hostname == "sensors.gfz.de"
        for name in ("SensorManagementSystemDeviceHandler", "SensorManagementSystemConfigurationHandler"):
            assert config.handlers[name].instances[0].backend == "gfz"
        for section in (config.device_search, config.configuration_search):
            assert any(provider.backend == "gfz" for provider in section.providers)


def test_data_collection_variable_sync_is_explicitly_catalog_scoped():
    for path in CONFIG_PATHS:
        config = PluginConfig.from_mapping(_load_config(path))
        catalog_configs = config.data_collection_variable_sync.catalogs

        assert catalog_configs
        assert all(catalog.scope.catalog_uris for catalog in catalog_configs)
        assert any(catalog.scope.matches(EARTH_SENSOR_CATALOG_URI) for catalog in catalog_configs)


def test_handlers_declare_additional_owned_attributes_as_managed():
    for path in CONFIG_PATHS:
        config = PluginConfig.from_mapping(_load_config(path))
        assert all(
            all(catalog.settings.managed_attribute_uris) for handler in config.handlers.values() for catalog in handler.catalogs
        )


def test_configuration_providers_use_compact_backend_labels():
    expected = {"gfzcfg": "GFZ Cfg", "kitcfg": "KIT Cfg", "ufzcfg": "UFZ Cfg", "o2amission": "O2A M"}
    for path in CONFIG_PATHS:
        config = PluginConfig.from_mapping(_load_config(path))
        assert {
            config.backend(provider.backend).configuration_id_prefix: provider.settings.text_prefix
            for provider in config.configuration_search.providers
        } == expected


def test_configuration_handlers_define_the_shared_tab_collection_attribute():
    expected_uri = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set"

    for path in CONFIG_PATHS:
        config = PluginConfig.from_mapping(_load_config(path))
        for name in ("SensorManagementSystemConfigurationHandler", "O2ARegistryMissionHandler"):
            assert all(
                catalog.settings.configuration_collection_attribute_uri == expected_uri
                for catalog in config.handlers[name].catalogs
            )


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
        config = PluginConfig.from_mapping(_load_config(path))

        for handler_name, (start_path, end_path) in source_paths.items():
            for catalog in config.handlers[handler_name].catalogs:
                assert expected_start_uri in catalog.settings.managed_attribute_uris
                assert expected_end_uri in catalog.settings.managed_attribute_uris
                assert catalog.attribute_mapping[start_path] == expected_start_uri
                assert catalog.attribute_mapping[end_path] == expected_end_uri


def test_baseline_has_no_membership_filter_action():
    for path in CONFIG_PATHS:
        config = PluginConfig.from_mapping(_load_config(path))
        assert not any(action.require_configuration_period for action in config.metadata_refresh.actions)
        assert not any(
            action.trigger_attribute_uri.endswith(("/apply-date-range", "/apply-member-filter"))
            for action in config.metadata_refresh.actions
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
    assert sms_catalog.settings.membership_filter_enabled is True
    assert parsed.metadata_refresh.actions[-1].require_configuration_period is True


def test_sms_mount_location_resolution_settings_are_shared_backend_settings():
    config = PluginConfig.from_mapping(_load_config(CONFIG_PATHS[0]))
    for name in ("gfz", "kit", "ufz"):
        settings = config.backend(name).settings
        assert settings.static_location_end_tolerance_seconds == 120
        assert settings.incomplete_mount_chain_policy == "direct_device_offset"


@pytest.mark.parametrize("invalid_value", (-1, True, "120", 1.5))
def test_mount_location_tolerance_validation_rejects_invalid_values(invalid_value):
    config = deepcopy(_load_config(CONFIG_PATHS[0]))
    config["backends"][0]["settings"]["static_location_end_tolerance_seconds"] = invalid_value

    with pytest.raises(ValueError, match="static_location_end_tolerance_seconds"):
        PluginConfig.from_mapping(config)


def test_mount_location_tolerance_validation_accepts_zero():
    config = deepcopy(_load_config(CONFIG_PATHS[0]))
    config["backends"][0]["settings"]["static_location_end_tolerance_seconds"] = 0

    PluginConfig.from_mapping(config)


def test_incomplete_mount_chain_policy_validation_rejects_unknown_value():
    config = deepcopy(_load_config(CONFIG_PATHS[0]))
    config["backends"][0]["settings"]["incomplete_mount_chain_policy"] = "guess"

    with pytest.raises(ValueError, match=r"incomplete_mount_chain_policy.*direct_device_offset, strict"):
        PluginConfig.from_mapping(config)


@pytest.mark.parametrize("policy", ("strict", "direct_device_offset"))
def test_incomplete_mount_chain_policy_validation_accepts_supported_values(policy):
    config = deepcopy(_load_config(CONFIG_PATHS[0]))
    config["backends"][0]["settings"]["incomplete_mount_chain_policy"] = policy

    parsed = PluginConfig.from_mapping(config)

    assert parsed.backend("gfz").settings.incomplete_mount_chain_policy == policy
