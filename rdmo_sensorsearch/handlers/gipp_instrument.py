import logging

from rdmo_sensorsearch.handlers.base import BackendRecordHandler, HandlerExecutionContext, HandlerResult

from ..client import fetch_json
from .parser import evaluate_jmespath_mapping

logger = logging.getLogger(__name__)


class GIPPInstrumentHandler(BackendRecordHandler):
    """
    Handles for the Geophysical Instrument Pool Potsdam (GIPP).

    This handler retrieves instrument information from the GIPP REST API.

     base_url (str, optional):           The base URL for API requests
                                                to GIPP. Defaults to
                                                'https://gipp.gfz.de/instruments/rest'.
    """

    id_prefix = "gfzgipp"
    base_url = "https://gipp.gfz.de/instruments/rest"

    json_url = "{base_url}/{id}.json"

    def handle(self, backend_id, instance=None, context: HandlerExecutionContext | None = None):
        """
        Synchronizes one GIPP instrument with its RDMO value.

        Args:
            backend_id (str): The ID of the instrument to get information for.

        Returns:
            dict: A dictionary containing the mapped values from the GIPP API
                  response.

        """

        data = fetch_json(self.json_url.format(base_url=self.base_url, id=backend_id))
        if isinstance(data, dict) and "errors" in data:
            return data
        if not isinstance(data, dict):
            return {"errors": [f"Unexpected GIPP payload for instrument {backend_id}: {type(data).__name__}"]}
        if not data:
            return {"errors": [f"GIPP request for instrument {backend_id} returned no instrument data."]}

        logger.debug("data: %s", data)
        return HandlerResult(mapped_values=evaluate_jmespath_mapping(self.attribute_mapping, data))
