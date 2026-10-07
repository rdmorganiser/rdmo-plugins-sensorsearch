import logging
from urllib.parse import quote

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.providers.base import BaseRemoteSearchProvider

logger = logging.getLogger(__name__)


class O2ARegistryItemProvider(BaseRemoteSearchProvider):
    """
    Searches the O2A Registry for items and returns options for selection.

    This provider queries the O2A Registry API for items matching a
    given search term. It then constructs option objects containing the item
    title, serial number (if available), and unique ID from the registry.

    Connection identity, display prefix, and result limit are supplied by
    typed backend assembly.
    """

    query_url = "{base_url}?hits={hits}&q={query}"

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

        # keep alphanumerics(and Unicode characters) and spaces
        search = "".join(c for c in search if c.isalnum() or c.isspace())

        query = f"(title:({search}*)^2 OR id:(/{search}/)^20 OR ({search}*)^0) AND (states.itemState:(public devicestore)^0)"
        url = f"{self.base_url}?hits={self.max_hits}&q={quote(query)}"
        json_data = fetch_json(url)

        for record in json_data.get("records", []):
            optionset.append(self.parse_option(record))
            if len(optionset) >= self.max_hits:
                break

        return optionset

    def parse_option(self, data_set: dict) -> dict[str, str]:
        """
        Converts a single data_set entry to an option dictionary.

        Args:
            data_set (dict): The JSON dictionary for a single registry item.

        Returns:
            dict: An option dictionary with "id" and "text" keys.
        """
        title = data_set["title"]
        serial = data_set.get("metadata", {}).get("serial")
        unique_id = data_set["uniqueId"]
        registry_id = data_set["id"]

        if serial:
            text = f"{self.text_prefix}({unique_id}): {title} (s/n: {serial}, id: {registry_id})"
        else:
            text = f"{self.text_prefix}({unique_id}): {title} (id: {registry_id})"

        return {"id": f"{self.id_prefix}:{unique_id}", "text": text}
