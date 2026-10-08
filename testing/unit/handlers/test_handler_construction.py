from types import MappingProxyType

import pytest

from rdmo_sensorsearch.handlers.base import BackendRecordHandler
from rdmo_sensorsearch.handlers.o2a_item import O2ARegistryItemHandler
from rdmo_sensorsearch.handlers.o2a_mission import O2ARegistryMissionHandler


def test_handler_owns_a_mutable_copy_of_read_only_mapping_and_preserves_managed_uris():
    source = {"name": "attribute:name"}
    handler = BackendRecordHandler(
        base_url="https://consumer.example",
        id_prefix="custom",
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
        BackendRecordHandler(base_url="https://consumer.example", id_prefix="custom")
    with pytest.raises(TypeError, match="unexpected keyword"):
        BackendRecordHandler(base_url="https://consumer.example", id_prefix="custom", attribute_mapping={}, unused=True)


@pytest.mark.parametrize("handler_class", [O2ARegistryItemHandler, O2ARegistryMissionHandler])
def test_remote_handlers_receive_capabilities_without_connection_fields(handler_class):
    backend = object()
    handler = handler_class(base_url="https://consumer.example", backend=backend, id_prefix="custom", attribute_mapping={})
    assert handler.backend is backend
    assert handler.base_url == "https://consumer.example"
