"""
TDD Tests for Communications, Support Tickets, Updates, and Tool Registry Search
"""

from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_tool_registry_search_api():
    # Empty query returns full catalog
    res = client.get("/api/tools/search?q=")
    assert res.status_code == 200
    data = res.json()
    assert len(data["tools"]) >= 10

    # Specific search for 'compress'
    res_compress = client.get("/api/tools/search?q=compress")
    assert res_compress.status_code == 200
    results = res_compress.json()["tools"]
    assert any("compress" in t["name"].lower() or "compress" in t["category"].lower() for t in results)

    jpeg_results = client.get("/api/tools/search?q=jpeg").json()["tools"]
    assert [tool["id"] for tool in jpeg_results] == ["image_converter"]
    assert {tool["id"] for tool in client.get("/api/tools/search?q=pdf%20to").json()["tools"]} >= {
        "bank_statement", "pdf_unlock", "pdf_protect", "pdf_merge", "pdf_split",
        "pdf_compress", "pdf_metadata_strip",
    }
    assert client.get("/api/tools/search", params={"q": "x" * 257}).status_code == 422

def test_pdf_to_search_lists_every_supported_export_and_rejects_unsupported_promises():
    expected = {
        "pdf to csv": {"bank_statement", "pdf_table_extractor"},
        "pdf to xls": {"bank_statement", "pdf_table_extractor"},
        "pdf to xlsx": {"bank_statement", "pdf_table_extractor"},
        "pdf to png": {"pdf_to_images"},
        "pdf to jpeg": {"pdf_to_images"},
        "pdf to docx": set(),
    }
    for query, expected_ids in expected.items():
        response = client.get("/api/tools/search", params={"q": query})
        assert response.status_code == 200
        results = response.json()["tools"]
        assert {tool["id"] for tool in results} == expected_ids, query

    csv_results = client.get("/api/tools/search", params={"q": "pdf to csv"}).json()["tools"]
    statement = next(tool for tool in csv_results if tool["id"] == "bank_statement")
    assert "supported" in statement["desc"].lower()
    assert "csv" in statement["desc"].lower()
    assert "excel" in statement["desc"].lower()
    assert ".xls" not in statement["desc"].lower()

    table_extractor = next(tool for tool in csv_results if tool["id"] == "pdf_table_extractor")
    assert "csv" in table_extractor["desc"].lower()
    assert "xlsx" in table_extractor["desc"].lower()
    assert ".xls" not in table_extractor["desc"].lower()

    images = next(
        tool for tool in client.get("/api/tools/search", params={"q": "pdf to jpeg"}).json()["tools"]
        if tool["id"] == "pdf_to_images"
    )
    assert "png" in images["name"].lower()
    assert "jpeg" in images["name"].lower()

def test_app_update_check_api(monkeypatch):
    monkeypatch.delenv("OFFICEKIT_RELEASE_MANIFEST_URL", raising=False)
    res = client.get("/api/system/check-update")
    assert res.status_code == 200
    data = res.json()
    assert "current_version" in data
    assert "latest_version" in data
    assert "update_available" in data
    assert "release_notes" in data
    assert data["status"] == "unavailable"
    assert data["latest_version"] is None
    assert data["update_available"] is False
    assert "not available" in data["release_notes"].lower()


def test_update_check_compares_manifest_version_and_uses_release_metadata(monkeypatch):
    import io
    import json
    from unittest.mock import patch

    from officekit.engines.engine_comms import CommsEngine

    manifest = {
        "version": "1.0.1",
        "release_notes": "Fixes PDF table extraction and improves local navigation.",
        "download_url": "https://officekit.app/download",
    }
    monkeypatch.setenv("OFFICEKIT_APP_VERSION", "1.0.0")
    monkeypatch.setenv("OFFICEKIT_RELEASE_MANIFEST_URL", "https://officekit.app/releases/latest.json")
    response = io.BytesIO(json.dumps(manifest).encode("utf-8"))
    with patch("officekit.engines.engine_comms.urlopen", return_value=response) as open_manifest:
        result = CommsEngine.check_for_updates()

    assert result == {
        "status": "update_available",
        "current_version": "1.0.0",
        "latest_version": "1.0.1",
        "update_available": True,
        "release_notes": manifest["release_notes"],
        "download_url": manifest["download_url"],
        "download_sha256": None,
        "download_size": None,
    }
    open_manifest.assert_called_once()
    request = open_manifest.call_args.args[0]
    assert request.full_url == "https://officekit.app/releases/latest.json"
    assert open_manifest.call_args.kwargs == {"timeout": 3}


