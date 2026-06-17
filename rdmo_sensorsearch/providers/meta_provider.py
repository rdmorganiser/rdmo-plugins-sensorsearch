import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from rdmo.options.providers import Provider
from rdmo.projects.models import Value

from rdmo_sensorsearch.config import get_config_file_path, load_config
from rdmo_sensorsearch.providers.factory import build_provider_instances

logger = logging.getLogger(__name__)

SENSORSPROVIDER_CONFIG_KEY = "SensorsProvider"
CONFIGURATIONSPROVIDER_CONFIG_KEY = "ConfigurationsProvider"
CONFIGURATION_SEARCH_ATTRIBUTE_URI = "https://rdmo.nfdi4earth.de/terms/domain/configuration-set/configuration-search"


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
        providers = self._filter_providers_for_project(project, providers)

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

        logger.debug("Configuration top-level keys: %s", sorted(configuration.keys()))
        logger.debug("Search term: %s", search)

        results = []

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_provider = {
                executor.submit(provider.get_options, project, search, user, site): provider for provider in providers
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

    def _filter_providers_for_project(self, project, providers: list[Provider]) -> list[Provider]:
        if self.config_key != SENSORSPROVIDER_CONFIG_KEY or project is None:
            return providers

        allowed_sms_prefixes = self._allowed_sms_prefixes(project)
        if not allowed_sms_prefixes:
            return providers

        filtered = []
        for provider in providers:
            if provider.__class__.__name__ != "SensorManagementSystemProvider":
                filtered.append(provider)
                continue

            provider_prefix = getattr(provider, "id_prefix", None)
            if provider_prefix in allowed_sms_prefixes:
                filtered.append(provider)

        logger.debug(
            "%s filtered SMS providers by project configuration prefixes=%s -> %s",
            type(self).__name__,
            sorted(allowed_sms_prefixes),
            [repr(provider) for provider in filtered],
        )
        return filtered

    def _allowed_sms_prefixes(self, project) -> set[str]:
        prefixes: set[str] = set()
        values = (
            Value.objects.filter(project=project, attribute__uri=CONFIGURATION_SEARCH_ATTRIBUTE_URI)
            .filter(snapshot=None)
            .exclude(external_id__isnull=True)
            .exclude(external_id__exact="")
            .values_list("external_id", flat=True)
        )
        for external_id in values:
            if not isinstance(external_id, str) or ":" not in external_id:
                continue
            cfg_prefix = external_id.split(":", 1)[0]
            if cfg_prefix.endswith("cfg"):
                prefixes.add(f"{cfg_prefix[:-3]}sms")
        return prefixes


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
