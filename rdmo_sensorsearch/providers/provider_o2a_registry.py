import logging
import re
from urllib.parse import quote

from rdmo_sensorsearch.providers.base import BaseSensorProvider
from rdmo_sensorsearch.config import get_user_agent

logger = logging.getLogger(__name__)


class O2ARegistrySearchProvider(BaseSensorProvider):
    """
    Searches the O2A REGISTRY for sensor data and returns options for selection.

    This provider queries the O2A REGISTRY API for sensor data matching a
    given search term. It then constructs option objects containing the sensor
    title, serial number (if available), and unique ID from the registry.

    Attributes:
        id_prefix (str):    Prefix for generated option IDs. Defaults to
                            "o2aregistry". This id_prefix can be used by
                            handlers (post_save) to query more data, when
                            using different instances.
        text_prefix (str):  Prefix for displayed option text. Defaults to
                            "O2A REGISTRY:".
        max_hits (int):     Maximum number of search results to return.
                            Defaults to 10.
        base_url (str):     Base URL for the O2A Registry API endpoint.
                            Defaults to "https://registry.o2a-data.de/index/rest/search/sensor-v2".
    """

    id_prefix = "o2aregistry"
    text_prefix = "O2A REGISTRY:"
    max_hits = 10
    base_url = "https://registry.o2a-data.de/index/rest/search/sensor-v2"

    def get_options(self, project, search=None, user=None, site=None):
        """
        Retrieves options based on the provided search term.

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

        optionset: list[dict[str, str]] = []

        search = re.sub(r"[^A-Za-z0-9\s]", "", search)
        query = (
            f"(title:({search}*)^2 OR id:(/{search}/)^20 OR "
            f"({search}*)^0) AND (states.itemState:(public devicestore)^0)"
        )
        url = f"{self.base_url}?hits={self.max_hits}&q={quote(query)}"
        json_data = self.fetch_json(url)

        for data_set in json_data.get("records", []):
            text = f"{self.text_prefix} {data_set['title']}"
            serial = data_set.get("metadata", {}).get("serial")
            if serial:
                text += f" (s/n: {serial}, id: {data_set['id']})"
            else:
                text += f" (id: {data_set['id']})"

            optionset.append({
                "id": f"{self.id_prefix}:{data_set['uniqueId']}",
                "text": text
            })

        return optionset[: self.max_hits]
