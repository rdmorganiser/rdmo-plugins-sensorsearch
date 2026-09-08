from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from django.db import transaction
from django.db.models import Q

from rdmo.projects.models import Project, Snapshot, Value
from rdmo.questions.models import Question, QuestionSet

from rdmo_sensorsearch.persistence.catalog_context import get_catalog_context, workflow_catalog_context
from rdmo_sensorsearch.persistence.collection_binding import CollectionBinding, CollectionBindingError, CollectionLayout
from rdmo_sensorsearch.persistence.device_details import catalog_attribute_ids
from rdmo_sensorsearch.persistence.value_reconciliation import _ScalarScopeResolver
from rdmo_sensorsearch.services.data_collection_variables import ParameterUnitPair, variable_unit_marker
from rdmo_sensorsearch.services.device_details import plan_device_detail_reconciliation
from rdmo_sensorsearch.services.synchronization_context import mute_value_sync
from rdmo_sensorsearch.signals import receivers
from rdmo_sensorsearch.workflows import data_collection_variables, event_routing, value_events
from testing.performance.fixtures import insert_values, make_workload
from testing.performance.measure import benchmark, measure

pytestmark = pytest.mark.django_db


def device_plan(workload, *, bulk, force=False):
    store = workload.store
    attributes = workload.attributes
    state = store.load_planning_state(a.uri for a in attributes.values()) if bulk else store
    return plan_device_detail_reconciliation(
        selected_devices=workload.devices,
        configuration_key="cfg:1",
        configuration_external_id="cfg:1",
        set_prefix=store.scope_prefix,
        existing_blocks=state.existing_blocks("cfg:1"),
        next_set_index=state.next_index if bulk else store.next_set_index(),
        resolve_handler=lambda external_id: workload.binding,
        metadata_is_current=lambda device, key, index, binding: state.block_metadata_is_current(
            device,
            key,
            index,
            binding,
            "Configuration",
        ),
        refresh_is_required=lambda index: state.block_needs_refresh(
            index,
            device_link_attribute_uri=attributes["link"].uri,
            usage_technology_attribute_uri=attributes["usage"].uri,
            instrument_start_attribute_uri=attributes["start"].uri,
        ),
        force_refresh=force,
    )


def legacy_parameters(store, external_id):
    """The pre-optimization query path, retained only as a parity oracle."""
    blocks = (
        Value.objects.filter(
            project=store.project,
            snapshot=None,
            attribute=store.attributes.device_collection,
            set_collection=True,
        )
        .filter(Q(external_id=external_id) | Q(external_id__endswith=f"||{external_id}"))
        .order_by(
            "set_prefix",
            "set_index",
            "id",
        )
    )
    parameters = []
    for block in blocks:
        names = store._values_by_set_index(store.attributes.parameter_name, str(block.set_index))
        units = store._values_by_set_index(store.attributes.parameter_unit, str(block.set_index))
        for index in sorted(set(names) | set(units)):
            name, unit = names.get(index, ""), units.get(index, "")
            if name or unit:
                parameters.append(ParameterUnitPair(name, unit))
    return tuple(parameters)


@pytest.mark.parametrize("count", [1, 10, 50, 100])
def test_device_planning_has_constant_reads(count):
    workload = make_workload(count)
    old, old_metrics = measure(lambda: device_plan(workload, bulk=False))
    new, new_metrics = measure(lambda: device_plan(workload, bulk=True))
    assert new == old
    assert not any(block.needs_refresh or block.needs_metadata_write for block in new.blocks)
    assert old_metrics["sql"] == {"SELECT": 2 + 5 * count}
    assert new_metrics["sql"] == {"SELECT": 2}
    benchmark(f"devices/{count}/legacy", lambda: device_plan(workload, bulk=False))
    benchmark(f"devices/{count}/bulk", lambda: device_plan(workload, bulk=True))


