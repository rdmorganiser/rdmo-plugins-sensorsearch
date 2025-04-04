import logging

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.handlers.base import GenericSearchHandler
from rdmo_sensorsearch.handlers.parser import map_jamespath_to_attribute_uri

logger = logging.getLogger(__name__)

class SensorManagementSystemHandler(GenericSearchHandler):
    """
    Handles the Sensor Management System (SMS) to gather sensor information.

    This handler fetches device information, including properties, from the
    SMS API.
    """
    id_prefix = "sms"

    def handle(self, id_):
        """
        Handles post_save for a specific device ID in the SMS.

        Args:
            id_ (str): The ID of the device to get information for .

        Returns:
            dict: A dictionary containing the mapped values from the SMS API
                  response.
        """
        data = fetch_json(f"{self.base_url}/devices/{id_}?include=device_properties")

        # contacts can not be included in the first request with the include parameter
        contact_data = fetch_json(f"{self.base_url}/devices/{id_}/device-contact-roles?include=contact")
        # add the included contact data to the data
        data.update({"included": [*data.get("included", []), *contact_data.get("included", [])]})
        if not data:
            logger.debug("data: %s", data)
        values = map_jamespath_to_attribute_uri(self.attribute_mapping, data)

        return values

