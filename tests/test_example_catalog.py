from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

from scripts.generate_plugin_dev_assets import TARGET_CATALOG_URI, generate_catalog, mirror_uri

ROOT = Path(__file__).parents[1]
SOURCE_PATH = ROOT / "xml" / "earth-sensor+original.xml"
CATALOG_PATH = ROOT / "xml" / "example_catalog_sensorsearch.xml"
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
    assert Counter(element.tag for element in source) == Counter(element.tag for element in mirror)
    assert mirror_definitions == [mirror_uri(uri) for uri in source_definitions]
    assert _referenced_uris(mirror) == [mirror_uri(uri) for uri in _referenced_uris(source)]
    assert all(uri.startswith("https://example.com/") for uri in mirror_definitions)
    assert all(uri.startswith("https://example.com/") for uri in _referenced_uris(mirror))
    assert all("/terms/" in uri for uri in (*mirror_definitions, *_referenced_uris(mirror)))


def test_example_catalog_uris_are_unique_and_references_resolve():
    root = _root(CATALOG_PATH)
    definitions = _defined_uris(root)

    source_definitions = _defined_uris(_root(SOURCE_PATH))
    assert Counter(definitions) == Counter(mirror_uri(uri) for uri in source_definitions)
    assert set(_referenced_uris(root)) <= set(definitions)


def test_example_catalog_preserves_optionset_provider_keys():
    source_provider_keys = {optionset.findtext("provider_key") for optionset in _root(SOURCE_PATH).findall("optionset")}
    mirror_provider_keys = {optionset.findtext("provider_key") for optionset in _root(CATALOG_PATH).findall("optionset")}

    assert mirror_provider_keys == source_provider_keys


def test_example_catalog_is_currently_generated():
    assert CATALOG_PATH.read_bytes() == generate_catalog()