def test_update_check_passes_on_the_installer_checksum_and_size_only_when_both_are_valid(monkeypatch):
    import io
    import json
    from unittest.mock import patch

    from officekit.engines.engine_comms import CommsEngine

    good_sha = "827F4A0365E4656AB9997B3CF917195379EA43455767437DC20FEA82D7374920"
    base = {
        "version": "1.0.1",
        "release_notes": "Notes",
        "download_url": "https://officekit.app/get",
    }
    cases = [
        ({"sha256": good_sha, "size": 247904819}, (good_sha.lower(), 247904819)),
        ({"sha256": good_sha}, (None, None)),
        ({"size": 247904819}, (None, None)),
        ({"sha256": "abc", "size": 10}, (None, None)),
        ({"sha256": "g" * 64, "size": 10}, (None, None)),
        ({"sha256": good_sha, "size": 0}, (None, None)),
        ({"sha256": good_sha, "size": -5}, (None, None)),
        ({"sha256": good_sha, "size": True}, (None, None)),
        ({"sha256": good_sha, "size": "10"}, (None, None)),
        ({"sha256": good_sha, "size": 1_500_000_001}, (None, None)),
        ({"sha256": 12345, "size": 10}, (None, None)),
    ]
    monkeypatch.setenv("OFFICEKIT_APP_VERSION", "1.0.0")
    monkeypatch.setenv("OFFICEKIT_RELEASE_MANIFEST_URL", "https://officekit.app/releases/latest.json")
    for extra, (sha, size) in cases:
        body = json.dumps({**base, **extra}).encode("utf-8")
        with patch("officekit.engines.engine_comms.urlopen", return_value=io.BytesIO(body)):
            result = CommsEngine.check_for_updates()
        assert result["status"] == "update_available", extra
        assert (result["download_sha256"], result["download_size"]) == (sha, size), extra


def test_update_check_never_calls_a_non_officekit_or_non_https_manifest(monkeypatch):
    from unittest.mock import patch

    from officekit.engines.engine_comms import CommsEngine

    monkeypatch.setenv("OFFICEKIT_APP_VERSION", "1.0.0")
    for manifest_url in (
        "http://officekit.app/releases/latest.json",
        "https://officekit.app:444/releases/latest.json",
        "https://attacker.example/latest.json",
        "https://officekit.app.attacker.example/latest.json",
    ):
        monkeypatch.setenv("OFFICEKIT_RELEASE_MANIFEST_URL", manifest_url)
        with patch("officekit.engines.engine_comms.urlopen") as open_manifest:
            result = CommsEngine.check_for_updates()
        assert result["status"] == "unavailable"
        assert result["latest_version"] is None
        assert result["update_available"] is False
        open_manifest.assert_not_called()


def test_update_check_reports_unknown_when_no_release_manifest_is_configured(monkeypatch):
    from unittest.mock import patch

    from officekit.engines.engine_comms import CommsEngine

    monkeypatch.delenv("OFFICEKIT_RELEASE_MANIFEST_URL", raising=False)
    monkeypatch.setenv("OFFICEKIT_APP_VERSION", "1.0.0")
    with patch("officekit.engines.engine_comms.urlopen") as open_manifest:
        result = CommsEngine.check_for_updates()

    assert result["status"] == "unavailable"
    assert result["current_version"] == "1.0.0"
    assert result["latest_version"] is None
    assert result["update_available"] is False
    assert "not available" in result["release_notes"].lower()
    open_manifest.assert_not_called()


def test_update_check_only_calls_equal_version_current_and_rejects_a_stale_manifest(monkeypatch):
    import io
    import json
    from unittest.mock import patch

    from officekit.engines.engine_comms import CommsEngine

    monkeypatch.setenv("OFFICEKIT_APP_VERSION", "1.2.0")
    monkeypatch.setenv("OFFICEKIT_RELEASE_MANIFEST_URL", "https://officekit.app/releases/latest.json")
    for latest_version in ("1.2.0", "1.1.9"):
        manifest = {
            "version": latest_version,
            "release_notes": "No newer release.",
            "download_url": "https://officekit.app/download",
        }
        with patch(
            "officekit.engines.engine_comms.urlopen",
            return_value=io.BytesIO(json.dumps(manifest).encode("utf-8")),
        ) as open_manifest:
            result = CommsEngine.check_for_updates()
        assert result["status"] == ("up_to_date" if latest_version == "1.2.0" else "unavailable")
        assert result["update_available"] is False
        assert result["latest_version"] == (latest_version if latest_version == "1.2.0" else None)
        open_manifest.assert_called_once()


