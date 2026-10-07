import sys
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from importlib import import_module
from threading import Lock
from time import sleep
from types import ModuleType, SimpleNamespace

import pytest

from testing.paths import REPOSITORY_ROOT


def _install_host_application_stubs():
    django = sys.modules.setdefault("django", ModuleType("django"))
    django_conf = sys.modules.setdefault("django.conf", ModuleType("django.conf"))
    django_conf.settings = getattr(django_conf, "settings", SimpleNamespace())
    django.conf = django_conf

    rdmo = sys.modules.setdefault("rdmo", ModuleType("rdmo"))
    rdmo.__version__ = "test"
    handlers = sys.modules.setdefault("rdmo_sensorsearch.handlers", ModuleType("rdmo_sensorsearch.handlers"))
    handlers.__path__ = [str(REPOSITORY_ROOT / "rdmo_sensorsearch" / "handlers")]


_install_host_application_stubs()

client = import_module("rdmo_sensorsearch.client")
config_module = import_module("rdmo_sensorsearch.config")
contracts = import_module("rdmo_sensorsearch.contracts")
catalog_registry_module = import_module("rdmo_sensorsearch.handlers.catalog_registry")
configuration_period = import_module("rdmo_sensorsearch.services.configuration_period")
o2a_item_handler_module = import_module("rdmo_sensorsearch.handlers.o2a_item")
o2a_mission_handler_module = import_module("rdmo_sensorsearch.handlers.o2a_mission")
backend_assembly = import_module("rdmo_sensorsearch.backend_assembly")
sms_device_backend = import_module("rdmo_sensorsearch.backends.sms.device")
from testing.sms_helpers import make_sms_configuration_handler, make_sms_device_handler, resolve_member_values  # noqa: E402

sms_device_handler_module = import_module("rdmo_sensorsearch.handlers.sms_device")
sms_configuration_handler_module = import_module("rdmo_sensorsearch.handlers.sms_configuration")
sms_configuration_membership_module = import_module("rdmo_sensorsearch.backends.sms.membership")

