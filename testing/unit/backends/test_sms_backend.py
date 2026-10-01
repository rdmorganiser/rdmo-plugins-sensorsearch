from dataclasses import FrozenInstanceError

import pytest

from rdmo_sensorsearch.backends.sms.backend import SMSBackend
from rdmo_sensorsearch.backends.sms.settings import SMSDeviceSettings, SMSSearchSettings
from rdmo_sensorsearch.contracts import BackendFailure, BackendSuccess, SearchRecord


@pytest.mark.parametrize("method,resource", [("search_devices", "devices"), ("search_configurations", "configurations")])
def test_search_uses_resource_url_query_limit_and_per_call_auth(method, resource):
    requests = []
    payload = {"data": [{"id": str(i), "attributes": {"label": "Sensor"}} for i in range(3)]}

    def fetch(url, auth_token=None):
        requests.append((url, auth_token))
        return payload

    backend = SMSBackend(
        fetch=fetch,
        search_settings=SMSSearchSettings(
            f"https://sms.example/api/{resource}",
            "{base_url}?q={query}&size={page_size}",
        ),
    )
    first = getattr(backend, method)("a & b", limit=2, auth_token="first")
    assert first == BackendSuccess(tuple(SearchRecord(str(i), {"label": "Sensor"}) for i in range(2)))
    first.value[0].attributes["label"] = "Changed"
    second = getattr(backend, method)("a & b", limit=2, auth_token="second")
    assert second.value[0].attributes == {"label": "Sensor"}
    assert requests == [(f"https://sms.example/api/{resource}?q=a%20%26%20b&size=2", token) for token in ("first", "second")]


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"data": []}, BackendSuccess(())),
        ({"errors": ["Unavailable"]}, BackendFailure(("Unavailable",))),
        ([], BackendFailure(("Unexpected SMS search payload.",))),
        ({"data": [{"id": "1"}]}, BackendFailure(("Malformed SMS search data.",))),
    ],
)
def test_search_failure_is_distinct_from_empty_success(payload, expected):
    backend = SMSBackend(
        fetch=lambda *args, **kwargs: payload, search_settings=SMSSearchSettings("https://sms.example/devices", "{base_url}")
    )
    assert backend.search_devices("test", limit=10) == expected


def test_device_normalization_does_not_mutate_transport_documents():
    document = {"data": {"id": "1", "links": {"self": "/backend/api/v1/devices/1"}}, "included": []}
    contacts = {"data": [], "included": []}
    backend = SMSBackend(
        fetch=lambda url, **kwargs: contacts if "contact" in url else document,
        device_settings=SMSDeviceSettings("https://sms.example/backend/api/v1"),
    )
    first = backend.get_device("1")
    assert isinstance(first, BackendSuccess)
    assert first.value.frontend_link == "https://sms.example/devices/1"
    first.value.document["included"].append({"id": "Changed"})
    assert backend.get_device("1").value.document["included"] == []
    assert "sms_owner_organizations" not in document
    with pytest.raises(FrozenInstanceError):
        first.value.frontend_link = "Changed"


def test_mount_failure_is_typed_and_empty_mount_is_successful():
    backend = SMSBackend(
        fetch=lambda *args, **kwargs: {"errors": ["Unavailable"]}, device_settings=SMSDeviceSettings("https://sms.example/api")
    )
    assert backend.get_mount_period("1", "2") == BackendFailure(("SMS mount action request for device 1 failed: Unavailable",))
    backend = SMSBackend(fetch=lambda *args, **kwargs: {"data": []}, device_settings=SMSDeviceSettings("https://sms.example/api"))
    assert backend.get_mount_period("1", "2") == BackendSuccess(None)
