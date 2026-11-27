"""Exact result checks for the GCD & LCM tool's HTTP contract."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from officekit.routes.calculators import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_gcd_lcm_returns_exact_results_for_mixed_values():
    response = _client().post("/api/calculator/gcd-lcm", json={"integers": [48, 180, 36]})

    assert response.status_code == 200, response.text
    assert response.json() == {
        "gcd": "12",
        "lcm": "720",
        "count": 3,
        "assumptions": {"sign": "absolute", "zero_policy": "gcd(0,0)=0; lcm with 0 = 0"},
    }


def test_gcd_lcm_zero_input_has_one_as_gcd_and_zero_as_lcm():
    response = _client().post("/api/calculator/gcd-lcm", json={"integers": [0, 7, 3]})

    assert response.status_code == 200, response.text
    assert response.json()["gcd"] == "1"
    assert response.json()["lcm"] == "0"
    assert response.json()["count"] == 3
