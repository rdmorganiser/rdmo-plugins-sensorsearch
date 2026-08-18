import sys
from concurrent.futures import ThreadPoolExecutor
from time import sleep
from types import ModuleType, SimpleNamespace

from rdmo_sensorsearch.handlers import catalog_registry


class ExactHandler:
    pass


class WildcardHandler:
    pass


def _binding(id_prefix, search_attribute_uri, handler):
    return SimpleNamespace(
        id_prefix=id_prefix,
        search_attribute_uri=search_attribute_uri,
        handler=handler,
    )


def test_catalog_registry_merges_wildcard_bindings_without_duplicates(monkeypatch):
    exact = _binding("sms", "attribute:configuration", ExactHandler())
    duplicate = _binding("sms", "attribute:configuration", ExactHandler())
    wildcard = _binding("o2a", "attribute:mission", WildcardHandler())
    monkeypatch.setattr(
        catalog_registry,
        "_HANDLER_BINDINGS_BY_CATALOG",
        {
            "catalog:earth-sensor": [exact],
            catalog_registry.WILDCARD_CATALOG_URI: [duplicate, wildcard],
        },
    )

    bindings = catalog_registry.get_handler_bindings_for_catalog("catalog:earth-sensor")

    assert bindings == [exact, wildcard]


def test_catalog_registry_returns_wildcard_bindings_for_unknown_catalog(monkeypatch):
    wildcard = _binding("gipp", "attribute:instrument", WildcardHandler())
    monkeypatch.setattr(
        catalog_registry,
        "_HANDLER_BINDINGS_BY_CATALOG",
        {catalog_registry.WILDCARD_CATALOG_URI: [wildcard]},
    )

    assert catalog_registry.get_handler_bindings_for_catalog("catalog:other") == [wildcard]


def test_catalog_registry_builds_configured_bindings_only_once(monkeypatch):
    calls = []
    configured_bindings = {"catalog:earth-sensor": []}
    factory = ModuleType("rdmo_sensorsearch.handlers.factory")

    def build_handlers_by_catalog():
        sleep(0.01)
        calls.append(True)
        return configured_bindings

    factory.build_handlers_by_catalog = build_handlers_by_catalog
    monkeypatch.setitem(sys.modules, "rdmo_sensorsearch.handlers.factory", factory)
    monkeypatch.setattr(catalog_registry, "_HANDLER_BINDINGS_BY_CATALOG", None)

    with ThreadPoolExecutor(max_workers=8) as executor:
        registries = list(executor.map(lambda _index: catalog_registry.handler_bindings_by_catalog(), range(8)))

    assert all(registry is configured_bindings for registry in registries)
    assert len(calls) == 1
