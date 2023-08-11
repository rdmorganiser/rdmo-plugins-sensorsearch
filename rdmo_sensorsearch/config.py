import logging
import os
import sys
from pathlib import Path

from django.conf import settings

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


logger = logging.getLogger(__name__)


def load_config():
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
