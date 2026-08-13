from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

CATALOG_PATH = Path(__file__).parents[1] / "xml" / "example_catalog_sensorsearch.xml"
DC_URI = "{http://purl.org/dc/elements/1.1/}uri"
INTERVIEW_PAGE_REFRESH_OPTIONSET_URI = "https://rdmo.nfdi4earth.de/terms/options/interview-page-refresh"
EXPECTED_PROVIDER_KEYS = {
    "sensorsearch_devices",
    "sensorsearch_configurations",
    "sensorsearch_interview_page_refresh",
    "sensorsearch_project_data_collection_devices",
    "sensorsearch_project_configuration_devices",
}
EXPECTED_REFRESH_TRIGGER_ATTRIBUTES = {
    "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/refresh-configuration",
    "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/refresh-device",
    "https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/configurations/trigger",
    "https://rdmo.nfdi4earth.de/terms/domain/metadata-refresh/devices/trigger",
}


def _catalog_root():
    return ElementTree.parse(CATALOG_PATH).getroot()


def test_example_catalog_uris_are_unique_and_references_resolve():
    root = _catalog_root()
    defined_uris = [element.attrib[DC_URI] for element in root if DC_URI in element.attrib]
    referenced_uris = {
        descendant.attrib[DC_URI]
        for element in root
        for descendant in element.iter()
        if descendant is not element and DC_URI in descendant.attrib
    }

    assert [uri for uri, count in Counter(defined_uris).items() if count > 1] == []
    assert referenced_uris <= set(defined_uris)


def test_example_catalog_contains_every_plugin_optionset_provider():
    provider_keys = {optionset.findtext("provider_key") for optionset in _catalog_root().findall("optionset")}

    assert provider_keys == EXPECTED_PROVIDER_KEYS


def test_example_catalog_attaches_page_refresh_to_every_metadata_trigger():
    trigger_attributes = {
        question.find("attribute").attrib[DC_URI]
        for question in _catalog_root().findall("question")
        if question.find(f"./optionsets/optionset[@{DC_URI}='{INTERVIEW_PAGE_REFRESH_OPTIONSET_URI}']") is not None
    }

    assert trigger_attributes == EXPECTED_REFRESH_TRIGGER_ATTRIBUTES


def test_example_catalog_uses_canonical_device_collection_page():
    device_page = next(
        page
        for page in _catalog_root().findall("page")
        if page.attrib[DC_URI] == "https://rdmo.nfdi4earth.de/terms/questions/instruments_general"
    )

    assert device_page.findtext("is_collection") == "True"
    assert device_page.find("attribute").attrib[DC_URI] == (
        "https://rdmo-sandbox.gfz-potsdam.de/terms/domain/moses/instruments/id"
    )


def test_example_catalog_data_collection_uses_sync_attributes():
    question_attributes = {question.find("attribute").attrib[DC_URI] for question in _catalog_root().findall("question")}

    assert {
        "https://rdmorganiser.github.io/terms/domain/project/dataset/collaboration_tools",
        "https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-variable",
        "https://rdmo.nfdi4earth.de/terms/domain/project/dataset/metadata/dc-unit",
    } <= question_attributes


def test_example_catalog_configuration_devices_use_sensor_search():
    question = next(
        question
        for question in _catalog_root().findall("question")
        if question.attrib[DC_URI] == "http://example.com/terms/questions/sensorsearch/configurations/devices"
    )

    assert question.findtext("widget_type") == "select"
    assert question.findtext("value_type") == "option"
    assert question.find("./optionsets/optionset").attrib[DC_URI] == ("http://example.com/terms/options/sensorsearch/devices")


def test_example_catalog_uses_canonical_configuration_page():
    configuration_page = next(
        page
        for page in _catalog_root().findall("page")
        if page.find("attribute") is not None
        and page.find("attribute").attrib[DC_URI] == "https://rdmo.nfdi4earth.de/terms/domain/configuration-set"
    )

    assert configuration_page.attrib[DC_URI] == ("https://rdmo.nfdi4earth.de/terms/questions/instruments/configuration-set")
