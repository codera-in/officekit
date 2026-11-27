"""HTTP-level contract and validation tests for the local color converter."""

from fastapi.testclient import TestClient

import app as officekit_app


client = TestClient(officekit_app.app)


def test_color_conversion_returns_typed_response_for_reference_vectors():
    response = client.post(
        "/api/colors/convert",
        json={"value": "#f00", "source_format": "hex", "target_format": "rgb"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "value": "rgb(255, 0, 0)",
        "source_format": "hex",
        "target_format": "rgb",
    }


def test_color_conversion_preserves_alpha_and_normalizes_wrapped_hue():
    alpha_response = client.post(
        "/api/colors/convert",
        json={"value": "#ff000080", "source_format": "hex", "target_format": "rgb"},
    )
    assert alpha_response.status_code == 200
    assert alpha_response.json() == {
        "value": "rgba(255, 0, 0, 0.502)",
        "source_format": "hex",
        "target_format": "rgb",
    }

    response = client.post(
        "/api/colors/convert",
        json={"value": "hsl(480, 100%, 50%, 0.5)", "source_format": "hsl", "target_format": "hex"},
    )

    assert response.status_code == 200
    assert response.json()["value"] == "#00ff0080"


def test_color_conversion_rejects_invalid_colors_without_echoing_user_input():
    secret_like_input = "rgb(999, 0, 0) private-marker"
    response = client.post(
        "/api/colors/convert",
        json={"value": secret_like_input, "source_format": "rgb", "target_format": "hex"},
    )

    assert response.status_code == 422
    assert "private-marker" not in response.text


def test_color_conversion_rejects_unknown_formats_extra_fields_and_non_string_values():
    valid = {"value": "#fff", "source_format": "hex", "target_format": "rgb"}
    invalid_requests = (
        {**valid, "source_format": "cmyk"},
        {**valid, "target_format": "cmyk"},
        {**valid, "unexpected": True},
        {**valid, "value": 123},
        {**valid, "value": "#" + "f" * 129},
    )

    for payload in invalid_requests:
        response = client.post("/api/colors/convert", json=payload)
        assert response.status_code == 422, payload

