"""Configuration-only routing, with no persistent cache of database identities."""

from functools import cache
from types import MappingProxyType

from rdmo.domain.models import Attribute
from rdmo.projects.models import Project

from rdmo_sensorsearch.config import catalog_uri_values, load_config
from rdmo_sensorsearch.handlers.catalog_registry import get_handler_bindings_for_catalog, handler_bindings_by_catalog
from rdmo_sensorsearch.workflows.data_collection_variables import get_data_collection_variable_sync_settings
from rdmo_sensorsearch.workflows.metadata_refresh import _get_refresh_actions


@cache
def routing_attributes():
    config = load_config()
    catalogs = set(handler_bindings_by_catalog()) | {"*"}
    for rule in (
        *config.get("DataCollectionVariableSync", {}).get("catalogs", ()),
        *config.get("MetadataRefresh", {}).get("actions", ()),
    ):
        catalogs.update(catalog_uri_values(rule))
    routes = {}
    for catalog_uri in catalogs:
        attributes = set()
        for binding in get_handler_bindings_for_catalog(catalog_uri):
            attributes.add(binding.search_attribute_uri)
            attributes.update(
                getattr(binding.handler, name, None)
                for name in ("configuration_collection_attribute_uri", "selected_devices_attribute_uri")
            )
        variables = get_data_collection_variable_sync_settings(catalog_uri)
        if variables is not None:
            attributes.add(variables.devices_attribute_uri)
        for action in _get_refresh_actions(catalog_uri):
            attributes.update((action.trigger_attribute_uri, action.source_attribute_uri, *action.input_attribute_uris))
        routes[catalog_uri] = frozenset(uri for uri in attributes if uri)
    return MappingProxyType(routes)


def is_relevant_attribute(catalog_uri: str, attribute_uri: str) -> bool:
    routes = routing_attributes()
    return attribute_uri in routes.get(catalog_uri, routes["*"])


def route_value(instance) -> tuple[str, str] | None:
    """Return catalog/attribute URIs without hydrating unrelated foreign keys."""
    if instance.attribute_id is None or instance.project_id is None:
        return None
    relations = instance._state.fields_cache
    attribute = relations.get("attribute")
    attribute_uri = (
        attribute.uri
        if attribute is not None
        else Attribute.objects.filter(
            pk=instance.attribute_id,
        )
        .values_list("uri", flat=True)
        .first()
    )
    routes = routing_attributes()
    if not any(attribute_uri in attributes for attributes in routes.values()):
        return None
    project = relations.get("project")
    catalog = project._state.fields_cache.get("catalog") if project is not None else None
    catalog_uri = (
        catalog.uri
        if catalog is not None
        else Project.objects.filter(
            pk=instance.project_id,
        )
        .values_list("catalog__uri", flat=True)
        .first()
    )
    if catalog_uri is None or not is_relevant_attribute(catalog_uri, attribute_uri):
        return None
    return catalog_uri, attribute_uri
