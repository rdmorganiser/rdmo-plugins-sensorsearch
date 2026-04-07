import logging

from rdmo_sensorsearch.config import load_config
from rdmo_sensorsearch.providers.registry import PROVIDER_REGISTRY

logger = logging.getLogger(__name__)


def build_provider_instances(config_section_name: str) -> list:
    """
    Factory method to create provider instances from config.

    Args:
        config_section_name (str): Name of the top-level section in config, usually the provider class name.

    Returns:
        list: List of instantiated provider objects.
    """
    configuration = load_config()
    provider_definitions = configuration.get(config_section_name, {}).get("providers", {})
    logger.debug(
        "Building provider instances for %s from configured provider keys: %s",
        config_section_name,
        sorted(provider_definitions.keys()),
    )

    flattened_provider_definitions = [
        (provider_name, config)
        for provider_name, configs in provider_definitions.items()
        for config in configs
    ]

    instances = []
    for provider_name, provider_config in flattened_provider_definitions:
        try:
            provider_cls = PROVIDER_REGISTRY[provider_name]
            instances.append(provider_cls(**provider_config))
        except KeyError:
            logger.error("Provider class %s not found in registry", provider_name)
        except TypeError as e:
            logger.error("Error initializing %s with config %s: %s", provider_name, provider_config, e)

    logger.debug(
        "Built %s provider instance(s) for %s: %s",
        len(instances),
        config_section_name,
        [repr(instance) for instance in instances],
    )
    return instances
