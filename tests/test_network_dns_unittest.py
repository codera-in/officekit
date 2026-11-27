from types import SimpleNamespace
import socketserver
import threading
from unittest.mock import Mock, patch

import dns.exception
import dns.message
import dns.name
import dns.rdatatype
import dns.rrset
import dns.resolver
import pytest
from fastapi.testclient import TestClient

from app import app
from officekit.engines.engine_network_dns import DnsLookup, DnsLookupError


def make_engine():
    return DnsLookup(resolver_factory=Mock())


@pytest.mark.parametrize(
    ("record_type", "records", "expected"),
    [
        ("A", ["192.0.2.1", "198.51.100.2"], ["192.0.2.1", "198.51.100.2"]),
        ("AAAA", ["2001:db8::1"], ["2001:db8::1"]),
        ("CNAME", [SimpleNamespace(target="Edge.Example.Test.")], ["edge.example.test"]),
        ("NS", [SimpleNamespace(target="ns1.example.test."), SimpleNamespace(target="NS2.example.test.")], ["ns1.example.test", "ns2.example.test"]),
        ("MX", [SimpleNamespace(preference=10, exchange="mail.example.test."), SimpleNamespace(preference=20, exchange="backup.example.test.")], [
            {"preference": 10, "exchange": "mail.example.test"},
            {"preference": 20, "exchange": "backup.example.test"},
        ]),
        ("TXT", [SimpleNamespace(strings=(b"hello ", b"world")), SimpleNamespace(strings=(b"officekit",))], ["hello world", "officekit"]),
    ],
)
def test_lookup_formats_supported_records(record_type, records, expected):
    resolver = Mock()
    resolver.resolve.return_value = records
    engine = DnsLookup(resolver_factory=lambda: resolver)

    with patch("officekit.engines.engine_network_dns.time.perf_counter", side_effect=[1.0, 1.0]):
        result = engine.lookup("Example.Test", record_type=record_type)

    assert result == {
        "hostname": "example.test",
        "record_type": record_type,
        "status": "success",
        "records": expected,
        "truncated": False,
        "nameserver": None,
        "duration_ms": 0,
    }
    resolver.resolve.assert_called_once_with("example.test.", record_type, lifetime=3.0, search=False)


def test_custom_resolver_is_validated_and_applied():
    resolver = Mock()
    resolver.resolve.side_effect = lambda *args, **kwargs: (
        ["192.0.2.8"] if resolver.nameservers == ["2001:db8::53"] else []
    )
    engine = DnsLookup(resolver_factory=lambda: resolver)

    result = engine.lookup("officekit.app", nameserver="2001:db8::53", timeout_seconds=1.25)

    assert result["nameserver"] == "2001:db8::53"
    resolver.nameservers = ["2001:db8::53"]
    resolver.lifetime = 1.25
    resolver.resolve.assert_called_once_with("officekit.app.", "A", lifetime=1.25, search=False)


@pytest.mark.parametrize(
    ("record_type", "answer_text", "expected"),
    [
        ("A", "192.0.2.8", ["192.0.2.8"]),
        ("AAAA", "2001:db8::8", ["2001:db8::8"]),
        ("MX", "10 mail.example.test.\n20 backup.example.test.", [
            {"preference": 10, "exchange": "mail.example.test"},
            {"preference": 20, "exchange": "backup.example.test"},
        ]),
        ("TXT", '"officekit local resolver"', ["officekit local resolver"]),
    ],
)
def test_custom_resolver_queries_local_server_for_supported_record_types(record_type, answer_text, expected):
    observed_types = []

    class DnsHandler(socketserver.BaseRequestHandler):
        def handle(self):
            packet, sock = self.request
            query = dns.message.from_wire(packet)
            question = query.question[0]
            observed_types.append(question.rdtype)
            response = dns.message.make_response(query)
            response.answer.append(
                dns.rrset.from_text(
                    question.name.to_text(), 30, "IN", record_type, *answer_text.splitlines()
                )
            )
            sock.sendto(response.to_wire(), self.client_address)

    with socketserver.ThreadingUDPServer(("127.0.0.1", 0), DnsHandler) as server:
        server.daemon_threads = True
        resolver_port = server.server_address[1]
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def local_resolver():
            resolver = dns.resolver.Resolver(configure=False)
            resolver.port = resolver_port
            return resolver

        try:
            result = DnsLookup(resolver_factory=local_resolver).lookup(
                "example.test", record_type=record_type, nameserver="127.0.0.1", timeout_seconds=1
            )
        finally:
            server.shutdown()
            worker.join(timeout=1)

    assert result["status"] == "success"
    assert result["nameserver"] == "127.0.0.1"
    assert result["records"] == expected
    assert observed_types == [dns.rdatatype.from_text(record_type)]


