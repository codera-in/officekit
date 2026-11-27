"""HTTP-boundary regressions for malformed and non-finite JSON request values."""

import json

from fastapi.testclient import TestClient

from app import app


def test_non_finite_json_number_returns_safe_validation_response():
    client = TestClient(app)
    response = client.post(
        "/api/calculator/compound-interest",
        content=json.dumps({
            "principal": float("nan"),
            "annual_rate": 5,
            "years": 1,
        }).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Origin": "tauri://localhost",
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Request contains invalid or unsupported values."}
    assert "nan" not in response.text.lower()
