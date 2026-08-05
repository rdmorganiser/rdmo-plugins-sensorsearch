import sys
from importlib import import_module
from types import ModuleType, SimpleNamespace

import pytest

from rdmo_sensorsearch.naming import device_detail_tab_label
from rdmo_sensorsearch.services.device_details import DeviceBlockPlan, SelectedDevice
from rdmo_sensorsearch.services.device_metadata import DeviceFetchResult


class FakeQ:
    def __init__(self, **lookups):
        self.lookups = lookups
        self.children = ()

    def __or__(self, other):
        combined = FakeQ()
        combined.children = (self, other)
        return combined

    def matches(self, value):
        if self.children:
            return any(child.matches(value) for child in self.children)
        return _matches(value, self.lookups)


class FakeValue:
    def __init__(
        self,
        value_id,
        *,
        project="project",
        snapshot=None,
        attribute=None,
        attribute_id=None,
        set_collection=False,
        set_prefix="",
        set_index=0,
        external_id=None,
        text=None,
    ):
        self.id = value_id
        self.project = project
        self.snapshot = snapshot
        self.attribute = attribute
        self.attribute_id = attribute_id if attribute_id is not None else getattr(attribute, "id", None)
        self.set_collection = set_collection
        self.set_prefix = set_prefix
        self.set_index = set_index
        self.external_id = external_id
        self.text = text


class FakeQuerySet:
    def __init__(self, manager, rows):
        self.manager = manager
        self.rows = list(rows)

    def filter(self, *conditions, **lookups):
        rows = [row for row in self.rows if _matches(row, lookups)]
        for condition in conditions:
            rows = [row for row in rows if condition.matches(row)]
        return FakeQuerySet(self.manager, rows)

    def exclude(self, **lookups):
        return FakeQuerySet(self.manager, [row for row in self.rows if not _matches(row, lookups)])

    def order_by(self, *fields):
        rows = list(self.rows)
        for field in reversed(fields):
            descending = field.startswith("-")
            name = field.removeprefix("-")
            rows.sort(key=lambda row: getattr(row, name), reverse=descending)
        return FakeQuerySet(self.manager, rows)

    def first(self):
        return self.rows[0] if self.rows else None

    def exists(self):
        return bool(self.rows)

    def values_list(self, field, *, flat=False):
        values = [getattr(row, field) for row in self.rows]
        return FakeValuesList(values if flat else [(value,) for value in values])

    def distinct(self):
        unique = []
        seen = set()
        for row in self.rows:
            if row.id not in seen:
                seen.add(row.id)
                unique.append(row)
        return FakeQuerySet(self.manager, unique)

    def update(self, **updates):
        for row in self.rows:
            for field, value in updates.items():
                setattr(row, field, value)
        return len(self.rows)

    def delete(self):
        ids = {row.id for row in self.rows}
        self.manager.rows[:] = [row for row in self.manager.rows if row.id not in ids]
        return len(ids), {}

    def __iter__(self):
        return iter(self.rows)


class FakeManager:
    def __init__(self, rows):
        self.rows = list(rows)

    def filter(self, *conditions, **lookups):
        return FakeQuerySet(self, self.rows).filter(*conditions, **lookups)


class FakeValuesList(list):
    def distinct(self):
        return FakeValuesList(dict.fromkeys(self))


def _matches(value, lookups):
    for lookup, expected in lookups.items():
        path, _, operation = lookup.rpartition("__")
        if operation not in {"in", "isnull", "exact"}:
            path = lookup
            operation = "exact"
        actual = value
        for part in path.split("__"):
            actual = getattr(actual, part)
        if operation == "in" and actual not in expected:
            return False
        if operation == "isnull" and (actual is None) is not expected:
            return False
        if operation == "exact" and actual != expected:
            return False
    return True


@pytest.fixture
def persistence_module(monkeypatch):
    django = ModuleType("django")
    django_db = ModuleType("django.db")
    django_db_models = ModuleType("django.db.models")
    django_db_models.Q = FakeQ
    django_db.models = django_db_models
    django.db = django_db

    rdmo = ModuleType("rdmo")
    rdmo_projects = ModuleType("rdmo.projects")
    rdmo_project_models = ModuleType("rdmo.projects.models")
    rdmo_project_models.Value = FakeValue
    rdmo_projects.models = rdmo_project_models
    rdmo.projects = rdmo_projects

    monkeypatch.setitem(sys.modules, "django", django)
    monkeypatch.setitem(sys.modules, "django.db", django_db)
    monkeypatch.setitem(sys.modules, "django.db.models", django_db_models)
    monkeypatch.setitem(sys.modules, "rdmo", rdmo)
    monkeypatch.setitem(sys.modules, "rdmo.projects", rdmo_projects)
    monkeypatch.setitem(sys.modules, "rdmo.projects.models", rdmo_project_models)
    monkeypatch.delitem(sys.modules, "rdmo_sensorsearch.persistence.device_details", raising=False)

    module = import_module("rdmo_sensorsearch.persistence.device_details")
    yield module
    sys.modules.pop("rdmo_sensorsearch.persistence.device_details", None)


