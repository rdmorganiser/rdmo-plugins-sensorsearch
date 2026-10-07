import logging

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.contracts import HandlerExecutionContext, HandlerResult
from rdmo_sensorsearch.handlers.base import BackendRecordHandler
from rdmo_sensorsearch.handlers.parser import evaluate_jmespath_mapping

logger = logging.getLogger(__name__)


class O2ARegistryItemHandler(BackendRecordHandler):
    """
    Synchronizes an item and its related metadata from the O2A Registry.

    To fetch additional data from the O2A REGISTRY at least three API calls
    must be made:
    1. Basic information about the item
    2. Parameters of the item
    3. Units to add them to the parameters
    4. Global units list (for parameter unit lookup)

    Connection identity and attribute mapping are supplied by typed assembly.
    """

    materialize_device_details = True

    # URL templates
    item_url = "{base_url}/items/{id}"
    contacts_url = "{base_url}/items/{id}/contacts"
    parameters_url = "{base_url}/items/{id}/parameters"
    units_url = "{base_url}/units"
    item_api_link_template = "{base_url}/items/{id}"
    item_frontend_link_template = "{base_url_origin}/items/{id}"
    device_link_attribute_uri = "https://rdmo.nfdi4earth.de/terms/domain/dataset/usage_technology/device-link"

    def handle(self, backend_id: str, *, context: HandlerExecutionContext, auth_token: str | None = None):
        """
        Synchronizes one O2A item with its RDMO value.

        Args:
            backend_id (str): The item ID to get additional information for.

        Returns:
            dict: A dictionary containing the mapped values from the O2A
                  REGISTRY response.

        """
        base_url = self.base_url
        # basic data
        data = fetch_json(self.item_url.format(base_url=base_url, id=backend_id))
        # contacts
        contacts_data = fetch_json(self.contacts_url.format(base_url=base_url, id=backend_id))
        # parameters
        parameters_data = fetch_json(self.parameters_url.format(base_url=base_url, id=backend_id))
        # units
        units_data = fetch_json(self.units_url.format(base_url=base_url))

        response_errors = self._response_errors(
            (
                ("item", data),
                ("contacts", contacts_data),
                ("parameters", parameters_data),
                ("units", units_data),
            ),
            backend_id,
        )
        if response_errors:
            return {"errors": response_errors}

        # extend basic data with contacts
        self.add_contacts_to_data(data, contacts_data)

        # extend basic data with parameters
        self.add_parameters_to_data(data, parameters_data, units_data)

        self.add_links_to_data(data, backend_id)

        logger.debug("data: %s", data)
        mapped_values = evaluate_jmespath_mapping(self.attribute_mapping, data)
        self.set_item_link(mapped_values, data)
        return HandlerResult(mapped_values=mapped_values)

    def _response_errors(self, responses, item_id: str) -> list[str]:
        errors = []
        for endpoint, payload in responses:
            if isinstance(payload, dict) and "errors" in payload:
                errors.extend(f"O2A {endpoint} request for item {item_id} failed: {error}" for error in payload["errors"])
            elif not isinstance(payload, dict):
                errors.append(f"Unexpected O2A {endpoint} payload for item {item_id}: {type(payload).__name__}")
            elif endpoint == "item" and not payload:
                errors.append(f"O2A item request for item {item_id} returned no data.")
        return errors

    def add_links_to_data(self, data: dict, item_id: str) -> None:
        values = {
            "base_url": self.base_url,
            "base_url_origin": self.base_url_origin,
            "id": item_id,
        }
        data.setdefault("links", {})
        data["links"]["api"] = self.item_api_link_template.format(**values)
        data["links"]["frontend"] = self.item_frontend_link_template.format(**values)

    def set_item_link(self, mapped_values: dict, data: dict) -> None:
        device_link_attribute_uri = getattr(self, "device_link_attribute_uri", None)
        if not device_link_attribute_uri:
            return
        frontend_link = data.get("links", {}).get("frontend")
        if isinstance(frontend_link, str) and frontend_link:
            mapped_values[device_link_attribute_uri] = frontend_link

    def add_contacts_to_data(self, data: dict, contacts_data: dict) -> None:
        contacts = []
        for contact in contacts_data.get("records", []):
            contact_data = contact.get("contact")
            # only add data if it is not a reference
            if contact_data and isinstance(contact_data, dict):
                simplified = {key: contact_data[key] for key in ("firstName", "lastName", "email") if key in contact_data}
                contacts.append(simplified)
        data["contacts"] = contacts

    def add_parameters_to_data(self, data: dict, parameters_data: dict, units_data: dict) -> None:
        # That's a bit special in the case of O2A. It is not guaranteed that
        # the unit is provided. Therefore it must be looked up on another
        # endpoint (`units_data`).
        parameters = []
        unit_lookup = {u["@uuid"]: u.get("code") for u in units_data.get("records", []) if "@uuid" in u}

        for parameter in parameters_data.get("records", []):
            name = parameter.get("name", "")
            unit_data = parameter.get("unit")
            if isinstance(unit_data, dict):
                unit = unit_data.get("code", "")
            else:
                unit = unit_lookup.get(unit_data, "")
            parameters.append({"name": name, "unit": unit})

        data["parameters"] = parameters
