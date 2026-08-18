from collections import Counter
from xml.etree import ElementTree

from testing.paths import CATALOGS_ROOT

CATALOG_PATH = CATALOGS_ROOT / "earth-sensor+original.xml"
DC_URI = "{http://purl.org/dc/elements/1.1/}uri"
INTERVIEW_PAGE_REFRESH_OPTIONSET_URI = "https://rdmo.nfdi4earth.de/terms/options/interview-page-refresh"
REFRESH_TRIGGER_QUESTION_URIS = {
    "https://rdmo.nfdi4earth.de/terms/questions/configurations-general/refresh",
    "https://rdmo.nfdi4earth.de/terms/questions/instruments_general/refresh",
    "https://rdmo.nfdi4earth.de/terms/questions/metadata-refresh/configurations/trigger",
    "https://rdmo.nfdi4earth.de/terms/questions/metadata-refresh/devices/trigger",
}
LOCAL_REFRESH_CONDITIONS = {
    "https://rdmo.nfdi4earth.de/terms/conditions/configurations-general/has-backend-configuration": {
        "source": "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-search",
        "questions": {
            "https://rdmo.nfdi4earth.de/terms/questions/configurations-general/refresh",
            "https://rdmo.nfdi4earth.de/terms/questions/configurations-general/refresh-status",
            "https://rdmo.nfdi4earth.de/terms/questions/configurations-general/refresh-message",
            "https://rdmo.nfdi4earth.de/terms/questions/configurations-general/refresh-timestamp",
        },
    },
    "https://rdmo.nfdi4earth.de/terms/conditions/instruments-general/has-backend-device": {
        "source": "https://rdmo.nfdi.de/terms/domain/dataset/usage_technology/keywords",
        "questions": {
            "https://rdmo.nfdi4earth.de/terms/questions/instruments_general/refresh",
            "https://rdmo.nfdi4earth.de/terms/questions/instruments_general/refresh-status",
            "https://rdmo.nfdi4earth.de/terms/questions/instruments_general/refresh-message",
            "https://rdmo.nfdi4earth.de/terms/questions/instruments_general/refresh-timestamp",
        },
    },
}


def _catalog_root():
    return ElementTree.parse(CATALOG_PATH).getroot()


def test_catalog_defines_each_top_level_uri_once():
    uris = [element.attrib[DC_URI] for element in _catalog_root() if DC_URI in element.attrib]

    assert [uri for uri, count in Counter(uris).items() if count > 1] == []


def test_refresh_optionset_uses_interview_page_refresh_provider():
    refresh_optionset = next(
        optionset
        for optionset in _catalog_root().findall("optionset")
        if optionset.attrib[DC_URI] == INTERVIEW_PAGE_REFRESH_OPTIONSET_URI
    )

    assert refresh_optionset.findtext("provider_key") == "sensorsearch_interview_page_refresh"


def test_refresh_optionset_is_attached_to_every_trigger_question_only():
    questions_with_refresh_optionset = {
        question.attrib[DC_URI]
        for question in _catalog_root().findall("question")
        if question.find(f"./optionsets/optionset[@{DC_URI}='{INTERVIEW_PAGE_REFRESH_OPTIONSET_URI}']") is not None
    }

    assert questions_with_refresh_optionset == REFRESH_TRIGGER_QUESTION_URIS


def test_individual_device_refresh_questions_are_on_device_collection_page():
    root = _catalog_root()
    device_page = next(
        page
        for page in root.findall("page")
        if page.attrib[DC_URI] == "https://rdmo.nfdi4earth.de/terms/questions/instruments_general"
    )
    question_uris = {question.attrib[DC_URI] for question in device_page.findall("./questions/question")}

    assert {
        "https://rdmo.nfdi4earth.de/terms/questions/instruments_general/refresh",
        "https://rdmo.nfdi4earth.de/terms/questions/instruments_general/refresh-status",
        "https://rdmo.nfdi4earth.de/terms/questions/instruments_general/refresh-message",
        "https://rdmo.nfdi4earth.de/terms/questions/instruments_general/refresh-timestamp",
    } <= question_uris


def test_configuration_device_rows_use_sensor_search():
    question = next(
        question
        for question in _catalog_root().findall("question")
        if question.attrib[DC_URI] == "https://rdmo.nfdi4earth.de/terms/questions/instruments/configuration-set/selected"
    )

    assert question.findtext("widget_type") == "select"
    assert question.findtext("value_type") == "option"
    assert question.find("./optionsets/optionset").attrib[DC_URI] == (
        "https://rdmo-sandbox.gfz-potsdam.de/terms/options/optionsets/sensorsearch"
    )


def test_local_refresh_questions_require_a_backend_source_in_their_scope():
    root = _catalog_root()

    for condition_uri, expected in LOCAL_REFRESH_CONDITIONS.items():
        condition = next(condition for condition in root.findall("condition") if condition.attrib[DC_URI] == condition_uri)
        questions = {
            question.attrib[DC_URI]
            for question in root.findall("question")
            if question.find(f"./conditions/condition[@{DC_URI}='{condition_uri}']") is not None
        }

        assert condition.find("source").attrib[DC_URI] == expected["source"]
        assert condition.findtext("relation") == "notempty"
        assert questions == expected["questions"]


def test_configuration_period_is_the_backend_period_without_an_apply_action():
    root = _catalog_root()
    questions = {question.attrib[DC_URI]: question for question in root.findall("question")}

    start = questions["https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period/start"]
    end = questions["https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period/end"]
    assert start.findtext("is_optional") == "False"
    assert end.findtext("is_optional") == "True"
    assert "https://rdmo.nfdi4earth.de/terms/questions/configurations/time-period/apply" not in questions
    assert not any(
        question.find("attribute").attrib[DC_URI].endswith("/apply-date-range")
        for question in questions.values()
        if question.find("attribute") is not None
    )