def _store(module, rows, *, scope_prefix="row"):
    value_model = SimpleNamespace(objects=FakeManager(rows))
    root_attribute = SimpleNamespace(id=10, uri="attribute:root")
    return module.RDMODeviceDetailStore(
        "project",
        root_attribute,
        scope_prefix,
        value_model=value_model,
    )


def _plan(handler=None):
    device = SelectedDevice(text="KIT Sensor: Temperature probe", external_id="kitsms:324")
    return DeviceBlockPlan(
        device=device,
        block_key="kitcfg:27||kitsms:324",
        set_index=3,
        handler_binding=SimpleNamespace(
            handler=handler or object(),
            search_attribute_uri="attribute:search",
        ),
        needs_metadata_write=True,
        needs_refresh=True,
    )


def test_store_finds_scoped_blocks_and_allocates_after_the_highest_index(persistence_module):
    root = SimpleNamespace(id=10, uri="attribute:root")
    rows = [
        FakeValue(1, attribute=root, set_collection=True, set_prefix="row", set_index=0, external_id="cfg:1||dev:1"),
        FakeValue(2, attribute=root, set_collection=True, set_prefix="row", set_index=3, external_id="cfg:2||dev:2"),
        FakeValue(3, attribute=root, set_collection=True, set_prefix="row", set_index=2, external_id="invalid"),
        FakeValue(4, attribute=root, set_collection=True, set_prefix="other", set_index=8, external_id="cfg:1||dev:3"),
    ]
    store = persistence_module.RDMODeviceDetailStore(
        "project",
        root,
        "row",
        value_model=SimpleNamespace(objects=FakeManager(rows)),
    )

    assert store.existing_blocks("cfg:1") == {"cfg:1||dev:1": persistence_module.DeviceBlockReference(set_index=0)}
    assert store.find_block("cfg:2||dev:2") == persistence_module.DeviceBlockReference(set_index=3)
    assert store.find_block("missing") is None
    assert store.next_set_index() == 4


def test_store_checks_identity_and_required_scalar_completeness(persistence_module):
    root = SimpleNamespace(id=10, uri="attribute:root")
    plan = _plan()
    rows = [
        FakeValue(
            1,
            attribute=root,
            set_collection=True,
            set_prefix="row",
            set_index=3,
            external_id=plan.block_key,
            text=device_detail_tab_label("KIT Cfg 27", plan.device.text, plan.device.external_id),
        ),
        FakeValue(
            2,
            attribute=SimpleNamespace(id=11, uri="attribute:search"),
            set_prefix="row",
            set_index=3,
            external_id=plan.device.external_id,
            text="Temperature probe",
        ),
        FakeValue(3, attribute=SimpleNamespace(uri="attribute:link"), set_prefix="row", set_index=3, text="link"),
        FakeValue(4, attribute=SimpleNamespace(uri="attribute:usage"), set_prefix="row", set_index=3, text="usage"),
        FakeValue(5, attribute=SimpleNamespace(uri="attribute:start"), set_prefix="3", set_index=0, text="start"),
    ]
    store = persistence_module.RDMODeviceDetailStore(
        "project",
        root,
        "row",
        value_model=SimpleNamespace(objects=FakeManager(rows)),
    )

    assert store.block_metadata_is_current(
        plan.device,
        plan.block_key,
        plan.set_index,
        plan.handler_binding,
        "KIT Cfg 27",
    )
    assert not store.block_needs_refresh(
        3,
        device_link_attribute_uri="attribute:link",
        usage_technology_attribute_uri="attribute:usage",
        instrument_start_attribute_uri="attribute:start",
    )

    rows[-1].text = ""
    assert store.block_needs_refresh(
        3,
        device_link_attribute_uri="attribute:link",
        usage_technology_attribute_uri="attribute:usage",
        instrument_start_attribute_uri="attribute:start",
    )


