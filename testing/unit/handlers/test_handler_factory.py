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
