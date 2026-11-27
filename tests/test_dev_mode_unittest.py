"""Source-build switches and the local API's loopback Host check."""

import pytest
from fastapi.testclient import TestClient

import app as api
from officekit.engines.engine_api_security import (
    TRUSTED_API_HOSTS,
    dev_unlock_enabled,
    is_api_authorization_valid,
    resolve_api_auth_token,
)


def test_an_explicit_token_is_used_as_is():
    assert resolve_api_auth_token({"OFFICEKIT_API_TOKEN": "abc"}) == "abc"


def test_a_missing_token_fails_closed_with_an_unguessable_per_call_token():
    first = resolve_api_auth_token({})
    second = resolve_api_auth_token({})
    assert isinstance(first, str) and len(first) >= 32
    assert first != second
    assert not is_api_authorization_valid(None, first)
    assert not is_api_authorization_valid("Bearer anything", first)


@pytest.mark.parametrize("value", ["", "0", "true", "yes", " 1", "1 "])
def test_only_the_exact_value_1_opts_out_of_authentication(value):
    token = resolve_api_auth_token({"OFFICEKIT_DEV_NOAUTH": value})
    assert token is not None


def test_dev_noauth_opts_out_only_when_no_token_is_set():
    assert resolve_api_auth_token({"OFFICEKIT_DEV_NOAUTH": "1"}) is None
    assert resolve_api_auth_token({"OFFICEKIT_DEV_NOAUTH": "1", "OFFICEKIT_API_TOKEN": "abc"}) == "abc"


@pytest.mark.parametrize(
    ("environment", "expected"),
    [({}, False), ({"OFFICEKIT_DEV_UNLOCK": "1"}, True), ({"OFFICEKIT_DEV_UNLOCK": "true"}, False), ({"OFFICEKIT_DEV_UNLOCK": ""}, False)],
)
def test_dev_unlock_needs_the_exact_value_1(environment, expected):
    assert dev_unlock_enabled(environment) is expected


def test_the_trusted_hosts_are_loopback_names_only():
    assert set(TRUSTED_API_HOSTS) == {"127.0.0.1", "localhost", "testserver"}


@pytest.mark.parametrize("host", ["evil.example", "127.0.0.1.evil.example", "192.168.1.5", "0.0.0.0"])
def test_a_request_with_a_foreign_host_header_is_refused(host):
    client = TestClient(api.app)
    response = client.get("/api/license/status", headers={"Host": host})
    assert response.status_code == 400


@pytest.mark.parametrize("host", ["127.0.0.1:8123", "localhost:8123", "127.0.0.1"])
def test_loopback_host_headers_reach_the_app(host):
    client = TestClient(api.app)
    response = client.get("/api/license/status", headers={"Host": host})
    assert response.status_code != 400
