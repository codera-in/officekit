from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app import app
from officekit.engines.engine_system_info import SystemInfoService, SystemInfoUnavailableError, SystemInfoUnsupportedError


def make_service(**overrides):
    providers = {
        "os_provider": lambda: "Darwin",
        "version_provider": lambda: "15.5.1",
        "architecture_provider": lambda: "arm64",
        "logical_cpu_provider": lambda: 8,
        "physical_cpu_provider": lambda: 4,
        "memory_provider": lambda: SimpleNamespace(total=16 * 1024**3),
    }
    providers.update(overrides)
    return SystemInfoService(**providers)


def test_system_report_contains_redacted_macos_identity_and_hardware_summary():
    result = make_service().snapshot()

    assert result == {
        "os_name": "macOS",
        "os_version": "15.5.1",
        "architecture": "arm64",
        "logical_cpu_count": 8,
        "physical_cpu_count": 4,
        "memory_total_bytes": 16 * 1024**3,
        "memory_total_gb": 16.0,
        "privacy_notice": "Contains macOS version, architecture, CPU core counts and memory capacity only. Device identifiers and host/account names are excluded.",
        "report_text": "Operating system: macOS 15.5.1\nArchitecture: arm64\nCPU cores: 4 physical, 8 logical\nMemory: 16 GB",
    }


def test_unknown_physical_cpu_count_is_reported_without_inventing_a_value():
    result = make_service(physical_cpu_provider=lambda: None).snapshot()

    assert result["physical_cpu_count"] is None
    assert "CPU cores: 8 logical" in result["report_text"]


def test_linux_is_explicitly_unsupported_until_an_adapter_is_verified():
    service = make_service(os_provider=lambda: "Linux")

    with pytest.raises(SystemInfoUnsupportedError, match="not supported"):
        service.snapshot()


@pytest.mark.parametrize("os_name", ["Windows", "FreeBSD", "", None])
def test_only_the_verified_macos_adapter_is_enabled(os_name):
    with pytest.raises(SystemInfoUnsupportedError, match="not supported"):
        make_service(os_provider=lambda: os_name).snapshot()


@pytest.mark.parametrize(
    "version",
    ["", "15.5.1\nsecret", "x" * 40, "15.5.1-beta", None],
)
def test_invalid_macos_versions_fail_closed(version):
    with pytest.raises(SystemInfoUnavailableError, match="unavailable"):
        make_service(version_provider=lambda: version).snapshot()


@pytest.mark.parametrize("architecture", ["arm64\nuser", "x" * 33, "", None])
def test_invalid_architecture_labels_fail_closed(architecture):
    with pytest.raises(SystemInfoUnavailableError, match="unavailable"):
        make_service(architecture_provider=lambda: architecture).snapshot()


@pytest.mark.parametrize(
    "count",
    [0, -1, 1025, True, 8.0, "8"],
)
def test_invalid_logical_cpu_counts_fail_closed(count):
    with pytest.raises(SystemInfoUnavailableError, match="unavailable"):
        make_service(logical_cpu_provider=lambda: count).snapshot()


@pytest.mark.parametrize("count", [0, -1, 9, True, 4.0, "4"])
def test_invalid_physical_cpu_counts_are_omitted(count):
    result = make_service(physical_cpu_provider=lambda: count).snapshot()

    assert result["physical_cpu_count"] is None
    assert "Physical CPU cores" not in result["report_text"]


def test_physical_cpu_probe_failure_omits_only_that_optional_field():
    result = make_service(physical_cpu_provider=Mock(side_effect=OSError("device-specific error"))).snapshot()

    assert result["physical_cpu_count"] is None
    assert "device-specific error" not in result["report_text"]


@pytest.mark.parametrize("total", [0, -1, 2**70 + 1, True, 16.0, "17179869184"])
def test_invalid_memory_capacity_fails_closed(total):
    with pytest.raises(SystemInfoUnavailableError, match="unavailable"):
        make_service(memory_provider=lambda: SimpleNamespace(total=total)).snapshot()


def test_provider_failures_are_redacted():
    service = make_service(memory_provider=Mock(side_effect=OSError("secret hardware detail")))

    with pytest.raises(SystemInfoUnavailableError, match="unavailable") as caught:
        service.snapshot()

    assert "secret hardware detail" not in str(caught.value)


def test_api_returns_shareable_report_without_host_or_account_identifiers():
    with patch("app.system_info_service.snapshot", return_value=make_service().snapshot()):
        response = TestClient(app).get("/api/system/info")

    assert response.status_code == 200
    body = response.json()
    assert body["report_text"].startswith("Operating system: macOS 15.5.1")
    assert not {"hostname", "username", "serial_number", "mac_address", "device_id"}.intersection(body)


def test_api_maps_unsupported_platform_to_501():
    with patch("app.system_info_service.snapshot", side_effect=SystemInfoUnsupportedError("private platform")):
        response = TestClient(app).get("/api/system/info")

    assert response.status_code == 501
    assert "private platform" not in response.text


def test_api_maps_provider_failure_to_safe_503():
    with patch("app.system_info_service.snapshot", side_effect=SystemInfoUnavailableError("private details")):
        response = TestClient(app).get("/api/system/info")

    assert response.status_code == 503
    assert "private details" not in response.text
