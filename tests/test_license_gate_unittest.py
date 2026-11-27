"""Sidecar licence gate: entitlement state, route classification, grant-guarded handoff."""

import json
import threading

import pytest
from fastapi.testclient import TestClient

import app as api
from officekit.engines import engine_license_gate as gate

API_TOKEN = "a" * 40
GRANT = "g" * 40
ACTIVATION_ID = "A" * 22


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def locked(monkeypatch):
    """Run with no entitlement installed, restoring the shared one afterwards."""
    state = gate.GATE_STATE
    saved = (state._entitlement, state._clock)
    state.clear()
    yield state
    state._entitlement, state._clock = saved


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv(gate.NATIVE_GRANT_ENVIRONMENT_KEY, GRANT)
    return TestClient(api.app, raise_server_exceptions=False)


def body(**overrides):
    value = {
        "activation_id": ACTIVATION_ID,
        "edition": "paid",
        "features": ["image.convert", "pdf.merge"],
        "valid_for_seconds": 1800,
    }
    value.update(overrides)
    return value


def put(client, payload, token=GRANT, headers=None):
    request_headers = dict(headers or {})
    if token is not None:
        request_headers[gate.NATIVE_GRANT_HEADER] = token
    return client.put("/api/license/entitlement", content=json.dumps(payload), headers={
        "content-type": "application/json", **request_headers,
    })


# ---------------------------------------------------------------- EntitlementState

def test_state_is_empty_until_installed_and_reports_edition_and_features():
    clock = FakeClock()
    state = gate.EntitlementState(clock=clock, wall_clock=lambda: 5000.0)
    assert state.current() is None
    state.install("paid", ["b", "a"], 60)
    current = state.current()
    assert current.edition == "paid"
    assert current.features == frozenset({"a", "b"})
    assert current.valid_until_epoch == 5060


def test_state_expires_on_the_monotonic_clock_and_forgets():
    clock = FakeClock()
    state = gate.EntitlementState(clock=clock, wall_clock=lambda: 5000.0)
    state.install("paid", [], 60)
    clock.now += 59.9
    assert state.current() is not None
    clock.now += 0.1
    assert state.current() is None
    assert state.current() is None


class FakeTimeModule:
    """Stands in for ``time``: only the clock ids passed in exist, as on a platform that lacks the rest."""

    def __init__(self, **clock_ids):
        for name, value in clock_ids.items():
            setattr(self, name, value)
        self.reads = []

    def monotonic(self):
        return -1.0

    def clock_gettime(self, clock_id):
        self.reads.append(clock_id)
        return 42.0 + clock_id


make_time_module = FakeTimeModule


def test_the_lifetime_clock_keeps_counting_through_system_sleep_on_macos():
    module = make_time_module(CLOCK_MONOTONIC_RAW=4)
    clock = gate.sleep_aware_clock(platform="darwin", time_module=module)
    assert clock() == 46.0
    assert module.reads == [4]


def test_the_lifetime_clock_uses_boottime_on_linux():
    module = make_time_module(CLOCK_BOOTTIME=7)
    clock = gate.sleep_aware_clock(platform="linux", time_module=module)
    assert clock() == 49.0
    assert module.reads == [7]


def test_the_lifetime_clock_falls_back_to_monotonic_where_no_sleep_aware_clock_exists():
    module = make_time_module()
    assert gate.sleep_aware_clock(platform="win32", time_module=module)() == -1.0
    assert gate.sleep_aware_clock(platform="darwin", time_module=module)() == -1.0


def test_the_default_lifetime_clock_is_sleep_aware_and_never_goes_backwards():
    state = gate.EntitlementState()
    first = state._clock()
    assert state._clock() >= first


def test_state_wall_clock_changes_do_not_extend_the_lifetime():
    clock = FakeClock()
    wall = {"now": 5000.0}
    state = gate.EntitlementState(clock=clock, wall_clock=lambda: wall["now"])
    state.install("paid", [], 60)
    wall["now"] += 10_000_000
    assert state.current() is not None
    clock.now += 61
    assert state.current() is None


def test_state_clear_is_idempotent_and_install_replaces():
    state = gate.EntitlementState(clock=FakeClock(), wall_clock=lambda: 0.0)
    state.clear()
    state.install("paid", ["a"], 60)
    state.install("paid", ["b"], 60)
    assert state.current().features == frozenset({"b"})
    state.clear()
    state.clear()
    assert state.current() is None


@pytest.mark.parametrize("seconds", [0, -1, True, 1.5, "60", float("nan")])
def test_state_rejects_non_positive_or_non_integer_lifetimes(seconds):
    state = gate.EntitlementState(clock=FakeClock(), wall_clock=lambda: 0.0)
    with pytest.raises(ValueError):
        state.install("paid", [], seconds)
    assert state.current() is None


def test_state_rejects_unknown_edition():
    state = gate.EntitlementState(clock=FakeClock(), wall_clock=lambda: 0.0)
    with pytest.raises(ValueError):
        state.install("free", [], 60)


