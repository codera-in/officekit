"""Redacted macOS system-information summary for sharing with support."""

from __future__ import annotations

import platform
import re
from collections.abc import Callable
from typing import Any

import psutil


MAX_MEMORY_BYTES = 2**70
_MACOS_VERSION = re.compile(r"^\d{1,3}(?:\.\d{1,3}){0,2}$")
_ARCHITECTURE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


class SystemInfoUnsupportedError(RuntimeError):
    """No verified system-information adapter exists for this platform."""


class SystemInfoUnavailableError(RuntimeError):
    """A required local system-information field could not be read safely."""


class SystemInfoService:
    def __init__(
        self,
        *,
        os_provider: Callable[[], str] = platform.system,
        version_provider: Callable[[], str] = lambda: platform.mac_ver()[0],
        architecture_provider: Callable[[], str] = platform.machine,
        logical_cpu_provider: Callable[[], int | None] = lambda: psutil.cpu_count(logical=True),
        physical_cpu_provider: Callable[[], int | None] = lambda: psutil.cpu_count(logical=False),
        memory_provider: Callable[[], Any] = psutil.virtual_memory,
    ):
        self._os = os_provider
        self._version = version_provider
        self._architecture = architecture_provider
        self._logical_cpus = logical_cpu_provider
        self._physical_cpus = physical_cpu_provider
        self._memory = memory_provider

    def snapshot(self) -> dict:
        try:
            if self._os() != "Darwin":
                raise SystemInfoUnsupportedError("System information is not supported on this platform.")
            version = self._version()
            architecture = self._architecture()
            logical_cpus = self._logical_cpus()
            memory = self._memory()
        except SystemInfoUnsupportedError:
            raise
        except Exception as error:
            raise SystemInfoUnavailableError("System information is unavailable.") from error

        if not isinstance(version, str) or not _MACOS_VERSION.fullmatch(version):
            raise SystemInfoUnavailableError("System information is unavailable.")
        if not isinstance(architecture, str) or not _ARCHITECTURE.fullmatch(architecture):
            raise SystemInfoUnavailableError("System information is unavailable.")
        if not self._valid_cpu_count(logical_cpus):
            raise SystemInfoUnavailableError("System information is unavailable.")
        total_memory = getattr(memory, "total", None)
        if (
            isinstance(total_memory, bool)
            or not isinstance(total_memory, int)
            or not 0 < total_memory <= MAX_MEMORY_BYTES
        ):
            raise SystemInfoUnavailableError("System information is unavailable.")

        physical_cpus = self._safe_physical_cpu_count(logical_cpus)
        gib = round(total_memory / (1024**3), 1)
        cpu_report = (
            f"CPU cores: {physical_cpus} physical, {logical_cpus} logical"
            if physical_cpus is not None
            else f"CPU cores: {logical_cpus} logical"
        )
        return {
            "os_name": "macOS",
            "os_version": version,
            "architecture": architecture,
            "logical_cpu_count": logical_cpus,
            "physical_cpu_count": physical_cpus,
            "memory_total_bytes": total_memory,
            "memory_total_gb": gib,
            "privacy_notice": (
                "Contains macOS version, architecture, CPU core counts and memory capacity only. "
                "Device identifiers and host/account names are excluded."
            ),
            "report_text": (
                f"Operating system: macOS {version}\n"
                f"Architecture: {architecture}\n"
                f"{cpu_report}\n"
                f"Memory: {gib:g} GB"
            ),
        }

    def _safe_physical_cpu_count(self, logical_cpus: int) -> int | None:
        try:
            value = self._physical_cpus()
        except Exception:
            return None
        if self._valid_cpu_count(value) and value <= logical_cpus:
            return value
        return None

    @staticmethod
    def _valid_cpu_count(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 1024
