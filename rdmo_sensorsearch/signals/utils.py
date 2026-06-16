from contextlib import contextmanager
from contextvars import ContextVar

_MUTE_POST_SAVE: ContextVar[bool] = ContextVar("rdmo_sensorsearch_mute_post_save", default=False)


def _is_muted() -> bool:
    return _MUTE_POST_SAVE.get()


@contextmanager
def mute_value_post_save():
    token = _MUTE_POST_SAVE.set(True)
    try:
        yield
    finally:
        _MUTE_POST_SAVE.reset(token)
