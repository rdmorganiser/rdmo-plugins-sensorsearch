import logging
import re
from urllib.parse import quote

import requests

from rdmo.options.providers import Provider

from .config import get_user_agent, load_config

logger = logging.getLogger(__name__)


class O2ARegistrySearchProvider(Provider):
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
                            Defaults to "https://registry.o2a-data.de/index/rest/search/sensor-v2".count
    """

    def __init__(
        self,
        id_prefix="o2aregistry",
        text_prefix="O2A REGISTRY:",
        max_hits=10,
        base_url="https://registry.o2a-data.de/index/rest/search/sensor-v2",
        **kwargs,
    ):
        self.id_prefix = id_prefix
        self.text_prefix = text_prefix
        self.max_hits = max_hits
        self.base_url = base_url
        self.results = []

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
            return self.results

        try:
            query = (
                f"(title:({search}*)^2 OR id:(/{search}/)^20 OR "
                f"({search}*)^0) AND (states.itemState:(public devicestore)^0)"
            )
            response = requests.get(
                self.base_url + f"?hits={self.max_hits}" + "&q=" + quote(query),
                headers={"User-Agent": get_user_agent()},
            )
            logger.debug("Response: %s", response)
            json_data = response.json()
            # assemble list of options with id and display text
            for data_set in json_data.get("records", []):
                text = f"{self.text_prefix} {data_set['title']}"
                if data_set["metadata"]["serial"]:
                    text += f" (s/n: {data_set['metadata']['serial']}, id: {data_set['id']})"
                else:
                    text += f" (id: {data_set['id']})"
                self.results.append({"id": self.id_prefix + ":" + data_set["uniqueId"], "text": text})
        except requests.exceptions.RequestException as e:
            logger.error("Request failed: %s", e)

        return self.results


class SensorManagentSystemProvider(Provider):
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

    def __init__(self, id_prefix="sms", text_prefix="SMS:", max_hits=10, base_url=None, **kwargs):
        self.id_prefix = id_prefix
        self.text_prefix = text_prefix
        self.max_hits = max_hits
        self.base_url = base_url
        self.results = []

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
        if self.base_url is None:
            logger.error("base_url is not set!")
            return self.results

        if search is None:
            return self.results

        try:
            query = f"{search}"
            url = self.base_url + "?" + "q=" + quote(query)
            response = requests.get(url, headers={"User-Agent": get_user_agent()})
            logger.debug("Response: %s", response)
            json_data = response.json()
            # assemble list of options with id and display text
            for data_set in json_data.get("data", []):
                text = f"{self.text_prefix} "
                if data_set["attributes"]["long_name"]:
                    text += data_set["attributes"]["long_name"]
                else:
                    text += data_set["attributes"]["short_name"]
                if data_set["attributes"]["serial_number"]:
                    text += " (s/n: " + data_set["attributes"]["serial_number"] + ")"
                self.results.append({"id": self.id_prefix + ":" + data_set["id"], "text": text})
        except requests.exceptions.RequestException as e:
            logger.error("Request failed: %s", e)

        return self.results[: self.max_hits]


class GeophysicalInstrumentPoolPotsdamProvider(Provider):
    """
    Searches the GFZ Potsdam Geophysical Instrument Pool (GIPP) for instruments
    and returns options.

    This provider queries the GIPP API for a list of all instruments and then
    filters based on a provided search term. It constructs option objects
    containing the instrument code and a unique ID derived from the
    instrument's ID in the GIPP.

    Attributes:
        id_prefix (str):    Prefix for generated option IDs. Defaults to
                            "gfzgipp". This id_prefix can be used by handlers
                            (post_save) to query more data, when using
                            different instances.
        text_prefix (str):  Prefix for displayed option text. Defaults to
                            "GIPP:".
        max_hits (int):     Maximum number of search results to return.
                            Defaults to 10.
        base_url (str):     Base URL for the GIPP API endpoint. Defaults to
                            "https://gipp.gfz-potsdam.de/instruments".
    """

    def __init__(
        self,
        id_prefix="gfzgipp",
        text_prefix="GIPP:",
        max_hits=10,
        base_url="https://gipp.gfz-potsdam.de/instruments",
        **kwargs,
    ):
        self.id_prefix = id_prefix
        self.text_prefix = text_prefix
        self.max_hits = max_hits
        self.base_url = base_url
        self.results = []

    def get_all_instruments(self):
        """
        Retrieves a list of all instruments from the GIPP API.

        Returns:
            The json response containing instrument data as retrieved from the
            GIPP API, or an empty list if the request fails.
        """
        try:
            response = requests.get(
                self.base_url + "/index.json?limit=10000&program=MOSES", headers={"User-Agent": get_user_agent()}
            )
            logger.debug("Response: %s", response)
            json_data = response.json()
            return json_data
        except requests.exceptions.RequestException as e:
            logger.error("Request failed: %s", e)
        return []

    def get_options(self, project, search=None, user=None, site=None):
        """
        Searches the GIPP instrument list for instruments matching the provided
        search term.

        Does a simple search through the list of instruments retreived from the
        GIPP API.

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
        for instrument in self.get_all_instruments():
            for key, value in instrument["Instrument"].items():
                if re.search(search, value, flags=re.IGNORECASE):
                    self.results.append(
                        {
                            "id": self.id_prefix + ":" + instrument["Instrument"]["id"],
                            "text": self.text_prefix + " " + instrument["Instrument"]["code"],
                        }
                    )
                    break
        return self.results


class SensorsProvider(Provider):
    """
    A meta-provider for searching sensor data across multiple sources.

    This provider acts as a centralized hub for querying different sensor data
    providers. It leverages a configuration file to define which providers to
    use and their respective parameters. The `get_options` method aggregates
    search results from all configured providers.
    """

    search = True

    refresh = True

    def get_options(self, project, search=None, user=None, site=None):
        """
        Searches for sensor options across configured providers.

        This method first loads the provider configuration from a file. It then
        checks if a search term is provided and meets the minimum length
        requirement specified in the configuration. If a valid search term
        exists, it iterates through the configured providers, instantiating
        them with the specified parameters and calling their `get_options`
        methods to retrieve sensor options.

        Args:
            project (Project):      The Project object this provider is
                                    associated with.
            search (str, optional): The search term to filter sensors by.
                                    Defaults to None.
            user (User, optional):  The User object making the request.
                                    Defaults to None.
            site (Site, optional):  The Site object the provider is scoped to.
                                    Defaults to None.

        Returns:
            list: A list of dictionaries representing sensor options. Each
            dictionary contains "id" and "text" keys.
        """
        # load configuration
        configuration = load_config()

        # Only run search if we have a term or at least n characters
        min_search_len = configuration.get(f"{self.__class__.__name__}", {}).get("min_search_len", 3)
        if not search or len(search) < min_search_len:
            return []

        results = []

        logger.debug("Configuration: %s", configuration)
        provider_configurations = configuration.get(f"{self.__class__.__name__}", {}).get("providers", [])
        provider_instances = []
        for provider, configs in provider_configurations.items():
            if provider == self.__class__.__name__:
                logger.warning("Skipping configuration for self (%s). Misconfiguration.", self.__class__.__name__)
                continue
            for config in configs:
                try:
                    provider_instances.append(globals()[provider](**config))
                except KeyError:
                    logger.error("The provider %s does not exist. Check yor configuration.", provider)

        logger.debug("Search term: %s", search)
        for p in provider_instances:
            results += p.get_options(project, search, user, site)

        logger.debug("Results: %s", results)
        return results
