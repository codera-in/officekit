from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from officekit.engines.engine_system_metrics import (
    PRESSURE_SYSCTL_KEY,
    SYSCTL_PATH,
    VM_STAT_PATH,
    SystemMetricsService,
    cpu_split_percent,
    macos_cpu_topology,
    macos_memory_breakdown,
    macos_memory_pressure,
    parse_vm_stat,
)

PAGE = 16384
VM_STAT = f"""Mach Virtual Memory Statistics: (page size of {PAGE} bytes)
Pages free:                                     4214.
Pages active:                                 428285.
Pages inactive:                               421141.
Pages speculative:                              1000.
Pages wired down:                             100000.
Pages occupied by compressor:                 200000.
Anonymous pages:                              400000.
Pages purgeable:                                5000.
File-backed pages:                            297675.
"""
TOTAL = 2_097_152 * PAGE


def runner(output):
    return Mock(return_value=SimpleNamespace(stdout=output))


def test_vm_stat_page_size_and_counts_are_parsed():
    page_size, pages = parse_vm_stat(VM_STAT)
    assert page_size == PAGE
    assert pages["Pages wired down"] == 100000
    assert pages["Pages occupied by compressor"] == 200000


def test_vm_stat_without_a_page_size_is_rejected():
    with pytest.raises(ValueError):
        parse_vm_stat("Pages free: 1.")


def test_memory_breakdown_follows_activity_monitor_definitions():
    breakdown = macos_memory_breakdown(run=runner(VM_STAT), total_bytes=TOTAL)
    app = (400000 - 5000) * PAGE
    wired = 100000 * PAGE
    compressed = 200000 * PAGE
    assert breakdown == {
        "total_bytes": TOTAL,
        "used_bytes": app + wired + compressed,
        "app_bytes": app,
        "wired_bytes": wired,
        "compressed_bytes": compressed,
        "free_bytes": TOTAL - (app + wired + compressed),
    }


def test_memory_breakdown_never_reports_more_used_than_installed():
    small_total = 100 * PAGE
    breakdown = macos_memory_breakdown(run=runner(VM_STAT), total_bytes=small_total)
    assert breakdown["used_bytes"] == small_total
    assert breakdown["free_bytes"] == 0


def test_memory_breakdown_is_none_when_vm_stat_is_missing_or_fails():
    assert macos_memory_breakdown(run=runner(VM_STAT.replace("Anonymous pages", "Other")), total_bytes=TOTAL) is None
    assert macos_memory_breakdown(run=Mock(side_effect=OSError("missing")), total_bytes=TOTAL) is None


def test_memory_pressure_maps_kernel_levels_and_runs_the_fixed_sysctl_path():
    run = Mock(return_value=SimpleNamespace(stdout="2\n"))
    assert macos_memory_pressure(run=run) == "warning"
    run.assert_called_once()
    args = run.call_args.args[0]
    assert args == [SYSCTL_PATH, "-n", PRESSURE_SYSCTL_KEY]
    assert SYSCTL_PATH == "/usr/sbin/sysctl"
    assert macos_memory_pressure(run=runner("1\n")) == "normal"
    assert macos_memory_pressure(run=runner("4\n")) == "critical"
    assert macos_memory_pressure(run=runner("9\n")) is None
    assert macos_memory_pressure(run=runner("not a number")) is None
    assert macos_memory_pressure(run=Mock(side_effect=OSError())) is None


def test_vm_stat_path_is_absolute():
    assert VM_STAT_PATH == "/usr/bin/vm_stat"


def test_cpu_split_is_the_share_of_elapsed_time():
    split = cpu_split_percent({"user": 10, "nice": 5, "system": 20, "idle": 65})
    assert split == {"user_percent": 15.0, "system_percent": 20.0, "idle_percent": 65.0}


def test_cpu_split_needs_elapsed_time():
    assert cpu_split_percent({"user": 0, "nice": 0, "system": 0, "idle": 0}) is None
    assert cpu_split_percent({}) is None


def make_service(clock, cpu_times, disk_io, **providers):
    resource = Mock()
    resource.snapshot.return_value = {"cpu_percent": 20, "memory_percent": 40}
    defaults = dict(
        memory_breakdown_provider=lambda: {"total_bytes": 10, "used_bytes": 4, "app_bytes": 1,
                                           "wired_bytes": 1, "compressed_bytes": 2, "free_bytes": 6},
        pressure_provider=lambda: "warning",
        topology_provider=lambda: None,
        swap_provider=lambda: SimpleNamespace(used=5_000, total=10_000, percent=50.0),
        load_provider=lambda: (1.234, 5.5, 15.0),
        boot_time_provider=lambda: 999_000.0,
        network_provider=Mock(side_effect=OSError()),
        interface_provider=Mock(),
    )
    defaults.update(providers)
    return SystemMetricsService(
        resource_service=resource,
        disk_provider=Mock(return_value=SimpleNamespace(percent=50, used=500, total=1000)),
        monotonic_clock=clock,
        wall_clock=lambda: 1_000_000.0,
        cpu_times_provider=cpu_times,
        disk_io_provider=disk_io,
        **defaults,
    )


