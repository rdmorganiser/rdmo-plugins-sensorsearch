import logging

from rdmo_sensorsearch.handlers.handler_sms import (
    INSTRUMENT_END_ATTRIBUTE_URI,
    INSTRUMENT_START_ATTRIBUTE_URI,
)
from rdmo_sensorsearch.handlers.base import HandlerResult
from rdmo_sensorsearch.handlers.factory import WILDCARD_CATALOG_URI, build_handlers_by_catalog
from rdmo_sensorsearch.signals.value_updater import (
    build_clear_payload,
    clear_attribute_values,
    clear_collection_attribute,
    replace_scalar_value_in_scopes,
    update_values_from_handler_result,
    update_values_from_mapped_data,
)

logger = logging.getLogger(__name__)

ALL_HANDLER_MAP = build_handlers_by_catalog()


def _get_handler_candidates(catalog_uri: str) -> list:
    specific_candidates = ALL_HANDLER_MAP.get(catalog_uri, [])
    wildcard_candidates = ALL_HANDLER_MAP.get(WILDCARD_CATALOG_URI, [])

    seen = {
        (candidate.id_prefix, candidate.auto_complete_field_uri, type(candidate.handler))
        for candidate in specific_candidates
    }

    merged_candidates = list(specific_candidates)
    for candidate in wildcard_candidates:
        key = (candidate.id_prefix, candidate.auto_complete_field_uri, type(candidate.handler))
        if key not in seen:
            merged_candidates.append(candidate)

    return merged_candidates


def _clear_handler_targets(instance, handler) -> None:
    reset_attribute_uris = set(getattr(handler, "reset_attribute_uris", []))
    member_sensors_attribute_uri = getattr(handler, "member_sensors_attribute_uri", None)

    for attribute_uri_to_clear in getattr(handler, "reset_attribute_uris", []):
        if attribute_uri_to_clear == member_sensors_attribute_uri:
            continue
        clear_attribute_values(instance, attribute_uri_to_clear)

    clear_payload = {
        attribute_uri: value
        for attribute_uri, value in build_clear_payload(handler.attribute_mapping).items()
        if attribute_uri not in reset_attribute_uris
    }
    update_values_from_mapped_data(instance, clear_payload)

    if member_sensors_attribute_uri:
        clear_collection_attribute(instance, member_sensors_attribute_uri)


def _clear_handler_signature(handler) -> tuple:
    reset_attribute_uris = tuple(sorted(getattr(handler, "reset_attribute_uris", [])))
    mapped_attribute_uris = tuple(sorted(set(handler.attribute_mapping.values())))
    member_sensors_attribute_uri = getattr(handler, "member_sensors_attribute_uri", None)
    return reset_attribute_uris, mapped_attribute_uris, member_sensors_attribute_uri


def _device_nested_questionset_scope(instance) -> tuple[str, int]:
    return str(instance.set_index), 0


def _update_mapped_data(instance, mapped_data: dict) -> None:
    scoped_scalar_values = {
        INSTRUMENT_START_ATTRIBUTE_URI: mapped_data.pop(INSTRUMENT_START_ATTRIBUTE_URI, ""),
        INSTRUMENT_END_ATTRIBUTE_URI: mapped_data.pop(INSTRUMENT_END_ATTRIBUTE_URI, ""),
    }
    update_values_from_mapped_data(instance, mapped_data)
    for attribute_uri, value in scoped_scalar_values.items():
        if attribute_uri not in {INSTRUMENT_START_ATTRIBUTE_URI, INSTRUMENT_END_ATTRIBUTE_URI}:
            continue
        replace_scalar_value_in_scopes(
            instance,
            attribute_uri,
            value,
            scopes_to_set=[_device_nested_questionset_scope(instance)],
            scopes_to_clear=[(instance.set_prefix or "", instance.set_index)],
        )


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

    handler_candidates = _get_handler_candidates(catalog_uri)
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
        cleared_signatures = set()
        for candidate in attribute_handler_candidates:
            signature = _clear_handler_signature(candidate.handler)
            if signature in cleared_signatures:
                continue
            cleared_signatures.add(signature)
            _clear_handler_targets(instance, candidate.handler)
        return

    if not instance.external_id:
        logger.debug("external_id is empty and not marked empty: %r", instance)
        return

    try:
        id_prefix, external_id = instance.external_id.split(":", 1)
    except ValueError:
        logger.warning("Can not parse instance.external_id: %s", instance.external_id)
        return

    matched = False
    for candidate in attribute_handler_candidates:
        if candidate.id_prefix == id_prefix and candidate.auto_complete_field_uri == attribute_uri:
            try:
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

            _clear_handler_targets(instance, candidate.handler)

            if isinstance(mapped_data, HandlerResult):
                update_values_from_handler_result(instance, mapped_data)
            else:
                _update_mapped_data(instance, mapped_data)

    if not matched:
        logger.warning(
            "No matching handlers found for id_prefix=%s and attribute_uri=%s in catalog=%s",
            id_prefix, attribute_uri, catalog_uri
        )
