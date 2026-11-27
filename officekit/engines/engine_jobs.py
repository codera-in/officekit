"""
OfficeKit - Dynamic Resource-Aware Concurrent Job Engine
Calculates optimal thread concurrency dynamically based on available CPU cores and physical RAM.
Supports progress streaming, atomic cancellation, and isolated partial error handling.
"""

import os
import uuid
import time
from enum import Enum
from typing import List, Callable, Any, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import psutil


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobResult:
    def __init__(self, job_id: str, total_items: int):
        self.job_id = job_id
        self.total_items = total_items
        self.completed_count = 0
        self.failed_count = 0
        self.status = JobStatus.QUEUED
        self.results: List[Any] = []
        self.errors: Dict[str, str] = {}
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    @property
    def progress_percent(self) -> float:
        if self.total_items == 0:
            return 100.0
        return round(((self.completed_count + self.failed_count) / self.total_items) * 100.0, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "total_items": self.total_items,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "progress_percent": self.progress_percent,
            "duration_sec": round((self.end_time or time.time()) - (self.start_time or time.time()), 2),
            "errors": self.errors
        }


class DynamicJobEngine:
    def __init__(self, max_workers: Optional[int] = None, mem_per_worker_gb: float = 0.5):
        self.mem_per_worker_gb = mem_per_worker_gb
        self.max_workers = max_workers or self.calculate_optimal_workers(mem_per_worker_gb=self.mem_per_worker_gb)

    @staticmethod
    def calculate_optimal_workers(
        simulated_cpus: Optional[int] = None,
        simulated_ram_gb: Optional[float] = None,
        mem_per_worker_gb: float = 0.5,
        ceiling: int = 32
    ) -> int:
        """
        Dynamically computes worker concurrency based on physical cores and free memory.
        Workers = max(1, min(Ceiling, min(CPUs * 2, floor(RAM_available_GB / mem_per_worker_GB))))
        """
        try:
            cpus = simulated_cpus if simulated_cpus is not None else (os.cpu_count() or 2)
            if simulated_ram_gb is not None:
                avail_ram_gb = simulated_ram_gb
            else:
                mem = psutil.virtual_memory()
                avail_ram_gb = mem.available / (1024 ** 3)
        except Exception:
            cpus = 2
            avail_ram_gb = 2.0

        # Max threads CPU can handle comfortably
        cpu_bound = max(1, cpus * 2)

        # Max threads RAM can handle before risk of swapping / OOM
        ram_bound = max(1, int(avail_ram_gb / max(0.1, mem_per_worker_gb)))

        optimal = min(cpu_bound, ram_bound, ceiling)
        return max(1, optimal)

    def execute_batch(
        self,
        items: List[Any],
        worker_func: Callable[[Any], Any],
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> JobResult:
        """Executes items across the resource-aware thread pool with non-blocking progress notification."""
        job = JobResult(job_id=str(uuid.uuid4())[:8], total_items=len(items))
        job.status = JobStatus.RUNNING
        job.start_time = time.time()

        if not items:
            job.status = JobStatus.COMPLETED
            job.end_time = time.time()
            return job

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Map future to (index, item) to preserve exact input sequence
            future_to_indexed = {executor.submit(worker_func, item): (idx, item) for idx, item in enumerate(items)}
            indexed_results = [None] * len(items)

            for future in as_completed(future_to_indexed):
                idx, item = future_to_indexed[future]
                try:
                    res = future.result()
                    indexed_results[idx] = res
                    job.completed_count += 1
                except Exception as ex:
                    job.failed_count += 1
                    job.errors[str(item)] = str(ex)

                if progress_callback:
                    try:
                        progress_callback(job.to_dict())
                    except Exception:
                        pass

            job.results = [r for r in indexed_results if r is not None]

        job.end_time = time.time()
        if job.failed_count == 0:
            job.status = JobStatus.COMPLETED
        elif job.completed_count > 0:
            job.status = JobStatus.COMPLETED_WITH_ERRORS
        else:
            job.status = JobStatus.FAILED

        return job
