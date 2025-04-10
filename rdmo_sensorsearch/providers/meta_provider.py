

import logging

from rdmo.options.providers import Provider

from rdmo_sensorsearch.config import load_config
from rdmo_sensorsearch.providers.factory import build_provider_instances

logger = logging.getLogger(__name__)

SENSORSPROVIDER_CONFIG_KEY = "SensorsProvider"
ALL_SENSOR_PROVIDERS = build_provider_instances(SENSORSPROVIDER_CONFIG_KEY)


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
        configuration = load_config()
        min_search_len = configuration.get(f"{SENSORSPROVIDER_CONFIG_KEY}", {}).get("min_search_len", 3)

        if not search or len(search) < min_search_len:
            return []

        logger.debug("Configuration: %s", configuration)
        logger.debug("Search term: %s", search)

        results = []
        for provider in ALL_SENSOR_PROVIDERS:
            results += provider.get_options(project, search, user, site)

        logger.debug("Results: %s", results)
        return results
