import sys
from types import ModuleType, SimpleNamespace

django = sys.modules.setdefault("django", ModuleType("django"))
django_conf = sys.modules.setdefault("django.conf", ModuleType("django.conf"))
django_conf.settings = getattr(django_conf, "settings", SimpleNamespace())
django.conf = django_conf
rdmo = sys.modules.setdefault("rdmo", ModuleType("rdmo"))
rdmo.__version__ = getattr(rdmo, "__version__", "test")

from rdmo_sensorsearch.handlers import sms_device_enrichment as enrichment_module  # noqa: E402
from rdmo_sensorsearch.handlers.sms_device_enrichment import (  # noqa: E402
    INSTRUMENT_END_ATTRIBUTE_URI,
    INSTRUMENT_LOCATION_AMSL_ATTRIBUTE_URI,
    INSTRUMENT_START_ATTRIBUTE_URI,
    SERIAL_NUMBER_ATTRIBUTE_URI,
    SITE_NAME_ATTRIBUTE_URI,
    SURFACE_OFFSET_Z_ATTRIBUTE_URI,
    SMSDeviceMetadataEnricher,
)
from rdmo_sensorsearch.services.device_details import DeviceBlockPlan, SelectedDevice  # noqa: E402


def _plan(device: SelectedDevice, handler, configuration_external_id="sms-configuration:27"):
    return DeviceBlockPlan(
        device=device,
        block_key=f"{configuration_external_id}||{device.external_id}",
        set_index=0,
        handler_binding=SimpleNamespace(handler=handler),
        needs_metadata_write=True,
        needs_refresh=True,
        configuration_external_id=configuration_external_id,
    )


def _handler(*, period=True, location=True):
    return SimpleNamespace(
        base_url="https://sms.example/api/v1",
        supports_mount_period_lookup=period,
        supports_mount_location_lookup=location,
    )


def _device_action(
    *,
    action_id="mount-1",
    begin_date="2025-01-02T10:00:00Z",
    end_date=None,
    serial_number="ABC-123",
    offset_z=-2,
):
    return {
        "type": "device_mount_action",
        "id": action_id,
        "attributes": {
            "begin_date": begin_date,
            "end_date": end_date,
            "serial_number": serial_number,
            "offset_z": offset_z,
            "z": None,
        },
        "relationships": {
            "configuration": {"data": {"type": "configuration", "id": "27"}},
            "device": {"data": {"type": "device", "id": "607"}},
            "parent_device": {"data": None},
            "parent_platform": {"data": None},
        },
    }


def test_selected_device_metadata_takes_precedence_without_sms_requests(monkeypatch):
    monkeypatch.setattr(
        enrichment_module,
        "fetch_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("SMS request was not expected")),
    )
    device = SelectedDevice(
        text="Device 607",
        external_id="sms-device:607",
        instrument_start="2025-04-01 08:00",
        instrument_end="2025-04-02 18:00",
        station_height_amsl=98.5,
        vertical_surface_offset=-1.5,
        site_name="Field plot",
        mount_location_resolved=True,
    )
    mapped_values = {}

    SMSDeviceMetadataEnricher(configuration_external_id="sms-configuration:27")(
        mapped_values,
        _plan(device, _handler()),
    )

    assert mapped_values[INSTRUMENT_START_ATTRIBUTE_URI] == "2025-04-01 08:00"
    assert mapped_values[INSTRUMENT_END_ATTRIBUTE_URI] == "2025-04-02 18:00"
    assert mapped_values[INSTRUMENT_LOCATION_AMSL_ATTRIBUTE_URI] == 98.5
    assert mapped_values[SURFACE_OFFSET_Z_ATTRIBUTE_URI] == -1.5
    assert mapped_values[SITE_NAME_ATTRIBUTE_URI] == "Field plot"


def test_existing_mapped_start_is_not_replaced(monkeypatch):
    monkeypatch.setattr(
        enrichment_module,
        "fetch_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("SMS request was not expected")),
    )
    device = SelectedDevice(
        text="Device 607",
        external_id="sms-device:607",
        mount_location_resolved=True,
    )
    mapped_values = {INSTRUMENT_START_ATTRIBUTE_URI: "2024-03-01 12:00"}

    SMSDeviceMetadataEnricher(configuration_external_id="sms-configuration:27")(
        mapped_values,
        _plan(device, _handler()),
    )

    assert mapped_values[INSTRUMENT_START_ATTRIBUTE_URI] == "2024-03-01 12:00"
    assert mapped_values[INSTRUMENT_END_ATTRIBUTE_URI] == ""


