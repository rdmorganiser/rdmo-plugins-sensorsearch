"""Tests for the O2A Registry item provider."""

import sys
from importlib import import_module
from types import ModuleType, SimpleNamespace

import pytest

from rdmo_sensorsearch.contracts import BackendFailure, BackendSuccess, SearchRecord
from testing.paths import REPOSITORY_ROOT


def _install_rdmo_provider_stub():
    rdmo = sys.modules.setdefault("rdmo", ModuleType("rdmo"))
    rdmo_options = sys.modules.setdefault("rdmo.options", ModuleType("rdmo.options"))
    rdmo_providers = sys.modules.setdefault("rdmo.options.providers", ModuleType("rdmo.options.providers"))
    rdmo_providers.Provider = getattr(rdmo_providers, "Provider", object)
    rdmo_options.providers = rdmo_providers
    rdmo.options = rdmo_options

    providers = sys.modules.setdefault("rdmo_sensorsearch.providers", ModuleType("rdmo_sensorsearch.providers"))
    providers.__path__ = [str(REPOSITORY_ROOT / "rdmo_sensorsearch" / "providers")]


_install_rdmo_provider_stub()
o2a_item_provider_module = import_module("rdmo_sensorsearch.providers.o2a_item")
o2a_mission_provider_module = import_module("rdmo_sensorsearch.providers.o2a_mission")


@pytest.mark.parametrize(
    "provider_class,capability,attributes,expected_text",
    [
        (
            o2a_item_provider_module.O2ARegistryItemProvider,
            "search_devices",
            {"title": "Sensor", "registry_id": "station:sensor", "serial": "ABC"},
            "Custom(42): Sensor (s/n: ABC, id: station:sensor)",
        ),
        (
            o2a_mission_provider_module.O2ARegistryMissionProvider,
            "search_configurations",
            {"name": "Mission", "description": "Survey", "start_date": "2026-01-01"},
            "Custom(42): Mission | Survey | 2026-01-01 | ",
        ),
    ],
)
@pytest.mark.parametrize("failure", [False, True])
def test_o2a_providers_use_search_capabilities_and_preserve_presentation(
    provider_class, capability, attributes, expected_text, failure
):
    calls = []

    def search(query, *, limit, auth_token=None):
        calls.append((query, limit, auth_token))
        return BackendFailure(("unavailable",)) if failure else BackendSuccess((SearchRecord("42", attributes),))

    provider = provider_class(
        backend=SimpleNamespace(**{capability: search}), id_prefix="custom", text_prefix="Custom", max_hits=3
    )
    if capability == "search_configurations":
        provider.option_text = "{prefix}({id}): {name} | {description} | {start_date} | {unknown}"
    provider.auth_token = "request-token"
    assert provider.get_options(None) == []
    options = provider.get_options(None, search="input")
    assert calls == [("input", 3, "request-token")]
    assert options == ([] if failure else [{"id": "custom:42", "text": expected_text}])


def test_o2a_registry_option_uses_item_id_in_display_name():
    provider = o2a_item_provider_module.O2ARegistryItemProvider(
        backend=SimpleNamespace(),
        id_prefix="o2aregistry",
        text_prefix="O2A Item",
        max_hits=10,
    )

    option = provider.parse_option(
        SearchRecord(
            "3581",
            {
                "title": "###HydroFIA Total Alkalinity analyzer",
                "serial": "TA-0317-001",
                "registry_id": "station:svluwobs:fb_731101:hydrofia_0317-001",
            },
        )
    )

    assert option == {
        "id": "o2aregistry:3581",
        "text": (
            "O2A Item(3581): ###HydroFIA Total Alkalinity analyzer "
            "(s/n: TA-0317-001, id: station:svluwobs:fb_731101:hydrofia_0317-001)"
        ),
    }


def test_remote_provider_requires_all_configuration_and_rejects_arbitrary_keywords():
    provider_class = o2a_item_provider_module.O2ARegistryItemProvider
    with pytest.raises(TypeError, match="required keyword-only"):
        provider_class()
    with pytest.raises(TypeError, match="max_hits"):
        provider_class(backend=SimpleNamespace(), id_prefix="custom", text_prefix="Custom")
    with pytest.raises(TypeError, match="unexpected keyword"):
        provider_class(backend=SimpleNamespace(), id_prefix="custom", text_prefix="Custom", max_hits=3, unused=True)
