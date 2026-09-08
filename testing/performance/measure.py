"""Optional NDJSON benchmark output alongside deterministic integration tests."""

import json
import math
import os
import tracemalloc
from collections import Counter
from pathlib import Path
from statistics import median
from time import perf_counter

from django.db import connection

from rdmo_sensorsearch.services.performance import capture_performance


def measure(operation):
    counts = Counter()
    sql_ms = 0.0

    def execute(execute, sql, params, many, context):
        nonlocal sql_ms
        kind = sql.lstrip().split(None, 1)[0].upper()
        started = perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            counts[kind] += 1
            sql_ms += (perf_counter() - started) * 1000

    with connection.execute_wrapper(execute), capture_performance() as record:
        result = operation()
    metrics = record.as_dict()
    metrics.update(sql=dict(counts), sql_ms=sql_ms)
    return result, metrics


def benchmark(name, operation):
    """Enable with SENSORSEARCH_BENCHMARK_OUTPUT=/tmp/sensorsearch.ndjson.

    Mutating scenarios must restore their fixture inside operation, or use
    repeated unchanged operations. Memory is measured separately from timings.
    """
    output = os.getenv("SENSORSEARCH_BENCHMARK_OUTPUT")
    if not output:
        return
    _, cold = measure(operation)
    for _ in range(5):
        operation()
    samples = [measure(operation)[1] for _ in range(20)]
    times = sorted(sample["wall_ms"] for sample in samples)
    tracemalloc.start()
    try:
        operation()
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    summary = {
        "name": name,
        "cold": cold,
        "median_ms": median(times),
        "p95_ms": times[math.ceil(len(times) * 0.95) - 1],
        "peak_bytes": peak_bytes,
        "samples": samples,
    }
    with Path(output).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(summary, sort_keys=True) + "\n")
