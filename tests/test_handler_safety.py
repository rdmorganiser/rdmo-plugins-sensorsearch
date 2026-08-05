import sys
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from importlib import import_module
from pathlib import Path
from threading import Lock
from time import sleep
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

    workflows = sys.modules.setdefault("rdmo_sensorsearch.workflows", ModuleType("rdmo_sensorsearch.workflows"))
    workflows.__path__ = [str(Path(__file__).parents[1] / "rdmo_sensorsearch" / "workflows")]
    device_details = ModuleType("rdmo_sensorsearch.workflows.device_details")

    device_details.reconcile_device_details_from_selected_devices = lambda **kwargs: None
    sys.modules.setdefault("rdmo_sensorsearch.workflows.device_details", device_details)

    project_values = ModuleType("rdmo_sensorsearch.project_values")
    project_values.get_scoped_project_value = lambda instance, attribute_uri: None
    sys.modules.setdefault("rdmo_sensorsearch.project_values", project_values)

    handlers = sys.modules.setdefault("rdmo_sensorsearch.handlers", ModuleType("rdmo_sensorsearch.handlers"))
    handlers.__path__ = [str(Path(__file__).parents[1] / "rdmo_sensorsearch" / "handlers")]


_install_host_application_stubs()

client = import_module("rdmo_sensorsearch.client")
handler_base = import_module("rdmo_sensorsearch.handlers.base")
catalog_registry_module = import_module("rdmo_sensorsearch.handlers.catalog_registry")
configuration_period = import_module("rdmo_sensorsearch.handlers.configuration_period")
o2a_item_handler_module = import_module("rdmo_sensorsearch.handlers.o2a_item")
o2a_mission_handler_module = import_module("rdmo_sensorsearch.handlers.o2a_mission")
sms_device_handler_module = import_module("rdmo_sensorsearch.handlers.sms_device")
sms_configuration_handler_module = import_module("rdmo_sensorsearch.handlers.sms_configuration")


class FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_catalog_handler_registry_builds_without_signal_import_cycle(monkeypatch):
    monkeypatch.setattr(catalog_registry_module, "_HANDLER_BINDINGS_BY_CATALOG", None)

    bindings_by_catalog = catalog_registry_module.handler_bindings_by_catalog()

    assert bindings_by_catalog
    assert "rdmo_sensorsearch.signals.device_detail_sync" not in sys.modules


def test_handler_builds_authoritative_values_for_its_complete_ownership():
    handler = sms_device_handler_module.SensorManagementSystemDeviceHandler(
        attribute_mapping={
            "data.attributes.name": "attribute:name",
            "included[].attributes.unit": "attribute:units",
        },
        managed_attribute_uris=["attribute:link"],
        base_url="https://sms.example/api",
    )

    values = handler.build_authoritative_mapped_values(
        {
            "attribute:name": "Sensor",
        }
    )

    assert values == {
        "attribute:name": "Sensor",
        "attribute:units": [],
        "attribute:link": None,
    }


def test_handler_authoritative_values_honor_scope_exclusions():
    handler = sms_device_handler_module.SensorManagementSystemDeviceHandler(
        attribute_mapping={"data.attributes.name": "attribute:name"},
        managed_attribute_uris=["attribute:scoped"],
        base_url="https://sms.example/api",
    )

    values = handler.build_authoritative_mapped_values(
        {
            "attribute:name": "Sensor",
            "attribute:scoped": "2026-07-27",
        },
        excluded_attribute_uris={"attribute:scoped"},
    )

    assert values == {"attribute:name": "Sensor"}


def test_collection_values_are_deduplicated_by_external_id_in_input_order():
    first = {"external_id": "ufzsms:483", "text": "First label"}
    duplicate = {"external_id": "ufzsms:483", "text": "Duplicate label"}
    without_external_id = {"external_id": "", "text": "Manual value"}

    values = handler_base.deduplicate_collection_values(
        (first, duplicate, without_external_id),
    )

    assert values == (first, without_external_id)


def test_user_agent_does_not_duplicate_itself_when_email_is_configured(monkeypatch):
    monkeypatch.setattr(client.settings, "DEFAULT_FROM_EMAIL", "admin@example.com", raising=False)
    client.get_user_agent.cache_clear()

    user_agent = client.get_user_agent()

    assert user_agent.count("rdmo/test SensorSearch Plugin") == 1
    assert user_agent.endswith(" (admin@example.com)")
    client.get_user_agent.cache_clear()


