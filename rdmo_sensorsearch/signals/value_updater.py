import logging
from collections.abc import Mapping
from typing import Any

from django.db import transaction

from rdmo.domain.models import Attribute
from rdmo.projects.models import Value
from rdmo.questions.models import Question, QuestionSet

from rdmo_sensorsearch.handlers.base import CollectionAssignment, HandlerResult
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

    queryset = Value.objects.filter(
        project=instance.project,
        attribute=attribute,
        set_index=instance.set_index,
    )
    if instance.set_prefix is None:
        queryset = queryset.filter(set_prefix__isnull=True)
    else:
        queryset = queryset.filter(set_prefix=instance.set_prefix)

    with transaction.atomic(), mute_value_post_save():
        deleted, _ = queryset.delete()
        logger.info("Cleared values for attribute %s (%s rows)", attribute_uri, deleted)


def clear_collection_attribute(instance, attribute_uri: str) -> None:
    try:
        attribute = Attribute.objects.get(uri=attribute_uri)
    except Attribute.DoesNotExist:
        logger.warning("Collection clear target attribute not found: %s", attribute_uri)
        return

    mode = _collection_shape(instance, attribute)
    if mode is None:
        logger.warning("Cannot clear collection attribute without collection shape: %s", attribute_uri)
        return

    with transaction.atomic(), mute_value_post_save():
        deleted, _ = _qs_collection(instance, attribute, mode).delete()
        logger.info("Cleared collection values for attribute %s (%s rows)", attribute_uri, deleted)


def _collection_shape(instance, attribute) -> str | None:
    question_match_count = Question.objects.filter(
        is_collection=True,
        attribute=attribute,
        pages__sections__catalogs__id__exact=instance.project.catalog.id,
    ).count()

    question_set_match_count = QuestionSet.objects.filter(
        is_collection=True,
        pages__sections__catalogs__id__exact=instance.project.catalog.id,
        questions__attribute=attribute,
    ).count()

    if question_match_count == 1 and question_set_match_count == 0:
        return "question"
    if question_set_match_count > 0:
        return "questionset"
    return None


def _qs_scalar(instance, attribute):
    queryset = Value.objects.filter(
        project=instance.project,
        attribute=attribute,
        set_index=instance.set_index,
        set_collection=False,
    )
    if instance.set_prefix is None:
        return queryset.filter(set_prefix__isnull=True)
    return queryset.filter(set_prefix=instance.set_prefix)


def _qs_collection(instance, attribute, mode: str):
    if mode == "question":
        return Value.objects.filter(
            project=instance.project,
            attribute=attribute,
            set_collection=True,
            set_index=instance.set_index,
        )
    return Value.objects.filter(
        project=instance.project,
        attribute=attribute,
        set_collection=True,
        set_prefix=instance.set_index,
    )


def update_values_from_mapped_data(instance, data: dict):
    if not data:
        return

    with transaction.atomic(), mute_value_post_save():
        for attribute_uri, value in data.items():
            try:
                attribute = Attribute.objects.get(uri=attribute_uri)
            except Attribute.DoesNotExist:
                continue

            if isinstance(value, list):
                _apply_list(instance, attribute, value)
                continue

            if _is_blank_scalar(value):
                deleted, _ = _qs_scalar(instance, attribute).delete()
                logger.info("Cleared scalar values for attribute %s (%s rows)", attribute.uri, deleted)
                continue

            normalized_value = _normalize_scalar(value)
            queryset = _qs_scalar(instance, attribute).order_by("id")
            current = queryset.first()

            if current is None:
                _, created = Value.objects.update_or_create(
                    project=instance.project,
                    attribute=attribute,
                    set_prefix=instance.set_prefix,
                    set_index=instance.set_index,
                    set_collection=False,
                    defaults={"text": normalized_value},
                )
            else:
                created = False
                if current.text != normalized_value and getattr(current, "value", None) != normalized_value:
                    current.text = normalized_value
                    current.save(update_fields=["text"])

                duplicate_ids = list(queryset.values_list("id", flat=True)[1:])
                if duplicate_ids:
                    deleted, _ = queryset.exclude(id=current.id).delete()
                    logger.info(
                        "Deleted duplicate scalar values for attribute %s (%s rows)",
                        attribute.uri,
                        deleted,
                    )
            logger.info(
                "%s scalar value for attribute %s: %r",
                "Created" if created else "Updated",
                attribute.uri,
                normalized_value,
            )


