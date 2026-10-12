from dataclasses import replace
from unittest.mock import Mock

from rdmo_sensorsearch.config_models import PluginConfig
from rdmo_sensorsearch.handlers import factory
from testing.paths import PRODUCTION_CONFIG_PATH

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def test_factory_materializes_attribute_mappings_from_immutable_configuration(monkeypatch):
    with PRODUCTION_CONFIG_PATH.open("rb") as config_file:
        config = PluginConfig.from_mapping(tomllib.load(config_file))
    monkeypatch.setattr(factory, "load_config_model", lambda: config)
    by_catalog = factory.build_handlers_by_catalog()
    bindings = [binding for entries in by_catalog.values() for binding in entries]
    assert bindings
    assert all(isinstance(binding.handler.attribute_mapping, dict) for binding in bindings)
    assert all(binding.backend_name in config.backends for binding in bindings)
    wildcard = next(binding for binding in by_catalog["*"] if binding.id_prefix == "gfzsms")
    original = dict(config.handlers["SensorManagementSystemDeviceHandler"].catalogs[-1].attribute_mapping)
    wildcard.handler.attribute_mapping.clear()
    assert dict(config.handlers["SensorManagementSystemDeviceHandler"].catalogs[-1].attribute_mapping) == original


def test_factory_creates_catalog_specific_bindings_with_one_shared_handler(monkeypatch):
    with PRODUCTION_CONFIG_PATH.open("rb") as config_file:
        config = PluginConfig.from_mapping(tomllib.load(config_file))
    handler_name = "SensorManagementSystemDeviceHandler"
    handler_config = config.handlers[handler_name]
    catalog = handler_config.catalogs[0]
    catalog = replace(catalog, scope=replace(catalog.scope, catalog_uris=("catalog:a", "catalog:b")))
    instance = handler_config.instances[0]
    config = replace(
        config,
        handlers={handler_name: replace(handler_config, catalogs=(catalog,), instances=(instance,))},
    )
    builder = Mock(wraps=factory.HANDLER_BUILDERS[handler_name])
    monkeypatch.setattr(factory, "load_config_model", lambda: config)
    monkeypatch.setitem(factory.HANDLER_BUILDERS, handler_name, builder)

    by_catalog = factory.build_handlers_by_catalog()

    assert set(by_catalog) == {"catalog:a", "catalog:b"}
    first, second = by_catalog["catalog:a"][0], by_catalog["catalog:b"][0]
    assert first is not second and first.handler is second.handler
    definition = config.backend(instance.backend)
    builder.assert_called_once_with(instance, catalog, definition)
    for uri, bindings in by_catalog.items():
        assert len(bindings) == 1
        binding = bindings[0]
        assert binding.catalog_uri == uri
        assert binding.search_attribute_uri == catalog.search_attribute_uri
        assert (binding.backend_name, binding.backend_type, binding.resource_kind, binding.id_prefix) == (
            definition.name,
            "sms",
            "device",
            definition.device_id_prefix,
        )
