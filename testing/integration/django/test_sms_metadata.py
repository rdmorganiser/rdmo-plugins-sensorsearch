"""Exercise SMS metadata through real catalog scopes and RDMO persistence."""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from rdmo.domain.models import Attribute
from rdmo.options.models import Option
from rdmo.projects.models import Project, Snapshot, Value
from rdmo.questions.models import Question

from rdmo_sensorsearch import backend_assembly
from rdmo_sensorsearch.contracts import AuthoritativeTextScalar, SelectedDevice
from rdmo_sensorsearch.handlers.catalog_registry import clear_handler_registry
from rdmo_sensorsearch.persistence import value_reconciliation
from rdmo_sensorsearch.persistence.value_reconciliation import apply_mapped_values
from rdmo_sensorsearch.services.device_detail_profile import DEFAULT_DEVICE_DETAIL_SETTINGS
from rdmo_sensorsearch.services.refresh import RefreshAction, RefreshKind
from rdmo_sensorsearch.services.synchronization_context import mute_value_sync
from rdmo_sensorsearch.workflows import backend_value_sync, device_details, metadata_refresh
from testing.integration.django.test_metadata_refresh import earth_sensor_catalog as earth_sensor_catalog

pytestmark = pytest.mark.django_db
OWNER_URI = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/owner"
SEARCH_URI = "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/keywords"
ROOT_URI = "https://rdmo-sandbox.gfz-potsdam.de/terms/domain/moses/instruments/id"
CONFIG_SEARCH_URI = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-search"
SELECTED_URI = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/selected-devices"
SITE_URI = DEFAULT_DEVICE_DETAIL_SETTINGS.site_name_attribute_uri


def _insert(project, uri, **fields):
    with mute_value_sync():
        return Value.objects.create(
            project=project,
            attribute=Attribute.objects.get(uri=uri),
            **{"set_collection": False, **fields},
        )


def _device_source(project, configuration="27", index=0):
    external_id = f"gfzcfg:{configuration}||gfzsms:42" if configuration else "gfzsms:42"
    _insert(project, ROOT_URI, set_collection=True, set_index=index, external_id=external_id, text="Device")
    return _insert(project, SEARCH_URI, set_index=index, external_id="gfzsms:42", text="Device")


def _mount(configuration):
    return {
        "type": "device_mount_action",
        "id": f"mount-{configuration}",
        "attributes": {"begin_date": "2026-01-01T00:00:00Z", "end_date": None, "offset_z": -1},
        "relationships": {
            "configuration": {"data": {"type": "configuration", "id": configuration}},
            "device": {"data": {"type": "device", "id": "42"}},
            "parent_device": {"data": None},
            "parent_platform": {"data": None},
        },
    }


@pytest.fixture
def sms_project(earth_sensor_catalog, monkeypatch):
    state = SimpleNamespace(
        project=Project.objects.create(title="SMS owner and location", catalog=earth_sensor_catalog),
        owners=["Institute A"],
        contact_payload=None,
        sites={"27": "Site A", "28": "Site B"},
        requests=[],
    )

    def fetch(url, auth_token=None):
        state.requests.append((url, auth_token))
        if "/device-contact-roles?" in url:
            if state.contact_payload is not None:
                return state.contact_payload
            return {
                "data": [
                    {
                        "type": "device_contact_role",
                        "id": str(i),
                        "attributes": {"role_name": "Owner"},
                        "relationships": {"contact": {"data": {"type": "contact", "id": str(i)}}},
                    }
                    for i, _ in enumerate(state.owners)
                ],
                "included": [
                    {"type": "contact", "id": str(i), "attributes": {"organization": name}} for i, name in enumerate(state.owners)
                ],
            }
        if "/devices/42?" in url:
            return {
                "data": {
                    "type": "device",
                    "id": "42",
                    "attributes": {"long_name": "Device"},
                    "links": {"self": "/backend/api/v1/devices/42"},
                }
            }
        if "/devices/42/device-mount-actions?" in url:
            return {"data": [_mount("27"), _mount("28")]}
        configuration = parse_qs(urlsplit(url).query).get("filter[configuration_id]", [None])[0]
        if "/device-mount-actions?" in url:
            return {"data": [_mount(configuration)]}
        if "/platform-mount-actions?" in url:
            return {"data": []}
        if "/static-location-actions?" in url:
            label = state.sites.get(configuration)
            return {
                "data": []
                if label is None
                else [
                    {
                        "type": "configuration_static_location_action",
                        "id": f"site-{configuration}",
                        "attributes": {"begin_date": "2020-01-01T00:00:00Z", "end_date": None, "label": label, "z": 100},
                    },
                ]
            }
        raise AssertionError(f"Unexpected SMS request: {url}")

    monkeypatch.setattr(backend_assembly, "fetch_json", fetch)
    clear_handler_registry()
    yield state
    clear_handler_registry()


