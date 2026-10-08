"""Tests for the GIPP instrument backend integration."""

import sys
from importlib import import_module
from types import ModuleType, SimpleNamespace

from rdmo_sensorsearch.contracts import HandlerExecutionContext, HandlerFailure
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


def test_provider_uses_current_gipp_hostname(monkeypatch):
    requested_urls = []
    instruments = [
        {
            "Instrument": {
                "id": 1,
                "code": "BASE_X2-26115",
                "program": "MOSES",
            }
        }
    ]

    def fetch_json(url):
        requested_urls.append(url)
        return instruments

    monkeypatch.setattr(gipp_provider_module, "fetch_json", fetch_json)

    options = gipp_provider_module.GIPPInstrumentProvider(
        id_prefix="gfzgipp",
        text_prefix="GFZ GIPP Instrument",
        base_url="https://gipp.gfz.de/instruments",
        max_hits=10,
    ).get_options(
        project=None,
        search="BASE_X2",
    )

    assert requested_urls == ["https://gipp.gfz.de/instruments/index.json?limit=10000&program=MOSES"]
    assert options == [
        {
            "id": "gfzgipp:1",
            "text": "GFZ GIPP Instrument(1): BASE_X2-26115",
        }
    ]


def test_handler_uses_current_gipp_hostname(monkeypatch):
    requested_urls = []

    def fetch_json(url):
        requested_urls.append(url)
        return {"Instrument": {"code": "BASE_X2-26115"}}

    monkeypatch.setattr(gipp_handler_module, "fetch_json", fetch_json)

    handler = gipp_handler_module.GIPPInstrumentHandler(
        attribute_mapping={"Instrument.code": "uri"},
        id_prefix="gfzgipp",
        base_url="https://gipp.gfz.de/instruments/rest",
    )
    result = handler.handle("1", context=HandlerExecutionContext())

    assert requested_urls == ["https://gipp.gfz.de/instruments/rest/1.json"]
    assert isinstance(result, import_module("rdmo_sensorsearch.contracts").HandlerResult)


def test_handler_propagates_backend_errors(monkeypatch):
    monkeypatch.setattr(
        gipp_handler_module,
        "fetch_json",
        lambda url: {"errors": ["instrument unavailable"]},
    )
    handler = gipp_handler_module.GIPPInstrumentHandler(
        attribute_mapping={"Instrument.code": "uri"},
        id_prefix="gfzgipp",
        base_url="https://gipp.gfz.de/instruments/rest",
    )

    result = handler.handle("1", context=HandlerExecutionContext())

    assert result == HandlerFailure(("instrument unavailable",))
