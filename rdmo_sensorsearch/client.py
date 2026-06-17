import logging
from functools import cache

from django.conf import settings

import requests

from rdmo import __version__

logger = logging.getLogger(__name__)


def fetch_json(url: str) -> dict | list:
    timeout = get_request_timeout()
    logger.debug("Requesting JSON from %s with timeout=%s", url, timeout)
    try:
        response = requests.get(
            url,
            headers={"User-Agent": get_user_agent()},
            timeout=timeout,
        )
        response.raise_for_status()
        logger.debug("Fetched data from %s with status=%s", url, response.status_code)
        json_data = response.json()
        if not json_data:
            logger.debug("Fetched data is empty for %s with status=%s", url, response.status_code)
        return json_data

    except requests.exceptions.HTTPError as e:
        status_code = getattr(e.response, "status_code", "unknown")
        response_text = getattr(e.response, "text", "")
        logger.error(
            "HTTP request failed for %s with status=%s and body=%s",
            url,
            status_code,
            response_text[:500],
        )
        return {"errors": [str(e)]}
    except requests.exceptions.RequestException as e:
        logger.error("Request failed for %s: %s", url, e)
        return {"errors": [str(e)]}


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


@cache
def get_request_timeout():
    try:
        return settings.SENSORS_SEARCH_PROVIDER_REQUEST_TIMEOUT
    except AttributeError:
        return 10
