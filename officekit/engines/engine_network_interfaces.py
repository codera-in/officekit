"""Bounded local network-interface inventory with address opt-in."""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable, Mapping
from typing import Any

import psutil


MAX_INTERFACES = 64
MAX_ADDRESSES_PER_INTERFACE = 32
_SAFE_SCOPE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class NetworkInterfaceError(RuntimeError):
    """A local network-interface query failed safely."""


class NetworkInterfaceService:
    def __init__(
        self,
        *,
        address_provider: Callable[[], Mapping[str, Any]] | None = None,
        stats_provider: Callable[[], Mapping[str, Any]] | None = None,
    ):
        self._address_provider = address_provider or psutil.net_if_addrs
        self._stats_provider = stats_provider or psutil.net_if_stats

    def list_interfaces(self, *, include_addresses: bool = False) -> dict:
        if not isinstance(include_addresses, bool):
            raise NetworkInterfaceError("Address visibility choice must be a boolean.")
        try:
            address_map = self._address_provider()
        except Exception as error:
            raise NetworkInterfaceError("Network interface information is unavailable.") from error
        if not isinstance(address_map, Mapping):
            raise NetworkInterfaceError("Network interface information is unavailable.")
        try:
            stats_map = self._stats_provider()
        except Exception:
            stats_map = {}
        if not isinstance(stats_map, Mapping):
            stats_map = {}

        names = sorted(address_map, key=lambda item: (not isinstance(item, str), item.casefold() if isinstance(item, str) else repr(item)))
        truncated = len(names) > MAX_INTERFACES
        interfaces = []
        for name in names[:MAX_INTERFACES]:
            if not isinstance(name, str) or not name or len(name) > 128 or any(ord(char) < 32 for char in name):
                truncated = True
                continue
            raw_addresses = address_map[name]
            if not isinstance(raw_addresses, (list, tuple)):
                truncated = True
                raw_addresses = ()
            parsed_addresses = []
            for item in raw_addresses:
                parsed = self._parse_ip_address(item)
                if parsed is None:
                    if self._is_ip_family(getattr(item, "family", None)):
                        truncated = True
                    continue
                parsed_addresses.append(parsed)
            if len(parsed_addresses) > MAX_ADDRESSES_PER_INTERFACE:
                truncated = True
            visible_addresses = parsed_addresses[:MAX_ADDRESSES_PER_INTERFACE] if include_addresses else []
            stats = stats_map.get(name)
            is_up = getattr(stats, "isup", None)
            interfaces.append({
                "name": name,
                "is_up": is_up if isinstance(is_up, bool) else None,
                "address_count": len(parsed_addresses),
                "addresses_hidden": bool(parsed_addresses) and not include_addresses,
                "addresses": visible_addresses,
            })
        return {
            "include_addresses": include_addresses,
            "privacy_notice": (
                "Contains local IP addresses. Copy or export only the addresses you select."
                if include_addresses
                else "Local IP addresses are hidden. Include addresses only when you want to view them."
            ),
            "interfaces": interfaces,
            "truncated": truncated,
        }

    @staticmethod
    def _is_ip_family(family: object) -> bool:
        return family in (socket.AF_INET, socket.AF_INET6)

    @classmethod
    def _parse_ip_address(cls, item: object) -> dict | None:
        family = getattr(item, "family", None)
        raw = getattr(item, "address", None)
        if not cls._is_ip_family(family) or not isinstance(raw, str) or not raw or len(raw) > 128:
            return None
        address, separator, scope = raw.partition("%")
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            return None
        expected_version = 4 if family == socket.AF_INET else 6
        if parsed.version != expected_version or (separator and (expected_version != 6 or not _SAFE_SCOPE.fullmatch(scope))):
            return None
        rendered = str(parsed) + (f"%{scope}" if separator else "")
        return {
            "family": f"IPv{expected_version}",
            "address": rendered,
            "netmask": cls._optional_address_field(getattr(item, "netmask", None)),
            "broadcast": cls._optional_address_field(getattr(item, "broadcast", None)),
        }

    @staticmethod
    def _optional_address_field(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or len(value) > 128 or any(ord(char) < 32 for char in value):
            return None
        return value
