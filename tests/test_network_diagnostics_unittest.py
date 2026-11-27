"""Native macOS ping diagnostics and HTTP boundary tests."""

from types import SimpleNamespace
import subprocess
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import app
from officekit.engines.engine_network_diagnostics import NetworkDiagnosticError, NetworkDiagnostics


REACHABLE_OUTPUT = """PING example.com (192.0.2.1): 56 data bytes
--- example.com ping statistics ---
4 packets transmitted, 4 packets received, 0.0% packet loss
round-trip min/avg/max/stddev = 1.000/2.500/4.000/1.100 ms
"""


class PingInputTests(unittest.TestCase):
    def test_validates_bounded_hosts_packet_counts_and_timeouts(self):
        cases = (
            ("192.0.2.10", 1, 0.1),
            ("2001:db8::1", 10, 10),
            ("localhost", 4, 1.5),
            ("sub-domain.example.com", 3, 2),
        )
        for target, count, timeout in cases:
            with self.subTest(target=target):
                result = NetworkDiagnostics.validate(target, count, timeout)
                self.assertEqual(result, (target, count, float(timeout)))

    def test_rejects_invalid_host_syntax(self):
        for target in (
            "", " example.com", "example.com ", "https://example.com", "example.com:443",
            "-bad.example", "bad-.example", "bad..example", "bad/name", "bad\n.example",
            "a" * 64 + ".example", "x" * 254,
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                NetworkDiagnostics.validate(target, 4, 1.0)

    def test_rejects_invalid_counts_and_timeout_types_or_bounds(self):
        for count in (0, 11, True, 1.5, "4", None):
            with self.subTest(count=count), self.assertRaises(ValueError):
                NetworkDiagnostics.validate("example.com", count, 1.0)
        for timeout in (0, 0.09, 10.01, True, float("inf"), float("nan"), 10 ** 1000, "1", None):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                NetworkDiagnostics.validate("example.com", 4, timeout)


class MacPingEngineTests(unittest.TestCase):
    def setUp(self):
        super().setUp()
        patcher = patch("officekit.engines.engine_network_diagnostics.sys.platform", "darwin")
        self.addCleanup(patcher.stop)
        patcher.start()

    @patch("officekit.engines.engine_network_diagnostics.subprocess.run")
    def test_invokes_native_ping_without_a_shell_and_parses_success_metrics(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout=REACHABLE_OUTPUT, stderr="")

        result = NetworkDiagnostics.ping("example.com", count=4, timeout_seconds=2.5)

        self.assertEqual(result, {
            "target": "example.com", "status": "reachable", "packets_sent": 4,
            "packets_received": 4, "packet_loss_percent": 0.0,
            "latency_ms": {"min": 1.0, "avg": 2.5, "max": 4.0},
        })
        run.assert_called_once_with(
            ["/sbin/ping", "-n", "-q", "-c", "4", "-W", "1000", "example.com"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=2.5, check=False, env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        )

    @patch("officekit.engines.engine_network_diagnostics.subprocess.run")
    def test_reports_partial_loss_without_claiming_complete_reachability(self, run):
        run.return_value = SimpleNamespace(
            returncode=2,
            stdout="2 packets transmitted, 1 packets received, 50.0% packet loss\n",
            stderr="",
        )

        result = NetworkDiagnostics.ping("example.com", count=2, timeout_seconds=1)

        self.assertEqual(result["status"], "partial_loss")
        self.assertEqual(result["packets_sent"], 2)
        self.assertEqual(result["packets_received"], 1)
        self.assertEqual(result["packet_loss_percent"], 50.0)
        self.assertIsNone(result["latency_ms"])

    @patch("officekit.engines.engine_network_diagnostics.subprocess.run")
    def test_reports_no_reply_when_no_packets_are_received(self, run):
        run.return_value = SimpleNamespace(
            returncode=2,
            stdout="1 packets transmitted, 0 packets received, 100.0% packet loss\n",
            stderr="",
        )

        result = NetworkDiagnostics.ping("192.0.2.5", count=1, timeout_seconds=0.5)

        self.assertEqual(result["status"], "no_reply")
        self.assertEqual(result["packets_received"], 0)
        self.assertEqual(result["latency_ms"], None)

    @patch("officekit.engines.engine_network_diagnostics.subprocess.run")
    def test_permission_denial_is_distinguished_from_packet_loss(self, run):
        run.return_value = SimpleNamespace(returncode=2, stdout="", stderr="ping: sendto: Operation not permitted")

        result = NetworkDiagnostics.ping("example.com", count=2, timeout_seconds=1)

        self.assertEqual(result["status"], "permission_denied")
        self.assertIsNone(result["packets_sent"])
        self.assertIsNone(result["packet_loss_percent"])

    @patch("officekit.engines.engine_network_diagnostics.subprocess.run", side_effect=subprocess.TimeoutExpired("/sbin/ping", 0.1))
    def test_enforces_total_process_timeout(self, run):
        result = NetworkDiagnostics.ping("example.com", count=10, timeout_seconds=0.1)

        self.assertEqual(result["status"], "timed_out")
        self.assertEqual(result["packets_sent"], None)
        run.assert_called_once_with(
            ["/sbin/ping", "-n", "-q", "-c", "10", "-W", "1", "example.com"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=0.1, check=False, env={"LC_ALL": "C", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"},
        )

    @patch("officekit.engines.engine_network_diagnostics.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_native_ping_binary_is_reported_as_unsupported(self, run):
        with self.assertRaisesRegex(NetworkDiagnosticError, "unavailable") as caught:
            NetworkDiagnostics.ping("example.com", count=4, timeout_seconds=1)

        self.assertEqual(caught.exception.status_code, 503)
        run.assert_called_once()

    @patch("officekit.engines.engine_network_diagnostics.subprocess.run", side_effect=PermissionError)
    def test_process_permission_failure_is_actionable_and_safe(self, run):
        with self.assertRaisesRegex(NetworkDiagnosticError, "permission") as caught:
            NetworkDiagnostics.ping("example.com", count=4, timeout_seconds=1)

        self.assertEqual(caught.exception.status_code, 503)
        run.assert_called_once()

    @patch("officekit.engines.engine_network_diagnostics.subprocess.run", side_effect=OSError("private host details"))
    def test_unexpected_native_failures_do_not_echo_operating_system_details(self, run):
        with self.assertRaisesRegex(NetworkDiagnosticError, "unavailable") as caught:
            NetworkDiagnostics.ping("example.com", count=4, timeout_seconds=1)

        self.assertEqual(caught.exception.status_code, 503)
        self.assertNotIn("private host details", str(caught.exception))
        run.assert_called_once()

    @patch("officekit.engines.engine_network_diagnostics.subprocess.run")
    @patch("officekit.engines.engine_network_diagnostics.sys.platform", "linux")
    def test_non_macos_provider_is_explicitly_unavailable(self, run):
        with self.assertRaisesRegex(NetworkDiagnosticError, "not supported") as caught:
            NetworkDiagnostics.ping("example.com", count=4, timeout_seconds=1)

        self.assertEqual(caught.exception.status_code, 501)
        run.assert_not_called()

    @patch("officekit.engines.engine_network_diagnostics.subprocess.run")
    def test_unparseable_native_output_never_claims_reachability(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout="localized output", stderr="")

        result = NetworkDiagnostics.ping("example.com", count=4, timeout_seconds=1)

        self.assertEqual(result["status"], "incomplete")
        self.assertIsNone(result["packets_sent"])
        self.assertIsNone(result["latency_ms"])

    @patch("officekit.engines.engine_network_diagnostics.subprocess.run")
    def test_inconsistent_packet_statistics_never_claim_reachability(self, run):
        cases = (
            ("3 packets transmitted, 3 packets received, 0.0% packet loss", 4),
            ("4 packets transmitted, 5 packets received, 0.0% packet loss", 4),
            ("4 packets transmitted, 4 packets received, 101.0% packet loss", 4),
            ("4 packets transmitted, 4 packets received, " + ("9" * 400) + ".0% packet loss", 4),
        )
        for statistics, requested_count in cases:
            with self.subTest(statistics=statistics[:80]):
                run.return_value = SimpleNamespace(returncode=0, stdout=statistics, stderr=None)
                result = NetworkDiagnostics.ping("example.com", count=requested_count, timeout_seconds=1)
                self.assertEqual(result["status"], "incomplete")
                self.assertIsNone(result["packets_sent"])

    @patch("officekit.engines.engine_network_diagnostics.subprocess.run")
    def test_bad_latency_order_is_omitted_even_when_packet_replies_are_valid(self, run):
        output = (
            "4 packets transmitted, 4 packets received, 0.0% packet loss\n"
            "round-trip min/avg/max/stddev = 5.000/2.000/1.000/0.500 ms\n"
        )
        run.return_value = SimpleNamespace(returncode=0, stdout=output, stderr=None)

        result = NetworkDiagnostics.ping("example.com", count=4, timeout_seconds=1)

        self.assertEqual(result["status"], "reachable")
        self.assertIsNone(result["latency_ms"])

        run.return_value = SimpleNamespace(returncode=2, stdout=REACHABLE_OUTPUT, stderr=None)
        incomplete = NetworkDiagnostics.ping("example.com", count=4, timeout_seconds=1)
        self.assertEqual(incomplete["status"], "incomplete")
        self.assertIsNone(incomplete["latency_ms"])
        self.assertEqual(run.call_count, 2)

    @patch("app.NetworkDiagnostics.ping", side_effect=NetworkDiagnosticError("The native ping utility is unavailable on this Mac."))
    def test_ping_route_maps_native_service_failures_without_leaking_os_errors(self, ping):
        response = TestClient(app).post("/api/network/ping", json={"target": "localhost"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "The native ping utility is unavailable on this Mac.")
        ping.assert_called_once_with("localhost", 4, 3.0)


class PingHttpTests(unittest.TestCase):
    @patch("app.NetworkDiagnostics.ping")
    def test_ping_route_returns_typed_diagnostic_for_valid_request(self, ping):
        ping.return_value = {
            "target": "localhost", "status": "reachable", "packets_sent": 1,
            "packets_received": 1, "packet_loss_percent": 0.0,
            "latency_ms": {"min": 0.05, "avg": 0.05, "max": 0.05},
        }
        response = TestClient(app).post(
            "/api/network/ping",
            json={"target": "localhost", "count": 1, "timeout_seconds": 1},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), ping.return_value)
        ping.assert_called_once_with("localhost", 1, 1.0)

    def test_ping_route_rejects_bad_dtos_before_running_network_operation(self):
        for payload in (
            {"target": "localhost", "count": 0, "timeout_seconds": 1},
            {"target": "https://localhost", "count": 1, "timeout_seconds": 1},
            {"target": "localhost", "count": 1, "timeout_seconds": 11},
            {"target": "localhost", "count": 1, "timeout_seconds": True},
            {"target": "localhost", "count": 1, "timeout_seconds": 1, "extra": True},
        ):
            with self.subTest(payload=payload):
                response = TestClient(app).post("/api/network/ping", json=payload)
                self.assertEqual(response.status_code, 422)

    @patch("app.NetworkDiagnostics.ping", side_effect=NetworkDiagnosticError("Ping is not supported on this platform.", 501))
    def test_ping_route_returns_explicit_platform_unavailable_error(self, ping):
        response = TestClient(app).post("/api/network/ping", json={"target": "localhost"})

        self.assertEqual(response.status_code, 501)
        self.assertEqual(response.json()["detail"], "Ping is not supported on this platform.")
        ping.assert_called_once_with("localhost", 4, 3.0)


if __name__ == "__main__":
    unittest.main()
