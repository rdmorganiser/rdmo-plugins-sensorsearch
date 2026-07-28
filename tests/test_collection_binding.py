import sys
from dataclasses import dataclass
from types import ModuleType

import pytest

from rdmo_sensorsearch.signals.collection_binding import (
    CollectionBinding,
    CollectionBindingError,
    CollectionLayout,
    CollectionScope,
    child_scope_prefix,
    parent_scope_from_child_prefix,
)


@dataclass(frozen=True)
class FakeCatalog:
    uri: str = "https://example.com/catalog"


@dataclass(frozen=True)
class FakeProject:
    catalog_id: int = 1
    catalog: FakeCatalog = FakeCatalog()


@dataclass(frozen=True)
class FakeAttribute:
    uri: str = "https://example.com/selected-devices"


@dataclass(frozen=True)
class FakeValue:
    set_prefix: str
    set_index: int


class FakeQuerySet:
    def __init__(self, count):
        self._count = count

    def distinct(self):
        return self

    def count(self):
        return self._count


class FakeManager:
    def __init__(self, count):
        self._count = count
        self.filters = []

    def filter(self, **filters):
        self.filters.append(filters)
        return FakeQuerySet(self._count)


class FakeValueQuerySet:
    def __init__(self, filters):
        self.filters = filters
        self.ordering = ()

    def order_by(self, *fields):
        self.ordering = fields
        return self


class FakeValueManager:
    def __init__(self):
        self.querysets = []

    def filter(self, **filters):
        queryset = FakeValueQuerySet(filters)
        self.querysets.append(queryset)
        return queryset


def make_binding(layout: CollectionLayout) -> CollectionBinding:
    return CollectionBinding(
        project=FakeProject(),
        attribute=FakeAttribute(),
        page_uri="https://example.com/configurations",
        layout=layout,
    )


def install_question_model_stubs(monkeypatch, question_count, questionset_count):
    questions = ModuleType("rdmo.questions")
    models = ModuleType("rdmo.questions.models")

    class FakeQuestion:
        objects = FakeManager(question_count)

    class FakeQuestionSet:
        objects = FakeManager(questionset_count)

    models.Question = FakeQuestion
    models.QuestionSet = FakeQuestionSet
    questions.models = models
    monkeypatch.setitem(sys.modules, "rdmo.questions", questions)
    monkeypatch.setitem(sys.modules, "rdmo.questions.models", models)
    return FakeQuestion, FakeQuestionSet


def install_value_model_stub(monkeypatch):
    projects = ModuleType("rdmo.projects")
    models = ModuleType("rdmo.projects.models")

    class StubValue:
        objects = FakeValueManager()

    models.Value = StubValue
    projects.models = models
    monkeypatch.setitem(sys.modules, "rdmo.projects", projects)
    monkeypatch.setitem(sys.modules, "rdmo.projects.models", models)
    return StubValue


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (CollectionScope("", 2), "2"),
        (CollectionScope("4", 2), "4|2"),
        (CollectionScope("1|4", 2), "1|4|2"),
    ],
)
def test_child_scope_prefix(scope, expected):
    assert child_scope_prefix(scope) == expected


@pytest.mark.parametrize(
    ("child_prefix", "expected"),
    [
        ("2", CollectionScope("", 2)),
        ("4|2", CollectionScope("4", 2)),
        ("1|4|2", CollectionScope("1|4", 2)),
    ],
)
def test_parent_scope_from_child_prefix(child_prefix, expected):
    assert parent_scope_from_child_prefix(child_prefix) == expected


@pytest.mark.parametrize("child_prefix", ["", "root|invalid"])
def test_parent_scope_rejects_invalid_child_prefix(child_prefix):
    with pytest.raises(CollectionBindingError):
        parent_scope_from_child_prefix(child_prefix)


def test_collection_question_uses_configuration_coordinates_and_collection_index():
    binding = make_binding(CollectionLayout.QUESTION)
    scope = CollectionScope("1|4", 2)

    assert binding.parent_scope_for_value(FakeValue(set_prefix="1|4", set_index=2)) == scope
    assert binding.scope_lookup(scope) == {
        "set_prefix": "1|4",
        "set_index": 2,
    }
    assert binding.value_lookup(scope, 3) == {
        "project": binding.project,
        "attribute": binding.attribute,
        "snapshot": None,
        "set_collection": True,
        "set_prefix": "1|4",
        "set_index": 2,
        "collection_index": 3,
    }
    assert binding.row_index_field == "collection_index"


