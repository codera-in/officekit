"""Shared fixtures for the Python test suite."""

import os

import pytest

# The suite drives the app in process with no desktop shell, so it opts out of the bearer token
# (a missing token otherwise fails closed). Set before app.py is imported.
os.environ.setdefault("OFFICEKIT_DEV_NOAUTH", "1")

from officekit.engines.engine_license_gate import GATE_STATE

# One hour is the longest lifetime the sidecar accepts over the wire; the whole suite runs well inside it.
TEST_ENTITLEMENT_SECONDS = 3600


@pytest.fixture(autouse=True, scope="session")
def session_entitlement():
    """Cover class- and module-level setup that calls the API before any per-test fixture runs."""
    GATE_STATE.install("paid", [], TEST_ENTITLEMENT_SECONDS)
    yield
    GATE_STATE.clear()


@pytest.fixture(autouse=True)
def installed_entitlement():
    """Paid routes need a live entitlement; install one through the real state object.

    The gate itself is never bypassed: tests that exercise the locked state clear the same
    state object (see test_license_gate_unittest.py). Reinstalled per test so a test that clears
    or expires the state cannot leak into the next one.
    """
    GATE_STATE.install("paid", [], TEST_ENTITLEMENT_SECONDS)
    yield GATE_STATE
    GATE_STATE.clear()
