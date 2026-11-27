from fastapi import FastAPI
from fastapi.testclient import TestClient
import io
from datetime import date

import pytest
from PIL import Image
from pypdf import PdfReader

from officekit.engines.engine_file_selections import FileSelectionStore
from officekit.invoices.storage import InvoiceLibraries
from officekit.invoices.routes import create_invoice_router
from officekit.invoices import models as m
from officekit.invoices.domain import InvoiceService


@pytest.fixture
def api_world(tmp_path):
    selections = FileSelectionStore(native_token="native")
    folder = tmp_path / "folder"
    folder.mkdir()
    selections_meta = selections.register_native([str(folder)], "read-write", "native")
    libraries = InvoiceLibraries(selections, tmp_path / "private" / "bindings.json")
    app = FastAPI()
    app.include_router(create_invoice_router(libraries))
    client = TestClient(app)
    attached = client.post("/api/invoice-libraries", json={"selection_id": selections_meta["id"]}).json()
    return client, libraries, "/api/invoice-libraries/" + attached["id"], tmp_path


def revision(world):
    client, _, root, _ = world
    return client.get(root).json()["revision"]


def post(world, path, body):
    client, _, root, _ = world
    response = client.post(root + path, json={"expected_revision": revision(world), **body})
    assert response.status_code in (200, 201), response.text
    return response.json()


def test_typed_invoice_routes_accept_native_folder_grants_and_create_profiles(tmp_path):
    selections = FileSelectionStore(native_token="native")
    folder = tmp_path / "selected"
    folder.mkdir()
    selection = selections.register_native([str(folder)], "read-write", "native")
    libraries = InvoiceLibraries(selections, tmp_path / "private" / "bindings.json")
    app = FastAPI()
    app.include_router(create_invoice_router(libraries))
    client = TestClient(app)
    attached = client.post("/api/invoice-libraries", json={"selection_id": selection["id"]})
    assert attached.status_code == 201, attached.text
    root = "/api/invoice-libraries/" + attached.json()["id"]
    business = client.post(root + "/businesses", json={"name": "Studio", "profile_name": "International / USD", "expected_revision": 0})
    assert business.status_code == 201, business.text
    assert business.json()["currencies"][0]["code"] == "USD"
    assert client.get(root + "/businesses").json()["items"][0]["id"] == business.json()["id"]
    assert client.post(root + "/businesses", json={"name": "Invalid", "expected_revision": 0, "path": "/tmp"}).status_code == 422
    assert client.post(root + "/reconnections", json={}).status_code == 403


