"""All configured consumers are assembled from typed profiles without HTTP."""

import pytest

from django.conf import settings

from rdmo.core.plugins import get_plugin

from rdmo_sensorsearch import backend_assembly, providers
from rdmo_sensorsearch.config_models import PluginConfig
from rdmo_sensorsearch.config_models.contracts import CONSUMER_CAPABILITIES
from testing.paths import FIXTURES_ROOT, PRODUCTION_CONFIG_PATH
from testing.transport_helpers import raising_fetch

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


@pytest.fixture(params=[PRODUCTION_CONFIG_PATH, FIXTURES_ROOT / "sensorsearch-plugin-dev.toml"])
def profile(request):
    with request.param.open("rb") as stream:
        return tomllib.load(stream)


@pytest.fixture(params=[False, True], ids=["deployment", "custom-connections"])
def config(profile, request, monkeypatch):
    if request.param:
        for definition in profile["backends"]:
            definition["base_url"] = f"https://{definition['name']}.assembly.example/root"
            for key in ("device_id_prefix", "configuration_id_prefix"):
                if key in definition:
                    definition[key] = f"custom-{definition[key]}"
        next(definition for definition in profile["backends"] if definition["type"] == "o2a")["settings"] = {
            "mission_query_url": "{base_url}?q={query}&hits={hits}",
        }
        next(definition for definition in profile["backends"] if definition["type"] == "gipp")["settings"] = {
            "instruments_url": "{base_url}/custom-instruments.json",
        }
        for section in ("DeviceSearchProvider", "ConfigurationSearchProvider"):
            for entries in profile[section]["providers"].values():
                for entry in entries:
                    entry["text_prefix"] = f"Custom {entry['backend']}"
                    entry["max_hits"] = 3

    def unexpected_http(*args, **kwargs):
        pytest.fail("Assembling consumers must not issue HTTP requests")

    monkeypatch.setattr(backend_assembly, "fetch_json", raising_fetch(unexpected_http))
    monkeypatch.setattr("requests.sessions.Session.request", unexpected_http)
    return PluginConfig.from_mapping(profile)


def test_all_provider_builders_use_typed_connection_and_presentation_values(config):
    names = set()
    for instance in (*config.device_search.providers, *config.configuration_search.providers):
        definition = config.backend(instance.backend)
        provider = backend_assembly.PROVIDER_BUILDERS[instance.provider_name](instance, definition)
        backend_type, resource = CONSUMER_CAPABILITIES[instance.provider_name]
        names.add(instance.provider_name)
        assert (provider.backend_name, provider.backend_type, provider.resource_kind) == (definition.name, backend_type, resource)
        assert provider.id_prefix == definition.prefix(resource)
        if definition.type != "sms":
            assert provider.backend.base_url == definition.base_url
            assert provider.backend.settings is definition.settings
        assert not hasattr(provider, "base_url")
        assert (provider.text_prefix, provider.max_hits) == (instance.settings.text_prefix, instance.settings.max_hits)
        if instance.provider_name == "O2ARegistryMissionProvider":
            assert provider.backend._mission.query_url == definition.settings.mission_query_url
            assert provider.backend._mission.search_settings.where_template == instance.settings.where_template
        elif instance.provider_name == "GIPPInstrumentProvider":
            assert provider.backend.settings.instruments_url == definition.settings.instruments_url
        with pytest.raises(TypeError, match="required keyword-only"):
            type(provider)()
    assert names == set(backend_assembly.PROVIDER_BUILDERS)


def test_all_handler_builders_use_typed_connections_and_own_catalog_mappings(config):
    names = set()
    for handler_config in config.handlers.values():
        names.add(handler_config.handler_name)
        _, resource = CONSUMER_CAPABILITIES[handler_config.handler_name]
        for instance in handler_config.instances:
            definition = config.backend(instance.backend)
            for catalog in handler_config.catalogs:
                handler = backend_assembly.HANDLER_BUILDERS[handler_config.handler_name](instance, catalog, definition)
                assert handler.id_prefix == definition.prefix(resource)
                if definition.type != "sms":
                    assert handler.backend.base_url == definition.base_url
                    assert handler.backend.settings is definition.settings
                assert not hasattr(handler, "base_url")
                assert handler.attribute_mapping == dict(catalog.attribute_mapping)
                assert handler.managed_attribute_uris == (
                    frozenset(catalog.attribute_mapping.values()) | frozenset(catalog.settings.managed_attribute_uris)
                )
                if handler_config.handler_name == "O2ARegistryMissionHandler":
                    assert handler.item_id_prefix == definition.device_id_prefix
                elif handler_config.handler_name == "SensorManagementSystemConfigurationHandler":
                    assert handler.device_id_prefix == definition.device_id_prefix
                original = dict(catalog.attribute_mapping)
                handler.attribute_mapping["fixture-only"] = "fixture:uri"
                assert dict(catalog.attribute_mapping) == original
                with pytest.raises(TypeError, match="required keyword-only"):
                    type(handler)()
    assert names == set(backend_assembly.HANDLER_BUILDERS)


def test_rdmo_provider_entry_points_keep_framework_construction_and_refresh_behavior(monkeypatch):
    names = (
        "DeviceSearchProvider",
        "ConfigurationSearchProvider",
        "ProjectConfigurationDevicesProvider",
        "ProjectDataCollectionDevicesProvider",
        "InterviewPageRefreshProvider",
    )
    entries = [(name, name, f"rdmo_sensorsearch.providers.{name}") for name in names]
    monkeypatch.setattr(settings, "OPTIONSET_PROVIDERS", entries)
    for key, label, class_name in entries:
        provider = get_plugin("OPTIONSET_PROVIDERS", key)
        assert isinstance(provider, getattr(providers, key))
        assert (provider.key, provider.label, provider.class_name) == (key, label, class_name)
        if key == "InterviewPageRefreshProvider":
            assert provider.refresh is True
            assert provider.get_options(None) == []
