from contextvars import ContextVar
from dataclasses import replace
from threading import Lock
from time import sleep
from types import SimpleNamespace

import pytest

from rdmo_sensorsearch.contracts import (
    CollectionAssignment,
    HandlerFailure,
    HandlerResult,
    RefreshDeviceDetails,
    RefreshNotice,
    SelectedDevice,
)
from rdmo_sensorsearch.services.device_detail_profile import DEFAULT_DEVICE_DETAIL_SETTINGS
from rdmo_sensorsearch.services.device_details import DeviceBlockPlan
from rdmo_sensorsearch.services.device_metadata import fetch_device_metadata_batch

START_ATTRIBUTE_URI = "attribute:start"
END_ATTRIBUTE_URI = "attribute:end"


def _plan(
    external_id: str,
    handler,
    *,
    set_index: int = 0,
    needs_refresh: bool = True,
) -> DeviceBlockPlan:
    return DeviceBlockPlan(
        device=SelectedDevice(text=external_id, external_id=external_id),
        block_key=f"cfg:1||{external_id}",
        set_index=set_index,
        handler_binding=SimpleNamespace(handler=handler),
        needs_metadata_write=True,
        needs_refresh=needs_refresh,
        configuration_external_id="cfg:1",
    )


class RecordingHandler:
    def __init__(self, result, *, uses_auth_token=False):
        self.result = result
        self.uses_auth_token = uses_auth_token
        self.calls = []

    def handle(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_fetch_service_invokes_only_refresh_plans_and_extracts_scoped_values():
    settings = replace(DEFAULT_DEVICE_DETAIL_SETTINGS, device_link_attribute_uri="attribute:custom-link")
    handler = RecordingHandler(
        HandlerResult(
            mapped_values={
                "attribute:name": "Temperature probe",
                START_ATTRIBUTE_URI: "2026-01-01 00:00",
            }
        )
    )
    skipped_handler = RecordingHandler(HandlerResult(mapped_values={"attribute:name": "unchanged"}))
    enrichment_calls = []

    def enrich(mapped_values, plan):
        enrichment_calls.append(plan.block_key)
        mapped_values[END_ATTRIBUTE_URI] = "2026-02-01 00:00"

    result = fetch_device_metadata_batch(
        (
            _plan("kitsms:324", handler, set_index=4),
            _plan("kitsms:325", skipped_handler, set_index=5, needs_refresh=False),
        ),
        device_detail_settings=settings,
        scoped_attribute_uris=(START_ATTRIBUTE_URI, END_ATTRIBUTE_URI),
        enrich_payload=enrich,
    )

    payload = result.payloads["cfg:1||kitsms:324"]
    assert payload.mapped_values == {"attribute:name": "Temperature probe"}
    assert payload.scoped_scalar_values == {
        START_ATTRIBUTE_URI: "2026-01-01 00:00",
        END_ATTRIBUTE_URI: "2026-02-01 00:00",
    }
    assert result.errors == ()
    assert enrichment_calls == ["cfg:1||kitsms:324"]
    assert skipped_handler.calls == []
    assert handler.calls[0]["backend_id"] == "324"
    assert "instance" not in handler.calls[0]
    assert handler.calls[0]["context"].configuration_external_id is None
    assert handler.calls[0]["context"].device_detail_settings is settings
    assert "auth_token" not in handler.calls[0]


def test_fetch_service_combines_handler_and_enrichment_notices():
    handler_notice = RefreshNotice("static_location_height_missing", "324")
    enrichment_notice = RefreshNotice("parent_mount_action_missing", "324")
    handler = RecordingHandler(HandlerResult(notices=(handler_notice,)))

    result = fetch_device_metadata_batch(
        (_plan("kitsms:324", handler),),
        device_detail_settings=DEFAULT_DEVICE_DETAIL_SETTINGS,
        scoped_attribute_uris=(),
        enrich_payload=lambda _mapped_values, _plan: (enrichment_notice,),
    )

    assert result.payloads["cfg:1||kitsms:324"].notices == (handler_notice, enrichment_notice)


def test_fetch_service_passes_authentication_and_copies_context_into_worker():
    request_marker = ContextVar("request_marker", default="missing")

    class ContextHandler:
        uses_auth_token = True

        def handle(self, **kwargs):
            return HandlerResult(
                mapped_values={
                    "attribute:context": request_marker.get(),
                    "attribute:token": kwargs.get("auth_token"),
                }
            )

    request_marker.set("request-42")
    result = fetch_device_metadata_batch(
        (_plan("kitsms:42", ContextHandler()),),
        device_detail_settings=DEFAULT_DEVICE_DETAIL_SETTINGS,
        scoped_attribute_uris=(),
        auth_token="secret-token",
    )

    assert result.payloads["cfg:1||kitsms:42"].mapped_values == {
        "attribute:context": "request-42",
        "attribute:token": "secret-token",
    }


@pytest.mark.parametrize(
    ("external_id", "handler_result", "expected_message"),
    (
        ("kitsms:1", HandlerFailure(("not found", "not authorized")), "not found; not authorized"),
        ("kitsms:legacy", {"errors": ["legacy"]}, "Device handler returned unexpected payload type: dict."),
        ("kitsms:2", "unexpected", "Device handler returned unexpected payload type: str."),
        (
            "kitsms:4",
            HandlerResult(effects=(RefreshDeviceDetails((), "selected", "root"),)),
            "Sensor handlers cannot return collections or effects during block sync.",
        ),
        (
            "kitsms:3",
            HandlerResult(
                collections=(
                    CollectionAssignment(
                        attribute_uri="attribute:collection",
                        page_uri="page:devices",
                    ),
                )
            ),
            "Sensor handlers cannot return collections or effects during block sync.",
        ),
    ),
)
def test_fetch_service_converts_invalid_handler_results_to_structured_errors(
    external_id,
    handler_result,
    expected_message,
):
    result = fetch_device_metadata_batch(
        (_plan(external_id, RecordingHandler(handler_result)),),
        device_detail_settings=DEFAULT_DEVICE_DETAIL_SETTINGS,
        scoped_attribute_uris=(),
    )

    assert result.payloads == {}
    assert len(result.errors) == 1
    assert result.errors[0].external_id == f"cfg:1||{external_id}"
    assert result.errors[0].message == expected_message


def test_fetch_service_isolates_handler_exceptions_per_device():
    failing_handler = RecordingHandler(RuntimeError("backend unavailable"))
    successful_handler = RecordingHandler(HandlerResult(mapped_values={"attribute:name": "working"}))

    result = fetch_device_metadata_batch(
        (
            _plan("kitsms:1", failing_handler),
            _plan("kitsms:2", successful_handler),
        ),
        device_detail_settings=DEFAULT_DEVICE_DETAIL_SETTINGS,
        scoped_attribute_uris=(),
    )

    assert result.payloads["cfg:1||kitsms:2"].mapped_values == {"attribute:name": "working"}
    assert [(error.external_id, error.message) for error in result.errors] == [("cfg:1||kitsms:1", "backend unavailable")]


def test_fetch_service_isolates_typed_failures_and_only_enriches_successful_payloads():
    enriched = []
    result = fetch_device_metadata_batch(
        (
            _plan("kitsms:1", RecordingHandler(HandlerFailure(("unavailable", "try later")))),
            _plan("kitsms:2", RecordingHandler(HandlerResult(mapped_values={"name": "working"}))),
        ),
        device_detail_settings=DEFAULT_DEVICE_DETAIL_SETTINGS,
        scoped_attribute_uris=(),
        enrich_payload=lambda mapped_values, plan: enriched.append(plan.block_key),
    )

    assert set(result.payloads) == {"cfg:1||kitsms:2"}
    assert result.payloads["cfg:1||kitsms:2"].mapped_values == {"name": "working"}
    assert [(error.external_id, error.message) for error in result.errors] == [("cfg:1||kitsms:1", "unavailable; try later")]
    assert enriched == ["cfg:1||kitsms:2"]


def test_fetch_service_rejects_an_external_id_without_a_backend_value():
    handler = RecordingHandler(HandlerResult(mapped_values={}))

    result = fetch_device_metadata_batch(
        (_plan("kitsms:", handler),),
        device_detail_settings=DEFAULT_DEVICE_DETAIL_SETTINGS,
        scoped_attribute_uris=(),
    )

    assert handler.calls == []
    assert result.errors[0].message == "Could not parse external device ID."


def test_fetch_service_bounds_parallel_handler_calls():
    lock = Lock()
    active_calls = 0
    peak_calls = 0

    class SlowHandler:
        uses_auth_token = False

        def handle(self, **_kwargs):
            nonlocal active_calls, peak_calls
            with lock:
                active_calls += 1
                peak_calls = max(peak_calls, active_calls)
            sleep(0.02)
            with lock:
                active_calls -= 1
            return HandlerResult(mapped_values={})

    result = fetch_device_metadata_batch(
        tuple(_plan(f"kitsms:{index}", SlowHandler()) for index in range(4)),
        device_detail_settings=DEFAULT_DEVICE_DETAIL_SETTINGS,
        scoped_attribute_uris=(),
        max_workers=2,
    )

    assert len(result.payloads) == 4
    assert peak_calls == 2


def test_fetch_service_rejects_a_nonpositive_worker_limit():
    with pytest.raises(ValueError, match="max_workers must be greater than zero"):
        fetch_device_metadata_batch(
            (_plan("kitsms:1", RecordingHandler(HandlerResult())),),
            device_detail_settings=DEFAULT_DEVICE_DETAIL_SETTINGS,
            scoped_attribute_uris=(),
            max_workers=0,
        )
