from itertools import count

import pytest

from django.utils import timezone

from rdmo.core.imports import ImportElementFields
from rdmo.core.xml import parse_xml_to_elements
from rdmo.domain.models import Attribute
from rdmo.management.imports import import_elements
from rdmo.projects.models import Project, Value
from rdmo.questions.models import Catalog

from rdmo_sensorsearch.services.refresh import RefreshResult
from rdmo_sensorsearch.workflows import metadata_refresh
from testing.paths import CATALOGS_ROOT

EARTH_SENSOR_CATALOG_URI = "https://rdmo.nfdi4earth.de/terms/questions/earth-sensor"
CONFIGURATION_COLLECTION_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set"
CONFIGURATION_SEARCH_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-search"
REFRESH_CONFIGURATION_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-configuration"
MISSING_CONFIGURATION_MESSAGE = "No backend configuration exists in this configuration scope."

_project_numbers = count()


@pytest.fixture
def earth_sensor_catalog():
    elements, errors = parse_xml_to_elements(CATALOGS_ROOT / "earth-sensor+original.xml")

    assert errors == []
    imported_elements = import_elements(elements)
    assert all(not element[ImportElementFields.ERRORS] for element in imported_elements)

    return Catalog.objects.get(uri=EARTH_SENSOR_CATALOG_URI)


def _project(catalog):
    return Project.objects.create(title=f"Metadata refresh scope test {next(_project_numbers)}", catalog=catalog)


def _attributes():
    return {
        uri: Attribute.objects.get(uri=uri)
        for uri in (
            CONFIGURATION_COLLECTION_ATTRIBUTE_URI,
            CONFIGURATION_SEARCH_ATTRIBUTE_URI,
            REFRESH_CONFIGURATION_ATTRIBUTE_URI,
        )
    }


def _create_configuration_values(
    project,
    attributes,
    *,
    trigger_scope: tuple[str, int],
    source_external_id: str,
):
    collection_attribute = attributes[CONFIGURATION_COLLECTION_ATTRIBUTE_URI]
    source_attribute = attributes[CONFIGURATION_SEARCH_ATTRIBUTE_URI]
    trigger_attribute = attributes[REFRESH_CONFIGURATION_ATTRIBUTE_URI]
    now = timezone.now()
    Value.objects.bulk_create(
        (
            Value(
                created=now,
                updated=now,
                project=project,
                attribute=collection_attribute,
                set_prefix="",
                set_index=1,
                set_collection=True,
            ),
            Value(
                created=now,
                updated=now,
                project=project,
                attribute=source_attribute,
                set_prefix="",
                set_index=1,
                set_collection=False,
                text="Test configuration",
                external_id=source_external_id,
            ),
            Value(
                created=now,
                updated=now,
                project=project,
                attribute=trigger_attribute,
                set_prefix=trigger_scope[0],
                set_index=trigger_scope[1],
                set_collection=False,
                value_type="boolean",
                text="1",
            ),
        )
    )
    return Value.objects.get(project=project, attribute=trigger_attribute)


@pytest.mark.django_db
def test_current_refresh_resolves_parent_page_scope_for_nested_questionset(earth_sensor_catalog, monkeypatch):
    attributes = _attributes()
    refreshed_values = []
    monkeypatch.setattr(
        metadata_refresh,
        "refresh_value_from_backend",
        lambda value, **kwargs: refreshed_values.append((value, kwargs)) or RefreshResult(1, 1),
    )

    nested_trigger = _create_configuration_values(
        _project(earth_sensor_catalog),
        attributes,
        trigger_scope=("1", 0),
        source_external_id="gfzcfg:123",
    )
    nested_result, _ = metadata_refresh._refresh_current_value(
        nested_trigger,
        CONFIGURATION_SEARCH_ATTRIBUTE_URI,
        MISSING_CONFIGURATION_MESSAGE,
        lambda text, external_id: text,
    )

    assert nested_result.refreshed_count == 1
    assert [value.external_id for value, _ in refreshed_values] == ["gfzcfg:123"]

    direct_trigger = _create_configuration_values(
        _project(earth_sensor_catalog),
        attributes,
        trigger_scope=("", 1),
        source_external_id="gfzcfg:456",
    )
    direct_result, _ = metadata_refresh._refresh_current_value(
        direct_trigger,
        CONFIGURATION_SEARCH_ATTRIBUTE_URI,
        MISSING_CONFIGURATION_MESSAGE,
        lambda text, external_id: text,
    )

    assert direct_result.refreshed_count == 1
    assert [value.external_id for value, _ in refreshed_values] == ["gfzcfg:123", "gfzcfg:456"]

    missing_id_trigger = _create_configuration_values(
        _project(earth_sensor_catalog),
        attributes,
        trigger_scope=("1", 0),
        source_external_id="",
    )
    missing_id_result, _ = metadata_refresh._refresh_current_value(
        missing_id_trigger,
        CONFIGURATION_SEARCH_ATTRIBUTE_URI,
        MISSING_CONFIGURATION_MESSAGE,
        lambda text, external_id: text,
    )

    assert missing_id_result.refreshed_count == 0
    assert missing_id_result.errors[0].message == MISSING_CONFIGURATION_MESSAGE
