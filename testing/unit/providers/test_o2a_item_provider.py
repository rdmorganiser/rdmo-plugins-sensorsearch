"""Tests for the O2A Registry item provider."""

import sys
from importlib import import_module
from types import ModuleType

import pytest

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


def test_o2a_registry_option_uses_item_id_in_display_name():
    provider = o2a_item_provider_module.O2ARegistryItemProvider(
        id_prefix="o2aregistry",
        text_prefix="O2A Item",
        base_url="https://registry.o2a-data.de/index/rest/search/sensor-v2",
        max_hits=10,
    )

    option = provider.parse_option(
        {
            "uniqueId": 3581,
            "id": "station:svluwobs:fb_731101:hydrofia_0317-001",
            "title": "###HydroFIA Total Alkalinity analyzer",
            "metadata": {"serial": "TA-0317-001"},
        }
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
        provider_class(id_prefix="custom", text_prefix="Custom", base_url="https://registry.example/search")
    with pytest.raises(TypeError, match="unexpected keyword"):
        provider_class(
            id_prefix="custom", text_prefix="Custom", base_url="https://registry.example/search", max_hits=3, unused=True
        )
