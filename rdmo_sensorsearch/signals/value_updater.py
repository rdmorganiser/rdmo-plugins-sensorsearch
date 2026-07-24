import logging
from collections.abc import Mapping
from typing import Any

from django.db import transaction

from rdmo.domain.models import Attribute
from rdmo.projects.answers import AnswerTree
from rdmo.projects.models import Value

from rdmo_sensorsearch.handlers.base import CollectionAssignment, HandlerResult
from rdmo_sensorsearch.signals.collection_binding import (
    CollectionBinding,
    CollectionBindingError,
    scope_from_value,
)
from rdmo_sensorsearch.signals.utils import mute_value_post_save

logger = logging.getLogger(__name__)


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


def _change_label(created: bool, changed: bool) -> str:
    if created:
        return "Created"
    if changed:
        return "Updated"
    return "Unchanged"


def build_clear_payload(attribute_mapping: Mapping[str, str]) -> dict[str, object]:
    clear = {}
    for path, attribute_uri in attribute_mapping.items():
        clear[attribute_uri] = [] if "[]" in path else ""
    return clear


def clear_attribute_values(instance, attribute_uri: str) -> None:
    try:
        attribute = Attribute.objects.get(uri=attribute_uri)
    except Attribute.DoesNotExist:
        logger.warning("Clear target attribute not found: %s", attribute_uri)
        return

    with transaction.atomic(), mute_value_post_save():
        deleted_total = 0
        for set_prefix, set_index in _scalar_scopes(instance, attribute):
            queryset = _qs_scalar_for_scope(instance, attribute, set_prefix, set_index)
            deleted, _ = queryset.delete()
            deleted_total += deleted
        logger.info("Cleared values for attribute %s (%s rows)", attribute_uri, deleted_total)


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

    with transaction.atomic(), mute_value_post_save():
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
                _change_label(created, changed),
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

    with transaction.atomic(), mute_value_post_save():
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
                _change_label(created, changed),
                attribute.uri,
                set_prefix,
                set_index,
                normalized_value,
            )


def clear_collection_attribute(instance, attribute_uri: str, page_uri: str) -> None:
    try:
        attribute = Attribute.objects.get(uri=attribute_uri)
    except Attribute.DoesNotExist:
        logger.warning("Collection clear target attribute not found: %s", attribute_uri)
        return

    try:
        binding = CollectionBinding.resolve(instance.project, attribute, page_uri)
    except CollectionBindingError as error:
        logger.warning("Cannot clear collection attribute: %s", error)
        return

    with transaction.atomic(), mute_value_post_save():
        deleted, _ = binding.values_for_scope(scope_from_value(instance)).delete()
        logger.info("Cleared collection values for attribute %s (%s rows)", attribute_uri, deleted)


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


def update_values_from_mapped_data(instance, data: dict):
    if not data:
        return

    with transaction.atomic(), mute_value_post_save():
        scope_cache: dict[int, list[tuple[str, int]]] = {}
        for attribute_uri, value in data.items():
            try:
                attribute = Attribute.objects.get(uri=attribute_uri)
            except Attribute.DoesNotExist:
                continue

            if isinstance(value, list):
                _apply_list(instance, attribute, value)
                continue

            scopes = scope_cache.setdefault(attribute.id, _scalar_scopes(instance, attribute))
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
                _, created, changed = upsert_value_if_changed(
                    {
                        "project": instance.project,
                        "attribute": attribute,
                        "snapshot": None,
                        "set_prefix": primary_set_prefix,
                        "set_index": primary_set_index,
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
                _change_label(created, changed),
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

    def upsert_at(index: int, text: Any):
        _, created, changed = upsert_value_if_changed(
            binding.value_lookup(parent_scope, index),
            {"text": text},
        )
        logger.info(
            "%s collection value for attribute %s at %s=%s: %r",
            _change_label(created, changed),
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
        if not current or (current.text != text and getattr(current, "value", None) != text):
            upsert_at(index, text)
        last_nonblank_index = max(last_nonblank_index, index)

    delete_from(last_nonblank_index + 1)


def update_values_from_handler_result(instance, result: HandlerResult) -> tuple[Any, ...]:
    update_values_from_mapped_data(instance, result.mapped_values)

    if result.collections:
        with transaction.atomic(), mute_value_post_save():
            for collection in result.collections:
                _update_collection_assignment(instance, collection)

    return tuple(post_action() for post_action in result.post_actions)


def _update_collection_assignment(instance, collection: CollectionAssignment):
    try:
        attribute = Attribute.objects.get(uri=collection.attribute_uri)
    except Attribute.DoesNotExist:
        logger.warning("Collection target attribute not found: %s", collection.attribute_uri)
        return

    try:
        binding = CollectionBinding.resolve(instance.project, attribute, collection.page_uri)
    except CollectionBindingError as error:
        logger.warning("Cannot update collection assignment: %s", error)
        return

    parent_scope = scope_from_value(instance)
    desired_indexes = set()

    for index, value in enumerate(collection.values):
        if not isinstance(value, dict):
            logger.warning("Collection value must be a dictionary, got %s", type(value).__name__)
            continue

        desired_indexes.add(index)
        defaults = {"text": value.get("text", "")}
        if "external_id" in value:
            defaults["external_id"] = value.get("external_id")

        _, created, changed = upsert_value_if_changed(
            binding.value_lookup(parent_scope, index),
            defaults,
        )
        logger.info(
            "%s handler collection value for attribute %s using %s at %s=%s: %r",
            _change_label(created, changed),
            attribute.uri,
            binding.layout.value,
            binding.row_index_field,
            index,
            defaults,
        )

    if collection.replace_existing:
        _delete_surplus_collection_values(binding, parent_scope, desired_indexes)


def _delete_surplus_collection_values(binding, parent_scope, desired_indexes: set[int]):
    queryset = binding.values_for_scope(parent_scope)
    if desired_indexes:
        queryset = queryset.exclude(**{f"{binding.row_index_field}__in": desired_indexes})

    deleted, _ = queryset.delete()
    if deleted:
        logger.info("Deleted surplus collection values for attribute %s (%s rows)", binding.attribute.uri, deleted)


def _normalize_set_prefix(set_prefix: str | None) -> str:
    return set_prefix or ""


def _scalar_scopes(instance, attribute) -> list[tuple[str, int]]:
    return _scalar_scopes_via_answer_tree(instance, attribute)


def _scalar_scopes_via_answer_tree(instance, attribute) -> list[tuple[str, int]]:
    base_scope = (_normalize_set_prefix(instance.set_prefix), instance.set_index)
    project = instance.project
    catalog = project.catalog

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
