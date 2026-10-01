"""Reconcile backend-derived values with persisted RDMO answers."""

import logging
from typing import Any

from django.db import transaction

from rdmo.domain.models import Attribute
from rdmo.projects.answers import AnswerTree
from rdmo.projects.models import Value

from rdmo_sensorsearch.handlers.base import (
    CollectionAssignment,
    HandlerResult,
    MergedTextScalar,
    deduplicate_collection_values,
)
from rdmo_sensorsearch.persistence.catalog_context import workflow_catalog_context
from rdmo_sensorsearch.persistence.collection_binding import (
    CollectionBinding,
    CollectionBindingError,
    scope_from_value,
)
from rdmo_sensorsearch.services.performance import measure_phase
from rdmo_sensorsearch.services.synchronization_context import mute_value_sync

logger = logging.getLogger(__name__)


class _ScalarScopeResolver:
    """Reuse one project value index while resolving all fields in one result."""

    @measure_phase("scalar.scope_setup")
    def __init__(self, instance):
        self.project = instance.project
        self.catalog = self.project.catalog
        self.catalog.prefetch_elements()
        values = self.project.values.filter(snapshot=None).select_related("attribute")
        self.answer_tree = AnswerTree(self.catalog, values)
        self._scopes_by_key: dict[tuple[int, int, str, int], list[tuple[str, int]]] = {}

    def resolve(self, instance, attribute) -> list[tuple[str, int]]:
        base_scope = (_normalize_set_prefix(instance.set_prefix), instance.set_index)
        key = (instance.attribute_id, attribute.id, *base_scope)
        cached = self._scopes_by_key.get(key)
        if cached is not None:
            return cached

        scopes = _scalar_scopes_via_answer_tree(instance, attribute, answer_tree=self.answer_tree)
        self._scopes_by_key[key] = scopes
        return scopes


def _attributes_by_uri(attribute_uris) -> dict[str, Attribute]:
    attributes: dict[str, Attribute] = {}
    for attribute in Attribute.objects.filter(uri__in=set(attribute_uris)).order_by("id"):
        attributes.setdefault(attribute.uri, attribute)
    return attributes


def _is_blank_scalar(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, (int, float, bool)):
        return value
    return value if value is None else str(value)


def _field_matches(value: Value, field: str, expected: Any) -> bool:
    # Use persisted fields for update decisions. RDMO's display properties
    # (`value`, `label`, `value_and_unit`) can format dates, options, files, and
    # booleans differently from the stored database value.
    return getattr(value, field) == expected


def update_value_if_changed(value: Value, **updates: Any) -> bool:
    changed_fields = [field for field, expected in updates.items() if not _field_matches(value, field, expected)]
    if not changed_fields:
        return False

    for field in changed_fields:
        setattr(value, field, updates[field])
    value.save(update_fields=changed_fields)
    return True


def upsert_value_if_changed(lookup: dict[str, Any], defaults: dict[str, Any]) -> tuple[Value, bool, bool]:
    value = Value.objects.filter(**lookup).order_by("id").first()
    if value is None:
        return Value.objects.create(**lookup, **defaults), True, True
    return value, False, update_value_if_changed(value, **defaults)


def format_change_label(created: bool, changed: bool) -> str:
    if created:
        return "Created"
    if changed:
        return "Updated"
    return "Unchanged"


def reconcile_mapped_values(
    instance,
    handler,
    mapped_values,
    excluded_attribute_uris: set[str] | None = None,
) -> None:
    apply_mapped_values(
        instance,
        handler.build_authoritative_mapped_values(
            mapped_values,
            excluded_attribute_uris=excluded_attribute_uris,
        ),
    )