def test_snapshot_carries_memory_cpu_disk_and_system_details():
    cpu = Mock(side_effect=[
        SimpleNamespace(user=100, nice=0, system=50, idle=850),
        SimpleNamespace(user=130, nice=0, system=60, idle=910),
    ])
    disk_io = Mock(side_effect=[
        SimpleNamespace(read_bytes=1000, write_bytes=2000),
        SimpleNamespace(read_bytes=3000, write_bytes=2600),
    ])
    service = make_service(Mock(side_effect=[10.0, 12.0]), cpu, disk_io)

    first = service.snapshot()
    assert first["cpu_breakdown"] is None
    assert first["disk"]["read_bytes_per_second"] is None
    assert first["disk"]["used_bytes"] == 500 and first["disk"]["total_bytes"] == 1000

    second = service.snapshot()
    assert second["cpu_breakdown"] == {"user_percent": 30.0, "system_percent": 10.0, "idle_percent": 60.0}
    assert second["disk"]["read_bytes_per_second"] == 1000.0
    assert second["disk"]["write_bytes_per_second"] == 300.0
    assert second["memory"]["free_bytes"] == 6
    assert second["memory_pressure"] == "warning"
    assert second["swap"] == {"used_bytes": 5_000, "total_bytes": 10_000, "percent": 50.0}
    assert second["load_average"] == [1.23, 5.5, 15.0]
    assert second["uptime_seconds"] == 1000


def sysctl_runner(values):
    def run(command, **_):
        assert command[0] == SYSCTL_PATH and command[1] == "-n"
        if command[2] not in values:
            raise OSError("unknown key")
        return SimpleNamespace(stdout=values[command[2]] + "\n")
    return run


def test_cpu_topology_reads_the_model_and_the_performance_and_efficiency_core_counts():
    run = sysctl_runner({"machdep.cpu.brand_string": "Apple M3 Pro", "hw.perflevel0.logicalcpu": "6", "hw.perflevel1.logicalcpu": "6"})
    assert macos_cpu_topology(run=run) == {"model": "Apple M3 Pro", "performance_cores": 6, "efficiency_cores": 6}


def test_cpu_topology_without_core_levels_keeps_the_model_only():
    assert macos_cpu_topology(run=sysctl_runner({"machdep.cpu.brand_string": "Intel(R) Core(TM) i7"})) == {
        "model": "Intel(R) Core(TM) i7", "performance_cores": None, "efficiency_cores": None}


def test_cpu_topology_is_none_when_the_model_is_unreadable_or_oversized():
    assert macos_cpu_topology(run=sysctl_runner({})) is None
    assert macos_cpu_topology(run=sysctl_runner({"machdep.cpu.brand_string": "x" * 200})) is None


def test_cpu_topology_rejects_impossible_core_counts():
    run = sysctl_runner({"machdep.cpu.brand_string": "Apple M3", "hw.perflevel0.logicalcpu": "-1", "hw.perflevel1.logicalcpu": "9999"})
    assert macos_cpu_topology(run=run) == {"model": "Apple M3", "performance_cores": None, "efficiency_cores": None}


def test_snapshot_carries_the_topology_once_and_reads_it_only_on_the_first_snapshot():
    cpu = Mock(side_effect=[SimpleNamespace(user=1, nice=0, system=1, idle=8)] * 2)
    disk_io = Mock(side_effect=[SimpleNamespace(read_bytes=0, write_bytes=0)] * 2)
    topology = Mock(return_value={"model": "Apple M3", "performance_cores": 4, "efficiency_cores": 4})
    service = make_service(Mock(side_effect=[10.0, 12.0]), cpu, disk_io, topology_provider=topology)
    assert service.snapshot()["cpu_topology"] == {"model": "Apple M3", "performance_cores": 4, "efficiency_cores": 4}
    assert service.snapshot()["cpu_topology"]["model"] == "Apple M3"
    assert topology.call_count == 1