def test_store_detects_orphaned_configuration_scopes(persistence_module):
    root = SimpleNamespace(id=10, uri="attribute:root")
    search = SimpleNamespace(id=11, uri="attribute:configuration-search")
    rows = [
        FakeValue(1, attribute=search, external_id="cfg:active", text="Active"),
        FakeValue(2, attribute=root, set_collection=True, set_prefix="a", set_index=0, external_id="cfg:active||dev:1"),
        FakeValue(3, attribute=root, set_collection=True, set_prefix="b", set_index=4, external_id="cfg:old||dev:2"),
    ]
    store = persistence_module.RDMODeviceDetailStore(
        "project",
        root,
        value_model=SimpleNamespace(objects=FakeManager(rows)),
    )

    assert store.orphaned_scopes(("attribute:configuration-search",)) == {("b", 4)}


def test_store_deletes_parent_and_nested_values_for_one_block(persistence_module):
    rows = [
        FakeValue(1, attribute_id=10, set_collection=True, set_prefix="row", set_index=3),
        FakeValue(2, attribute_id=11, set_prefix="3", set_index=0),
        FakeValue(3, attribute_id=99, set_prefix="row", set_index=3),
        FakeValue(4, attribute_id=10, set_collection=True, set_prefix="row", set_index=4),
    ]
    store = _store(persistence_module, rows)

    assert store.delete_block(3, {10, 11}) == 2
    assert [row.id for row in store.value_model.objects.rows] == [3, 4]


def test_store_compacts_parent_and_nested_indexes_in_two_phases(persistence_module):
    root = SimpleNamespace(id=10, uri="attribute:root")
    rows = [
        FakeValue(1, attribute=root, set_collection=True, set_prefix="row", set_index=1),
        FakeValue(2, attribute_id=11, set_prefix="1", set_index=0),
        FakeValue(3, attribute=root, set_collection=True, set_prefix="row", set_index=3),
        FakeValue(4, attribute_id=11, set_prefix="3", set_index=0),
    ]
    store = persistence_module.RDMODeviceDetailStore(
        "project",
        root,
        "row",
        value_model=SimpleNamespace(objects=FakeManager(rows)),
    )

    store.compact({10, 11})

    assert [(row.id, row.set_prefix, row.set_index) for row in rows] == [
        (1, "row", 0),
        (2, "0", 0),
        (3, "row", 1),
        (4, "1", 0),
    ]


def test_catalog_attribute_ids_walks_only_selected_pages(persistence_module):
    selected_page = SimpleNamespace(
        uri="page:selected",
        attribute_id=1,
        elements=[SimpleNamespace(attribute_id=2, elements=[SimpleNamespace(attribute_id=3, elements=[])])],
    )
    ignored_page = SimpleNamespace(uri="page:ignored", attribute_id=4, elements=[])
    catalog = SimpleNamespace(pages=[selected_page, ignored_page], prefetch_elements=lambda: None)

    assert persistence_module.catalog_attribute_ids(catalog, {"page:selected"}) == {1, 2, 3}


def test_store_delegates_identity_and_payload_writes_to_reconciliation_helpers(
    persistence_module,
    monkeypatch,
):
    reconciliation = ModuleType("rdmo_sensorsearch.persistence.value_reconciliation")
    upserts = []
    reconciled = []
    scalar_replacements = []
    reconciliation.format_change_label = lambda created, changed: "Changed" if created or changed else "Unchanged"
    reconciliation.upsert_value_if_changed = lambda lookup, defaults: upserts.append((lookup, defaults)) or (object(), True, True)
    reconciliation.reconcile_mapped_values = lambda *args, **kwargs: reconciled.append((args, kwargs))
    reconciliation.replace_scalar_value_in_scopes = lambda *args, **kwargs: scalar_replacements.append((args, kwargs))
    monkeypatch.setitem(sys.modules, "rdmo_sensorsearch.persistence.value_reconciliation", reconciliation)
    monkeypatch.setattr(persistence_module, "get_attribute_by_uri", lambda _uri: SimpleNamespace(id=11))

    store = _store(persistence_module, [])
    plan = _plan(handler=SimpleNamespace(build_authoritative_mapped_values=lambda values, **_kwargs: values))
    store.upsert_block_identity(plan, "KIT Cfg 27")
    store.write_fetch_payload(
        plan,
        DeviceFetchResult(
            mapped_values={"attribute:name": "Temperature probe"},
            scoped_scalar_values={"attribute:start": "2026-01-01 00:00"},
        ),
        excluded_attribute_uris={"attribute:start"},
    )

    assert len(upserts) == 2
    assert upserts[0][1]["external_id"] == plan.block_key
    assert upserts[1][1] == {"text": "Temperature probe", "external_id": "kitsms:324"}
    assert reconciled[0][0][1] is plan.handler_binding.handler
    assert reconciled[0][1]["excluded_attribute_uris"] == {"attribute:start"}
    assert scalar_replacements[0][1] == {
        "scopes_to_set": [("3", 0)],
        "scopes_to_clear": [("row", 3)],
    }
