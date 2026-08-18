from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rdmo.projects.models import Value

from rdmo_sensorsearch.signals import receivers
from rdmo_sensorsearch.workflows import value_events


def _value(**overrides):
    fields = {
        "pk": 17,
        "snapshot_id": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


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
