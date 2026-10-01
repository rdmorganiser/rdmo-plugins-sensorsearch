"""Tests for aggregate backend search providers."""

import sys
from importlib import import_module
from types import ModuleType, SimpleNamespace

import pytest

from testing.paths import REPOSITORY_ROOT


def _install_host_application_stubs():
    django = sys.modules.setdefault("django", ModuleType("django"))
    django_conf = sys.modules.setdefault("django.conf", ModuleType("django.conf"))
    django_conf.settings = getattr(django_conf, "settings", SimpleNamespace())
    django.conf = django_conf

    django_utils = sys.modules.setdefault("django.utils", ModuleType("django.utils"))
    django_timezone = sys.modules.setdefault("django.utils.timezone", ModuleType("django.utils.timezone"))
    django_timezone.now = lambda: None
    django_module_loading = sys.modules.setdefault(
        "django.utils.module_loading",
        ModuleType("django.utils.module_loading"),
    )
    django_module_loading.import_string = lambda path: None
    django_utils.timezone = django_timezone
    django_utils.module_loading = django_module_loading

    rdmo = sys.modules.setdefault("rdmo", ModuleType("rdmo"))
    rdmo.__version__ = "test"
    rdmo_options = sys.modules.setdefault("rdmo.options", ModuleType("rdmo.options"))
    rdmo_providers = sys.modules.setdefault("rdmo.options.providers", ModuleType("rdmo.options.providers"))
    rdmo_providers.Provider = getattr(rdmo_providers, "Provider", object)
    rdmo_options.providers = rdmo_providers
    rdmo.options = rdmo_options

    rdmo_projects = sys.modules.setdefault("rdmo.projects", ModuleType("rdmo.projects"))
    rdmo_project_models = sys.modules.setdefault("rdmo.projects.models", ModuleType("rdmo.projects.models"))
    rdmo_project_models.Value = getattr(rdmo_project_models, "Value", type("Value", (), {}))
    rdmo_projects.models = rdmo_project_models
    rdmo.projects = rdmo_projects

    sensorsearch_providers = sys.modules.setdefault(
        "rdmo_sensorsearch.providers",
        ModuleType("rdmo_sensorsearch.providers"),
    )
    sensorsearch_providers.__path__ = [str(REPOSITORY_ROOT / "rdmo_sensorsearch" / "providers")]


_install_host_application_stubs()

search_provider = import_module("rdmo_sensorsearch.providers.search")


class FakeQuerySet:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, **lookups):
        return FakeQuerySet(row for row in self.rows if all(row.get(field) == expected for field, expected in lookups.items()))

    def exclude(self, **lookups):
        rows = self.rows
        for lookup, expected in lookups.items():
            field, _, operation = lookup.partition("__")
            if operation == "isnull":
                rows = [row for row in rows if (row.get(field) is None) is not expected]
            elif operation == "exact":
                rows = [row for row in rows if row.get(field) != expected]
            else:
                raise AssertionError(f"Unsupported test lookup: {lookup}")
        return FakeQuerySet(rows)

    def order_by(self, field):
        return FakeQuerySet(sorted(self.rows, key=lambda row: row[field]))

    def values_list(self, *fields):
        return [tuple(row[field] for field in fields) for row in self.rows]


class FakeManager:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, **lookups):
        return FakeQuerySet(self.rows).filter(**lookups)


class FakeBackendProvider:
    def __init__(self, id_prefix, results=None, uses_auth_token=True):
        self.id_prefix = id_prefix
        self.results = results or []
        self.uses_auth_token = uses_auth_token
        self.calls = []

    def get_options(self, project, search, user, site):
        self.calls.append((project, search, user, site))
        return self.results


def _configure_provider(monkeypatch, config_section_name, providers, rows, min_search_len=3):
    monkeypatch.setattr(
        search_provider,
        "load_config_model",
        lambda: SimpleNamespace(
            search_provider=lambda section: SimpleNamespace(
                minimum_search_length=min_search_len, filter_sms_devices_by_selected_configuration=False
            )
        ),
    )
    monkeypatch.setattr(search_provider, "get_config_file_path", lambda: "test-config.toml")
    monkeypatch.setattr(search_provider, "build_provider_instances", lambda key: providers)
    monkeypatch.setattr(search_provider.Value, "objects", FakeManager(rows), raising=False)


