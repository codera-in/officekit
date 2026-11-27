import json
import socket
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import app
from officekit.engines.engine_network_health import (
    NetworkHealthError,
    NetworkHealthService,
    NetworkHealthUnsupportedError,
)


def service_with_samples(router, internet, router_port=53):
    service = NetworkHealthService()
    monkeypatches = [
        patch.object(service, "_default_route", return_value=("192.0.2.1", "en0", "wired")),
        patch.object(service, "_discover_router_port", return_value=router_port),
        patch.object(service, "_probe", side_effect=iter(router)),
        patch.object(service, "_probe_internet", side_effect=iter(internet)),
        patch("officekit.engines.engine_network_health.time.sleep"),
    ]
    for item in monkeypatches:
        item.start()
    return service, monkeypatches


def stop_patches(patches):
    for item in reversed(patches):
        item.stop()


@pytest.mark.parametrize(
    ("router", "internet", "router_port", "status"),
    [
        ([1.0, 1.0, 1.0], [10.0, 11.0, 12.0], 53, "healthy"),
        ([41.0, 42.0, 43.0], [50.0, 51.0, 52.0], 53, "router_slow"),
        ([None, 1.0, 1.0], [10.0, 11.0, 12.0], 53, "router_slow"),
        ([1.0, 1.0, 1.0], [None, 10.0, 11.0], 53, "internet_slow"),
        ([1.0, 1.0, 1.0], [102.0, 103.0, 104.0], 53, "internet_slow"),
        ([None, None, None], [10.0, 11.0, 12.0], None, "router_unmeasured"),
        ([1.0, 1.0, 1.0], [None, 10.0, None], 53, "incomplete"),
        ([1.0, 1.0, 1.0], [10.0, None, None], 53, "offline"),
    ],
)
def test_check_classifies_gateway_and_internet_samples(router, internet, router_port, status):
    service, cleanup = service_with_samples(router, internet, router_port)
    try:
        result = service.check()
    finally:
        stop_patches(cleanup)
    assert result["status"] == status
    assert result["link_type"] == "wired"
    assert result["sample_count"] == 3
    assert "gateway" not in result and "local_address" not in result


def test_check_returns_explicit_no_route_without_probing():
    service = NetworkHealthService()
    with patch.object(service, "_default_route", return_value=None), patch.object(service, "_discover_router_port") as discover:
        result = service.check()
    assert result["status"] == "no_route"
    assert result["sample_count"] == 0
    discover.assert_not_called()


@pytest.mark.parametrize(
    ("system", "route", "link_type", "expected"),
    [
        ("Darwin", ("192.0.2.1", "en0"), "wifi", ("192.0.2.1", "en0", "wifi")),
        ("Linux", ("192.0.2.1", "wlp2s0"), None, ("192.0.2.1", "wlp2s0", "wifi")),
        ("Linux", ("192.0.2.1", "enp0s31f6"), None, ("192.0.2.1", "enp0s31f6", "wired")),
        ("Windows", ("192.0.2.1", "10.0.0.8"), "Wi-Fi", ("192.0.2.1", "Wi-Fi", "wifi")),
        ("Windows", ("192.0.2.1", "10.0.0.8"), "Ethernet 2", ("192.0.2.1", "Ethernet 2", "wired")),
    ],
)
def test_default_route_classifies_supported_wifi_and_wired_platforms(system, route, link_type, expected):
    service = NetworkHealthService()
    with patch("officekit.engines.engine_network_health.platform.system", return_value=system), \
         patch.object(service, "_mac_default_route", return_value=route if system == "Darwin" else None), \
         patch.object(service, "_mac_link_type", return_value=link_type), \
         patch.object(service, "_linux_default_route", return_value=route if system == "Linux" else None), \
         patch.object(service, "_windows_default_route", return_value=route if system == "Windows" else None, create=True), \
         patch.object(service, "_windows_interface_name", return_value=link_type, create=True):
        assert service._default_route() == expected


def test_default_route_returns_none_for_empty_platform_route():
    service = NetworkHealthService()
    with patch("officekit.engines.engine_network_health.platform.system", return_value="Darwin"), \
         patch.object(service, "_mac_default_route", return_value=(None, None)):
        assert service._default_route() is None


@pytest.mark.parametrize(
    ("system", "reader"),
    [("Linux", "_linux_default_route"), ("Windows", "_windows_default_route")],
)
def test_default_route_returns_none_when_platform_has_no_route(system, reader):
    service = NetworkHealthService()
    with patch("officekit.engines.engine_network_health.platform.system", return_value=system), \
         patch.object(service, reader, return_value=None), \
         patch.object(service, "_windows_interface_name", return_value="Ethernet", create=True):
        assert service._default_route() is None


