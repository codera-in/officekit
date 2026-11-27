"""Private beta scope is enforced before any excluded operation executes."""

import asyncio
import io
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

import app as api
from officekit.engines.engine_release_profile import ReleaseScopeMiddleware, load_release_profile


def make_pdf_table_fixture():
    output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=letter)
    table = Table([
        ["Reference", "Description", "Amount"],
        ["000042", "Tea", "12.50"],
        ["A-07", "=1+1", "2.00"],
    ], repeatRows=1)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, (0, 0, 0))]))
    document.build([table])
    return output.getvalue()


def make_png_fixture():
    output = io.BytesIO()
    Image.new("RGB", (4, 2), (40, 90, 140)).save(output, format="PNG")
    return output.getvalue()


def test_profile_defaults_to_development_and_validates_startup_setting():
    assert load_release_profile({}).name == "development"
    assert load_release_profile({"OFFICEKIT_RELEASE_PROFILE": "private-beta"}).name == "private-beta"
    for value in ("", "paid", " private-beta", "PRIVATE-BETA", None):
        with pytest.raises(ValueError):
            load_release_profile({"OFFICEKIT_RELEASE_PROFILE": value})


def test_beta_manifest_exactly_matches_the_audited_shortlist():
    profile = load_release_profile({"OFFICEKIT_RELEASE_PROFILE": "private-beta"})
    assert len(profile.tool_ids) == len(set(profile.tool_ids)) == 50
    audit = Path("docs/FIRST-MAC-RELEASE.md").read_text()
    assert all(f"`{tool_id}`" in audit for tool_id in profile.tool_ids)
    assert "bank_statement" in profile.tool_ids
    assert "pdf_unlock" in profile.tool_ids
    assert "pdf_protect" in profile.tool_ids
    assert "pdf_merge" in profile.tool_ids
    assert "pdf_split" in profile.tool_ids
    assert "pdf_compress" in profile.tool_ids
    assert "pdf_to_images" in profile.tool_ids
    assert "pdf_metadata_strip" in profile.tool_ids
    assert "pdf_table_extractor" in profile.tool_ids
    assert "pdf_text_extract" in profile.tool_ids
    assert "pdf_delete_pages" in profile.tool_ids
    assert "pdf_reorder_pages" in profile.tool_ids
    assert "image_converter" in profile.tool_ids
    assert "image_resize" in profile.tool_ids
    assert "image_exif_strip" in profile.tool_ids
    assert "voice_transcription" in profile.tool_ids
    assert "meeting_notes" in profile.tool_ids
    assert "system_info" in profile.tool_ids
    assert "system_resources" in profile.tool_ids
    assert profile.allows("POST", "/api/convert/image")
    assert profile.allows("POST", "/api/image/resize")
    assert profile.allows("POST", "/api/images/resize")
    assert profile.allows("POST", "/api/image/metadata")
    assert profile.allows("POST", "/api/extract/statement")
    assert profile.allows("POST", "/api/export/csv")
    assert profile.allows("POST", "/api/export/excel")
    assert profile.allows("POST", "/api/export/xls")
    assert profile.allows("POST", "/api/pdf/unlock")
    assert profile.allows("POST", "/api/pdf/protect")
    assert profile.allows("POST", "/api/pdf/merge")
    assert profile.allows("POST", "/api/pdf/split/groups")
    assert profile.allows("POST", "/api/pdf/compress")
    assert profile.allows("POST", "/api/pdf/images")
    assert profile.allows("POST", "/api/pdf/metadata")
    assert profile.allows("POST", "/api/pdf/page-counts")
    assert profile.allows("POST", "/api/pdf/tables")
    assert profile.allows("POST", "/api/pdf/tables/export")
    assert profile.allows("POST", "/api/pdf/text")
    assert profile.allows("POST", "/api/pdf/pages/delete")
    assert profile.allows("POST", "/api/pdf/pages/reorder")
    assert profile.allows("POST", "/api/dictate/format-notes")
    assert profile.allows("POST", "/api/dictate/cleanup")
    assert profile.allows("GET", "/api/system/info")
    assert profile.allows("GET", "/api/system/resources")
    assert profile.allows("POST", "/api/pdf/page-thumbnails")
    assert profile.allows("POST", "/api/calculator/loan-emi")
    assert "everyday_percentages" in profile.tool_ids
    for path in ("/api/calculator/percent-of", "/api/calculator/percentage-change", "/api/calculator/discount"):
        assert profile.allows("POST", path)
    assert profile.allows("GET", "/api/release")
    assert not profile.allows("GET", "/api/calculator/loan-emi")
    assert not profile.allows("POST", "/api/calculator/loan-emi/extra")
    assert profile.allows("POST", "/api/workspaces")
    assert profile.allows("GET", "/api/workspaces/0123456789abcdef0123456789abcdef")
    assert profile.allows("POST", "/api/workspaces/0123456789abcdef0123456789abcdef/hash-reports")
    assert profile.allows("GET", "/api/workspaces/0123456789abcdef0123456789abcdef/artifacts/abcdef0123456789abcdef0123456789")
    assert not profile.allows("GET", "/api/workspaces/../release")
    assert not profile.allows("POST", "/api/workspaces/0123456789abcdef0123456789abcdef/unknown")
    assert not profile.allows("DELETE", "/api/workspaces/0123456789abcdef0123456789abcdef/extra")
    assert load_release_profile({}).allows("POST", "/api/extract/statement")


