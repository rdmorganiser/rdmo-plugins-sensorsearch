from types import SimpleNamespace

import pytest

from django.db import transaction

from rdmo.projects.models import Value

from rdmo_sensorsearch.contracts import HandlerFailure, HandlerResult, RefreshDeviceDetails, RefreshNotice, SelectedDevice
from rdmo_sensorsearch.services.refresh import RefreshResult
from rdmo_sensorsearch.workflows import backend_value_sync
from testing.performance.fixtures import make_workload


@pytest.mark.django_db
@pytest.mark.parametrize("preserve", (False, True))
@pytest.mark.parametrize(
    ("output", "message"),
    (
        (HandlerFailure(("unavailable", "try later")), "unavailable; try later"),
        ({"errors": ["legacy"]}, "Handler returned dict, expected HandlerResult."),
    ),
)
def test_handler_failures_skip_persistence_and_effects(monkeypatch, preserve, output, message):
    workload = make_workload(0)
    source = Value.objects.create(
        project=workload.project, attribute=workload.attributes["search"], external_id="sms:42", text="selected"
    )
    handler = SimpleNamespace(uses_auth_token=True, handle=lambda **kwargs: output)
    binding = SimpleNamespace(id_prefix="sms", search_attribute_uri=source.attribute.uri, handler=handler)
    monkeypatch.setattr(backend_value_sync, "get_handler_bindings_for_catalog", lambda uri: [binding])

    def unexpected(*args, **kwargs):
        pytest.fail("Failed handler output must not reach persistence or effects")

    for name in ("_reconcile_result", "_execute_effect", "_refresh_selected_configuration_devices"):
        monkeypatch.setattr(backend_value_sync, name, unexpected)

    result = backend_value_sync.refresh_value_from_backend(source, preserve_existing_collections=preserve)

    source.refresh_from_db()
    assert source.text == "selected"
    assert result.requested_count == 1
    assert result.refreshed_count == result.device_requested_count == result.device_refreshed_count == 0
    assert [(error.external_id, error.message) for error in result.errors] == [("sms:42", message)]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("failure", (None, "persistence", "effect", "unsupported"))
def test_effects_follow_successful_persistence_and_preserve_failure_semantics(monkeypatch, failure):
    workload = make_workload(0)
    source = Value.objects.create(
        project=workload.project, attribute=workload.attributes["search"], external_id="sms:42", text="selected"
    )
    effect = RefreshDeviceDetails((SelectedDevice("Sensor", "sms:1"),), "selected-uri", "root-uri")
    output = HandlerResult(effects=(object() if failure == "unsupported" else effect,))
    handler = SimpleNamespace(uses_auth_token=True, handle=lambda **kwargs: output)
    binding = SimpleNamespace(id_prefix="sms", search_attribute_uri=source.attribute.uri, handler=handler)
    monkeypatch.setattr(backend_value_sync, "get_handler_bindings_for_catalog", lambda uri: [binding])
    events = []

    def persist(instance, handler, result):
        events.append("persist")
        assert transaction.get_connection().in_atomic_block
        Value.objects.filter(pk=source.pk).update(text="synchronized")
        if failure == "persistence":
            raise ValueError("storage failed")

    def reconcile(**kwargs):
        events.append("effect")
        assert not transaction.get_connection().in_atomic_block
        assert Value.objects.get(pk=source.pk).text == "synchronized"
        assert kwargs["selected_devices"] == effect.selected_devices
        assert kwargs["project"] == source.project
        assert kwargs["configuration_external_id"] == "sms:42"
        assert kwargs["configuration_search_attribute_uri"] == source.attribute.uri
        assert kwargs["auth_token"] == "token"
        assert kwargs["force_refresh"] is True
        if failure == "effect":
            raise ValueError("follow-up failed")
        return RefreshResult(1, 1, notices=(RefreshNotice("test-notice"),))

    monkeypatch.setattr(backend_value_sync, "_reconcile_result", persist)
    monkeypatch.setattr(backend_value_sync, "reconcile_device_details_from_selected_devices", reconcile)
    result = backend_value_sync.refresh_value_from_backend(source, auth_token="token")
    source.refresh_from_db()
    if failure == "persistence":
        assert events == ["persist"]
        assert source.text == "selected"
        assert "Could not store backend data" in result.errors[0].message
    elif failure in ("effect", "unsupported"):
        assert events == (["persist", "effect"] if failure == "effect" else ["persist"])
        assert source.text == "synchronized"
        assert "Could not complete backend update" in result.errors[0].message
    else:
        assert events == ["persist", "effect"]
        assert result.refreshed_count == result.device_refreshed_count == 1
        assert result.device_requested_count == 1
        assert result.notices == (RefreshNotice("test-notice"),)
    assert result.refreshed_count == (0 if failure else 1)
