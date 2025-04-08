import logging

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.handlers.base import GenericSearchHandler
from rdmo_sensorsearch.handlers.parser import map_jamespath_to_attribute_uri

logger = logging.getLogger(__name__)


class O2ARegistrySearchHandler(GenericSearchHandler):
    """
    Handles the O2A Registry to gather additional informations about a sensor.

    To fetch additional data from the O2A REGISTRY at least three API calls
    must be made:
    1. Basic information about the sensor
    2. Parameters of the sensor
    3. Units to add them to the parameters
    4. Global units list (for parameter unit lookup)

     base_url (str, optional):           The base URL for API requests
                                                to the O2A Registry. Defaults
                                                to 'https://registry.o2a-data.de/rest/v2'.
    """
    id_prefix = "o2aregistry"
    base_url = "https://registry.o2a-data.de/rest/v2"

    # URL templates
    item_url = "{base_url}/items/{id}"
    contacts_url = "{base_url}/items/{id}/contacts"
    parameters_url = "{base_url}/items/{id}/parameters"
    units_url = "{base_url}/units"


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
            id_ (str): The (sensor) ID to get additional information for.

        Returns:
            dict: A dictionary containing the mapped values from the O2A
                  REGISTRY response.

        """
        base_url = self.base_url
        # basic data
        data = fetch_json(self.item_url.format(base_url=base_url, id=id_))
        # contacts
        contacts_data = fetch_json(self.contacts_url.format(base_url=base_url, id=id_))
        # parameters
        parameters_data = fetch_json(self.parameters_url.format(base_url=base_url, id=id_))
        # units
        units_data = fetch_json(self.units_url.format(base_url=base_url))


        # extend basic data with contacts
        self.add_contacts_to_data(data, contacts_data)

        # extend basic data with parameters
        self.add_parameters_to_data(data, parameters_data, units_data)

        logger.debug("data: %s", data)
        return map_jamespath_to_attribute_uri(self.attribute_mapping, data)

    def add_contacts_to_data(self, data: dict, contacts_data: dict) -> None:
        contacts = []
        for contact in contacts_data.get("records", []):
            contact_data = contact.get("contact")
            # only add data if it is not a reference
            if contact_data and isinstance(contact_data, dict):
                simplified = {
                    key: contact_data[key]
                    for key in ("firstName", "lastName", "email")
                    if key in contact_data
                }
                contacts.append(simplified)
        data["contacts"] = contacts

    def add_parameters_to_data(self, data: dict, parameters_data: dict, units_data: dict) -> None:
        # That's a bit special in the case of O2A. It is not guaranteed that
        # the unit is provided. Therefore it must be looked up on another
        # endpoint (`units_data`).
        parameters = []
        unit_lookup = {
            u["@uuid"]: u.get("code")
            for u in units_data.get("records", [])
            if "@uuid" in u
        }

        for parameter in parameters_data.get("records", []):
            name = parameter.get("name", "")
            unit_data = parameter.get("unit")
            if isinstance(unit_data, dict):
                unit = unit_data.get("code", "")
            else:
                unit = unit_lookup.get(unit_data, "")
            parameters.append({"name": name, "unit": unit})

        data["parameters"] = parameters