def test_beta_profile_covers_every_route_the_shipped_duplicate_finder_calls():
    # Routes the beta-shipped dup_finder uses: the temporary workspace import, its duplicate report
    # and its clear (index.html), and the file-selection, file-job, results and Show in Finder reveal calls
    # (scripts/smoke-duplicate-finder.mjs, assets/officekit-files.js via file_job_reveal).
    beta = load_release_profile({"OFFICEKIT_RELEASE_PROFILE": "private-beta"})
    job = "0123456789abcdef0123456789abcdef"
    workspace = "fedcba9876543210fedcba9876543210"
    calls = [
        ("POST", "/api/workspaces"),
        ("POST", f"/api/workspaces/{workspace}/duplicate-reports"),
        ("DELETE", f"/api/workspaces/{workspace}"),
        ("POST", "/api/file-selections"),
        ("POST", "/api/file-jobs"),
        ("GET", f"/api/file-jobs/{job}"),
        ("GET", f"/api/file-jobs/{job}/results"),
        ("POST", f"/api/file-jobs/{job}/reveals"),
    ]
    missing = [f"{method} {path}" for method, path in calls if not beta.allows(method, path)]
    assert missing == []
    assert not beta.allows("POST", f"/api/file-jobs/{job}/reveals/extra")
    assert not beta.allows("GET", f"/api/file-jobs/{job}/reveals")


@pytest.mark.parametrize("document", [
    {}, {"tool_ids": ["loan_emi", "loan_emi"], "routes": []},
    {"tool_ids": [42], "routes": []}, {"tool_ids": [], "routes": []},
    {"tool_ids": ["loan_emi"], "routes": [["PATCH", "/api/calculator/loan-emi"]]},
    {"tool_ids": ["loan_emi"], "routes": [["POST", "/api/calculator/loan-emi/**"]]},
    {"tool_ids": ["loan_emi"], "routes": [["POST", "/api/calculator/loan-emi"], ["POST", "/api/calculator/loan-emi"]]},
])
def test_invalid_manifest_fails_closed(document):
    with pytest.raises(ValueError):
        load_release_profile({"OFFICEKIT_RELEASE_PROFILE": "private-beta"}, document)


def test_profile_payload_is_detached_and_explicit():
    profile = load_release_profile({"OFFICEKIT_RELEASE_PROFILE": "private-beta"})
    data = profile.payload()
    assert set(data) == {"profile", "tool_ids"}
    assert data["profile"] == "private-beta"
    data["tool_ids"].clear()
    assert len(profile.tool_ids) == 50


