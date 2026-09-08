"""Opt-in, thread-safe measurements shared by a workflow and its HTTP workers.

Phase durations are cumulative and can overlap; they are not additive wall time.
No URLs, authentication tokens, or answer contents are collected.
"""

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import perf_counter


class PerformanceRecord:
    def __init__(self):
        self._lock = Lock()
        self._counts = defaultdict(int)
        self._durations = defaultdict(float)
        self.wall_ms = 0.0

    def add(self, name, *, count=1, duration_ms=0.0):
        with self._lock:
            self._counts[name] += count
            self._durations[name] += duration_ms

    def as_dict(self):
        with self._lock:
            return {
                "wall_ms": self.wall_ms,
                "counts": dict(self._counts),
                "cumulative_ms": dict(self._durations),
            }


_PERFORMANCE: ContextVar[PerformanceRecord | None] = ContextVar("sensorsearch_performance", default=None)


def count_event(name: str) -> None:
    record = _PERFORMANCE.get()
    if record is not None:
        record.add(name)


@contextmanager
def capture_performance():
    """Wrap the operation AND execution of its commit callbacks for full timing."""
    existing = _PERFORMANCE.get()
    if existing is not None:
        yield existing
        return
    record = PerformanceRecord()
    token = _PERFORMANCE.set(record)
    started = perf_counter()
    try:
        yield record
    finally:
        record.wall_ms = (perf_counter() - started) * 1000
        _PERFORMANCE.reset(token)


@contextmanager
def measure_phase(name: str):
    record = _PERFORMANCE.get()
    if record is None:
        yield
        return
    started = perf_counter()
    try:
        yield
    except BaseException:
        record.add(f"{name}.failed")
        raise
    finally:
        record.add(name, duration_ms=(perf_counter() - started) * 1000)
