import logging
from urllib.parse import quote

from rdmo_sensorsearch.providers.base import BaseSensorProvider
from rdmo_sensorsearch.config import get_user_agent

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

        query = quote(search)
        url = f"{self.base_url}/devices?q={query}"
        json_data = self.fetch_json(url)

        for data_set in json_data.get("data", []):
            attrs = data_set["attributes"]
            text = f"{self.text_prefix} {attrs.get('long_name') or attrs['short_name']}"
            if attrs.get("serial_number"):
                text += f" (s/n: {attrs['serial_number']})"

            self.results.append({
                "id": f"{self.id_prefix}:{data_set['id']}",
                "text": text
            })

        return self.results[: self.max_hits]