def _answer(project, uri=OWNER_URI, index=0):
    return Value.objects.get(project=project, attribute__uri=uri, snapshot=None, set_prefix="", set_index=index)


def test_initial_device_sync_populates_owner_and_actual_catalog_site(sms_project):
    source = _device_source(sms_project.project)

    backend_value_sync.sync_backend_value_after_save(source, auth_token="test-token")

    owner = _answer(sms_project.project)
    assert (owner.text, owner.external_id, owner.option_id, owner.value_type) == ("Institute A", "", None, "option")
    assert _answer(sms_project.project, SITE_URI).text == "Site A"
    question = Question.objects.get(uri="https://rdmo.nfdi4earth.de/terms/questions/instrument_owner")
    assert (question.widget_type, question.value_type) == ("select_creatable", "option")
    assert all(token == "test-token" for _, token in sms_project.requests)


def test_refresh_replaces_manual_and_previous_backend_names_and_is_idempotent(sms_project):
    project = sms_project.project
    source = _device_source(project)
    _insert(project, OWNER_URI, text="Manual institute", value_type="option")
    assert backend_value_sync.refresh_value_from_backend(source).status == "success"
    owner = _answer(project)
    assert owner.text == "Institute A"
    assert owner.external_id == "" and owner.option_id is None

    sms_project.owners = ["Institute B", " Institute B "]
    assert backend_value_sync.refresh_value_from_backend(source).status == "success"
    assert _answer(project).text == "Institute B"
    before = list(Value.objects.filter(project=project, attribute__uri=OWNER_URI).values())
    assert backend_value_sync.refresh_value_from_backend(source).status == "success"
    assert list(Value.objects.filter(project=project, attribute__uri=OWNER_URI).values()) == before


@pytest.mark.parametrize("existing_name", ["Institute A", "Different institute"])
def test_refresh_replaces_ror_metadata_even_when_owner_label_matches(sms_project, existing_name):
    project = sms_project.project
    source = _device_source(project)
    option = Option.objects.create(
        uri_prefix="https://test.example", uri_path="ror-owner", text_lang1=existing_name, text_lang2=existing_name
    )
    owner = _insert(
        project, OWNER_URI, text=existing_name, option=option, external_id="https://ror.org/example", value_type="option"
    )

    assert backend_value_sync.refresh_value_from_backend(source).status == "success"

    owner.refresh_from_db()
    assert (owner.text, owner.option_id, owner.external_id, owner.value_type) == ("Institute A", None, "", "option")


@pytest.mark.parametrize("owners", [[], ["", "  "]])
def test_successful_sms_refresh_without_usable_owner_clears_existing_owner(sms_project, owners):
    source = _device_source(sms_project.project)
    assert backend_value_sync.refresh_value_from_backend(source).status == "success"
    sms_project.owners = owners

    assert backend_value_sync.refresh_value_from_backend(source).status == "success"

    assert not sms_project.project.values.filter(attribute__uri=OWNER_URI, snapshot=None).exists()


def test_refresh_normalizes_multiple_owners_without_splitting_organization_names(sms_project):
    source = _device_source(sms_project.project)
    _insert(sms_project.project, OWNER_URI, text="Old owner")
    sms_project.owners = [" Institute A ", "Institute B", "Institute A", "Institute; Research", " "]

    assert backend_value_sync.refresh_value_from_backend(source).status == "success"

    assert _answer(sms_project.project).text == "Institute A; Institute B; Institute; Research"


