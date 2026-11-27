"""Bounded native network diagnostics for the supported macOS desktop build."""

import ipaddress
import math
import re
import subprocess
import sys


class NetworkDiagnosticError(RuntimeError):
    """A safe, client-visible network diagnostic failure."""

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


class NetworkDiagnostics:
    MIN_TIMEOUT_SECONDS = 0.1
    MAX_TIMEOUT_SECONDS = 10.0
    MIN_PACKETS = 1
    MAX_PACKETS = 10
    REPORTING_GRACE_SECONDS = 1.5
    PING_BINARY = "/sbin/ping"
    SAFE_ENV = {"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}
    HOST_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
    PACKET_STATS = re.compile(
        r"(?m)^(\d+) packets transmitted,\s*(\d+) packets received,\s*([0-9]+(?:\.[0-9]+)?)% packet loss\s*$"
    )
    LATENCY_STATS = re.compile(
        r"(?m)^(?:round-trip|rtt) min/avg/max/(?:stddev|mdev) = "
        r"([0-9]+(?:\.[0-9]+)?)/([0-9]+(?:\.[0-9]+)?)/([0-9]+(?:\.[0-9]+)?)/"
        r"[0-9]+(?:\.[0-9]+)? ms\s*$"
    )
    PERMISSION_MARKERS = (
        "operation not permitted",
        "permission denied",
        "not permitted",
        "permission required",
    )

    @classmethod
    def validate(cls, target, count, timeout_seconds):
        if not isinstance(target, str) or not target or len(target) > 253 or target != target.strip():
            raise ValueError("Target must be an IP address or hostname of at most 253 characters")
        try:
            ipaddress.ip_address(target)
        except ValueError:
            labels = target[:-1].split(".") if target.endswith(".") else target.split(".")
            if not labels or any(len(label) > 63 or not cls.HOST_LABEL.fullmatch(label) for label in labels):
                raise ValueError("Target must be an IP address or hostname without a scheme or port")
        if type(count) is not int or not cls.MIN_PACKETS <= count <= cls.MAX_PACKETS:
            raise ValueError(f"Packet count must be an integer from {cls.MIN_PACKETS} to {cls.MAX_PACKETS}")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
            raise ValueError(
                f"Timeout must be a finite number from {cls.MIN_TIMEOUT_SECONDS} to {cls.MAX_TIMEOUT_SECONDS} seconds"
            )
        try:
            normalized_timeout = float(timeout_seconds)
        except (OverflowError, ValueError) as error:
            raise ValueError(
                f"Timeout must be a finite number from {cls.MIN_TIMEOUT_SECONDS} to {cls.MAX_TIMEOUT_SECONDS} seconds"
            ) from error
        if not math.isfinite(normalized_timeout) or not cls.MIN_TIMEOUT_SECONDS <= normalized_timeout <= cls.MAX_TIMEOUT_SECONDS:
            raise ValueError(
                f"Timeout must be a finite number from {cls.MIN_TIMEOUT_SECONDS} to {cls.MAX_TIMEOUT_SECONDS} seconds"
            )
        return target, count, normalized_timeout

    @classmethod
    def ping(cls, target, count=4, timeout_seconds=3.0):
        target, count, timeout_seconds = cls.validate(target, count, timeout_seconds)
        if sys.platform != "darwin":
            raise NetworkDiagnosticError("Ping diagnostics are not supported on this platform yet.", 501)

        wait_budget_ms = round(timeout_seconds * 1000) - round(cls.REPORTING_GRACE_SECONDS * 1000)
        wait_milliseconds = str(max(1, wait_budget_ms))
        arguments = [cls.PING_BINARY, "-n", "-q", "-c", str(count), "-W", wait_milliseconds, target]
        try:
            completed = subprocess.run(
                arguments,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
                env=cls.SAFE_ENV,
            )
        except subprocess.TimeoutExpired:
            return cls._result(target, "timed_out")
        except FileNotFoundError as error:
            raise NetworkDiagnosticError("The native ping utility is unavailable on this Mac.") from error
        except PermissionError as error:
            raise NetworkDiagnosticError("macOS denied permission to run ping diagnostics.") from error
        except OSError as error:
            raise NetworkDiagnosticError("The local ping diagnostic is unavailable.") from error

        output = f"{completed.stdout or ''}\n{completed.stderr or ''}"
        if cls._permission_denied(output):
            return cls._result(target, "permission_denied")

        packet_match = cls.PACKET_STATS.search(completed.stdout or "")
        if packet_match is None:
            return cls._result(target, "incomplete")
        packets_sent, packets_received = int(packet_match.group(1)), int(packet_match.group(2))
        packet_loss_percent = float(packet_match.group(3))
        if (
            packets_sent != count
            or packets_received > packets_sent
            or not math.isfinite(packet_loss_percent)
            or not 0 <= packet_loss_percent <= 100
        ):
            return cls._result(target, "incomplete")

        if packets_received == packets_sent and completed.returncode == 0:
            status = "reachable"
        elif packets_received == 0:
            status = "no_reply"
        elif packets_received < packets_sent:
            status = "partial_loss"
        else:
            return cls._result(target, "incomplete")

        latency_match = cls.LATENCY_STATS.search(completed.stdout or "")
        latency = None
        if packets_received > 0 and latency_match is not None:
            minimum, average, maximum = (float(latency_match.group(index)) for index in range(1, 4))
            if all(math.isfinite(value) for value in (minimum, average, maximum)) and minimum <= average <= maximum:
                latency = {"min": minimum, "avg": average, "max": maximum}

        return cls._result(
            target,
            status,
            packets_sent=packets_sent,
            packets_received=packets_received,
            packet_loss_percent=packet_loss_percent,
            latency_ms=latency,
        )

    @classmethod
    def _permission_denied(cls, output):
        normalized = output.casefold()
        return any(marker in normalized for marker in cls.PERMISSION_MARKERS)

    @staticmethod
    def _result(
        target,
        status,
        packets_sent=None,
        packets_received=None,
        packet_loss_percent=None,
        latency_ms=None,
    ):
        return {
            "target": target,
            "status": status,
            "packets_sent": packets_sent,
            "packets_received": packets_received,
            "packet_loss_percent": packet_loss_percent,
            "latency_ms": latency_ms,
        }
