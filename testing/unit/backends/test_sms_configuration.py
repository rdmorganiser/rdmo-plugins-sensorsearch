from rdmo_sensorsearch.backends.sms.backend import SMSBackend
from rdmo_sensorsearch.backends.sms.settings import SMSConfigurationSettings
from rdmo_sensorsearch.contracts import BackendFailure, BackendSuccess, StaticLocation
from rdmo_sensorsearch.transport import TransportError
from testing.transport_helpers import raising_fetch


def test_configuration_returns_normalized_members_and_reuses_static_locations():
    requests = []
    mount = {
        "type": "device_mount_action",
        "id": "mount",
        "attributes": {"begin_date": "2025-01-01T00:00:00Z", "offset_z": -1},
        "relationships": {
            "device": {"data": {"type": "device", "id": "42"}},
            "parent_platform": {"data": None},
            "parent_device": {"data": None},
        },
    }
    static = {"id": "site", "attributes": {"begin_date": "2024-01-01T00:00:00Z", "label": "Plot", "z": 100, "y": 51, "x": 7}}

    def fetch(url, auth_token=None):
        requests.append((url, auth_token))
        if "/configurations/49" in url:
            return {"data": {"id": "49", "links": {"self": "/backend/api/v1/configurations/49"}}}
        if "/device-mount-actions?" in url:
            return {"data": [mount], "included": [{"type": "device", "id": "42", "attributes": {"long_name": "Sensor"}}]}
        if "/platform-mount-actions?" in url:
            return {"data": []}
        if "/static-location-actions?" in url:
            return {"data": [static]}
        raise AssertionError(url)

    backend = SMSBackend(
        fetch=raising_fetch(fetch), configuration_settings=SMSConfigurationSettings("https://sms.example/backend/api/v1")
    )
    configuration = backend.get_configuration("49", auth_token="token")
    assert isinstance(configuration, BackendSuccess)
    assert configuration.value.frontend_link == "https://sms.example/configurations/49"
    members = backend.get_configuration_members(configuration.value, auth_token="token")
    assert isinstance(members, BackendSuccess)
    assert members.value.static_location == StaticLocation(51, 7)
    (member,) = members.value.members
    assert member.identifier == "42" and member.attributes == {"long_name": "Sensor"}
    assert member.instrument_start == "2025-01-01 00:00"
    assert member.location.station_height_amsl == 100 and member.location.vertical_surface_offset == -1
    assert member.location.site_name == "Plot"
    assert len(requests) == 4 and all(token == "token" for _, token in requests)


def test_configuration_uses_requested_id_when_payload_has_no_id():
    requests = []

    def fetch(url, auth_token=None):
        requests.append(url)
        return {"data": {}} if "/configurations/49" in url else {"data": []}

    backend = SMSBackend(fetch=raising_fetch(fetch), configuration_settings=SMSConfigurationSettings("https://sms.example/api"))
    configuration = backend.get_configuration("49")
    assert isinstance(backend.get_configuration_members(configuration.value), BackendSuccess)
    assert all("filter[configuration_id]=49" in url for url in requests[1:])


def test_configuration_static_location_failure_retains_existing_message():
    backend = SMSBackend(
        fetch=raising_fetch(lambda *args, **kwargs: TransportError("Unavailable")),
        configuration_settings=SMSConfigurationSettings("https://sms.example/api"),
    )
    assert backend.get_static_location("49") == BackendFailure(
        ("SMS static location request for configuration 49 failed: Unavailable",)
    )
