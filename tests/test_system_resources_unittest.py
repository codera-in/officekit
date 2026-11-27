import math
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app import app
from officekit.engines.engine_system_resources import (
    SystemResourceError,
    SystemResourceService,
)


class FakeClock:
    def __init__(self, *times):
        self.times = iter(times)

    def __call__(self):
        return next(self.times)


def memory(total=8 * 1024**3, available=3 * 1024**3):
    return SimpleNamespace(total=total, available=available)


def service(*, cpu_percent=25.4, mem=None, cpus=8, clock=None):
    return SystemResourceService(
        cpu_sample_provider=Mock(return_value=cpu_percent),
        memory_provider=Mock(return_value=mem or memory()),
        cpu_count_provider=Mock(return_value=cpus),
        monotonic_clock=clock or FakeClock(10.0, 10.1),
    )


def test_first_sample_returns_actual_cpu_memory_and_worker_snapshot():
    cpu_provider = Mock(return_value=25.4)
    memory_provider = Mock(return_value=memory())
    service_instance = SystemResourceService(
        cpu_sample_provider=cpu_provider,
        memory_provider=memory_provider,
        cpu_count_provider=lambda: 8,
        monotonic_clock=FakeClock(10.0, 10.12),
    )

    result = service_instance.snapshot()

    assert result == {
        "cpu_count": 8,
        "cpu_percent": 25.4,
        "cpu_sample_interval_seconds": 0.1,
        "total_ram_gb": 8.0,
        "available_ram_gb": 3.0,
        "memory_total_bytes": 8 * 1024**3,
        "memory_available_bytes": 3 * 1024**3,
        "memory_used_estimate_bytes": 5 * 1024**3,
        "memory_percent": 62.5,
        "optimal_workers": 6,
        "cached": False,
        "sample_age_ms": 0,
    }
    cpu_provider.assert_called_once_with(interval=0.1)
    memory_provider.assert_called_once_with()


def test_fast_repeats_reuse_cached_sample_then_refresh_after_one_second():
    cpu_provider = Mock(side_effect=[10.0, 55.0])
    service_instance = SystemResourceService(
        cpu_sample_provider=cpu_provider,
        memory_provider=Mock(return_value=memory()),
        cpu_count_provider=lambda: 4,
        monotonic_clock=FakeClock(10.0, 10.1, 10.5, 11.1, 11.2),
    )

    first = service_instance.snapshot()
    cached = service_instance.snapshot()
    refreshed = service_instance.snapshot()

    assert first["cpu_percent"] == 10.0 and first["cached"] is False
    assert cached["cpu_percent"] == 10.0 and cached["cached"] is True
    assert cached["sample_age_ms"] == 400
    assert refreshed["cpu_percent"] == 55.0 and refreshed["cached"] is False
    assert cpu_provider.call_count == 2


@pytest.mark.parametrize("cpu_percent", [-0.1, 100.1, math.nan, math.inf, "10", True])
def test_rejects_invalid_cpu_utilization(cpu_percent):
    instance = service(cpu_percent=cpu_percent)

    with pytest.raises(SystemResourceError, match="unavailable"):
        instance.snapshot()


@pytest.mark.parametrize(
    ("total", "available"),
    [(0, 0), (-1, 0), (8, -1), (8, 9), (8.0, 4), (True, 0), (8, True)],
)
def test_rejects_invalid_memory_samples(total, available):
    instance = service(mem=memory(total, available))

    with pytest.raises(SystemResourceError, match="unavailable"):
        instance.snapshot()


@pytest.mark.parametrize("cpus", [0, -2, 2.5, True, "4"])
def test_invalid_cpu_counts_fall_back_to_os_cpu_count(cpus):
    instance = SystemResourceService(
        cpu_sample_provider=Mock(return_value=0.0),
        memory_provider=Mock(return_value=memory()),
        cpu_count_provider=Mock(return_value=cpus),
        fallback_cpu_count_provider=Mock(return_value=6),
        monotonic_clock=FakeClock(1.0, 1.1),
    )

    assert instance.snapshot()["cpu_count"] == 6


def test_sensor_exceptions_map_to_safe_service_error():
    instance = SystemResourceService(
        cpu_sample_provider=Mock(side_effect=OSError("private sensor details")),
        memory_provider=Mock(return_value=memory()),
        cpu_count_provider=Mock(return_value=8),
        monotonic_clock=FakeClock(1.0),
    )

    with pytest.raises(SystemResourceError, match="unavailable") as error:
        instance.snapshot()

    assert "private sensor details" not in str(error.value)


@pytest.mark.parametrize("interval", [True, 0, 0.05, 60.1, math.nan, "1"])
def test_rejects_invalid_minimum_sample_intervals(interval):
    with pytest.raises(ValueError, match="sample interval"):
        SystemResourceService(minimum_sample_interval_seconds=interval)


@pytest.mark.parametrize("times", [(math.nan,), (True,)])
def test_rejects_invalid_monotonic_clock_samples(times):
    instance = service(clock=FakeClock(*times))

    with pytest.raises(SystemResourceError, match="unavailable"):
        instance.snapshot()


def test_rejects_monotonic_clock_that_moves_backwards():
    instance = service(clock=FakeClock(10.0, 9.0))

    with pytest.raises(SystemResourceError, match="unavailable"):
        instance.snapshot()


def test_cpu_count_provider_exception_uses_valid_fallback():
    instance = SystemResourceService(
        cpu_sample_provider=Mock(return_value=0.0),
        memory_provider=Mock(return_value=memory()),
        cpu_count_provider=Mock(side_effect=OSError("cpu count unavailable")),
        fallback_cpu_count_provider=Mock(return_value=3),
        monotonic_clock=FakeClock(1.0, 1.1),
    )

    assert instance.snapshot()["cpu_count"] == 3


def test_bad_or_unavailable_cpu_count_fallback_uses_safe_minimum():
    for fallback_provider in (Mock(return_value=True), Mock(side_effect=OSError("fallback failed"))):
        instance = SystemResourceService(
            cpu_sample_provider=Mock(return_value=0.0),
            memory_provider=Mock(return_value=memory()),
            cpu_count_provider=Mock(return_value=None),
            fallback_cpu_count_provider=fallback_provider,
            monotonic_clock=FakeClock(1.0, 1.1),
        )
        assert instance.snapshot()["cpu_count"] == 1


def test_api_returns_typed_resource_snapshot():
    with patch("app.system_resource_service.snapshot", return_value={
        "cpu_count": 8, "cpu_percent": 12.5, "cpu_sample_interval_seconds": 0.1,
        "total_ram_gb": 8.0, "available_ram_gb": 3.0, "memory_total_bytes": 8 * 1024**3,
        "memory_available_bytes": 3 * 1024**3, "memory_used_estimate_bytes": 5 * 1024**3,
        "memory_percent": 62.5, "optimal_workers": 16, "cached": False, "sample_age_ms": 0,
    }):
        response = TestClient(app).get("/api/system/resources")

    assert response.status_code == 200
    assert response.json()["cpu_percent"] == 12.5
    assert response.json()["memory_percent"] == 62.5


def test_api_maps_sensor_failure_to_safe_service_unavailable():
    with patch("app.system_resource_service.snapshot", side_effect=SystemResourceError("private details")):
        response = TestClient(app).get("/api/system/resources")

    assert response.status_code == 503
    assert "private details" not in response.text
