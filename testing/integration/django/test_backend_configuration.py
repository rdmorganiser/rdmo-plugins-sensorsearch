"""Named definitions preserve existing URL, option, and catalog behavior."""

from dataclasses import replace
from types import MappingProxyType, SimpleNamespace
from urllib.parse import parse_qs, urlsplit

from rdmo_sensorsearch import backend_assembly
from rdmo_sensorsearch.config import load_config_model
from rdmo_sensorsearch.contracts import HandlerExecutionContext, HandlerResult
from rdmo_sensorsearch.handlers import factory as handler_factory
from rdmo_sensorsearch.handlers import gipp_instrument, o2a_item, o2a_mission
from rdmo_sensorsearch.providers import factory as provider_factory
from rdmo_sensorsearch.providers import gipp_instrument as gipp_provider
from rdmo_sensorsearch.providers import o2a_item as item_provider
from rdmo_sensorsearch.providers import o2a_mission as mission_provider
from rdmo_sensorsearch.providers import search as search_provider


def test_all_search_consumers_use_named_definitions_and_preserve_options(monkeypatch):
    calls = []

    def fetch(url, auth_token=None):
        calls.append((url, auth_token))
        if "/devices?" in url:
            return {"data": [{"id": "42", "attributes": {"long_name": "foo"}}]}
        if "/configurations?" in url:
            return {"data": [{"id": "7", "attributes": {"label": "foo"}}]}
        if "/index/rest/search/" in url:
            return {"records": [{"title": "foo", "id": "registry-id", "uniqueId": "uuid"}]}
        if "/missions?" in url:
            return {"records": [{"id": "7", "name": "foo"}]}
        return [{"Instrument": {"id": "2", "code": "foo"}}]

    for module in (backend_assembly, item_provider, mission_provider, gipp_provider):
        monkeypatch.setattr(module, "fetch_json", fetch)
    devices = provider_factory.build_provider_instances("DeviceSearchProvider")
    configurations = provider_factory.build_provider_instances("ConfigurationSearchProvider")
    results = {}
    for provider in (*devices, *configurations):
        provider.auth_token = "per-request-token"
        results[provider.id_prefix] = provider.get_options(None, search="foo")
    assert results["gfzsms"][0]["id"] == "gfzsms:42"
    assert results["gfzcfg"][0] == {"id": "gfzcfg:7", "text": "GFZ Cfg(7): foo"}
    assert results["o2aregistry"][0]["id"] == "o2aregistry:uuid"
    assert results["o2amission"][0] == {"id": "o2amission:7", "text": "O2A M(7): foo"}
    assert results["gfzgipp"][0] == {"id": "gfzgipp:2", "text": "GFZ GIPP Instrument(2): foo"}
    urls = [url for url, token in calls]
    assert "https://sensors.gfz.de/backend/api/v1/devices?q=foo" in urls
    assert (
        "https://sensors.gfz.de/backend/api/v1/configurations?page[size]=10&page[number]=1&include=created_by.contact&filter=[]&q=foo&sort=label&hide_archived=false"
        in urls
    )
    assert "https://gipp.gfz.de/instruments/index.json?limit=10000&program=MOSES" in urls
    mission_url = next(url for url in urls if "/rest/v2/missions?" in url)
    assert parse_qs(urlsplit(mission_url).query)["where"] == ['name=ILIKE="*foo*"']
    assert all(token == "per-request-token" for url, token in calls if "/backend/api/v1/" in url)
    assert all(token is None for url, token in calls if "o2a-data" in url or "gipp.gfz" in url)


def test_o2a_and_gipp_metadata_use_existing_endpoints_and_mappings(monkeypatch):
    calls = []

    def fetch(url, auth_token=None):
        calls.append(url)
        if url.endswith("/items/1"):
            return {"longName": "Item", "id": "1"}
        if url.endswith("/missions/1"):
            return {"name": "Mission", "id": "1", "description": "Description"}
        if url.endswith("/1.json"):
            return {"Instrument": {"code": "Instrument"}}
        return {"records": []}

    for module in (o2a_item, o2a_mission, gipp_instrument):
        monkeypatch.setattr(module, "fetch_json", fetch)
    bindings = {binding.id_prefix: binding for binding in handler_factory.build_handlers_by_catalog()["*"]}
    for prefix in ("o2aregistry", "o2amission", "gfzgipp"):
        result = bindings[prefix].handler.handle("1", context=HandlerExecutionContext())
        assert isinstance(result, HandlerResult)
    assert calls == [
        "https://registry.o2a-data.de/rest/v2/items/1",
        "https://registry.o2a-data.de/rest/v2/items/1/contacts",
        "https://registry.o2a-data.de/rest/v2/items/1/parameters",
        "https://registry.o2a-data.de/rest/v2/units",
        "https://registry.o2a-data.de/rest/v2/missions/1",
        "https://registry.o2a-data.de/rest/v2/missions/1/items?offset=0&hits=100",
        "https://gipp.gfz.de/instruments/rest/1.json",
    ]
    assert bindings["o2amission"].handler.item_id_prefix == "o2aregistry"
    assert bindings["kitcfg"].handler.device_id_prefix == "kitsms"


def test_sms_search_filter_uses_declared_namespaces_without_suffix_inference(monkeypatch):
    config = load_config_model()
    definitions = dict(config.backends)
    definitions["kit"] = replace(definitions["kit"], device_id_prefix="instruments-k", configuration_id_prefix="campaigns-k")
    config = replace(config, backends=MappingProxyType(definitions))
    monkeypatch.setattr(search_provider, "load_config_model", lambda: config)
    monkeypatch.setattr(handler_factory, "load_config_model", lambda: config)
    monkeypatch.setattr(provider_factory, "load_config_model", lambda: config)
    bindings = handler_factory.build_handlers_by_catalog()["*"]
    monkeypatch.setattr(search_provider, "get_handler_bindings_for_catalog", lambda uri: bindings)

    class Query:
        def filter(self, **kwargs):
            return self

        def exclude(self, **kwargs):
            return self

        def values_list(self, *args, **kwargs):
            return ["campaigns-k:49", "o2amission:7"]

    monkeypatch.setattr(search_provider.Value, "objects", Query())
    aggregate = search_provider.DeviceSearchProvider("test", "Test", "rdmo_sensorsearch.providers.DeviceSearchProvider")
    providers = provider_factory.build_provider_instances("DeviceSearchProvider")
    project = SimpleNamespace(catalog=SimpleNamespace(uri="catalog"))
    assert aggregate._allowed_sms_prefixes(project) == {"instruments-k"}
    filtered = aggregate._filter_providers_for_project(project, providers)
    assert {provider.id_prefix for provider in filtered} == {"instruments-k", "o2aregistry", "gfzgipp"}


def test_rebuilding_consumers_does_not_share_mutable_provider_or_mapping_state():
    first = provider_factory.build_provider_instances("DeviceSearchProvider")
    second = provider_factory.build_provider_instances("DeviceSearchProvider")
    first[1].auth_token = "request-a"
    assert first[1] is not second[1]
    assert not hasattr(second[1], "auth_token")
    config = load_config_model()
    assert config.backend("gfz").auth.source == "sms_user_token"