def test_state_is_thread_safe_under_concurrent_install_and_read():
    state = gate.EntitlementState()
    errors = []

    def writer():
        for _ in range(300):
            state.install("paid", ["a"], 60)
            state.clear()

    def reader():
        for _ in range(300):
            try:
                current = state.current()
                assert current is None or current.edition == "paid"
            except Exception as error:  # pragma: no cover - failure path
                errors.append(error)

    threads = [threading.Thread(target=target) for target in (writer, reader, writer, reader)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def test_state_takes_its_lock_for_every_operation():
    class CountingLock:
        entered = 0

        def __enter__(self):
            CountingLock.entered += 1

        def __exit__(self, *exc):
            return False

    state = gate.EntitlementState(clock=FakeClock(), wall_clock=lambda: 0.0)
    state._lock = CountingLock()
    state.install("paid", [], 60)
    assert CountingLock.entered == 1
    state.current()
    assert CountingLock.entered == 2
    state.clear()
    assert CountingLock.entered == 3


def test_exemption_is_per_method_not_per_path(client, locked):
    assert client.post("/api/health").json()["error"]["code"] == "license_required"
    assert client.delete("/api/release").json()["error"]["code"] == "license_required"
    assert client.post("/api/license/status").json()["error"]["code"] == "license_required"


# ---------------------------------------------------------------- route classification

def test_exempt_list_is_exactly_the_documented_set():
    assert gate.GATE_EXEMPT_ROUTES == frozenset({
        ("GET", "/api/health"),
        ("GET", "/api/release"),
        ("GET", "/api/license/status"),
        ("PUT", "/api/license/entitlement"),
        ("DELETE", "/api/license/entitlement"),
        ("POST", "/api/license/activate"),
        ("POST", "/api/support/tickets"),
        ("GET", "/api/support/tickets"),
        ("GET", "/api/support/tickets/{ticket_id}"),
        ("GET", "/api/communications/banner"),
    })


FREE_CALCULATOR_ROUTES = {
    ("POST", "/api/calculator/break-even"),
    ("POST", "/api/calculator/compound-interest"),
    ("POST", "/api/calculator/depreciation"),
    ("POST", "/api/calculator/discount"),
    ("POST", "/api/calculator/freelance-rate"),
    ("POST", "/api/calculator/loan-emi"),
    ("POST", "/api/calculator/margin-markup"),
    ("POST", "/api/calculator/percent-of"),
    ("POST", "/api/calculator/percentage-change"),
    ("POST", "/api/calculator/simple-interest"),
    ("POST", "/api/calculator/vat-sales-tax"),
    ("POST", "/api/math/eval"),
    ("POST", "/api/calculator/averages"),
    ("POST", "/api/calculator/fractions"),
    ("POST", "/api/calculator/roi"),
    ("POST", "/api/calculator/cagr"),
    ("POST", "/api/calculator/date-differences"),
    ("POST", "/api/calculator/ages"),
    ("POST", "/api/calculator/business-days"),
    ("POST", "/api/calculator/work-hours"),
    ("GET", "/api/calculator/time-zones"),
    ("POST", "/api/calculator/time-zone-conversions"),
    ("POST", "/api/calculator/quadratics"),
    ("POST", "/api/calculator/gcd-lcm"),
    ("POST", "/api/calculator/statistics"),
    ("POST", "/api/calculator/geometry"),
}
FREE_CONVERTER_ROUTES = {
    ("GET", "/api/units/catalog"),
    ("POST", "/api/units/convert"),
    ("POST", "/api/colors/convert"),
}
FREE_DEVELOPER_ROUTES = {
    ("POST", "/api/devtools/process"),
    ("POST", "/api/convert/data"),
    ("POST", "/api/convert/data/sheets"),
    ("POST", "/api/developer/json-diffs"),
    ("POST", "/api/developer/text-diffs"),
    ("POST", "/api/developer/text-case-conversions"),
    ("POST", "/api/developer/text-analyses"),
    ("POST", "/api/developer/timestamp-conversions"),
    ("GET", "/api/developer/time-zones"),
    ("POST", "/api/developer/uuids"),
    ("POST", "/api/developer/qr-codes"),
}

# Owner decision 2026-10-22: Clipboard & Snippets Studio is a paid tool even though the catalog files
# it under "Developer & Data"; every /api/clipboard route is gated.
CLIPBOARD_ROUTES = {
    ("POST", "/api/clipboard/clear"),
    ("POST", "/api/clipboard/clips"),
    ("DELETE", "/api/clipboard/clips/{clip_id}"),
    ("GET", "/api/clipboard/clips/{clip_id}"),
    ("POST", "/api/clipboard/clips/{clip_id}/pin"),
    ("GET", "/api/clipboard/folders"),
    ("POST", "/api/clipboard/folders"),
    ("DELETE", "/api/clipboard/folders/{folder_id}"),
    ("GET", "/api/clipboard/global-settings"),
    ("POST", "/api/clipboard/global-settings"),
    ("GET", "/api/clipboard/history"),
    ("GET", "/api/clipboard/snippets"),
    ("POST", "/api/clipboard/snippets"),
    ("GET", "/api/clipboard/snippets/export"),
    ("POST", "/api/clipboard/snippets/import"),
    ("POST", "/api/clipboard/snippets/render"),
    ("DELETE", "/api/clipboard/snippets/{snippet_id}"),
    ("POST", "/api/clipboard/transform"),
}

# Routes a free tool uses that a paid tool also uses (or that the catalog puts in a paid category):
# these stay gated until the owner decides; see the S3 notes in the LLD.
SHARED_WITH_PAID_ROUTES = {
    ("POST", "/api/crypto/hashes"),
    ("POST", "/api/export/result"),
}

# Free categories (catalog names) and, per tool in them, the backend routes the tool calls. A tool
# in a free category must have every route in FREE_ROUTES, or be listed in PAID_DESPITE_FREE_CATEGORY
# with every route gated. A new tool in a free category fails the coverage test until it is added.
FREE_CATEGORIES = {"Calculators", "Unit Converters", "Developer & Data"}
TOOL_ROUTES = {
    "loan_emi": {("POST", "/api/calculator/loan-emi")},
    "compound_interest": {("POST", "/api/calculator/compound-interest")},
    "vat_salestax": {("POST", "/api/calculator/vat-sales-tax")},
    "freelance_rate": {("POST", "/api/calculator/freelance-rate")},
    "margin_markup": {("POST", "/api/calculator/margin-markup")},
    "break_even": {("POST", "/api/calculator/break-even")},
    "simple_interest": {("POST", "/api/calculator/simple-interest")},
    "depreciation": {("POST", "/api/calculator/depreciation")},
    "everyday_percentages": {
        ("POST", "/api/calculator/percent-of"),
        ("POST", "/api/calculator/percentage-change"),
        ("POST", "/api/calculator/discount"),
    },
    "math_eval": {("POST", "/api/math/eval")},
    "units_convert": {("GET", "/api/units/catalog"), ("POST", "/api/units/convert")},
    "color_converter": {("POST", "/api/colors/convert")},
    "data_converter": {("POST", "/api/convert/data"), ("POST", "/api/convert/data/sheets")},
    "devtools_format": {("POST", "/api/devtools/process")},
    "url_codec": {("POST", "/api/devtools/process")},
    "jwt_inspector": {("POST", "/api/devtools/process")},
    "clipboard_manager": CLIPBOARD_ROUTES,
    "weighted_average": {("POST", "/api/calculator/averages")},
    "fractions_ratios": {("POST", "/api/calculator/fractions")},
    "roi": {("POST", "/api/calculator/roi")},
    "cagr": {("POST", "/api/calculator/cagr")},
    "date_difference": {("POST", "/api/calculator/date-differences")},
    "age_calculator": {("POST", "/api/calculator/ages")},
    "business_days": {("POST", "/api/calculator/business-days")},
    "work_hours": {("POST", "/api/calculator/work-hours")},
    "time_zone_converter": {
        ("GET", "/api/calculator/time-zones"),
        ("POST", "/api/calculator/time-zone-conversions"),
    },
    "quadratic_solver": {("POST", "/api/calculator/quadratics")},
    "gcd_lcm": {("POST", "/api/calculator/gcd-lcm")},
    "descriptive_statistics": {("POST", "/api/calculator/statistics")},
    "geometry": {("POST", "/api/calculator/geometry")},
    "json_compare": {("POST", "/api/developer/json-diffs")},
    "text_diff": {("POST", "/api/developer/text-diffs")},
    "text_case": {("POST", "/api/developer/text-case-conversions")},
    "text_metrics": {("POST", "/api/developer/text-analyses")},
    "timestamp_converter": {
        ("POST", "/api/developer/timestamp-conversions"),
        ("GET", "/api/developer/time-zones"),
    },
    "uuid_generator": {("POST", "/api/developer/uuids")},
    "qr_generator": {("POST", "/api/developer/qr-codes")},
    # Global Launcher: a native desktop page, paid by tool id like the clipboard studio; it calls no
    # sidecar route of its own.
    "global_launcher": set(),
}
PAID_DESPITE_FREE_CATEGORY = {"clipboard_manager", "global_launcher"}


# Catalog metadata (names and categories only) that every locked screen needs to render.
FREE_CATALOG_ROUTES = {("GET", "/api/tools/search")}


def test_free_list_is_exactly_the_documented_set():
    assert gate.FREE_ROUTES == frozenset(
        FREE_CALCULATOR_ROUTES | FREE_CONVERTER_ROUTES | FREE_DEVELOPER_ROUTES | FREE_CATALOG_ROUTES
    )


def test_every_free_category_tool_is_tied_to_its_backend_routes():
    from officekit.engines.engine_comms import TOOL_REGISTRY

    in_free_categories = {tool["id"] for tool in TOOL_REGISTRY if tool["category"] in FREE_CATEGORIES}
    assert in_free_categories == set(TOOL_ROUTES), "add the tool's routes to TOOL_ROUTES"
    for tool_id, routes in TOOL_ROUTES.items():
        if tool_id in PAID_DESPITE_FREE_CATEGORY:
            assert routes.isdisjoint(gate.FREE_ROUTES), tool_id
            assert all(route in gate.ROUTE_FEATURES for route in routes), tool_id
        else:
            assert routes <= gate.FREE_ROUTES, tool_id
    free_tool_routes = set().union(*(r for t, r in TOOL_ROUTES.items() if t not in PAID_DESPITE_FREE_CATEGORY))
    assert gate.FREE_ROUTES - free_tool_routes == FREE_CATALOG_ROUTES


def test_clipboard_routes_are_gated_not_free():
    assert CLIPBOARD_ROUTES.isdisjoint(gate.FREE_ROUTES)
    assert CLIPBOARD_ROUTES <= set(gate.ROUTE_FEATURES)
    assert not any(route[1].startswith("/api/clipboard/") for route in gate.FREE_ROUTES)


def test_free_routes_exclude_every_route_shared_with_a_paid_tool():
    assert gate.FREE_ROUTES.isdisjoint(SHARED_WITH_PAID_ROUTES)
    for route in SHARED_WITH_PAID_ROUTES:
        assert route in gate.ROUTE_FEATURES


def test_is_free_route_matches_method_and_path_with_parameters():
    assert gate.is_free_route("/api/math/eval", "POST")
    assert gate.is_free_route("/api/units/catalog", "GET")
    assert gate.is_free_route("/api/convert/data/sheets", "POST")
    assert not gate.is_free_route("/api/math/eval", "GET")
    assert not gate.is_free_route("/api/clipboard/clips/c1", "GET")
    assert not gate.is_free_route("/api/clipboard/snippets/export", "GET")
    assert not gate.is_free_route("/api/convert/data/sheets/extra", "POST")
    assert not gate.is_free_route("/api/units/..", "GET")
    assert not gate.is_free_route("/api/crypto/hashes", "POST")
    assert not gate.is_free_route("/api/health", "GET")
    assert not gate.is_free_route("/api/calculator/unknown", "POST")
    assert not gate.is_free_route("/api/math/eval/", "POST")


def test_free_routes_are_not_exempt_and_exempt_routes_are_not_free():
    assert not gate.is_gate_exempt("/api/math/eval", "POST")
    assert not gate.is_free_route("/api/health", "GET")
    assert not gate.is_gate_exempt("/api/system/check-update", "GET")


def test_is_gate_exempt_matches_method_and_path_with_parameters():
    assert gate.is_gate_exempt("/api/health", "GET")
    assert gate.is_gate_exempt("/api/support/tickets/T-1", "GET")
    assert gate.is_gate_exempt("/api/license/entitlement", "PUT")
    assert not gate.is_gate_exempt("/api/health", "POST")
    assert not gate.is_gate_exempt("/api/pdf/merge", "POST")
    assert not gate.is_gate_exempt("/api/support/tickets/", "GET")
    assert not gate.is_gate_exempt("/api/support/tickets/..", "GET")
    assert not gate.is_gate_exempt("/api/support/tickets/a/b", "GET")
    assert not gate.is_gate_exempt("/api/health/", "GET")
    assert not gate.is_gate_exempt("/api//health", "GET")
    assert not gate.is_gate_exempt("/API/health", "GET")


def test_is_gate_exempt_without_method_matches_any_listed_method():
    assert gate.is_gate_exempt("/api/license/entitlement")
    assert not gate.is_gate_exempt("/api/media-jobs")


def test_feature_for_route_reads_one_table_and_prefers_the_most_specific_match():
    assert gate.feature_for_route("POST", "/api/pdf/merge") is None
    assert gate.feature_for_route("GET", "/api/storage-scans/s1") is None
    assert gate.feature_for_route("DELETE", "/api/storage-scans/s1") is None


def test_feature_for_route_returns_bound_feature_from_the_table(monkeypatch):
    monkeypatch.setitem(gate.ROUTE_FEATURES, ("POST", "/api/pdf/merge"), "pdf.merge")
    monkeypatch.setitem(gate.ROUTE_FEATURES, ("GET", "/api/media-jobs/{job_id}"), "media")
    assert gate.feature_for_route("POST", "/api/pdf/merge") == "pdf.merge"
    assert gate.feature_for_route("GET", "/api/media-jobs/abc") == "media"


def test_a_literal_route_beats_a_parameter_route():
    table = {
        ("GET", "/api/x/{id}"): "param",
        ("GET", "/api/x/export"): "literal",
    }
    assert gate.match_route(table, "GET", "/api/x/export") == "literal"
    assert gate.match_route(table, "GET", "/api/x/other") == "param"
    assert gate.match_route(table, "POST", "/api/x/other") is gate.NO_MATCH


def test_every_route_in_app_is_classified_exempt_free_or_in_the_feature_table():
    unclassified = []
    for template, methods in api.app.openapi()["paths"].items():
        if not template.startswith("/api/"):
            continue
        for method in methods:
            method = method.upper()
            key = (method, template)
            if (
                key not in gate.GATE_EXEMPT_ROUTES
                and key not in gate.FREE_ROUTES
                and key not in gate.ROUTE_FEATURES
            ):
                unclassified.append(key)
    assert unclassified == [], "classify new routes in engine_license_gate.py"


def test_a_new_unclassified_route_fails_the_completeness_check(monkeypatch):
    monkeypatch.setattr(gate, "FREE_ROUTES", gate.FREE_ROUTES - {("POST", "/api/math/eval")})
    with pytest.raises(AssertionError):
        test_every_route_in_app_is_classified_exempt_free_or_in_the_feature_table()


def test_no_route_is_in_more_than_one_classification():
    assert gate.GATE_EXEMPT_ROUTES.isdisjoint(gate.ROUTE_FEATURES)
    assert gate.FREE_ROUTES.isdisjoint(gate.ROUTE_FEATURES)
    assert gate.FREE_ROUTES.isdisjoint(gate.GATE_EXEMPT_ROUTES)


def test_classification_tables_name_no_route_that_does_not_exist():
    real = {
        (method.upper(), template)
        for template, methods in api.app.openapi()["paths"].items()
        for method in methods
    }
    stale = (gate.GATE_EXEMPT_ROUTES | gate.FREE_ROUTES | set(gate.ROUTE_FEATURES)) - real
    assert stale == set()


def test_feature_values_are_valid_slugs_or_none():
    for feature in gate.ROUTE_FEATURES.values():
        assert feature is None or gate.FEATURE_PATTERN.fullmatch(feature)


# ---------------------------------------------------------------- grant token loading

def test_grant_token_must_be_well_formed_and_distinct_from_the_api_token():
    assert gate.load_native_grant_token({gate.NATIVE_GRANT_ENVIRONMENT_KEY: GRANT}, API_TOKEN) == GRANT
    for bad in ("", "short", "x" * 129, "x" * 31 + "\n", "é" * 40, "a b" * 20):
        assert gate.load_native_grant_token({gate.NATIVE_GRANT_ENVIRONMENT_KEY: bad}, API_TOKEN) is None
    assert gate.load_native_grant_token({}, API_TOKEN) is None
    assert gate.load_native_grant_token({gate.NATIVE_GRANT_ENVIRONMENT_KEY: API_TOKEN}, API_TOKEN) is None


def test_grant_header_comparison_fails_closed():
    assert gate.is_native_grant_valid(GRANT, GRANT)
    assert not gate.is_native_grant_valid(None, GRANT)
    assert not gate.is_native_grant_valid(GRANT, None)
    assert not gate.is_native_grant_valid("", "")
    assert not gate.is_native_grant_valid("x", "")
    assert not gate.is_native_grant_valid("", GRANT)
    assert not gate.is_native_grant_valid("h" * 40, GRANT)
    assert not gate.is_native_grant_valid(GRANT + "x", GRANT)
    assert not gate.is_native_grant_valid("é" * 40, GRANT)
    assert not gate.is_native_grant_valid("g" * 500, GRANT)


def test_grant_header_uses_a_constant_time_comparison(monkeypatch):
    calls = []
    real = gate.hmac.compare_digest

    def spy(left, right):
        calls.append((left, right))
        return real(left, right)

    monkeypatch.setattr(gate.hmac, "compare_digest", spy)
    assert gate.is_native_grant_valid(GRANT, GRANT)
    assert calls


# ---------------------------------------------------------------- middleware

def test_locked_app_returns_license_required_for_paid_routes(client, locked):
    response = client.post("/api/pdf/merge")
    assert response.status_code == 403
    assert response.json() == {"error": {
        "code": "license_required",
        "message": "An active OfficeKit licence is required.",
    }}


def test_locked_app_gates_every_method_and_unknown_api_paths(client, locked):
    assert client.get("/api/system/info").status_code == 403
    assert client.delete("/api/workspaces/abc").status_code == 403
    assert client.get("/api/not-a-route").json()["error"]["code"] == "license_required"


def test_exempt_routes_work_without_an_entitlement(client, locked):
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/release").status_code == 200
    assert client.get("/api/license/status").status_code == 200
    banner = client.get("/api/communications/banner")
    assert banner.status_code == 200
    assert banner.json().get("error", {}).get("code") != "license_required"


def test_updates_are_disabled_while_locked(client, locked):
    response = client.get("/api/system/check-update")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "license_required"


def test_free_routes_work_without_an_entitlement(client, locked):
    assert client.post("/api/math/eval", json={"expression": "1+1"}).status_code == 200
    assert client.get("/api/units/catalog").status_code == 200
    percent = client.post("/api/calculator/percent-of", json={"percent": 10, "value": 50})
    assert percent.status_code == 200
    devtools = client.post("/api/devtools/process", json={"operation": "format_json", "content": "{}"})
    assert devtools.status_code != 403
    assert "license_required" not in devtools.text


def test_clipboard_and_snippets_studio_is_locked_while_locked(client, locked):
    for method, template in sorted(CLIPBOARD_ROUTES):
        path = template.replace("{clip_id}", "c1").replace("{folder_id}", "f1").replace("{snippet_id}", "s1")
        response = client.request(method, path)
        assert response.status_code == 403, (method, path)
        assert response.json()["error"]["code"] == "license_required", (method, path)


def test_clipboard_opens_with_a_live_entitlement(client, locked):
    locked.install("paid", [], 60)
    response = client.get("/api/clipboard/history")
    assert response.status_code == 200


def test_free_routes_stay_free_when_the_entitlement_has_expired(client, locked):
    clock = FakeClock()
    locked._clock = clock
    locked.install("paid", [], 60)
    clock.now += 61
    assert client.get("/api/units/catalog").status_code == 200
    assert client.get("/api/system/info").json()["error"]["code"] == "license_required"


def test_free_classification_is_per_method_and_exact_path(client, locked):
    assert client.delete("/api/units/catalog").json()["error"]["code"] == "license_required"
    assert client.get("/api/math/eval").json()["error"]["code"] == "license_required"
    assert client.post("/api/calculator/not-a-calculator").json()["error"]["code"] == "license_required"
    assert client.get("/api/units/unknown/path").json()["error"]["code"] == "license_required"


def test_routes_shared_with_paid_tools_stay_gated(client, locked):
    assert client.post("/api/crypto/hashes", json={"text": "a"}).json()["error"]["code"] == "license_required"
    assert client.post("/api/export/result", json={}).json()["error"]["code"] == "license_required"


def test_tool_catalog_listing_is_free_so_a_locked_app_can_render_free_and_locked_tools(client, locked):
    response = client.get("/api/tools/search")
    assert response.status_code == 200
    assert response.json()["tools"]


def test_options_preflight_is_not_gated(client, locked):
    response = client.options("/api/pdf/merge", headers={
        "origin": "tauri://localhost", "access-control-request-method": "POST",
    })
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"
    assert "license_required" not in response.text


def test_head_on_a_gated_route_is_403_because_the_gate_runs_before_routing(client, locked):
    # Intentional: the gate classifies by (method, path) before Starlette routing, so an unlisted
    # method such as HEAD is gated (fail closed) instead of answering 405, even on a free route.
    for path in ("/api/system/info", "/api/units/catalog"):
        response = client.head(path)
        assert response.status_code == 403
    assert client.get("/api/units/catalog").status_code == 200


@pytest.mark.parametrize("path", ["/api/pdf/merge", "/api/system/info"])
def test_gate_rejection_carries_cors_headers_for_a_trusted_origin(client, locked, path):
    # The webview is cross-origin to the loopback sidecar; without Access-Control-Allow-Origin on
    # the 403 the browser hides the body and the licence prompt never fires.
    response = client.request("POST" if path.endswith("merge") else "GET", path, headers={"origin": "tauri://localhost"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "license_required"
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"


def test_feature_rejection_carries_cors_headers_for_a_trusted_origin(client, locked, monkeypatch):
    monkeypatch.setitem(gate.ROUTE_FEATURES, ("GET", "/api/system/info"), "units.secret")
    locked.install("paid", ["other"], 60)
    response = client.get("/api/system/info", headers={"origin": "http://tauri.localhost"})
    assert response.json()["error"]["code"] == "feature_not_licensed"
    assert response.headers["access-control-allow-origin"] == "http://tauri.localhost"


def test_authentication_rejection_carries_cors_headers_for_a_trusted_origin(client, locked, monkeypatch):
    monkeypatch.setattr(api, "API_AUTH_TOKEN", API_TOKEN)
    response = client.get("/api/system/info", headers={"origin": "tauri://localhost"})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"


def test_an_untrusted_origin_gets_no_cors_headers_on_any_rejection(client, locked):
    response = client.post("/api/pdf/merge", headers={"origin": "https://evil.example"})
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers
    free = client.get("/api/units/catalog", headers={"origin": "https://evil.example"})
    assert free.status_code == 403
    assert free.json() == {"detail": "Browser request origin is not allowed."}
    assert "access-control-allow-origin" not in free.headers


def test_cors_is_the_outermost_middleware():
    layers = [layer.cls.__name__ for layer in api.app.user_middleware]
    assert layers[0] == "CORSMiddleware"


def test_a_live_entitlement_opens_paid_routes(client, locked):
    locked.install("paid", [], 60)
    assert client.get("/api/system/info").status_code == 200


def test_an_expired_entitlement_closes_the_gate_again(client, locked):
    clock = FakeClock()
    locked._clock = clock
    locked.install("paid", [], 60)
    assert client.get("/api/system/info").status_code == 200
    clock.now += 61
    assert client.get("/api/system/info").json()["error"]["code"] == "license_required"


def test_feature_bound_route_without_the_feature_is_forbidden_without_detail(client, locked, monkeypatch):
    monkeypatch.setitem(gate.ROUTE_FEATURES, ("GET", "/api/system/info"), "units.secret")
    locked.install("paid", ["other"], 60)
    response = client.get("/api/system/info")
    assert response.status_code == 403
    assert response.json() == {"error": {
        "code": "feature_not_licensed",
        "message": "Your licence does not include this feature.",
    }}
    assert "units.secret" not in response.text
    locked.install("paid", ["units.secret"], 60)
    assert client.get("/api/system/info").status_code == 200


def test_gate_runs_after_authentication(client, locked, monkeypatch):
    monkeypatch.setattr(api, "API_AUTH_TOKEN", API_TOKEN)
    assert client.get("/api/system/info").status_code == 401
    bearer = {"authorization": f"Bearer {API_TOKEN}"}
    assert client.get("/api/system/info", headers=bearer).json()["error"]["code"] == "license_required"


def test_gate_cannot_be_disabled_by_environment_or_headers(client, locked, monkeypatch):
    for name in ("OFFICEKIT_LICENSE_GATE", "OFFICEKIT_DISABLE_LICENSE_GATE", "OFFICEKIT_DEV", "OFFICEKIT_RELEASE_PROFILE"):
        monkeypatch.setenv(name, "off")
    response = client.get("/api/system/info", headers={"x-officekit-license-gate": "off"})
    assert response.status_code == 403


def test_the_app_module_exposes_no_gate_off_switch():
    source = open(api.__file__, encoding="utf-8").read() + open(gate.__file__, encoding="utf-8").read()
    for token in ("GATE_ENABLED", "gate_enabled", "disable_gate", "license_gate_enabled"):
        assert token not in source


# ---------------------------------------------------------------- status

def test_status_without_entitlement_has_no_secrets(client, locked):
    response = client.get("/api/license/status")
    assert response.json() == {"activated": False, "edition": None, "features": [], "valid_until_epoch": None}


def test_status_reflects_the_entitlement(client, locked):
    locked.install("paid", ["b", "a"], 120)
    payload = client.get("/api/license/status").json()
    assert payload["activated"] is True
    assert payload["edition"] == "paid"
    assert payload["features"] == ["a", "b"]
    assert isinstance(payload["valid_until_epoch"], int)
    assert set(payload) == {"activated", "edition", "features", "valid_until_epoch"}


def test_status_and_release_bodies_keep_their_exact_field_order(client, locked):
    assert client.get("/api/license/status").text == (
        '{"activated":false,"edition":null,"features":[],"valid_until_epoch":null}'
    )
    assert client.get("/api/release").text == (
        f'{{"profile":"development","tool_ids":[],"version":"{api.app.version}","edition":null}}'
    )


def _openapi_operation(path, method):
    return api.app.openapi()["paths"][path][method]


def _resolve(schema):
    if "$ref" in schema:
        return api.app.openapi()["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def test_openapi_describes_the_release_response():
    schema = _resolve(_openapi_operation("/api/release", "get")["responses"]["200"]["content"]["application/json"]["schema"])
    assert list(schema["properties"]) == ["profile", "tool_ids", "version", "edition"]
    assert schema["required"] == ["profile", "tool_ids", "version", "edition"]
    assert {"type": "null"} in schema["properties"]["edition"]["anyOf"]


def test_openapi_describes_the_license_status_response():
    schema = _resolve(
        _openapi_operation("/api/license/status", "get")["responses"]["200"]["content"]["application/json"]["schema"]
    )
    assert list(schema["properties"]) == ["activated", "edition", "features", "valid_until_epoch"]
    assert schema["properties"]["features"]["items"] == {"type": "string"}
    assert {"type": "null"} in schema["properties"]["valid_until_epoch"]["anyOf"]


def test_openapi_describes_the_entitlement_push_body_and_its_responses():
    operation = _openapi_operation("/api/license/entitlement", "put")
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    assert schema["required"] == ["activation_id", "edition", "features", "valid_for_seconds"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["valid_for_seconds"]["minimum"] == gate.MIN_VALID_FOR_SECONDS
    assert schema["properties"]["valid_for_seconds"]["maximum"] == gate.MAX_VALID_FOR_SECONDS
    assert operation["requestBody"]["required"] is True
    assert {"204", "401", "422"} <= set(operation["responses"])
    assert {"204", "401"} <= set(_openapi_operation("/api/license/entitlement", "delete")["responses"])


def test_status_never_contains_the_grant_token(client, locked):
    assert GRANT not in client.get("/api/license/status").text
    assert GRANT not in client.get("/api/release").text
    assert GRANT not in client.get("/api/health").text


# ---------------------------------------------------------------- entitlement handoff

def test_put_installs_the_entitlement_and_status_reflects_it(client, locked):
    assert put(client, body()).status_code == 204
    assert client.get("/api/license/status").json()["features"] == ["image.convert", "pdf.merge"]
    assert client.get("/api/system/info").status_code == 200


def test_put_replaces_the_previous_entitlement(client, locked):
    assert put(client, body(features=["a"])).status_code == 204
    assert put(client, body(features=["b"])).status_code == 204
    assert client.get("/api/license/status").json()["features"] == ["b"]


def test_delete_clears_the_entitlement_and_is_idempotent(client, locked):
    assert put(client, body()).status_code == 204
    headers = {gate.NATIVE_GRANT_HEADER: GRANT}
    assert client.delete("/api/license/entitlement", headers=headers).status_code == 204
    assert client.delete("/api/license/entitlement", headers=headers).status_code == 204
    assert client.get("/api/system/info").json()["error"]["code"] == "license_required"


@pytest.mark.parametrize("token", [None, "", "wrong" * 10, "g" * 41])
def test_put_and_delete_reject_a_missing_or_wrong_grant(client, locked, token):
    response = put(client, body(), token=token)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "native_grant_required"
    headers = {} if token is None else {gate.NATIVE_GRANT_HEADER: token}
    assert client.delete("/api/license/entitlement", headers=headers).status_code == 401
    assert client.get("/api/license/status").json()["activated"] is False


def test_wrong_grant_does_not_clear_an_existing_entitlement(client, locked):
    locked.install("paid", [], 60)
    assert client.delete("/api/license/entitlement", headers={gate.NATIVE_GRANT_HEADER: "w" * 40}).status_code == 401
    assert locked.current() is not None


def test_the_webview_api_token_alone_is_not_a_grant(client, locked, monkeypatch):
    monkeypatch.setattr(api, "API_AUTH_TOKEN", API_TOKEN)
    bearer = {"authorization": f"Bearer {API_TOKEN}"}
    assert put(client, body(), token=None, headers=bearer).status_code == 401
    assert put(client, body(), token=API_TOKEN, headers=bearer).status_code == 401
    assert client.delete("/api/license/entitlement", headers=bearer).status_code == 401
    assert locked.current() is None


def test_grant_route_still_requires_the_api_token_when_one_is_configured(client, locked, monkeypatch):
    monkeypatch.setattr(api, "API_AUTH_TOKEN", API_TOKEN)
    assert put(client, body()).status_code == 401
    assert locked.current() is None
    bearer = {"authorization": f"Bearer {API_TOKEN}"}
    assert put(client, body(), headers=bearer).status_code == 204


@pytest.mark.parametrize("environment", [None, "", "short", "x" * 129, "bad token with spaces " * 3])
def test_unset_or_malformed_env_grant_fails_closed(locked, monkeypatch, environment):
    if environment is None:
        monkeypatch.delenv(gate.NATIVE_GRANT_ENVIRONMENT_KEY, raising=False)
    else:
        monkeypatch.setenv(gate.NATIVE_GRANT_ENVIRONMENT_KEY, environment)
    client = TestClient(api.app, raise_server_exceptions=False)
    for candidate in (environment, "", "anything" * 6):
        response = put(client, body(), token=candidate if candidate else None)
        assert response.status_code == 401
    assert locked.current() is None


def test_env_grant_equal_to_the_api_token_fails_closed(locked, monkeypatch):
    monkeypatch.setenv(gate.NATIVE_GRANT_ENVIRONMENT_KEY, API_TOKEN)
    monkeypatch.setattr(api, "API_AUTH_TOKEN", API_TOKEN)
    client = TestClient(api.app, raise_server_exceptions=False)
    response = put(client, body(), token=API_TOKEN, headers={"authorization": f"Bearer {API_TOKEN}"})
    assert response.status_code == 401


def test_the_entitlement_push_still_needs_the_secret_grant_value_even_though_cors_lists_the_header(client, locked):
    # Main allows the grant header in CORS (the invoice folder authority sends it from the shell's
    # HTTP client). The licence push is therefore protected by the secret value, never by CORS: a
    # cross-origin request that names the header without the value is refused and installs nothing.
    response = client.put("/api/license/entitlement", json=body(), headers={
        "origin": "tauri://localhost",
        gate.NATIVE_GRANT_HEADER: "not-the-grant",
    })
    assert response.status_code == 401
    assert locked.current() is None


@pytest.mark.parametrize("payload", [
    body(edition="free"),
    body(edition=None),
    body(activation_id="short"),
    body(activation_id="A" * 23),
    body(activation_id="A" * 21 + "!"),
    body(activation_id=5),
    body(valid_for_seconds=59),
    body(valid_for_seconds=3601),
    body(valid_for_seconds="1800"),
    body(valid_for_seconds=1800.5),
    body(valid_for_seconds=True),
    body(features=["b", "a"]),
    body(features=["a", "a"]),
    body(features=["Bad Slug"]),
    body(features=["x" * 65]),
    body(features=[5]),
    body(features="a"),
    body(features=[f"f{index:03d}" for index in range(129)]),
    body(extra="field"),
    ["not", "an", "object"],
    "text",
    None,
])
def test_put_rejects_invalid_bodies_with_422_and_installs_nothing(client, locked, payload):
    response = put(client, payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_entitlement"
    assert ACTIVATION_ID not in response.text
    assert locked.current() is None


def test_put_rejects_missing_fields_and_bad_json(client, locked):
    partial = body()
    del partial["features"]
    assert put(client, partial).status_code == 422
    bad = client.put("/api/license/entitlement", content=b"{not json", headers={
        gate.NATIVE_GRANT_HEADER: GRANT, "content-type": "application/json",
    })
    assert bad.status_code == 422
    assert client.put("/api/license/entitlement", content=b"\xff\xfe", headers={
        gate.NATIVE_GRANT_HEADER: GRANT,
    }).status_code == 422
    assert locked.current() is None


def test_put_accepts_boundary_values(client, locked):
    assert put(client, body(valid_for_seconds=60, features=[])).status_code == 204
    assert put(client, body(valid_for_seconds=3600, features=[f"f{index:03d}" for index in range(128)])).status_code == 204
    assert put(client, body(features=["a" * 64])).status_code == 204


def test_put_rejects_oversized_bodies_with_413(client, locked):
    response = client.put("/api/license/entitlement", content=b"{" + b" " * (gate.MAX_ENTITLEMENT_BODY_BYTES + 1) + b"}", headers={
        gate.NATIVE_GRANT_HEADER: GRANT, "content-type": "application/json",
    })
    assert response.status_code == 413
    assert locked.current() is None


def test_put_with_a_wrong_grant_is_rejected_before_the_body_is_validated(client, locked):
    response = put(client, {"nonsense": True}, token="w" * 40)
    assert response.status_code == 401


def test_the_body_limit_is_registered_for_the_entitlement_route():
    assert gate.MAX_ENTITLEMENT_BODY_BYTES <= 16 * 1024
    limits = [layer for layer in api.app.user_middleware if layer.kwargs.get("path_limits")]
    assert limits[0].kwargs["path_limits"]["/api/license/entitlement"] == gate.MAX_ENTITLEMENT_BODY_BYTES
