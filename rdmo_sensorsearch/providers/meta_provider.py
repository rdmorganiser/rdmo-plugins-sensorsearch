import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from rdmo.options.providers import Provider

from rdmo_sensorsearch.config import get_config_file_path, load_config
from rdmo_sensorsearch.providers.factory import build_provider_instances

logger = logging.getLogger(__name__)

SENSORSPROVIDER_CONFIG_KEY = "SensorsProvider"
CONFIGURATIONSPROVIDER_CONFIG_KEY = "ConfigurationsProvider"


class BaseMetaProvider(Provider):
    search = True

    refresh = True

    config_key: str | None = None

    def get_options(self, project, search=None, user=None, site=None):
        if self.config_key is None:
            raise NotImplementedError(f"{type(self).__name__} must define `config_key`")

        configuration = load_config()
        min_search_len = configuration.get(self.config_key, {}).get("min_search_len", 3)
        providers = build_provider_instances(self.config_key)

        logger.debug(
            "%s.get_options called with search=%r, min_search_len=%s, config_path=%s, providers=%s",
            type(self).__name__,
            search,
            min_search_len,
            get_config_file_path(),
            [repr(provider) for provider in providers],
        )

        if not search or len(search) < min_search_len:
            logger.debug(
                "%s returning no results because search term is missing or shorter than min_search_len",
                type(self).__name__,
            )
            return []

        if not providers:
            logger.warning(
                "%s has no configured backend providers. Check %s [%s].providers",
                type(self).__name__,
                get_config_file_path(),
                self.config_key,
            )
            return []

        logger.debug("Configuration: %s", configuration)
        logger.debug("Search term: %s", search)

        results = []

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_provider = {
                executor.submit(provider.get_options, project, search, user, site): provider
                for provider in providers
            }

            for future in as_completed(future_to_provider):
                try:
                    result = future.result()
                    results.extend(result)
                except Exception as e:
                    provider = future_to_provider[future]
                    logger.warning("Provider %s failed with exception: %s", provider.__class__.__name__, e)

        logger.debug("Results: %s", results)
        return results


class SensorsProvider(BaseMetaProvider):
    """
    A meta-provider for searching sensor data across multiple sources.
    """

    config_key = SENSORSPROVIDER_CONFIG_KEY


class ConfigurationsProvider(BaseMetaProvider):
    """
    A meta-provider for searching configuration data across multiple sources.
    """

    config_key = CONFIGURATIONSPROVIDER_CONFIG_KEY
