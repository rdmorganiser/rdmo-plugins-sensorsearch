from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest

from rdmo_sensorsearch.services.performance import capture_performance, count_event, measure_phase


def test_measurement_is_opt_in_nested_and_shared_across_workers():
    count_event("ignored")
    with capture_performance() as record:
        with capture_performance() as nested:
            assert nested is record
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(copy_context().run, count_event, "work") for _ in range(100)]
            for future in futures:
                future.result()
        with pytest.raises(ValueError), measure_phase("failure"):
            raise ValueError("expected")
    metrics = record.as_dict()
    assert metrics["counts"] == {"work": 100, "failure": 1, "failure.failed": 1}
    assert metrics["wall_ms"] >= metrics["cumulative_ms"]["failure"] >= 0
    with capture_performance() as next_record:
        pass
    assert next_record.as_dict()["counts"] == {}
