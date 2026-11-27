from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from officekit.engines.engine_system_metrics import (
    DATA_VOLUME_PATH,
    SystemMetricsService,
    data_volume_path,
    macos_memory_used_percent,
)

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                     4214.
Pages active:                                 428285.
Pages inactive:                               421141.
File-backed pages:                            297675.
"""
TOTAL = 2_097_152 * 16384


def runner(output):
    return Mock(return_value=SimpleNamespace(stdout=output))


def test_memory_in_use_excludes_free_and_file_backed_pages():
    assert macos_memory_used_percent(run=runner(VM_STAT), total_bytes=TOTAL) == 85.6


@pytest.mark.parametrize(
    "output",
    ["", "page size of 16384 bytes\nPages free: 1.", VM_STAT.replace("Pages free", "Pages gone"), "page size of x bytes"],
)
def test_memory_in_use_is_none_when_vm_stat_cannot_be_parsed(output):
    assert macos_memory_used_percent(run=runner(output), total_bytes=TOTAL) is None


def test_memory_in_use_is_none_when_vm_stat_fails():
    assert macos_memory_used_percent(run=Mock(side_effect=OSError("missing")), total_bytes=TOTAL) is None


def test_memory_in_use_is_clamped_to_a_percentage():
    over = VM_STAT.replace("Pages free:                                     4214.", "Pages free: -9999999.").replace("297675", "0")
    assert macos_memory_used_percent(run=runner(over), total_bytes=TOTAL) == 100.0
    under = VM_STAT.replace("297675", "99999999")
    assert macos_memory_used_percent(run=runner(under), total_bytes=TOTAL) == 0.0


def test_data_volume_is_used_when_present_and_root_otherwise():
    assert data_volume_path(isdir=lambda path: True) == DATA_VOLUME_PATH
    assert data_volume_path(isdir=lambda path: False) == "/"


def make(memory_provider, disk_path="/System/Volumes/Data"):
    resource = Mock()
    resource.snapshot.return_value = {"cpu_percent": 20, "memory_percent": 40}
    disk = Mock(return_value=SimpleNamespace(percent=67))
    service = SystemMetricsService(
        resource_service=resource,
        disk_provider=disk,
        network_provider=Mock(side_effect=OSError()),
        interface_provider=Mock(),
        monotonic_clock=lambda: 10.0,
        wall_clock=lambda: 0,
        memory_percent_provider=memory_provider,
        disk_path=disk_path,
    )
    return service, disk


def test_snapshot_prefers_the_monitor_style_memory_figure_and_the_data_volume():
    service, disk = make(lambda: 85.6)
    result = service.snapshot()
    assert result["memory_percent"] == 85.6
    assert result["storage_percent"] == 67
    disk.assert_called_once_with("/System/Volumes/Data")


@pytest.mark.parametrize("provider_value", [None, float("nan"), 120, -1])
def test_snapshot_keeps_the_resource_memory_figure_when_the_override_is_unusable(provider_value):
    service, _ = make(lambda: provider_value)
    assert service.snapshot()["memory_percent"] == 40