@pytest.mark.parametrize("existing_name", ["Institute A", "Static institute"])
def test_refresh_replaces_static_option_even_when_owner_label_matches(sms_project, existing_name):
    project = sms_project.project
    source = _device_source(project)
    option = Option.objects.create(
        uri_prefix="https://test.example",
        uri_path="owner",
        text_lang1=existing_name,
        text_lang2=existing_name,
    )
    _insert(project, OWNER_URI, option=option, value_type="option")

    assert backend_value_sync.refresh_value_from_backend(source).status == "success"

    answer = _answer(project)
    assert (answer.text, answer.option_id, answer.external_id, answer.value_type) == ("Institute A", None, "", "option")


def test_clearing_device_selection_clears_managed_owner(sms_project):
    project = sms_project.project
    source = _device_source(project)
    assert backend_value_sync.refresh_value_from_backend(source).status == "success"
    with mute_value_sync():
        source.text = source.external_id = ""
        source.save(update_fields=["text", "external_id"])

    backend_value_sync.sync_backend_value_after_save(source)

    assert not project.values.filter(attribute__uri=OWNER_URI, snapshot=None).exists()


@pytest.mark.parametrize(
    "payload",
    [
        {"errors": ["backend unavailable"]},
        {"data": None},
        {"data": [], "included": [None]},
    ],
)
def test_contact_failure_preserves_all_existing_metadata(sms_project, payload):
    source = _device_source(sms_project.project)
    assert backend_value_sync.refresh_value_from_backend(source).status == "success"
    before = list(sms_project.project.values.order_by("id").values())
    sms_project.contact_payload = payload

    assert backend_value_sync.refresh_value_from_backend(source).status == "failed"
    assert list(sms_project.project.values.order_by("id").values()) == before


def test_no_owner_creates_no_blank_answer_and_no_context_borrows_no_site(sms_project):
    sms_project.owners = []
    source = _device_source(sms_project.project, configuration=None)

    assert backend_value_sync.refresh_value_from_backend(source).status == "success"
    assert not sms_project.project.values.filter(attribute__uri__in=[OWNER_URI, SITE_URI]).exists()
    assert len(sms_project.requests) == 2


def test_bulk_refresh_keeps_same_device_in_two_configuration_blocks(sms_project):
    project = sms_project.project
    first = _device_source(project, "27", 0)
    _device_source(project, "28", 1)
    _insert(project, OWNER_URI, set_index=1, text="Manual institute")
    action = RefreshAction(RefreshKind.ALL_DEVICES, "unused", CONFIG_SEARCH_URI, SEARCH_URI)

    result = metadata_refresh._refresh_all_devices(first, action)

    assert result.refreshed_count == 2 and result.status == "success"
    assert _answer(project, SITE_URI, 0).text == "Site A"
    assert _answer(project, SITE_URI, 1).text == "Site B"
    assert _answer(project, index=0).text == "Institute A"
    assert _answer(project, index=1).text == "Institute A"
    sms_project.sites["27"] = None
    assert backend_value_sync.refresh_value_from_backend(first).status == "success"
    assert not project.values.filter(attribute__uri=SITE_URI, set_index=0).exists()
    assert _answer(project, SITE_URI, 1).text == "Site B"
    sms_project.owners = ["Institute B"]
    assert backend_value_sync.refresh_value_from_backend(first).status == "success"
    assert _answer(project, index=0).text == "Institute B"
    assert _answer(project, index=1).text == "Institute A"


