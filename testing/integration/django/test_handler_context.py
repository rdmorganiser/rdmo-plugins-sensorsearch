from types import SimpleNamespace

import pytest

from rdmo.projects.models import Snapshot

from rdmo_sensorsearch.persistence.handler_context import device_configuration_reference, read_configuration_period
from rdmo_sensorsearch.workflows import backend_value_sync
from testing.performance.fixtures import insert_values, make_workload

pytestmark = pytest.mark.django_db


def test_device_context_uses_latest_live_root_from_exact_collection_scope():
    workload = make_workload(0)
    snapshot = Snapshot.objects.create(project=workload.project, title="Historical")
    common = {"attribute": workload.attributes["root"], "set_collection": True, "set_prefix": "4", "set_index": 2}
    insert_values(
        workload.project,
        [
            {**common, "external_id": "cfg:old||sms:1"},
            {**common, "external_id": "cfg:current||sms:1"},
            {**common, "external_id": "cfg:other-row||sms:1", "set_index": 3},
            {**common, "external_id": "cfg:other-prefix||sms:1", "set_prefix": "5"},
            {**common, "external_id": "cfg:snapshot||sms:1", "snapshot": snapshot},
            {**common, "external_id": "cfg:scalar||sms:1", "set_collection": False},
            {**common, "external_id": ""},
        ],
    )
    instance = SimpleNamespace(project=workload.project, set_prefix="4", set_index=2)
    assert device_configuration_reference(instance, workload.attributes["root"].uri) == "cfg:current"
    instance.set_index = 3
    assert device_configuration_reference(instance, workload.attributes["root"].uri) == "cfg:other-row"
    instance.set_index = 99
    assert device_configuration_reference(instance, workload.attributes["root"].uri) is None


@pytest.mark.parametrize("end, expected_error", (("", None), ("2026-02-01 00:00", None), ("2025-01-01 00:00", "earlier")))
def test_period_context_preserves_scope_and_validation(end, expected_error):
    workload = make_workload(0)
    common = {"set_prefix": "2", "set_index": 0}
    insert_values(
        workload.project,
        [
            {**common, "attribute": workload.attributes["start"], "text": "2026-01-01 00:00"},
            {**common, "attribute": workload.attributes["end"], "text": end},
            {**common, "attribute": workload.attributes["start"], "text": "1999-01-01 00:00", "set_prefix": "3"},
        ],
    )
    instance = SimpleNamespace(project=workload.project, **common)
    period, error = read_configuration_period(instance, workload.attributes["start"].uri, workload.attributes["end"].uri)
    if expected_error:
        assert period is None and expected_error in error
    else:
        assert error is None
        assert period.formatted == ("2026-01-01 00:00", end or None)


def test_invalid_period_stops_refresh_before_handler_or_persistence(monkeypatch):
    workload = make_workload(0)
    instance = SimpleNamespace(
        project=workload.project,
        attribute=workload.attributes["search"],
        external_id="cfg:1",
        set_prefix="",
        set_index=0,
    )
    handler = SimpleNamespace(
        membership_filter_enabled=True,
        membership_filter_start_attribute_uri=workload.attributes["start"].uri,
        membership_filter_end_attribute_uri=workload.attributes["end"].uri,
        handle=lambda **kwargs: pytest.fail("Invalid input must be rejected before backend fetching."),
    )
    binding = SimpleNamespace(handler=handler, id_prefix="cfg", search_attribute_uri=instance.attribute.uri)
    monkeypatch.setattr(backend_value_sync, "get_handler_bindings_for_catalog", lambda uri: [binding])
    monkeypatch.setattr(
        backend_value_sync, "_reconcile_result", lambda *args: pytest.fail("Invalid input must not be persisted.")
    )
    result = backend_value_sync.refresh_value_from_backend(instance, require_configuration_period=True)
    assert result.refreshed_count == 0
    assert result.errors[0].message == "Enter a membership filter start date before applying the date range."