def test_default_route_rejects_invalid_gateway_and_unsupported_platform():
    service = NetworkHealthService()
    with patch("officekit.engines.engine_network_health.platform.system", return_value="Darwin"), \
         patch.object(service, "_mac_default_route", return_value=("not-an-ip", "en0")):
        with pytest.raises(NetworkHealthError):
            service._default_route()
    with patch("officekit.engines.engine_network_health.platform.system", return_value="Plan9"):
        with pytest.raises(NetworkHealthUnsupportedError):
            service._default_route()


@pytest.mark.parametrize(
    ("completed", "expected"),
    [
        (SimpleNamespace(returncode=0, stdout="gateway: 192.0.2.1\ninterface: en0\n"), ("192.0.2.1", "en0")),
        (SimpleNamespace(returncode=1, stdout=""), (None, None)),
        (SimpleNamespace(returncode=0, stdout="gateway: 192.0.2.1\n"), (None, None)),
    ],
)
def test_mac_default_route_parses_success_and_missing_routes(completed, expected):
    with patch("officekit.engines.engine_network_health.subprocess.run", return_value=completed) as run:
        assert NetworkHealthService()._mac_default_route() == expected
    assert run.call_args.args[0] == ["/sbin/route", "-n", "get", "default"]
    assert run.call_args.kwargs["timeout"] == 1.0


@pytest.mark.parametrize("failure", [OSError("private"), subprocess.TimeoutExpired("route", 1)])
def test_mac_default_route_hides_command_failures(failure):
    with patch("officekit.engines.engine_network_health.subprocess.run", side_effect=failure):
        with pytest.raises(NetworkHealthError, match="route could not be read"):
            NetworkHealthService()._mac_default_route()


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("Hardware Port: Wi-Fi\nDevice: en0\n\n", "wifi"),
        ("Hardware Port: Ethernet\nDevice: en1\n\n", "wired"),
        ("", "wired"),
    ],
)
def test_mac_link_type_uses_hardware_port_name(stdout, expected):
    with patch("officekit.engines.engine_network_health.subprocess.run", return_value=SimpleNamespace(stdout=stdout)):
        assert NetworkHealthService._mac_link_type("en0" if expected == "wifi" else "en1") == expected


def test_mac_link_type_falls_back_to_wired_when_command_fails():
    with patch("officekit.engines.engine_network_health.subprocess.run", side_effect=OSError):
        assert NetworkHealthService._mac_link_type("en0") == "wired"


def test_mac_link_type_recognizes_airport_and_timeout_fallback():
    with patch("officekit.engines.engine_network_health.subprocess.run", return_value=SimpleNamespace(stdout="Hardware Port: Airport\nDevice: en0\n")):
        assert NetworkHealthService._mac_link_type("en0") == "wifi"
    with patch("officekit.engines.engine_network_health.subprocess.run", side_effect=subprocess.TimeoutExpired("networksetup", 1)):
        assert NetworkHealthService._mac_link_type("en0") == "wired"


def test_linux_default_route_chooses_lowest_metric_deterministically():
    routes = """Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT
bad line
en9 00000100 0102A8C0 0003 0 0 1 00FFFFFF 0 0 0
en9 00000000 0102A8C0 0003 0 0 200 00000000 0 0 0
en2 00000000 0202A8C0 0003 0 0 10 00000000 0 0 0
en1 00000000 0302A8C0 0003 0 0 10 00000000 0 0 0
"""
    with patch("builtins.open", mock_open_text(routes)):
        assert NetworkHealthService._linux_default_route() == ("192.168.2.3", "en1")


def mock_open_text(text):
    from unittest.mock import mock_open
    return mock_open(read_data=text)


def test_linux_default_route_returns_none_for_missing_or_unusable_routes():
    with patch("builtins.open", mock_open_text("Iface Destination Gateway Flags Ref Use Metric Mask MTU Window IRTT\nen0 00000000 00000000 0001 0 0 1 00000000 0 0 0\nen1 00000000 01000000 0000 0 0 1 00000000 0 0 0\nen2 00000000 ZZZZZZZZ 0001 0 0 bad 00000000 0 0 0\nen3 00000000 FFFFFFFFFF 0001 0 0 1 00000000 0 0 0\n")):
        assert NetworkHealthService._linux_default_route() is None
    with patch("builtins.open", side_effect=OSError("private")):
        with pytest.raises(NetworkHealthError, match="route could not be read"):
            NetworkHealthService._linux_default_route()


