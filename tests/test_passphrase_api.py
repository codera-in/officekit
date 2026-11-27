"""HTTP-level validation and response tests for local passphrase generation."""

from fastapi.testclient import TestClient
from unittest.mock import patch

import app as officekit_app


client = TestClient(officekit_app.app)


def test_passphrase_endpoint_returns_typed_secret_and_entropy():
    response = client.post("/api/crypto/passphrase", json={"word_count": 6, "separator": " "})

    assert response.status_code == 200
    payload = response.json()
    words = payload["passphrase"].split(" ")
    assert len(words) == 6
    assert all(word.isascii() and word.replace("-", "").isalpha() for word in words)
    assert payload["word_count"] == 6
    assert payload["separator"] == " "
    assert payload["theoretical_search_space_bits"] == 6 * __import__("math").log2(7776)
    assert response.headers["cache-control"] == "no-store"


def test_passphrase_endpoint_accepts_boundary_word_counts_and_default_values():
    for word_count in (6, 12):
        response = client.post("/api/crypto/passphrase", json={"word_count": word_count})
        assert response.status_code == 200
        assert response.json()["word_count"] == word_count
        assert response.json()["separator"] == " "


def test_password_endpoint_marks_generated_secrets_as_non_cacheable():
    response = client.post("/api/crypto/password?length=12&include_symbols=false")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["password"]


def test_passphrase_endpoint_rejects_bad_bounds_types_separators_and_extra_fields():
    for payload in (
        {"word_count": 5},
        {"word_count": 13},
        {"word_count": True},
        {"word_count": 6.0},
        {"word_count": 6, "separator": "\n"},
        {"word_count": 6, "separator": "-"},
        {"word_count": 6, "separator": 1},
        {"word_count": 6, "extra": "value"},
    ):
        response = client.post("/api/crypto/passphrase", json=payload)
        assert response.status_code == 422, payload


def test_passphrase_endpoint_never_returns_a_partial_secret_for_a_bad_request():
    response = client.post("/api/crypto/passphrase", json={"word_count": 6, "separator": "__"})

    assert response.status_code == 422
    assert "passphrase" not in response.json()


def test_passphrase_endpoint_reports_missing_local_resources_without_echoing_internal_errors():
    with patch(
        "app.PrivacySecurityEngine.generate_passphrase",
        side_effect=ValueError("host path /private/wordlist was unavailable"),
    ):
        response = client.post("/api/crypto/passphrase", json={"word_count": 6})

    assert response.status_code == 503
    assert response.json() == {"detail": "Passphrase generation is unavailable."}
    assert "/private/wordlist" not in response.text
