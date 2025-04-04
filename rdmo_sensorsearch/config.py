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

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


logger = logging.getLogger(__name__)


@cache
def load_config():
    """
    Loads the sensor search provider configuration from a TOML file.

    This function attempts to load the sensor provider configuration from a
    TOML file. It first tries to retrieve the configuration file name and path
    from settings variables. If those are not defined, it uses default values.
    The function then checks for environment variables that might override the
    file name or path. Finally, it opens the configuration file using `tomllib`
    and returns the parsed configuration as a dictionary.

    Returns:
        dict: A dictionary containing the loaded configuration settings.

    Raises:
        FileNotFoundError:          If the configuration file is not found.
        PermissionError:            If there are permission issues accessing
                                    the configuration file.
        tomllib.TOMLDecodeError:    If the configuration file cannot be
                                    decoded as valid TOML.

    """
    # load settings
    try:
        config_file_name = settings.SENSORS_SEARCH_PROVIDER_CONFIG_FILE_NAME
    except AttributeError:
        config_file_name = "config.toml"

    try:
        config_file_path = settings.SENSORS_SEARCH_PROVIDER_CONFIG_FILE_PATH
    except AttributeError:
        config_file_path = None

    # override by environment variables or use defaults
    config_file_name = os.getenv("SENSORS_SEARCH_PROVIDER_CONFIG_FILE_NAME", config_file_name)
    config_file_path = os.getenv("SENSORS_SEARCH_PROVIDER_CONFIG_FILE_PATH", config_file_path)

    if config_file_path is None:
        config_file_path = os.path.join(Path(__file__).parent, config_file_name)

    logger.debug("Try to open configuration file: %s", config_file_path)

    try:
        with open(config_file_path, "rb") as config_file:
            return tomllib.load(config_file)
    except (FileNotFoundError, PermissionError) as e:
        logger.error("Cannot open configuration file: %s", config_file_path)
        raise e from e
    except tomllib.TOMLDecodeError as e:
        logger.error("Failed to decode configuration file: %s", config_file_path)
        raise e from e