def test_device_state_preserves_duplicates_scopes_snapshots_and_index_allocation(django_assert_num_queries):
    workload = make_workload(2, prefix="2|3")
    a = workload.attributes
    snapshot = Snapshot.objects.create(project=workload.project, title="Historical")
    insert_values(
        workload.project,
        [
            {
                "attribute": a["root"],
                "set_collection": True,
                "set_prefix": "2|3",
                "set_index": 30,
                "external_id": "cfg:other||sms:9",
            },
            {"attribute": a["root"], "set_collection": True, "set_prefix": "2|3", "set_index": 40, "external_id": ""},
            {
                "attribute": a["root"],
                "set_collection": True,
                "set_prefix": "other",
                "set_index": 100,
                "external_id": "cfg:1||sms:0",
            },
            {"attribute": a["search"], "set_prefix": "2|3", "text": "Wrong later duplicate", "external_id": "sms:0"},
            {"attribute": a["start"], "set_prefix": "0", "text": ""},
            {"attribute": a["root"], "set_collection": True, "snapshot": snapshot, "set_prefix": "2|3", "set_index": 200},
        ],
    )
    assert device_plan(workload, bulk=True) == device_plan(workload, bulk=False)
    state = workload.store.load_planning_state(a.uri for a in a.values())
    assert state.next_index == 41
    with django_assert_num_queries(0):
        assert state.block_metadata_is_current(workload.devices[0], "cfg:1||sms:0", 0, workload.binding, "Configuration")
    with mute_value_sync():
        Value.objects.filter(project=workload.project, attribute=a["start"], set_prefix="0").delete()
    assert device_plan(workload, bulk=True) == device_plan(workload, bulk=False)
    assert device_plan(workload, bulk=True).blocks[0].needs_refresh
    assert all(block.needs_refresh for block in device_plan(workload, bulk=True, force=True).blocks)


@pytest.mark.parametrize("count", [1, 10, 50, 100])
def test_variable_parameters_have_constant_reads(count):
    workload = make_workload(count)
    ids = [device.external_id for device in workload.devices]

    def old_op():
        return {device_id: legacy_parameters(workload.variables, device_id) for device_id in ids}

    def new_op():
        return workload.variables.parameters_by_device(ids)

    old, old_metrics = measure(old_op)
    new, new_metrics = measure(new_op)
    assert old == new
    assert old_metrics["sql"] == {"SELECT": 3 * count}
    assert new_metrics["sql"] == {"SELECT": 2}
    benchmark(f"parameters/{count}/legacy", old_op)
    benchmark(f"parameters/{count}/bulk", new_op)


def test_parameter_and_variable_duplicate_precedence(django_assert_num_queries):
    workload = make_workload(2)
    a = workload.attributes
    marker = variable_unit_marker(ParameterUnitPair("generated", "K"))
    snapshot = Snapshot.objects.create(project=workload.project, title="Historical")
    insert_values(
        workload.project,
        [
            {"attribute": a["root"], "set_collection": True, "set_index": 4, "external_id": "sms:0"},
            {
                "attribute": a["root"],
                "set_collection": True,
                "set_prefix": "other",
                "set_index": 4,
                "external_id": "cfg:2||sms:0",
            },
            {"attribute": a["name"], "set_collection": True, "set_prefix": "4", "text": "earlier"},
            {"attribute": a["name"], "set_collection": True, "set_prefix": "4", "text": ""},
            {"attribute": a["unit"], "set_collection": True, "set_prefix": "4", "text": "unit only"},
            {"attribute": a["name"], "set_collection": True, "set_prefix": "4", "text": "historical", "snapshot": snapshot},
            {"attribute": a["variable"], "set_collection": True, "set_prefix": "0", "text": "generated", "external_id": marker},
            {"attribute": a["variable"], "set_collection": True, "set_prefix": "0", "text": "later", "external_id": "manual"},
            {"attribute": a["variable-unit"], "set_collection": True, "set_prefix": "0", "text": "K", "external_id": marker},
            {"attribute": a["variable"], "set_collection": True, "set_prefix": "0", "set_index": 1, "text": "manual"},
        ],
    )
    ids = ("sms:0", "sms:1", "missing")
    assert workload.variables.parameters_by_device(ids) == {key: legacy_parameters(workload.variables, key) for key in ids}
    with django_assert_num_queries(1):
        variables = workload.variables.existing_variables()
    assert [(v.name, v.unit, v.external_id) for v in variables] == [("later", "K", marker), ("manual", "", None)]