def test_windows_default_route_chooses_lowest_metric_and_ignores_invalid_rows():
    output = json.dumps([
        {"Gateway": "192.168.1.1", "InterfaceAddress": "192.168.1.20", "Metric": 250},
        {"Gateway": "10.0.0.1", "InterfaceAddress": "10.0.0.8", "Metric": 20},
        {"Gateway": "0.0.0.0", "InterfaceAddress": "10.0.0.2", "Metric": 1},
        {"Gateway": "bad", "InterfaceAddress": "10.0.0.3", "Metric": 1},
        {"Gateway": "10.0.0.4", "InterfaceAddress": "10.0.0.4", "Metric": "invalid"},
    ])
    with patch("officekit.engines.engine_network_health.os.path.isfile", return_value=True), \
         patch("officekit.engines.engine_network_health.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout=output)) as run:
        assert NetworkHealthService._windows_default_route() == ("10.0.0.1", "10.0.0.8")
    command = run.call_args.args[0]
    assert command[-1].find("-PolicyStore ActiveStore") >= 0
    assert "Sort-Object Metric,Gateway,InterfaceAddress | Select-Object -First 512" in command[-1]
    assert "ConvertTo-Json" in command[-1]


def test_windows_default_route_returns_none_for_empty_active_store():
    with patch("officekit.engines.engine_network_health.os.path.isfile", return_value=True), \
         patch("officekit.engines.engine_network_health.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="[]")):
        assert NetworkHealthService._windows_default_route() is None


@pytest.mark.parametrize(
    "completed",
    [
        SimpleNamespace(returncode=0, stdout="null"),
        SimpleNamespace(returncode=0, stdout=json.dumps([
            {"Gateway": "0.0.0.0", "InterfaceAddress": "10.0.0.2", "Metric": 1},
            {"Gateway": "bad", "InterfaceAddress": "10.0.0.3", "Metric": 1},
            {"Gateway": "10.0.0.1", "InterfaceAddress": "10.0.0.4", "Metric": "invalid"},
            "not a route record",
        ])),
    ],
)
def test_windows_default_route_returns_none_for_empty_or_invalid_active_routes(completed):
    with patch("officekit.engines.engine_network_health.os.path.isfile", return_value=True), \
         patch("officekit.engines.engine_network_health.subprocess.run", return_value=completed):
        assert NetworkHealthService._windows_default_route() is None


def test_windows_default_route_rejects_nonzero_command_exit_malformed_json_and_oversized_results():
    cases = [
        SimpleNamespace(returncode=1, stdout="[]"),
        SimpleNamespace(returncode=0, stdout="not-json"),
        SimpleNamespace(returncode=0, stdout=json.dumps([{"Gateway": "10.0.0.1", "InterfaceAddress": "10.0.0.2", "Metric": 1}] * 513)),
    ]
    for completed in cases:
        with patch("officekit.engines.engine_network_health.os.path.isfile", return_value=True), \
             patch("officekit.engines.engine_network_health.subprocess.run", return_value=completed):
            with pytest.raises(NetworkHealthError):
                NetworkHealthService._windows_default_route()


def test_windows_route_errors_are_safe():
    with patch("officekit.engines.engine_network_health.os.path.isfile", return_value=False):
        with pytest.raises(NetworkHealthError):
            NetworkHealthService._windows_default_route()
    with patch("officekit.engines.engine_network_health.os.path.isfile", return_value=True), \
         patch("officekit.engines.engine_network_health.subprocess.run", side_effect=subprocess.TimeoutExpired("powershell", 2)):
        with pytest.raises(NetworkHealthError):
            NetworkHealthService._windows_default_route()
    with patch("officekit.engines.engine_network_health.os.path.isfile", return_value=True), \
         patch("officekit.engines.engine_network_health.subprocess.run", side_effect=OSError("private")):
        with pytest.raises(NetworkHealthError):
            NetworkHealthService._windows_default_route()


def test_windows_interface_lookup_maps_ipv4_to_a_sanitized_adapter_name():
    adapter = SimpleNamespace(family=socket.AF_INET, address="10.0.0.8")
    with patch("officekit.engines.engine_network_health.psutil.net_if_addrs", return_value={"Wi-Fi": [adapter]}):
        assert NetworkHealthService._windows_interface_name("10.0.0.8") == "Wi-Fi"
    with patch("officekit.engines.engine_network_health.psutil.net_if_addrs", side_effect=OSError):
        assert NetworkHealthService._windows_interface_name("10.0.0.8") == "Windows network interface"


def test_windows_interface_lookup_skips_unsafe_names_and_nonmatching_addresses():
    long_name = "x" * 65
    controls = "bad\x01name"
    entries = {
        4: [SimpleNamespace(family=socket.AF_INET, address="10.0.0.8")],
        "": [SimpleNamespace(family=socket.AF_INET, address="10.0.0.8")],
        long_name: [SimpleNamespace(family=socket.AF_INET, address="10.0.0.8")],
        controls: [SimpleNamespace(family=socket.AF_INET, address="10.0.0.8")],
        "Other": [SimpleNamespace(family=socket.AF_INET6, address="10.0.0.8"), SimpleNamespace(family=socket.AF_INET, address="10.0.0.9")],
    }
    with patch("officekit.engines.engine_network_health.psutil.net_if_addrs", return_value=entries):
        assert NetworkHealthService._windows_interface_name("10.0.0.8") == "Windows network interface"


def test_discover_router_port_stops_at_first_reply_and_handles_no_reply():
    service = NetworkHealthService()
    with patch.object(service, "_probe", side_effect=[None, 0.5, 0.7]) as probe:
        assert service._discover_router_port("192.0.2.1") == 80
        assert probe.call_count == 2
    with patch.object(service, "_probe", return_value=None):
        assert service._discover_router_port("192.0.2.1") is None


def test_probe_internet_uses_fastest_reply_and_handles_losses():
    service = NetworkHealthService()
    values = {"1.1.1.1": 25.0, "8.8.8.8": 10.0}
    with patch.object(service, "_probe", side_effect=lambda host, port: values[host]):
        assert service._probe_internet() == 10.0
    with patch.object(service, "_probe", side_effect=TimeoutError):
        assert service._probe_internet() is None


@pytest.mark.parametrize(
    ("side_effect", "expected"),
    [
        (None, 15.0),
        (ConnectionRefusedError("refused"), 15.0),
        (TimeoutError("timed out"), None),
        (OSError("network down"), None),
    ],
)
def test_probe_handles_success_refusal_timeout_and_os_error(side_effect, expected):
    service = NetworkHealthService()
    connection = MagicMock()
    with patch("officekit.engines.engine_network_health.time.monotonic", side_effect=[1.0, 1.015]), \
         patch("officekit.engines.engine_network_health.socket.create_connection", side_effect=side_effect, return_value=connection) as connect:
        result = service._probe("192.0.2.1", 443)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)
    if expected is not None:
        connect.assert_called_once_with(("192.0.2.1", 443), timeout=0.75)


def test_probe_without_port_returns_none_without_connecting():
    with patch("officekit.engines.engine_network_health.socket.create_connection") as connect:
        assert NetworkHealthService()._probe("192.0.2.1", None) is None
    connect.assert_not_called()


@pytest.mark.parametrize(("samples", "expected"), [([], 0.0), ([1.0, 2.0], 0.0), ([None], 100.0), ([1.0, None, 1.0], 33.3)])
def test_loss_percent_handles_empty_complete_and_lost_samples(samples, expected):
    assert NetworkHealthService._loss_percent(samples) == expected


def test_result_bounds_derived_metrics_and_null_router_values():
    result = NetworkHealthService()._result(
        "incomplete", "Measurement incomplete", "Not enough replies.", "en0", "wifi", 3,
        [None, None, None], [10.0, None, 20.0],
    )
    assert result["router_median_ms"] is None
    assert result["router_loss_percent"] == 100.0
    assert result["internet_median_ms"] == 15.0
    assert result["internet_loss_percent"] == 33.3
    assert result["checked_at"].endswith("+00:00")


def test_network_health_api_success_and_strict_empty_request():
    result = NetworkHealthService()._result("healthy", "Connection looks healthy", "All good.", "en0", "wired", 3, [1, 1, 1], [10, 10, 10])
    with patch("app.network_health_service.check", return_value=result):
        response = TestClient(app).post("/api/network/health", json={})
        bad_request = TestClient(app).post("/api/network/health", json={"extra": True})
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert bad_request.status_code == 422


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (NetworkHealthUnsupportedError("unsupported"), 501),
        (NetworkHealthError("private route details"), 503),
    ],
)
def test_network_health_api_maps_unsupported_and_service_errors_safely(error, status):
    with patch("app.network_health_service.check", side_effect=error):
        response = TestClient(app).post("/api/network/health", json={})
    assert response.status_code == status
    assert "private route details" not in response.text