@pytest.mark.parametrize(
    ("record_type", "answer_text", "expected"),
    [
        ("A", "192.0.2.8", ["192.0.2.8"]),
        ("AAAA", "2001:db8::8", ["2001:db8::8"]),
        ("MX", "10 mail.example.test.\n20 backup.example.test.", [
            {"preference": 10, "exchange": "mail.example.test"},
            {"preference": 20, "exchange": "backup.example.test"},
        ]),
        ("TXT", '"officekit local resolver"', ["officekit local resolver"]),
    ],
)
def test_api_returns_real_records_from_a_loopback_resolver(
    monkeypatch, record_type, answer_text, expected
):
    observed_types = []

    class DnsHandler(socketserver.BaseRequestHandler):
        def handle(self):
            packet, sock = self.request
            query = dns.message.from_wire(packet)
            question = query.question[0]
            observed_types.append(question.rdtype)
            response = dns.message.make_response(query)
            response.answer.append(
                dns.rrset.from_text(
                    question.name.to_text(), 30, "IN", record_type, *answer_text.splitlines()
                )
            )
            sock.sendto(response.to_wire(), self.client_address)

    with socketserver.ThreadingUDPServer(("127.0.0.1", 0), DnsHandler) as server:
        server.daemon_threads = True
        resolver_port = server.server_address[1]
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def local_resolver():
            resolver = dns.resolver.Resolver(configure=False)
            resolver.port = resolver_port
            return resolver

        monkeypatch.setattr(
            "app.dns_lookup_service",
            DnsLookup(resolver_factory=local_resolver),
        )
        try:
            response = TestClient(app).post(
                "/api/network/dns",
                json={
                    "hostname": "example.test",
                    "record_type": record_type,
                    "nameserver": "127.0.0.1",
                    "timeout_seconds": 1,
                },
            )
        finally:
            server.shutdown()
            worker.join(timeout=1)

    assert response.status_code == 200, response.text
    assert response.json()["hostname"] == "example.test"
    assert response.json()["record_type"] == record_type
    assert response.json()["status"] == "success"
    assert response.json()["records"] == expected
    assert response.json()["nameserver"] == "127.0.0.1"
    assert observed_types == [dns.rdatatype.from_text(record_type)]


def test_hostname_normalizes_idn_and_one_trailing_root_dot():
    resolver = Mock()
    resolver.resolve.return_value = ["192.0.2.4"]
    engine = DnsLookup(resolver_factory=lambda: resolver)

    result = engine.lookup("BÜCHER.de.")

    assert result["hostname"] == "xn--bcher-kva.de"
    resolver.resolve.assert_called_once_with("xn--bcher-kva.de.", "A", lifetime=3.0, search=False)


@pytest.mark.parametrize("encoded", ["x" * 254, "bad_label"])
def test_rejects_overlong_or_invalid_ascii_result_from_idna(encoded):
    with patch("officekit.engines.engine_network_dns.idna.encode", return_value=encoded.encode("ascii")):
        with pytest.raises(DnsLookupError, match="hostname"):
            make_engine().lookup("example.test")


@pytest.mark.parametrize(
    "hostname", ["", "bad host", "-invalid.test", "a..test", ".example.test", "example.test..", "x" * 254,
                 "example.test;id", "bad_name.test"],
)
def test_rejects_invalid_hostnames(hostname):
    with pytest.raises(DnsLookupError, match="hostname"):
        make_engine().lookup(hostname)


@pytest.mark.parametrize("record_type", ["PTR", "SOA", "ANY", "a", "TXT;whoami"])
def test_rejects_unsupported_record_types(record_type):
    with pytest.raises(DnsLookupError, match="record type"):
        make_engine().lookup("example.test", record_type=record_type)


@pytest.mark.parametrize("nameserver", ["localhost", "dns.example.test", "127.0.0.1;id", ""])
def test_rejects_non_ip_nameserver(nameserver):
    with pytest.raises(DnsLookupError, match="(?i)nameserver"):
        make_engine().lookup("example.test", nameserver=nameserver)


def test_rejects_non_string_nameserver():
    with pytest.raises(DnsLookupError, match="Nameserver"):
        make_engine().lookup("example.test", nameserver=53)


@pytest.mark.parametrize("timeout", [0, -1, 0.1, 10.1, float("nan"), float("inf")])
def test_rejects_out_of_range_or_non_finite_timeouts(timeout):
    with pytest.raises(DnsLookupError, match="timeout"):
        make_engine().lookup("example.test", timeout_seconds=timeout)


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (dns.resolver.NXDOMAIN(), "nxdomain"),
        (dns.resolver.NoAnswer(), "no_records"),
        (dns.exception.Timeout(), "timed_out"),
        (dns.resolver.NoNameservers(), "resolver_error"),
    ],
)
def test_lookup_returns_safe_dns_failure_states(failure, status):
    resolver = Mock()
    resolver.resolve.side_effect = failure
    engine = DnsLookup(resolver_factory=lambda: resolver)

    result = engine.lookup("missing.example.test")

    assert result["status"] == status
    assert result["records"] == []


def test_lookup_does_not_leak_unexpected_resolver_error():
    resolver = Mock()
    resolver.resolve.side_effect = RuntimeError("secret resolver detail")
    engine = DnsLookup(resolver_factory=lambda: resolver)

    with pytest.raises(DnsLookupError, match="DNS lookup failed") as caught:
        engine.lookup("example.test")

    assert "secret resolver detail" not in str(caught.value)


