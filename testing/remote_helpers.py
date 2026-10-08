"""Build remote adapters for endpoint regressions; capability tests inject doubles directly."""

from dataclasses import fields, replace

from rdmo_sensorsearch import backend_assembly
from rdmo_sensorsearch.backends.o2a.backend import O2ABackend
from rdmo_sensorsearch.config_models.backend_settings import O2ABackendSettings
from rdmo_sensorsearch.handlers.o2a_item import O2ARegistryItemHandler
from rdmo_sensorsearch.handlers.o2a_mission import O2ARegistryMissionHandler
from testing.transport_helpers import raising_fetch


def _make_handler(kind, values):
    settings = O2ABackendSettings(api_url="{base_url}")
    endpoints = getattr(settings, kind)
    endpoint_names = {field.name for field in fields(endpoints)}
    endpoints = replace(endpoints, **{name: values.pop(name) for name in tuple(values) if name in endpoint_names})
    settings = replace(settings, **{kind: endpoints})
    backend = O2ABackend(
        base_url=values.pop("base_url", "https://registry.o2a-data.de/rest/v2"),
        settings=settings,
        fetch=raising_fetch(backend_assembly.fetch_json),
    )
    cls = O2ARegistryItemHandler if kind == "item" else O2ARegistryMissionHandler
    handler = cls(
        backend=backend,
        id_prefix=values.pop("id_prefix", "o2aregistry" if kind == "item" else "o2amission"),
        attribute_mapping=values.pop("attribute_mapping", {}),
    )
    for name, value in values.items():
        setattr(handler, name, value)
    return handler


def make_o2a_item_handler(**kwargs):
    return _make_handler("item", kwargs)


def make_o2a_mission_handler(**kwargs):
    return _make_handler("mission", kwargs)
