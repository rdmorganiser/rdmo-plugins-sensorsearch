import logging
from dataclasses import dataclass

from rdmo_sensorsearch.config import catalog_uri_values, load_config, merge_config
from rdmo_sensorsearch.handlers.base import GenericSearchHandler
from rdmo_sensorsearch.handlers.registry import HANDLER_REGISTRY

logger = logging.getLogger(__name__)

WILDCARD_CATALOG_URI = "*"


@dataclass
class HandlerInstanceData:
    id_prefix: str
    handler: GenericSearchHandler
    auto_complete_field_uri: str
    catalog_uri: str


def build_handlers_by_catalog() -> dict:
    config = load_config()
    handler_configs = config.get("handlers", {})
    handlers_by_catalog: dict = {}

    for handler_name, handler_cfg in handler_configs.items():
        defaults = handler_cfg.get("defaults", {})
        default_attribute_mapping = defaults.get("attribute_mapping", {})
        default_catalog_kwargs = {key: value for key, value in defaults.items() if key != "attribute_mapping"}

        catalogs = handler_cfg.get("catalogs", [])
        if not catalogs and defaults:
            catalogs = [{}]

        backend_defaults = handler_cfg.get("backend_defaults", {})
        backends = handler_cfg.get("backends")  # might be None or omitted

        for catalog in catalogs:
            merged_catalog = merge_config(
                {
                    **default_catalog_kwargs,
                    "attribute_mapping": default_attribute_mapping,
                },
                catalog,
            )

            catalog_uris = catalog_uri_values(merged_catalog) or [WILDCARD_CATALOG_URI]
            catalog_uri = catalog_uris[0]
            auto_field_uri = merged_catalog.get("auto_complete_field_uri")
            attribute_mapping = merged_catalog.get("attribute_mapping", {})
            catalog_extra_kwargs = {
                key: value
                for key, value in merged_catalog.items()
                if key not in {"catalog_uri", "catalog_uris", "auto_complete_field_uri", "attribute_mapping"}
            }

            if not auto_field_uri:
                logger.warning(
                    "Skipping handler config with missing auto_complete_field_uri for handler %s",
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
                        attribute_mapping=attribute_mapping,
                        **catalog_extra_kwargs,
                    )
                    hid = HandlerInstanceData(
                        id_prefix=instance.id_prefix,
                        handler=instance,
                        catalog_uri=catalog_uri,
                        auto_complete_field_uri=auto_field_uri,
                    )
                    _register_handler_instance(handlers_by_catalog, catalog_uris, hid)
                except Exception as e:
                    logger.error("Failed to instantiate handler %s with defaults: %s", handler_name, e)
                continue

            # One handler per backend
            for backend in backends:
                merged_backend = merge_config(backend_defaults, backend)
                id_prefix = merged_backend.get("id_prefix")
                base_url = merged_backend.get("base_url")
                backend_extra_kwargs = {
                    key: value for key, value in merged_backend.items() if key not in {"id_prefix", "base_url"}
                }

                try:
                    instance = handler_cls(
                        attribute_mapping=attribute_mapping,
                        id_prefix=id_prefix,
                        base_url=base_url,
                        **backend_extra_kwargs,
                        **catalog_extra_kwargs,
                    )
                    hid = HandlerInstanceData(
                        id_prefix=instance.id_prefix,
                        handler=instance,
                        catalog_uri=catalog_uri,
                        auto_complete_field_uri=auto_field_uri,
                    )
                    _register_handler_instance(handlers_by_catalog, catalog_uris, hid)
                except Exception as e:
                    logger.error("Failed to instantiate handler %s with id_prefix=%s: %s", handler_name, id_prefix, e)

    return handlers_by_catalog


def _register_handler_instance(handlers_by_catalog: dict, catalog_uris: list[str], handler_data: HandlerInstanceData) -> None:
    for catalog_uri in catalog_uris:
        handlers_by_catalog.setdefault(catalog_uri, []).append(
            HandlerInstanceData(
                id_prefix=handler_data.id_prefix,
                handler=handler_data.handler,
                catalog_uri=catalog_uri,
                auto_complete_field_uri=handler_data.auto_complete_field_uri,
            )
        )
