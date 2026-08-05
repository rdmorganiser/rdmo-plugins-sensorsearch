import logging
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from functools import cache
from threading import Event, Lock

from django.conf import settings

import requests

from rdmo import __version__

logger = logging.getLogger(__name__)


@dataclass
class _PendingRequest:
    event: Event = field(default_factory=Event)
    response: dict | list | None = None
    error: BaseException | None = None


class _RequestCache:
    def __init__(self):
        self._responses: dict[tuple[str, str | None], dict | list] = {}
        self._pending: dict[tuple[str, str | None], _PendingRequest] = {}
        self._lock = Lock()

    def get_or_fetch(
        self,
        key: tuple[str, str | None],
        fetcher: Callable[[], dict | list],
    ) -> dict | list:
        with self._lock:
            cached = self._responses.get(key)
            if cached is not None:
                return deepcopy(cached)

            pending = self._pending.get(key)
            if pending is None:
                pending = _PendingRequest()
                self._pending[key] = pending
                is_owner = True
            else:
                is_owner = False

        if not is_owner:
            pending.event.wait()
            if pending.error is not None:
                raise pending.error
            return deepcopy(pending.response)

        try:
            response = fetcher()
        except BaseException as error:
            with self._lock:
                pending.error = error
                self._pending.pop(key, None)
                pending.event.set()
            raise

        with self._lock:
            stored_response = deepcopy(response)
            self._responses[key] = stored_response
            pending.response = stored_response
            self._pending.pop(key, None)
            pending.event.set()
        return deepcopy(stored_response)


_REQUEST_CACHE: ContextVar[_RequestCache | None] = ContextVar(
    "rdmo_sensorsearch_request_cache",
    default=None,
)


@contextmanager
def deduplicate_json_requests():
    existing_cache = _REQUEST_CACHE.get()
    if existing_cache is not None:
        yield
        return

    token = _REQUEST_CACHE.set(_RequestCache())
    try:
        yield
    finally:
        _REQUEST_CACHE.reset(token)


def fetch_json(url: str, auth_token: str | None = None) -> dict | list:
    request_cache = _REQUEST_CACHE.get()
    if request_cache is not None:
        return request_cache.get_or_fetch(
            (url, auth_token),
            lambda: _fetch_json_uncached(url, auth_token=auth_token),
        )
    return _fetch_json_uncached(url, auth_token=auth_token)


def _fetch_json_uncached(url: str, auth_token: str | None = None) -> dict | list:
    timeout = get_request_timeout()
    logger.debug("Requesting JSON from %s with timeout=%s", url, timeout)
    headers = {"User-Agent": get_user_agent()}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    try:
        response = requests.get(
            url,
            headers=headers,
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
            user_agent += f" ({settings.DEFAULT_FROM_EMAIL})"
    except AttributeError:
        pass
    return user_agent


@cache
def get_request_timeout():
    try:
        return settings.SENSORSEARCH_REQUEST_TIMEOUT
    except AttributeError:
        return 10
