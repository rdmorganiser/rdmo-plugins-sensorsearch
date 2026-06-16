import logging
from datetime import datetime, timezone as dt_timezone

import jmespath
from jmespath.exceptions import JMESPathError

logger = logging.getLogger(__name__)


def map_jamespath_to_attribute_uri(attribute_mapping: dict, data: dict) -> dict:
    """
    Maps values from the response data to attribute URIs using JamesPath
    expressions.

    The mapping is usually provided by the configuration file.

    Args:
        attribute_mapping (dict): The mapping of attribute names to JamesPath URIs.
        data (dict): The JSON response data.

    Returns:
        dict: A dictionary containing mapped values with attribute URIs as
              keys.

    """
    mapped_values = {}
    for path, attribute_uri in attribute_mapping.items():
        try:
            value = jmespath.search(path, data)
        except JMESPathError:
            logger.exception(
                "Skipping attribute mapping for %s because JMESPath evaluation failed: %s",
                attribute_uri,
                path,
            )
            continue

        mapped_values.update({f"{attribute_uri}": value})
    logger.debug("mapped_values %s", mapped_values)
    return mapped_values


def parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None