"""Safe, bounded process listing and termination for OfficeKit system tools."""

from __future__ import annotations

import math
import os
import plistlib
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import psutil


MAX_PID = 4_194_304
MIN_KILLABLE_PID = 2
DEFAULT_PROCESS_LIMIT = 30
MAX_PROCESS_LIMIT = 100
CACHE_TTL_SECONDS = 1.0
MAX_IOREG_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_APP_INFO_BYTES = 512 * 1024


def macos_gpu_process_times(run=subprocess.run) -> dict[int, int] | None:
    """Read best-effort cumulative Apple GPU time by PID from local IOKit registry data."""
    if sys.platform != "darwin":
        return None
    try:
        result = run(
            ["/usr/sbin/ioreg", "-r", "-c", "AGXDeviceUserClient", "-d", "0"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        output = result.stdout
        if result.returncode != 0 or not isinstance(output, str) or len(output.encode("utf-8")) > MAX_IOREG_OUTPUT_BYTES:
            return None
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None

    readings: dict[int, int] = {}
    blocks = re.split(r"(?m)^\+-o AGXDeviceUserClient\b", output)
    clients_found = False
    for block in blocks[1:]:
        creator = re.search(r'"IOUserClientCreator"\s*=\s*"pid\s+(\d+),', block)
        if creator is None:
            continue
        clients_found = True
        try:
            pid = int(creator.group(1))
        except (ValueError, OverflowError):
            continue
        if not (0 <= pid <= MAX_PID):
            continue
        counters = re.findall(r'"accumulatedGPUTime"\s*=\s*(\d+)', block)
        if not counters:
            return None
        gpu_time = sum(int(value) for value in counters)
        if gpu_time > 2**63 - 1:
            return None
        readings[pid] = min(2**63 - 1, readings.get(pid, 0) + gpu_time)
    return readings if clients_found and readings else None


@lru_cache(maxsize=512)
def _application_name_from_bundle(bundle_path: str) -> str | None:
    info_path = Path(bundle_path) / "Contents" / "Info.plist"
    try:
        if not info_path.is_file() or info_path.stat().st_size > MAX_APP_INFO_BYTES:
            return None
        with info_path.open("rb") as info_file:
            info = plistlib.load(info_file)
        for key in ("CFBundleDisplayName", "CFBundleName"):
            name = info.get(key) if isinstance(info, dict) else None
            if isinstance(name, str) and name.strip():
                return "".join(char for char in name if char.isprintable() and char not in "\r\n\t").strip()[:128] or None
    except (OSError, plistlib.InvalidFileException, ValueError, TypeError):
        return None
    return None


def _bundle_for_executable(executable: str | None) -> tuple[str, str] | None:
    if not isinstance(executable, str) or not executable:
        return None
    try:
        path = Path(executable)
        candidates = [parent for parent in path.parents if parent.suffix.lower() == ".app"]
        if not candidates:
            return None
        bundle_path = str(candidates[-1])
        display_name = _application_name_from_bundle(bundle_path) or Path(bundle_path).stem
        display_name = "".join(char for char in display_name if char.isprintable() and char not in "\r\n\t").strip()[:128]
        if not display_name:
            return None
        return (bundle_path, display_name)
    except (OSError, ValueError):
        return None


class ProcessManagerError(Exception):
    """Base exception for process manager operations."""


class ProcessNotFoundError(ProcessManagerError):
    """The requested process does not exist or has already exited."""


class ProcessAccessDeniedError(ProcessManagerError):
    """Permission denied when attempting to access or terminate the process."""


class ProcessSafetyError(ProcessManagerError):
    """Attempted to terminate a protected system process or OfficeKit itself."""


class ProcessManagerService:
    def __init__(
        self,
        *,
        process_iter_provider: Callable[..., Any] | None = None,
        process_lookup_provider: Callable[[int], Any] | None = None,
        gpu_usage_provider: Callable[[], dict[int, int] | None] | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ):
        self._process_iter = process_iter_provider or psutil.process_iter
        self._process_lookup = process_lookup_provider or psutil.Process
        self._gpu_usage_provider = gpu_usage_provider or macos_gpu_process_times
        self._clock = monotonic_clock
        self._wall_clock = wall_clock
        self._lock = threading.Lock()
        self._cached_processes: list[dict[str, Any]] | None = None
        self._cache_timestamp: float = 0.0
        self._gpu_previous: tuple[float, dict[int, int]] | None = None

    def list_processes(
        self,
        *,
        limit: int = DEFAULT_PROCESS_LIMIT,
        sort_by: str = "cpu",
    ) -> dict[str, Any]:
        """Return a bounded snapshot of running processes sorted by resource consumption."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= MAX_PROCESS_LIMIT):
            raise ValueError(f"Limit must be an integer between 1 and {MAX_PROCESS_LIMIT}.")
        if sort_by not in ("cpu", "memory", "gpu"):
            raise ValueError("sort_by must be 'cpu', 'memory' or 'gpu'.")

        now = self._clock()
        with self._lock:
            if self._cached_processes is not None and (now - self._cache_timestamp) < CACHE_TTL_SECONDS:
                raw_list = list(self._cached_processes)
            else:
                raw_list = self._collect_processes()
                self._cached_processes = raw_list
                self._cache_timestamp = now

        if sort_by == "memory":
            sorted_procs = sorted(raw_list, key=lambda p: (p["memory_bytes"], p["cpu_percent"]), reverse=True)
        elif sort_by == "gpu":
            sorted_procs = sorted(raw_list, key=lambda p: (p["gpu_percent"] if p["gpu_percent"] is not None else -1, p["cpu_percent"], p["memory_bytes"]), reverse=True)
        else:
            sorted_procs = sorted(raw_list, key=lambda p: (p["cpu_percent"], p["memory_bytes"]), reverse=True)
        applications = self._aggregate_applications(raw_list)
        if sort_by == "memory":
            applications.sort(key=lambda item: (item["memory_bytes"], item["cpu_percent"]), reverse=True)
        elif sort_by == "gpu":
            applications.sort(key=lambda item: (item["gpu_percent"] if item["gpu_percent"] is not None else -1, item["cpu_percent"], item["memory_bytes"]), reverse=True)
        else:
            applications.sort(key=lambda item: (item["cpu_percent"], item["memory_bytes"]), reverse=True)

        return {
            "processes": [self._public_process(item) for item in sorted_procs[:limit]],
            "applications": applications[:limit],
            "total_applications": len(applications),
            "total_count": len(raw_list),
            "captured_at": datetime.fromtimestamp(self._wall_clock(), timezone.utc).isoformat(),
        }

    def terminate_process(self, pid: int, *, force: bool = False) -> dict[str, Any]:
        """Safely terminate a user-space process with strict bounds and protection."""
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise ValueError("PID must be a valid integer.")
        if pid < MIN_KILLABLE_PID or pid > MAX_PID:
            raise ProcessSafetyError(f"PID {pid} is outside permitted termination bounds.")

        if pid in self._protected_pids():
            raise ProcessSafetyError("Terminating OfficeKit, its parent application or its helpers is not permitted.")

        try:
            proc = self._process_lookup(pid)
        except psutil.NoSuchProcess:
            raise ProcessNotFoundError(f"Process {pid} was not found or has already terminated.")
        except psutil.AccessDenied:
            raise ProcessAccessDeniedError(f"Permission denied: cannot access process {pid}.")

        try:
            name = proc.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            name = f"Process-{pid}"

        clean_name = self._sanitize_name(name)

        try:
            if force:
                proc.kill()
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                except psutil.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait(timeout=0.5)
                    except Exception:
                        pass
        except psutil.NoSuchProcess:
            raise ProcessNotFoundError(f"Process {clean_name} (PID {pid}) has already exited.")
        except psutil.AccessDenied:
            raise ProcessAccessDeniedError(f"Permission denied: cannot terminate {clean_name} (PID {pid}).")

        # Invalidate cache so subsequent process list is up to date
        with self._lock:
            self._cached_processes = None

        return {
            "success": True,
            "pid": pid,
            "name": clean_name,
            "message": f"Successfully terminated {clean_name} (PID {pid}).",
        }

    @staticmethod
    def _protected_pids() -> frozenset[int]:
        """OfficeKit itself, its ancestors (the launching app) and its own helper children are never offered Quit."""
        protected = {os.getpid(), os.getppid()}
        try:
            me = psutil.Process(os.getpid())
            protected.update(parent.pid for parent in me.parents())
            protected.update(child.pid for child in me.children(recursive=True))
        except (psutil.Error, OSError):
            pass
        return frozenset(protected)

    def _collect_processes(self) -> list[dict[str, Any]]:
        current_uid = os.getuid()
        protected = self._protected_pids()
        results: list[dict[str, Any]] = []

        gpu_percentages = self._sample_gpu_percentages(self._clock())
        attrs = ["pid", "name", "cpu_percent", "memory_info", "memory_percent", "status", "uids", "exe", "ppid"]
        process_infos: list[dict[str, Any]] = []
        for p in self._process_iter(attrs=attrs):
            try:
                info = dict(p.info)
                pid = info.get("pid")
                if not isinstance(pid, int) or isinstance(pid, bool) or pid < 0 or pid > MAX_PID:
                    continue
                process_infos.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        infos_by_pid = {info["pid"]: info for info in process_infos}
        for info in process_infos:
            try:
                pid = info["pid"]

                raw_name = info.get("name") or "unknown"
                name = self._sanitize_name(str(raw_name))
                # Only the signed-in user's own non-root processes can be offered Quit; system daemons are never listed as killable.
                uids = info.get("uids")
                owner = getattr(uids, "real", None)

                raw_cpu = info.get("cpu_percent")
                cpu = float(raw_cpu) if isinstance(raw_cpu, (int, float)) and math.isfinite(raw_cpu) and raw_cpu >= 0 else 0.0
                cpu = round(min(cpu, 10000.0), 1)

                mem_info = info.get("memory_info")
                rss = getattr(mem_info, "rss", 0) if mem_info else 0
                if not isinstance(rss, int) or rss < 0:
                    rss = 0

                raw_mem_pct = info.get("memory_percent")
                mem_pct = float(raw_mem_pct) if isinstance(raw_mem_pct, (int, float)) and math.isfinite(raw_mem_pct) and 0 <= raw_mem_pct <= 100 else 0.0
                mem_pct = round(mem_pct, 1)

                status = str(info.get("status") or "unknown")[:32]
                is_killable = (pid >= MIN_KILLABLE_PID and pid not in protected and owner == current_uid
                               and current_uid != 0 and not name.lower().startswith("officekit"))

                app_name, app_bundle_path = self._application_for_process(info, infos_by_pid, name)
                gpu_percent = None
                if gpu_percentages is not None:
                    tracked, percentages = gpu_percentages
                    gpu_percent = percentages.get(pid, 0.0 if pid not in tracked else None)
                executable = info.get("exe")
                is_primary_app_process = False
                if app_bundle_path and isinstance(executable, str):
                    try:
                        is_primary_app_process = Path(executable).parent == Path(app_bundle_path) / "Contents" / "MacOS"
                    except (OSError, ValueError):
                        pass

                results.append({
                    "pid": pid,
                    "name": name,
                    "app_name": app_name,
                    "cpu_percent": cpu,
                    "gpu_percent": gpu_percent,
                    "memory_bytes": rss,
                    "memory_mb": round(rss / (1024 * 1024), 1),
                    "memory_percent": mem_pct,
                    "status": status,
                    "is_killable": is_killable,
                    "_app_bundle_path": app_bundle_path,
                    "_is_primary_app_process": is_primary_app_process,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        return results

    def _sample_gpu_percentages(self, now: float) -> tuple[set[int], dict[int, float | None]] | None:
        try:
            current = self._gpu_usage_provider()
        except Exception:
            current = None
        if not isinstance(current, dict):
            self._gpu_previous = None
            return None

        sanitized: dict[int, int] = {}
        for pid, gpu_time in current.items():
            if (isinstance(pid, int) and not isinstance(pid, bool) and 0 <= pid <= MAX_PID
                    and isinstance(gpu_time, int) and not isinstance(gpu_time, bool) and 0 <= gpu_time <= 2**63 - 1):
                sanitized[pid] = gpu_time

        previous = self._gpu_previous
        self._gpu_previous = (now, sanitized)
        if previous is None:
            return set(sanitized), {pid: None for pid in sanitized}
        previous_at, previous_times = previous
        elapsed_ns = (now - previous_at) * 1_000_000_000
        if not math.isfinite(elapsed_ns) or elapsed_ns <= 0:
            return set(sanitized), {pid: None for pid in sanitized}

        percentages: dict[int, float | None] = {}
        for pid, total in sanitized.items():
            earlier = previous_times.get(pid)
            if earlier is None or total < earlier:
                percentages[pid] = None
            else:
                percentages[pid] = round(min(100.0, (total - earlier) / elapsed_ns * 100), 1)
        return set(sanitized), percentages

    @staticmethod
    def _application_for_process(info: dict[str, Any], infos_by_pid: dict[int, dict[str, Any]], fallback: str) -> tuple[str, str | None]:
        pid = info.get("pid")
        visited: set[int] = set()
        for _ in range(9):
            if not isinstance(pid, int) or pid in visited:
                break
            visited.add(pid)
            candidate = infos_by_pid.get(pid)
            if candidate is None:
                break
            bundle = _bundle_for_executable(candidate.get("exe"))
            if bundle is not None:
                return bundle[1], bundle[0]
            pid = candidate.get("ppid")
        return fallback, None

    @staticmethod
    def _aggregate_applications(processes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for process in processes:
            name = process["app_name"]
            bundle_path = process.get("_app_bundle_path")
            group_key = bundle_path.casefold() if isinstance(bundle_path, str) else f"process:{process['pid']}"
            groups.setdefault(group_key, []).append(process)

        applications: list[dict[str, Any]] = []
        for members in groups.values():
            members.sort(key=lambda item: (item["_is_primary_app_process"], item["cpu_percent"], item["memory_bytes"]), reverse=True)
            primary = members[0]
            memory_bytes = sum(item["memory_bytes"] for item in members)
            gpu_values = [item["gpu_percent"] for item in members]
            gpu_percent = None if any(value is None for value in gpu_values) else round(min(100.0, sum(gpu_values)), 1)
            raw_memory_percent = sum(item["memory_percent"] for item in members)
            process_names = list(dict.fromkeys(item["name"] for item in members))[:4]
            applications.append({
                "name": primary["app_name"],
                "pid": primary["pid"],
                "process_count": len(members),
                "process_names": process_names,
                "cpu_percent": round(sum(item["cpu_percent"] for item in members), 1),
                "gpu_percent": gpu_percent,
                "memory_bytes": memory_bytes,
                "memory_mb": round(memory_bytes / (1024 * 1024), 1),
                "memory_percent": round(min(100.0, raw_memory_percent), 1),
                "status": "running" if any(item["status"] == "running" for item in members) else primary["status"],
                "is_killable": primary["is_killable"],
            })
        return applications

    @staticmethod
    def _public_process(process: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in process.items() if not key.startswith("_")}

    @staticmethod
    def _sanitize_name(name: str) -> str:
        clean = "".join(c for c in name if c.isprintable() and c not in "\r\n\t")
        return clean.strip()[:128] or "unknown"
