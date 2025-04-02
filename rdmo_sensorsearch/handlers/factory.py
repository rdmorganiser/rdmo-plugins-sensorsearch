import logging

from rdmo_sensorsearch.handlers.registry import HANDLER_REGISTRY

logger = logging.getLogger(__name__)


def create_handler_from_config(handler_name, config, id_prefix, catalog_config):
    try:
        HandlerClass = HANDLER_REGISTRY[handler_name]
    except KeyError:
        logger.error("Handler %s not found in registry", handler_name)
        return None

    backends = config.get("backends")
    mapping = catalog_config.get("attribute_mapping")

    handler_kwargs = {
        "id_prefix": id_prefix,
        "attribute_mapping": mapping,
    }

    # Use backend-specific config
    if backends:
        matching_backend = next((b for b in backends if b["id_prefix"] == id_prefix), None)
        if matching_backend:
            handler_kwargs["base_url"] = matching_backend.get("base_url")

    handler = HandlerClass(**handler_kwargs)

    # Only accept if id_prefix is valid for this handler
    return handler if handler.id_prefix == id_prefix else None
