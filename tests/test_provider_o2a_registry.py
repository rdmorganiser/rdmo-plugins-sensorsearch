import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType


def _install_rdmo_provider_stub():
    rdmo = sys.modules.setdefault("rdmo", ModuleType("rdmo"))
    rdmo_options = sys.modules.setdefault("rdmo.options", ModuleType("rdmo.options"))
    rdmo_providers = sys.modules.setdefault("rdmo.options.providers", ModuleType("rdmo.options.providers"))
    rdmo_providers.Provider = getattr(rdmo_providers, "Provider", object)
    rdmo_options.providers = rdmo_providers
    rdmo.options = rdmo_options

    providers = sys.modules.setdefault("rdmo_sensorsearch.providers", ModuleType("rdmo_sensorsearch.providers"))
    providers.__path__ = [str(Path(__file__).parents[1] / "rdmo_sensorsearch" / "providers")]


_install_rdmo_provider_stub()
provider_o2a_registry = import_module("rdmo_sensorsearch.providers.provider_o2a_registry")


def test_o2a_registry_option_uses_item_id_in_display_name():
    provider = provider_o2a_registry.O2ARegistrySearchProvider()

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
