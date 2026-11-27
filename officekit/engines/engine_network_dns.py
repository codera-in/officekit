"""Bounded, local DNS queries for the OfficeKit network diagnostics tools."""

from __future__ import annotations

import ipaddress
import re
import time
from typing import Callable, Literal

import dns.exception
import dns.resolver
import idna


SUPPORTED_RECORD_TYPES = ("A", "AAAA", "CNAME", "NS", "MX", "TXT", "SPF", "DKIM")
MIN_TIMEOUT_SECONDS = 0.2
MAX_TIMEOUT_SECONDS = 5.0
MAX_RESPONSE_RECORDS = 100
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SELECTOR_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,61}[a-z0-9])?$")
_SPF = re.compile(r"^v=spf1(?:\s|$)", re.IGNORECASE)
_DKIM = re.compile(r"^\s*v=dkim1\b|(?:^|;)\s*p\s*=", re.IGNORECASE)
MAX_SELECTOR_LENGTH = 63


class DnsLookupError(ValueError):
    """Invalid DNS query parameters or an unexpected resolver failure."""


class DnsLookupInputError(DnsLookupError):
    """Invalid user-provided DNS query parameters."""


def normalize_dns_hostname(hostname: str) -> str:
    if not isinstance(hostname, str) or not hostname or len(hostname) > 1024:
        raise DnsLookupInputError("A valid DNS hostname is required.")
    if hostname.endswith(".."):
        raise DnsLookupInputError("A valid DNS hostname is required.")
    value = hostname[:-1] if hostname.endswith(".") else hostname
    if not value or len(value) > 253:
        raise DnsLookupInputError("A valid DNS hostname is required.")
    try:
        ascii_name = idna.encode(value, uts46=True, std3_rules=True).decode("ascii").lower()
    except (idna.IDNAError, UnicodeError) as error:
        raise DnsLookupInputError("A valid DNS hostname is required.") from error
    if len(ascii_name) > 253 or any(not _LABEL.fullmatch(label) for label in ascii_name.split(".")):
        raise DnsLookupInputError("A valid DNS hostname is required.")
    return ascii_name


def normalize_dkim_selector(selector: str | None) -> str:
    if not isinstance(selector, str) or not selector or len(selector) > MAX_SELECTOR_LENGTH:
        raise DnsLookupInputError("A DKIM selector is required.")
    value = selector.lower()
    if any(not _SELECTOR_LABEL.fullmatch(label) for label in value.split(".")):
        raise DnsLookupInputError("A DKIM selector is required.")
    return value


def normalize_nameserver(nameserver: str | None) -> str | None:
    if nameserver is None:
        return None
    if not isinstance(nameserver, str):
        raise DnsLookupInputError("Nameserver must be an IPv4 or IPv6 address.")
    try:
        return str(ipaddress.ip_address(nameserver))
    except ValueError as error:
        raise DnsLookupInputError("Nameserver must be an IPv4 or IPv6 address.") from error


class DnsLookup:
    def __init__(self, resolver_factory: Callable[[], dns.resolver.Resolver] = dns.resolver.Resolver):
        self._resolver_factory = resolver_factory

    def lookup(
        self,
        hostname: str,
        *,
        record_type: Literal["A", "AAAA", "CNAME", "NS", "MX", "TXT", "SPF", "DKIM"] = "A",
        nameserver: str | None = None,
        timeout_seconds: float = 3.0,
        selector: str | None = None,
    ) -> dict:
        name = normalize_dns_hostname(hostname)
        server = normalize_nameserver(nameserver)
        if record_type not in SUPPORTED_RECORD_TYPES:
            raise DnsLookupInputError("Unsupported DNS record type.")
        query_name = name
        if record_type == "DKIM":
            query_name = f"{normalize_dkim_selector(selector)}._domainkey.{name}"
            if len(query_name) > 253:
                raise DnsLookupInputError("A valid DNS hostname is required.")
        elif selector is not None:
            raise DnsLookupInputError("A selector is only used for DKIM lookups.")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not MIN_TIMEOUT_SECONDS <= timeout_seconds <= MAX_TIMEOUT_SECONDS
        ):
            raise DnsLookupInputError("DNS timeout must be between 0.2 and 5 seconds.")

        resolver = self._resolver_factory()
        resolver.lifetime = float(timeout_seconds)
        if server is not None:
            resolver.nameservers = [server]
        started = time.perf_counter()
        try:
            wire_type = "TXT" if record_type in ("SPF", "DKIM") else record_type
            answer = resolver.resolve(f"{query_name}.", wire_type, lifetime=float(timeout_seconds), search=False)
            formatted = [self._format_record(wire_type, item) for item in answer]
            if record_type == "SPF":
                formatted = [text for text in formatted if _SPF.match(text)]
            elif record_type == "DKIM":
                formatted = [text for text in formatted if _DKIM.search(text)]
            if record_type == "MX":
                formatted.sort(key=lambda record: record["preference"])
            truncated = len(formatted) > MAX_RESPONSE_RECORDS
            records = formatted[:MAX_RESPONSE_RECORDS]
            status = "success" if records else "no_records"
        except dns.resolver.NXDOMAIN:
            status, records, truncated = "nxdomain", [], False
        except dns.resolver.NoAnswer:
            status, records, truncated = "no_records", [], False
        except dns.exception.Timeout:
            status, records, truncated = "timed_out", [], False
        except dns.resolver.NoNameservers:
            status, records, truncated = "resolver_error", [], False
        except Exception as error:
            raise DnsLookupError("DNS lookup failed due to an unexpected resolver error.") from error
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        return {
            "hostname": name,
            "record_type": record_type,
            "status": status,
            "records": records,
            "truncated": truncated,
            "nameserver": server,
            "duration_ms": duration_ms,
        }

    @staticmethod
    def _format_record(record_type: str, item: object) -> str | dict:
        if record_type in ("A", "AAAA"):
            address = str(item)
            parsed = ipaddress.ip_address(address)
            if record_type == "A" and parsed.version != 4 or record_type == "AAAA" and parsed.version != 6:
                raise DnsLookupError("Resolver returned an invalid address record.")
            return str(parsed)
        if record_type in ("CNAME", "NS"):
            return str(getattr(item, "target")).rstrip(".").lower()
        if record_type == "MX":
            preference = int(getattr(item, "preference"))
            exchange = str(getattr(item, "exchange")).rstrip(".").lower()
            return {"preference": preference, "exchange": exchange}
        if record_type == "TXT":
            chunks = getattr(item, "strings")
            return b"".join(chunks).decode("utf-8", errors="replace")
        raise DnsLookupError("Unsupported DNS record type.")
