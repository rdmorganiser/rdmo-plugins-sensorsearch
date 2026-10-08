from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from rdmo_sensorsearch.contracts import (
    AuthoritativeTextScalar,
    BackendFailure,
    BackendSuccess,
    ConfigurationMember,
    ConfigurationMembership,
    ConfigurationMetadata,
    ConfigurationPeriod,
    DeviceMetadata,
    HandlerExecutionContext,
    HandlerFailure,
    HandlerResult,
    MountLocation,
    MountPeriod,
    RefreshNotice,
    SelectedDevice,
    StaticLocation,
)
from rdmo_sensorsearch.handlers.sms_configuration import SensorManagementSystemConfigurationHandler
from rdmo_sensorsearch.handlers.sms_device import SensorManagementSystemDeviceHandler
from rdmo_sensorsearch.handlers.sms_device_enrichment import SMSDeviceMetadataEnricher
from rdmo_sensorsearch.services.device_detail_profile import DEFAULT_DEVICE_DETAIL_SETTINGS
from rdmo_sensorsearch.services.device_details import DeviceBlockPlan


def test_device_handler_maps_injected_metadata_and_binds_notices_without_http():
    calls = []

    def get_device(identifier, *, auth_token):
        calls.append((identifier, auth_token))
        return BackendSuccess(
            DeviceMetadata(
                {"data": {"attributes": {"long_name": "Sensor"}}, "sms_owner_organizations": ["Institute"]},
                ("Institute",),
                "https://sms.example/devices/1",
            ),
            (RefreshNotice("owner_contact_unresolved"),),
        )

    handler = SensorManagementSystemDeviceHandler(
        backend=SimpleNamespace(get_device=get_device),
        id_prefix="dev",
        attribute_mapping={"data.attributes.long_name": "name", "sms_owner_organizations": "owner"},
    )
    result = handler.handle("1", context=HandlerExecutionContext(), auth_token="token")
    assert calls == [("1", "token")]
    assert result.mapped_values["name"] == "Sensor" and result.mapped_values["owner"] == AuthoritativeTextScalar(("Institute",))
    assert result.notices == (RefreshNotice("owner_contact_unresolved", "dev:1"),)


@pytest.mark.parametrize("preserve", [True, False])
def test_configuration_handler_keeps_mapping_and_effects_with_injected_membership(preserve):
    calls = []
    period = ConfigurationPeriod(datetime(2025, 1, 1, tzinfo=timezone.utc))
    member = ConfigurationMember("1", {"long_name": "Sensor"}, "2025-01-01 00:00", None, MountLocation(100, -1, "Plot"))
    metadata = ConfigurationMetadata(
        {"data": {"id": "2", "attributes": {"label": "Configuration"}}}, frontend_link="https://sms.example/configurations/2"
    )

    def get_configuration(identifier, *, auth_token):
        calls.append(("configuration", identifier, auth_token))
        return BackendSuccess(metadata)

    def get_members(configuration, *, period, require_configuration_period, auth_token):
        assert require_configuration_period
        calls.append(("members", configuration, period, auth_token))
        return BackendSuccess(ConfigurationMembership((member,), StaticLocation(51, 7)))

    handler = SensorManagementSystemConfigurationHandler(
        backend=SimpleNamespace(get_configuration=get_configuration, get_configuration_members=get_members),
        id_prefix="cfg",
        attribute_mapping={"data.attributes.label": "label"},
    )
    handler.device_id_prefix = "dev"
    handler.selected_devices_attribute_uri = "selected"
    handler.selected_devices_page_uri = "page"
    handler.device_collection_attribute_uri = "root"
    handler.frontend_link_attribute_uri = "link"
    handler.membership_filter_enabled = True
    handler.membership_filter_start_attribute_uri = "start"
    handler.membership_filter_end_attribute_uri = "end"
    result = handler.handle(
        "2",
        context=HandlerExecutionContext(
            preserve_existing_collections=preserve, require_configuration_period=True, configuration_period=period
        ),
        auth_token="token",
    )
    assert isinstance(result, HandlerResult)
    assert result.mapped_values == {"label": "Configuration", "link": "https://sms.example/configurations/2"}
    assert calls[0] == ("configuration", "2", "token")
    if preserve:
        assert len(calls) == 1 and result.collections == result.effects == ()
    else:
        assert calls[1] == ("members", metadata, period, "token")
        (selected,) = result.effects[0].selected_devices
        assert selected.external_id == "dev:1" and selected.site_name == "Plot" and selected.mount_location_resolved


