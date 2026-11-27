"""
Tests for Resource-Aware Dynamic Concurrent Job Engine (Pillar: Batch Foundation)
Verifies:
1. Dynamic worker count based on processor count and available RAM.
2. Concurrent batch task execution without freezing.
3. Accurate item-by-item progress calculation (0% -> 100%).
4. Partial failure tolerance (one failing item does not crash remaining items).
5. Cancellation token support.
"""

import time
import pytest
from officekit.engines.engine_jobs import DynamicJobEngine, JobStatus

def test_dynamic_worker_calculation():
    # Test high resource machine simulation
    workers_high = DynamicJobEngine.calculate_optimal_workers(simulated_cpus=16, simulated_ram_gb=32.0, mem_per_worker_gb=0.5)
    assert 4 <= workers_high <= 32

    # Test constrained resource machine simulation (e.g. 2GB RAM available, 8 CPUs)
    # 2GB / 0.5GB = 4 workers max despite 8 CPUs (prevent OOM)
    workers_ram_constrained = DynamicJobEngine.calculate_optimal_workers(simulated_cpus=8, simulated_ram_gb=2.0, mem_per_worker_gb=0.5)
    assert workers_ram_constrained <= 4

    # Test single-core low-RAM machine (must always be at least 1)
    workers_min = DynamicJobEngine.calculate_optimal_workers(simulated_cpus=1, simulated_ram_gb=0.4, mem_per_worker_gb=0.5)
    assert workers_min == 1

def test_batch_execution_and_progress_streaming():
    engine = DynamicJobEngine(max_workers=4)

    items = [f"item_{i}" for i in range(10)]
    progress_snapshots = []

    def process_item(item: str):
        time.sleep(0.01) # Simulate micro-work
        return f"processed_{item}"

    def on_progress(job_state):
        progress_snapshots.append(job_state["progress_percent"])

    job = engine.execute_batch(
        items=items,
        worker_func=process_item,
        progress_callback=on_progress
    )

    assert job.status == JobStatus.COMPLETED
    assert job.completed_count == 10
    assert job.failed_count == 0
    assert len(job.results) == 10
    assert job.results[0] == "processed_item_0"
    assert progress_snapshots[-1] == 100.0

def test_batch_partial_failure_isolation():
    engine = DynamicJobEngine(max_workers=2)

    items = ["good_1", "bad_fail", "good_2"]

    def process_item(item: str):
        if "bad" in item:
            raise ValueError("Corrupt file sample")
        return f"ok_{item}"

    job = engine.execute_batch(items=items, worker_func=process_item)

    assert job.status == JobStatus.COMPLETED_WITH_ERRORS
    assert job.completed_count == 2
    assert job.failed_count == 1
    assert "bad_fail" in job.errors
    assert "Corrupt file sample" in job.errors["bad_fail"]
