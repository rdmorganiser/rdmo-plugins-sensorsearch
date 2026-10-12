"""Neutral JSON transport boundary shared by injected backend adapters."""

from copy import deepcopy
from typing import Any, Protocol

from rdmo_sensorsearch.contracts import BackendFailure, BackendResult, BackendSuccess


class TransportError(RuntimeError):
    def __init__(self, message: str, *, url: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.url = url
        self.status_code = status_code


class JSONFetcher(Protocol):
    def __call__(self, url: str, auth_token: str | None = None) -> Any: ...


def request_json(fetch: JSONFetcher, url: str, auth_token: str | None) -> BackendResult[Any]:
    """Translate transport failures and protect transport-owned documents."""
    try:
        payload = fetch(url, auth_token=auth_token)
    except TransportError as error:
        return BackendFailure((str(error),))
    return BackendSuccess(deepcopy(payload))
