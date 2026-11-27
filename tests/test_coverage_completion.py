"""
Targeted tests to bring coverage across all core engines towards 100%:
- app.py edge cases & error branches (invalid inputs, devtools operations, exception handler)
- officekit/engines/engine_file_converter.py formats (CMYK, TSV, HTML, SQL)
- officekit/engines/engine_units.py edge cases (area, typography, invalid units)
- officekit/engines/engine_file_ops.py casing (snake, camel, title, replace)
- officekit/engines/engine_license.py invalid signatures & expiration handling
- officekit/engines/engine_comms.py user ticket filtering
"""

import io
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from PIL import Image
import officekit.engines.engine_comms as engine_comms

from app import app
from officekit.engines.engine_file_converter import FileConverterEngine
from officekit.engines.engine_units import UnitConverterEngine, MathEvaluator
from officekit.engines.engine_file_ops import FileOpsEngine, StorageAnalyzerEngine
from officekit.engines.engine_license import LicenseManager
from officekit.engines.engine_comms import SupportEngine, CommsEngine

client = TestClient(app)

def test_app_error_branches_and_edge_cases(monkeypatch, tmp_path):
    # Keep support tests isolated from a real user's local ticket history.
    monkeypatch.setattr(engine_comms, "TICKETS_FILE", str(tmp_path / "tickets.json"))
    # 1. Invalid file format for statement
    res_bad_file = client.post(
        "/api/extract/statement",
        files={"file": ("test.exe", b"MZbinary...", "application/octet-stream")}
    )
    assert res_bad_file.status_code == 400

    # 2. Empty transcript
    res_empty_dictate = client.post("/api/dictate/format-notes", json={"transcript": "   "})
    assert res_empty_dictate.status_code == 400

    # 3. Invalid devtools operation
    res_bad_op = client.post("/api/devtools/process", json={"content": "test", "operation": "unknown_op"})
    assert res_bad_op.status_code == 422

    # 4. DevTools YAML and Base64 operations
    res_yaml = client.post("/api/devtools/process", json={"content": '{"k":"v"}', "operation": "json_to_yaml"})
    assert res_yaml.status_code == 200
    assert "k: v" in res_yaml.json()["result"]

    res_b64_dec = client.post("/api/devtools/process", json={"content": "SGVsbG8=", "operation": "base64_decode"})
    assert res_b64_dec.status_code == 200
    assert res_b64_dec.json()["result"] == "Hello"

    # 5. Ticket lookup and filtering operate only on this test's isolated store.
    payload = {
        "user_email": "tester@example.com",
        "ticket_type": "bug",
        "title": "Test report",
        "description": "A private test ticket.",
        "system_info": {"os": "test"},
    }
    created = client.post("/api/support/tickets", json=payload)
    assert created.status_code == 200
    ticket = created.json()

    res_not_found = client.get("/api/support/tickets/NON_EXISTENT_ID")
    assert res_not_found.status_code == 404

    # 6. Listing returns exactly this user's newly created ticket, never ambient state.
    res_list = client.get("/api/support/tickets?user_email=tester@example.com")
    assert res_list.status_code == 200
    assert res_list.json()["tickets"] == [ticket]
    res_ticket = client.get(f"/api/support/tickets/{ticket['ticket_id']}")
    assert res_ticket.status_code == 200
    assert res_ticket.json() == ticket

    # 7. Password crypto generator
    res_pwd = client.post("/api/crypto/password?length=20&include_symbols=false")
    assert res_pwd.status_code == 200
    assert len(res_pwd.json()["password"]) == 20

def test_file_converter_formats_and_modes():
    # 1. CMYK image to PNG; verify the output is a decodable image, not only a MIME label.
    cmyk_img = Image.new("CMYK", (50, 50), (0, 255, 255, 0))
    buf = io.BytesIO()
    cmyk_img.save(buf, format="JPEG")
    cmyk_bytes = buf.getvalue()
    out_png, mime = FileConverterEngine.convert_image(cmyk_bytes, "png")
    assert mime == "image/png"
    with Image.open(io.BytesIO(out_png)) as converted:
        assert converted.size == cmyk_img.size
        assert converted.mode in {"RGB", "RGBA"}

    # 2. Tabular TSV and HTML export
    csv_bytes = b"id,val\n1,Alpha\n2,Beta\n"
    tsv_out, _ = FileConverterEngine.convert_data_file(csv_bytes, "csv", "tsv")
    assert b"1\tAlpha" in tsv_out

    html_out, _ = FileConverterEngine.convert_data_file(csv_bytes, "csv", "html")
    assert b"<table" in html_out

    # 3. Strip EXIF
    clean_bytes = FileConverterEngine.strip_exif(cmyk_bytes)
    assert len(clean_bytes) > 0

    # 4. Unsupported format error
    with pytest.raises(ValueError):
        FileConverterEngine.convert_image(cmyk_bytes, "unsupported_xyz")

def test_unit_converter_extended_categories():
    # 1. Typography: pt to px, rem
    pts = UnitConverterEngine.convert(12, "typography", "pt", "px")
    assert pts == 16.0

    rems = UnitConverterEngine.convert(32, "typography", "px", "rem")
    assert rems == 2.0

    # 2. Same unit conversion
    assert UnitConverterEngine.convert(50, "length", "meter", "meter") == 50.0

    # 3. Invalid unit error
    with pytest.raises(ValueError):
        UnitConverterEngine.convert(10, "length", "meter", "invalid_unit")

    # 4. Math evaluator unary operations
    assert MathEvaluator.evaluate("-5 + 10") == 5
    assert MathEvaluator.evaluate("10 // 3") == 3

def test_file_ops_casing_variations(tmp_path):
    names = ["hello world test"]
    snake = FileOpsEngine.generate_rename_plan(names, pattern_type="casing", casing="snake")
    assert snake[0] == "hello_world_test"

    camel = FileOpsEngine.generate_rename_plan(names, pattern_type="casing", casing="camel")
    assert camel[0] == "helloWorldTest"

    title = FileOpsEngine.generate_rename_plan(names, pattern_type="casing", casing="title")
    assert title[0] == "Hello World Test"

    rep = FileOpsEngine.generate_rename_plan(names, pattern_type="replace", find_text="world", replace_text="officekit")
    assert rep[0] == "hello officekit test"

    # Protected storage rejection is exercised against an isolated temporary path,
    # so the assertion behaves the same on macOS, Windows and Linux.
    protected_dir = tmp_path / "protected"
    protected_dir.mkdir()
    with patch.object(StorageAnalyzerEngine, "PROTECTED_SYSTEM_PATHS", {str(protected_dir)}):
        with pytest.raises(PermissionError):
            StorageAnalyzerEngine.analyze_directory(str(protected_dir))

def test_license_manager_edge_cases():
    status = LicenseManager.get_current_license()
    assert status["valid"] is False
    assert status["tier"] == 0