# Other unit-test modules can import Django before this isolated module is
# collected. Keep these tests independent from Django's global LazySettings in
# either collection order.
settings = SimpleNamespace()
client.settings = settings
config_module.settings = settings


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
    handler = make_sms_device_handler(
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
    handler = make_sms_device_handler(
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
    handler = o2a_item_handler_module.O2ARegistryItemHandler(
        attribute_mapping={},
        id_prefix="o2aregistry",
        base_url="https://registry.o2a-data.de/rest/v2",
    )

    result = handler.handle("42", context=contracts.HandlerExecutionContext())

    assert result == {"errors": ["O2A contacts request for item 42 failed: contacts unavailable"]}


def test_sms_device_refresh_fails_when_contact_request_fails(monkeypatch):
    responses = iter(
        (
            {"data": {"links": {}}, "included": []},
            {"errors": ["contacts unavailable"]},
        )
    )
    monkeypatch.setattr(backend_assembly, "fetch_json", lambda url, auth_token=None: next(responses))
    handler = make_sms_device_handler(
        attribute_mapping={},
        base_url="https://sms.example/api",
    )

    result = handler.handle("7", context=contracts.HandlerExecutionContext())

    assert result == {"errors": ["contacts unavailable"]}


def _owner_role(contact_id, *, role_id="role-1", role_name="Owner"):
    return {
        "type": "device_contact_role",
        "id": role_id,
        "attributes": {"role_name": role_name},
        "relationships": {"contact": {"data": {"type": "contact", "id": contact_id}}},
    }


def _owner_contact(contact_id, organization, *, resource_type="contact"):
    return {
        "type": resource_type,
        "id": contact_id,
        "attributes": {"organization": organization, "family_name": contact_id, "given_name": "Person"},
    }


def _sms_owner_handler():
    return make_sms_device_handler(
        attribute_mapping={
            "sms_owner_organizations": "attribute:owner",
            "included[?type==`contact`].attributes.family_name": "attribute:responsible",
        },
        id_prefix="example-sms",
        base_url="https://sms.example/backend/api/v1",
    )


def test_sms_owner_relationship_join_preserves_other_contact_mappings(monkeypatch):
    roles = [_owner_role("2"), _owner_role("1", role_id="role-2", role_name="PI")]
    contacts = [_owner_contact("1", "Not owner"), _owner_contact("2", "Wrong type", resource_type="device")]
    contacts.extend([_owner_contact("unrelated", "Unrelated"), _owner_contact("2", " Owner institute ")])
    responses = iter([{"data": {"id": "42"}}, {"data": roles, "included": contacts}])
    monkeypatch.setattr(backend_assembly, "fetch_json", lambda url, auth_token=None: next(responses))

    result = _sms_owner_handler().handle("42", context=contracts.HandlerExecutionContext())

    assert result.mapped_values["attribute:owner"] == contracts.AuthoritativeTextScalar(("Owner institute",))
    assert result.mapped_values["attribute:responsible"] == ["1", "unrelated", "2"]
    assert result.notices == ()


def test_sms_owner_names_are_trimmed_deduplicated_and_kept_in_role_order():
    payload = {
        "data": [_owner_role(str(i), role_id=str(i)) for i in range(6)],
        "included": [
            _owner_contact("5", None),
            _owner_contact("4", "  "),
            _owner_contact("3", "Institute A"),
            _owner_contact("2", "Institute B"),
            _owner_contact("1", " Institute A "),
            {"type": "contact", "id": "0", "attributes": {}},
        ],
    }

    assert sms_device_backend.extract_owner_organizations(payload) == (("Institute A", "Institute B"), ())


@pytest.mark.parametrize("reference", [None, {}, {"type": "device", "id": "1"}, {"type": "contact", "id": "absent"}])
def test_sms_unresolved_owner_contacts_return_nonfatal_notices(reference):
    role = _owner_role("1")
    role["relationships"]["contact"]["data"] = reference

    names, notices = sms_device_backend.extract_owner_organizations(
        {"data": [role], "included": [_owner_contact("1", "Institute")]},
        "example-sms:42",
    )

    assert names == ()
    assert notices[0].code == "owner_contact_unresolved"
    assert notices[0].external_id == "example-sms:42"


@pytest.mark.parametrize(
    ("next_link", "expected_next_url"),
    [
        ("/backend/api/v1/roles?page[number]=2", "https://sms.example/backend/api/v1/roles?page[number]=2"),
        (
            "?include=contact&page[number]=2",
            "https://sms.example/backend/api/v1/devices/42/device-contact-roles?include=contact&page[number]=2",
        ),
    ],
)
def test_sms_owner_pagination_joins_contacts_across_pages_and_reuses_authentication(
    monkeypatch,
    next_link,
    expected_next_url,
):
    requests = []
    responses = iter(
        [
            {"data": {"id": "42"}},
            {"data": [_owner_role("1")], "links": {"next": next_link}},
            {
                "data": [_owner_role("2", role_id="role-2")],
                "included": [
                    _owner_contact("2", "Institute B"),
                    _owner_contact("1", "Institute A"),
                ],
            },
        ]
    )

    def fetch(url, auth_token=None):
        requests.append((url, auth_token))
        return next(responses)

    monkeypatch.setattr(backend_assembly, "fetch_json", fetch)
    result = _sms_owner_handler().handle("42", auth_token="test-token", context=contracts.HandlerExecutionContext())

    assert result.mapped_values["attribute:owner"] == contracts.AuthoritativeTextScalar(("Institute A", "Institute B"))
    assert requests == [
        ("https://sms.example/backend/api/v1/devices/42?include=device_properties", "test-token"),
        (
            "https://sms.example/backend/api/v1/devices/42/device-contact-roles?include=contact&page[size]=100&page[number]=1",
            "test-token",
        ),
        (expected_next_url, "test-token"),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"data": {}},
        {"data": [None]},
        {"data": [], "included": {}},
        {"data": [], "included": [{"type": "contact", "id": "1", "attributes": None}]},
    ],
)
def test_sms_malformed_contact_pages_fail_instead_of_returning_authoritative_metadata(monkeypatch, payload):
    responses = iter([{"data": {"id": "42"}}, payload])
    monkeypatch.setattr(backend_assembly, "fetch_json", lambda url, auth_token=None: next(responses))

    assert "errors" in _sms_owner_handler().handle("42", context=contracts.HandlerExecutionContext())


