import logging

from rdmo_sensorsearch.handlers.base import HandlerResult
from rdmo_sensorsearch.handlers.factory import build_handlers_by_catalog
from rdmo_sensorsearch.signals.value_updater import (
    build_clear_payload,
    clear_attribute_values,
    clear_collection_attribute,
    update_values_from_handler_result,
    update_values_from_mapped_data,
)

logger = logging.getLogger(__name__)

ALL_HANDLER_MAP = build_handlers_by_catalog()

def handle_post_save(instance):

    if not ALL_HANDLER_MAP:
        logger.warning("No handlers found for %s", __name__)
        return

    project = instance.project
    attribute = instance.attribute

    if project is None or attribute is None or project.catalog is None:
        logger.debug("Skipping post_save handling for incomplete value instance: %r", instance)
        return

    catalog_uri = project.catalog.uri
    attribute_uri = attribute.uri

    if not catalog_uri or not attribute_uri:
        logger.warning("Missing catalog or attribute URI")
        return

    handler_candidates = ALL_HANDLER_MAP.get(catalog_uri, [])
    attribute_handler_candidates = [
        candidate for candidate in handler_candidates if candidate.auto_complete_field_uri == attribute_uri
    ]

    if not attribute_handler_candidates:
        logger.debug(
            "Skipping post_save handling for attribute_uri=%s in catalog=%s because no handler is configured for it",
            attribute_uri,
            catalog_uri,
        )
        return

    if not instance.external_id and getattr(instance, "is_empty", False):
        for candidate in attribute_handler_candidates:
            for attribute_uri_to_clear in getattr(candidate.handler, "reset_attribute_uris", []):
                clear_attribute_values(instance, attribute_uri_to_clear)
            update_values_from_mapped_data(instance, build_clear_payload(candidate.handler.attribute_mapping))
            member_sensors_attribute_uri = getattr(candidate.handler, "member_sensors_attribute_uri", None)
            if member_sensors_attribute_uri:
                clear_collection_attribute(instance, member_sensors_attribute_uri)
        return

    if not instance.external_id:
        logger.debug("external_id is empty and not marked empty: %r", instance)
        return

    try:
        id_prefix, external_id = instance.external_id.split(":")
    except ValueError:
        logger.warning("Can not parse instance.external_id: %s", instance.external_id)
        return

    matched = False
    for candidate in attribute_handler_candidates:
        if candidate.id_prefix == id_prefix and candidate.auto_complete_field_uri == attribute_uri:
            try:
                for attribute_uri_to_clear in getattr(candidate.handler, "reset_attribute_uris", []):
                    clear_attribute_values(instance, attribute_uri_to_clear)
                mapped_data = candidate.handler.handle(id_=external_id, instance=instance)
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
