import logging
import re
from urllib.parse import quote

import requests

# from cachetools import cached, TTLCache
from rdmo.options.providers import Provider

from .config import load_config, get_user_agent

logger = logging.getLogger(__name__)


class O2ARegistrySearchProvider(Provider):
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
        if search is None:
            return self.results

        try:
            query = (
                f"(title:({search}*)^2 OR id:(/{search}/)^20 OR "
                f"({search}*)^0) AND (states.itemState:(public devicestore)^0)"
            )
            response = requests.get(self.base_url + f"?hits={self.max_hits}" + "&q=" + quote(query), headers={"User-Agent": get_user_agent()})
            logger.debug("Response: %s", response)
            json_data = response.json()
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
    def __init__(self, id_prefix="sms", text_prefix="SMS:", max_hits=10, base_url=None, **kwargs):
        self.id_prefix = id_prefix
        self.text_prefix = text_prefix
        self.max_hits = max_hits
        self.base_url = base_url
        self.results = []

    def get_options(self, project, search=None, user=None, site=None):
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
            logger.debug("json_data: %s", json_data)
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

    # @cached(cache=TTLCache(maxsize=1024, ttl=600))
    def get_all_instruments(self):
        try:
            response = requests.get(self.base_url + "/index.json?limit=10000&program=MOSES", headers={"User-Agent": get_user_agent()})
            logger.debug("Response: %s", response)
            json_data = response.json()
            logger.debug("json_data: %s", json_data)
            return json_data
        except requests.exceptions.RequestException as e:
            logger.error("Request failed: %s", e)
        return []

    def get_options(self, project, search=None, user=None, site=None):
        # simple search
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
    search = True

    refresh = True

    def get_options(self, project, search=None, user=None, site=None):
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
