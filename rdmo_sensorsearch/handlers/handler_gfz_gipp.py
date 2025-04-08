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
    json_url = "{base_url}/{id}.json"

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

        data = fetch_json(self.json_url.format(base_url=self.base_url, id=id_))
        logger.debug("data: %s", data)
        return map_jamespath_to_attribute_uri(self.attribute_mapping, data)
