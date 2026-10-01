import logging
from dataclasses import dataclass

from rdmo_sensorsearch.backend_assembly import sms_constructor_kwargs
from rdmo_sensorsearch.config import catalog_uri_values, load_config, merge_config
from rdmo_sensorsearch.handlers.base import BackendRecordHandler
from rdmo_sensorsearch.handlers.catalog_registry import WILDCARD_CATALOG_URI
from rdmo_sensorsearch.handlers.registry import HANDLER_REGISTRY

logger = logging.getLogger(__name__)


@dataclass
class HandlerBinding:
    id_prefix: str
    handler: BackendRecordHandler
    search_attribute_uri: str
    catalog_uri: str


def build_handlers_by_catalog() -> dict:
    plugin_config = load_config()
    handler_configs = plugin_config.get("handlers", {})
    handlers_by_catalog: dict = {}

    for handler_name, handler_config in handler_configs.items():
        defaults = handler_config.get("defaults", {})
        default_attribute_mapping = defaults.get("attribute_mapping", {})
        default_catalog_kwargs = {key: value for key, value in defaults.items() if key != "attribute_mapping"}

        catalogs = handler_config.get("catalogs", [])
        if not catalogs and defaults:
            catalogs = [{}]

        backend_defaults = handler_config.get("backend_defaults", {})
        backends = handler_config.get("backends")  # might be None or omitted

        for catalog_config in catalogs:
            merged_catalog = merge_config(
                {
                    **default_catalog_kwargs,
                    "attribute_mapping": default_attribute_mapping,
                },
                catalog_config,
            )

            catalog_uris = catalog_uri_values(merged_catalog) or [WILDCARD_CATALOG_URI]
            catalog_uri = catalog_uris[0]
            search_attribute_uri = merged_catalog.get("search_attribute_uri")
            # Parsed deployment configuration is immutable. Handlers retain a
            # concrete dictionary here because their public setter validates
            # and stores a mutable mapping.
            attribute_mapping = dict(merged_catalog.get("attribute_mapping", {}))
            catalog_extra_kwargs = {
                key: value
                for key, value in merged_catalog.items()
                if key not in {"catalog_uri", "catalog_uris", "search_attribute_uri", "attribute_mapping"}
            }

            if not search_attribute_uri:
                logger.warning(
                    "Skipping handler config with missing search_attribute_uri for handler %s",
                    handler_name,
                )
                continue

            handler_cls = HANDLER_REGISTRY.get(handler_name)
            if handler_cls is None:
                logger.warning("Handler class %s not found in registry.", handler_name)
                continue

            if not backends:
                # No backends defined, single handler instance using class defaults
                try:
                    instance = handler_cls(
                        **sms_constructor_kwargs(
                            handler_name,
                            {
                                "attribute_mapping": attribute_mapping,
                                **catalog_extra_kwargs,
                            },
                        )
                    )
                    binding = HandlerBinding(
                        id_prefix=instance.id_prefix,
                        handler=instance,
                        catalog_uri=catalog_uri,
                        search_attribute_uri=search_attribute_uri,
                    )
                    _register_handler_binding(handlers_by_catalog, catalog_uris, binding)
                except Exception as e:
                    logger.error("Failed to instantiate handler %s with defaults: %s", handler_name, e)
                continue

            # One handler per backend
            for backend_config in backends:
                merged_backend = merge_config(backend_defaults, backend_config)
                id_prefix = merged_backend.get("id_prefix")
                base_url = merged_backend.get("base_url")
                backend_extra_kwargs = {
                    key: value for key, value in merged_backend.items() if key not in {"id_prefix", "base_url"}
                }

                try:
                    instance = handler_cls(
                        **sms_constructor_kwargs(
                            handler_name,
                            {
                                "attribute_mapping": attribute_mapping,
                                "id_prefix": id_prefix,
                                "base_url": base_url,
                                **backend_extra_kwargs,
                                **catalog_extra_kwargs,
                            },
                        )
                    )
                    binding = HandlerBinding(
                        id_prefix=instance.id_prefix,
                        handler=instance,
                        catalog_uri=catalog_uri,
                        search_attribute_uri=search_attribute_uri,
                    )
                    _register_handler_binding(handlers_by_catalog, catalog_uris, binding)
                except Exception as e:
                    logger.error("Failed to instantiate handler %s with id_prefix=%s: %s", handler_name, id_prefix, e)

    return handlers_by_catalog


def _register_handler_binding(
    handlers_by_catalog: dict,
    catalog_uris: list[str],
    handler_binding: HandlerBinding,
) -> None:
    for catalog_uri in catalog_uris:
        handlers_by_catalog.setdefault(catalog_uri, []).append(
            HandlerBinding(
                id_prefix=handler_binding.id_prefix,
                handler=handler_binding.handler,
                catalog_uri=catalog_uri,
                search_attribute_uri=handler_binding.search_attribute_uri,
            )
        )