def test_request_scope_reuses_responses_without_sharing_mutations(monkeypatch):
    calls = []

    def get(url, headers, timeout):
        calls.append(url)
        return FakeResponse({"records": []})

    monkeypatch.setattr(client.requests, "get", get)

    with client.deduplicate_json_requests():
        first = client.fetch_json("https://api.example/units")
        first["records"].append({"code": "m"})
        second = client.fetch_json("https://api.example/units")

    assert second == {"records": []}
    assert calls == ["https://api.example/units"]


def test_request_scope_deduplicates_concurrent_requests_in_copied_contexts(monkeypatch):
    calls = 0
    calls_lock = Lock()

    def get(url, headers, timeout):
        nonlocal calls
        with calls_lock:
            calls += 1
        sleep(0.02)
        return FakeResponse({"records": [{"code": "m"}]})

    monkeypatch.setattr(client.requests, "get", get)

    with client.deduplicate_json_requests(), ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(
                copy_context().run,
                client.fetch_json,
                "https://api.example/units",
            )
            for _ in range(4)
        ]
        results = [future.result() for future in futures]

    assert results == [{"records": [{"code": "m"}]}] * 4
    assert calls == 1


def test_o2a_device_refresh_fails_when_an_auxiliary_request_fails(monkeypatch):
    responses = iter(
        (
            {"id": 42},
            {"errors": ["contacts unavailable"]},
            {"records": []},
            {"records": []},
        )
    )
    monkeypatch.setattr(o2a_item_handler_module, "fetch_json", lambda url: next(responses))
    handler = o2a_item_handler_module.O2ARegistryItemHandler(attribute_mapping={})

    result = handler.handle("42")

    assert result == {"errors": ["O2A contacts request for item 42 failed: contacts unavailable"]}


def test_sms_device_refresh_fails_when_contact_request_fails(monkeypatch):
    responses = iter(
        (
            {"data": {"links": {}}, "included": []},
            {"errors": ["contacts unavailable"]},
        )
    )
    monkeypatch.setattr(sms_device_handler_module, "fetch_json", lambda url, auth_token=None: next(responses))
    handler = sms_device_handler_module.SensorManagementSystemDeviceHandler(
        attribute_mapping={},
        base_url="https://sms.example/api",
    )

    result = handler.handle("7")

    assert result == {"errors": ["contacts unavailable"]}


