"""Injected transports for decoded JSON and explicit failure fixtures."""

from functools import wraps

from rdmo_sensorsearch.transport import TransportError


def transport_payload(payload):
    if isinstance(payload, TransportError):
        raise payload
    return payload


def raising_fetch(fetch):
    @wraps(fetch)
    def wrapped(*args, **kwargs):
        return transport_payload(fetch(*args, **kwargs))

    return wrapped
