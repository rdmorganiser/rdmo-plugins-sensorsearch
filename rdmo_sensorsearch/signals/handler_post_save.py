import logging

from rdmo_sensorsearch.handlers.factory import build_handlers_from_config
from rdmo_sensorsearch.signals.value_updater import update_values_from_response

logger = logging.getLogger(__name__)

ALL_HANDLERS = build_handlers_from_config()

def handle_post_save(instance):
    if instance is None or instance.external_id is None:
        return

    id_prefix, external_id = parse_external_id(instance.external_id)
    if not id_prefix or not external_id:
        return

    handler = ALL_HANDLERS.get(id_prefix)
    if not handler:
        logger.warning("No handler found for id_prefix: %s", id_prefix)
        return

    response = handler.handle(id_=external_id)
    if 'errors' in response:
        logger.error("Errors in handler response %s", response['errors'])
        return
    update_values_from_response(instance, response)


def parse_external_id(external_id: str):
    parts = external_id.split(":")
    return parts if len(parts) == 2 else (None, None)
