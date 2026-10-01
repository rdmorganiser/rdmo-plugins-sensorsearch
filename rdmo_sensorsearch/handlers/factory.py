"""Construct catalog bindings from typed instances and shared backend definitions."""

from dataclasses import dataclass

from rdmo_sensorsearch.backend_assembly import HANDLER_BUILDERS
from rdmo_sensorsearch.config import load_config_model
from rdmo_sensorsearch.config_models.contracts import CONSUMER_CAPABILITIES
from rdmo_sensorsearch.handlers.base import BackendRecordHandler
from rdmo_sensorsearch.handlers.catalog_registry import WILDCARD_CATALOG_URI


@dataclass
class HandlerBinding:
    id_prefix: str
    handler: BackendRecordHandler
    search_attribute_uri: str
    catalog_uri: str
    backend_name: str = ""
    backend_type: str = ""
    resource_kind: str = ""


def build_handlers_by_catalog() -> dict:
    config = load_config_model()
    bindings_by_catalog = {}
    for handler_config in config.handlers.values():
        builder = HANDLER_BUILDERS[handler_config.handler_name]
        backend_type, resource = CONSUMER_CAPABILITIES[handler_config.handler_name]
        for catalog in handler_config.catalogs:
            catalog_uris = catalog.scope.catalog_uris or (WILDCARD_CATALOG_URI,)
            for instance in handler_config.instances:
                definition = config.backend(instance.backend)
                handler = builder(instance, catalog, definition)
                binding = HandlerBinding(
                    id_prefix=definition.prefix(resource),
                    handler=handler,
                    search_attribute_uri=catalog.search_attribute_uri,
                    catalog_uri=catalog_uris[0],
                    backend_name=definition.name,
                    backend_type=backend_type,
                    resource_kind=resource,
                )
                for uri in catalog_uris:
                    bindings_by_catalog.setdefault(uri, []).append(binding)
    return bindings_by_catalog
