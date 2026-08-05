from contextvars import ContextVar
from threading import Lock
from time import sleep
from types import SimpleNamespace

import pytest

from rdmo_sensorsearch.handlers.base import CollectionAssignment, HandlerResult
from rdmo_sensorsearch.services.device_details import DeviceBlockPlan, SelectedDevice
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
        root_attribute_id=17,
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
    assert handler.calls[0]["instance"].project is None
    assert handler.calls[0]["instance"].attribute_id == 17
    assert handler.calls[0]["instance"].set_index == 4
    assert "auth_token" not in handler.calls[0]


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
        root_attribute_id=1,
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
        ("kitsms:1", {"errors": ["not found", "not authorized"]}, "not found; not authorized"),
        ("kitsms:2", "unexpected", "Device handler returned unexpected payload type: str."),
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
            "Sensor handlers cannot return collections or post-actions during block sync.",
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
        root_attribute_id=1,
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
        root_attribute_id=1,
        scoped_attribute_uris=(),
    )

    assert result.payloads["cfg:1||kitsms:2"].mapped_values == {"attribute:name": "working"}
    assert [(error.external_id, error.message) for error in result.errors] == [("cfg:1||kitsms:1", "backend unavailable")]


def test_fetch_service_rejects_an_external_id_without_a_backend_value():
    handler = RecordingHandler(HandlerResult(mapped_values={}))

    result = fetch_device_metadata_batch(
        (_plan("kitsms:", handler),),
        root_attribute_id=1,
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
        root_attribute_id=1,
        scoped_attribute_uris=(),
        max_workers=2,
    )

    assert len(result.payloads) == 4
    assert peak_calls == 2


def test_fetch_service_rejects_a_nonpositive_worker_limit():
    with pytest.raises(ValueError, match="max_workers must be greater than zero"):
        fetch_device_metadata_batch(
            (_plan("kitsms:1", RecordingHandler(HandlerResult())),),
            root_attribute_id=1,
            scoped_attribute_uris=(),
            max_workers=0,
        )
