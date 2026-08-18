import importlib
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from rdmo_sensorsearch.config_models import PluginConfig
from rdmo_sensorsearch.handlers.base import BackendRecordHandler
from testing.paths import PRODUCTION_CONFIG_PATH

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


CONFIG_PATH = PRODUCTION_CONFIG_PATH


class FactoryHandler(BackendRecordHandler):
    id_prefix = "test"


def test_factory_materializes_attribute_mappings_from_immutable_configuration(monkeypatch):
    with CONFIG_PATH.open("rb") as config_file:
        plugin_config = PluginConfig.from_mapping(tomllib.load(config_file))

    django_module = ModuleType("django")
    django_conf_module = ModuleType("django.conf")
    django_conf_module.settings = SimpleNamespace()
    django_module.conf = django_conf_module
    registry_module = ModuleType("rdmo_sensorsearch.handlers.registry")
    registry_module.HANDLER_REGISTRY = dict.fromkeys(plugin_config.raw["handlers"], FactoryHandler)
    with patch.dict(
        sys.modules,
        {
            "django": django_module,
            "django.conf": django_conf_module,
            "rdmo_sensorsearch.handlers.registry": registry_module,
        },
    ):
        factory = importlib.import_module("rdmo_sensorsearch.handlers.factory")
        monkeypatch.setattr(factory, "load_config", lambda: plugin_config.raw)

        bindings_by_catalog = factory.build_handlers_by_catalog()
    bindings = [binding for catalog_bindings in bindings_by_catalog.values() for binding in catalog_bindings]

    assert bindings
    assert all(isinstance(binding.handler.attribute_mapping, dict) for binding in bindings)
