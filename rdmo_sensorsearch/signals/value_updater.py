import logging

from rdmo.domain.models import Attribute
from rdmo.projects.models import Value
from rdmo.questions.models import Question, QuestionSet

from rdmo_sensorsearch.handlers.base import CollectionAssignment, HandlerResult

logger = logging.getLogger(__name__)


def update_values_from_mapped_data(instance, data: dict):
    for attribute_uri, value in data.items():
        if value is None:
            continue

        try:
            attribute = Attribute.objects.get(uri=attribute_uri)
        except Attribute.DoesNotExist:
            continue

        if isinstance(value, list):
            _handle_list_value(instance, attribute, value)
        else:
            Value.objects.update_or_create(
                project=instance.project,
                attribute=attribute,
                set_index=instance.set_index,
                defaults={"text": value},
            )


def _handle_list_value(instance, attribute, value_list):
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

    for i, value in enumerate(value_list):
        if question_match_count == 1 and question_set_match_count == 0:
            Value.objects.update_or_create(
                project=instance.project,
                attribute=attribute,
                set_collection=True,
                set_index=instance.set_index,
                collection_index=i,
                defaults={"text": value},
            )
        elif question_set_match_count > 0:
            Value.objects.update_or_create(
                project=instance.project,
                attribute=attribute,
                set_prefix=instance.set_index,
                set_collection=True,
                set_index=i,
                defaults={"text": value},
            )
        else:
            logger.warning(
                "List value found, but no matching Question or QuestionSet with is_collection flag. "
                "Questions: %s, QuestionSets: %s, Attribute: %s",
                question_match_count,
                question_set_match_count,
                attribute,
            )


def update_values_from_handler_result(instance, result: HandlerResult):
    update_values_from_mapped_data(instance, result.mapped_values)

    for collection in result.collections:
        _update_collection_assignment(instance, collection)


def _update_collection_assignment(instance, collection: CollectionAssignment):
    try:
        attribute = Attribute.objects.get(uri=collection.attribute_uri)
    except Attribute.DoesNotExist:
        logger.warning("Collection target attribute not found: %s", collection.attribute_uri)
        return

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

    if collection.replace_existing:
        _delete_existing_collection_values(instance, attribute, question_match_count, question_set_match_count)

    for index, value in enumerate(collection.values):
        if not isinstance(value, dict):
            logger.warning("Collection value must be a dictionary, got %s", type(value).__name__)
            continue

        defaults = {"text": value.get("text", "")}
        if "external_id" in value:
            defaults["external_id"] = value.get("external_id")

        if question_match_count == 1 and question_set_match_count == 0:
            Value.objects.update_or_create(
                project=instance.project,
                attribute=attribute,
                set_collection=True,
                set_index=instance.set_index,
                collection_index=index,
                defaults=defaults,
            )
        elif question_set_match_count > 0:
            Value.objects.update_or_create(
                project=instance.project,
                attribute=attribute,
                set_prefix=instance.set_index,
                set_collection=True,
                set_index=index,
                defaults=defaults,
            )
        else:
            logger.warning(
                "Collection assignment found, but no matching Question or QuestionSet with is_collection flag. "
                "Questions: %s, QuestionSets: %s, Attribute: %s",
                question_match_count,
                question_set_match_count,
                attribute,
            )


def _delete_existing_collection_values(instance, attribute, question_match_count: int, question_set_match_count: int):
    queryset = Value.objects.filter(project=instance.project, attribute=attribute)

    if question_match_count == 1 and question_set_match_count == 0:
        queryset = queryset.filter(set_collection=True, set_index=instance.set_index)
    elif question_set_match_count > 0:
        queryset = queryset.filter(set_collection=True, set_prefix=instance.set_index)
    else:
        logger.warning(
            "Cannot determine collection deletion scope. Questions: %s, QuestionSets: %s, Attribute: %s",
            question_match_count,
            question_set_match_count,
            attribute,
        )
        return

    queryset.delete()
