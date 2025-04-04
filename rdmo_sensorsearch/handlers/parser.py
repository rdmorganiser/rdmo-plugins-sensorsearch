import logging

import jmespath

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
        mapped_values.update({f"{attribute_uri}": jmespath.search(path, data)})
    logger.debug("mapped_values %s", mapped_values)
    return mapped_values
