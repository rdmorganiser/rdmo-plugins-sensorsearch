from dataclasses import replace
from datetime import datetime, timezone

import pytest

from rdmo_sensorsearch.backends.o2a.backend import O2ABackend
from rdmo_sensorsearch.config_models.backend_settings import O2ABackendSettings, O2AMissionQuerySettings
from rdmo_sensorsearch.contracts import BackendFailure, BackendSuccess, ConfigurationMetadata, ConfigurationPeriod
from testing.transport_helpers import raising_fetch


@pytest.mark.parametrize("identifier", [["unit"], {"id": "unit"}])
def test_malformed_unit_identity_returns_backend_failure(identifier):
    def fetch(url, auth_token=None):
        if url.endswith("/units"):
            return {"records": [{"@uuid": identifier, "code": "K"}]}
        if url.endswith("/items/42"):
            return {"longName": "Sensor"}
        return {"records": []}

    backend = O2ABackend(base_url="https://registry.example", settings=O2ABackendSettings(), fetch=fetch)
    assert backend.get_device("42") == BackendFailure(("Malformed O2A unit identifier for item 42.",))


def test_item_enrichment_preserves_document_links_and_transport_ownership():
    settings = O2ABackendSettings()
    data = {"longName": "Sensor", "type": {"generalName": "Probe"}}
    payloads = {
        "https://registry.example/rest/v2/items/42": data,
        "https://registry.example/rest/v2/items/42/contacts": {
            "records": [
                {"contact": {"firstName": "Ada", "lastName": "Lovelace", "email": "ada@example.org", "unused": True}},
                {"contact": "reference"},
            ]
        },
        "https://registry.example/rest/v2/items/42/parameters": {
            "records": [
                {"name": "temperature", "unit": "kelvin"},
                {"name": "pressure", "unit": {"code": "Pa"}},
            ]
        },
        "https://registry.example/rest/v2/units": {"records": [{"@uuid": "kelvin", "code": "K"}]},
    }
    calls = []

    def fetch(url, auth_token=None):
        calls.append((url, auth_token))
        return payloads[url]

    backend = O2ABackend(base_url="https://registry.example", settings=settings, fetch=raising_fetch(fetch))
    result = backend.get_device("42", auth_token="sms-secret")

    assert isinstance(result, BackendSuccess)
    assert result.value.document["contacts"] == [{"firstName": "Ada", "lastName": "Lovelace", "email": "ada@example.org"}]
    assert result.value.document["parameters"] == [{"name": "temperature", "unit": "K"}, {"name": "pressure", "unit": "Pa"}]
    assert result.value.frontend_link == "https://registry.example/items/42"
    assert result.value.document["links"]["api"] == "https://registry.example/rest/v2/items/42"
    assert all(token is None for _, token in calls)
    assert data == {"longName": "Sensor", "type": {"generalName": "Probe"}}


def test_search_preserves_item_identity_and_mission_query_settings():
    calls = []

    def fetch(url, auth_token=None):
        calls.append((url, auth_token))
        if "sensor-v2" in url:
            return {"records": [{"uniqueId": 42, "id": "station:sensor", "title": "Sensor", "metadata": {"serial": "ABC"}}]}
        return {"records": [{"id": 30, "name": "Mission", "startDate": "2026-01-01", "@uuid": "uuid"}]}

    backend = O2ABackend(
        base_url="https://registry.example",
        settings=O2ABackendSettings(),
        fetch=raising_fetch(fetch),
        mission_query_settings=O2AMissionQuerySettings(
            where_template='description=ILIKE="*{query}*"', sorts="name desc", offset=2
        ),
    )
    item = backend.search_devices("Sen!sor", limit=3, auth_token="secret").value[0]
    mission = backend.search_configurations('M"\\', limit=3, auth_token="secret").value[0]

    assert item.identifier == "42" and item.attributes == {"title": "Sensor", "serial": "ABC", "registry_id": "station:sensor"}
    assert mission.identifier == "30" and mission.attributes["start_date"] == "2026-01-01"
    assert "Sensor" in calls[0][0] and "Sen%21sor" not in calls[0][0]
    assert "description=ILIKE=" in calls[1][0] and "sorts=name%20desc&offset=2&hits=3" in calls[1][0]
    assert all(token is None for _, token in calls)


def test_mission_membership_fetches_basic_items_and_preserves_template_attributes():
    settings = O2ABackendSettings(mission=replace(O2ABackendSettings().mission, mission_item_page_size=1))
    calls = []

    def fetch(url, auth_token=None):
        calls.append(url)
        if "offset=0" in url:
            return {"records": [{"id": "member", "@uuid": "member-uuid", "itemId": 42}]}
        if "offset=1" in url:
            return {"records": []}
        return {
            "id": 42,
            "@uuid": "item-uuid",
            "longName": "CTD",
            "serialNumber": "ABC",
            "model": "M",
            "manufacturer": "Institute",
        }

    backend = O2ABackend(base_url="https://registry.example", settings=settings, fetch=raising_fetch(fetch))
    result = backend.get_configuration_members(
        ConfigurationMetadata({"startDate": "2026-01-01", "endDate": None}, identifier="30")
    )
    member = result.value.members[0]

    assert member.identifier == "42" and member.instrument_start == "2026-01-01"
    assert member.attributes["mission_item_id"] == "member" and member.attributes["mission_item_uuid"] == "member-uuid"
    assert member.attributes["item_uuid"] == "item-uuid" and member.attributes["serial_number"] == "ABC"
    assert len(calls) == 3 and not any("contacts" in url or "parameters" in url for url in calls)


@pytest.mark.parametrize(
    "period,required", [(None, True), (ConfigurationPeriod(datetime(2026, 1, 1, tzinfo=timezone.utc)), False)]
)
def test_mission_historical_membership_rejected_before_http(period, required):
    def fetch(*args, **kwargs):
        pytest.fail("Historical membership must not issue HTTP")

    backend = O2ABackend(base_url="https://registry.example", settings=O2ABackendSettings(), fetch=raising_fetch(fetch))
    result = backend.get_configuration_members(
        ConfigurationMetadata({}, identifier="30"), period=period, require_configuration_period=required
    )
    assert result == BackendFailure(("O2A Registry does not support historical mission-membership filtering.",))
