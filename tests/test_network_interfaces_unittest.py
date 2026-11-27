import socket
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import app
from officekit.engines.engine_network_interfaces import NetworkInterfaceError, NetworkInterfaceService


def make_service(addresses, stats=None):
    return NetworkInterfaceService(
        address_provider=lambda: addresses,
        stats_provider=lambda: stats or {},
    )


@pytest.fixture
def address_fixture():
    return {
        "en0": [
            SimpleNamespace(family=socket.AF_INET, address="192.168.1.20", netmask="255.255.255.0", broadcast="192.168.1.255"),
            SimpleNamespace(family=socket.AF_INET6, address="fe80::1%en0", netmask="ffff:ffff:ffff:ffff::", broadcast=None),
            SimpleNamespace(family=18, address="aa:bb:cc:dd:ee:ff", netmask=None, broadcast=None),
        ],
        "utun4": [SimpleNamespace(family=socket.AF_INET6, address="fd00::3", netmask="ffff:ffff:ffff:ffff::", broadcast=None)],
        "lo0": [SimpleNamespace(family=socket.AF_INET, address="127.0.0.1", netmask="255.0.0.0", broadcast=None)],
        "offline0": [],
    }


def test_interface_list_hides_addresses_by_default_without_exposing_link_layer(address_fixture):
    service = make_service(address_fixture, {"en0": SimpleNamespace(isup=True, speed=1000), "offline0": SimpleNamespace(isup=False, speed=0)})

    result = service.list_interfaces()

    assert result["include_addresses"] is False
    assert result["privacy_notice"] == "Local IP addresses are hidden. Include addresses only when you want to view them."
    assert [interface["name"] for interface in result["interfaces"]] == ["en0", "lo0", "offline0", "utun4"]
    assert result["interfaces"][0] == {
        "name": "en0", "is_up": True, "address_count": 2, "addresses_hidden": True, "addresses": [],
    }
    assert result["interfaces"][2]["is_up"] is False
    assert all("aa:bb:cc:dd:ee:ff" not in str(interface) for interface in result["interfaces"])


def test_explicit_opt_in_returns_only_ipv4_ipv6_and_preserves_ipv6_scope(address_fixture):
    result = make_service(address_fixture).list_interfaces(include_addresses=True)

    ethernet = result["interfaces"][0]
    assert result["privacy_notice"] == "Contains local IP addresses. Copy or export only the addresses you select."
    assert ethernet["addresses_hidden"] is False
    assert ethernet["addresses"] == [
        {"family": "IPv4", "address": "192.168.1.20", "netmask": "255.255.255.0", "broadcast": "192.168.1.255"},
        {"family": "IPv6", "address": "fe80::1%en0", "netmask": "ffff:ffff:ffff:ffff::", "broadcast": None},
    ]


def test_unknown_address_families_are_omitted(address_fixture):
    result = make_service(address_fixture).list_interfaces(include_addresses=True)

    assert all(item["family"] in {"IPv4", "IPv6"} for row in result["interfaces"] for item in row["addresses"])
    assert result["interfaces"][1]["addresses"] == [{
        "family": "IPv4", "address": "127.0.0.1", "netmask": "255.0.0.0", "broadcast": None,
    }]


def test_interface_address_lists_are_bounded_and_report_truncation():
    addresses = {f"if{index:02d}": [] for index in range(65)}
    addresses["if00"] = [SimpleNamespace(family=socket.AF_INET, address=f"192.0.2.{index + 1}", netmask=None, broadcast=None) for index in range(34)]

    result = make_service(addresses).list_interfaces(include_addresses=True)

    assert len(result["interfaces"]) == 64
    assert result["truncated"] is True
    assert len(result["interfaces"][0]["addresses"]) == 32


def test_invalid_provider_entries_are_skipped_and_marked_truncated():
    result = make_service({"": [], "valid0": [SimpleNamespace(family=socket.AF_INET, address="not-an-ip", netmask=None, broadcast=None)]}).list_interfaces()

    assert result["interfaces"] == [{
        "name": "valid0", "is_up": None, "address_count": 0, "addresses_hidden": False, "addresses": [],
    }]
    assert result["truncated"] is True


@pytest.mark.parametrize("include_addresses", ["yes", 1, None])
def test_rejects_non_boolean_privacy_choice(include_addresses, address_fixture):
    with pytest.raises(NetworkInterfaceError, match="boolean"):
        make_service(address_fixture).list_interfaces(include_addresses=include_addresses)


