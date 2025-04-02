import logging
from urllib.parse import quote

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.providers.base import BaseSensorProvider

logger = logging.getLogger(__name__)


class SensorManagementSystemProvider(BaseSensorProvider):
    """
    Searches a Sensor Management System (SMS) API for sensor data and returns
    options for selection.

    This provider queries an SMS API endpoint for sensors matching a given
    search term. It then constructs option objects containing the sensor's
    long name (if available), short name, serial number (if available), and
    unique ID from the SMS.

    Attributes:
        id_prefix (str):    Prefix for generated option IDs. Defaults to "sms".
                            This id_prefix can be used by handlers (post_save)
                            to query more data, when using different instances.
        text_prefix (str):  Prefix for displayed option text. Defaults to
                            "SMS:".
        max_hits (int):     Maximum number of search results to return.
                            Defaults to 10.
        base_url (str):     Base URL for the SMS API endpoint. Must be set
                            before calling get_options().
    """

    id_prefix = "sms"
    text_prefix = "SMS:"
    max_hits = 10
    base_url = None  # must be set in config

    def get_query_url(self, search: str):
        query = quote(search)
        return f"{self.base_url}?q={query}"

    def get_options(self, project, search=None, user=None, site=None):
        """
        Retrieves options based on the provided search term from the SMS.

        Args:
            project (Project):      The RDMO project object.
            search (str, optional): Search term to query the O2A Registry.
                                    Defaults to None.
            user (User, optional):  Current user object. Not used in this
                                    implementation.
            site (Site, optional):  Site object. Not used in this
                                    implementation.

        Returns:
            list: A list of option dictionaries containing "id" and "text".
        """

        if search is None:
            return []

        optionset = []

        query_url = self.get_query_url(search)
        json_fetched = fetch_json(query_url)
        json_data = json_fetched.get("data", [])
        if not json_data:
            logger.debug(f"Empty response from SMS API for {query_url}")
            return []


        for data_set in json_data:
            attrs = data_set["attributes"]
            text = f"{self.text_prefix} {attrs.get('long_name') or attrs['short_name']}"
            if attrs.get("serial_number"):
                text += f" (s/n: {attrs['serial_number']})"

            optionset.append({
                "id": f"{self.id_prefix}:{data_set['id']}",
                "text": text
            })

        return optionset[: self.max_hits]
