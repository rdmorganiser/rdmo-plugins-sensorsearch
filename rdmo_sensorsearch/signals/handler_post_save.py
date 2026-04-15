import logging

from rdmo_sensorsearch.handlers.base import HandlerResult
from rdmo_sensorsearch.handlers.factory import build_handlers_by_catalog
from rdmo_sensorsearch.signals.value_updater import (
    update_values_from_handler_result,
    update_values_from_mapped_data,
)

logger = logging.getLogger(__name__)

ALL_HANDLER_MAP = build_handlers_by_catalog()

def handle_post_save(instance):

    if not ALL_HANDLER_MAP:
        logger.warning("No handlers found for %s", __name__)
        return

    try:
        id_prefix, external_id = instance.external_id.split(":")
    except ValueError:
        logger.warning("Can not parse instance.external_id: %s", instance.external_id)
        return

    catalog_uri = instance.project.catalog.uri
    attribute_uri = instance.attribute.uri

    if not catalog_uri or not attribute_uri:
        logger.warning("Missing catalog or attribute URI")
        return

    handler_candidates = ALL_HANDLER_MAP.get(catalog_uri, [])
    matched = False
    for candidate in handler_candidates:
        if candidate.id_prefix == id_prefix and candidate.auto_complete_field_uri == attribute_uri:
            try:
                mapped_data = candidate.handler.handle(id_=external_id)
            except Exception:
                logger.exception(
                    "Handler %s failed while processing external_id=%s for catalog=%s",
                    candidate.id_prefix,
                    external_id,
                    catalog_uri,
                )
                continue

            matched = True

            if isinstance(mapped_data, dict) and 'errors' in mapped_data:
                logger.error("Handler %s returned errors: %s", candidate.id_prefix, mapped_data['errors'])
                continue

            if isinstance(mapped_data, HandlerResult):
                update_values_from_handler_result(instance, mapped_data)
            else:
                update_values_from_mapped_data(instance, mapped_data)

    if not matched:
        logger.warning(
            "No matching handlers found for id_prefix=%s and attribute_uri=%s in catalog=%s",
            id_prefix, attribute_uri, catalog_uri
        )