def test_parameter_matching_preserves_database_comparisons_and_batches():
    workload = make_workload(1)
    Value.objects.filter(project=workload.project, attribute=workload.attributes["root"]).update(
        external_id="cfg:1||SMS:0",
    )
    ids = ("sms:0", "SMS:0", "cfg:1||SMS:0", "sms:%", "sms:_", *(f"missing:{i}" for i in range(101)))
    assert workload.variables.parameters_by_device(ids) == {
        device_id: legacy_parameters(workload.variables, device_id) for device_id in ids
    }


def test_variable_workflow_uses_union_once_and_does_not_rewrite(monkeypatch):
    workload = make_workload(2)
    a = workload.attributes
    settings = data_collection_variables.DataCollectionVariableSyncSettings(
        a["selected"].uri,
        a["root"].uri,
        a["name"].uri,
        a["unit"].uri,
        a["variable"].uri,
        a["variable-unit"].uri,
    )
    source = Value.objects.get(project=workload.project, attribute=a["selected"], external_id="sms:0")
    monkeypatch.setattr(data_collection_variables.RDMODataCollectionVariableStore, "resolve", lambda **kwargs: workload.variables)
    loader = Mock(wraps=workload.variables.parameters_by_device)
    monkeypatch.setattr(workload.variables, "parameters_by_device", loader)

    def operation():
        return data_collection_variables.reconcile_data_collection_variables_for_selected_device(source, settings)

    operation()
    loader.assert_called_once_with({"sms:0", "sms:1"})
    before = list(Value.objects.filter(project=workload.project).order_by("id").values())
    _, metrics = measure(operation)
    assert not any(key in metrics["sql"] for key in ("INSERT", "UPDATE", "DELETE"))
    assert list(Value.objects.filter(project=workload.project).order_by("id").values()) == before
    benchmark("variables/unchanged", operation)


def test_unrelated_signal_fast_path_and_loaded_relations(monkeypatch, django_assert_num_queries):
    workload = make_workload(1)
    value = Value.objects.filter(project=workload.project, attribute=workload.attributes["link"]).first()
    auth, callback = Mock(), Mock()
    monkeypatch.setattr(receivers, "get_sms_auth_token", auth)
    monkeypatch.setattr(receivers.transaction, "on_commit", callback)
    with django_assert_num_queries(1):
        receivers.value_saved(Value, value, raw=False)
    with django_assert_num_queries(1):
        receivers.value_deleted(Value, value)
    value.attribute = workload.attributes["link"]
    with django_assert_num_queries(0):
        receivers.value_saved(Value, value, raw=False)
        receivers.value_deleted(Value, value)
    auth.assert_not_called()
    callback.assert_not_called()
    benchmark("signals/unrelated-loaded", lambda: receivers.value_saved(Value, value, raw=False))


@pytest.mark.parametrize("rollback", [False, True])
def test_relevant_callbacks_follow_savepoints(monkeypatch, rollback, django_capture_on_commit_callbacks):
    workload = make_workload(1)
    uri = workload.attributes["search"].uri
    monkeypatch.setattr(event_routing, "routing_attributes", lambda: {"*": frozenset({uri})})
    saved, deleted = Mock(), Mock()
    monkeypatch.setattr(receivers, "handle_value_saved", saved)
    monkeypatch.setattr(receivers, "handle_value_deleted", deleted)
    monkeypatch.setattr(receivers, "get_sms_auth_token", lambda: "token")
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            try:
                with transaction.atomic():
                    value = Value.objects.create(project=workload.project, attribute=workload.attributes["search"])
                    value.delete()
                    if rollback:
                        raise ValueError("rollback")
            except ValueError:
                pass
        saved.assert_not_called()
        deleted.assert_not_called()
    assert saved.call_count == deleted.call_count == (0 if rollback else 1)