def test_lookup_caps_record_lists_and_marks_truncation():
    resolver = Mock()
    resolver.resolve.return_value = ["192.0.2.1"] * 101
    engine = DnsLookup(resolver_factory=lambda: resolver)

    result = engine.lookup("example.test")

    assert len(result["records"]) == 100
    assert result["truncated"] is True


def test_record_formatter_rejects_address_family_mismatch():
    with pytest.raises(DnsLookupError, match="invalid address"):
        DnsLookup._format_record("A", "2001:db8::1")

    with pytest.raises(DnsLookupError, match="invalid address"):
        DnsLookup._format_record("AAAA", "192.0.2.1")


def test_record_formatter_rejects_unknown_type():
    with pytest.raises(DnsLookupError, match="Unsupported"):
        DnsLookup._format_record("PTR", "example.test")


def test_api_returns_typed_dns_result():
    with patch("app.dns_lookup_service.lookup", return_value={
        "hostname": "example.test", "record_type": "A", "status": "success",
        "records": ["192.0.2.1"], "nameserver": None, "duration_ms": 1,
        "truncated": False,
    }):
        response = TestClient(app).post("/api/network/dns", json={"hostname": "Example.Test"})

    assert response.status_code == 200
    assert response.json()["records"] == ["192.0.2.1"]


def test_api_maps_unexpected_dns_failures_to_a_safe_service_error():
    with patch("app.dns_lookup_service.lookup", side_effect=DnsLookupError("private failure data")):
        response = TestClient(app).post("/api/network/dns", json={"hostname": "example.test"})

    assert response.status_code == 503
    assert "private failure data" not in response.text


@pytest.mark.parametrize(
    "body",
    [
        {"hostname": "example.test", "extra": True},
        {"hostname": "bad host"},
        {"hostname": "example.test", "record_type": "PTR"},
        {"hostname": "example.test", "nameserver": "dns.example.test"},
        {"hostname": "example.test", "timeout_seconds": 0},
        {"hostname": "example.test", "timeout_seconds": 12},
    ],
)
def test_api_rejects_invalid_dns_requests(body):
    response = TestClient(app).post("/api/network/dns", json=body)
    assert response.status_code == 422
    assert "input" not in response.text


def _txt(*parts):
    return SimpleNamespace(strings=tuple(part.encode() for part in parts))


def test_spf_keeps_only_spf_records_from_the_domain_txt_set():
    resolver = Mock()
    resolver.resolve.return_value = [_txt("google-site-verification=abc"), _txt("v=spf1 include:_spf.google.com ~all")]
    result = DnsLookup(resolver_factory=lambda: resolver).lookup("Example.Test", record_type="SPF")

    assert result["record_type"] == "SPF"
    assert result["records"] == ["v=spf1 include:_spf.google.com ~all"]
    resolver.resolve.assert_called_once_with("example.test.", "TXT", lifetime=3.0, search=False)


def test_spf_with_no_spf_record_reports_no_records():
    resolver = Mock()
    resolver.resolve.return_value = [_txt("v=spf10 not-spf")]
    result = DnsLookup(resolver_factory=lambda: resolver).lookup("example.test", record_type="SPF")

    assert (result["status"], result["records"]) == ("no_records", [])


def test_dkim_queries_the_selector_under_domainkey_and_keeps_key_records():
    resolver = Mock()
    resolver.resolve.return_value = [_txt("v=DKIM1; k=rsa; p=", "MIIB"), _txt("unrelated text")]
    result = DnsLookup(resolver_factory=lambda: resolver).lookup("Example.Test", record_type="DKIM", selector="Google")

    assert result["hostname"] == "example.test"
    assert result["records"] == ["v=DKIM1; k=rsa; p=MIIB"]
    resolver.resolve.assert_called_once_with("google._domainkey.example.test.", "TXT", lifetime=3.0, search=False)


@pytest.mark.parametrize("selector", [None, "", "a b", "bad;sel", "-x", "x" * 64, "g..x"])
def test_dkim_requires_a_valid_selector(selector):
    with pytest.raises(DnsLookupError, match="selector"):
        make_engine().lookup("example.test", record_type="DKIM", selector=selector)


def test_selector_is_rejected_for_other_record_types():
    with pytest.raises(DnsLookupError, match="selector"):
        make_engine().lookup("example.test", record_type="TXT", selector="google")


def test_api_requires_a_dkim_selector_and_rejects_a_stray_one():
    client = TestClient(app)
    assert client.post("/api/network/dns", json={"hostname": "example.test", "record_type": "DKIM"}).status_code == 422
    assert client.post("/api/network/dns", json={"hostname": "example.test", "record_type": "TXT", "selector": "google"}).status_code == 422
    assert client.post("/api/network/dns", json={"hostname": "example.test", "record_type": "DKIM", "selector": "a;b"}).status_code == 422