def test_beta_api_discovery_filters_aliases_and_direct_calls_never_execute():
    beta = load_release_profile({"OFFICEKIT_RELEASE_PROFILE": "private-beta"})
    with patch.object(api, "RELEASE_PROFILE", beta):
        client = TestClient(api.app)
        release = client.get("/api/release").json()
        assert {key: release[key] for key in beta.payload()} == beta.payload()
        catalogue = client.get("/api/tools/search").json()["tools"]
        assert {tool["id"] for tool in catalogue} == set(beta.tool_ids)
        for query in ("pdf to csv", "pdf to xls", "pdf to xlsx"):
            assert [tool["id"] for tool in client.get("/api/tools/search", params={"q": query}).json()["tools"]] == ["pdf_table_extractor", "bank_statement"]
        unlock_results = [tool["id"] for tool in client.get("/api/tools/search", params={"q": "unlock pdf"}).json()["tools"]]
        assert unlock_results[:2] == ["pdf_unlock", "pdf_metadata_strip"]
        assert [tool["id"] for tool in client.get("/api/tools/search", params={"q": "protect pdf"}).json()["tools"]] == ["pdf_protect"]
        assert [tool["id"] for tool in client.get("/api/tools/search", params={"q": "merge pdf"}).json()["tools"]] == ["pdf_merge"]
        assert [tool["id"] for tool in client.get("/api/tools/search", params={"q": "pdf to text"}).json()["tools"]] == ["pdf_text_extract", "pdf_table_extractor"]
        assert client.get("/api/tools/search", params={"q": "delete pages from pdf"}).json()["tools"][0]["id"] == "pdf_delete_pages"
        assert client.get("/api/tools/search", params={"q": "reorder pdf pages"}).json()["tools"][0]["id"] == "pdf_reorder_pages"
        assert [tool["id"] for tool in client.get("/api/tools/search", params={"q": "image converter"}).json()["tools"]] == ["image_converter"]
        assert [tool["id"] for tool in client.get("/api/tools/search", params={"q": "resize images"}).json()["tools"]] == ["image_resize"]
        assert [tool["id"] for tool in client.get("/api/tools/search", params={"q": "remove image metadata"}).json()["tools"]] == ["image_exif_strip"]
        split_results = [tool["id"] for tool in client.get("/api/tools/search", params={"q": "split pdf"}).json()["tools"]]
        assert split_results[0] == "pdf_split"
        assert client.get("/api/tools/search", params={"q": "dictation"}).json()["tools"][0]["id"] == "voice_transcription"
        assert client.get("/api/tools/search", params={"q": "meeting notes"}).json()["tools"][0]["id"] == "meeting_notes"
        assert [tool["id"] for tool in client.get("/api/tools/search", params={"q": "system information"}).json()["tools"]] == ["system_info"]
        assert any(tool["id"] == "file_split_join" for tool in client.get("/api/tools/search", params={"q": "file split"}).json()["tools"])
        with patch.object(api, "read_api_upload", side_effect=AssertionError("Excluded input was read")):
            for path in ("/api/convert/data", "/api/license/activate", "/api/network/ping"):
                response = client.post(path, params={"profile": "development"}, json={"release_profile": "development"})
                assert response.status_code == 404
                assert response.json() == {"detail": "This operation is not available in the OfficeKit private beta."}
        resized = client.post(
            "/api/image/resize",
            data={"max_width": "8", "max_height": "8"},
            files={"file": ("tiny.png", make_png_fixture(), "image/png")},
        )
        assert resized.status_code == 200
        assert resized.headers["content-type"].startswith("image/png")
        statement = client.post(
            "/api/extract/statement",
            files={"file": ("statement.csv", b"Date,Description,Credit,Balance\n2024-01-01,Opening balance,,100.00\n2024-01-02,Transfer,25.00,125.00\n", "text/csv")},
        )
        assert statement.status_code == 200
        assert statement.json()["reconciliation"]["status"] == "verified"
        assert len(statement.json()["transactions"]) == 2
        assert client.post("/api/export/csv", json=statement.json()).status_code == 200
        from io import BytesIO
        import pikepdf
        plain = Path("tests/fixtures/pdf-protect-source.pdf").read_bytes()
        locked_buffer = BytesIO()
        with pikepdf.open(BytesIO(plain)) as document:
            document.save(locked_buffer, encryption=pikepdf.Encryption(owner="fixture-owner", user="known-password", R=6))
        unlocked = client.post(
            "/api/pdf/unlock",
            data={"password": "known-password"},
            files={"file": ("protected.pdf", locked_buffer.getvalue(), "application/pdf")},
        )
        assert unlocked.status_code == 200
        assert unlocked.headers["content-type"].startswith("application/pdf")
        with pikepdf.open(BytesIO(unlocked.content)) as document:
            assert not document.is_encrypted
            assert len(document.pages) == 1
        protected = client.post(
            "/api/pdf/protect",
            data={"password": "known-password"},
            files={"file": ("source.pdf", plain, "application/pdf")},
        )
        assert protected.status_code == 200
        assert protected.headers["content-type"].startswith("application/pdf")
        with pikepdf.open(BytesIO(protected.content), password="known-password") as document:
            assert document.is_encrypted
            assert len(document.pages) == 1
        rejected_protection = client.post(
            "/api/pdf/protect",
            data={"password": ""},
            files={"file": ("source.pdf", plain, "application/pdf")},
        )
        assert rejected_protection.status_code == 422
        assert client.post("/api/calculator/loan-emi", json={"principal": 1200, "annual_interest_rate": 0, "tenure_years": 1}).json()["monthly_emi"] == 100
        assert client.get("/api/health").status_code == 200
        assert client.get("/").status_code == 200


