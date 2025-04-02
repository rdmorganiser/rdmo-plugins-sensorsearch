import logging
from rdmo.domain.models import Attribute
from rdmo.projects.models import Value
from rdmo.questions.models import Question, QuestionSet

logger = logging.getLogger(__name__)


def update_values_from_response(instance, data: dict):
    for attribute_uri, value in data.items():
        if value is None:
            continue

        attribute = Attribute.objects.get(uri=attribute_uri)

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