def test_real_router_crud_pdf_payment_history_backup_restore_and_reports(api_world):
    client, libraries, root, tmp_path = api_world
    business = post(api_world, "/businesses", {"name": "Studio", "profile_name": "Global / USD"})
    business_update = {key: value for key, value in business.items() if key in m.Business.model_fields}
    business_update["address"] = "Global address"
    result = client.put(root + "/businesses/" + business["id"], json={**business_update, "expected_revision": revision(api_world)})
    assert result.status_code == 200 and result.json()["address"] == "Global address"
    assert client.get(root + "/businesses/" + business["id"]).status_code == 200
    saved_client = post(api_world, "/clients", {"business_id": business["id"], "name": "Client"})
    updated_client = client.put(root + "/clients/" + saved_client["id"], json={"expected_revision": revision(api_world), "business_id": business["id"], "name": "Client updated"})
    assert updated_client.status_code == 200
    assert client.get(root + "/clients/" + saved_client["id"]).json()["name"] == "Client updated"
    item = post(api_world, "/items", {"business_id": business["id"], "private_name": "Saved item", "description": "Base", "rate": "100"})
    assert client.get(root + "/items/" + item["id"]).json()["rate"] == "100"
    assert client.put(root + "/items/" + item["id"], json={"expected_revision": revision(api_world), "business_id": business["id"], "private_name": "Saved item", "description": "Updated", "rate": "100"}).status_code == 200
    draft_payload = {"business_id": business["id"], "client_id": saved_client["id"], "issue_date": "2026-10-25", "due_date": "2026-11-08", "lines": [{"description": "Invoice details", "rate": "100", "item_id": item["id"]}]}
    document = post(api_world, "/documents", draft_payload)
    assert client.get(root + "/documents/" + document["id"]).json()["totals"]["total"] == "100.00"
    assert client.put(root + "/documents/" + document["id"], json={"expected_revision": revision(api_world), **draft_payload, "notes": "Updated invoice only"}).status_code == 200
    assert client.get(root + "/documents", params={"start": "2026-10-01", "end": "2026-10-31", "sort": "amount", "order": "asc"}).json()["items"][0]["id"] == document["id"]
    preview = client.post(root + "/document-previews", json={"expected_revision": revision(api_world), "document_id": document["id"]})
    assert preview.status_code == 200 and preview.content.startswith(b"%PDF")
    assert "Updated invoice only" in PdfReader(io.BytesIO(preview.content)).pages[0].extract_text()
    issued = post(api_world, "/documents/" + document["id"] + "/transitions", {"action": "issue"})
    assert issued["state"] == "issued" and issued["archive_status"] == "ready"
    assert post(api_world, "/documents/" + document["id"] + "/archives", {})["archive_status"] == "ready"
    pdf = client.get(root + "/documents/" + document["id"] + "/pdf")
    assert pdf.headers["content-type"] == "application/pdf"
    payment = post(api_world, "/documents/" + document["id"] + "/payments", {"amount": "25", "date": "2026-10-26", "idempotency_key": m.new_id()})
    assert payment["document"]["balance"] == "75.00"
    payments = client.get(root + "/documents/" + document["id"] + "/payments").json()["items"]
    correction = post(api_world, "/documents/" + document["id"] + "/payment-corrections", {"payment_id": payments[0]["id"], "reason": "Wrong transfer"})
    assert correction["document"]["balance"] == "100.00"
    schedule = post(api_world, "/schedules", {"business_id": business["id"], "draft": draft_payload, "anchor_date": "2026-10-25", "end_count": 1})
    assert client.get(root + "/schedules/" + schedule["id"]).status_code == 200
    assert client.put(root + "/schedules/" + schedule["id"], json={"expected_revision": revision(api_world), "business_id": business["id"], "draft": draft_payload, "anchor_date": "2026-10-25", "end_count": 1}).status_code == 200
    assert len(post(api_world, "/recurring-draft-batches", {})["created_document_ids"]) == 1
    report_query = {"business_id": business["id"], "currency_id": business["default_currency_id"], "start": "2026-10-01", "end": "2026-10-31"}
    report = client.get(root + "/reports", params=report_query)
    assert report.status_code == 200 and report.json()["received"] == "0.00"
    assert client.get(root + "/reports.csv", params=report_query).content.startswith(b"\xef\xbb\xbfClient")
    history = client.get(root + "/history")
    assert history.status_code == 200, history.text
    assert any(entry["action"] == "document_issue" for entry in history.json()["items"])
    assert client.post(root + "/reloads", json={}).status_code == 200
    assert client.post(root + "/reconnections", json={}, headers={"X-OfficeKit-Native-Grant": "native"}).status_code == 200
    backup = client.post(root + "/backups", json={})
    assert backup.status_code == 200 and backup.content.startswith(b"PK")
    backup_file = tmp_path / "backup.zip"
    backup_file.write_bytes(backup.content)
    destination = tmp_path / "restore"
    destination.mkdir()
    target = libraries.selections.register_native([str(destination)], "read-write", "native")
    source = libraries.selections.register_native([str(backup_file)], "read", "native")
    restored = client.post("/api/invoice-restorations", json={"selection_id": target["id"], "backup_selection_id": source["id"]})
    assert restored.status_code == 201, restored.text
    assert client.get("/api/invoice-libraries").status_code == 200


def test_logo_asset_routes_and_all_release_validation_failures(api_world):
    client, libraries, root, tmp_path = api_world
    logo = tmp_path / "logo.png"
    Image.new("RGB", (4, 2), "red").save(logo)
    selected = libraries.selections.register_native([str(logo)], "read", "native")
    response = client.post(root + "/assets", json={"expected_revision": 0, "selection_id": selected["id"]})
    assert response.status_code == 201, response.text
    assert client.get(root + "/assets/" + response.json()["id"]).content.startswith(b"\x89PNG")
    folder = libraries.selections.register_native([str(tmp_path)], "read", "native")
    assert client.post(root + "/assets", json={"expected_revision": revision(api_world), "selection_id": folder["id"]}).status_code == 422
    assert client.get(root + "/assets/invalid").status_code == 422
    assert client.get(root + "/businesses/" + m.new_id()).status_code == 404
    assert client.get("/api/invoice-libraries/" + m.new_id()).status_code == 404
    app = FastAPI()
    app.include_router(create_invoice_router(libraries, release_profile="private-beta"))
    assert TestClient(app).get("/api/invoice-libraries").status_code == 403


def test_quote_conversion_route(api_world):
    client, libraries, root, _ = api_world
    business = post(api_world, "/businesses", {"name": "Studio"})
    saved_client = post(api_world, "/clients", {"business_id": business["id"], "name": "Client"})
    quote = post(api_world, "/documents", {"business_id": business["id"], "client_id": saved_client["id"], "kind": "quote", "issue_date": "2026-10-25", "lines": [{"description": "Quote", "rate": "100"}]})
    post(api_world, "/documents/" + quote["id"] + "/transitions", {"action": "issue"})
    post(api_world, "/documents/" + quote["id"] + "/transitions", {"action": "accept"})
    converted = post(api_world, "/document-conversions", {"source_quote_id": quote["id"], "idempotency_key": m.new_id()})
    assert converted["documents"][0]["totals"]["total"] == "100.00"