def test_provider_failure_returns_safe_network_interface_error():
    service = NetworkInterfaceService(address_provider=lambda: (_ for _ in ()).throw(OSError("private path detail")))

    with pytest.raises(NetworkInterfaceError, match="unavailable") as error:
        service.list_interfaces()

    assert "private path detail" not in str(error.value)


def test_non_mapping_address_provider_is_reported_as_unavailable():
    service = NetworkInterfaceService(address_provider=lambda: [])

    with pytest.raises(NetworkInterfaceError, match="unavailable"):
        service.list_interfaces()


def test_stats_failure_does_not_hide_addresses_or_fail_the_report(address_fixture):
    service = NetworkInterfaceService(
        address_provider=lambda: address_fixture,
        stats_provider=lambda: (_ for _ in ()).throw(OSError("stats unavailable")),
    )

    result = service.list_interfaces(include_addresses=True)

    assert all(interface["is_up"] is None for interface in result["interfaces"])


def test_non_mapping_stats_and_non_sequence_addresses_are_handled():
    service = NetworkInterfaceService(
        address_provider=lambda: {"bad0": object(), 7: [], "good0": []},
        stats_provider=lambda: [],
    )

    result = service.list_interfaces()

    assert [interface["name"] for interface in result["interfaces"]] == ["bad0", "good0"]
    assert result["truncated"] is True


@pytest.mark.parametrize(
    ("family", "address"),
    [
        (socket.AF_INET, "2001:db8::1"),
        (socket.AF_INET6, "fe80::1%bad scope"),
        (socket.AF_INET, "192.0.2.1%en0"),
        (socket.AF_INET, "x" * 129),
        (socket.AF_INET, 12),
    ],
)
def test_invalid_ip_addresses_are_skipped_and_mark_report_incomplete(family, address):
    service = make_service({"en0": [SimpleNamespace(family=family, address=address, netmask="bad\nmask", broadcast=7)]})

    result = service.list_interfaces(include_addresses=True)

    assert result["interfaces"][0]["address_count"] == 0
    assert result["truncated"] is True


def test_optional_interface_fields_are_sanitized_and_stats_are_typed():
    addresses = {"en0": [SimpleNamespace(
        family=socket.AF_INET, address="192.0.2.1", netmask="x" * 129, broadcast="192.0.2.255",
    )]}
    service = make_service(addresses, {"en0": SimpleNamespace(isup=1)})

    result = service.list_interfaces(include_addresses=True)

    assert result["interfaces"][0]["is_up"] is None
    assert result["interfaces"][0]["addresses"][0]["netmask"] is None
    assert result["interfaces"][0]["addresses"][0]["broadcast"] == "192.0.2.255"


@pytest.mark.parametrize("value", [7, "x" * 129, "line\nbreak"])
def test_optional_ip_fields_reject_oversized_non_text_and_controls(value):
    assert NetworkInterfaceService._optional_address_field(value) is None


def test_api_returns_hidden_addresses_by_default():
    with patch("app.network_interface_service.list_interfaces", return_value={
        "include_addresses": False, "privacy_notice": "Local IP addresses are hidden. Include addresses only when you want to view them.",
        "interfaces": [{"name": "en0", "is_up": True, "address_count": 1, "addresses_hidden": True, "addresses": []}],
        "truncated": False,
    }):
        response = TestClient(app).post("/api/network/interfaces", json={})

    assert response.status_code == 200
    assert response.json()["interfaces"][0]["addresses"] == []


def test_api_allows_explicit_address_opt_in():
    with patch("app.network_interface_service.list_interfaces", return_value={
        "include_addresses": True, "privacy_notice": "Contains local IP addresses. Copy or export only the addresses you select.",
        "interfaces": [{
            "name": "en0", "is_up": True, "address_count": 1, "addresses_hidden": False,
            "addresses": [{"family": "IPv4", "address": "192.168.1.20", "netmask": None, "broadcast": None}],
        }], "truncated": False,
    }):
        response = TestClient(app).post("/api/network/interfaces", json={"include_addresses": True})

    assert response.status_code == 200
    assert response.json()["interfaces"][0]["addresses"][0]["address"] == "192.168.1.20"


@pytest.mark.parametrize("body", [{"include_addresses": "true"}, {"include_addresses": 1}, {"extra": True}])
def test_api_rejects_invalid_interface_requests(body):
    response = TestClient(app).post("/api/network/interfaces", json=body)
    assert response.status_code == 422
    assert "input" not in response.text


def test_api_maps_provider_failure_to_safe_service_unavailable():
    with patch("app.network_interface_service.list_interfaces", side_effect=NetworkInterfaceError("private details")):
        response = TestClient(app).post("/api/network/interfaces", json={})

    assert response.status_code == 503
    assert "private details" not in response.text