def test_membership_failure_returns_typed_failure_without_effects():
    backend = SimpleNamespace(
        get_configuration=lambda *args, **kwargs: BackendSuccess(ConfigurationMetadata({"data": {"id": "2"}})),
        get_configuration_members=lambda *args, **kwargs: BackendFailure(("Unavailable",)),
    )
    handler = SensorManagementSystemConfigurationHandler(
        backend=backend,
        attribute_mapping={},
        id_prefix="cfg",
    )
    handler.selected_devices_attribute_uri = "selected"
    assert handler.handle("2", context=HandlerExecutionContext()) == HandlerFailure(("Unavailable",))


@pytest.mark.parametrize("operation", ("get_device", "get_mount_period", "get_mount_location"))
def test_device_handler_propagates_capability_failures(operation):
    backend = SimpleNamespace(
        get_device=lambda *args, **kwargs: BackendSuccess(DeviceMetadata({"name": "Sensor"})),
        get_mount_period=lambda *args, **kwargs: BackendSuccess(MountPeriod("2025-01-01", None, {})),
    )
    errors = ("Unavailable", "Try later")
    setattr(backend, operation, lambda *args, **kwargs: BackendFailure(errors))
    handler = SensorManagementSystemDeviceHandler(backend=backend, id_prefix="dev", attribute_mapping={"name": "name"})

    result = handler.handle("1", context=HandlerExecutionContext(configuration_external_id="cfg:2"))

    assert result == HandlerFailure(errors)


@pytest.mark.parametrize("operation", ("get_configuration", "get_static_location"))
def test_configuration_handler_propagates_capability_failures(operation):
    backend = SimpleNamespace(
        get_configuration=lambda *args, **kwargs: BackendSuccess(ConfigurationMetadata({"name": "Configuration"})),
    )
    errors = ("Unavailable", "Try later")
    setattr(backend, operation, lambda *args, **kwargs: BackendFailure(errors))
    handler = SensorManagementSystemConfigurationHandler(backend=backend, id_prefix="cfg", attribute_mapping={"name": "name"})
    handler.latitude_attribute_uri = "latitude"

    assert handler.handle("2", context=HandlerExecutionContext()) == HandlerFailure(errors)


def test_membership_filter_requires_configured_input_uris():
    handler = SensorManagementSystemConfigurationHandler(
        backend=SimpleNamespace(get_configuration=lambda *args, **kwargs: BackendSuccess(ConfigurationMetadata({}))),
        id_prefix="cfg",
        attribute_mapping={},
    )
    handler.membership_filter_enabled = True

    result = handler.handle("2", context=HandlerExecutionContext(require_configuration_period=True))

    assert result == HandlerFailure(("The SMS membership filter inputs are not configured for this catalog.",))


def test_bulk_enricher_uses_custom_profile_and_logs_partial_capability_failures(caplog):
    calls = []

    def get_period(device_id, configuration_id, *, serial_number, auth_token):
        calls.append(("period", device_id, configuration_id, serial_number, auth_token))
        return BackendFailure(("Period unavailable",))

    def get_location(device_id, configuration_id, *, best_effort, auth_token):
        calls.append(("location", device_id, configuration_id, best_effort, auth_token))
        return BackendSuccess(MountLocation(100, -1, "Plot"), diagnostics=("Partial lookup unavailable",))

    handler = SimpleNamespace(
        backend=SimpleNamespace(get_mount_period=get_period, get_mount_location=get_location),
        supports_mount_period_lookup=True,
        supports_mount_location_lookup=True,
    )
    device = SelectedDevice("Sensor (s/n: ABC)", "dev:1")
    plan = DeviceBlockPlan(
        device, "cfg:2||dev:1", 0, SimpleNamespace(handler=handler), True, True, configuration_external_id="cfg:2"
    )
    settings = replace(DEFAULT_DEVICE_DETAIL_SETTINGS, site_name_attribute_uri="custom:site")
    mapped_values = {}
    SMSDeviceMetadataEnricher("cfg:2", auth_token="token", detail_settings=settings)(mapped_values, plan)
    assert calls == [("period", "1", "2", "ABC", "token"), ("location", "1", "2", True, "token")]
    assert mapped_values[settings.instrument_start_attribute_uri] == ""
    assert mapped_values["custom:site"] == "Plot"
    assert "Period unavailable" in caplog.text and "Partial lookup unavailable" in caplog.text
