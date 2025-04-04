import logging

from rdmo_sensorsearch.handlers.base import GenericSearchHandler

from ..client import fetch_json
from .parser import map_jamespath_to_attribute_uri

logger = logging.getLogger(__name__)

class GeophysicalInstrumentPoolPotsdamHandler(GenericSearchHandler):
    """
    Handles for the Geophysical Instrument Pool Potsdam (GIPP).

    This handler retrieves instrument information from the GIPP REST API.

     base_url (str, optional):           The base URL for API requests
                                                to GIPP. Defaults to
                                                'https://gipp.gfz-potsdam.de/instruments/rest'.
    """
    id_prefix = "gfzgipp"
    base_url = "https://gipp.gfz-potsdam.de/instruments/rest"

    def __init__(self,attribute_mapping=None,**kwargs,):
        """
        Initializes the GeophysicalInstrumentPoolPotsdamHandler.

        Args:
            attribute_mapping (dict, optional): A dictionary mapping JamesPath
                                                expressions to attribute URIs.
                                                Defaults to an empty dictionary.
            **kwargs:                           Additional keyword arguments.

        """
        super().__init__(attribute_mapping=attribute_mapping, **kwargs)

    def handle(self, id_):
        """
        Handles post_save for a specific instrument ID in GIPP.

        Args:
            id_ (str): The ID of the instrument to get information for.

        Returns:
            dict: A dictionary containing the mapped values from the GIPP API
                  response.

        """
        url = f"{self.base_url}/{id_}.json"
        data = fetch_json(url)
        logger.debug("data: %s", data)

        values = map_jamespath_to_attribute_uri(self.attribute_mapping, data)

        return values
