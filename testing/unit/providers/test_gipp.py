"""Tests for the GIPP instrument backend integration."""

import sys
from importlib import import_module
from types import ModuleType, SimpleNamespace

from rdmo_sensorsearch.contracts import (
    BackendFailure,
    BackendSuccess,
    DeviceMetadata,
    HandlerExecutionContext,
    HandlerFailure,
    SearchRecord,
)
from testing.paths import REPOSITORY_ROOT


def _install_host_application_stubs():
    django = ModuleType("django")
    django_conf = ModuleType("django.conf")
    django_conf.settings = SimpleNamespace()
    django.conf = django_conf

    rdmo = ModuleType("rdmo")
    rdmo.__version__ = "test"
    rdmo_options = ModuleType("rdmo.options")
    rdmo_providers = ModuleType("rdmo.options.providers")
    rdmo_providers.Provider = object
    rdmo_options.providers = rdmo_providers
    rdmo.options = rdmo_options

    sensorsearch_providers = ModuleType("rdmo_sensorsearch.providers")
    sensorsearch_providers.__path__ = [str(REPOSITORY_ROOT / "rdmo_sensorsearch" / "providers")]

    sys.modules.setdefault("django", django)
    sys.modules.setdefault("django.conf", django_conf)
    sys.modules.setdefault("rdmo", rdmo)
    sys.modules.setdefault("rdmo.options", rdmo_options)
    sys.modules.setdefault("rdmo.options.providers", rdmo_providers)
    sys.modules.setdefault("rdmo_sensorsearch.providers", sensorsearch_providers)


_install_host_application_stubs()

gipp_handler_module = import_module("rdmo_sensorsearch.handlers.gipp_instrument")
handler_base = import_module("rdmo_sensorsearch.handlers.base")
gipp_provider_module = import_module("rdmo_sensorsearch.providers.gipp_instrument")


def test_provider_formats_capability_search_records_and_returns_empty_on_failure():
    backend = SimpleNamespace(
        search_devices=lambda *args, **kwargs: BackendSuccess((SearchRecord("1", {"code": "BASE_X2-26115"}),))
    )
    provider = gipp_provider_module.GIPPInstrumentProvider(
        base_url="https://consumer.example", backend=backend, id_prefix="gfzgipp", text_prefix="GFZ GIPP Instrument", max_hits=10
    )
    assert provider.get_options(None, search="BASE_X2") == [{"id": "gfzgipp:1", "text": "GFZ GIPP Instrument(1): BASE_X2-26115"}]
    backend.search_devices = lambda *args, **kwargs: BackendFailure(("unavailable",))
    assert provider.get_options(None, search="BASE_X2") == []


def test_handler_maps_capability_metadata_and_propagates_failure():
    backend = SimpleNamespace(
        get_device=lambda *args, **kwargs: BackendSuccess(DeviceMetadata({"Instrument": {"code": "BASE_X2-26115"}}))
    )
    handler = gipp_handler_module.GIPPInstrumentHandler(
        base_url="https://consumer.example", backend=backend, id_prefix="gfzgipp", attribute_mapping={"Instrument.code": "uri"}
    )
    assert handler.handle("1", context=HandlerExecutionContext()).mapped_values == {"uri": "BASE_X2-26115"}
    backend.get_device = lambda *args, **kwargs: BackendFailure(("instrument unavailable",))
    assert handler.handle("1", context=HandlerExecutionContext()) == HandlerFailure(("instrument unavailable",))
