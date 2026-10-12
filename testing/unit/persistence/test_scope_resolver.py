from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rdmo_sensorsearch.persistence.scope_resolver import RDMOAnswerTreeScopeResolver, _build_answer_tree


def test_old_api_initializes_without_computing_the_entire_tree():
    class OldTree:
        def __init__(self, catalog, values, verbose=None):
            self.catalog, self.values = catalog, values

        def compute(self):
            raise AssertionError("The old API already initialized its scope index.")

    values = object()
    tree = _build_answer_tree("catalog", values, OldTree)
    assert (tree.catalog, tree.values) == ("catalog", values)


def test_new_api_computes_values_without_treating_them_as_verbose():
    class NewTree:
        def __init__(self, catalog, verbose=None):
            assert verbose is None
            self.catalog = catalog

        def compute(self, values):
            self.values = values

    values = object()
    tree = _build_answer_tree("catalog", values, NewTree)
    assert (tree.catalog, tree.values) == ("catalog", values)


@pytest.mark.parametrize("failure_site", ("constructor", "compute"))
def test_initialization_errors_are_not_retried_or_masked(failure_site):
    class BrokenTree:
        def __init__(self, catalog, verbose=None):
            if failure_site == "constructor":
                raise TypeError("real initialization failure")

        def compute(self, values):
            raise TypeError("real computation failure")

    with pytest.raises(TypeError, match=r"real .* failure"):
        _build_answer_tree("catalog", [], BrokenTree)


def test_unsupported_api_fails_explicitly():
    class UnknownTree:
        def __init__(self, catalog):
            pass

        def compute(self):
            pass

    with pytest.raises(TypeError, match="Unsupported RDMO"):
        _build_answer_tree("catalog", [], UnknownTree)


def _question(attribute_id):
    return SimpleNamespace(attribute_id=attribute_id, _meta=SimpleNamespace(model_name="question"))


def test_nested_scope_resolution_reuses_tree_and_preserves_fallback_and_order():
    source, target = _question(11), _question(21)
    nested = SimpleNamespace(elements=[target], _meta=SimpleNamespace(model_name="questionset"))
    page = SimpleNamespace(attribute_id=None, descendants=[source, target], elements=[source, nested])
    catalog = SimpleNamespace(pages=[page], prefetch_elements=Mock())
    values = Mock()
    live_values = values.filter.return_value.select_related.return_value
    builds = []

    class Tree:
        def __init__(self, catalog, values):
            builds.append((catalog, values))

        def compute_element_sets(self, element, parent_set=None):
            return [("", 2)] if element is page else [("2", 0), ("2", 0)]

    resolver = RDMOAnswerTreeScopeResolver(SimpleNamespace(catalog=catalog, values=values), answer_tree_factory=Tree)
    assert resolver.resolve(11, 21, ("", 2)) == [("2", 0), ("", 2)]
    # Return a defensive copy so a caller cannot corrupt subsequent cached lookups.
    resolver.resolve(11, 21, ("", 2)).clear()
    assert resolver.resolve(11, 21, ("", 2)) == [("2", 0), ("", 2)]
    assert resolver.resolve(11, 99, ("", 2)) == [("", 2)]
    assert resolver.resolve(11, 21, ("", 3)) == [("", 3)]
    assert builds == [(catalog, live_values)]
    catalog.prefetch_elements.assert_called_once_with()
    values.filter.assert_called_once_with(snapshot=None)
    values.filter.return_value.select_related.assert_called_once_with("attribute")
