import logging
from dataclasses import dataclass

from rdmo_sensorsearch.config import load_config
from rdmo_sensorsearch.handlers.base import GenericSearchHandler
from rdmo_sensorsearch.handlers.registry import HANDLER_REGISTRY

logger = logging.getLogger(__name__)



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
        catalogs = handler_cfg.get("catalogs", [])
        backends = handler_cfg.get("backends")  # might be None or omitted

        for catalog in catalogs:
            catalog_uri = catalog.get("catalog_uri")
            auto_field_uri = catalog.get("auto_complete_field_uri")
            attribute_mapping = catalog.get("attribute_mapping", {})

            if not catalog_uri or not auto_field_uri:
                logger.warning("Skipping catalog with missing catalog_uri or"
                               " auto_complete_field_uri for handler %s", handler_name)
                continue

            handler_cls = HANDLER_REGISTRY.get(handler_name)
            if handler_cls is None:
                logger.warning("Handler class %s not found in registry.", handler_name)
                continue

            if not backends:
                # No backends defined, single handler instance using class defaults
                try:
                    instance = handler_cls(attribute_mapping=attribute_mapping)
                    hid = HandlerInstanceData(
                        id_prefix=instance.id_prefix,
                        handler=instance,
                        catalog_uri=catalog_uri,
                        auto_complete_field_uri=auto_field_uri
                    )
                    handlers_by_catalog.setdefault(catalog_uri, []).append(hid)
                except Exception as e:
                    logger.error("Failed to instantiate handler %s with defaults: %s", handler_name, e)
                continue

            # One handler per backend
            for backend in backends:
                id_prefix = backend.get("id_prefix")
                base_url = backend.get("base_url")

                try:
                    instance = handler_cls(
                        attribute_mapping=attribute_mapping,
                        id_prefix=id_prefix,
                        base_url=base_url
                    )
                    hid = HandlerInstanceData(
                        id_prefix=instance.id_prefix,
                        handler=instance,
                        catalog_uri=catalog_uri,
                        auto_complete_field_uri=auto_field_uri
                    )
                    handlers_by_catalog.setdefault(catalog_uri, []).append(hid)
                except Exception as e:
                    logger.error(
                        "Failed to instantiate handler %s with id_prefix=%s: %s",
                        handler_name, id_prefix, e
                    )

    return handlers_by_catalog