def test_sms_no_owner_returns_an_explicit_clearing_scalar(monkeypatch):
    responses = iter([{"data": {"id": "42"}}, {"data": []}])
    monkeypatch.setattr(backend_assembly, "fetch_json", lambda url, auth_token=None: next(responses))

    assert (
        _sms_owner_handler().handle("42", context=contracts.HandlerExecutionContext()).mapped_values["attribute:owner"]
        == contracts.AuthoritativeTextScalar()
    )


def test_sms_contact_pagination_failure_discards_partial_results(monkeypatch):
    responses = iter(
        [
            {"data": {"id": "42"}},
            {"data": [_owner_role("1")], "included": [_owner_contact("1", "Institute")], "links": {"next": "roles?page=2"}},
            {"errors": ["second page unavailable"]},
        ]
    )
    monkeypatch.setattr(backend_assembly, "fetch_json", lambda url, auth_token=None: next(responses))

    assert _sms_owner_handler().handle("42", context=contracts.HandlerExecutionContext()) == {
        "errors": ["second page unavailable"]
    }


def test_sms_owner_contact_missing_relationship_preserves_other_resolved_owners():
    missing = _owner_role("missing")
    missing.pop("relationships")
    names, notices = sms_device_backend.extract_owner_organizations(
        {
            "data": [missing, _owner_role("1", role_id="role-2")],
            "included": [_owner_contact("1", "Institute")],
        }
    )

    assert names == ("Institute",)
    assert len(notices) == 1 and notices[0].code == "owner_contact_unresolved"


@pytest.mark.parametrize("next_link", ["https://other.example/contacts", "roles?page=1"])
def test_sms_contact_pagination_rejects_other_backends_and_repeated_pages(monkeypatch, next_link):
    calls = []

    def fetch(url, auth_token=None):
        calls.append(url)
        if "/devices/42?" in url:
            return {"data": {"id": "42"}}
        return {"data": [_owner_role("1")], "links": {"next": next_link}}

    monkeypatch.setattr(backend_assembly, "fetch_json", fetch)

    assert "errors" in _sms_owner_handler().handle("42", auth_token="test-token", context=contracts.HandlerExecutionContext())
    assert all(url.startswith("https://sms.example/") for url in calls)
    assert len(calls) <= 3


def test_sms_contact_pagination_limit_discards_incomplete_results(monkeypatch):
    pages = []

    def fetch(url, auth_token=None):
        if "/devices/42?" in url:
            return {"data": {"id": "42"}}
        pages.append(url)
        return {"data": [_owner_role("1", role_id=str(len(pages)))], "links": {"next": "roles?page=next"}}

    monkeypatch.setattr(backend_assembly, "fetch_json", fetch)

    assert _sms_owner_handler().handle("42", context=contracts.HandlerExecutionContext()) == {
        "errors": ["SMS contact roles collection pagination exceeded 100 pages."]
    }
    assert len(pages) == 100


def test_sms_device_refresh_maps_station_height_depth_and_site(monkeypatch):
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

    monkeypatch.setattr(backend_assembly, "fetch_json", fetch_json)
    handler = make_sms_device_handler(
        attribute_mapping={},
        base_url="https://sms.example/api",
    )
    mapped_values = {}

    errors = handler._set_mount_metadata(mapped_values, "607", configuration_external_id="kitcfg:27")

    assert errors == []
    assert mapped_values[sms_device_handler_module.INSTRUMENT_START_ATTRIBUTE_URI] == "2020-08-25 12:00"
    assert mapped_values[sms_device_handler_module.INSTRUMENT_END_ATTRIBUTE_URI] == ""
    assert mapped_values[sms_device_handler_module.INSTRUMENT_LOCATION_AMSL_ATTRIBUTE_URI] == 110
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

    monkeypatch.setattr(backend_assembly, "fetch_json", fetch_json)
    handler = make_sms_configuration_handler(
        attribute_mapping={},
        base_url="https://sms.example/api",
    )

    result = handler.backend._configuration._collection(
        handler.backend._configuration.settings.device_mount_actions_url,
        "49",
        page_size=2,
        auth_token=None,
    )

    assert [item["id"] for item in result.value["data"]] == ["1", "2", "3"]
    assert [item["id"] for item in result.value["included"]] == ["10", "11"]
    assert len(requested_urls) == 2