def test_collection_questionset_uses_child_prefix_and_set_index():
    binding = make_binding(CollectionLayout.QUESTIONSET)
    scope = CollectionScope("1|4", 2)

    assert binding.parent_scope_for_value(FakeValue(set_prefix="1|4|2", set_index=3)) == scope
    assert binding.scope_lookup(scope) == {"set_prefix": "1|4|2"}
    assert binding.value_lookup(scope, 3) == {
        "project": binding.project,
        "attribute": binding.attribute,
        "snapshot": None,
        "set_collection": True,
        "set_prefix": "1|4|2",
        "set_index": 3,
        "collection_index": 0,
    }
    assert binding.row_index_field == "set_index"


@pytest.mark.parametrize(
    ("active_layout", "parent_scope", "expected_layout", "expected_scope", "expected_ordering"),
    [
        (
            CollectionLayout.QUESTION,
            CollectionScope("", 2),
            CollectionLayout.QUESTIONSET,
            {"set_prefix": "2"},
            ("set_index", "id"),
        ),
        (
            CollectionLayout.QUESTIONSET,
            CollectionScope("", 2),
            CollectionLayout.QUESTION,
            {"set_prefix": "", "set_index": 2},
            ("collection_index", "id"),
        ),
        (
            CollectionLayout.QUESTION,
            CollectionScope("1|4", 2),
            CollectionLayout.QUESTIONSET,
            {"set_prefix": "1|4|2"},
            ("set_index", "id"),
        ),
        (
            CollectionLayout.QUESTIONSET,
            CollectionScope("1|4", 2),
            CollectionLayout.QUESTION,
            {"set_prefix": "1|4", "set_index": 2},
            ("collection_index", "id"),
        ),
    ],
)
def test_opposite_values_use_the_inactive_layout_coordinates(
    monkeypatch,
    active_layout,
    parent_scope,
    expected_layout,
    expected_scope,
    expected_ordering,
):
    value_model = install_value_model_stub(monkeypatch)
    binding = make_binding(active_layout)

    queryset = binding.opposite_values_for_scope(parent_scope)

    assert binding.opposite_layout is expected_layout
    assert binding.layout is active_layout
    assert queryset.filters == {
        "project": binding.project,
        "attribute": binding.attribute,
        "snapshot": None,
        "set_collection": True,
        **expected_scope,
    }
    assert queryset.ordering == expected_ordering
    assert len(value_model.objects.querysets) == 1


@pytest.mark.parametrize(
    ("question_count", "questionset_count", "expected_layout"),
    [
        (1, 0, CollectionLayout.QUESTION),
        (0, 1, CollectionLayout.QUESTIONSET),
    ],
)
def test_resolve_selects_the_single_layout_on_the_configured_page(
    monkeypatch,
    question_count,
    questionset_count,
    expected_layout,
):
    question, questionset = install_question_model_stubs(monkeypatch, question_count, questionset_count)
    project = FakeProject()
    attribute = FakeAttribute()
    page_uri = "https://example.com/configurations"

    binding = CollectionBinding.resolve(project, attribute, page_uri)

    assert binding.layout is expected_layout
    assert question.objects.filters[0]["pages__uri"] == page_uri
    assert questionset.objects.filters[0]["pages__uri"] == page_uri
    assert question.objects.filters[0]["pages__sections__catalogs__id"] == project.catalog_id


@pytest.mark.parametrize(("question_count", "questionset_count"), [(0, 0), (1, 1), (2, 0)])
def test_resolve_rejects_missing_or_ambiguous_layouts(monkeypatch, question_count, questionset_count):
    install_question_model_stubs(monkeypatch, question_count, questionset_count)

    with pytest.raises(CollectionBindingError):
        CollectionBinding.resolve(FakeProject(), FakeAttribute(), "https://example.com/configurations")