@pytest.mark.parametrize("layout", ["question", "questionset"])
def test_binding_cache_preserves_layout_and_lifetime(layout, django_assert_num_queries):
    workload = make_workload(1)
    question = Question.objects.get(attribute=workload.attributes["search"])
    if layout == "question":
        question.is_collection = True
        question.save()
    else:
        workload.page.questions.remove(question)
        questionset = QuestionSet.objects.create(
            uri_prefix="https://performance.example",
            uri_path="collection",
            is_collection=True,
        )
        questionset.questions.add(question)
        workload.page.questionsets.add(questionset)

    def resolve():
        return CollectionBinding.resolve(workload.project, workload.attributes["search"], workload.page.uri)

    with workflow_catalog_context():
        with django_assert_num_queries(2):
            first = resolve()
        assert first.layout is CollectionLayout(layout)
        with workflow_catalog_context(), django_assert_num_queries(0):
            assert resolve() == first
    assert get_catalog_context() is None
    with workflow_catalog_context(), django_assert_num_queries(2):
        assert resolve() == first


def test_catalog_cache_errors_pages_and_cleanup(django_assert_num_queries):
    workload = make_workload(1)
    with pytest.raises(RuntimeError), workflow_catalog_context():
        for count in (2, 0):
            with django_assert_num_queries(count), pytest.raises(CollectionBindingError):
                CollectionBinding.resolve(workload.project, workload.attributes["search"])
        expected = catalog_attribute_ids(workload.catalog, {workload.page.uri})
        with django_assert_num_queries(0):
            assert catalog_attribute_ids(workload.catalog, {workload.page.uri}) == expected
            assert catalog_attribute_ids(workload.catalog, {"missing"}) == set()
        raise RuntimeError("exit")
    assert get_catalog_context() is None


@pytest.mark.parametrize("fields", [{}, {"text": "x"}, {"external_id": "x"}, {"file": None}, {"file": "file.txt"}])
def test_meaningful_check_matches_original(fields, django_assert_num_queries):
    workload = make_workload(0)
    insert_values(workload.project, [dict(attribute=workload.attributes["root"], **fields)])
    values = Value.objects.filter(project=workload.project)
    old = (
        values.exclude(text__exact="").exists()
        or values.exclude(external_id__exact="").exists()
        or values.filter(option__isnull=False).exists()
        or values.exclude(file__exact="").exists()
    )
    with django_assert_num_queries(1):
        assert value_events._has_meaningful_collection_values(values) == old


@pytest.mark.parametrize("count", [100, 1000, 5000, 10000])
def test_scalar_scope_scaling(count):
    workload = make_workload(1)
    insert_values(
        workload.project, [{"attribute": workload.attributes["selected"], "text": "unrelated"} for _ in range(count - 8)]
    )

    def operation():
        project = Project.objects.select_related("catalog").get(pk=workload.project.pk)
        instance = SimpleNamespace(project=project, attribute_id=workload.attributes["root"].id, set_prefix="", set_index=0)
        return _ScalarScopeResolver(instance).resolve(instance, workload.attributes["link"])

    assert operation() == [("", 0)]
    benchmark(f"scalar/{count}", operation)


@pytest.mark.parametrize("count", [1, 10, 100, 1000])
@pytest.mark.parametrize("kind", ["unrelated", "relevant", "project"])
def test_delete_callback_scaling(count, kind, monkeypatch, django_capture_on_commit_callbacks):
    workload = make_workload(0)
    attribute = workload.attributes["selected"]
    insert_values(
        workload.project,
        [{"attribute": attribute, "external_id": f"sms:{index}", "set_collection": True} for index in range(count)],
    )
    monkeypatch.setattr(
        event_routing,
        "routing_attributes",
        lambda: {
            "*": frozenset({attribute.uri}) if kind != "unrelated" else frozenset(),
        },
    )

    def operation():
        with transaction.atomic():
            with django_capture_on_commit_callbacks(execute=True):
                if kind == "project":
                    Project.objects.filter(pk=workload.project.pk).delete()
                else:
                    Value.objects.filter(project=workload.project).delete()
            transaction.set_rollback(True)

    _, metrics = measure(operation)
    assert metrics["counts"]["value.deleted"] == count
    expected_callbacks = count if kind == "relevant" else 0
    assert metrics["counts"].get("callback.delete.scheduled", 0) == expected_callbacks
    assert metrics["counts"].get("callback.delete.executed", 0) == expected_callbacks
    assert Value.objects.filter(project=workload.project).count() == count
    benchmark(f"delete/{kind}/{count}", operation)
