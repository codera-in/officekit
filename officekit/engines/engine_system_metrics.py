"""Process-local bounded menu-bar metrics; no telemetry or background sampler."""

from __future__ import annotations

import math
import os
import plistlib
import re
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import psutil

from officekit.engines.engine_system_resources import SystemResourceService

DATA_VOLUME_PATH = "/System/Volumes/Data"
VM_STAT_PATH = "/usr/bin/vm_stat"
SYSCTL_PATH = "/usr/sbin/sysctl"
PRESSURE_SYSCTL_KEY = "kern.memorystatus_vm_pressure_level"
PRESSURE_LEVELS = {1: "normal", 2: "warning", 4: "critical"}
_VM_STAT_PAGE_SIZE = re.compile(r"page size of (\d+) bytes")
_CPU_FIELDS = ("user", "nice", "system", "idle")
IOREG_PATH = "/usr/sbin/ioreg"
PMSET_PATH = "/usr/bin/pmset"


def data_volume_path(isdir=os.path.isdir) -> str:
    """The macOS user-data volume; "/" is the sealed system volume and reads almost empty."""
    return DATA_VOLUME_PATH if isdir(DATA_VOLUME_PATH) else "/"


def parse_vm_stat(output: str) -> tuple[int, dict[str, int]]:
    """Page size and integer page counts from vm_stat output. Raises ValueError without a page size."""
    match = _VM_STAT_PAGE_SIZE.search(output)
    if match is None:
        raise ValueError("vm_stat page size is missing.")
    pages: dict[str, int] = {}
    for line in output.splitlines():
        name, separator, value = line.partition(":")
        value = value.strip().rstrip(".")
        if separator and re.fullmatch(r"-?\d+", value):
            pages[name.strip()] = int(value)
    return int(match.group(1)), pages


def _run_vm_stat(run) -> str:
    return run([VM_STAT_PATH], capture_output=True, text=True, timeout=2, check=True).stdout


def macos_memory_used_percent(run=subprocess.run, total_bytes=None) -> float | None:
    """Memory in use the way macOS monitors report it: everything except free and file-backed (cache) pages."""
    try:
        total = total_bytes if total_bytes is not None else psutil.virtual_memory().total
        page_size, pages = parse_vm_stat(_run_vm_stat(run))
        total_pages = total // page_size
        used = total_pages - pages["Pages free"] - pages["File-backed pages"]
        return max(0.0, min(100.0, round(used / total_pages * 100.0, 1)))
    except Exception:
        return None


def macos_memory_breakdown(run=subprocess.run, total_bytes=None) -> dict | None:
    """Memory split the way Activity Monitor shows it: App (anonymous minus purgeable), Wired, Compressed; Free is the rest."""
    try:
        total = total_bytes if total_bytes is not None else psutil.virtual_memory().total
        page_size, pages = parse_vm_stat(_run_vm_stat(run))
        app = max(0, pages["Anonymous pages"] - pages.get("Pages purgeable", 0)) * page_size
        wired = pages["Pages wired down"] * page_size
        compressed = pages["Pages occupied by compressor"] * page_size
        used = min(total, app + wired + compressed)
        return {
            "total_bytes": total,
            "used_bytes": used,
            "app_bytes": min(app, used),
            "wired_bytes": min(wired, used),
            "compressed_bytes": min(compressed, used),
            "free_bytes": max(0, total - used),
        }
    except Exception:
        return None


def macos_cpu_topology(run=subprocess.run) -> dict | None:
    """Chip name and the performance / efficiency core counts; the counts are None on Macs without core levels."""
    def read(key: str) -> str:
        return run([SYSCTL_PATH, "-n", key], capture_output=True, text=True, timeout=2, check=True).stdout.strip()

    def count(key: str) -> int | None:
        try:
            value = int(read(key))
        except Exception:
            return None
        return value if 0 < value <= 256 else None

    try:
        model = read("machdep.cpu.brand_string")
    except Exception:
        return None
    if not model or len(model) > 64 or not model.isprintable():
        return None
    return {"model": model, "performance_cores": count("hw.perflevel0.logicalcpu"),
            "efficiency_cores": count("hw.perflevel1.logicalcpu")}