def test_configuration_derived_import_and_forced_refresh_replace_owner_in_device_block(sms_project):
    project = sms_project.project
    _insert(project, CONFIG_SEARCH_URI, text="Configuration", external_id="gfzcfg:27")

    def synchronize(force=False, devices=None):
        return device_details.reconcile_device_details_from_selected_devices(
            project=project,
            catalog=project.catalog,
            scope_prefix="",
            source_set_index=0,
            selected_devices=devices if devices is not None else [SelectedDevice("Device", "gfzsms:42")],
            selected_devices_attribute_uri=SELECTED_URI,
            device_collection_attribute_uri=ROOT_URI,
            configuration_search_attribute_uri=CONFIG_SEARCH_URI,
            configuration_external_id="gfzcfg:27",
            force_refresh=force,
        )

    assert synchronize().status == "success"
    assert _answer(project).text == "Institute A"
    assert _answer(project, SITE_URI).text == "Site A"
    sms_project.owners = ["Institute B"]
    assert synchronize(force=True).status == "success"
    assert _answer(project).text == "Institute B"
    before = list(project.values.filter(attribute__uri=OWNER_URI).values())
    sms_project.contact_payload = {"errors": ["backend unavailable"]}
    assert synchronize(force=True).status == "failed"
    assert list(project.values.filter(attribute__uri=OWNER_URI).values()) == before
    assert synchronize(devices=[]).status == "success"
    assert not project.values.filter(attribute__uri__in=[OWNER_URI, SITE_URI]).exists()


def test_authoritative_refresh_ignores_snapshots_and_normal_scalar_clearing_still_works(sms_project):
    project = sms_project.project
    source = _device_source(project)
    snapshot = Snapshot.objects.create(project=project, title="Historical")
    historical = _insert(project, OWNER_URI, snapshot=snapshot, text="Snapshot owner")
    apply_mapped_values(source, {OWNER_URI: AuthoritativeTextScalar(("Institute A",))})
    assert _answer(project).text == "Institute A"
    apply_mapped_values(source, {OWNER_URI: None})
    assert not project.values.filter(attribute__uri=OWNER_URI, snapshot=None).exists()
    historical.refresh_from_db()
    assert historical.text == "Snapshot owner"


@pytest.mark.parametrize(
    "names,expected",
    [
        ((" Institute;Research ", "Institute B", "Institute;Research", " "), "Institute;Research; Institute B"),
        ((), None),
        (("", " \t "), None),
    ],
)
def test_authoritative_scalar_consolidates_resolved_scopes_and_preserves_other_values(sms_project, monkeypatch, names, expected):
    project = sms_project.project
    source = _device_source(project)
    primary = _insert(project, OWNER_URI, text="Old primary", value_type="text")
    _insert(project, OWNER_URI, text="Duplicate")
    _insert(project, OWNER_URI, set_prefix="legacy", set_index=2, text="Secondary")
    unrelated = _insert(project, OWNER_URI, set_index=1, text="Unrelated")
    collection = _insert(project, OWNER_URI, set_collection=True, text="Collection")
    snapshot = Snapshot.objects.create(project=project, title="Historical")
    historical = _insert(project, OWNER_URI, snapshot=snapshot, text="Snapshot primary")
    secondary_historical = _insert(
        project, OWNER_URI, snapshot=snapshot, set_prefix="legacy", set_index=2, text="Snapshot secondary"
    )
    preserved_ids = [unrelated.pk, collection.pk, historical.pk, secondary_historical.pk]
    preserved = list(Value.objects.filter(pk__in=preserved_ids).order_by("id").values())
    resolver = SimpleNamespace(resolve=lambda *args: [("", 0), ("legacy", 2)])
    monkeypatch.setattr(value_reconciliation, "RDMOAnswerTreeScopeResolver", lambda project: resolver)

    apply_mapped_values(source, {OWNER_URI: AuthoritativeTextScalar(names)})

    assert list(Value.objects.filter(pk__in=preserved_ids).order_by("id").values()) == preserved
    assert not project.values.filter(attribute__uri=OWNER_URI, snapshot=None, set_prefix="legacy").exists()
    active = project.values.filter(attribute__uri=OWNER_URI, snapshot=None, set_collection=False, set_index=0)
    if expected is None:
        assert not active.exists()
    else:
        answer = active.get()
        assert answer.pk == primary.pk
        assert (answer.text, answer.option_id, answer.external_id, answer.value_type) == (expected, None, "", "option")
        before = list(active.values())
        apply_mapped_values(source, {OWNER_URI: AuthoritativeTextScalar(names)})
        assert list(active.values()) == before