def test_beta_pdf_table_routes_preview_and_export_formula_safe_files():
    beta = load_release_profile({"OFFICEKIT_RELEASE_PROFILE": "private-beta"})
    source = make_pdf_table_fixture()
    with patch.object(api, "RELEASE_PROFILE", beta):
        client = TestClient(api.app)
        preview = client.post("/api/pdf/tables", files={"file": ("inventory.pdf", source, "application/pdf")})
        assert preview.status_code == 200, preview.text
        table = preview.json()["tables"][0]
        assert table["preview_rows"] == [
            ["Reference", "Description", "Amount"],
            ["000042", "Tea", "12.50"],
            ["A-07", "=1+1", "2.00"],
        ]
        for export_format, signature in (
            ("csv", b"\xef\xbb\xbf"),
            ("xls", bytes.fromhex("d0cf11e0a1b11ae1")),
            ("xlsx", bytes.fromhex("504b0304")),
        ):
            response = client.post(
                "/api/pdf/tables/export",
                files={"file": ("inventory.pdf", source, "application/pdf")},
                data={
                    "page_number": str(table["page_number"]),
                    "table_number": str(table["table_number"]),
                    "format": export_format,
                },
            )
            assert response.status_code == 200, response.text
            assert response.content.startswith(signature)
            if export_format == "csv":
                assert b"000042,Tea,12.50" in response.content
                assert b"A-07,'=1+1,2.00" in response.content
    assert source.startswith(b"%PDF-")


def test_beta_allows_selected_workspace_import_inspection_and_cleanup():
    from tempfile import TemporaryDirectory
    from officekit.engines.engine_workspaces import FileWorkspaceStore

    beta = load_release_profile({"OFFICEKIT_RELEASE_PROFILE": "private-beta"})
    with TemporaryDirectory() as root:
        with patch.object(api, "RELEASE_PROFILE", beta), patch.object(api, "workspace_store", FileWorkspaceStore(root=root)):
            client = TestClient(api.app)
            imported = client.post("/api/workspaces", files=[("files", ("note.txt", b"local fixture"))])
            assert imported.status_code == 201
            workspace_id = imported.json()["workspace_id"]
            report = client.post(
                f"/api/workspaces/{workspace_id}/hash-reports",
                json={"filenames": ["note.txt"], "algorithm": "sha256"},
            )
            assert report.status_code == 200
            assert report.json()["files"][0]["name"] == "note.txt"
            assert client.delete(f"/api/workspaces/{workspace_id}").status_code == 204
            assert client.get(f"/api/workspaces/{workspace_id}").status_code == 404


def test_scope_middleware_forwards_non_http_scopes():
    seen = []
    async def downstream(scope, receive, send):
        seen.append(scope)
    scope = {"type": "lifespan"}
    middleware = ReleaseScopeMiddleware(downstream, profile=lambda: load_release_profile({}))
    asyncio.run(middleware(scope, None, None))
    assert seen == [scope]
