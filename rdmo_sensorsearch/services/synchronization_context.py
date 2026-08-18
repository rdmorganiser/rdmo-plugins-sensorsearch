"""Context state used to prevent recursive synchronization signals."""

from contextlib import contextmanager
from contextvars import ContextVar

_MUTE_VALUE_SYNC: ContextVar[bool] = ContextVar("rdmo_sensorsearch_mute_value_sync", default=False)


def is_value_sync_muted() -> bool:
    return _MUTE_VALUE_SYNC.get()


@contextmanager
def mute_value_sync():
    token = _MUTE_VALUE_SYNC.set(True)
    try:
        yield
    finally:
        _MUTE_VALUE_SYNC.reset(token)
