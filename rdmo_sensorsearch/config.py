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
        CONFIG_FILE_NAME = settings.SENSORS_SEARCH_PROVIDER_CONFIG_FILE_NAME
    except AttributeError:
        CONFIG_FILE_NAME = "config.toml"

    try:
        CONFIG_FILE_PATH = settings.SENSORS_SEARCH_PROVIDER_CONFIG_FILE_PATH
    except AttributeError:
        CONFIG_FILE_PATH = None

    # override by environment variables or use defaults
    CONFIG_FILE_NAME = os.getenv("SENSORS_SEARCH_PROVIDER_CONFIG_FILE_NAME", CONFIG_FILE_NAME)
    CONFIG_FILE_PATH = os.getenv("SENSORS_SEARCH_PROVIDER_CONFIG_FILE_PATH", CONFIG_FILE_PATH)

    if CONFIG_FILE_PATH is None:
        CONFIG_FILE_PATH = os.path.join(Path(__file__).parent, CONFIG_FILE_NAME)

    logger.debug("Try to open configuration file: %s", CONFIG_FILE_PATH)

    try:
        with open(CONFIG_FILE_PATH, "rb") as config_file:
            return tomllib.load(config_file)
    except (FileNotFoundError, PermissionError) as e:
        logger.error("Connot open configuration file: %s", CONFIG_FILE_PATH)
        raise e from e
    except tomllib.TOMLDecodeError as e:
        logger.error("Failed to decode configuration file: %s", CONFIG_FILE_PATH)
        raise e from e
