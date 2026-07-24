import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType, SimpleNamespace


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
    sensorsearch_providers.__path__ = [str(Path(__file__).parents[1] / "rdmo_sensorsearch" / "providers")]

    sys.modules.setdefault("django", django)
    sys.modules.setdefault("django.conf", django_conf)
    sys.modules.setdefault("rdmo", rdmo)
    sys.modules.setdefault("rdmo.options", rdmo_options)
    sys.modules.setdefault("rdmo.options.providers", rdmo_providers)
    sys.modules.setdefault("rdmo_sensorsearch.providers", sensorsearch_providers)


_install_host_application_stubs()

handler_gfz_gipp = import_module("rdmo_sensorsearch.handlers.handler_gfz_gipp")
provider_gfz_gipp = import_module("rdmo_sensorsearch.providers.provider_gfz_gipp")


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

    monkeypatch.setattr(provider_gfz_gipp, "fetch_json", fetch_json)

    options = provider_gfz_gipp.GeophysicalInstrumentPoolPotsdamProvider().get_options(
        project=None,
        search="BASE_X2",
    )

    assert requested_urls == ["https://gipp.gfz.de/instruments/index.json?limit=10000&program=MOSES"]
    assert options == [{"id": "gfzgipp:1", "text": "GIPP: BASE_X2-26115"}]


def test_handler_uses_current_gipp_hostname(monkeypatch):
    requested_urls = []

    def fetch_json(url):
        requested_urls.append(url)
        return {}

    monkeypatch.setattr(handler_gfz_gipp, "fetch_json", fetch_json)

    handler = handler_gfz_gipp.GeophysicalInstrumentPoolPotsdamHandler(attribute_mapping={"Instrument.code": "uri"})
    handler.handle("1")

    assert requested_urls == ["https://gipp.gfz.de/instruments/rest/1.json"]


def test_handler_propagates_backend_errors(monkeypatch):
    monkeypatch.setattr(
        handler_gfz_gipp,
        "fetch_json",
        lambda url: {"errors": ["instrument unavailable"]},
    )
    handler = handler_gfz_gipp.GeophysicalInstrumentPoolPotsdamHandler(attribute_mapping={"Instrument.code": "uri"})

    result = handler.handle("1")

    assert result == {"errors": ["instrument unavailable"]}
