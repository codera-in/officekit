"""Bounded, cached CPU and memory snapshots for the local resource overview."""

from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Callable
from typing import Any

import psutil

from officekit.engines.engine_jobs import DynamicJobEngine


CPU_SAMPLE_INTERVAL_SECONDS = 0.1
MINIMUM_SAMPLE_INTERVAL_SECONDS = 1.0
BYTES_PER_GIB = 1024**3
MAX_LOGICAL_CPUS = 1024
MAX_MEMORY_BYTES = 2**70


class SystemResourceError(RuntimeError):
    """Local CPU or memory data could not be read or validated."""


class SystemResourceService:
    def __init__(
        self,
        *,
        cpu_sample_provider: Callable[..., float] | None = None,
        memory_provider: Callable[[], Any] | None = None,
        cpu_count_provider: Callable[[], int | None] | None = None,
        fallback_cpu_count_provider: Callable[[], int | None] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        minimum_sample_interval_seconds: float = MINIMUM_SAMPLE_INTERVAL_SECONDS,
    ):
        if (
            isinstance(minimum_sample_interval_seconds, bool)
            or not isinstance(minimum_sample_interval_seconds, (int, float))
            or not math.isfinite(minimum_sample_interval_seconds)
            or not 0.1 <= minimum_sample_interval_seconds <= 60.0
        ):
            raise ValueError("Minimum resource sample interval is outside its supported bounds.")
        self._cpu_sample = cpu_sample_provider or psutil.cpu_percent
        self._memory = memory_provider or psutil.virtual_memory
        self._cpu_count = cpu_count_provider or (lambda: psutil.cpu_count(logical=True))
        self._fallback_cpu_count = fallback_cpu_count_provider or os.cpu_count
        self._clock = monotonic_clock
        self._minimum_sample_interval = float(minimum_sample_interval_seconds)
        self._lock = threading.Lock()
        self._last_snapshot: dict | None = None
        self._last_sampled_at: float | None = None

    def snapshot(self) -> dict:
        try:
            with self._lock:
                now = self._clock()
                if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now):
                    raise SystemResourceError("System resource information is unavailable.")
                if self._last_snapshot is not None and self._last_sampled_at is not None:
                    age = max(0.0, now - self._last_sampled_at)
                    if age < self._minimum_sample_interval:
                        return {**self._last_snapshot, "cached": True, "sample_age_ms": round(age * 1000)}
                snapshot, sampled_at = self._read_snapshot(now)
                self._last_snapshot = snapshot
                self._last_sampled_at = sampled_at
                return {**snapshot, "cached": False, "sample_age_ms": 0}
        except SystemResourceError:
            raise
        except Exception as error:
            raise SystemResourceError("System resource information is unavailable.") from error

    def _read_snapshot(self, start: float) -> tuple[dict, float]:
        cpu_percent = self._cpu_sample(interval=CPU_SAMPLE_INTERVAL_SECONDS)
        if (
            isinstance(cpu_percent, bool)
            or not isinstance(cpu_percent, (int, float))
            or not math.isfinite(cpu_percent)
            or not 0.0 <= cpu_percent <= 100.0
        ):
            raise SystemResourceError("System resource information is unavailable.")
        mem = self._memory()
        total = getattr(mem, "total", None)
        available = getattr(mem, "available", None)
        if (
            isinstance(total, bool)
            or not isinstance(total, int)
            or isinstance(available, bool)
            or not isinstance(available, int)
            or not 0 < total <= MAX_MEMORY_BYTES
            or not 0 <= available <= total
        ):
            raise SystemResourceError("System resource information is unavailable.")
        cores = self._resolve_cpu_count()
        used_estimate = total - available
        memory_percent = round((used_estimate / total) * 100.0, 1)
        workers = DynamicJobEngine.calculate_optimal_workers(
            simulated_cpus=cores,
            simulated_ram_gb=available / BYTES_PER_GIB,
        )
        sampled_at = self._clock()
        if (
            not isinstance(sampled_at, (int, float))
            or isinstance(sampled_at, bool)
            or not math.isfinite(sampled_at)
            or sampled_at < start
        ):
            raise SystemResourceError("System resource information is unavailable.")
        snapshot = {
            "cpu_count": cores,
            "cpu_percent": round(float(cpu_percent), 1),
            "cpu_sample_interval_seconds": CPU_SAMPLE_INTERVAL_SECONDS,
            "total_ram_gb": round(total / BYTES_PER_GIB, 2),
            "available_ram_gb": round(available / BYTES_PER_GIB, 2),
            "memory_total_bytes": total,
            "memory_available_bytes": available,
            "memory_used_estimate_bytes": used_estimate,
            "memory_percent": memory_percent,
            "optimal_workers": workers,
        }
        return snapshot, sampled_at

    def _resolve_cpu_count(self) -> int:
        try:
            value = self._cpu_count()
        except Exception:
            value = None
        if self._is_valid_cpu_count(value):
            return value
        try:
            fallback = self._fallback_cpu_count()
        except Exception:
            fallback = None
        if self._is_valid_cpu_count(fallback):
            return fallback
        return 1

    @staticmethod
    def _is_valid_cpu_count(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_LOGICAL_CPUS
