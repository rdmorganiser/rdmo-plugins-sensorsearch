import logging
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
from functools import cache
from threading import Event, Lock
from typing import Any

from django.conf import settings

import requests

from rdmo import __version__

from rdmo_sensorsearch.services.performance import count_event, measure_phase
from rdmo_sensorsearch.transport import TransportError

logger = logging.getLogger(__name__)


@dataclass
class _PendingRequest:
    event: Event = field(default_factory=Event)
    response: Any = None
    error: BaseException | None = None


class _RequestCache:
    def __init__(self):
        self._responses: dict[tuple[str, str | None], Any] = {}
        self._failures: dict[tuple[str, str | None], TransportError] = {}
        self._pending: dict[tuple[str, str | None], _PendingRequest] = {}
        self._lock = Lock()

    def get_or_fetch(
        self,
        key: tuple[str, str | None],
        fetcher: Callable[[], Any],
    ) -> Any:
        with self._lock:
            if key in self._failures:
                count_event("http.cache_hit")
                raise self._failures[key]
            if key in self._responses:
                count_event("http.cache_hit")
                return deepcopy(self._responses[key])

            pending = self._pending.get(key)
            if pending is None:
                pending = _PendingRequest()
                self._pending[key] = pending
                is_owner = True
            else:
                is_owner = False

        if not is_owner:
            count_event("http.shared_wait")
            pending.event.wait()
            if pending.error is not None:
                raise pending.error
            return deepcopy(pending.response)

        try:
            response = fetcher()
        except BaseException as error:
            with self._lock:
                pending.error = error
                if isinstance(error, TransportError):
                    self._failures[key] = error
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


def fetch_json(url: str, auth_token: str | None = None) -> Any:
    count_event("http.requested")
    request_cache = _REQUEST_CACHE.get()
    if request_cache is not None:
        return request_cache.get_or_fetch(
            (url, auth_token),
            lambda: _fetch_json_uncached(url, auth_token=auth_token),
        )
    return _fetch_json_uncached(url, auth_token=auth_token)


@measure_phase("http.executed")
def _fetch_json_uncached(url: str, auth_token: str | None = None) -> Any:
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
        count_event(f"http.status.{response.status_code}")
        logger.debug("Fetched data from %s with status=%s", url, response.status_code)
        try:
            json_data = response.json()
        except ValueError as error:
            count_event("http.error")
            logger.error("Invalid JSON returned from %s: %s", url, error)
            raise TransportError(str(error), url=url, status_code=response.status_code) from error
        if not json_data:
            logger.debug("Fetched data is empty for %s with status=%s", url, response.status_code)
        return json_data

    except requests.exceptions.HTTPError as e:
        count_event("http.error")
        status_code = getattr(e.response, "status_code", "unknown")
        response_text = getattr(e.response, "text", "")
        logger.error(
            "HTTP request failed for %s with status=%s and body=%s",
            url,
            status_code,
            response_text[:500],
        )
        raise TransportError(str(e), url=url, status_code=getattr(e.response, "status_code", None)) from e
    except requests.exceptions.RequestException as e:
        count_event("http.error")
        logger.error("Request failed for %s: %s", url, e)
        raise TransportError(str(e), url=url) from e


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
