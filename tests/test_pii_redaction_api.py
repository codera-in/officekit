"""HTTP contract checks for review-first PII file preparation."""

import json

from fastapi.testclient import TestClient

from app import app
from officekit.engines.engine_pii_redaction import PiiRedactionEngine


client = TestClient(app)


def test_scan_returns_reviewable_matches_without_file_or_server_paths():
    content = b"Contact: Maya Chen\nEmail: maya@example.com"
    response = client.post("/api/privacy/pii/scan", files={"file": ("private-note.txt", content, "text/plain")})
    assert response.status_code == 200
    result = response.json()
    assert result["filename"] == "private-note.txt"
    assert result["format"] == "TXT"
    assert result["page_count"] is None
    assert [item["confidence"] for item in result["matches"]] == ["possible", "high"]
    assert all(item["location"] == "Text" for item in result["matches"])
    assert all(set(item) == {"id", "type", "label", "confidence", "value", "location"} for item in result["matches"])
    assert "/private-note" not in response.text


def test_optional_context_match_flows_through_scan_and_redact_api(monkeypatch):
    class FakeDetector:
        def detect(self, text):
            start = text.index("Nora Scott")
            return [{"type": "person", "label": "Person name", "confidence": "possible", "value": "Nora Scott",
                     "_start": start, "_end": start + 10, "_source": "neural", "_validation": "none", "_score": 0.9}]

    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_MODEL", "/local/poc-model")
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector", FakeDetector())
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector_path", "/local/poc-model")
    content = b"Please ask our colleague Nora Scott for help."
    scanned = client.post("/api/privacy/pii/scan", files={"file": ("note.txt", content, "text/plain")})
    assert scanned.status_code == 200
    matches = scanned.json()["matches"]
    match = next(item for item in matches if "Context match" in item["label"])
    assert match["confidence"] == "possible"
    assert set(match) == {"id", "type", "label", "confidence", "value", "location"}
    redacted = client.post(
        "/api/privacy/pii/redact",
        files={"file": ("note.txt", content, "text/plain")},
        data={"selected_ids": json.dumps([match["id"]]), "mode": "redact"},
    )
    assert redacted.status_code == 200
    assert b"Nora Scott" not in redacted.content


def test_context_username_and_ip_address_matches_are_reviewable_and_redactable(monkeypatch):
    content = b"Username: @sample_user\nIP address: 192.0.2.18"

    class FakeDetector:
        def detect(self, text):
            results = []
            for kind, value in (("username", "@sample_user"), ("ip_address", "192.0.2.18")):
                start = text.index(value)
                results.append({
                    "type": kind, "label": kind, "confidence": "possible", "value": value,
                    "_start": start, "_end": start + len(value), "_source": "neural",
                    "_validation": "none", "_score": 0.9,
                })
            return results

    monkeypatch.setenv("OFFICEKIT_PII_CONTEXT_MODEL", "/local/poc-model")
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector", FakeDetector())
    monkeypatch.setattr(PiiRedactionEngine, "_context_detector_path", "/local/poc-model")
    scanned = client.post("/api/privacy/pii/scan", files={"file": ("identifiers.txt", content, "text/plain")})
    assert scanned.status_code == 200
    matches = scanned.json()["matches"]
    assert {item["type"] for item in matches} == {"username", "ip_address"}
    assert all(item["confidence"] == "possible" for item in matches)

    redacted = client.post(
        "/api/privacy/pii/redact",
        files={"file": ("identifiers.txt", content, "text/plain")},
        data={"selected_ids": json.dumps([item["id"] for item in matches]), "mode": "redact"},
    )
    assert redacted.status_code == 200
    assert b"@sample_user" not in redacted.content
    assert b"192.0.2.18" not in redacted.content


def test_redact_endpoint_replaces_only_reviewed_match_and_returns_new_filename():
    content = b"Name: Maya Chen\nEmail: maya@example.com\nShare this report."
    scan = client.post("/api/privacy/pii/scan", files={"file": ("private-note.txt", content, "text/plain")}).json()
    selected_email = next(item["id"] for item in scan["matches"] if item["type"] == "email")
    response = client.post(
        "/api/privacy/pii/redact",
        files={"file": ("private-note.txt", content, "text/plain")},
        data={"selected_ids": json.dumps([selected_email])},
    )
    assert response.status_code == 200
    assert "private-note-masked.txt" in response.headers["content-disposition"]
    assert "m•••@example.com".encode() in response.content
    assert b"maya@example.com" not in response.content
    assert b"Maya Chen" in response.content


def test_redact_endpoint_allows_no_selected_matches_and_rejects_unknown_ids():
    content = b"Nothing likely private here."
    response = client.post(
        "/api/privacy/pii/redact",
        files={"file": ("note.txt", content, "text/plain")},
        data={"selected_ids": "[]"},
    )
    assert response.status_code == 200
    assert response.content == content
    assert client.post(
        "/api/privacy/pii/redact",
        files={"file": ("note.txt", b"Email: a@example.com", "text/plain")},
        data={"selected_ids": json.dumps(["0" * 24])},
    ).status_code == 422


def test_scan_rejects_unsupported_formats_with_safe_error():
    response = client.post("/api/privacy/pii/scan", files={"file": ("document.doc", b"opaque", "application/msword")})
    assert response.status_code == 422
    assert "DOCX" in response.json()["detail"]


def test_redact_endpoint_supports_full_redaction_and_rejects_invalid_mode():
    content = b"Email: maya@example.com"
    scan = client.post("/api/privacy/pii/scan", files={"file": ("note.txt", content, "text/plain")}).json()
    selected = [scan["matches"][0]["id"]]
    response = client.post("/api/privacy/pii/redact", files={"file": ("note.txt", content, "text/plain")}, data={"selected_ids": json.dumps(selected), "mode": "redact"})
    assert response.status_code == 200
    assert "note-redacted.txt" in response.headers["content-disposition"]
    assert b"[REDACTED]" in response.content
    invalid = client.post("/api/privacy/pii/redact", files={"file": ("note.txt", content, "text/plain")}, data={"selected_ids": json.dumps(selected), "mode": "other"})
    assert invalid.status_code == 422
