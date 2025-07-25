import logging

logger = logging.getLogger(__name__)


class GenericSearchHandler:
    """
    Base class for handling post_saves.

    Derived classes are used to gather additional information from the
    implemented API provider and map them to attributes in a catalog using
    JMESPath.
    """

    def __init__(self,
                 attribute_mapping=None,
                 id_prefix=None,
                 base_url=None
        ):
        """
        Initializes the GenericSearchHandler.

        Args:

            attribute_mapping (dict, optional): A dictionary mapping JamesPath
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
        value = self._attribute_mapping or getattr(type(self), "attribute_mapping", None)
        if value is None:
            raise ValueError(
                f"{self.__class__.__name__} requires `attribute_mapping` to be set before use."
            )
        return value

    @attribute_mapping.setter
    def attribute_mapping(self, mapping: dict) -> None:
        if not isinstance(mapping, dict):
            raise TypeError("attribute_mapping must be a dictionary")
        self._attribute_mapping = mapping
