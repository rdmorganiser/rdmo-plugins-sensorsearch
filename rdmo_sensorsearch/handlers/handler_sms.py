import logging

from rdmo_sensorsearch.handlers.base import GenericSearchHandler

logger = logging.getLogger(__name__)

class SensorManagementSystemHandler(GenericSearchHandler):
    """
    Handles the Sensor Management System (SMS) to gather sensor information.

    This handler fetches device information, including properties, from the
    SMS API.
    """
    default_id_prefix = "sms"

    def handle(self, id_):
        """
        Handles post_save for a specific device ID in the SMS.

        Args:
            id_ (str): The ID of the device to get information for .

        Returns:
            dict: A dictionary containing the mapped values from the SMS API
                  response.
        """
        data = self._get(f"{self.base_url}/devices/{id_}?include=device_properties")

        # contacts can not be included in the first request with the include parameter
        contact_data = self._get(f"{self.base_url}/devices/{id_}/device-contact-roles?include=contact")
        # add the included contact data to the data
        data.update({"included": [*data.get("included", []), *contact_data.get("included", [])]})

        logger.debug("data: %s", data)

        return self._map_jamespath_to_attribute_uri(data)
