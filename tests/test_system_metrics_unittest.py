import plistlib
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from officekit.engines.engine_system_metrics import (
    SystemMetricsService,
    _ioreg_records,
    macos_battery_metrics,
    macos_gpu_metrics,
    system_battery_metrics,
    system_sensor_metrics,
)


def test_ioreg_records_fail_closed_for_other_platforms_and_bad_plists(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert _ioreg_records("AppleSmartBattery", Mock()) is None
    monkeypatch.setattr(sys, "platform", "darwin")
    assert _ioreg_records("AppleSmartBattery", Mock(return_value=SimpleNamespace(stdout=b"bad plist"))) is None
    assert _ioreg_records("AppleSmartBattery", Mock(return_value=SimpleNamespace(stdout=plistlib.dumps({"not": "a list"})))) is None


def test_macos_gpu_metrics_uses_bounded_ioreg_percentages(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    record = {"PerformanceStatistics": {
        "Device Utilization %": 17,
        "Renderer Utilization %": 9,
        "Tiler Utilization %": 101,
    }}
    run = Mock(return_value=SimpleNamespace(stdout=plistlib.dumps([record])))

    assert macos_gpu_metrics(run) == {
        "utilization_percent": 17.0,
        "renderer_percent": 9.0,
        "tiler_percent": None,
    }
    run.assert_called_once()


def test_macos_battery_metrics_parses_charge_health_and_time(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    record = {
        "AppleRawMaxCapacity": 4600,
        "DesignCapacity": 5000,
        "CycleCount": 324,
        "IsCharging": False,
        "BatteryHealth": "Good",
        # This is a capacity value in mAh, not a percentage.
        "CurrentCapacity": 76,
    }

    def run(command, **_kwargs):
        if command[0].endswith("ioreg"):
            return SimpleNamespace(stdout=plistlib.dumps([record]))
        return SimpleNamespace(stdout="Now drawing from 'Battery Power'\n-InternalBattery-0 76%; discharging; 2:15 remaining\n")

    result = macos_battery_metrics(run)
    assert result == {
        "percent": 76,
        "power_source": "battery",
        "state": "discharging",
        "time_remaining_seconds": 8100,
        "cycle_count": 324,
        "designed_capacity_mah": 5000,
        "full_charge_capacity_mah": 4600,
        "health_percent": 92.0,
        "condition": "Normal",
        "adapter_watts": None,
        "voltage_v": None,
        "current_a": None,
        "power_w": None,
        "temperature_c": None,
    }


def test_macos_battery_hides_phantom_ioreg_records_when_pmset_reports_none(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    record = {"CurrentCapacity": 76, "CycleCount": 0}

    def run(command, **_kwargs):
        if command[0].endswith("ioreg"):
            return SimpleNamespace(stdout=plistlib.dumps([record]))
        return SimpleNamespace(stdout="Now drawing from 'AC Power'\nNo batteries available\n")

    assert macos_battery_metrics(run) is None


@pytest.mark.parametrize(
    ("power", "expected_source", "expected_state"),
    [
        ("Now drawing from 'Battery Power'\n76%; discharging; 2:15 remaining\n", "battery", "discharging"),
        ("Now drawing from 'Battery Power'\n76%; charging; 1:20 remaining\n", "battery", "charging"),
        ("Now drawing from 'AC Power'\n100%; charged; 0:00 remaining\n", "ac", "charged"),
    ],
)
def test_macos_battery_state_fallback_parses_pmset_state_token(monkeypatch, power, expected_source, expected_state):
    monkeypatch.setattr(sys, "platform", "darwin")
    record = {"CurrentCapacity": 76, "CycleCount": 20}

    def run(command, **_kwargs):
        if command[0].endswith("ioreg"):
            return SimpleNamespace(stdout=plistlib.dumps([record]))
        return SimpleNamespace(stdout=power)

    result = macos_battery_metrics(run)
    assert result["power_source"] == expected_source
    assert result["state"] == expected_state


def test_macos_battery_reads_nested_capacity_fields(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    record = {"BatteryData": {"AppleRawMaxCapacity": 4500, "DesignCapacity": 5000}}

    def run(command, **_kwargs):
        if command[0].endswith("ioreg"):
            return SimpleNamespace(stdout=plistlib.dumps([record]))
        return SimpleNamespace(stdout="Now drawing from 'Battery Power'\n60%; discharging\n")

    result = macos_battery_metrics(run)
    assert result["full_charge_capacity_mah"] == 4500
    assert result["designed_capacity_mah"] == 5000
    assert result["health_percent"] == 90.0


def test_macos_battery_optional_sources_and_condition_states(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert macos_battery_metrics(lambda *_args, **_kwargs: SimpleNamespace(stdout=plistlib.dumps([]))) is None
    record = {"Condition": "Replace Now"}

    def run(command, **_kwargs):
        if command[0].endswith("ioreg"):
            return SimpleNamespace(stdout=plistlib.dumps([record]))
        return SimpleNamespace(stdout="Now drawing from 'Battery Power'\n60%; discharging\n")

    result = macos_battery_metrics(run)
    assert result["condition"] == "Service required"
    assert result["health_percent"] is None
    no_state = macos_battery_metrics(lambda command, **_kwargs: SimpleNamespace(
        stdout=plistlib.dumps([{}]) if command[0].endswith("ioreg") else "50%; unknown"
    ))
    assert no_state["state"] == "unknown"
    record["Condition"] = "Fair"
    assert macos_battery_metrics(run)["condition"] == "Service recommended"
    failed_power = macos_battery_metrics(lambda command, **_kwargs: (
        SimpleNamespace(stdout=plistlib.dumps([{}])) if command[0].endswith("ioreg") else (_ for _ in ()).throw(OSError())
    ))
    assert failed_power is None


def test_macos_ioreg_and_gpu_records_without_metrics_are_unavailable(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert macos_gpu_metrics(lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unavailable"))) is None
    assert macos_gpu_metrics(lambda *_args, **_kwargs: SimpleNamespace(stdout=plistlib.dumps([{"Name": "GPU"}]))) is None


def test_portable_battery_provider_uses_psutil_values(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("officekit.engines.engine_system_metrics.psutil.sensors_battery", lambda: SimpleNamespace(
        percent=62.5, power_plugged=False, secsleft=3600,
    ))
    result = system_battery_metrics()
    assert result["percent"] == 62.5
    assert result["power_source"] == "battery"
    assert result["state"] == "discharging"
    assert result["time_remaining_seconds"] == 3600
    assert result["health_percent"] is None


def test_portable_battery_provider_rejects_missing_invalid_and_failed_data(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr("officekit.engines.engine_system_metrics.psutil.sensors_battery", lambda: None)
    assert system_battery_metrics() is None
    monkeypatch.setattr("officekit.engines.engine_system_metrics.psutil.sensors_battery", lambda: SimpleNamespace(
        percent=101, power_plugged=None, secsleft=-1,
    ))
    assert system_battery_metrics() is None
    monkeypatch.setattr("officekit.engines.engine_system_metrics.psutil.sensors_battery", lambda: (_ for _ in ()).throw(OSError()))
    assert system_battery_metrics() is None


def test_portable_sensor_provider_validates_and_caps_readings(monkeypatch):
    entries = [SimpleNamespace(label=f"Sensor {i}", current=float(20 + i), high=90.0) for i in range(20)]
    entries.extend([SimpleNamespace(label="bad", current=float("nan"), high=None), SimpleNamespace(label="", current=200.0, high=None)])
    monkeypatch.setattr("officekit.engines.engine_system_metrics.psutil.sensors_temperatures", lambda: {"cpu": entries}, raising=False)
    result = system_sensor_metrics()
    assert len(result) == 16
    assert result[0] == {"name": "Sensor 0", "current_c": 20.0, "high_c": 90.0}
    assert all(sensor["current_c"] <= 150 for sensor in result)


def test_portable_sensor_provider_handles_unsupported_and_malformed_groups(monkeypatch):
    setter = "officekit.engines.engine_system_metrics.psutil.sensors_temperatures"
    monkeypatch.setattr(setter, lambda: (_ for _ in ()).throw(OSError()), raising=False)
    assert system_sensor_metrics() is None
    monkeypatch.setattr(setter, lambda: [], raising=False)
    assert system_sensor_metrics() is None
    monkeypatch.setattr(setter, lambda: {"cpu": "invalid", "gpu": [SimpleNamespace(current=float("inf"))]}, raising=False)
    assert system_sensor_metrics() is None


def test_metrics_snapshot_includes_injected_hardware_providers():
    clock = Mock(return_value=10.0)
    resource = Mock()
    resource.snapshot.return_value = {"cpu_percent": 20, "memory_percent": 40}
    service = SystemMetricsService(
        resource_service=resource,
        disk_provider=Mock(return_value=SimpleNamespace(percent=50)),
        network_provider=Mock(return_value={"en0": SimpleNamespace(bytes_sent=1, bytes_recv=1)}),
        interface_provider=Mock(return_value={"en0": SimpleNamespace(isup=True)}),
        monotonic_clock=clock,
        wall_clock=lambda: 0,
        cpu_cores_provider=lambda: [5, 45],
        gpu_provider=lambda: {"utilization_percent": 25, "renderer_percent": 20, "tiler_percent": 10},
        battery_provider=lambda: {"percent": 80, "power_source": "ac", "state": "charging"},
        sensors_provider=lambda: [{"name": "CPU", "current_c": 42.0, "high_c": None}],
    )
    result = service.snapshot()
    assert result["cpu_cores_percent"] == [5.0, 45.0]
    assert result["gpu"]["utilization_percent"] == 25
    assert result["battery"]["percent"] == 80
    assert result["sensors"][0]["name"] == "CPU"


def test_metrics_snapshot_rejects_invalid_core_usage_provider():
    clock = Mock(return_value=10.0)
    resource = Mock()
    resource.snapshot.return_value = {"cpu_percent": 20, "memory_percent": 40}
    service = SystemMetricsService(
        resource_service=resource,
        disk_provider=Mock(return_value=SimpleNamespace(percent=50)),
        network_provider=Mock(return_value={"en0": SimpleNamespace(bytes_sent=1, bytes_recv=1)}),
        interface_provider=Mock(return_value={"en0": SimpleNamespace(isup=True)}),
        monotonic_clock=clock,
        wall_clock=lambda: 0,
        cpu_cores_provider=lambda: [],
    )
    assert service.snapshot()["cpu_cores_percent"] is None


def make_service():
    clock = Mock(return_value=10.0)
    resource = Mock()
    resource.snapshot.return_value = {"cpu_percent": 20, "memory_percent": 40}
    disk = Mock(return_value=SimpleNamespace(percent=50))
    network = Mock(return_value={"en0": SimpleNamespace(bytes_sent=100, bytes_recv=200),
                                "lo0": SimpleNamespace(bytes_sent=9000, bytes_recv=9000)})
    interfaces = Mock(return_value={"en0": SimpleNamespace(isup=True), "lo0": SimpleNamespace(isup=True)})
    service = SystemMetricsService(resource_service=resource, disk_provider=disk,
        network_provider=network, interface_provider=interfaces, monotonic_clock=clock, wall_clock=lambda: 0)
    return service, clock, resource, disk, network, interfaces


def test_warming_cache_rates_and_independent_return_objects():
    service, clock, resource, disk, network, interfaces = make_service()
    first = service.snapshot()
    assert first["upload_bytes_per_second"] is None
    assert "warming" in first["reasons"]["network"].lower()
    assert first["storage_percent"] == 50
    assert first["captured_at"] == "1970-01-01T00:00:00+00:00"
    first["reasons"]["network"] = "corrupted"
    clock.return_value = 10.5
    assert service.snapshot()["sample_age_ms"] == 500
    resource.snapshot.assert_called_once_with()
    disk.assert_called_once_with("/")
    network.assert_called_once_with(pernic=True)
    interfaces.assert_called_once_with()
    clock.return_value = 12.0
    network.return_value["en0"] = SimpleNamespace(bytes_sent=300, bytes_recv=800)
    second = service.snapshot()
    assert second["upload_bytes_per_second"] == 100
    assert second["download_bytes_per_second"] == 300
    assert second["reasons"] == {}


def test_reset_and_interface_switch_never_produce_negative_rates():
    service, clock, _, _, network, interfaces = make_service()
    service.snapshot()
    clock.return_value = 12
    network.return_value["en0"] = SimpleNamespace(bytes_sent=10, bytes_recv=10)
    assert "reset" in service.snapshot()["reasons"]["network"].lower()
    clock.return_value = 14
    network.return_value = {"wlan0": SimpleNamespace(bytes_sent=50, bytes_recv=70)}
    interfaces.return_value = {"wlan0": SimpleNamespace(isup=True)}
    assert service.snapshot()["upload_bytes_per_second"] is None


@pytest.mark.parametrize("bad", [True, float("nan"), -1, 101, "20"])
def test_invalid_resource_values_are_unavailable(bad):
    service, _, resource, disk, _, _ = make_service()
    resource.snapshot.return_value = {"cpu_percent": bad, "memory_percent": bad}
    disk.return_value = SimpleNamespace(percent=bad)
    result = service.snapshot()
    assert result["cpu_percent"] is None
    assert result["memory_percent"] is None
    assert result["storage_percent"] is None


def test_provider_failures_keep_partial_snapshot():
    service, _, resource, disk, network, _ = make_service()
    resource.snapshot.side_effect = RuntimeError("private")
    disk.side_effect = RuntimeError("private")
    network.side_effect = RuntimeError("private")
    result = service.snapshot()
    assert all(result[field] is None for field in ("cpu_percent", "memory_percent", "storage_percent", "upload_bytes_per_second"))
    assert "private" not in str(result)


@pytest.mark.parametrize("value", [True, float("nan"), "bad"])
def test_invalid_clock_rejected(value):
    service, clock, _, _, _, _ = make_service()
    clock.return_value = value
    with pytest.raises(ValueError, match="clock"):
        service.snapshot()


@pytest.mark.parametrize("interfaces,counters", [({}, {}), ({"lo0": SimpleNamespace(isup=True)}, {"lo0": SimpleNamespace(bytes_sent=10, bytes_recv=20)}),
    ({"en0": SimpleNamespace(isup=False)}, {"en0": SimpleNamespace(bytes_sent=10, bytes_recv=20)}),
    ({"en0": SimpleNamespace(isup=True)}, {"en0": SimpleNamespace(bytes_sent=-1, bytes_recv=20)})])
def test_unavailable_network_is_null(interfaces, counters):
    service, _, _, _, network, stats = make_service()
    network.return_value = counters
    stats.return_value = interfaces
    assert service.snapshot()["upload_bytes_per_second"] is None


@pytest.mark.parametrize("counters,interfaces", [(None, {}), ({}, None), ({str(i): None for i in range(1025)}, {})])
def test_network_payloads_are_bounded(counters, interfaces):
    service, _, _, _, network, stats = make_service()
    network.return_value, stats.return_value = counters, interfaces
    assert service.snapshot()["reasons"]["network"] == "Network information unavailable."


def test_active_physical_interface_excludes_vpn_double_counting():
    service, clock, _, _, network, interfaces = make_service()
    network.return_value["utun0"] = SimpleNamespace(bytes_sent=90000, bytes_recv=90000)
    interfaces.return_value["utun0"] = SimpleNamespace(isup=True)
    service.snapshot()
    clock.return_value = 12
    network.return_value["en0"] = SimpleNamespace(bytes_sent=300, bytes_recv=800)
    network.return_value["utun0"] = SimpleNamespace(bytes_sent=200000, bytes_recv=200000)
    assert service.snapshot()["upload_bytes_per_second"] == 100


def test_network_rates_follow_the_physical_adapter_with_observed_traffic():
    service, clock, _, _, network, interfaces = make_service()
    network.return_value["en0"] = SimpleNamespace(bytes_sent=100, bytes_recv=200)
    network.return_value["utun0"] = SimpleNamespace(bytes_sent=5000, bytes_recv=7000)
    interfaces.return_value.update({"en0": SimpleNamespace(isup=True), "utun0": SimpleNamespace(isup=True)})
    assert service.snapshot()["upload_bytes_per_second"] is None

    clock.return_value = 12
    network.return_value["en0"] = SimpleNamespace(bytes_sent=100, bytes_recv=200)
    network.return_value["en1"] = SimpleNamespace(bytes_sent=1000, bytes_recv=2000)
    interfaces.return_value["en1"] = SimpleNamespace(isup=True)
    network.return_value["utun0"] = SimpleNamespace(bytes_sent=9000, bytes_recv=15000)
    result = service.snapshot()
    assert result["upload_bytes_per_second"] is None
    assert "warming up" in result["reasons"]["network"]

    clock.return_value = 14
    network.return_value["en1"] = SimpleNamespace(bytes_sent=1400, bytes_recv=3000)
    network.return_value["utun0"] = SimpleNamespace(bytes_sent=19000, bytes_recv=35000)
    result = service.snapshot()
    assert result["upload_bytes_per_second"] == 200
    assert result["download_bytes_per_second"] == 500
    assert result["reasons"] == {}

    clock.return_value = 16
    network.return_value["en1"] = SimpleNamespace(bytes_sent=1800, bytes_recv=4000)
    network.return_value["utun0"] = SimpleNamespace(bytes_sent=39000, bytes_recv=75000)
    result = service.snapshot()
    assert result["upload_bytes_per_second"] == 200
    assert result["download_bytes_per_second"] == 500
    assert result["reasons"] == {}


def test_network_rates_sum_traffic_across_active_physical_adapters():
    service, clock, _, _, network, interfaces = make_service()
    network.return_value = {
        "en0": SimpleNamespace(bytes_sent=100, bytes_recv=200),
        "en1": SimpleNamespace(bytes_sent=1000, bytes_recv=2000),
    }
    interfaces.return_value = {
        "en0": SimpleNamespace(isup=True),
        "en1": SimpleNamespace(isup=True),
    }
    service.snapshot()

    clock.return_value = 12
    network.return_value = {
        "en0": SimpleNamespace(bytes_sent=200, bytes_recv=400),
        "en1": SimpleNamespace(bytes_sent=1000, bytes_recv=2200),
    }
    result = service.snapshot()

    assert result["upload_bytes_per_second"] == 50
    assert result["download_bytes_per_second"] == 200
    assert result["reasons"] == {}


def test_backwards_clock_resets_sample_instead_of_using_negative_interval():
    service, clock, _, _, _, _ = make_service()
    service.snapshot()
    clock.return_value = 9
    assert "reset" in service.snapshot()["reasons"]["network"].lower()
