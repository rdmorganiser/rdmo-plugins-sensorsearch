import logging

import jmespath
import requests

from rdmo_sensorsearch.client import get_user_agent

logger = logging.getLogger(__name__)


class GenericSearchHandler:
    """
    Base class for handling post_saves.

    Derived classes are used to gather additional information from the
    implemented API provider and map them to attributes in a catalog using
    JMESPath.
    """

    default_id_prefix: str = None # Must be set by subclass
    base_url: str = None          # can be set by subclass

    def __init__(self, attribute_mapping=None, id_prefix=None, base_url=None):
        """
        Initializes the GenericSearchHandler.

        Args:

            attribute_mapping (dict, optional): A dictionary mapping JamesPath
                                                expressions to attribute URIs.
                                                Defaults to an empty dictionary.
            **kwargs:                           Additional keyword arguments.

        """
        self._id_prefix = id_prefix or self.default_id_prefix
        self._base_url = base_url or getattr(self.__class__, "base_url", None)

        if attribute_mapping is not None:
            self.attribute_mapping = attribute_mapping  # must be set via the setter
        else:
            self._attribute_mapping = None  # internal default

    @property
    def id_prefix(self) -> str:
        return self._id_prefix


    @property
    def default_id_prefix(self) -> str:
        """
        Return the default id_prefix of the handler.

        This should be the same as defined as default in the provider classes
        and can be set to use more than one instance of a provider.

        Raises:
            NotImplementedError: If not set in subclass.
        """
        value = getattr(self.__class__, "default_id_prefix", None)
        if value is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must define `default_id_prefix` as a class attribute"
            )
        return value

    @property
    def base_url(self) -> str:
        """
        Returns:
            base_url (str, optional):           The base URL for API requests.
                                                Defaults to None.
        """
        if self._base_url is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must define `base_url` either in __init__ or as class attribute"
            )
        return self._base_url

    @property
    def attribute_mapping(self) -> dict:
        if self._attribute_mapping is None:
            raise ValueError(
                f"{self.__class__.__name__} requires `attribute_mapping` to be set before use."
            )
        return self._attribute_mapping

    @attribute_mapping.setter
    def attribute_mapping(self, mapping: dict) -> None:
        if not isinstance(mapping, dict):
            raise TypeError("attribute_mapping must be a dictionary")
        self._attribute_mapping = mapping

    def _get(self, url):
        """
        Performs a GET request to the specified URL with custom user agent.

        Args:
            url (str): The URL to send the GET request to.

        Returns:
            dict: A dictionary containing the JSON response from the server, or
                  an empty dictionary if there is an error.

        """
        try:
            return requests.get(url, headers={"User-Agent": get_user_agent()}).json()
        except requests.exceptions.RequestException as e:
            logger.error("Request failed: %s, %s", e, url)

        return {}

    def _map_jamespath_to_attribute_uri(self, data):
        """
        Maps values from the response data to attribute URIs using JamesPath
        expressions.

        The mapping is usually provided by the configuration file.

        Args:
            data (dict): The JSON response data.

        Returns:
            dict: A dictionary containing mapped values with attribute URIs as
                  keys.

        """
        mapped_values = {}
        for path, attribute_uri in self.attribute_mapping.items():
            mapped_values.update({f"{attribute_uri}": jmespath.search(path, data)})
        logger.debug("mapped_values %s", mapped_values)
        return mapped_values
