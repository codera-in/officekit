"""One-shot gateway versus internet latency check for the Network popover."""

from __future__ import annotations

import ipaddress
import json
import os
import platform
import re
import socket
import statistics
import struct
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import psutil


class NetworkHealthUnsupportedError(RuntimeError):
    """The host platform does not expose a supported default-route reader."""


class NetworkHealthError(RuntimeError):
    """The local route or probe service could not be read safely."""


class NetworkHealthService:
    INTERNET_TARGETS = ("1.1.1.1", "8.8.8.8")
    INTERNET_PORT = 443
    ROUTER_PORTS = (53, 80, 443)
    SAMPLE_COUNT = 3
    SAMPLE_INTERVAL_SECONDS = 1.0
    CONNECT_TIMEOUT_SECONDS = 0.75
    ROUTER_SLOW_MS = 40.0
    INTERNET_GAP_SLOW_MS = 100.0
    LOSS_THRESHOLD_PERCENT = 25.0
    SAFE_ENV = {"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    GATEWAY_LINE = re.compile(r"(?m)^\s*gateway:\s*(\S+)\s*$")
    INTERFACE_LINE = re.compile(r"(?m)^\s*interface:\s*(\S+)\s*$")

    def check(self) -> dict:
        route = self._default_route()
        if route is None:
            return self._result(
                "no_route", "No active network route", "Connect to Wi-Fi or Ethernet, then try again.",
                None, "unknown", 0, [], [],
            )
        gateway, interface, link_type = route
        router_port = self._discover_router_port(gateway)
        router_samples: list[float | None] = []
        internet_samples: list[float | None] = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            for index in range(self.SAMPLE_COUNT):
                if index:
                    time.sleep(self.SAMPLE_INTERVAL_SECONDS)
                router_future = pool.submit(self._probe, gateway, router_port) if router_port else None
                internet_future = pool.submit(self._probe_internet)
                router_samples.append(router_future.result() if router_future else None)
                internet_samples.append(internet_future.result())
        router_values = [value for value in router_samples if value is not None]
        internet_values = [value for value in internet_samples if value is not None]
        router_loss = self._loss_percent(router_samples) if router_port else None
        internet_loss = self._loss_percent(internet_samples)
        router_median = statistics.median(router_values) if router_values else None
        internet_median = statistics.median(internet_values) if internet_values else None

        if len(internet_samples) >= 2 and internet_samples[-1] is None and internet_samples[-2] is None:
            status, headline, detail = "offline", "Offline: internet is not responding", "The last two internet checks received no reply."
        elif len(internet_values) < 2:
            status, headline, detail = "incomplete", "Measurement incomplete", "Not enough internet replies to compare router and internet timing."
        elif router_median is None:
            status, headline, detail = (
                "router_unmeasured", "Router not measured", "The internet replied, but the gateway did not answer on the checked ports."
            )
        elif (router_loss or 0) >= self.LOSS_THRESHOLD_PERCENT or router_median > self.ROUTER_SLOW_MS:
            status, headline, detail = (
                "router_slow", "Slow: Wi-Fi or router", "The gateway response is slow or losing replies."
            )
        elif (internet_loss or 0) >= self.LOSS_THRESHOLD_PERCENT or (
            internet_median is not None and internet_median - router_median > self.INTERNET_GAP_SLOW_MS
        ):
            status, headline, detail = (
                "internet_slow", "Slow: ISP, not Wi-Fi", "The gateway is quick, while internet responses are slow or missing."
            )
        else:
            status, headline, detail = "healthy", "Connection looks healthy", "The gateway and internet responded normally."

        return self._result(
            status, headline, detail, interface, link_type, self.SAMPLE_COUNT,
            router_samples if router_port else [], internet_samples,
        )

    def _default_route(self) -> tuple[str, str, str] | None:
        system = platform.system()
        if system == "Darwin":
            gateway, interface = self._mac_default_route()
            if not gateway or not interface:
                return None
            link_type = self._mac_link_type(interface)
        elif system == "Linux":
            route = self._linux_default_route()
            if route is None:
                return None
            gateway, interface = route
            lowered = interface.casefold()
            link_type = "wifi" if lowered.startswith(("wl", "wlan", "wifi")) else "wired"
        elif system == "Windows":
            route = self._windows_default_route()
            if route is None:
                return None
            gateway, interface_address = route
            interface = self._windows_interface_name(interface_address)
            lowered = interface.casefold()
            link_type = "wifi" if any(token in lowered for token in ("wi-fi", "wifi", "wireless", "wlan")) else "wired"
        else:
            raise NetworkHealthUnsupportedError("Network health checks are not supported on this platform yet.")
        try:
            ipaddress.ip_address(gateway)
        except ValueError as error:
            raise NetworkHealthError("The active network route could not be read.") from error
        return gateway, interface[:64], link_type

    def _mac_default_route(self) -> tuple[str | None, str | None]:
        try:
            completed = subprocess.run(
                ["/sbin/route", "-n", "get", "default"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=1.0, check=False, env=self.SAFE_ENV,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise NetworkHealthError("The active network route could not be read.") from error
        if completed.returncode != 0:
            return None, None
        gateway = self.GATEWAY_LINE.search(completed.stdout)
        interface = self.INTERFACE_LINE.search(completed.stdout)
        return (gateway.group(1), interface.group(1)) if gateway and interface else (None, None)

    @staticmethod
    def _mac_link_type(interface: str) -> str:
        try:
            completed = subprocess.run(
                ["/usr/sbin/networksetup", "-listallhardwareports"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=1.0, check=False, env=NetworkHealthService.SAFE_ENV,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "wired"
        blocks = re.split(r"\n\s*\n", completed.stdout)
        for block in blocks:
            device = re.search(r"(?m)^Device:\s*(\S+)\s*$", block)
            label = re.search(r"(?m)^Hardware Port:\s*(.+?)\s*$", block)
            if device and label and device.group(1) == interface:
                return "wifi" if "wi-fi" in label.group(1).casefold() or "airport" in label.group(1).casefold() else "wired"
        return "wired"

    @staticmethod
    def _linux_default_route() -> tuple[str, str] | None:
        try:
            with open("/proc/net/route", "r", encoding="ascii") as handle:
                lines = handle.read().splitlines()[1:]
        except OSError as error:
            raise NetworkHealthError("The active network route could not be read.") from error
        candidates: list[tuple[int, str, str]] = []
        for line in lines[:512]:
            fields = line.split()
            if len(fields) < 7 or fields[1] != "00000000":
                continue
            try:
                flags = int(fields[3], 16)
                raw_gateway = int(fields[2], 16)
                metric = int(fields[6], 10)
                if flags & 1 and raw_gateway and 0 <= metric <= 0xFFFFFFFF:
                    gateway = socket.inet_ntoa(struct.pack("<I", raw_gateway))
                    candidates.append((metric, fields[0], gateway))
            except (ValueError, OSError, struct.error):
                continue
        if not candidates:
            return None
        metric, interface, gateway = min(candidates)
        return gateway, interface

    @staticmethod
    def _windows_default_route() -> tuple[str, str] | None:
        system_root = os.environ.get("SystemRoot", "C:\\Windows")
        powershell_binary = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        if not os.path.isfile(powershell_binary):
            raise NetworkHealthError("The active network route could not be read.")
        query = (
            "$ErrorActionPreference='Stop'; "
            "$routes=@(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 -PolicyStore ActiveStore | "
            "ForEach-Object { $route=$_; $adapter=Get-NetIPInterface -AddressFamily IPv4 "
            "-InterfaceIndex $route.InterfaceIndex; $address=Get-NetIPAddress -AddressFamily IPv4 "
            "-InterfaceIndex $route.InterfaceIndex -AddressState Preferred | "
            "Select-Object -First 1 -ExpandProperty IPAddress; "
            "[pscustomobject]@{Metric=[int]($route.RouteMetric+$adapter.InterfaceMetric); "
            "Gateway=[string]$route.NextHop; InterfaceAddress=[string]$address} } | "
            "Sort-Object Metric,Gateway,InterfaceAddress | Select-Object -First 512); "
            "ConvertTo-Json -InputObject $routes -Compress"
        )
        safe_env = {
            "SystemRoot": system_root,
            "WINDIR": system_root,
            "PATH": os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0"),
            "PSModulePath": os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "Modules"),
            "LC_ALL": "C",
        }
        try:
            completed = subprocess.run(
                [powershell_binary, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", query],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=2.0, check=False, env=safe_env,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise NetworkHealthError("The active network route could not be read.") from error
        if completed.returncode != 0:
            raise NetworkHealthError("The active network route could not be read.")
        try:
            parsed = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError) as error:
            raise NetworkHealthError("The active network route could not be read.") from error
        records = parsed if isinstance(parsed, list) else [parsed]
        if len(records) > 512:
            raise NetworkHealthError("The active network route could not be read.")
        candidates: list[tuple[int, str, str]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                gateway = str(ipaddress.IPv4Address(record["Gateway"]))
                interface_address = str(ipaddress.IPv4Address(record["InterfaceAddress"]))
                metric = record["Metric"]
                if isinstance(metric, bool) or not isinstance(metric, int) or not 0 <= metric <= 0xFFFFFFFF:
                    continue
                if gateway != "0.0.0.0":
                    candidates.append((metric, interface_address, gateway))
            except (KeyError, ValueError, TypeError):
                continue
        if not candidates:
            return None
        metric, interface_address, gateway = min(candidates)
        return gateway, interface_address

    @staticmethod
    def _windows_interface_name(interface_address: str) -> str:
        try:
            interfaces = psutil.net_if_addrs()
        except Exception:
            return "Windows network interface"
        for name, addresses in interfaces.items():
            if not isinstance(name, str) or not name or len(name) > 64 or any(ord(character) < 32 for character in name):
                continue
            for address in addresses:
                if getattr(address, "family", None) == socket.AF_INET and getattr(address, "address", None) == interface_address:
                    return name
        return "Windows network interface"

    def _discover_router_port(self, gateway: str) -> int | None:
        for port in self.ROUTER_PORTS:
            if self._probe(gateway, port) is not None:
                return port
        return None

    def _probe_internet(self) -> float | None:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self._probe, host, self.INTERNET_PORT) for host in self.INTERNET_TARGETS]
            values = []
            for future in futures:
                try:
                    value = future.result(timeout=self.CONNECT_TIMEOUT_SECONDS + 0.25)
                except Exception:
                    value = None
                if value is not None:
                    values.append(value)
        return min(values) if values else None

    def _probe(self, host: str, port: int | None) -> float | None:
        if port is None:
            return None
        start = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=self.CONNECT_TIMEOUT_SECONDS):
                pass
        except ConnectionRefusedError:
            # A TCP reset is still a reply from the host, like a completed handshake.
            return max(0.0, (time.monotonic() - start) * 1000)
        except (OSError, TimeoutError):
            return None
        return max(0.0, (time.monotonic() - start) * 1000)

    @staticmethod
    def _loss_percent(samples: list[float | None]) -> float:
        return round(sum(value is None for value in samples) / len(samples) * 100, 1) if samples else 0.0

    def _result(self, status, headline, detail, interface, link_type, sample_count, router, internet) -> dict:
        router_values = [value for value in router if value is not None]
        internet_values = [value for value in internet if value is not None]
        return {
            "status": status,
            "headline": headline,
            "detail": detail,
            "interface": interface,
            "link_type": link_type,
            "sample_count": sample_count,
            "router_median_ms": round(statistics.median(router_values), 1) if router_values else None,
            "router_loss_percent": self._loss_percent(router) if router else None,
            "internet_median_ms": round(statistics.median(internet_values), 1) if internet_values else None,
            "internet_loss_percent": self._loss_percent(internet),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