def test_update_check_rejects_oversized_configured_version_without_parsing_integer(monkeypatch):
    from unittest.mock import patch

    from officekit.engines.engine_comms import CommsEngine

    monkeypatch.setenv("OFFICEKIT_APP_VERSION", "9" * 5000 + ".0.0")
    monkeypatch.setenv("OFFICEKIT_RELEASE_MANIFEST_URL", "https://officekit.app/releases/latest.json")
    with patch("officekit.engines.engine_comms.urlopen") as open_manifest:
        result = CommsEngine.check_for_updates()

    assert result["status"] == "unavailable"
    assert result["current_version"] == "1.0.0"
    assert result["latest_version"] is None
    open_manifest.assert_not_called()


def test_update_check_rejects_invalid_or_oversized_manifest_without_claiming_current(monkeypatch):
    import io
    import json
    from unittest.mock import patch

    from officekit.engines.engine_comms import CommsEngine, UPDATE_MANIFEST_MAX_BYTES

    monkeypatch.setenv("OFFICEKIT_APP_VERSION", "1.0.0")
    monkeypatch.setenv("OFFICEKIT_RELEASE_MANIFEST_URL", "https://officekit.app/releases/latest.json")
    invalid_manifests = [
        b"not json",
        json.dumps({"version": "1.0", "release_notes": "Notes", "download_url": "https://officekit.app/download"}).encode(),
        json.dumps({"version": "1.0.1", "release_notes": "Notes", "download_url": "https://attacker.example/download"}).encode(),
        json.dumps({"version": "1.0.1", "release_notes": "x" * 4001, "download_url": "https://officekit.app/download"}).encode(),
        b" " * (UPDATE_MANIFEST_MAX_BYTES + 1),
    ]
    for body in invalid_manifests:
        with patch("officekit.engines.engine_comms.urlopen", return_value=io.BytesIO(body)) as open_manifest:
            result = CommsEngine.check_for_updates()
        assert result["status"] == "unavailable"
        assert result["latest_version"] is None
        assert result["update_available"] is False
        open_manifest.assert_called_once()


def test_update_check_rejects_redirects_to_untrusted_hosts_and_handles_network_errors(monkeypatch):
    import io
    import json
    from unittest.mock import patch

    from officekit.engines.engine_comms import CommsEngine

    class RedirectedResponse(io.BytesIO):
        def geturl(self):
            return "https://attacker.example/releases/latest.json"

    monkeypatch.setenv("OFFICEKIT_APP_VERSION", "1.0.0")
    monkeypatch.setenv("OFFICEKIT_RELEASE_MANIFEST_URL", "https://officekit.app/releases/latest.json")
    with patch("officekit.engines.engine_comms.urlopen", return_value=RedirectedResponse(b"{}")) as open_manifest:
        redirected = CommsEngine.check_for_updates()
    assert redirected["status"] == "unavailable"
    assert redirected["latest_version"] is None
    open_manifest.assert_called_once()

    with patch("officekit.engines.engine_comms.urlopen", side_effect=OSError("offline")) as open_manifest:
        offline = CommsEngine.check_for_updates()
    assert offline["status"] == "unavailable"
    assert offline["latest_version"] is None
    open_manifest.assert_called_once()

def test_in_app_announcement_banner_api():
    res = client.get("/api/communications/banner")
    assert res.status_code == 200
    data = res.json()
    assert "active" in data
    assert "message" in data
    assert "banner_type" in data # info, warning, success

def test_support_and_bug_report_lifecycle(monkeypatch, tmp_path):
    import officekit.engines.engine_comms as engine_comms
    monkeypatch.setattr(engine_comms, "TICKETS_FILE", str(tmp_path / "OfficeKit" / "tickets.json"))
    payload = {
        "user_email": "tester@example.com",
        "ticket_type": "bug", # 'bug' or 'support'
        "title": "OCR text extraction glitch on rotated bank statement",
        "description": "When uploading a 90 degree rotated scan, columns are displaced.",
        "system_info": {"os": "macOS", "app_version": "1.0.0"}
    }
    # 1. Submit ticket
    submit_res = client.post("/api/support/tickets", json=payload)
    assert submit_res.status_code == 200
    ticket = submit_res.json()
    ticket_id = ticket["ticket_id"]
    assert ticket["status"] == "saved_locally"
    assert ticket["timeline"][0]["status"] == "saved_locally"
    assert "saved on this Mac" in ticket["timeline"][0]["message"]
    assert "sent or published" in ticket["timeline"][0]["message"]

    # 2. Query ticket status
    status_res = client.get(f"/api/support/tickets/{ticket_id}")
    assert status_res.status_code == 200
    queried = status_res.json()
    assert queried["ticket_id"] == ticket_id
    assert queried["title"] == payload["title"]
    assert "timeline" in queried

    listed = client.get("/api/support/tickets", params={"user_email": payload["user_email"], "limit": 1})
    assert listed.status_code == 200
    assert listed.json()["tickets"] == [ticket]


