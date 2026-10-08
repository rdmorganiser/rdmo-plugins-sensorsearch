from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

from testing.paths import CATALOGS_ROOT
from testing.tools.generate_plugin_dev_assets import (
    PLUGIN_DEV_ATTRIBUTE_URI,
    TARGET_CATALOG_URI,
    generate_catalog,
    mirror_uri,
)

SOURCE_PATH = CATALOGS_ROOT / "earth-sensor+original.xml"
CATALOG_PATH = CATALOGS_ROOT / "example_catalog_sensorsearch.xml"
DC_URI = "{http://purl.org/dc/elements/1.1/}uri"


def _root(path: Path):
    return ElementTree.parse(path).getroot()


def _defined_uris(root):
    return [element.attrib[DC_URI] for element in root if DC_URI in element.attrib]


def _referenced_uris(root):
    return [
        descendant.attrib[DC_URI]
        for element in root
        for descendant in element.iter()
        if descendant is not element and DC_URI in descendant.attrib
    ]


def test_example_catalog_is_a_complete_independent_mirror():
    source = _root(SOURCE_PATH)
    mirror = _root(CATALOG_PATH)
    source_definitions = _defined_uris(source)
    mirror_definitions = _defined_uris(mirror)

    assert mirror.find("catalog").attrib[DC_URI] == TARGET_CATALOG_URI
    assert Counter(element.tag for element in mirror) == Counter(element.tag for element in source) + Counter({"attribute": 1})
    assert Counter(mirror_definitions) == Counter(mirror_uri(uri) for uri in source_definitions) + Counter(
        {PLUGIN_DEV_ATTRIBUTE_URI: 1}
    )
    assert Counter(mirror_uri(uri) for uri in _referenced_uris(source)) <= Counter(_referenced_uris(mirror))
    assert all(uri.startswith("https://example.com/") for uri in mirror_definitions)
    assert all(uri.startswith("https://example.com/") for uri in _referenced_uris(mirror))
    assert all("/terms/" in uri for uri in (*mirror_definitions, *_referenced_uris(mirror)))


def test_example_catalog_uris_are_unique_and_references_resolve():
    root = _root(CATALOG_PATH)
    definitions = _defined_uris(root)

    source_definitions = _defined_uris(_root(SOURCE_PATH))
    assert Counter(definitions) == Counter(mirror_uri(uri) for uri in source_definitions) + Counter({PLUGIN_DEV_ATTRIBUTE_URI: 1})
    assert set(_referenced_uris(root)) <= set(definitions)


def test_example_catalog_preserves_optionset_provider_keys():
    source_provider_keys = {optionset.findtext("provider_key") for optionset in _root(SOURCE_PATH).findall("optionset")}
    mirror_provider_keys = {optionset.findtext("provider_key") for optionset in _root(CATALOG_PATH).findall("optionset")}

    assert mirror_provider_keys == source_provider_keys


def test_example_catalog_attribute_tree_derives_each_declared_uri():
    source_root_attributes = [
        attribute for attribute in _root(SOURCE_PATH).findall("attribute") if DC_URI not in attribute.find("parent").attrib
    ]
    attribute_elements = _root(CATALOG_PATH).findall("attribute")
    attributes = {attribute.attrib[DC_URI]: attribute for attribute in attribute_elements}

    assert attributes[PLUGIN_DEV_ATTRIBUTE_URI].find("parent").attrib == {}
    assert [attribute for attribute in attribute_elements if not attribute.find("parent").attrib] == [
        attributes[PLUGIN_DEV_ATTRIBUTE_URI]
    ]

    plugin_dev_children = [
        attribute for attribute in attribute_elements if attribute.find("parent").attrib.get(DC_URI) == PLUGIN_DEV_ATTRIBUTE_URI
    ]
    assert len(plugin_dev_children) == len(source_root_attributes)

    for attribute in attribute_elements:
        uri = attribute.attrib[DC_URI]
        keys = [attribute.findtext("key")]
        parent_uri = attribute.find("parent").attrib.get(DC_URI)
        while parent_uri:
            parent = attributes[parent_uri]
            keys.append(parent.findtext("key"))
            parent_uri = parent.find("parent").attrib.get(DC_URI)
        expected_uri = f"{attribute.findtext('uri_prefix')}/domain/{'/'.join(reversed(keys))}"
        assert uri == expected_uri


def test_example_catalog_is_currently_generated():
    assert CATALOG_PATH.read_bytes() == generate_catalog()


def test_owner_question_accepts_sms_names_and_retains_ror_suggestions():
    owner_uri = "https://rdmo.nfdi4earth.de/terms/questions/instrument_owner"
    for path, uri in ((SOURCE_PATH, owner_uri), (CATALOG_PATH, mirror_uri(owner_uri))):
        root = _root(path)
        question = next(element for element in root.findall("question") if element.attrib[DC_URI] == uri)
        assert question.findtext("widget_type") == "select_creatable"
        assert question.findtext("value_type") == "option"
        assert question.findtext("is_collection") == "False"
        optionset_uri = question.find("optionsets/optionset").attrib[DC_URI]
        optionset = next(element for element in root.findall("optionset") if element.attrib[DC_URI] == optionset_uri)
        assert optionset.findtext("provider_key") == "ror"
