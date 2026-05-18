from rdmo.projects.models import Value


def get_project_value(instance, attribute_uri: str) -> str | None:
    query_variants = [
        {"project": instance.project, "attribute__uri": attribute_uri, "set_prefix": instance.set_prefix, "set_index": instance.set_index},
        {"project": instance.project, "attribute__uri": attribute_uri, "set_prefix": instance.set_prefix},
        {"project": instance.project, "attribute__uri": attribute_uri, "set_index": instance.set_index},
        {"project": instance.project, "attribute__uri": attribute_uri},
    ]

    for filters in query_variants:
        queryset = Value.objects.filter(**filters).order_by("-id")
        value = queryset.first()
        if value is None:
            continue

        if value.text:
            return value.text
        if value.value:
            return value.value

    return None