def test_sms_configuration_member_uses_compact_configuration_label():
    handler = make_sms_configuration_handler(
        attribute_mapping={}, id_prefix="kitcfg", device_id_prefix="kitsms", device_text_prefix="KIT Sensor"
    )
    member = contracts.ConfigurationMember(
        "327", {"long_name": "SMT100", "serial_number": "SMTEB23"}, None, None, contracts.MountLocation()
    )
    assert handler._member_value(member, "49")["text"] == "KIT Cfg(49) KIT Sensor(327): SMT100 (s/n: SMTEB23)"


def test_sms_configuration_member_includes_derived_vertical_location():
    handler = make_sms_configuration_handler(
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

    values, errors = resolve_member_values(
        handler,
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
    assert values[0]["station_height_amsl"] == 100
    assert values[0]["vertical_surface_offset"] == 8
    assert values[0]["site_name"] == "Test site"


def test_sms_configuration_period_supports_an_optional_end_and_exclusive_unmount_boundary():
    period, error = configuration_period.parse_configuration_period("2025-01-01 12:00", None)

    assert error is None
    assert period is not None
    assert period.start.isoformat() == "2025-01-01T12:00:00+00:00"
    assert period.end is None
    assert (
        sms_configuration_membership_module.mount_action_overlaps_period(
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
        sms_configuration_membership_module.mount_action_overlaps_period(
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


def test_sms_configuration_range_selects_latest_mount_and_location_within_range():
    handler = make_sms_configuration_handler(
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

    values, errors = resolve_member_values(
        handler,
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
    assert values[0]["station_height_amsl"] == 200
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

    monkeypatch.setattr(backend_assembly, "fetch_json", fetch_json)
    handler = make_sms_configuration_handler(
        attribute_mapping={},
        base_url="https://sms.example/api",
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
    )

    result = handler.handle("49", context=contracts.HandlerExecutionContext())

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

    monkeypatch.setattr(backend_assembly, "fetch_json", fetch_json)
    handler = make_sms_configuration_handler(
        attribute_mapping={
            "data.attributes.description": "configuration:description",
            "data.attributes.start_date": "configuration:start",
            "data.attributes.end_date": "configuration:end",
        },
        base_url="https://sms.example/api",
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
    )

    result = handler.handle(
        "49",
        context=contracts.HandlerExecutionContext(preserve_existing_collections=True),
    )

    assert result == contracts.HandlerResult(
        mapped_values={
            "configuration:description": "Updated",
            "configuration:start": "2020-01-01 00:00",
            "configuration:end": "2030-01-01 00:00",
        },
    )
    assert requested_urls == ["https://sms.example/api/configurations/49"]


def test_sms_configuration_selection_syncs_immediately_without_a_membership_filter(monkeypatch):
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

    monkeypatch.setattr(backend_assembly, "fetch_json", fetch_json)
    handler = make_sms_configuration_handler(
        attribute_mapping={"data.attributes.description": "configuration:description"},
        base_url="https://sms.example/api",
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
    )

    result = handler.handle("49", context=contracts.HandlerExecutionContext())

    assert result == contracts.HandlerResult(
        mapped_values={"configuration:description": "Configuration"},
        collections=(
            contracts.CollectionAssignment(
                attribute_uri="selected-devices",
                page_uri="device-page",
                values=(),
            ),
        ),
    )
    assert any("/device-mount-actions?" in url for url in requested_urls)


def test_sms_membership_filter_fails_closed_when_the_period_is_invalid(monkeypatch):
    monkeypatch.setattr(
        backend_assembly,
        "fetch_json",
        lambda url, auth_token=None: {"data": {"id": "49", "attributes": {}, "links": {}}},
    )
    handler = make_sms_configuration_handler(
        attribute_mapping={},
        base_url="https://sms.example/api",
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
        membership_filter_enabled=True,
        membership_filter_start_attribute_uri="configuration:member-filter-start",
        membership_filter_end_attribute_uri="configuration:member-filter-end",
    )

    result = handler.handle(
        "49",
        context=contracts.HandlerExecutionContext(require_configuration_period=True),
    )

    assert result == {"errors": ["A validated configuration period is required for SMS membership filtering."]}


def test_sms_membership_filter_action_requires_explicit_enablement(monkeypatch):
    monkeypatch.setattr(
        backend_assembly,
        "fetch_json",
        lambda url, auth_token=None: {"data": {"id": "49", "attributes": {}, "links": {}}},
    )
    handler = make_sms_configuration_handler(
        attribute_mapping={},
        base_url="https://sms.example/api",
        selected_devices_attribute_uri="selected-devices",
        selected_devices_page_uri="device-page",
    )

    result = handler.handle(
        "49",
        context=contracts.HandlerExecutionContext(require_configuration_period=True),
    )

    assert result == {"errors": ["SMS membership filtering is not enabled for this catalog."]}


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
        id_prefix="o2amission",
        base_url="https://registry.o2a-data.de/rest/v2",
    )
    handler.mission_item_page_size = 2
    handler.item_id_prefix = "o2aregistry"

    result = handler._fetch_mission_items("30")

    assert [item["id"] for item in result["records"]] == ["1", "2", "3"]
    assert len(requested_urls) == 2


def test_o2a_mission_member_uses_compact_mission_label():
    handler = o2a_mission_handler_module.O2ARegistryMissionHandler(
        attribute_mapping={},
        id_prefix="o2amission",
        base_url="https://registry.o2a-data.de/rest/v2",
    )
    handler.item_id_prefix = "o2aregistry"

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
        id_prefix="o2amission",
        base_url="https://registry.o2a-data.de/rest/v2",
    )
    handler.selected_devices_attribute_uri = "selected-devices"
    handler.selected_devices_page_uri = "device-page"
    handler.item_id_prefix = "o2aregistry"

    result = handler.handle("30", context=contracts.HandlerExecutionContext())

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
        id_prefix="o2amission",
        base_url="https://registry.o2a-data.de/rest/v2",
    )
    handler.selected_devices_attribute_uri = "selected-devices"
    handler.selected_devices_page_uri = "device-page"
    handler.item_id_prefix = "o2aregistry"

    result = handler.handle(
        "30",
        context=contracts.HandlerExecutionContext(preserve_existing_collections=True),
    )

    assert result == contracts.HandlerResult(
        mapped_values={
            "configuration:name": "Updated mission",
            "configuration:start": "2020-01-01 00:00",
            "configuration:end": "2030-01-01 00:00",
        },
    )
    assert requested_urls == ["https://registry.o2a-data.de/rest/v2/missions/30"]


def test_o2a_mission_selection_syncs_immediately(monkeypatch):
    requested_urls = []

    def fetch_json(url):
        requested_urls.append(url)
        if url.endswith("/missions/30"):
            return {"name": "Mission"}
        if "/missions/30/items" in url:
            return {"records": []}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(o2a_mission_handler_module, "fetch_json", fetch_json)
    handler = o2a_mission_handler_module.O2ARegistryMissionHandler(
        attribute_mapping={"name": "configuration:name"},
        id_prefix="o2amission",
        base_url="https://registry.o2a-data.de/rest/v2",
    )
    handler.selected_devices_attribute_uri = "selected-devices"
    handler.selected_devices_page_uri = "device-page"
    handler.item_id_prefix = "o2aregistry"

    result = handler.handle("30", context=contracts.HandlerExecutionContext())

    assert result == contracts.HandlerResult(
        mapped_values={"configuration:name": "Mission"},
        collections=(
            contracts.CollectionAssignment(
                attribute_uri="selected-devices",
                page_uri="device-page",
                values=(),
            ),
        ),
    )
    assert any("/missions/30/items" in url for url in requested_urls)


def test_o2a_mission_items_inherit_the_backend_mission_period(monkeypatch):
    def fetch_json(url):
        if url.endswith("/missions/30"):
            return {
                "name": "Mission",
                "startDate": "2026-07-01T10:00:00Z",
                "endDate": "2026-07-02T12:00:00Z",
            }
        if "/missions/30/items" in url:
            return {"records": [{"id": "1", "itemId": 4152}]}
        if url.endswith("/items/4152"):
            return {"id": 4152, "longName": "CTD"}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(o2a_mission_handler_module, "fetch_json", fetch_json)
    handler = o2a_mission_handler_module.O2ARegistryMissionHandler(
        attribute_mapping={
            "startDate": "configuration:start",
            "endDate": "configuration:end",
        },
        id_prefix="o2amission",
        base_url="https://registry.o2a-data.de/rest/v2",
    )
    handler.selected_devices_attribute_uri = "selected-devices"
    handler.selected_devices_page_uri = "device-page"
    handler.item_id_prefix = "o2aregistry"

    result = handler.handle("30", context=contracts.HandlerExecutionContext())

    member = result.collections[0].values[0]
    assert member["instrument_start"] == "2026-07-01 10:00"
    assert member["instrument_end"] == "2026-07-02 12:00"


def test_o2a_mission_rejects_historical_membership_filtering(monkeypatch):
    monkeypatch.setattr(
        o2a_mission_handler_module,
        "fetch_json",
        lambda url: {"name": "Mission"},
    )
    handler = o2a_mission_handler_module.O2ARegistryMissionHandler(
        attribute_mapping={},
        id_prefix="o2amission",
        base_url="https://registry.o2a-data.de/rest/v2",
    )
    handler.selected_devices_attribute_uri = "selected-devices"
    handler.selected_devices_page_uri = "device-page"
    handler.item_id_prefix = "o2aregistry"

    result = handler.handle(
        "30",
        context=contracts.HandlerExecutionContext(require_configuration_period=True),
    )

    assert result == {"errors": ["O2A Registry does not support historical mission-membership filtering."]}


def test_o2a_mission_exposes_the_backend_period_for_preserved_devices():
    handler = o2a_mission_handler_module.O2ARegistryMissionHandler(
        attribute_mapping={
            "startDate": "configuration:start",
            "endDate": "configuration:end",
        },
        id_prefix="o2amission",
        base_url="https://registry.o2a-data.de/rest/v2",
    )
    handler.item_id_prefix = "o2aregistry"

    period = handler.get_member_device_period(
        {
            "configuration:start": "2026-07-01 10:00",
            "configuration:end": "2026-07-02 12:00",
        },
    )

    assert period == ("2026-07-01 10:00", "2026-07-02 12:00")


@pytest.mark.parametrize("backend", ("sms", "o2a"))
@pytest.mark.parametrize("member_values", ([], [{"text": "Sensor", "external_id": "sensor:1", "instrument_start": "2026-01-01"}]))
def test_configuration_handlers_describe_device_effects_without_interview_models(monkeypatch, backend, member_values):
    module = sms_configuration_handler_module if backend == "sms" else o2a_mission_handler_module
    handler_class = make_sms_configuration_handler if backend == "sms" else module.O2ARegistryMissionHandler
    monkeypatch.setattr(
        backend_assembly if backend == "sms" else module,
        "fetch_json",
        lambda *args, **kwargs: {"data": {"id": "1"}, "name": "Mission"},
    )
    handler = handler_class(
        attribute_mapping={},
        id_prefix="configuration",
        base_url="https://backend.example",
    )
    handler.selected_devices_attribute_uri = "selected"
    handler.selected_devices_page_uri = "page"
    handler.device_collection_attribute_uri = "root"
    if backend == "sms":
        members = tuple(
            contracts.ConfigurationMember(
                value["external_id"].split(":", 1)[1],
                {"long_name": value["text"]},
                value.get("instrument_start"),
                None,
                contracts.MountLocation(),
            )
            for value in member_values
        )
        handler.device_id_prefix = "sensor"
        monkeypatch.setattr(
            handler.backend,
            "get_configuration_members",
            lambda *args, **kwargs: contracts.BackendSuccess(contracts.ConfigurationMembership(members)),
        )
    else:
        monkeypatch.setattr(handler, "_fetch_mission_items", lambda *args, **kwargs: {"records": []})
    if backend != "sms":
        monkeypatch.setattr(handler, "_build_selected_device_values", lambda **kwargs: (member_values, []))
    result = handler.handle("1", context=contracts.HandlerExecutionContext())
    if backend != "sms":
        assert result.collections[0].values == tuple(member_values)
    else:
        assert len(result.collections[0].values) == len(member_values)
    assert len(result.effects) == 1
    effect = result.effects[0]
    assert isinstance(effect, contracts.RefreshDeviceDetails)
    assert (effect.selected_devices_attribute_uri, effect.device_collection_attribute_uri) == ("selected", "root")
    assert tuple(device.external_id for device in effect.selected_devices) == tuple(
        value["external_id"] for value in member_values
    )
    if member_values:
        assert effect.selected_devices[0].instrument_start == "2026-01-01"
        assert effect.selected_devices[0].mount_location_resolved == (backend == "sms")
    preserved = handler.handle("1", context=contracts.HandlerExecutionContext(preserve_existing_collections=True))
    assert preserved.collections == preserved.effects == ()
