import logging

from rdmo_sensorsearch.config import load_config
from rdmo_sensorsearch.handlers.registry import HANDLER_REGISTRY

logger = logging.getLogger(__name__)


handler_instances_by_prefix = {}  # module-level cache


def build_handlers_from_config() -> dict[str, object]:
    config = load_config()
    if not config or "handlers" not in config:
        return {}

    handlers = {}

    for handler_name, handler_cfg in config["handlers"].items():
        catalogs = handler_cfg.get("catalogs", [])
        backends = handler_cfg.get("backends", [])

        for catalog in catalogs:
            catalog_mapping = catalog.get("attribute_mapping")
            catalog.get("catalog_uri")
            catalog.get("auto_complete_field_uri")

            # Default config, no backends
            if not backends:
                instance = create_handler_instance(handler_name, catalog_mapping, None)
                if instance:
                    handlers[instance.id_prefix] = instance
                continue

            # Backend-specific handlers
            for backend in backends:
                id_prefix = backend.get("id_prefix")
                base_url = backend.get("base_url")
                instance = create_handler_instance(handler_name, catalog_mapping, id_prefix, base_url)
                if instance:
                    handlers[instance.id_prefix] = instance

    return handlers


def create_handler_instance(handler_name, attribute_mapping, id_prefix=None, base_url=None):
    try:
        handler_cls = HANDLER_REGISTRY[handler_name]
        handler_cls_instance = handler_cls(attribute_mapping=attribute_mapping, id_prefix=id_prefix, base_url=base_url)
        assert handler_cls_instance.base_url
        return handler_cls_instance
    except Exception as e:
        logger.error("Failed to instantiate handler %s with id_prefix=%s: %s", handler_name, id_prefix, e)
        return None