def _apply_list(instance, attribute, items: list[Any]) -> None:
    mode = _collection_shape(instance, attribute)

    if mode is None:
        logger.warning(
            "List value found, but no matching Question or QuestionSet with is_collection flag. Attribute: %s",
            attribute,
        )
        Value.objects.filter(
            project=instance.project,
            attribute=attribute,
            set_collection=True,
            set_index=instance.set_index,
        ).delete()
        Value.objects.filter(
            project=instance.project,
            attribute=attribute,
            set_collection=True,
            set_prefix=instance.set_index,
        ).delete()
        logger.info("Cleared stray collection values for attribute %s", attribute.uri)
        return

    queryset = _qs_collection(instance, attribute, mode)

    if not items:
        deleted, _ = queryset.delete()
        logger.info("Cleared collection values for attribute %s (%s rows)", attribute.uri, deleted)
        return

    if mode == "question":
        existing = {value.collection_index: value for value in queryset.only("id", "collection_index", "text")}

        def upsert_at(index: int, text: Any):
            _, created = Value.objects.update_or_create(
                project=instance.project,
                attribute=attribute,
                set_collection=True,
                set_index=instance.set_index,
                collection_index=index,
                defaults={"text": text},
            )
            logger.info(
                "%s collection value for attribute %s at collection_index=%s: %r",
                "Created" if created else "Updated",
                attribute.uri,
                index,
                text,
            )

        def delete_index(index: int):
            deleted, _ = queryset.filter(collection_index=index).delete()
            if deleted:
                logger.info(
                    "Deleted collection value for attribute %s at collection_index=%s",
                    attribute.uri,
                    index,
                )

        def delete_from(start: int):
            deleted, _ = queryset.filter(collection_index__gte=start).delete()
            if deleted:
                logger.info(
                    "Deleted surplus collection values for attribute %s from collection_index=%s (%s rows)",
                    attribute.uri,
                    start,
                    deleted,
                )
    else:
        existing = {value.set_index: value for value in queryset.only("id", "set_index", "text")}

        def upsert_at(index: int, text: Any):
            _, created = Value.objects.update_or_create(
                project=instance.project,
                attribute=attribute,
                set_prefix=instance.set_index,
                set_collection=True,
                set_index=index,
                defaults={"text": text},
            )
            logger.info(
                "%s collection value for attribute %s at set_index=%s: %r",
                "Created" if created else "Updated",
                attribute.uri,
                index,
                text,
            )

        def delete_index(index: int):
            deleted, _ = queryset.filter(set_index=index, set_prefix=instance.set_index).delete()
            if deleted:
                logger.info(
                    "Deleted collection value for attribute %s at set_index=%s",
                    attribute.uri,
                    index,
                )

        def delete_from(start: int):
            deleted, _ = queryset.filter(set_index__gte=start).delete()
            if deleted:
                logger.info(
                    "Deleted surplus collection values for attribute %s from set_index=%s (%s rows)",
                    attribute.uri,
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


def update_values_from_handler_result(instance, result: HandlerResult):
    update_values_from_mapped_data(instance, result.mapped_values)

    if not result.collections:
        return

    with transaction.atomic(), mute_value_post_save():
        for collection in result.collections:
            _update_collection_assignment(instance, collection)


def _update_collection_assignment(instance, collection: CollectionAssignment):
    try:
        attribute = Attribute.objects.get(uri=collection.attribute_uri)
    except Attribute.DoesNotExist:
        logger.warning("Collection target attribute not found: %s", collection.attribute_uri)
        return

    mode = _collection_shape(instance, attribute)

    if collection.replace_existing:
        _delete_existing_collection_values(instance, attribute, mode)

    for index, value in enumerate(collection.values):
        if not isinstance(value, dict):
            logger.warning("Collection value must be a dictionary, got %s", type(value).__name__)
            continue

        defaults = {"text": value.get("text", "")}
        if "external_id" in value:
            defaults["external_id"] = value.get("external_id")

        if mode == "question":
            _, created = Value.objects.update_or_create(
                project=instance.project,
                attribute=attribute,
                set_collection=True,
                set_index=instance.set_index,
                collection_index=index,
                defaults=defaults,
            )
            logger.info(
                "%s handler collection value for attribute %s at collection_index=%s: %r",
                "Created" if created else "Updated",
                attribute.uri,
                index,
                defaults,
            )
        elif mode == "questionset":
            _, created = Value.objects.update_or_create(
                project=instance.project,
                attribute=attribute,
                set_prefix=instance.set_index,
                set_collection=True,
                set_index=index,
                defaults=defaults,
            )
            logger.info(
                "%s handler collection value for attribute %s at set_index=%s: %r",
                "Created" if created else "Updated",
                attribute.uri,
                index,
                defaults,
            )
        else:
            logger.warning(
                "Collection assignment found, but no matching Question or QuestionSet with is_collection flag. "
                "Attribute: %s",
                attribute,
            )


def _delete_existing_collection_values(instance, attribute, mode: str | None):
    queryset = Value.objects.filter(project=instance.project, attribute=attribute)

    if mode == "question":
        queryset = queryset.filter(set_collection=True, set_index=instance.set_index)
    elif mode == "questionset":
        queryset = queryset.filter(set_collection=True, set_prefix=instance.set_index)
    else:
        logger.warning(
            "Cannot determine collection deletion scope. Attribute: %s",
            attribute,
        )
        return

    deleted, _ = queryset.delete()
    if deleted:
        logger.info("Deleted existing collection values for attribute %s (%s rows)", attribute.uri, deleted)