def macos_memory_pressure(run=subprocess.run) -> str | None:
    """normal, warning or critical from the kernel's memory pressure level; None when unreadable."""
    try:
        output = run([SYSCTL_PATH, "-n", PRESSURE_SYSCTL_KEY], capture_output=True, text=True, timeout=2, check=True).stdout
        return PRESSURE_LEVELS.get(int(output.strip()))
    except Exception:
        return None


def cpu_split_percent(deltas: dict[str, float]) -> dict | None:
    """User, system and idle shares of the CPU time elapsed between two samples; None when no time passed."""
    total = sum(max(0.0, float(deltas.get(name, 0.0))) for name in _CPU_FIELDS)
    if not math.isfinite(total) or total <= 0:
        return None

    def share(names):
        return round(sum(max(0.0, float(deltas.get(name, 0.0))) for name in names) / total * 100.0, 1)

    return {
        "user_percent": share(("user", "nice")),
        "system_percent": share(("system",)),
        "idle_percent": share(("idle",)),
    }


def _ioreg_records(class_name: str, run=subprocess.run) -> list[dict] | None:
    """Read a fixed IOKit class as a plist; never return registry output to the API."""
    if sys.platform != "darwin":
        return None
    try:
        result = run([IOREG_PATH, "-r", "-c", class_name, "-a"], capture_output=True, timeout=2, check=True)
        records = plistlib.loads(result.stdout)
        return records if isinstance(records, list) and records and isinstance(records[0], dict) else None
    except Exception:
        return None


def _safe_metric_percent(value) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 100:
        return None
    return round(float(value), 1)


def macos_gpu_metrics(run=subprocess.run) -> dict | None:
    """Best-effort live GPU percentages from the local IOAccelerator registry."""
    records = _ioreg_records("IOAccelerator", run)
    if not records:
        return None
    for record in records:
        stats = record.get("PerformanceStatistics")
        if not isinstance(stats, dict):
            continue
        values = {
            "utilization_percent": _safe_metric_percent(stats.get("Device Utilization %")),
            "renderer_percent": _safe_metric_percent(stats.get("Renderer Utilization %")),
            "tiler_percent": _safe_metric_percent(stats.get("Tiler Utilization %")),
        }
        if any(value is not None for value in values.values()):
            return values
    return None


def macos_gpu_info(run=subprocess.run) -> dict | None:
    """GPU model and core count from the accelerator's registry entry; read once because they never change."""
    if sys.platform != "darwin":
        return None
    try:
        text = run([IOREG_PATH, "-r", "-c", "AGXAccelerator", "-d1"], capture_output=True, text=True, timeout=2, check=True).stdout
    except Exception:
        return None
    model = re.search(r'"model"\s*=\s*"([^"\n]{1,48})"', text)
    cores = re.search(r'"gpu-core-count"\s*=\s*(\d{1,3})\b', text)
    info = {"model": model.group(1) if model and model.group(1).isprintable() else None,
            "core_count": int(cores.group(1)) if cores and 1 <= int(cores.group(1)) <= 256 else None}
    return info if info["model"] or info["core_count"] else None


def macos_bluetooth_batteries(run=subprocess.run) -> list[dict] | None:
    """Battery levels of connected Bluetooth accessories. Names stay in memory only and are never logged."""
    if sys.platform != "darwin":
        return None
    try:
        result = run([IOREG_PATH, "-r", "-k", "BatteryPercent", "-a"], capture_output=True, timeout=2, check=True)
        records = plistlib.loads(result.stdout) if result.stdout.strip() else []
    except Exception:
        return None
    devices = []
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        name = record.get("Product") or record.get("DeviceName")
        level = record.get("BatteryPercent")
        if not isinstance(name, str) or not name.strip() or not name.isprintable():
            continue
        if type(level) is not int or not 0 <= level <= 100:
            continue
        devices.append({"name": name.strip()[:40], "percent": level})
        if len(devices) >= 8:
            break
    return devices or None


