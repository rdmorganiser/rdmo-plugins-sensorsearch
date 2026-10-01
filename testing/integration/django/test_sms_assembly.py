"""Exercise real provider/factory assembly with injected SMS capabilities."""

from types import SimpleNamespace

import pytest

from rdmo_sensorsearch import backend_assembly
from rdmo_sensorsearch.contracts import BackendFailure, BackendSuccess, SearchRecord
from rdmo_sensorsearch.handlers import factory as handler_factory
from rdmo_sensorsearch.providers import factory as provider_factory
from rdmo_sensorsearch.providers.sms_configuration import SensorManagementSystemConfigurationProvider
from rdmo_sensorsearch.providers.sms_device import SensorManagementSystemDeviceProvider


@pytest.mark.parametrize(
    "provider_class,method,attributes,expected",
    [
        (
            SensorManagementSystemDeviceProvider,
            "search_devices",
            {"long_name": "Sensor", "serial_number": "ABC", "status_name": "Active & Ready", "is_public": True},
            {"id": "test:42", "text": "Test(42): Sensor (s/n: ABC)", "help": "Active &amp; Ready | Public"},
        ),
        (
            SensorManagementSystemConfigurationProvider,
            "search_configurations",
            {"label": "Configuration", "project": "Project", "persistent_identifier": "PID"},
            {"id": "test:42", "text": "Test(42): Configuration [Project] (PID)"},
        ),
    ],
)
def test_providers_format_options_using_injected_capabilities(provider_class, method, attributes, expected):
    calls = []

    def search(query, *, limit, auth_token):
        calls.append((query, limit, auth_token))
        return BackendSuccess((SearchRecord("42", attributes),))

    provider = provider_class(backend=SimpleNamespace(**{method: search}), id_prefix="test", text_prefix="Test", max_hits=5)
    provider.auth_token = "token"
    assert provider.get_options(None, search=None) == [] and calls == []
    assert provider.get_options(None, search="Sensor & Configuration") == [expected]
    assert calls == [("Sensor & Configuration", 5, "token")]


@pytest.mark.parametrize(
    "provider_class,method",
    [
        (SensorManagementSystemDeviceProvider, "search_devices"),
        (SensorManagementSystemConfigurationProvider, "search_configurations"),
    ],
)
def test_provider_failure_returns_no_options(provider_class, method):
    backend = SimpleNamespace(**{method: lambda *args, **kwargs: BackendFailure(("Unavailable",))})
    provider = provider_class(backend=backend, id_prefix="test", text_prefix="Test")
    provider.auth_token = "token"
    assert provider.get_options(None, search="Sensor") == []


def test_provider_factory_keeps_resource_urls_and_entry_overrides(monkeypatch):
    requests = []

    def fetch(url, auth_token=None):
        requests.append(url)
        return {"data": []}

    monkeypatch.setattr(backend_assembly, "fetch_json", fetch)
    monkeypatch.setattr(
        provider_factory,
        "load_config",
        lambda: {
            "DeviceSearchProvider": {
                "provider_defaults": {"SensorManagementSystemDeviceProvider": {"max_hits": 5, "text_prefix": "Default"}},
                "providers": {
                    "SensorManagementSystemDeviceProvider": [
                        {
                            "base_url": "https://sms.example/custom/devices",
                            "id_prefix": "test",
                            "max_hits": 2,
                            "query_url": "{base_url}?size={page_size}&query={query}",
                        }
                    ]
                },
            }
        },
    )
    (provider,) = provider_factory.build_provider_instances("DeviceSearchProvider")
    provider.auth_token = "token"
    assert provider.max_hits == 2 and provider.text_prefix == "Default"
    assert provider.get_options(None, search="a & b") == []
    assert requests == ["https://sms.example/custom/devices?size=2&query=a%20%26%20b"]


def test_handler_factory_keeps_catalog_mapping_and_endpoint_overrides(monkeypatch):
    requests = []

    def fetch(url, auth_token=None):
        requests.append(url)
        return (
            {"data": {"attributes": {"long_name": "Sensor", "serial_number": "ABC"}}}
            if "/catalog-device/1" in url
            else {"data": []}
        )

    monkeypatch.setattr(backend_assembly, "fetch_json", fetch)
    config = {
        "handlers": {
            "SensorManagementSystemDeviceHandler": {
                "defaults": {
                    "search_attribute_uri": "search",
                    "contact_url": "{base_url}/contacts/{id}",
                    "attribute_mapping": {"data.attributes.long_name": "name"},
                },
                "backend_defaults": {"base_url": "https://sms.example/api"},
                "backends": [{"id_prefix": "test"}],
                "catalogs": [
                    {
                        "catalog_uri": "catalog",
                        "device_url": "{base_url}/catalog-device/{id}",
                        "attribute_mapping": {"data.attributes.serial_number": "serial"},
                    }
                ],
            }
        }
    }
    monkeypatch.setattr(handler_factory, "load_config", lambda: config)
    (binding,) = handler_factory.build_handlers_by_catalog()["catalog"]
    from rdmo_sensorsearch.contracts import HandlerExecutionContext

    result = binding.handler.handle("1", context=HandlerExecutionContext())
    assert result.mapped_values["name"] == "Sensor" and result.mapped_values["serial"] == "ABC"
    assert binding.id_prefix == "test" and binding.search_attribute_uri == "search"
    assert requests == ["https://sms.example/api/catalog-device/1", "https://sms.example/api/contacts/1"]


def test_handler_factory_preserves_rejection_of_conflicting_constructor_settings(monkeypatch, caplog):
    monkeypatch.setattr(
        handler_factory,
        "load_config",
        lambda: {
            "handlers": {
                "SensorManagementSystemDeviceHandler": {
                    "defaults": {"search_attribute_uri": "search", "incomplete_mount_chain_policy": "strict"},
                    "backend_defaults": {
                        "base_url": "https://sms.example/api",
                        "incomplete_mount_chain_policy": "direct_device_offset",
                    },
                    "backends": [{"id_prefix": "test"}],
                    "catalogs": [{"catalog_uri": "catalog"}],
                }
            }
        },
    )
    assert handler_factory.build_handlers_by_catalog() == {}
    assert "Multiple values for keyword argument 'incomplete_mount_chain_policy'" in caplog.text
