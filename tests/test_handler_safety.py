import sys
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import ModuleType, SimpleNamespace


def _install_host_application_stubs():
    django = sys.modules.setdefault("django", ModuleType("django"))
    django_conf = sys.modules.setdefault("django.conf", ModuleType("django.conf"))
    django_conf.settings = getattr(django_conf, "settings", SimpleNamespace())
    django.conf = django_conf

    django_utils = sys.modules.setdefault("django.utils", ModuleType("django.utils"))
    django_timezone = sys.modules.setdefault("django.utils.timezone", ModuleType("django.utils.timezone"))
    django_timezone.is_aware = lambda value: value.tzinfo is not None
    django_timezone.make_aware = lambda value, timezone: value.replace(tzinfo=timezone)
    django_utils.timezone = django_timezone

    rdmo = sys.modules.setdefault("rdmo", ModuleType("rdmo"))
    rdmo.__version__ = "test"
    rdmo_projects = sys.modules.setdefault("rdmo.projects", ModuleType("rdmo.projects"))
    rdmo_project_models = sys.modules.setdefault("rdmo.projects.models", ModuleType("rdmo.projects.models"))
    rdmo_project_models.Value = getattr(rdmo_project_models, "Value", type("Value", (), {}))
    rdmo_projects.models = rdmo_project_models
    rdmo.projects = rdmo_projects

    device_set_sync = ModuleType("rdmo_sensorsearch.signals.device_set_sync")

    @dataclass(frozen=True)
    class SelectedDevice:
        text: str
        external_id: str
        instrument_start: str | None = None
        instrument_end: str | None = None

    device_set_sync.SelectedDevice = SelectedDevice
    device_set_sync.sync_device_detail_blocks_from_payload = lambda **kwargs: None
    sys.modules.setdefault("rdmo_sensorsearch.signals.device_set_sync", device_set_sync)

    sensorsearch_utils = ModuleType("rdmo_sensorsearch.utils")
    sensorsearch_utils.get_project_value = lambda instance, attribute_uri: None
    sys.modules.setdefault("rdmo_sensorsearch.utils", sensorsearch_utils)

    handlers = sys.modules.setdefault("rdmo_sensorsearch.handlers", ModuleType("rdmo_sensorsearch.handlers"))
    handlers.__path__ = [str(Path(__file__).parents[1] / "rdmo_sensorsearch" / "handlers")]


_install_host_application_stubs()

client = import_module("rdmo_sensorsearch.client")
handler_o2a_registry = import_module("rdmo_sensorsearch.handlers.handler_o2a_registry")
handler_o2a_missions = import_module("rdmo_sensorsearch.handlers.handler_o2a_registry_missions")
handler_sms = import_module("rdmo_sensorsearch.handlers.handler_sms")
handler_sms_configurations = import_module("rdmo_sensorsearch.handlers.handler_sms_configurations")


def test_user_agent_does_not_duplicate_itself_when_email_is_configured(monkeypatch):
    monkeypatch.setattr(client.settings, "DEFAULT_FROM_EMAIL", "admin@example.com", raising=False)
    client.get_user_agent.cache_clear()

    user_agent = client.get_user_agent()

    assert user_agent.count("rdmo/test SensorSearch Plugin") == 1
    assert user_agent.endswith(" (admin@example.com)")
    client.get_user_agent.cache_clear()


def test_o2a_device_refresh_fails_when_an_auxiliary_request_fails(monkeypatch):
    responses = iter(
        (
            {"id": 42},
            {"errors": ["contacts unavailable"]},
            {"records": []},
            {"records": []},
        )
    )
    monkeypatch.setattr(handler_o2a_registry, "fetch_json", lambda url: next(responses))
    handler = handler_o2a_registry.O2ARegistrySearchHandler(attribute_mapping={})

    result = handler.handle("42")

    assert result == {"errors": ["O2A contacts request for item 42 failed: contacts unavailable"]}


