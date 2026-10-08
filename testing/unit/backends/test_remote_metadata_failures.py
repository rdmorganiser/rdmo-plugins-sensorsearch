"""Remote transport failures must become typed failures before reaching workflows."""

from dataclasses import replace

import pytest

from rdmo_sensorsearch.backends.gipp.backend import GIPPBackend
from rdmo_sensorsearch.backends.o2a.backend import O2ABackend
from rdmo_sensorsearch.config_models.backend_settings import GIPPBackendSettings, O2ABackendSettings
from rdmo_sensorsearch.contracts import BackendFailure
from rdmo_sensorsearch.transport import TransportError
from testing.transport_helpers import raising_fetch


@pytest.mark.parametrize("endpoint", ("item", "contacts", "parameters", "units"))
@pytest.mark.parametrize("malformed", (False, True))
def test_o2a_item_endpoint_failures(monkeypatch, endpoint, malformed):
    responses = {"item": {"id": "42"}, "contacts": {}, "parameters": {}, "units": {}}
    responses[endpoint] = [] if malformed else TransportError("unavailable; try later")
    payloads = iter(responses.values())
    fetch = raising_fetch(lambda url, auth_token=None: next(payloads))
    handler = O2ABackend(base_url="https://registry.example", settings=O2ABackendSettings(), fetch=fetch)

    result = handler.get_device("42")

    errors = (
        (f"Unexpected O2A {endpoint} payload for item 42: list",)
        if malformed
        else (f"O2A {endpoint} request for item 42 failed: unavailable; try later",)
    )
    assert result == BackendFailure(errors)


def test_o2a_item_aggregates_endpoint_failures_in_request_order(monkeypatch):
    payloads = iter(({}, TransportError("unavailable"), [], {}))
    fetch = raising_fetch(lambda url, auth_token=None: next(payloads))
    handler = O2ABackend(base_url="https://registry.example", settings=O2ABackendSettings(), fetch=fetch)

    assert handler.get_device("42") == BackendFailure(
        (
            "O2A item request for item 42 returned no data.",
            "O2A contacts request for item 42 failed: unavailable",
            "Unexpected O2A parameters payload for item 42: list",
        )
    )


@pytest.mark.parametrize(
    ("payload", "errors"),
    (
        (TransportError("unavailable; try later"), ("unavailable; try later",)),
        ([], ("Unexpected O2A mission payload for ID 30",)),
        ({}, ("O2A mission request for ID 30 returned no mission data.",)),
    ),
)
def test_o2a_mission_metadata_failures(monkeypatch, payload, errors):
    fetch = raising_fetch(lambda url, auth_token=None: payload)
    handler = O2ABackend(base_url="https://registry.example", settings=O2ABackendSettings(), fetch=fetch)

    assert handler.get_configuration("30") == BackendFailure(errors)


@pytest.mark.parametrize(
    ("pages", "errors"),
    (
        ([TransportError("unavailable")], ("unavailable",)),
        ([None], ("Unexpected O2A mission items payload: NoneType",)),
        (
            [{"records": [{"itemId": 1}]}, TransportError("second page unavailable")],
            ("second page unavailable",),
        ),
        (
            [{"records": [{"itemId": 1}]}, {"records": [{"itemId": 1}]}],
            ("O2A mission item pagination returned the same page more than once.",),
        ),
        (
            [{"records": [{"itemId": 1}]}, {"records": [{"itemId": 2}]}],
            ("O2A mission item pagination exceeded 2 pages.",),
        ),
    ),
)
def test_o2a_mission_collection_failures_discard_partial_metadata(monkeypatch, pages, errors):
    payloads = iter([{"id": "30", "name": "Mission"}, *pages])
    fetch = raising_fetch(lambda url, auth_token=None: next(payloads))
    handler = O2ABackend(base_url="https://registry.example", settings=O2ABackendSettings(), fetch=fetch)
    handler._mission.settings = replace(handler._mission.settings, mission_item_page_size=1, max_collection_pages=2)
    metadata = handler.get_configuration("30").value

    assert handler.get_configuration_members(metadata) == BackendFailure(errors)


@pytest.mark.parametrize(
    ("payload", "errors"),
    (
        (TransportError("unavailable; try later"), ("unavailable; try later",)),
        ([], ("Unexpected GIPP payload for instrument 1: list",)),
        ({}, ("GIPP request for instrument 1 returned no instrument data.",)),
    ),
)
def test_gipp_metadata_failures(monkeypatch, payload, errors):
    fetch = raising_fetch(lambda url, auth_token=None: payload)
    handler = GIPPBackend(base_url="https://gipp.example", settings=GIPPBackendSettings(), fetch=fetch)

    assert handler.get_device("1") == BackendFailure(errors)