def test_sms_mount_period_and_location_are_resolved_from_action_endpoints(monkeypatch):
    requested_urls = []
    device_action = _device_action(end_date="2025-01-03T11:30:00Z")

    def fetch_json(url, auth_token=None):
        requested_urls.append((url, auth_token))
        if "/devices/607/device-mount-actions" in url:
            return {"data": [device_action]}
        if "/device-mount-actions?" in url:
            return {"data": [device_action]}
        if "/platform-mount-actions?" in url:
            return {"data": []}
        if "/static-location-actions?" in url:
            return {
                "data": [
                    {
                        "type": "configuration_static_location_action",
                        "id": "site-1",
                        "attributes": {
                            "begin_date": "2020-01-01T00:00:00Z",
                            "end_date": None,
                            "z": 100,
                            "label": "Test site",
                        },
                    }
                ]
            }
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(enrichment_module, "fetch_json", fetch_json)
    mapped_values = {SERIAL_NUMBER_ATTRIBUTE_URI: " abc-123 "}
    plan = _plan(
        SelectedDevice(text="Device 607", external_id="sms-device:607"),
        _handler(),
    )

    SMSDeviceMetadataEnricher(
        configuration_external_id="unused:99",
        auth_token="secret-token",
    )(mapped_values, plan)

    assert mapped_values[INSTRUMENT_START_ATTRIBUTE_URI] == "2025-01-02 10:00"
    assert mapped_values[INSTRUMENT_END_ATTRIBUTE_URI] == "2025-01-03 11:30"
    assert mapped_values[INSTRUMENT_LOCATION_AMSL_ATTRIBUTE_URI] == 100
    assert mapped_values[SURFACE_OFFSET_Z_ATTRIBUTE_URI] == -2
    assert mapped_values[SITE_NAME_ATTRIBUTE_URI] == "Test site"
    assert len(requested_urls) == 4
    assert all(auth_token == "secret-token" for _, auth_token in requested_urls)


def test_unsupported_handler_produces_empty_enrichment_without_requests(monkeypatch):
    monkeypatch.setattr(
        enrichment_module,
        "fetch_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("SMS request was not expected")),
    )
    mapped_values = {}

    SMSDeviceMetadataEnricher(configuration_external_id="sms-configuration:27")(
        mapped_values,
        _plan(
            SelectedDevice(text="Device 607", external_id="other-device:607"),
            _handler(period=False, location=False),
        ),
    )

    assert mapped_values[INSTRUMENT_START_ATTRIBUTE_URI] == ""
    assert mapped_values[INSTRUMENT_END_ATTRIBUTE_URI] == ""
    assert mapped_values[INSTRUMENT_LOCATION_AMSL_ATTRIBUTE_URI] == ""
    assert mapped_values[SURFACE_OFFSET_Z_ATTRIBUTE_URI] == ""
    assert mapped_values[SITE_NAME_ATTRIBUTE_URI] == ""


def test_sms_endpoint_errors_degrade_to_empty_mount_metadata(monkeypatch):
    monkeypatch.setattr(
        enrichment_module,
        "fetch_json",
        lambda url, auth_token=None: {"errors": ["backend unavailable"]},
    )
    mapped_values = {}

    SMSDeviceMetadataEnricher(configuration_external_id="sms-configuration:27")(
        mapped_values,
        _plan(
            SelectedDevice(text="Device 607 (s/n: ABC-123)", external_id="sms-device:607"),
            _handler(),
        ),
    )

    assert mapped_values[INSTRUMENT_START_ATTRIBUTE_URI] == ""
    assert mapped_values[INSTRUMENT_END_ATTRIBUTE_URI] == ""
    assert mapped_values[INSTRUMENT_LOCATION_AMSL_ATTRIBUTE_URI] == ""
    assert mapped_values[SURFACE_OFFSET_Z_ATTRIBUTE_URI] == ""
    assert mapped_values[SITE_NAME_ATTRIBUTE_URI] == ""
