from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rdmo.projects.models import Value


class CollectionLayout(Enum):
    QUESTION = "question"
    QUESTIONSET = "questionset"


class CollectionBindingError(ValueError):
    pass


@dataclass(frozen=True)
class CollectionScope:
    set_prefix: str
    set_index: int


@dataclass(frozen=True)
class CollectionBinding:
    project: Any
    attribute: Any
    page_uri: str | None
    layout: CollectionLayout

    @classmethod
    def resolve(cls, project, attribute, page_uri: str | None = None) -> CollectionBinding:
        from rdmo.questions.models import Question, QuestionSet

        catalog_id = project.catalog_id
        question_filters = {
            "is_collection": True,
            "attribute": attribute,
            "pages__sections__catalogs__id": catalog_id,
        }
        questionset_filters = {
            "is_collection": True,
            "questions__attribute": attribute,
            "pages__sections__catalogs__id": catalog_id,
        }
        if page_uri is not None:
            question_filters["pages__uri"] = page_uri
            questionset_filters["pages__uri"] = page_uri

        question_count = Question.objects.filter(**question_filters).distinct().count()
        questionset_count = QuestionSet.objects.filter(**questionset_filters).distinct().count()

        matches = question_count + questionset_count
        if matches != 1:
            location = f" on page {page_uri}" if page_uri else f" in catalog {project.catalog.uri}"
            raise CollectionBindingError(
                f"Expected exactly one collection for attribute {attribute.uri}{location}, "
                f"found {question_count} collection Question(s) and {questionset_count} collection QuestionSet(s)."
            )

        layout = CollectionLayout.QUESTION if question_count == 1 else CollectionLayout.QUESTIONSET
        return cls(project=project, attribute=attribute, page_uri=page_uri, layout=layout)

    def parent_scope_for_value(self, value: Value) -> CollectionScope:
        if self.layout is CollectionLayout.QUESTION:
            return CollectionScope(set_prefix=value.set_prefix or "", set_index=value.set_index)

        return parent_scope_from_child_prefix(value.set_prefix or "")

    def value_lookup(self, parent_scope: CollectionScope, row_index: int) -> dict[str, Any]:
        lookup = {
            "project": self.project,
            "attribute": self.attribute,
            "snapshot": None,
            "set_collection": True,
            **self.scope_lookup(parent_scope),
        }
        if self.layout is CollectionLayout.QUESTION:
            return {
                **lookup,
                "collection_index": row_index,
            }
        return {
            **lookup,
            "set_index": row_index,
            "collection_index": 0,
        }

    def scope_lookup(self, parent_scope: CollectionScope) -> dict[str, Any]:
        if self.layout is CollectionLayout.QUESTION:
            return {
                "set_prefix": parent_scope.set_prefix,
                "set_index": parent_scope.set_index,
            }
        return {"set_prefix": child_scope_prefix(parent_scope)}

    def values_for_scope(self, parent_scope: CollectionScope):
        from rdmo.projects.models import Value

        queryset = Value.objects.filter(
            project=self.project,
            attribute=self.attribute,
            snapshot=None,
            set_collection=True,
            **self.scope_lookup(parent_scope),
        )
        return queryset.order_by(self.row_index_field, "id")

    @property
    def row_index_field(self) -> str:
        if self.layout is CollectionLayout.QUESTION:
            return "collection_index"
        return "set_index"


def scope_from_value(value: Value) -> CollectionScope:
    return CollectionScope(set_prefix=value.set_prefix or "", set_index=value.set_index)


def child_scope_prefix(parent_scope: CollectionScope) -> str:
    if parent_scope.set_prefix:
        return f"{parent_scope.set_prefix}|{parent_scope.set_index}"
    return str(parent_scope.set_index)


def parent_scope_from_child_prefix(child_prefix: str) -> CollectionScope:
    if not child_prefix:
        raise CollectionBindingError("A collection QuestionSet value has no parent scope in set_prefix.")

    if "|" in child_prefix:
        parent_prefix, parent_index = child_prefix.rsplit("|", 1)
    else:
        parent_prefix, parent_index = "", child_prefix

    try:
        set_index = int(parent_index)
    except ValueError as error:
        raise CollectionBindingError(f"Invalid collection QuestionSet prefix: {child_prefix!r}.") from error

    return CollectionScope(set_prefix=parent_prefix, set_index=set_index)