def _bounded_number(value, low: float, high: float, digits: int = 1) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        return None
    return round(float(value), digits)


def _battery_integer(record: dict, keys: tuple[str, ...], nested: dict) -> int | None:
    for source in (record, nested):
        for key in keys:
            value = source.get(key)
            if type(value) is int and value >= 0:
                return value
    return None


def macos_battery_metrics(run=subprocess.run) -> dict | None:
    """Read local charge and health data when macOS exposes an internal battery."""
    records = _ioreg_records("AppleSmartBattery", run)
    if not records:
        return None
    record = records[0]
    nested = record.get("BatteryData")
    nested = nested if isinstance(nested, dict) else {}
    try:
        power = run([PMSET_PATH, "-g", "batt"], capture_output=True, text=True, timeout=2, check=True).stdout
    except Exception:
        power = ""
    if "no batteries available" in power.lower():
        return None
    match = re.search(r"\b(\d{1,3})%", power)
    percent = int(match.group(1)) if match and int(match.group(1)) <= 100 else None
    charging = record.get("IsCharging") if type(record.get("IsCharging")) is bool else None
    power_lower = power.lower()
    source = "ac" if "ac power" in power_lower else "battery" if "battery power" in power_lower else None
    if charging is None and power_lower:
        if re.search(r"\bdischarging\b|\bnot charging\b", power_lower):
            charging = False
        elif re.search(r"\bcharging\b", power_lower):
            charging = True
    if percent is None and source is None:
        return None

    full = _battery_integer(record, ("AppleRawMaxCapacity", "NominalChargeCapacity", "FullChargeCapacity", "MaxCapacity"), nested)
    designed = _battery_integer(record, ("DesignCapacity",), nested)
    cycles = _battery_integer(record, ("CycleCount",), {})
    health = None
    if full is not None and designed is not None and designed > 0:
        health = min(100.0, round(full / designed * 100, 1))
    condition = record.get("BatteryHealth") or record.get("Condition")
    if not isinstance(condition, str) or not condition or len(condition) > 40:
        condition = None
    elif condition.lower() in {"good", "normal"}:
        condition = "Normal"
    elif condition.lower() in {"replace soon", "service recommended", "fair"}:
        condition = "Service recommended"
    elif condition.lower() in {"replace now", "poor"}:
        condition = "Service required"
    remaining = re.search(r"\b(\d+):(\d{2})\s+remaining\b", power, re.IGNORECASE)
    seconds_remaining = int(remaining.group(1)) * 3600 + int(remaining.group(2)) * 60 if remaining else None
    state = "charging" if charging is True else "discharging" if charging is False and source == "battery" else "charged" if "charged" in power_lower else "discharging" if source == "battery" else "unknown"
    adapter = record.get("AdapterDetails")
    millivolts = _bounded_number(record.get("Voltage"), 1, 40_000, 0)
    amperage = record.get("Amperage")
    if type(amperage) is int and amperage >= 2**63:
        amperage -= 2**64
    milliamps = _bounded_number(amperage, -20_000, 20_000, 0)
    temperature = record.get("Temperature")
    return {
        "adapter_watts": _bounded_number(adapter.get("Watts") if isinstance(adapter, dict) else None, 1, 500, 0),
        "voltage_v": round(millivolts / 1000, 2) if millivolts is not None else None,
        "current_a": round(milliamps / 1000, 2) if milliamps is not None else None,
        "power_w": round(millivolts * milliamps / 1_000_000, 1) if millivolts is not None and milliamps is not None else None,
        "temperature_c": _bounded_number(temperature / 100 if type(temperature) is int else None, -20, 100),
        "percent": percent,
        "power_source": source,
        "state": state,
        "time_remaining_seconds": seconds_remaining,
        "cycle_count": cycles,
        "designed_capacity_mah": designed,
        "full_charge_capacity_mah": full,
        "health_percent": health,
        "condition": condition,
    }