@pytest.mark.parametrize(
    ("provider_class", "config_section_name", "external_id", "expected_text"),
    (
        (
            search_provider.DeviceSearchProvider,
            search_provider.DEVICE_SEARCH_CONFIG_SECTION,
            "kitsms:327",
            "KIT Sensor(327): Existing project option",
        ),
        (
            search_provider.ConfigurationSearchProvider,
            search_provider.CONFIGURATION_SEARCH_CONFIG_SECTION,
            "kitcfg:49",
            "KIT Cfg(49): Existing project option",
        ),
    ),
)
def test_exact_project_value_skips_backend_and_auth(
    monkeypatch,
    provider_class,
    config_section_name,
    external_id,
    expected_text,
):
    project = object()
    text = "Existing project option"
    backend = FakeBackendProvider(external_id.split(":", 1)[0])
    _configure_provider(
        monkeypatch,
        config_section_name,
        [backend],
        [{"id": 1, "project": project, "snapshot": None, "text": text, "external_id": external_id}],
    )

    def fail_auth(**kwargs):
        raise AssertionError("Authentication should not be resolved for a project-local match")

    monkeypatch.setattr(search_provider, "get_sms_auth_token", fail_auth)

    options = provider_class().get_options(project, search=text, user=object(), site=object())

    assert options == [{"id": external_id, "text": expected_text}]
    assert backend.calls == []


def test_project_options_are_deduplicated_and_keep_distinct_external_ids(monkeypatch):
    project = object()
    text = "Shared device label"
    backend = FakeBackendProvider("kitsms")
    _configure_provider(
        monkeypatch,
        search_provider.DEVICE_SEARCH_CONFIG_SECTION,
        [backend],
        [
            {"id": 1, "project": project, "snapshot": None, "text": text, "external_id": "kitsms:1"},
            {"id": 2, "project": project, "snapshot": None, "text": text, "external_id": "kitsms:1"},
            {"id": 3, "project": project, "snapshot": None, "text": text, "external_id": "kitsms:2"},
        ],
    )

    options = search_provider.DeviceSearchProvider().get_options(project, search=text)

    assert options == [
        {"id": "kitsms:1", "text": "KIT Sensor(1): Shared device label"},
        {"id": "kitsms:2", "text": "KIT Sensor(2): Shared device label"},
    ]
    assert backend.calls == []


@pytest.mark.parametrize(
    "external_id",
    (
        "unknown:327",
        "kitcfg:49||kitsms:327",
        "",
        None,
    ),
)
def test_invalid_project_match_falls_through_to_backend(monkeypatch, external_id):
    project = object()
    text = "Device search"
    remote_option = {"id": "kitsms:327", "text": "Remote device"}
    backend = FakeBackendProvider("kitsms", [remote_option])
    _configure_provider(
        monkeypatch,
        search_provider.DEVICE_SEARCH_CONFIG_SECTION,
        [backend],
        [{"id": 1, "project": project, "snapshot": None, "text": text, "external_id": external_id}],
    )
    monkeypatch.setattr(search_provider, "get_sms_auth_token", lambda **kwargs: "token")

    options = search_provider.DeviceSearchProvider().get_options(project, search=text)

    assert options == [remote_option]
    assert backend.calls == [(project, text, None, None)]
    assert backend.auth_token == "token"


def test_nonexact_and_snapshot_values_fall_through_to_backend(monkeypatch):
    project = object()
    remote_option = {"id": "kitsms:327", "text": "Remote device"}
    backend = FakeBackendProvider("kitsms", [remote_option])
    _configure_provider(
        monkeypatch,
        search_provider.DEVICE_SEARCH_CONFIG_SECTION,
        [backend],
        [
            {
                "id": 1,
                "project": project,
                "snapshot": None,
                "text": "Different text",
                "external_id": "kitsms:327",
            },
            {
                "id": 2,
                "project": project,
                "snapshot": object(),
                "text": "Device search",
                "external_id": "kitsms:327",
            },
        ],
    )
    monkeypatch.setattr(search_provider, "get_sms_auth_token", lambda **kwargs: None)

    options = search_provider.DeviceSearchProvider().get_options(project, search="Device search")

    assert options == [remote_option]
    assert backend.calls == [(project, "Device search", None, None)]


def test_search_shorter_than_minimum_skips_project_and_backend_queries(monkeypatch):
    project = object()
    backend = FakeBackendProvider("kitsms")
    _configure_provider(
        monkeypatch,
        search_provider.DEVICE_SEARCH_CONFIG_SECTION,
        [backend],
        [{"id": 1, "project": project, "snapshot": None, "text": "ab", "external_id": "kitsms:1"}],
    )
    monkeypatch.setattr(search_provider, "get_sms_auth_token", lambda **kwargs: None)

    options = search_provider.DeviceSearchProvider().get_options(project, search="ab")

    assert options == []
    assert backend.calls == []