def update_scalar_value_across_scopes(
    instance,
    attribute_uri: str,
    value: Any,
    extra_scopes: list[tuple[str, int]] | None = None,
) -> None:
    try:
        attribute = Attribute.objects.get(uri=attribute_uri)
    except Attribute.DoesNotExist:
        logger.warning("Scalar scope update target attribute not found: %s", attribute_uri)
        return

    scopes = _scalar_scopes(instance, attribute)
    if not scopes:
        scopes = [(_normalize_set_prefix(instance.set_prefix), instance.set_index)]
    if extra_scopes:
        scopes = _unique_scopes(scopes + extra_scopes, (_normalize_set_prefix(instance.set_prefix), instance.set_index))

    with transaction.atomic(), mute_value_sync():
        if _is_blank_scalar(value):
            deleted_total = 0
            for set_prefix, set_index in scopes:
                deleted, _ = _qs_scalar_for_scope(instance, attribute, set_prefix, set_index).delete()
                deleted_total += deleted
            logger.info("Cleared scalar values across scopes for attribute %s (%s rows)", attribute.uri, deleted_total)
            return

        normalized_value = _normalize_scalar(value)
        for set_prefix, set_index in scopes:
            queryset = _qs_scalar_for_scope(instance, attribute, set_prefix, set_index).order_by("id")
            current = queryset.first()

            if current is None:
                _, created, changed = upsert_value_if_changed(
                    {
                        "project": instance.project,
                        "attribute": attribute,
                        "snapshot": None,
                        "set_prefix": set_prefix,
                        "set_index": set_index,
                        "set_collection": False,
                    },
                    {"text": normalized_value},
                )
            else:
                created = False
                changed = update_value_if_changed(current, text=normalized_value)

                duplicate_ids = list(queryset.values_list("id", flat=True)[1:])
                if duplicate_ids:
                    deleted, _ = queryset.exclude(id=current.id).delete()
                    logger.info(
                        "Deleted duplicate scalar values for attribute %s (%s rows)",
                        attribute.uri,
                        deleted,
                    )

            logger.info(
                "%s scalar value across scope for attribute %s (set_prefix=%s, set_index=%s): %r",
                format_change_label(created, changed),
                attribute.uri,
                set_prefix,
                set_index,
                normalized_value,
            )


def replace_scalar_value_in_scopes(
    instance,
    attribute_uri: str,
    value: Any,
    scopes_to_set: list[tuple[str, int]],
    scopes_to_clear: list[tuple[str, int]] | None = None,
) -> None:
    try:
        attribute = Attribute.objects.get(uri=attribute_uri)
    except Attribute.DoesNotExist:
        logger.warning("Scoped scalar update target attribute not found: %s", attribute_uri)
        return

    normalized_scopes_to_set = list(dict.fromkeys(scopes_to_set))
    normalized_scopes_to_clear = list(dict.fromkeys(scopes_to_clear or []))

    with transaction.atomic(), mute_value_sync():
        for set_prefix, set_index in normalized_scopes_to_clear:
            deleted, _ = _qs_scalar_for_scope(instance, attribute, set_prefix, set_index).delete()
            if deleted:
                logger.info(
                    "Cleared scoped scalar value for attribute %s (set_prefix=%s, set_index=%s, rows=%s)",
                    attribute.uri,
                    set_prefix,
                    set_index,
                    deleted,
                )

        if _is_blank_scalar(value):
            for set_prefix, set_index in normalized_scopes_to_set:
                deleted, _ = _qs_scalar_for_scope(instance, attribute, set_prefix, set_index).delete()
                if deleted:
                    logger.info(
                        "Cleared scoped scalar value for attribute %s (set_prefix=%s, set_index=%s, rows=%s)",
                        attribute.uri,
                        set_prefix,
                        set_index,
                        deleted,
                    )
            return

        normalized_value = _normalize_scalar(value)
        for set_prefix, set_index in normalized_scopes_to_set:
            queryset = _qs_scalar_for_scope(instance, attribute, set_prefix, set_index).order_by("id")
            current = queryset.first()

            if current is None:
                _, created, changed = upsert_value_if_changed(
                    {
                        "project": instance.project,
                        "attribute": attribute,
                        "snapshot": None,
                        "set_prefix": set_prefix,
                        "set_index": set_index,
                        "set_collection": False,
                    },
                    {"text": normalized_value},
                )
            else:
                created = False
                changed = update_value_if_changed(current, text=normalized_value)

                duplicate_ids = list(queryset.values_list("id", flat=True)[1:])
                if duplicate_ids:
                    deleted, _ = queryset.exclude(id=current.id).delete()
                    logger.info(
                        "Deleted duplicate scalar values for attribute %s (%s rows)",
                        attribute.uri,
                        deleted,
                    )

            logger.info(
                "%s scoped scalar value for attribute %s (set_prefix=%s, set_index=%s): %r",
                format_change_label(created, changed),
                attribute.uri,
                set_prefix,
                set_index,
                normalized_value,
            )


def _qs_scalar_for_scope(instance, attribute, set_prefix: str, set_index: int):
    queryset = Value.objects.filter(
        project=instance.project,
        attribute=attribute,
        snapshot=None,
        set_index=set_index,
        set_collection=False,
        set_prefix=set_prefix,
    )
    return queryset


