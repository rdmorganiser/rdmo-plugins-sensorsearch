import logging
import sys
from functools import cache

from django.conf import settings

import requests
from django.http import Http404

from rdmo import __version__

if sys.version_info >= (3, 11):
    pass
else:
    pass


logger = logging.getLogger(__name__)


def fetch_json(url: str) -> dict| list:
    try:
        response = requests.get(url, headers={"User-Agent": get_user_agent()})
        response.raise_for_status()
        logger.debug("Fetched data from %s: %s", url, response)
        json_data = response.json()
        if not json_data:
            logger.debug("Fetched data is empty %s: %s", url, response)
        return json_data

    except requests.exceptions.RequestException as e:
        logger.error("Request failed for %s: %s", url, e)
        return {'errors': [str(e)]}



@cache
def get_user_agent():
    """
    Constructs a user agent string for HTTP requests.

    This function generates a user agent string that identifies the RDMO
    SensorSearch plugin along with the RDMO version and optionally the email
    address configured in settings.

    Returns:
        str: A formatted user agent string.
    """
    user_agent = f"rdmo/{__version__} SensorSearch Plugin https://github.com/rdmorganiser/rdmo-plugins-sensorsearch"
    try:
        if settings.DEFAULT_FROM_EMAIL:
            user_agent += f"{user_agent} ({settings.DEFAULT_FROM_EMAIL})"
    except AttributeError:
        pass
    return user_agent