def test_support_drafts_allow_no_email_and_store_testimonial_consent_separately(monkeypatch, tmp_path):
    import officekit.engines.engine_comms as engine_comms
    monkeypatch.setattr(engine_comms, "TICKETS_FILE", str(tmp_path / "OfficeKit" / "tickets.json"))
    testimonial = {
        "ticket_type": "testimonial",
        "title": "A helpful toolkit",
        "description": "OfficeKit helps me finish file tasks locally.",
        "display_name": "Sam",
        "publication_consent": True,
    }
    response = client.post("/api/support/tickets", json=testimonial)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["status"] == "saved_locally"
    assert saved["user_email"] is None
    assert saved["display_name"] == "Sam"
    assert saved["publication_consent"] is True
    assert saved["timeline"][0]["message"] == "Draft saved on this Mac. Nothing was sent or published."

    feature = {
        "ticket_type": "feature",
        "title": "Add another export",
        "description": "Please add Markdown export.",
        "publication_consent": False,
    }
    feature_response = client.post("/api/support/tickets", json=feature)
    assert feature_response.status_code == 200, feature_response.text
    assert feature_response.json()["publication_consent"] is False
    assert feature_response.json()["display_name"] is None

    invalid_consent = {**feature, "publication_consent": True}
    assert client.post("/api/support/tickets", json=invalid_consent).status_code == 422
    missing_publication_name = {**testimonial, "display_name": None}
    assert client.post("/api/support/tickets", json=missing_publication_name).status_code == 422


def test_support_draft_rejects_invalid_optional_email_and_name(monkeypatch, tmp_path):
    import officekit.engines.engine_comms as engine_comms
    monkeypatch.setattr(engine_comms, "TICKETS_FILE", str(tmp_path / "OfficeKit" / "tickets.json"))
    payload = {
        "ticket_type": "bug",
        "title": "A reproducible issue",
        "description": "Steps to reproduce it.",
    }
    assert client.post("/api/support/tickets", json=payload).status_code == 200
    assert client.post("/api/support/tickets", json={**payload, "user_email": "invalid"}).status_code == 422
    assert client.post("/api/support/tickets", json={**payload, "display_name": "x" * 81}).status_code == 422


def test_legacy_received_draft_is_exposed_as_local_only_without_rewriting_store(monkeypatch, tmp_path):
    import json
    import officekit.engines.engine_comms as engine_comms
    ticket_file = tmp_path / "OfficeKit" / "tickets.json"
    monkeypatch.setattr(engine_comms, "TICKETS_FILE", str(ticket_file))
    legacy = {
        "OK-legacy-api": {
            "ticket_id": "OK-legacy-api", "user_email": "tester@example.com", "ticket_type": "bug",
            "title": "Legacy local record", "description": "This was stored locally.", "system_info": {},
            "status": "received", "created_at": 1,
            "timeline": [{"status": "received", "message": "Ticket saved locally.", "timestamp": 1}],
        }
    }
    ticket_file.parent.mkdir(parents=True)
    ticket_file.write_text(json.dumps(legacy), encoding="utf-8")

    response = client.get("/api/support/tickets/OK-legacy-api")

    assert response.status_code == 200
    assert response.json()["status"] == "saved_locally"
    assert response.json()["timeline"][0]["status"] == "saved_locally"
    assert response.json()["publication_consent"] is False
    assert json.loads(ticket_file.read_text(encoding="utf-8")) == legacy


def test_support_rejects_invalid_types_unbounded_text_and_unknown_fields(monkeypatch, tmp_path):
    import officekit.engines.engine_comms as engine_comms
    monkeypatch.setattr(engine_comms, "TICKETS_FILE", str(tmp_path / "OfficeKit" / "tickets.json"))
    payload = {
        "user_email": "tester@example.com",
        "ticket_type": "testimonial",
        "title": "A quick note",
        "description": "OfficeKit saved me time.",
        "system_info": {"platform": "macOS"},
    }
    assert client.post("/api/support/tickets", json=payload).status_code == 200

    invalid_payloads = (
        {**payload, "ticket_type": "spam"},
        {**payload, "title": " " * 3},
        {**payload, "description": "x" * 20_001},
        {**payload, "extra": "not accepted"},
        {**payload, "system_info": {"license_key": "secret"}},
    )
    for invalid in invalid_payloads:
        assert client.post("/api/support/tickets", json=invalid).status_code == 422

    assert client.get("/api/support/tickets", params={"limit": 101}).status_code == 422
    assert client.get("/api/support/tickets", params={"user_email": "not-email"}).status_code == 422
