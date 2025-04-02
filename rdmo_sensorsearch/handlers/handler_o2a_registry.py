import logging

from rdmo_sensorsearch.handlers.base import GenericSearchHandler

logger = logging.getLogger(__name__)


class O2ARegistrySearchHandler(GenericSearchHandler):
    """
    Handles the O2A Registry to gather additional informations about a sensor.

    To fetch additional data from the O2A REGISTRY at least three API calls
    must be made:
    1. Basic information about the sensor
    2. Parameters of the sensor
    3. Units to add them to the parameters

     base_url (str, optional):           The base URL for API requests
                                                to the O2A Registry. Defaults
                                                to 'https://registry.o2a-data.de/rest/v2'.
    """
    id_prefix = "o2aregistry"
    base_url = "https://registry.o2a-data.de/rest/v2"

    def __init__(self, attribute_mapping=None, id_prefix=None, base_url=None):
        """
        Initializes the O2ARegistrySearchHandler.

        Args:

            attribute_mapping (dict, optional): A dictionary mapping JamesPath
                                                expressions to attribute URIs.
                                                Defaults to an empty dictionary.
            **kwargs: Additional keyword arguments.

        """
        base_url = base_url or self.base_url

        super().__init__(attribute_mapping=attribute_mapping, id_prefix=id_prefix, base_url=base_url)

    def handle(self, id_):
        """
        Handles post_save for a specific ID.

        Args:
            id_ (str): The (sensor) ID to to get additional information for.

        Returns:
            dict: A dictionary containing the mapped values from the O2A
                  REGISTRY response.

        """
        # basic date
        basic_data = self._get(f"{self.base_url}/items/{id_}")

        # contacts
        contacts_data = self._get(f"{self.base_url}/items/{id_}/contacts")

        # parameters
        parameters_data = self._get(f"{self.base_url}/items/{id_}/parameters")

        # units
        units_data = self._get(f"{self.base_url}/units")

        # extend basic data with contacts
        data = basic_data
        data.update({"contacts": []})
        for contact in contacts_data.get("records", []):
            contact_data = contact.get("contact")
            # only add data if it is not a reference
            if contact_data and isinstance(contact_data, dict):
                tmp_contact_dict = {}
                for key in ["firstName", "lastName", "email"]:
                    if key in contact_data:
                        tmp_contact_dict.update({key: contact_data.get(key)})
                data.update({"contacts": [*data.get("contacts", []), tmp_contact_dict]})

        # extend basic data with parameters
        data.update({"parameters": []})

        # That's a bit special in the case of O2A. It is not guaranteed that
        # the unit is provided. Therefore it must be looked up on another
        # endpoint (`units_data`).
        for parameter in parameters_data.get("records", []):
            parameter_name = parameter.get("name")
            parameter_unit = ""
            # get the unit, maybe lookup from units
            unit_data = parameter.get("unit")
            if unit_data and isinstance(unit_data, dict):
                parameter_unit = unit_data.get("code")
            else:
                for u in units_data.get("records", []):
                    if u.get("@uuid") and u.get("@uuid") == unit_data:
                        parameter_unit = u.get("code")
            #data.update({"parameters": data.get("parameters", []) + [{"name": parameter_name, "unit": parameter_unit}]})
            data.update({"parameters": [*data.get("parameters", []), {"name": parameter_name, "unit": parameter_unit}]})

        logger.debug("data: %s", data)

        return self._map_jamespath_to_attribute_uri(data)