def _apply_merged_text_scalar(instance, attribute, value: MergedTextScalar, scopes: list[tuple[str, int]]) -> None:
    """Merge names in this answer's scopes, preserving unchanged provider selections."""
    if not value.values:
        return
    existing_values = [
        current
        for set_prefix, set_index in scopes
        for current in (_qs_scalar_for_scope(instance, attribute, set_prefix, set_index).select_related("option").order_by("id"))
    ]
    names = list(dict.fromkeys(name.strip() for current in existing_values for name in current.label.split(";") if name.strip()))
    new_names = [name.strip() for raw_name in value.values for name in raw_name.split(";") if name.strip()]
    merged_names = list(dict.fromkeys([*names, *new_names]))
    if merged_names == names:
        return

    text = "; ".join(merged_names)
    primary_set_prefix, primary_set_index = scopes[0]
    primary_values = _qs_scalar_for_scope(instance, attribute, primary_set_prefix, primary_set_index).order_by("id")
    current = primary_values.first()
    updates = {"text": text, "value_type": "option", "external_id": "", "option": None}
    if current is None:
        current = Value.objects.create(
            project=instance.project,
            attribute=attribute,
            snapshot=None,
            set_prefix=primary_set_prefix,
            set_index=primary_set_index,
            set_collection=False,
            **updates,
        )
    else:
        update_value_if_changed(current, **updates)
    # Preserve the names from legacy/duplicate rows before consolidating them.
    for set_prefix, set_index in scopes:
        _qs_scalar_for_scope(instance, attribute, set_prefix, set_index).exclude(id=current.id).delete()
    logger.info("Merged scalar names for attribute %s: %r", attribute.uri, text)


@measure_phase("scalar.apply")
def apply_mapped_values(instance, mapped_values: dict):
    if not mapped_values:
        return

    with transaction.atomic(), mute_value_sync():
        attributes = _attributes_by_uri(mapped_values)
        scope_resolver: _ScalarScopeResolver | None = None
        scope_cache: dict[int, list[tuple[str, int]]] = {}
        for attribute_uri, value in mapped_values.items():
            attribute = attributes.get(attribute_uri)
            if attribute is None:
                continue

            if isinstance(value, list):
                _apply_list(instance, attribute, value)
                continue

            if scope_resolver is None:
                scope_resolver = _ScalarScopeResolver(instance)
            scopes = scope_cache.setdefault(attribute.id, _scalar_scopes(instance, attribute, scope_resolver))
            if not scopes:
                scopes = [(_normalize_set_prefix(instance.set_prefix), instance.set_index)]
            if len(scopes) > 1:
                logger.debug(
                    "Resolved scalar scopes for attribute %s: %s",
                    attribute.uri,
                    scopes,
                )
            primary_set_prefix, primary_set_index = scopes[0]
            secondary_scopes = scopes[1:]

            if isinstance(value, MergedTextScalar):
                _apply_merged_text_scalar(instance, attribute, value, scopes)
                continue

            if _is_blank_scalar(value):
                deleted_total = 0
                for set_prefix, set_index in scopes:
                    deleted, _ = _qs_scalar_for_scope(instance, attribute, set_prefix, set_index).delete()
                    deleted_total += deleted
                logger.info("Cleared scalar values for attribute %s (%s rows)", attribute.uri, deleted_total)
                continue

            normalized_value = _normalize_scalar(value)
            queryset = _qs_scalar_for_scope(
                instance,
                attribute,
                primary_set_prefix,
                primary_set_index,
            ).order_by("id")
            current = queryset.first()

            if current is None:
                Value.objects.create(
                    project=instance.project,
                    attribute=attribute,
                    snapshot=None,
                    set_prefix=primary_set_prefix,
                    set_index=primary_set_index,
                    set_collection=False,
                    text=normalized_value,
                )
                created = changed = True
            else:
                created = False
                changed = update_value_if_changed(current, text=normalized_value)

                duplicate_ids = list(queryset.values_list("id", flat=True)[1:])
                if duplicate_ids:
                    deleted, _ = queryset.exclude(id=current.id).delete()
                    logger.info(
                        "Deleted duplicate scalar values for attribute %s (%s rows)",
                        attribute.uri,
                        deleted,
                    )

            for set_prefix, set_index in secondary_scopes:
                deleted, _ = _qs_scalar_for_scope(instance, attribute, set_prefix, set_index).delete()
                if deleted:
                    logger.info(
                        "Deleted scalar values in secondary scope for attribute %s (set_prefix=%s, set_index=%s, rows=%s)",
                        attribute.uri,
                        set_prefix,
                        set_index,
                        deleted,
                    )
            logger.info(
                "%s scalar value for attribute %s: %r",
                format_change_label(created, changed),
                attribute.uri,
                normalized_value,
            )


