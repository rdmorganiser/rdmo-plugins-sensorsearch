# SPDX-FileCopyrightText: 2023 - 2024 Hannes Fuchs (GFZ) <hannes.fuchs@gfz-potsdam.de>
# SPDX-FileCopyrightText: 2023 - 2024 Helmholtz Centre Potsdam - GFZ German Research Centre for Geosciences
#
# SPDX-License-Identifier: Apache-2.0

import logging
import os
import sys
from functools import cache
from pathlib import Path

from django.conf import settings

from rdmo_sensorsearch.config_models import ConfigValidationError, PluginConfig

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


logger = logging.getLogger(__name__)


def get_config_file_path() -> str:
    try:
        config_file_name = settings.SENSORSEARCH_CONFIG_FILE_NAME
    except AttributeError:
        config_file_name = "sensorsearch.toml"

    try:
        config_file_path = settings.SENSORSEARCH_CONFIG_FILE_PATH
    except AttributeError:
        config_file_path = None

    config_file_name = os.getenv("SENSORSEARCH_CONFIG_FILE_NAME", config_file_name)
    config_file_path = os.getenv("SENSORSEARCH_CONFIG_FILE_PATH", config_file_path)

    if config_file_path is not None:
        return config_file_path

    repository_config_path = Path(__file__).parent.parent / config_file_name
    if repository_config_path.is_file():
        return str(repository_config_path)
    return str(Path(__file__).parent / config_file_name)


@cache
def load_config_model() -> PluginConfig:
    """
    Loads the sensor search provider configuration from a TOML file.

    This function attempts to load the sensor provider configuration from a
    TOML file. It first tries to retrieve the configuration file name and path
    from settings variables. If those are not defined, it uses default values.
    The function then checks for environment variables that might override the
    file name or path. Finally, it opens the configuration file using `tomllib`
    validates it, and returns an immutable configuration model.

    Returns:
        PluginConfig: The validated immutable configuration model.

    Raises:
        FileNotFoundError:          If the configuration file is not found.
        PermissionError:            If there are permission issues accessing
                                    the configuration file.
        tomllib.TOMLDecodeError:    If the configuration file cannot be
                                    decoded as valid TOML.
        ConfigValidationError:      If the TOML structure or values violate
                                    the plugin configuration schema.

    """
    config_file_path = get_config_file_path()
    logger.debug("Try to open configuration file: %s", config_file_path)

    try:
        with open(config_file_path, "rb") as config_file:
            raw_config = tomllib.load(config_file)
            plugin_config = PluginConfig.from_mapping(raw_config)
            logger.debug(
                "Loaded sensor search configuration from %s with top-level keys: %s",
                config_file_path,
                sorted(raw_config.keys()),
            )
            return plugin_config
    except (FileNotFoundError, PermissionError) as e:
        logger.error("Cannot open configuration file: %s", config_file_path)
        raise e from e
    except tomllib.TOMLDecodeError as e:
        logger.error("Failed to decode configuration file: %s", config_file_path)
        raise e from e
    except ConfigValidationError:
        logger.exception("Invalid sensor search configuration: %s", config_file_path)
        raise


def clear_config_cache() -> None:
    """Clear the parsed configuration cache, primarily for tests and controlled reloads."""
    load_config_model.cache_clear()
    # Avoid importing the Django workflow graph merely to reset configuration
    # (the configuration API is also used by framework-independent tooling).
    registry = sys.modules.get("rdmo_sensorsearch.handlers.catalog_registry")
    if registry is not None:
        registry.clear_handler_registry()
    routing = sys.modules.get("rdmo_sensorsearch.workflows.event_routing")
    if routing is not None:
        routing.routing_attributes.cache_clear()
