from types import MappingProxyType

import pytest

from rdmo_sensorsearch.handlers.base import BackendRecordHandler
from rdmo_sensorsearch.handlers.o2a_item import O2ARegistryItemHandler
from rdmo_sensorsearch.handlers.o2a_mission import O2ARegistryMissionHandler


def test_handler_owns_a_mutable_copy_of_read_only_mapping_and_preserves_managed_uris():
    source = {"name": "attribute:name"}
    handler = BackendRecordHandler(
        id_prefix="custom",
        base_url="https://backend.example/api",
        attribute_mapping=MappingProxyType(source),
    )
    handler.managed_attribute_uris = ("attribute:other",)
    source["name"] = "attribute:changed"
    assert handler.attribute_mapping == {"name": "attribute:name"}
    handler.attribute_mapping["serial"] = "attribute:serial"
    assert handler.managed_attribute_uris == frozenset({"attribute:name", "attribute:serial", "attribute:other"})
    assert "serial" not in source


def test_handler_requires_a_mapping_even_with_connection_values():
    with pytest.raises(TypeError, match="attribute_mapping"):
        BackendRecordHandler(id_prefix="custom", base_url="https://backend.example/api")
    with pytest.raises(TypeError, match="unexpected keyword"):
        BackendRecordHandler(id_prefix="custom", base_url="https://backend.example/api", attribute_mapping={}, unused=True)


@pytest.mark.parametrize("handler_class", [O2ARegistryItemHandler, O2ARegistryMissionHandler])
def test_o2a_handlers_use_shared_origin_for_custom_api_paths(handler_class):
    handler = handler_class(id_prefix="custom", base_url="https://registry.example:8443/custom/rest/v2", attribute_mapping={})
    assert handler.base_url_origin == "https://registry.example:8443"
    handler.base_url = "https://other.example/different/api"
    assert handler.base_url_origin == "https://other.example"
