from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from django.utils import timezone

from rdmo.core.imports import ImportElementFields
from rdmo.core.xml import parse_xml_to_elements
from rdmo.domain.models import Attribute
from rdmo.management.imports import import_elements
from rdmo.projects.models import Project, Value
from rdmo.questions.models import Catalog

from rdmo_sensorsearch.signals import receivers
from rdmo_sensorsearch.workflows import value_events
from testing.paths import CATALOGS_ROOT

MIRROR_CATALOG_PATH = CATALOGS_ROOT / "example_catalog_sensorsearch.xml"
MIRROR_CATALOG_URI = "https://example.com/terms/questions/plugin-dev/sensorsearch"
PLUGIN_DEV_ATTRIBUTE_URI = "https://example.com/terms/domain/plugin-dev"
PROJECT_LEAD_ATTRIBUTE_URI = "https://example.com/terms/domain/plugin-dev/project-lead"


def _value(**overrides):
    fields = {
        "pk": 17,
        "snapshot_id": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


@pytest.fixture
def mirror_catalog():
    elements, errors = parse_xml_to_elements(MIRROR_CATALOG_PATH)

    assert errors == []
    imported_elements = import_elements(elements)
    assert all(not element[ImportElementFields.ERRORS] for element in imported_elements)

    return Catalog.objects.get(uri=MIRROR_CATALOG_URI)


def _project(catalog):
    return Project.objects.create(title="SensorSearch signal receiver test", catalog=catalog)


def _create_values(project):
    root_attribute = Attribute.objects.get(uri=PLUGIN_DEV_ATTRIBUTE_URI)
    project_lead_attribute = Attribute.objects.get(uri=PROJECT_LEAD_ATTRIBUTE_URI)
    now = timezone.now()
    Value.objects.bulk_create(
        (
            Value(created=now, updated=now, project=project, attribute=root_attribute, text="root"),
            Value(created=now, updated=now, project=project, attribute=project_lead_attribute, text="lead"),
        )
    )


def test_raw_value_save_is_ignored(monkeypatch):
    on_commit = Mock()
    get_auth_token = Mock()
    monkeypatch.setattr(receivers.transaction, "on_commit", on_commit)
    monkeypatch.setattr(receivers, "get_sms_auth_token", get_auth_token)

    receivers.value_saved(sender=Value, instance=_value(), raw=True)

    on_commit.assert_not_called()
    get_auth_token.assert_not_called()


@pytest.mark.django_db
def test_value_save_runs_once_after_commit(monkeypatch, django_capture_on_commit_callbacks):
    handler = Mock()
    monkeypatch.setattr(receivers, "handle_value_saved", handler)
    monkeypatch.setattr(receivers, "get_sms_auth_token", lambda: "token")

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        receivers.value_saved(sender=Value, instance=_value(), raw=False)
        handler.assert_not_called()

    assert len(callbacks) == 1
    handler.assert_called_once_with(value_id=17, auth_token="token")


@pytest.mark.django_db
def test_value_delete_passes_an_immutable_context_after_commit(
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    context = value_events.DeletedValueContext(
        value_id=17,
        project_id=23,
        catalog_uri="https://example.test/catalog",
        attribute_id=42,
        attribute_uri="https://example.test/attribute",
        set_prefix="1",
        set_index=2,
        external_id="sms:7",
    )
    handler = Mock()
    monkeypatch.setattr(receivers.DeletedValueContext, "from_value", lambda instance: context)
    monkeypatch.setattr(receivers, "handle_value_deleted", handler)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        receivers.value_deleted(sender=Value, instance=_value())
        handler.assert_not_called()

    assert len(callbacks) == 1
    handler.assert_called_once_with(context=context)


@pytest.mark.django_db
def test_value_delete_skips_project_queryset_origin(monkeypatch):
    context_from_value = Mock()
    on_commit = Mock()
    monkeypatch.setattr(receivers.DeletedValueContext, "from_value", context_from_value)
    monkeypatch.setattr(receivers.transaction, "on_commit", on_commit)

    receivers.value_deleted(sender=Value, instance=_value(), origin=Project.objects.none())

    context_from_value.assert_not_called()
    on_commit.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_project_delete_skips_sensorsearch_value_handling(
    mirror_catalog,
    monkeypatch,
    django_capture_on_commit_callbacks,
):
    project = _project(mirror_catalog)
    _create_values(project)
    project_id = project.pk
    context_from_value = Mock(wraps=value_events.DeletedValueContext.from_value)
    handler = Mock()
    monkeypatch.setattr(receivers.DeletedValueContext, "from_value", context_from_value)
    monkeypatch.setattr(receivers, "handle_value_deleted", handler)

    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        project.delete()

    assert not Project.objects.filter(pk=project_id).exists()
    assert not Value.objects.filter(project_id=project_id).exists()
    context_from_value.assert_not_called()
    assert callbacks == []
    handler.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_deleted_value_context_ignores_missing_project(mirror_catalog):
    project = _project(mirror_catalog)
    _create_values(project)
    value = Value.objects.filter(project=project).first()

    project.delete()

    assert value_events.DeletedValueContext.from_value(value) is None


def test_workflow_failures_are_isolated(caplog):
    completed = []

    def fail():
        raise RuntimeError("backend unavailable")

    value_events._run_stages(
        "save",
        17,
        23,
        (
            ("backend-value", fail),
            ("configuration-tab", lambda: completed.append("configuration-tab")),
        ),
    )

    assert completed == ["configuration-tab"]
    assert "Sensorsearch save stage backend-value failed for value=17 project=23" in caplog.text


def test_save_workflow_only_builds_relevant_stages(monkeypatch):
    catalog_uri = "https://example.test/catalog"
    search_uri = "https://example.test/search"
    configuration_uri = "https://example.test/configuration"
    selected_uri = "https://example.test/selected"
    variables_uri = "https://example.test/variables"
    refresh_uri = "https://example.test/refresh"
    source_uri = "https://example.test/source"
    input_uri = "https://example.test/input"
    handler = SimpleNamespace(
        configuration_collection_attribute_uri=configuration_uri,
        selected_devices_attribute_uri=selected_uri,
        device_collection_attribute_uri="https://example.test/devices",
    )
    binding = SimpleNamespace(search_attribute_uri=search_uri, handler=handler)
    monkeypatch.setattr(value_events, "get_handler_bindings_for_catalog", lambda uri: (binding,))
    monkeypatch.setattr(
        value_events,
        "get_data_collection_variable_sync_settings",
        lambda uri: SimpleNamespace(devices_attribute_uri=variables_uri),
    )
    monkeypatch.setattr(
        value_events,
        "get_refresh_action",
        lambda catalog, attribute: object() if attribute == refresh_uri else None,
    )
    monkeypatch.setattr(
        value_events,
        "get_refresh_actions_for_source",
        lambda catalog, attribute: (object(),) if attribute == source_uri else (),
    )
    monkeypatch.setattr(
        value_events,
        "get_refresh_actions_for_input",
        lambda catalog, attribute: (object(),) if attribute == input_uri else (),
    )

    def stage_names(attribute_uri, *, external_id="", is_empty=True):
        instance = SimpleNamespace(
            project=SimpleNamespace(catalog=SimpleNamespace(uri=catalog_uri)),
            attribute=SimpleNamespace(uri=attribute_uri),
            external_id=external_id,
            is_empty=is_empty,
        )
        return [name for name, _ in value_events._save_stages(instance, "token")]

    assert stage_names(search_uri) == ["backend-value", "configuration-tab", "orphaned-device-details"]
    assert stage_names(configuration_uri) == ["configuration-tab"]
    assert stage_names(selected_uri) == ["selected-device-details"]
    assert stage_names(variables_uri) == ["data-collection-variables"]
    assert stage_names(refresh_uri) == ["metadata-refresh"]
    assert stage_names(source_uri) == ["metadata-source-state"]
    assert stage_names(source_uri, external_id="sms:1") == []
    assert stage_names(input_uri) == ["metadata-input-state"]
    assert stage_names("https://example.test/unrelated") == []


def test_scalar_scope_resolver_reuses_one_answer_tree(monkeypatch):
    catalog = SimpleNamespace(prefetch_elements=Mock())
    values = Mock()
    values.filter.return_value.select_related.return_value = [SimpleNamespace()]
    project = SimpleNamespace(catalog=catalog, values=values)
    instance = SimpleNamespace(
        project=project,
        attribute_id=11,
        set_prefix=None,
        set_index=2,
    )
    answer_tree = object()
    answer_tree_factory = Mock(return_value=answer_tree)
    scope_lookup = Mock(side_effect=lambda instance, attribute, answer_tree: [("", attribute.id)])
    monkeypatch.setattr(value_events, "AnswerTree", answer_tree_factory, raising=False)

    from rdmo_sensorsearch.persistence import value_reconciliation

    monkeypatch.setattr(value_reconciliation, "AnswerTree", answer_tree_factory)
    monkeypatch.setattr(value_reconciliation, "_scalar_scopes_via_answer_tree", scope_lookup)
    resolver = value_reconciliation._ScalarScopeResolver(instance)
    first_attribute = SimpleNamespace(id=21)
    second_attribute = SimpleNamespace(id=22)

    assert resolver.resolve(instance, first_attribute) == [("", 21)]
    assert resolver.resolve(instance, first_attribute) == [("", 21)]
    assert resolver.resolve(instance, second_attribute) == [("", 22)]

    catalog.prefetch_elements.assert_called_once_with()
    values.filter.assert_called_once_with(snapshot=None)
    answer_tree_factory.assert_called_once_with(catalog, [SimpleNamespace()])
    assert scope_lookup.call_count == 2


@pytest.mark.django_db
def test_mirror_catalog_imports_with_plugin_dev_attribute_root():
    elements, errors = parse_xml_to_elements(MIRROR_CATALOG_PATH)

    assert errors == []
    imported_elements = import_elements(elements)
    assert all(not element[ImportElementFields.ERRORS] for element in imported_elements)

    plugin_dev_root = Attribute.objects.get(uri=PLUGIN_DEV_ATTRIBUTE_URI)
    assert Attribute.objects.get(uri=PROJECT_LEAD_ATTRIBUTE_URI).parent == plugin_dev_root
