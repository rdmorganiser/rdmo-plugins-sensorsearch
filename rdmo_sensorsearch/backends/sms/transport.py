from copy import deepcopy
from typing import Any, Protocol

from rdmo_sensorsearch.contracts import BackendFailure, BackendResult, BackendSuccess


class JSONFetcher(Protocol):
    def __call__(self, url: str, auth_token: str | None = None) -> Any: ...


def request_json(fetch: JSONFetcher, url: str, auth_token: str | None) -> BackendResult[Any]:
    """Translate the legacy client envelope only at the SMS transport boundary."""
    payload = fetch(url, auth_token=auth_token)
    if isinstance(payload, dict) and "errors" in payload:
        return BackendFailure(tuple(payload["errors"]))
    # Adapters never mutate transport-owned objects, including injected fixtures.
    return BackendSuccess(deepcopy(payload))
