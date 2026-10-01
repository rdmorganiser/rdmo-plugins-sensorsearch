"""Configuration identity, capabilities, and the one-time schema boundary."""

from dataclasses import FrozenInstanceError

import pytest

from rdmo_sensorsearch.config_models import ConfigValidationError, PluginConfig
from rdmo_sensorsearch.config_models.backend_settings import SMSBackendSettings
from testing.paths import PRODUCTION_CONFIG_PATH

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def configuration():
    with PRODUCTION_CONFIG_PATH.open("rb") as stream:
        return tomllib.load(stream)


def test_backend_identity_is_independent_of_persisted_namespaces():
    data = configuration()
    data["backends"][0]["name"] = "renamed-installation"
    for section in ("DeviceSearchProvider", "ConfigurationSearchProvider"):
        for entries in data[section]["providers"].values():
            for entry in entries:
                if entry["backend"] == "gfz":
                    entry["backend"] = "renamed-installation"
    for handler in data["handlers"].values():
        for instance in handler["instances"]:
            if instance["backend"] == "gfz":
                instance["backend"] = "renamed-installation"
    parsed = PluginConfig.from_mapping(data)
    definition = parsed.backend("renamed-installation")
    assert definition.device_id_prefix == "gfzsms"
    assert definition.configuration_id_prefix == "gfzcfg"
    assert isinstance(definition.settings, SMSBackendSettings)
    with pytest.raises(FrozenInstanceError):
        definition.name = "other"
    with pytest.raises(FrozenInstanceError):
        definition.settings.device.device_url = "other"
    assert not hasattr(parsed, "raw")
    assert definition.auth.source == "sms_user_token"
    assert parsed.backend("o2a").auth is None


@pytest.mark.parametrize(
    "key,value,message",
    [
        ("name", "kit", "duplicate backend name"),
        ("type", "unknown", "unsupported backend type"),
        ("base_url", "relative/api", "absolute HTTP"),
        ("base_url", "ftp://example.com/api", "absolute HTTP"),
        ("base_url", "https://example.com:invalid/api", "absolute HTTP"),
        ("device_id_prefix", "kitcfg", "duplicate namespace"),
        ("configuration_id_prefix", "gfzsms", "duplicate namespace"),
        ("device_id_prefix", "invalid:prefix", "must not contain"),
        ("configuration_id_prefix", "invalid||prefix", "must not contain"),
    ],
)
def test_invalid_backend_definition_reports_its_path(key, value, message):
    data = configuration()
    data["backends"][0][key] = value
    with pytest.raises(ConfigValidationError, match=message) as caught:
        PluginConfig.from_mapping(data)
    assert caught.value.path.startswith("backends[")


@pytest.mark.parametrize(
    "settings,message",
    [
        ({"o2a_item_endpoint": "wrong"}, "unknown setting"),
        ({"device": {"device_url": "{base_url}/{unknown}"}}, "invalid URL template"),
        ({"device": {"device_url": "relative/device"}}, "absolute HTTP"),
        ({"configuration": {"max_collection_pages": 0}}, "greater than zero"),
        ({"configuration": {"device_mount_action_page_size": True}}, "expected an integer"),
        ({"static_location_end_tolerance_seconds": -1}, "must not be negative"),
        ({"incomplete_mount_chain_policy": "guess"}, "must be one of"),
    ],
)
def test_backend_specific_settings_are_validated(settings, message):
    data = configuration()
    data["backends"][0]["settings"] = settings
    with pytest.raises(ConfigValidationError, match=message):
        PluginConfig.from_mapping(data)


@pytest.mark.parametrize("backend,message", [("missing", "unknown backend"), ("o2a", "requires 'sms'")])
def test_provider_reference_requires_an_existing_compatible_backend(backend, message):
    data = configuration()
    data["DeviceSearchProvider"]["providers"]["SensorManagementSystemDeviceProvider"][0]["backend"] = backend
    with pytest.raises(ConfigValidationError, match=message):
        PluginConfig.from_mapping(data)


def test_missing_required_namespace_is_rejected():
    data = configuration()
    del data["backends"][0]["configuration_id_prefix"]
    with pytest.raises(ConfigValidationError, match="no configuration namespace"):
        PluginConfig.from_mapping(data)


