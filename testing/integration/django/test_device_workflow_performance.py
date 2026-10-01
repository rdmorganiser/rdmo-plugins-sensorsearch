from collections import Counter
from types import SimpleNamespace

import pytest

from django.db import transaction

from rdmo.projects.models import Value
from rdmo.questions.models import Question

from rdmo_sensorsearch import client
from rdmo_sensorsearch.contracts import HandlerResult, SelectedDevice
from rdmo_sensorsearch.services.device_details import ConfigurationIdentity
from rdmo_sensorsearch.services.performance import capture_performance
from rdmo_sensorsearch.workflows import device_details
from testing.performance.fixtures import make_workload
from testing.performance.measure import benchmark, measure

pytestmark = pytest.mark.django_db


@pytest.fixture
def device_workflow(monkeypatch):
    workload = make_workload(0)
    a = workload.attributes
    # Include nested metadata attributes in cleanup ownership for this fixture.
    for name in ("start", "end", "name", "unit"):
        question = Question.objects.create(
            uri_prefix="https://performance.example",
            uri_path=name,
            attribute=a[name],
            is_collection=name in ("name", "unit"),
        )
        workload.page.questions.add(question)
    settings = SimpleNamespace(
        configuration_collection_attribute_uri=a["root"].uri,
        device_details_page_uri=workload.page.uri,
        device_optional_info_page_uri="unused",
        device_link_attribute_uri=a["link"].uri,
        usage_technology_attribute_uri=a["usage"].uri,
        instrument_start_attribute_uri=a["start"].uri,
        instrument_end_attribute_uri=a["end"].uri,
    )
    failed_ids = set()

    class Handler:
        materialize_device_details = True

        def handle(self, backend_id, instance):
            client.fetch_json("https://backend.example/configuration")
            response = client.fetch_json(f"https://backend.example/devices/{backend_id}")
            if backend_id in failed_ids:
                return {"errors": ["Synthetic backend failure"]}
            return HandlerResult(
                mapped_values={
                    a["link"].uri: response["link"],
                    a["usage"].uri: "instrument",
                    a["start"].uri: "2026-01-01",
                    a["name"].uri: ["temperature"],
                    a["unit"].uri: ["K"],
                }
            )

        def build_authoritative_mapped_values(self, values, excluded_attribute_uris=()):
            return {key: value for key, value in values.items() if key not in excluded_attribute_uris}

    class Enricher:
        scoped_attribute_uris = (a["start"].uri,)

        def __init__(self, **kwargs):
            pass

        def __call__(self, mapped_values, plan):
            return ()

    binding = SimpleNamespace(id_prefix="sms", search_attribute_uri=a["search"].uri, handler=Handler())
    monkeypatch.setattr(device_details, "get_device_detail_settings", lambda uri, **kwargs: settings)
    monkeypatch.setattr(device_details, "get_handler_bindings_for_catalog", lambda uri: [binding])
    monkeypatch.setattr(
        device_details,
        "_resolve_configuration_identity",
        lambda **kwargs: ConfigurationIdentity(
            "cfg:1",
            "Configuration",
            "cfg:1",
        ),
    )
    monkeypatch.setattr(device_details, "SMSDeviceMetadataEnricher", Enricher)
    monkeypatch.setattr(
        client.requests,
        "get",
        lambda url, **kwargs: SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
            json=lambda: {"link": url},
        ),
    )

    def synchronize(devices, *, force=False):
        with client.deduplicate_json_requests():
            return device_details.reconcile_device_details(
                project=workload.project,
                catalog=workload.catalog,
                scope_prefix="",
                source_set_index=0,
                selected_devices=devices,
                selected_devices_attribute_uri=a["selected"].uri,
                device_collection_attribute_uri=a["root"].uri,
                configuration_search_attribute_uri=a["search"].uri,
                force_refresh=force,
            )

    return workload, synchronize, failed_ids


@pytest.mark.parametrize("count", [1, 10, 50, 100])
def test_creation_unchanged_refresh_failure_and_cleanup(device_workflow, count):
    workload, synchronize, failed_ids = device_workflow
    devices = tuple(SelectedDevice(text=f"Sensor {index}", external_id=f"sms:{index}") for index in range(count))
    with capture_performance() as creation:
        result = synchronize(devices)
    assert not result.errors
    assert result.refreshed_count == count
    assert creation.as_dict()["counts"]["http.executed"] == count + 1
    values = Value.objects.filter(project=workload.project)
    before = list(values.order_by("id").values())
    # Each device produces root, identity, link, usage, start, name and unit.
    assert values.count() == count * 7
    assert Counter(values.values_list("attribute_id", flat=True)) == {
        workload.attributes[name].pk: count for name in ("root", "search", "link", "usage", "start", "name", "unit")
    }
    result, metrics = measure(lambda: synchronize(devices))
    assert result.requested_count == result.refreshed_count == 0
    assert metrics["counts"].get("http.executed", 0) == 0
    assert not {"INSERT", "UPDATE", "DELETE"} & metrics["sql"].keys()
    assert list(values.order_by("id").values()) == before
    benchmark(f"workflow/{count}/unchanged", lambda: synchronize(devices))
    benchmark(f"workflow/{count}/forced", lambda: synchronize(devices, force=True))

    def create_from_empty():
        # Exclude reset/rollback costs from the inner record used for assertions;
        # optional benchmark timings include the complete rollback-isolated run.
        with transaction.atomic():
            synchronize(())
            created = synchronize(devices)
            transaction.set_rollback(True)
        return created

    benchmark(f"workflow/{count}/initial", create_from_empty)
    failed_ids.add("0")
    with capture_performance() as forced:
        result = synchronize(devices, force=True)
    assert result.refreshed_count == count - 1
    assert len(result.errors) == 1
    assert forced.as_dict()["counts"]["http.executed"] == count + 1
    assert list(values.order_by("id").values()) == before
    result = synchronize(devices[1:])
    assert not result.errors
    assert values.count() == (count - 1) * 7
    assert list(
        values.filter(attribute=workload.attributes["root"])
        .order_by("set_index")
        .values_list(
            "set_index",
            flat=True,
        )
    ) == list(range(count - 1))