def test_sms_device_refresh_fails_when_contact_request_fails(monkeypatch):
    responses = iter(
        (
            {"data": {"links": {}}, "included": []},
            {"errors": ["contacts unavailable"]},
        )
    )
    monkeypatch.setattr(handler_sms, "fetch_json", lambda url, auth_token=None: next(responses))
    handler = handler_sms.SensorManagementSystemHandler(
        attribute_mapping={},
        base_url="https://sms.example/api",
    )

    result = handler.handle("7")

    assert result == {"errors": ["contacts unavailable"]}


def test_sms_configuration_collection_fetches_every_page(monkeypatch):
    requested_urls = []

    def fetch_json(url, auth_token=None):
        requested_urls.append(url)
        if "page[number]=1" in url:
            return {
                "data": [{"type": "device_mount_action", "id": "1"}, {"type": "device_mount_action", "id": "2"}],
                "included": [{"type": "device", "id": "10"}],
            }
        return {
            "data": [{"type": "device_mount_action", "id": "3"}],
            "included": [{"type": "device", "id": "11"}],
        }

    monkeypatch.setattr(handler_sms_configurations, "fetch_json", fetch_json)
    handler = handler_sms_configurations.SensorManagementSystemConfigurationsHandler(
        attribute_mapping={},
        base_url="https://sms.example/api",
    )

    result = handler._fetch_jsonapi_collection(
        handler.device_mount_actions_url,
        "49",
        page_size=2,
    )

    assert [item["id"] for item in result["data"]] == ["1", "2", "3"]
    assert [item["id"] for item in result["included"]] == ["10", "11"]
    assert len(requested_urls) == 2


def test_sms_configuration_refresh_aborts_when_a_member_cannot_be_resolved(monkeypatch):
    def fetch_json(url, auth_token=None):
        if "/configurations/" in url:
            return {"data": {"id": "49", "relationships": {}, "links": {}}}
        if "/device-mount-actions?" in url:
            return {
                "data": [
                    {
                        "id": "1",
                        "attributes": {},
                        "relationships": {"device": {"data": {"type": "device", "id": "327"}}},
                    }
                ],
                "included": [],
            }
        if "/devices/327" in url:
            return {"errors": ["device unavailable"]}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(handler_sms_configurations, "fetch_json", fetch_json)
    handler = handler_sms_configurations.SensorManagementSystemConfigurationsHandler(
        attribute_mapping={},
        base_url="https://sms.example/api",
        member_sensors_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
    )

    result = handler.handle("49")

    assert result == {"errors": ["SMS device request for mounted device 327 failed: device unavailable"]}


def test_o2a_mission_collection_fetches_every_page(monkeypatch):
    requested_urls = []

    def fetch_json(url):
        requested_urls.append(url)
        if "offset=0" in url:
            return {"records": [{"id": "1", "itemId": 10}, {"id": "2", "itemId": 11}]}
        return {"records": [{"id": "3", "itemId": 12}]}

    monkeypatch.setattr(handler_o2a_missions, "fetch_json", fetch_json)
    handler = handler_o2a_missions.O2ARegistryMissionsHandler(
        attribute_mapping={},
        mission_item_max_hits=2,
    )

    result = handler._fetch_mission_items("30")

    assert [item["id"] for item in result["records"]] == ["1", "2", "3"]
    assert len(requested_urls) == 2


def test_o2a_mission_refresh_aborts_when_a_member_cannot_be_resolved(monkeypatch):
    def fetch_json(url):
        if url.endswith("/missions/30"):
            return {"name": "Mission"}
        if "/missions/30/items" in url:
            return {"records": [{"id": "1", "itemId": 4152}]}
        if url.endswith("/items/4152"):
            return {"errors": ["item unavailable"]}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(handler_o2a_missions, "fetch_json", fetch_json)
    handler = handler_o2a_missions.O2ARegistryMissionsHandler(
        attribute_mapping={},
        member_sensors_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
    )

    result = handler.handle("30")

    assert result == {"errors": ["O2A item request for mission item 4152 failed: item unavailable"]}