def system_battery_metrics(run=subprocess.run) -> dict | None:
    """Provide charge data on supported platforms and extra health data on macOS."""
    if sys.platform == "darwin":
        return macos_battery_metrics(run)
    try:
        battery = psutil.sensors_battery()
    except Exception:
        return None
    if battery is None or not math.isfinite(battery.percent) or not 0 <= battery.percent <= 100:
        return None
    plugged = battery.power_plugged if type(battery.power_plugged) is bool else None
    charging = bool(plugged and battery.percent < 100) if plugged is not None else None
    seconds = battery.secsleft if type(battery.secsleft) is int and battery.secsleft >= 0 else None
    return {
        "percent": round(float(battery.percent), 1),
        "power_source": "ac" if plugged else "battery" if plugged is False else None,
        "state": "charging" if charging else "charged" if plugged and battery.percent >= 100 else "discharging" if plugged is False else "unknown",
        "time_remaining_seconds": seconds,
        "cycle_count": None,
        "designed_capacity_mah": None,
        "full_charge_capacity_mah": None,
        "health_percent": None,
        "condition": None,
    }


def system_sensor_metrics() -> list[dict] | None:
    """Return bounded temperature readings where the host OS exposes them to psutil."""
    try:
        groups = psutil.sensors_temperatures()
    except Exception:
        return None
    result = []
    if not isinstance(groups, dict):
        return None
    for sensor_name, entries in groups.items():
        if not isinstance(sensor_name, str) or not isinstance(entries, (list, tuple)):
            continue
        for entry in entries:
            current = getattr(entry, "current", None)
            if type(current) not in (int, float) or not math.isfinite(current) or not -20 <= current <= 150:
                continue
            label = getattr(entry, "label", None)
            high = getattr(entry, "high", None)
            result.append({
                "name": (label if isinstance(label, str) and label.strip() else sensor_name)[:60],
                "current_c": round(float(current), 1),
                "high_c": round(float(high), 1) if type(high) in (int, float) and math.isfinite(high) and -20 <= high <= 150 else None,
            })
            if len(result) >= 16:
                return result
    return result or None


