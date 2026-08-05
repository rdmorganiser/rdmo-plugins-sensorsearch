from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rdmo_sensorsearch.handlers.factory import HandlerBinding

WILDCARD_CATALOG_URI = "*"

_HANDLER_BINDINGS_BY_CATALOG: dict[str, list[HandlerBinding]] | None = None
_REGISTRY_LOCK = Lock()


def handler_bindings_by_catalog() -> dict[str, list[HandlerBinding]]:
    """Return the configured handler bindings, building the registry once."""

    global _HANDLER_BINDINGS_BY_CATALOG
    if _HANDLER_BINDINGS_BY_CATALOG is None:
        with _REGISTRY_LOCK:
            if _HANDLER_BINDINGS_BY_CATALOG is None:
                from rdmo_sensorsearch.handlers.factory import build_handlers_by_catalog

                _HANDLER_BINDINGS_BY_CATALOG = build_handlers_by_catalog()
    return _HANDLER_BINDINGS_BY_CATALOG


def get_handler_bindings_for_catalog(catalog_uri: str) -> list[HandlerBinding]:
    """Merge exact and wildcard bindings without returning duplicates."""

    bindings_by_catalog = handler_bindings_by_catalog()
    catalog_bindings = bindings_by_catalog.get(catalog_uri, [])
    wildcard_bindings = bindings_by_catalog.get(WILDCARD_CATALOG_URI, [])

    seen = {(binding.id_prefix, binding.search_attribute_uri, type(binding.handler)) for binding in catalog_bindings}
    merged_bindings = list(catalog_bindings)
    for binding in wildcard_bindings:
        key = (binding.id_prefix, binding.search_attribute_uri, type(binding.handler))
        if key not in seen:
            merged_bindings.append(binding)
    return merged_bindings