def test_headline_cpu_matches_the_system_user_idle_split_once_a_split_exists():
    cpu = Mock(side_effect=[
        SimpleNamespace(user=100, nice=0, system=50, idle=850),
        SimpleNamespace(user=130, nice=0, system=60, idle=910),
    ])
    disk_io = Mock(side_effect=[SimpleNamespace(read_bytes=0, write_bytes=0)] * 2)
    service = make_service(Mock(side_effect=[10.0, 12.0]), cpu, disk_io)

    assert service.snapshot()["cpu_percent"] == 20
    second = service.snapshot()
    assert second["cpu_breakdown"]["idle_percent"] == 60.0
    assert second["cpu_percent"] == 40.0


def test_snapshot_detail_failures_become_null_without_breaking_the_snapshot():
    broken = Mock(side_effect=OSError("unavailable"))
    service = make_service(
        Mock(side_effect=[10.0]),
        broken,
        Mock(side_effect=OSError()),
        memory_breakdown_provider=broken,
        pressure_provider=broken,
        swap_provider=broken,
        load_provider=broken,
        boot_time_provider=broken,
    )
    result = service.snapshot()
    assert result["memory"] is None and result["memory_pressure"] is None and result["swap"] is None
    assert result["cpu_breakdown"] is None and result["load_average"] is None and result["uptime_seconds"] is None
    assert result["disk"]["read_bytes_per_second"] is None
    assert result["cpu_percent"] == 20


def test_snapshot_rejects_invalid_optional_details_and_counters():
    times = Mock(side_effect=[SimpleNamespace(user=1, nice=0, system=1, idle=1)] * 2)
    disk_io = Mock(side_effect=[SimpleNamespace(read_bytes="bad", write_bytes=1)] * 2)
    counters = Mock(side_effect=[
        {"en0": SimpleNamespace(bytes_sent=1, bytes_recv=1)},
        {},
    ])
    interfaces = Mock(return_value={"en0": SimpleNamespace(isup=True)})
    service = make_service(
        Mock(side_effect=[10.0, 12.0]),
        times,
        disk_io,
        network_provider=counters,
        interface_provider=interfaces,
        swap_provider=lambda: SimpleNamespace(used=0, total=100, percent=float("nan")),
        load_provider=lambda: (1.0, -1.0, 2.0),
    )
    service.snapshot()
    result = service.snapshot()
    assert result["swap"] is None
    assert result["load_average"] is None
    assert result["disk"]["read_bytes_per_second"] is None
    assert result["reasons"]["network"] == "Network information unavailable."


def test_disk_rates_are_none_after_a_counter_reset():
    cpu = Mock(side_effect=[SimpleNamespace(user=1, nice=0, system=1, idle=1)] * 2)
    disk_io = Mock(side_effect=[
        SimpleNamespace(read_bytes=5000, write_bytes=5000),
        SimpleNamespace(read_bytes=10, write_bytes=10),
    ])
    service = make_service(Mock(side_effect=[10.0, 12.0]), cpu, disk_io)
    service.snapshot()
    result = service.snapshot()
    assert result["disk"]["read_bytes_per_second"] is None
    assert result["disk"]["write_bytes_per_second"] is None


def test_gpu_info_and_bluetooth_and_battery_extras_are_parsed_and_bounded(monkeypatch):
    import plistlib, sys
    from officekit.engines.engine_system_metrics import macos_battery_metrics, macos_bluetooth_batteries, macos_gpu_info
    monkeypatch.setattr(sys, "platform", "darwin")
    gpu = macos_gpu_info(lambda *a, **k: SimpleNamespace(stdout=chr(34) + "model" + chr(34) + " = " + chr(34) + "Apple M1 Max" + chr(34) + chr(10) + chr(34) + "gpu-core-count" + chr(34) + " = 24" + chr(10)))
    assert gpu == {"model": "Apple M1 Max", "core_count": 24}
    assert macos_gpu_info(lambda *a, **k: SimpleNamespace(stdout="nothing")) is None
    devices = [{"Product": "Trackpad", "BatteryPercent": 92}, {"Product": "Bad", "BatteryPercent": 400}, {"BatteryPercent": 5}]
    assert macos_bluetooth_batteries(lambda *a, **k: SimpleNamespace(stdout=plistlib.dumps(devices))) == [{"name": "Trackpad", "percent": 92}]
    record = {"IsCharging": True, "Voltage": 12000, "Amperage": 2**64 - 1500, "Temperature": 3050, "AdapterDetails": {"Watts": 96}, "CycleCount": 3}
    def run(command, **_kwargs):
        return SimpleNamespace(stdout=plistlib.dumps([record]) if command[0].endswith("ioreg") else "Now drawing from AC Power" + chr(10) + "-InternalBattery-0 80%; charging; 1:00 remaining" + chr(10))
    battery = macos_battery_metrics(run)
    assert (battery["adapter_watts"], battery["voltage_v"], battery["current_a"], battery["power_w"], battery["temperature_c"]) == (96, 12.0, -1.5, -18.0, 30.5)
