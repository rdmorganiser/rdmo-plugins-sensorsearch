from types import SimpleNamespace

from rdmo_sensorsearch.contracts import (
    BackendFailure,
    BackendSuccess,
    ConfigurationMember,
    ConfigurationMembership,
    ConfigurationMetadata,
    DeviceMetadata,
    HandlerExecutionContext,
    HandlerFailure,
    MountLocation,
)
from rdmo_sensorsearch.handlers.o2a_item import O2ARegistryItemHandler
from rdmo_sensorsearch.handlers.o2a_mission import O2ARegistryMissionHandler


def test_item_handler_maps_capability_metadata_and_propagates_failure():
    backend = SimpleNamespace(
        get_device=lambda *args, **kwargs: BackendSuccess(
            DeviceMetadata({"name": "Sensor", "parameters": [{"unit": "K"}]}, frontend_link="https://registry.example/items/42")
        )
    )
    handler = O2ARegistryItemHandler(
        base_url="https://consumer.example",
        backend=backend,
        id_prefix="o2a",
        attribute_mapping={"name": "name", "parameters[].unit": "units"},
    )
    handler.device_link_attribute_uri = "link"
    result = handler.handle("42", context=HandlerExecutionContext())
    assert result.mapped_values == {"name": "Sensor", "units": ["K"], "link": "https://registry.example/items/42"}
    backend.get_device = lambda *args, **kwargs: BackendFailure(("Unavailable",))
    assert handler.handle("42", context=HandlerExecutionContext()) == HandlerFailure(("Unavailable",))


def test_mission_handler_keeps_custom_dates_labels_and_effects():
    calls = []
    metadata = ConfigurationMetadata(
        {"name": "Mission", "begin": "2026-01-01T12:00:00+02:00", "finish": None},
        frontend_link="https://registry.example/missions/30",
        identifier="30",
    )
    member = ConfigurationMember(
        "42",
        {"item_id": 42, "name": "CTD", "serial_number": "ABC", "mission_item_uuid": "uuid"},
        "unformatted",
        None,
        MountLocation(),
    )

    def members(configuration, **kwargs):
        calls.append(kwargs)
        return BackendSuccess(ConfigurationMembership((member,)))

    handler = O2ARegistryMissionHandler(
        base_url="https://consumer.example",
        backend=SimpleNamespace(
            get_configuration=lambda *args, **kwargs: BackendSuccess(metadata), get_configuration_members=members
        ),
        id_prefix="o2amission",
        attribute_mapping={"begin": "start", "finish": "end"},
    )
    handler.mission_start_date_path = "begin"
    handler.mission_end_date_path = "finish"
    handler.date_mapping_paths = ("begin", "finish")
    handler.datetime_output_format = "%Y/%m/%d %H:%M"
    handler.item_id_prefix = "o2aregistry"
    handler.item_text_template = "{configuration} {mission_name} {mission_item_uuid} {name}{serial}"
    handler.selected_devices_attribute_uri = "selected"
    handler.selected_devices_page_uri = "page"
    handler.device_collection_attribute_uri = "root"
    handler.frontend_link_attribute_uri = "link"

    result = handler.handle("30", context=HandlerExecutionContext(), auth_token="token")
    assert result.mapped_values == {"start": "2026/01/01 10:00", "end": None, "link": metadata.frontend_link}
    selected = result.effects[0].selected_devices[0]
    assert selected.instrument_start == "2026/01/01 10:00" and selected.external_id == "o2aregistry:42"
    assert selected.text == "O2A M(30) Mission uuid CTD (s/n: ABC)"
    assert calls == [{"period": None, "require_configuration_period": False, "auth_token": "token"}]
    preserved = handler.handle("30", context=HandlerExecutionContext(preserve_existing_collections=True))
    assert preserved.collections == preserved.effects == () and len(calls) == 1
    assert handler.get_member_device_period(preserved.mapped_values) == ("2026/01/01 10:00", None)