def _apply_list(instance, attribute, items: list[Any]) -> None:
    try:
        binding = CollectionBinding.resolve(instance.project, attribute)
    except CollectionBindingError as error:
        logger.warning("Cannot apply list value: %s", error)
        return

    parent_scope = scope_from_value(instance)
    queryset = binding.values_for_scope(parent_scope)

    if not items:
        deleted, _ = queryset.delete()
        logger.info("Cleared collection values for attribute %s (%s rows)", attribute.uri, deleted)
        return

    row_index_field = binding.row_index_field
    existing = {getattr(value, row_index_field): value for value in queryset.only("id", row_index_field, "text")}

    def upsert_at(index: int, text: Any, current=None):
        if current is None:
            Value.objects.create(**binding.value_lookup(parent_scope, index), text=text)
            created = changed = True
        else:
            created = False
            changed = update_value_if_changed(current, text=text)
        logger.info(
            "%s collection value for attribute %s at %s=%s: %r",
            format_change_label(created, changed),
            attribute.uri,
            row_index_field,
            index,
            text,
        )

    def delete_index(index: int):
        deleted, _ = queryset.filter(**{row_index_field: index}).delete()
        if deleted:
            logger.info(
                "Deleted collection value for attribute %s at %s=%s",
                attribute.uri,
                row_index_field,
                index,
            )

    def delete_from(start: int):
        deleted, _ = queryset.filter(**{f"{row_index_field}__gte": start}).delete()
        if deleted:
            logger.info(
                "Deleted surplus collection values for attribute %s from %s=%s (%s rows)",
                attribute.uri,
                row_index_field,
                start,
                deleted,
            )

    last_nonblank_index = -1
    for index, raw_value in enumerate(items):
        if _is_blank_scalar(raw_value):
            delete_index(index)
            continue

        text = _normalize_scalar(raw_value)
        current = existing.get(index)
        if not current or current.text != text:
            upsert_at(index, text, current=current)
        last_nonblank_index = max(last_nonblank_index, index)

    delete_from(last_nonblank_index + 1)


@workflow_catalog_context()
def reconcile_handler_result(
    instance,
    handler,
    result: HandlerResult,
    excluded_attribute_uris: set[str] | None = None,
) -> tuple:
    collection_attribute_uris = {collection.attribute_uri for collection in result.collections}
    scalar_exclusions = set(excluded_attribute_uris or ())
    scalar_exclusions.update(collection_attribute_uris)
    reconcile_mapped_values(
        instance,
        handler,
        result.mapped_values,
        excluded_attribute_uris=scalar_exclusions,
    )

    if result.collections:
        with transaction.atomic(), mute_value_sync():
            for collection in result.collections:
                _update_collection_assignment(instance, collection)

    return tuple(result.post_actions)


def _update_collection_assignment(instance, collection: CollectionAssignment):
    invalid_value_types = {type(value).__name__ for value in collection.values if not isinstance(value, dict)}
    if invalid_value_types:
        raise TypeError(f"Collection values must be dictionaries, got {', '.join(sorted(invalid_value_types))}.")

    collection_values = deduplicate_collection_values(collection.values)
    duplicate_count = len(collection.values) - len(collection_values)
    if duplicate_count:
        logger.warning(
            "Discarding %s duplicate collection value(s) for attribute %s",
            duplicate_count,
            collection.attribute_uri,
        )

    try:
        attribute = Attribute.objects.get(uri=collection.attribute_uri)
    except Attribute.DoesNotExist as error:
        raise ValueError(f"Collection target attribute not found: {collection.attribute_uri}") from error

    try:
        binding = CollectionBinding.resolve(instance.project, attribute, collection.page_uri)
    except CollectionBindingError as error:
        raise ValueError(f"Cannot update collection assignment: {error}") from error

    parent_scope = scope_from_value(instance)
    desired_indexes = set()
    existing_values = list(binding.values_for_scope(parent_scope))
    existing_by_external_id = {}
    for value in existing_values:
        if value.external_id:
            existing_by_external_id.setdefault(value.external_id, value)
    existing_by_index = {getattr(value, binding.row_index_field): value for value in existing_values}
    next_index = max(existing_by_index, default=-1) + 1

    for desired_index, value in enumerate(collection_values):
        external_id = value.get("external_id")
        existing = existing_by_external_id.get(external_id) if external_id else existing_by_index.get(desired_index)
        if existing is not None:
            row_index = getattr(existing, binding.row_index_field)
        else:
            row_index = next_index
            next_index += 1

        desired_indexes.add(row_index)
        defaults = {"text": value.get("text", "")}
        if "external_id" in value:
            defaults["external_id"] = value.get("external_id")

        if existing is None:
            Value.objects.create(**binding.value_lookup(parent_scope, row_index), **defaults)
            created = changed = True
        else:
            created = False
            changed = update_value_if_changed(existing, **defaults)
        logger.info(
            "%s handler collection value for attribute %s using %s at %s=%s: %r",
            format_change_label(created, changed),
            attribute.uri,
            binding.layout.value,
            binding.row_index_field,
            row_index,
            defaults,
        )

    if collection.replace_existing:
        _delete_surplus_collection_values(binding, parent_scope, desired_indexes)
        _delete_inactive_collection_values(binding, parent_scope)