def test_sms_device_refresh_maps_mount_height_depth_and_site(monkeypatch):
    device_action = {
        "type": "device_mount_action",
        "id": "647",
        "attributes": {
            "begin_date": "2020-08-25T12:00:00Z",
            "end_date": None,
            "offset_z": 50,
            "z": None,
        },
        "relationships": {
            "configuration": {"data": {"type": "configuration", "id": "27"}},
            "device": {"data": {"type": "device", "id": "607"}},
            "parent_device": {"data": None},
            "parent_platform": {"data": None},
        },
    }

    def fetch_json(url, auth_token=None):
        if "/devices/607/device-mount-actions" in url:
            return {"data": [device_action]}
        if "/device-mount-actions?" in url:
            return {"data": [device_action]}
        if "/platform-mount-actions?" in url:
            return {"data": []}
        if "/static-location-actions?" in url:
            return {
                "data": [
                    {
                        "type": "configuration_static_location_action",
                        "id": "14",
                        "attributes": {
                            "begin_date": "1972-12-01T00:00:00Z",
                            "end_date": None,
                            "z": 110,
                            "label": "Wettermast_CN",
                        },
                    }
                ]
            }
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(sms_device_handler_module, "fetch_json", fetch_json)
    handler = sms_device_handler_module.SensorManagementSystemDeviceHandler(
        attribute_mapping={},
        base_url="https://sms.example/api",
    )
    monkeypatch.setattr(
        handler,
        "_resolve_configuration_external_id",
        lambda instance: "kitcfg:27",
    )
    mapped_values = {}

    errors = handler._set_mount_metadata(mapped_values, "607", instance=object())

    assert errors == []
    assert mapped_values[sms_device_handler_module.INSTRUMENT_START_ATTRIBUTE_URI] == "2020-08-25 12:00"
    assert mapped_values[sms_device_handler_module.INSTRUMENT_END_ATTRIBUTE_URI] == ""
    assert mapped_values[sms_device_handler_module.INSTRUMENT_LOCATION_AMSL_ATTRIBUTE_URI] == 160
    assert mapped_values[sms_device_handler_module.SURFACE_OFFSET_Z_ATTRIBUTE_URI] == 50
    assert mapped_values[sms_device_handler_module.SITE_NAME_ATTRIBUTE_URI] == "Wettermast_CN"


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

    monkeypatch.setattr(sms_configuration_handler_module, "fetch_json", fetch_json)
    handler = sms_configuration_handler_module.SensorManagementSystemConfigurationHandler(
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


def test_sms_configuration_member_uses_compact_configuration_label():
    handler = sms_configuration_handler_module.SensorManagementSystemConfigurationHandler(
        attribute_mapping={},
        id_prefix="kitcfg",
        device_text_prefix="KIT Sensor",
    )

    assert (
        handler._format_device_text(
            configuration_id="49",
            device_id="327",
            attrs={
                "long_name": "SMT100",
                "serial_number": "SMTEB23",
            },
        )
        == "KIT Cfg(49) KIT Sensor(327): SMT100 (s/n: SMTEB23)"
    )


def test_sms_configuration_member_includes_derived_vertical_location():
    handler = sms_configuration_handler_module.SensorManagementSystemConfigurationHandler(
        attribute_mapping={},
        id_prefix="kitcfg",
        device_id_prefix="kitsms",
    )
    platform_action = {
        "type": "platform_mount_action",
        "id": "20",
        "attributes": {
            "begin_date": "2025-01-01T00:00:00Z",
            "end_date": None,
            "offset_z": 10,
            "z": None,
        },
        "relationships": {
            "platform": {"data": {"type": "platform", "id": "84"}},
            "parent_platform": {"data": None},
        },
    }
    device_action = {
        "type": "device_mount_action",
        "id": "21",
        "attributes": {
            "begin_date": "2025-01-01T00:00:00Z",
            "end_date": None,
            "offset_z": -2,
            "z": None,
        },
        "relationships": {
            "device": {"data": {"type": "device", "id": "327"}},
            "parent_platform": {"data": {"type": "platform", "id": "84"}},
            "parent_device": {"data": None},
        },
    }

    values, errors = handler._build_selected_device_values(
        configuration_data={"data": {"id": "49"}},
        mount_action_data={
            "data": [device_action],
            "included": [
                {
                    "type": "device",
                    "id": "327",
                    "attributes": {"long_name": "SMT100", "serial_number": "SMTEB23"},
                }
            ],
        },
        platform_mount_action_data={"data": [platform_action]},
        static_location_action_data={
            "data": [
                {
                    "type": "configuration_static_location_action",
                    "id": "10",
                    "attributes": {
                        "begin_date": "2020-01-01T00:00:00Z",
                        "end_date": None,
                        "z": 100,
                        "label": "Test site",
                    },
                }
            ]
        },
    )

    assert errors == []
    assert values[0]["height_amsl"] == 108
    assert values[0]["vertical_surface_offset"] == 8
    assert values[0]["site_name"] == "Test site"


def test_sms_configuration_period_supports_an_optional_end_and_exclusive_unmount_boundary():
    handler = sms_configuration_handler_module.SensorManagementSystemConfigurationHandler(
        attribute_mapping={},
        id_prefix="kitcfg",
    )
    period, error = configuration_period.parse_configuration_period("2025-01-01 12:00", None)

    assert error is None
    assert period is not None
    assert period.start.isoformat() == "2025-01-01T12:00:00+00:00"
    assert period.end is None
    assert (
        handler._is_mount_action_in_period(
            {
                "attributes": {
                    "begin_date": "2024-01-01T00:00:00Z",
                    "end_date": "2025-01-01T12:00:00Z",
                }
            },
            period,
        )
        is False
    )
    assert (
        handler._is_mount_action_in_period(
            {
                "attributes": {
                    "begin_date": "2025-01-01T12:00:00Z",
                    "end_date": None,
                }
            },
            period,
        )
        is True
    )


def test_configuration_period_validation_fails_closed():
    period, error = configuration_period.parse_configuration_period(None, None)
    assert period is None
    assert "start date" in error

    period, error = configuration_period.parse_configuration_period("not a date", None)
    assert period is None
    assert "start date is invalid" in error

    period, error = configuration_period.parse_configuration_period(
        "2025-02-01 00:00",
        "2025-01-01 00:00",
    )
    assert period is None
    assert "end date must not be earlier" in error


def test_configuration_period_workflow_depends_on_the_catalog_trigger():
    trigger = SimpleNamespace(
        attribute=SimpleNamespace(uri=configuration_period.APPLY_DATE_RANGE_ATTRIBUTE_URI),
        elements=[],
    )
    nested_questionset = SimpleNamespace(attribute=None, elements=[trigger])
    catalog = SimpleNamespace(
        pages=[SimpleNamespace(attribute=None, elements=[nested_questionset])],
        prefetch_elements=lambda: None,
    )
    instance = SimpleNamespace(project=SimpleNamespace(catalog=catalog))

    assert configuration_period.catalog_has_date_range_trigger(instance) is True

    catalog.pages = [SimpleNamespace(attribute=None, elements=[])]
    assert configuration_period.catalog_has_date_range_trigger(instance) is False


def test_sms_configuration_range_selects_latest_mount_and_location_within_range():
    handler = sms_configuration_handler_module.SensorManagementSystemConfigurationHandler(
        attribute_mapping={},
        id_prefix="kitcfg",
        device_id_prefix="kitsms",
    )

    def device_action(action_id, device_id, begin_date, end_date, offset_z):
        return {
            "type": "device_mount_action",
            "id": action_id,
            "attributes": {
                "begin_date": begin_date,
                "end_date": end_date,
                "offset_z": offset_z,
                "z": None,
            },
            "relationships": {
                "device": {"data": {"type": "device", "id": device_id}},
                "parent_platform": {"data": None},
                "parent_device": {"data": None},
            },
        }

    older_mount = device_action(
        "old",
        "327",
        "2024-01-01T00:00:00Z",
        "2025-02-01T00:00:00Z",
        1,
    )
    latest_mount = device_action(
        "latest",
        "327",
        "2025-03-01T00:00:00Z",
        None,
        2,
    )
    future_mount = device_action(
        "future",
        "999",
        "2026-01-01T00:00:00Z",
        None,
        3,
    )
    period, error = configuration_period.parse_configuration_period(
        "2025-01-01 00:00",
        "2025-06-30 23:59",
    )
    assert error is None

    values, errors = handler._build_selected_device_values(
        configuration_data={"data": {"id": "49"}},
        mount_action_data={
            "data": [older_mount, latest_mount, future_mount],
            "included": [
                {
                    "type": "device",
                    "id": "327",
                    "attributes": {"long_name": "Selected sensor"},
                },
                {
                    "type": "device",
                    "id": "999",
                    "attributes": {"long_name": "Future sensor"},
                },
            ],
        },
        platform_mount_action_data={"data": []},
        static_location_action_data={
            "data": [
                {
                    "id": "range",
                    "attributes": {
                        "begin_date": "2025-04-01T00:00:00Z",
                        "end_date": "2025-09-01T00:00:00Z",
                        "z": 200,
                        "label": "Range site",
                    },
                },
                {
                    "id": "current",
                    "attributes": {
                        "begin_date": "2025-09-01T00:00:00Z",
                        "end_date": None,
                        "z": 300,
                        "label": "Current site",
                    },
                },
            ]
        },
        configuration_period=period,
    )

    assert errors == []
    assert [value["external_id"] for value in values] == ["kitsms:327"]
    assert values[0]["instrument_start"] == "2025-03-01 00:00"
    assert values[0]["height_amsl"] == 202
    assert values[0]["vertical_surface_offset"] == 2
    assert values[0]["site_name"] == "Range site"


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
        if "/platform-mount-actions?" in url or "/static-location-actions?" in url:
            return {"data": [], "included": []}
        if "/devices/327" in url:
            return {"errors": ["device unavailable"]}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(sms_configuration_handler_module, "fetch_json", fetch_json)
    handler = sms_configuration_handler_module.SensorManagementSystemConfigurationHandler(
        attribute_mapping={},
        base_url="https://sms.example/api",
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
    )

    result = handler.handle("49")

    assert result == {"errors": ["SMS device request for mounted device 327 failed: device unavailable"]}


def test_sms_configuration_refresh_can_preserve_the_current_device_set(monkeypatch):
    requested_urls = []

    def fetch_json(url, auth_token=None):
        requested_urls.append(url)
        if "/configurations/49" in url:
            return {
                "data": {
                    "id": "49",
                    "attributes": {
                        "description": "Updated",
                        "start_date": "2020-01-01T00:00:00Z",
                        "end_date": "2030-01-01T00:00:00Z",
                    },
                    "links": {},
                }
            }
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(sms_configuration_handler_module, "fetch_json", fetch_json)
    handler = sms_configuration_handler_module.SensorManagementSystemConfigurationHandler(
        attribute_mapping={
            "data.attributes.description": "configuration:description",
            "data.attributes.start_date": "configuration:start",
            "data.attributes.end_date": "configuration:end",
        },
        base_url="https://sms.example/api",
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
        period_start_attribute_uri="configuration:start",
        period_end_attribute_uri="configuration:end",
    )

    result = handler.handle(
        "49",
        context=handler_base.HandlerExecutionContext(preserve_existing_collections=True),
    )

    assert result == handler_base.HandlerResult(
        mapped_values={"configuration:description": "Updated"},
    )
    assert requested_urls == ["https://sms.example/api/configurations/49"]


def test_sms_configuration_defers_device_assignments_until_the_period_is_applied(monkeypatch):
    requested_urls = []

    def fetch_json(url, auth_token=None):
        requested_urls.append(url)
        return {"data": {"id": "49", "attributes": {"description": "Configuration"}, "links": {}}}

    monkeypatch.setattr(sms_configuration_handler_module, "fetch_json", fetch_json)
    monkeypatch.setattr(
        sms_configuration_handler_module,
        "catalog_has_date_range_trigger",
        lambda instance: True,
    )
    monkeypatch.setattr(
        sms_configuration_handler_module,
        "read_configuration_period",
        lambda instance, start_uri, end_uri: (None, "Enter a configuration start date."),
    )
    handler = sms_configuration_handler_module.SensorManagementSystemConfigurationHandler(
        attribute_mapping={"data.attributes.description": "configuration:description"},
        base_url="https://sms.example/api",
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
        period_start_attribute_uri="configuration:start",
        period_end_attribute_uri="configuration:end",
    )

    result = handler.handle("49", instance=SimpleNamespace())

    assert result == handler_base.HandlerResult(
        mapped_values={"configuration:description": "Configuration"},
        collections=(
            handler_base.CollectionAssignment(
                attribute_uri="selected-devices",
                page_uri="device-page",
                values=(),
            ),
        ),
    )
    assert requested_urls == ["https://sms.example/api/configurations/49"]


def test_sms_configuration_without_apply_trigger_syncs_immediately_without_a_period(monkeypatch):
    requested_urls = []

    def fetch_json(url, auth_token=None):
        requested_urls.append(url)
        if "/configurations/49" in url:
            return {"data": {"id": "49", "attributes": {"description": "Configuration"}, "links": {}}}
        if any(
            endpoint in url
            for endpoint in (
                "/device-mount-actions?",
                "/platform-mount-actions?",
                "/static-location-actions?",
            )
        ):
            return {"data": [], "included": []}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(sms_configuration_handler_module, "fetch_json", fetch_json)
    monkeypatch.setattr(
        sms_configuration_handler_module,
        "read_configuration_period",
        lambda *args: (_ for _ in ()).throw(AssertionError("The period must not be read")),
    )
    handler = sms_configuration_handler_module.SensorManagementSystemConfigurationHandler(
        attribute_mapping={"data.attributes.description": "configuration:description"},
        base_url="https://sms.example/api",
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
        period_start_attribute_uri="configuration:start",
        period_end_attribute_uri="configuration:end",
    )
    catalog = SimpleNamespace(pages=[], prefetch_elements=lambda: None)

    result = handler.handle(
        "49",
        instance=SimpleNamespace(project=SimpleNamespace(catalog=catalog)),
    )

    assert result == handler_base.HandlerResult(
        mapped_values={"configuration:description": "Configuration"},
        collections=(
            handler_base.CollectionAssignment(
                attribute_uri="selected-devices",
                page_uri="device-page",
                values=(),
            ),
        ),
    )
    assert any("/device-mount-actions?" in url for url in requested_urls)


def test_sms_apply_date_range_fails_closed_when_the_period_is_invalid(monkeypatch):
    monkeypatch.setattr(
        sms_configuration_handler_module,
        "fetch_json",
        lambda url, auth_token=None: {"data": {"id": "49", "attributes": {}, "links": {}}},
    )
    monkeypatch.setattr(
        sms_configuration_handler_module,
        "read_configuration_period",
        lambda instance, start_uri, end_uri: (None, "The end date must not be earlier than the start date."),
    )
    handler = sms_configuration_handler_module.SensorManagementSystemConfigurationHandler(
        attribute_mapping={},
        base_url="https://sms.example/api",
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
        period_start_attribute_uri="configuration:start",
        period_end_attribute_uri="configuration:end",
    )

    result = handler.handle(
        "49",
        instance=SimpleNamespace(),
        context=handler_base.HandlerExecutionContext(require_configuration_period=True),
    )

    assert result == {"errors": ["The end date must not be earlier than the start date."]}


def test_o2a_mission_collection_fetches_every_page(monkeypatch):
    requested_urls = []

    def fetch_json(url):
        requested_urls.append(url)
        if "offset=0" in url:
            return {"records": [{"id": "1", "itemId": 10}, {"id": "2", "itemId": 11}]}
        return {"records": [{"id": "3", "itemId": 12}]}

    monkeypatch.setattr(o2a_mission_handler_module, "fetch_json", fetch_json)
    handler = o2a_mission_handler_module.O2ARegistryMissionHandler(
        attribute_mapping={},
        mission_item_page_size=2,
    )

    result = handler._fetch_mission_items("30")

    assert [item["id"] for item in result["records"]] == ["1", "2", "3"]
    assert len(requested_urls) == 2


def test_o2a_mission_member_uses_compact_mission_label():
    handler = o2a_mission_handler_module.O2ARegistryMissionHandler(attribute_mapping={})

    assert (
        handler._format_item_text(
            mission_id="30",
            mission_data={"name": "HYDREX"},
            mission_item={"id": "100", "itemId": 4152},
            item_data={
                "id": 4152,
                "longName": "SST_CTD_519",
                "serialNumber": "519",
            },
        )
        == "O2A M(30) O2A Item(4152): SST_CTD_519 (s/n: 519)"
    )


def test_o2a_mission_refresh_aborts_when_a_member_cannot_be_resolved(monkeypatch):
    def fetch_json(url):
        if url.endswith("/missions/30"):
            return {"name": "Mission"}
        if "/missions/30/items" in url:
            return {"records": [{"id": "1", "itemId": 4152}]}
        if url.endswith("/items/4152"):
            return {"errors": ["item unavailable"]}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(o2a_mission_handler_module, "fetch_json", fetch_json)
    handler = o2a_mission_handler_module.O2ARegistryMissionHandler(
        attribute_mapping={},
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
    )

    result = handler.handle("30")

    assert result == {"errors": ["O2A item request for mission item 4152 failed: item unavailable"]}


def test_o2a_mission_refresh_can_preserve_the_current_device_set(monkeypatch):
    requested_urls = []

    def fetch_json(url):
        requested_urls.append(url)
        if url.endswith("/missions/30"):
            return {
                "name": "Updated mission",
                "startDate": "2020-01-01T00:00:00Z",
                "endDate": "2030-01-01T00:00:00Z",
            }
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(o2a_mission_handler_module, "fetch_json", fetch_json)
    handler = o2a_mission_handler_module.O2ARegistryMissionHandler(
        attribute_mapping={
            "name": "configuration:name",
            "startDate": "configuration:start",
            "endDate": "configuration:end",
        },
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
        period_start_attribute_uri="configuration:start",
        period_end_attribute_uri="configuration:end",
    )

    result = handler.handle(
        "30",
        context=handler_base.HandlerExecutionContext(preserve_existing_collections=True),
    )

    assert result == handler_base.HandlerResult(
        mapped_values={"configuration:name": "Updated mission"},
    )
    assert requested_urls == ["https://registry.o2a-data.de/rest/v2/missions/30"]


def test_o2a_mission_defers_device_assignments_until_the_period_is_applied(monkeypatch):
    requested_urls = []

    def fetch_json(url):
        requested_urls.append(url)
        return {"name": "Mission"}

    monkeypatch.setattr(o2a_mission_handler_module, "fetch_json", fetch_json)
    monkeypatch.setattr(
        o2a_mission_handler_module,
        "catalog_has_date_range_trigger",
        lambda instance: True,
    )
    monkeypatch.setattr(
        o2a_mission_handler_module,
        "read_configuration_period",
        lambda instance, start_uri, end_uri: (None, "Enter a mission start date."),
    )
    handler = o2a_mission_handler_module.O2ARegistryMissionHandler(
        attribute_mapping={"name": "configuration:name"},
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
        period_start_attribute_uri="configuration:start",
        period_end_attribute_uri="configuration:end",
    )

    result = handler.handle("30", instance=SimpleNamespace())

    assert result == handler_base.HandlerResult(
        mapped_values={"configuration:name": "Mission"},
        collections=(
            handler_base.CollectionAssignment(
                attribute_uri="selected-devices",
                page_uri="device-page",
                values=(),
            ),
        ),
    )
    assert requested_urls == ["https://registry.o2a-data.de/rest/v2/missions/30"]


def test_o2a_mission_without_apply_trigger_syncs_immediately_without_a_period(monkeypatch):
    requested_urls = []

    def fetch_json(url):
        requested_urls.append(url)
        if url.endswith("/missions/30"):
            return {"name": "Mission"}
        if "/missions/30/items" in url:
            return {"records": []}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(o2a_mission_handler_module, "fetch_json", fetch_json)
    monkeypatch.setattr(
        o2a_mission_handler_module,
        "read_configuration_period",
        lambda *args: (_ for _ in ()).throw(AssertionError("The period must not be read")),
    )
    handler = o2a_mission_handler_module.O2ARegistryMissionHandler(
        attribute_mapping={"name": "configuration:name"},
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
        period_start_attribute_uri="configuration:start",
        period_end_attribute_uri="configuration:end",
    )
    catalog = SimpleNamespace(pages=[], prefetch_elements=lambda: None)

    result = handler.handle(
        "30",
        instance=SimpleNamespace(project=SimpleNamespace(catalog=catalog)),
    )

    assert result == handler_base.HandlerResult(
        mapped_values={"configuration:name": "Mission"},
        collections=(
            handler_base.CollectionAssignment(
                attribute_uri="selected-devices",
                page_uri="device-page",
                values=(),
            ),
        ),
    )
    assert any("/missions/30/items" in url for url in requested_urls)


def test_o2a_mission_applies_the_user_period_to_its_devices(monkeypatch):
    period, error = configuration_period.parse_configuration_period(
        "2026-07-01 10:00",
        "2026-07-02 12:00",
    )
    assert error is None

    def fetch_json(url):
        if url.endswith("/missions/30"):
            return {"name": "Mission"}
        if "/missions/30/items" in url:
            return {"records": [{"id": "1", "itemId": 4152}]}
        if url.endswith("/items/4152"):
            return {"id": 4152, "longName": "CTD"}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(o2a_mission_handler_module, "fetch_json", fetch_json)
    monkeypatch.setattr(
        o2a_mission_handler_module,
        "read_configuration_period",
        lambda instance, start_uri, end_uri: (period, None),
    )
    handler = o2a_mission_handler_module.O2ARegistryMissionHandler(
        attribute_mapping={},
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
        period_start_attribute_uri="configuration:start",
        period_end_attribute_uri="configuration:end",
    )

    result = handler.handle(
        "30",
        instance=SimpleNamespace(),
        context=handler_base.HandlerExecutionContext(require_configuration_period=True),
    )

    assert result.collections[0].values[0]["instrument_start"] == "2026-07-01 10:00"
    assert result.collections[0].values[0]["instrument_end"] == "2026-07-02 12:00"


def test_o2a_mission_exposes_the_user_period_for_preserved_devices(monkeypatch):
    period, error = configuration_period.parse_configuration_period(
        "2026-07-01 10:00",
        "2026-07-02 12:00",
    )
    assert error is None
    monkeypatch.setattr(
        o2a_mission_handler_module,
        "read_configuration_period",
        lambda instance, start_uri, end_uri: (period, None),
    )
    monkeypatch.setattr(
        o2a_mission_handler_module,
        "catalog_has_date_range_trigger",
        lambda instance: True,
    )
    handler = o2a_mission_handler_module.O2ARegistryMissionHandler(
        attribute_mapping={},
        period_start_attribute_uri="configuration:start",
        period_end_attribute_uri="configuration:end",
    )

    period = handler.get_member_device_period(
        SimpleNamespace(),
        {},
    )

    assert period == ("2026-07-01 10:00", "2026-07-02 12:00")
