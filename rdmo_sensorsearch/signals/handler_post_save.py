import logging

from rdmo_sensorsearch.handlers.factory import build_handlers_by_catalog
from rdmo_sensorsearch.signals.value_updater import update_values_from_mapped_data

logger = logging.getLogger(__name__)

ALL_HANDLER_MAP = build_handlers_by_catalog()

def handle_post_save(instance):

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
    for candidate in handler_candidates:
        if candidate.id_prefix == id_prefix and candidate.auto_complete_field_uri == attribute_uri:
            mapped_data = candidate.handler.handle(id_=external_id)
            matched = True

            if 'errors' in mapped_data:
                logger.error("Handler %s returned errors: %s", candidate.id_prefix, mapped_data['errors'])
                continue

            update_values_from_mapped_data(instance, mapped_data)

    if not matched:
        logger.warning(
            "No matching handlers found for id_prefix=%s and attribute_uri=%s in catalog=%s",
            id_prefix, attribute_uri, catalog_uri
        )