class SystemMetricsService:
    CACHE_SECONDS = 1.0
    MAX_INTERFACES = 1024
    MAX_COUNTER = 2**64 - 1

    def __init__(self, *, resource_service=None, disk_provider=None, network_provider=None,
                 interface_provider=None, monotonic_clock=time.monotonic, wall_clock=time.time,
                 memory_percent_provider=None, disk_path="/", memory_breakdown_provider=None,
                 pressure_provider=None, swap_provider=None, cpu_times_provider=None,
                 load_provider=None, boot_time_provider=None, disk_io_provider=None,
                 cpu_cores_provider=None, gpu_provider=None, battery_provider=None, sensors_provider=None,
                 topology_provider=None, gpu_info_provider=None, bluetooth_provider=None,
                 volumes_provider=None, addresses_provider=None):
        self._resources = resource_service or SystemResourceService()
        self._memory_percent = memory_percent_provider
        self._disk_path = disk_path
        self._disk = disk_provider or psutil.disk_usage
        self._network = network_provider or psutil.net_io_counters
        self._interfaces = interface_provider or psutil.net_if_stats
        self._memory_breakdown = memory_breakdown_provider or macos_memory_breakdown
        self._pressure = pressure_provider or macos_memory_pressure
        self._swap = swap_provider or psutil.swap_memory
        self._cpu_times = cpu_times_provider or psutil.cpu_times
        self._load = load_provider or os.getloadavg
        self._boot_time = boot_time_provider or psutil.boot_time
        self._disk_io = disk_io_provider or psutil.disk_io_counters
        self._cpu_cores = cpu_cores_provider or (lambda: psutil.cpu_percent(interval=None, percpu=True))
        self._gpu = gpu_provider or macos_gpu_metrics
        self._battery = battery_provider or system_battery_metrics
        self._sensors = sensors_provider or system_sensor_metrics
        self._topology_provider = topology_provider or (macos_cpu_topology if sys.platform == "darwin" else (lambda: None))
        self._topology = None
        self._topology_read = False
        self._gpu_info_provider = gpu_info_provider or macos_gpu_info
        self._gpu_info = None
        self._gpu_info_read = False
        self._bluetooth = bluetooth_provider or macos_bluetooth_batteries
        self._volumes = volumes_provider or self._mounted_volumes
        self._addresses = addresses_provider or psutil.net_if_addrs
        self._clock = monotonic_clock
        self._wall_clock = wall_clock
        self._lock = threading.Lock()
        self._cached = None
        self._sampled_at = None
        self._previous_network = None
        self._previous_cpu = None
        self._previous_disk = None
        self._last_disk_totals = None
        self._last_network_read = None

    @staticmethod
    def _percent(value):
        return float(value) if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 100 else None

    def snapshot(self):
        with self._lock:
            now = self._clock()
            if type(now) not in (int, float) or not math.isfinite(now):
                raise ValueError("Metrics clock is unavailable.")
            if self._cached is not None and 0 <= now - self._sampled_at < self.CACHE_SECONDS:
                return {**self._cached, "reasons": dict(self._cached["reasons"]), "sample_age_ms": round((now - self._sampled_at) * 1000)}
            result = {"cpu_percent": None, "memory_percent": None, "storage_percent": None,
                      "volume_label": "Startup disk", "upload_bytes_per_second": None,
                      "download_bytes_per_second": None,
                      "captured_at": datetime.fromtimestamp(self._wall_clock(), timezone.utc).isoformat(),
                      "sample_age_ms": 0, "reasons": {},
                      "memory": None, "memory_pressure": None, "swap": None, "cpu_breakdown": None,
                      "load_average": None, "uptime_seconds": None, "disk": None,
                      "cpu_cores_percent": None, "gpu": None, "battery": None, "sensors": None,
                      "cpu_topology": None, "network": None, "bluetooth": None}
            try:
                resource = self._resources.snapshot()
                for field in ("cpu_percent", "memory_percent"):
                    result[field] = self._percent(resource.get(field))
            except Exception:
                pass
            if self._memory_percent is not None:
                override = self._percent(self._memory_percent())
                if override is not None:
                    result["memory_percent"] = override
            for field in ("cpu_percent", "memory_percent"):
                if result[field] is None:
                    result["reasons"][field] = "Resource information unavailable."
            try:
                usage = self._disk(self._disk_path)
                result["storage_percent"] = self._percent(usage.percent)
                result["disk"] = {"used_bytes": self._byte_count(getattr(usage, "used", None)),
                                  "total_bytes": self._byte_count(getattr(usage, "total", None)),
                                  "read_bytes_per_second": None, "write_bytes_per_second": None}
            except Exception:
                pass
            if result["storage_percent"] is None:
                result["reasons"]["storage_percent"] = "Storage information unavailable."
            self._read_network(result, now)
            self._read_details(result, now)
            result["cpu_cores_percent"] = self._optional(self._read_cpu_cores)
            result["gpu"] = self._optional(self._gpu)
            if not self._gpu_info_read:
                self._gpu_info = self._optional(self._gpu_info_provider)
                self._gpu_info_read = True
            if self._gpu_info is not None:
                result["gpu"] = {**(result["gpu"] or {}), **self._gpu_info}
            result["network"] = self._optional(self._network_details)
            result["bluetooth"] = self._optional(self._bluetooth)
            result["battery"] = self._optional(self._battery)
            result["sensors"] = self._optional(self._sensors)
            if not self._topology_read:
                # The chip never changes while the app runs, so read it once.
                self._topology = self._optional(self._topology_provider)
                self._topology_read = True
            result["cpu_topology"] = self._topology
            self._cached = result
            self._sampled_at = now
            return {**result, "reasons": dict(result["reasons"])}

    def _read_cpu_cores(self):
        values = self._cpu_cores()
        if not isinstance(values, (list, tuple)) or not values or len(values) > 1024:
            return None
        parsed = [_safe_metric_percent(value) for value in values]
        return parsed if all(value is not None for value in parsed) else None

    @staticmethod
    def _byte_count(value):
        return value if type(value) is int and value >= 0 else None

    def _read_details(self, result, now):
        """Memory, swap, CPU split, load, uptime and disk throughput. Each part is independently optional."""
        result["memory"] = self._optional(self._memory_breakdown)
        result["memory_pressure"] = self._optional(self._pressure)
        result["swap"] = self._optional(self._swap_summary)
        result["cpu_breakdown"] = self._optional(lambda: self._cpu_split(now))
        if result["cpu_breakdown"] is not None:
            # The 100 ms probe can land in a quiet gap and read 0% while System + User over the whole interval says 23%.
            # The split covers the same interval as the rows beside it, so the headline follows it.
            result["cpu_percent"] = round(100.0 - result["cpu_breakdown"]["idle_percent"], 1)
        result["load_average"] = self._optional(self._load_average)
        result["uptime_seconds"] = self._optional(self._uptime)
        if result["disk"] is not None:
            rates = self._optional(lambda: self._disk_rates(now))
            if rates is not None:
                result["disk"]["read_bytes_per_second"], result["disk"]["write_bytes_per_second"] = rates
            totals = self._optional(self._disk_totals)
            if totals is not None:
                result["disk"]["read_total_bytes"], result["disk"]["write_total_bytes"] = totals
            result["disk"]["volumes"] = self._optional(self._volumes)

    def _disk_totals(self):
        """Totals since start-up from the counters the rate calculation just read."""
        return self._last_disk_totals

    MAX_VOLUMES = 8

    def _mounted_volumes(self):
        """Used and total bytes per local volume. Mount points stay in memory and are shown by their folder name only."""
        volumes = []
        for partition in psutil.disk_partitions(all=False):
            mount = partition.mountpoint
            if not isinstance(mount, str) or not (mount == "/" or mount.startswith("/Volumes/") or sys.platform != "darwin"):
                continue
            usage = psutil.disk_usage(data_volume_path() if mount == "/" else mount)
            total, used = self._byte_count(usage.total), self._byte_count(usage.used)
            if not total or used is None:
                continue
            name = os.path.basename(mount.rstrip("/")) if mount != "/" else "Macintosh HD"
            volumes.append({"name": (name or mount)[:40], "used_bytes": used, "total_bytes": total})
            if len(volumes) >= self.MAX_VOLUMES:
                break
        return volumes or None

    def _network_details(self):
        """Active interface, its IPv4 address and the byte totals since start-up. The public address is never read here."""
        counters, interfaces = self._last_network_read or (None, None)
        if not isinstance(counters, dict) or not isinstance(interfaces, dict) or len(counters) > self.MAX_INTERFACES:
            return None
        active = [name for name in counters if isinstance(name, str) and not name.lower().startswith(("lo", "loopback"))
                  and getattr(interfaces.get(name), "isup", False) is True]
        physical = [name for name in active if name.lower().startswith(("en", "eth", "wl"))]
        names = physical or active
        if not names:
            return None
        sent = sum(counters[name].bytes_sent for name in names)
        received = sum(counters[name].bytes_recv for name in names)
        if any(type(value) is not int or not 0 <= value <= self.MAX_COUNTER for value in (sent, received)):
            return None
        addresses = self._addresses()
        primary, address = sorted(names)[0], None
        for name in sorted(names):
            for entry in addresses.get(name, []):
                if getattr(entry, "family", None) == socket.AF_INET and isinstance(entry.address, str) and len(entry.address) <= 15:
                    primary, address = name, entry.address
                    break
            if address:
                break
        return {"interface": primary[:16], "local_address": address, "sent_total_bytes": sent, "received_total_bytes": received}

    @staticmethod
    def _optional(read):
        try:
            return read()
        except Exception:
            return None

    def _swap_summary(self):
        swap = self._swap()
        percent = self._percent(swap.percent)
        total = self._byte_count(swap.total)
        if percent is None or total is None:
            return None
        return {"used_bytes": self._byte_count(swap.used), "total_bytes": total, "percent": percent}

    def _cpu_split(self, now):
        times = self._cpu_times()
        current = {name: float(getattr(times, name, 0.0)) for name in _CPU_FIELDS}
        previous, self._previous_cpu = self._previous_cpu, current
        if previous is None or any(current[name] < previous[name] for name in _CPU_FIELDS):
            return None
        return cpu_split_percent({name: current[name] - previous[name] for name in _CPU_FIELDS})

    def _load_average(self):
        values = self._load()
        if len(values) != 3 or not all(math.isfinite(value) and value >= 0 for value in values):
            return None
        return [round(float(value), 2) for value in values]

    def _uptime(self):
        seconds = self._wall_clock() - self._boot_time()
        return int(seconds) if math.isfinite(seconds) and seconds >= 0 else None

    def _disk_rates(self, now):
        counters = self._disk_io()
        read, written = counters.read_bytes, counters.write_bytes
        if type(read) is not int or type(written) is not int or read < 0 or written < 0:
            raise ValueError()
        self._last_disk_totals = (read, written)
        previous, self._previous_disk = self._previous_disk, (read, written, now)
        if previous is None:
            return None
        interval = now - previous[2]
        if interval <= 0 or read < previous[0] or written < previous[1]:
            return None
        return (read - previous[0]) / interval, (written - previous[1]) / interval

    def _read_network(self, result, now):
        try:
            counters = self._network(pernic=True)
            interfaces = self._interfaces()
            if not isinstance(counters, dict) or not isinstance(interfaces, dict) or len(counters) > self.MAX_INTERFACES or len(interfaces) > self.MAX_INTERFACES:
                raise ValueError()
            self._last_network_read = (counters, interfaces)
            active = [name for name in counters if isinstance(name, str) and not name.lower().startswith(("lo", "loopback")) and getattr(interfaces.get(name), "isup", False) is True]
            physical = [name for name in active if name.lower().startswith(("en", "eth", "wl"))]
            previous = self._previous_network
            previous_counters = previous[0] if previous else {}
            previous_chosen = previous[1] if previous else None
            previous_time = previous[2] if previous else None
            interval = now - previous_time if previous_time is not None else None

            valid = {}
            for name in physical or active:
                sent = getattr(counters[name], "bytes_sent", None)
                received = getattr(counters[name], "bytes_recv", None)
                if any(type(value) is not int or not 0 <= value <= self.MAX_COUNTER for value in (sent, received)):
                    raise ValueError()
                valid[name] = (sent, received)

            self._previous_network = (valid, previous_chosen, now)
            if previous is None:
                result["reasons"]["network"] = "Network rates warming up."
                self._previous_network = (valid, sorted(valid)[0], now)
                return
            if interval is None or interval <= 0:
                result["reasons"]["network"] = "Network counters reset; rates warming up."
                self._previous_network = (valid, previous_chosen if previous_chosen in valid else sorted(valid)[0], now)
                return

            deltas = {}
            reset = False
            new_interface = False
            for name, (sent, received) in valid.items():
                old = previous_counters.get(name)
                if old is None:
                    new_interface = True
                    continue
                if sent < old[0] or received < old[1]:
                    reset = True
                    continue
                delta_sent, delta_received = sent - old[0], received - old[1]
                if delta_sent or delta_received:
                    deltas[name] = (delta_sent, delta_received)

            # Sum physical adapters rather than switching to whichever adapter
            # had the largest delta in this sample. A route/interface change
            # otherwise alternates between a partial rate and a warming sample.
            # Tunnel interfaces stay excluded when physical adapters are up so
            # VPN traffic is not counted twice.
            if not valid:
                raise ValueError()
            chosen = previous_chosen if previous_chosen in valid else sorted(valid)[0]
            self._previous_network = (valid, chosen, now)
            if reset or new_interface:
                result["reasons"]["network"] = "Network counters reset or interface changed; rates warming up."
            else:
                result["upload_bytes_per_second"] = sum(delta[0] for delta in deltas.values()) / interval
                result["download_bytes_per_second"] = sum(delta[1] for delta in deltas.values()) / interval
        except Exception:
            self._previous_network = None
            result["reasons"]["network"] = "Network information unavailable."