def _delete_surplus_collection_values(binding, parent_scope, desired_indexes: set[int]):
    queryset = binding.values_for_scope(parent_scope)
    if desired_indexes:
        queryset = queryset.exclude(**{f"{binding.row_index_field}__in": desired_indexes})

    deleted, _ = queryset.delete()
    if deleted:
        logger.info("Deleted surplus collection values for attribute %s (%s rows)", binding.attribute.uri, deleted)


def _delete_inactive_collection_values(binding, parent_scope):
    deleted, _ = binding.opposite_values_for_scope(parent_scope).delete()
    if deleted:
        logger.info(
            "Deleted inactive %s collection values for attribute %s (%s rows)",
            binding.opposite_layout.value,
            binding.attribute.uri,
            deleted,
        )


def _normalize_set_prefix(set_prefix: str | None) -> str:
    return set_prefix or ""


def _scalar_scopes(instance, attribute, resolver: _ScalarScopeResolver | None = None) -> list[tuple[str, int]]:
    if resolver is None:
        resolver = _ScalarScopeResolver(instance)
    return resolver.resolve(instance, attribute)


def _scalar_scopes_via_answer_tree(instance, attribute, *, answer_tree=None) -> list[tuple[str, int]]:
    base_scope = (_normalize_set_prefix(instance.set_prefix), instance.set_index)
    project = instance.project
    catalog = project.catalog

    if answer_tree is None:
        catalog.prefetch_elements()
        values = project.values.filter(snapshot=None).select_related("attribute")
        answer_tree = AnswerTree(catalog, values)

    discovered_scopes: list[tuple[str, int]] = []
    for page in catalog.pages:
        if not _element_contains_attribute(page, instance.attribute_id):
            continue
        if not _element_contains_attribute(page, attribute.id):
            continue

        page_sets = answer_tree.compute_element_sets(page, parent_set=None)
        for page_set in page_sets:
            trigger_scopes = _collect_question_scopes(answer_tree, page, page_set, instance.attribute_id)
            if base_scope not in trigger_scopes:
                continue

            discovered_scopes.extend(_collect_question_scopes(answer_tree, page, page_set, attribute.id))

    return _unique_scopes(discovered_scopes, base_scope)


def _unique_scopes(discovered_scopes: list[tuple[str, int]], base_scope: tuple[str, int]) -> list[tuple[str, int]]:
    ordered_scopes: list[tuple[str, int]] = []
    for scope in [*discovered_scopes, base_scope]:
        if scope not in ordered_scopes:
            ordered_scopes.append(scope)
    return ordered_scopes


def _element_contains_attribute(element, attribute_id: int) -> bool:
    if getattr(element, "attribute_id", None) == attribute_id:
        return True
    return any(getattr(descendant, "attribute_id", None) == attribute_id for descendant in element.descendants)


def _collect_question_scopes(
    answer_tree: AnswerTree,
    element,
    parent_set: tuple[str, int],
    attribute_id: int,
) -> list[tuple[str, int]]:
    scopes: list[tuple[str, int]] = []
    for child in element.elements:
        child_type = child._meta.model_name
        if child_type == "question":
            if child.attribute_id == attribute_id:
                scopes.append(parent_set)
            continue

        if child_type == "questionset":
            child_sets = answer_tree.compute_element_sets(child, parent_set)
            for child_set in child_sets:
                scopes.extend(_collect_question_scopes(answer_tree, child, child_set, attribute_id))

    return scopes