def test_gipp_configuration_namespace_is_rejected():
    data = configuration()
    data["backends"][-1]["configuration_id_prefix"] = "gippconfig"
    with pytest.raises(ConfigValidationError, match="no configuration capability"):
        PluginConfig.from_mapping(data)


def test_duplicate_handler_instances_are_rejected():
    data = configuration()
    instances = data["handlers"]["SensorManagementSystemDeviceHandler"]["instances"]
    instances.append(dict(instances[0]))
    with pytest.raises(ConfigValidationError, match="duplicate backend binding"):
        PluginConfig.from_mapping(data)


def test_old_handler_backend_layout_has_migration_guidance():
    data = configuration()
    handler = data["handlers"]["SensorManagementSystemDeviceHandler"]
    handler["backends"] = [{"id_prefix": "gfzsms", "base_url": "https://example.com/api"}]
    with pytest.raises(ConfigValidationError, match="migrate to top-level"):
        PluginConfig.from_mapping(data)


@pytest.mark.parametrize(
    "key,value", [("base_url", "https://example.com/api"), ("id_prefix", "another"), ("query_url", "{base_url}?q={query}")]
)
def test_provider_connection_overrides_are_rejected(key, value):
    data = configuration()
    data["DeviceSearchProvider"]["providers"]["SensorManagementSystemDeviceProvider"][0][key] = value
    with pytest.raises(ConfigValidationError, match="unknown setting"):
        PluginConfig.from_mapping(data)


def test_configuration_member_requires_device_handler_from_the_same_backend():
    data = configuration()
    data["handlers"]["SensorManagementSystemDeviceHandler"]["instances"].pop(0)
    data["DeviceSearchProvider"]["providers"]["SensorManagementSystemDeviceProvider"].pop(0)
    with pytest.raises(ConfigValidationError, match="has no matching SensorManagementSystemDeviceHandler"):
        PluginConfig.from_mapping(data)


@pytest.mark.parametrize("kind,auth", [("sms", {"source": "new_strategy"}), ("o2a", {"source": "sms_user_token"})])
def test_unsupported_authentication_configuration_is_rejected(kind, auth):
    data = configuration()
    next(entry for entry in data["backends"] if entry["type"] == kind)["auth"] = auth
    with pytest.raises(ConfigValidationError, match="supported"):
        PluginConfig.from_mapping(data)


def test_url_placeholders_must_be_supported_by_the_actual_capability():
    data = configuration()
    data["backends"][0]["settings"]["device"] = {"device_url": "{base_url}/devices/{where}"}
    with pytest.raises(ConfigValidationError, match="invalid URL template"):
        PluginConfig.from_mapping(data)


def test_invalid_provider_defaults_are_rejected_even_if_an_instance_overrides_them():
    data = configuration()
    data["DeviceSearchProvider"]["provider_defaults"] = {"SensorManagementSystemDeviceProvider": {"max_hits": "ten"}}
    data["DeviceSearchProvider"]["providers"]["SensorManagementSystemDeviceProvider"][0]["max_hits"] = 10
    with pytest.raises(ConfigValidationError, match="expected an integer"):
        PluginConfig.from_mapping(data)


def test_complete_provider_profiles_resolve_option_defaults_during_parsing():
    config = PluginConfig.from_mapping(configuration())
    providers = {entry.provider_name: entry for entry in config.configuration_search.providers}
    assert providers["SensorManagementSystemConfigurationProvider"].settings.option_id == "{id_prefix}:{id}"
    assert providers["O2ARegistryMissionProvider"].settings.option_text == "{prefix}({id}): {name}"


def test_configuration_can_be_parsed_without_host_application_imports():
    import subprocess
    import sys

    from testing.paths import REPOSITORY_ROOT

    script = """
import sys
sys.path.insert(0, sys.argv[1])
from rdmo_sensorsearch.config_models import PluginConfig
config = PluginConfig.from_mapping({"backends": [{"name": "test", "type": "sms",
    "base_url": "https://example.com/api", "device_id_prefix": "devices"}]})
assert config.backend("test").device_id_prefix == "devices"
assert not any(name.split(".", 1)[0] in {"django", "rdmo"} for name in sys.modules)
"""
    subprocess.run([sys.executable, "-I", "-c", script, str(REPOSITORY_ROOT)], check=True, capture_output=True, text=True)
