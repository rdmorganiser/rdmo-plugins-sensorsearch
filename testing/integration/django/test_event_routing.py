from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from django.test import override_settings

from rdmo.projects.models import Value

from rdmo_sensorsearch.config import clear_config_cache
from rdmo_sensorsearch.handlers import catalog_registry
from rdmo_sensorsearch.services.refresh import RefreshAction, RefreshKind
from rdmo_sensorsearch.services.synchronization_context import mute_value_sync
from rdmo_sensorsearch.signals import receivers
from rdmo_sensorsearch.workflows import event_routing
from testing.paths import FIXTURES_ROOT
from testing.performance.fixtures import make_workload


def test_routing_includes_all_stage_inputs_and_wildcards(monkeypatch):
    bindings = [
        SimpleNamespace(
            search_attribute_uri="search",
            handler=SimpleNamespace(
                configuration_collection_attribute_uri="root",
                selected_devices_attribute_uri="selected",
            ),
        )
    ]
    monkeypatch.setattr(
        event_routing,
        "load_config_model",
        lambda: SimpleNamespace(
            data_collection_variable_sync=SimpleNamespace(catalogs=()),
            metadata_refresh=SimpleNamespace(
                actions=(SimpleNamespace(scope=SimpleNamespace(catalog_uris=("catalog:a", "catalog:b"))),)
            ),
        ),
    )
    monkeypatch.setattr(event_routing, "handler_bindings_by_catalog", lambda: {"*": bindings})
    monkeypatch.setattr(event_routing, "get_handler_bindings_for_catalog", lambda uri: bindings)
    monkeypatch.setattr(
        event_routing,
        "get_data_collection_variable_sync_settings",
        lambda uri: SimpleNamespace(
            devices_attribute_uri="variables",
        ),
    )
    monkeypatch.setattr(
        event_routing,
        "_get_refresh_actions",
        lambda uri: (
            (RefreshAction(RefreshKind.DEVICE, "trigger", "configuration", "device", input_attribute_uris=("input",)),)
            if uri != "*"
            else ()
        ),
    )
    event_routing.routing_attributes.cache_clear()
    try:
        for catalog in ("catalog:a", "catalog:b"):
            assert event_routing.routing_attributes()[catalog] == {
                "search",
                "root",
                "selected",
                "variables",
                "trigger",
                "device",
                "input",
            }
        assert event_routing.is_relevant_attribute("unknown", "selected")
        assert not event_routing.is_relevant_attribute("unknown", "trigger")
        with pytest.raises(TypeError):
            event_routing.routing_attributes()["other"] = frozenset()
    finally:
        event_routing.routing_attributes.cache_clear()


def test_configuration_reload_resets_routing_and_handler_instances():
    clear_config_cache()
    try:
        initial = event_routing.routing_attributes()
        initial_handlers = catalog_registry.handler_bindings_by_catalog()
        with override_settings(SENSORSEARCH_CONFIG_FILE_PATH=str(FIXTURES_ROOT / "sensorsearch-plugin-dev.toml")):
            clear_config_cache()
            mirror = event_routing.routing_attributes()
            assert mirror is not initial
            assert catalog_registry.handler_bindings_by_catalog() is not initial_handlers
            assert "https://example.com/terms/questions/plugin-dev/sensorsearch" in mirror
    finally:
        clear_config_cache()


@pytest.mark.django_db
def test_routing_uses_current_database_ids_and_catalog(monkeypatch, django_assert_num_queries):
    workload = make_workload(1)
    attribute = workload.attributes["search"]
    configured_uri = attribute.uri
    monkeypatch.setattr(
        event_routing,
        "routing_attributes",
        lambda: {
            "*": frozenset(),
            workload.catalog.uri: {configured_uri},
        },
    )
    value = Value.objects.get(project=workload.project, attribute=attribute)
    with django_assert_num_queries(2):
        assert event_routing.route_value(value) == (workload.catalog.uri, attribute.uri)
    value.project = workload.project
    value.attribute = attribute
    with django_assert_num_queries(0):
        assert event_routing.route_value(value) == (workload.catalog.uri, attribute.uri)
    attribute.key = "renamed"
    attribute.save()
    # No database-ID cache may retain the old routing decision.
    value = Value.objects.get(pk=value.pk)
    assert event_routing.route_value(value) is None


@pytest.mark.django_db
def test_snapshot_and_muted_events_skip_routing(monkeypatch):
    route = Mock(side_effect=AssertionError("must not route"))
    monkeypatch.setattr(receivers, "route_value", route)
    value = SimpleNamespace(snapshot_id=1, pk=1)
    receivers.value_saved(Value, value, raw=False)
    receivers.value_deleted(Value, value)
    value.snapshot_id = None
    with mute_value_sync():
        receivers.value_saved(Value, value, raw=False)
        receivers.value_deleted(Value, value)
    route.assert_not_called()


@pytest.mark.django_db
def test_broken_early_routing_preserves_robust_callback(monkeypatch, django_capture_on_commit_callbacks):
    monkeypatch.setattr(receivers, "route_value", Mock(side_effect=ValueError("invalid configuration")))
    monkeypatch.setattr(receivers, "get_sms_auth_token", lambda: None)
    handler = Mock()
    monkeypatch.setattr(receivers, "handle_value_saved", handler)
    with django_capture_on_commit_callbacks(execute=True):
        receivers.value_saved(Value, SimpleNamespace(snapshot_id=None, pk=17), raw=False)
    handler.assert_called_once_with(value_id=17, auth_token=None)
