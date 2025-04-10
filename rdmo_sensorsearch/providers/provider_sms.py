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

    id_prefix: str = "sms"
    text_prefix = "SMS:"
    # base_url is set by config
    query_url = "{base_url}?q={query}"

    option_id = "{id_prefix}:{id}"
    option_text = "{prefix} {name}{serial}"
    max_hits = 10


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
        url = self.query_url.format(base_url=self.base_url, query=query)
        json_fetched = fetch_json(url)

        json_data = json_fetched.get("data", [])
        if not json_data:
            logger.debug(f"Empty response from SMS API for {search}")
            return []

        optionset = []

        for sensor in json_data[:self.max_hits]:
            optionset.append(
                {
                    "id": self.option_id.format(id_prefix=self.id_prefix, id=sensor["id"]),
                    "text": self._format_sensor_text(sensor["attributes"]),
                }
            )
        return optionset

    def _format_sensor_text(self, attrs: dict) -> str:
        name = attrs.get("long_name") or attrs.get("short_name", "")
        serial = f" (s/n: {attrs['serial_number']})" if attrs.get("serial_number") else ""
        return self.option_text.format(prefix=self.text_prefix, name=name, serial=serial)
