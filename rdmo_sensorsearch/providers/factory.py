"""Construct search consumers from validated typed configuration."""

from rdmo_sensorsearch.backend_assembly import PROVIDER_BUILDERS
from rdmo_sensorsearch.config import load_config_model
from rdmo_sensorsearch.providers.base import BaseRemoteSearchProvider


def build_provider_instances(config_section_name: str) -> list[BaseRemoteSearchProvider]:
    config = load_config_model()
    return [
        PROVIDER_BUILDERS[instance.provider_name](instance, config.backend(instance.backend))
        for instance in config.search_provider(config_section_name).providers
    ]
