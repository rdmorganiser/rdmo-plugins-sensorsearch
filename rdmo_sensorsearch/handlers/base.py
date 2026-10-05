import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

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
        attribute_mapping=None,
        id_prefix=None,
        base_url=None,
        **kwargs,
    ):
        """
        Initializes the BackendRecordHandler.

        Args:

            attribute_mapping (dict, optional): A dictionary mapping JMESPath
                                                expressions to attribute URIs.
                                                Defaults to an empty dictionary.
            **kwargs:                           Additional keyword arguments.

        """
        self._id_prefix = id_prefix
        self._base_url = base_url

        if attribute_mapping is not None:
            self.attribute_mapping = attribute_mapping  # must be set via the setter
        else:
            self._attribute_mapping = None  # internal default

        for key, value in kwargs.items():
            setattr(self, key, value)

    @property
    def id_prefix(self) -> str:
        """
        Return the default id_prefix of the handler.

        This should be the same as defined as default in the provider classes
        and can be set to use more than one instance of a provider.

        Raises:
            NotImplementedError: If not set in subclass.
        """
        value = self._id_prefix or getattr(type(self), "id_prefix", None)
        if value is None:
            raise NotImplementedError(f"{type(self).__name__} must define `id_prefix`")
        return value

    @property
    def base_url(self) -> str:
        value = self._base_url or getattr(type(self), "base_url", None)
        if value is None:
            raise NotImplementedError(f"{type(self).__name__} must define `base_url`")
        return value

    @base_url.setter
    def base_url(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("base_url must be a string")
        self._base_url = value

    @property
    def attribute_mapping(self) -> dict:
        if self._attribute_mapping is not None:
            return self._attribute_mapping

        for handler_class in type(self).__mro__:
            value = handler_class.__dict__.get("attribute_mapping")
            if value is not None and not isinstance(value, property):
                return value
        raise ValueError(f"{self.__class__.__name__} requires `attribute_mapping` to be set before use.")

    @attribute_mapping.setter
    def attribute_mapping(self, mapping: dict) -> None:
        if not isinstance(mapping, dict):
            raise TypeError("attribute_mapping must be a dictionary")
        self._attribute_mapping = mapping

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

    @property
    def base_url_origin(self) -> str:
        parsed = urlsplit(self.base_url)
        return f"{parsed.scheme}://{parsed.netloc}"
