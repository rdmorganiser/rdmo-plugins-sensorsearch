import logging
from rdmo_sensorsearch.config import load_config
from rdmo_sensorsearch.handlers.factory import create_handler_from_config
from rdmo_sensorsearch.signals.value_updater import update_values_from_response

logger = logging.getLogger(__name__)


def handle_post_save(instance):
    config = load_config()
    if config is None:
        return

    id_prefix, external_id = parse_external_id(instance.external_id)
    if not id_prefix or not external_id:
        return

    handlers_config = config.get("handlers", {})
    if not handlers_config:
        logger.debug("No handlers in config")

    for handler_name, handler_config in handlers_config.items():

        handler_config_catalogs = handler_config.get("catalogs", [])
        if not handler_config_catalogs:
            logger.error("No catalog mappings for handler %s", handler_name)
            continue

        catalog_matches = [
            cc for cc in handler_config_catalogs
            if cc["catalog_uri"] == instance.project.catalog.uri
               and cc["auto_complete_field_uri"] == instance.attribute.uri
        ]

        if not catalog_matches:
            logger.debug("No catalog matches for handler %s", handler_name)
            continue

        handler = create_handler_from_config(handler_name, handler_config, id_prefix, catalog_matches[0])
        if handler is None:
            continue

        response = handler.handle(id_=external_id)
        update_values_from_response(instance, response)


def parse_external_id(external_id: str):
    parts = external_id.split(":")
    return parts if len(parts) == 2 else (None, None)
