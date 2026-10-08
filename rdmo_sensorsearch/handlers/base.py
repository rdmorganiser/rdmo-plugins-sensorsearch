import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)


class BackendRecordHandler:
    """
    Base class for synchronizing a selected backend record with RDMO values.

    Derived classes are used to gather additional information from the
    implemented API provider and map them to attributes in a catalog using
    JMESPath.
    """

    def __init__(
        self,
        *,
        id_prefix: str,
        attribute_mapping: Mapping[str, str],
    ):
        """Own the mapping and connection values supplied by typed assembly."""
        self._id_prefix = id_prefix
        self.attribute_mapping = attribute_mapping

    @property
    def id_prefix(self) -> str:
        """Return the configured external-ID namespace."""
        return self._id_prefix

    @property
    def attribute_mapping(self) -> dict[str, str]:
        return self._attribute_mapping

    @attribute_mapping.setter
    def attribute_mapping(self, mapping: Mapping[str, str]) -> None:
        if not isinstance(mapping, Mapping):
            raise TypeError("attribute_mapping must be a mapping")
        self._attribute_mapping = dict(mapping)

    @property
    def managed_attribute_uris(self) -> frozenset[str]:
        configured_uris = getattr(self, "_managed_attribute_uris", ())
        return frozenset(self.attribute_mapping.values()) | frozenset(configured_uris)

    @managed_attribute_uris.setter
    def managed_attribute_uris(self, value) -> None:
        if isinstance(value, str):
            raise TypeError("managed_attribute_uris must be a collection of URI strings")
        self._managed_attribute_uris = tuple(value)

    def build_authoritative_mapped_values(
        self,
        mapped_values: Mapping[str, Any],
        excluded_attribute_uris: set[str] | None = None,
    ) -> dict[str, Any]:
        excluded_attribute_uris = excluded_attribute_uris or set()
        authoritative_values: dict[str, Any] = {}

        for path, attribute_uri in self.attribute_mapping.items():
            if attribute_uri in excluded_attribute_uris:
                continue
            default_value = [] if "[]" in path else None
            if isinstance(authoritative_values.get(attribute_uri), list) or isinstance(default_value, list):
                authoritative_values[attribute_uri] = []
            else:
                authoritative_values[attribute_uri] = None

        for attribute_uri in self.managed_attribute_uris:
            if attribute_uri not in excluded_attribute_uris:
                authoritative_values.setdefault(attribute_uri, None)

        authoritative_values.update(
            {
                attribute_uri: value
                for attribute_uri, value in mapped_values.items()
                if attribute_uri not in excluded_attribute_uris
            }
        )
        return authoritative_values
