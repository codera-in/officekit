import csv
import io

import pytest

pytest.importorskip("pdfplumber")
pytest.importorskip("fastapi")
pytest.importorskip("openpyxl")
pytest.importorskip("reportlab")

import pikepdf
import xlrd
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from app import app
from officekit.engines.engine_pdf_tables import (
    PdfTableExportError,
    PdfTableInputError,
    export_pdf_table,
    extract_pdf_tables,
)


def make_table_pdf(rows):
    output = io.BytesIO()
    document = SimpleDocTemplate(output, pagesize=letter)
    table = Table(rows, repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    document.build([table])
    return output.getvalue()


def make_unruled_date_table_pdf():
    """Mimic statements where vertical rules exist but transactions wrap vertically."""
    from reportlab.pdfgen import canvas

    output = io.BytesIO()
    document = canvas.Canvas(output, pagesize=letter)
    x_positions = [36, 100, 330, 425, 495, 576]
    top, header_bottom, bottom = 650, 625, 520
    document.setLineWidth(0.6)
    for x_position in x_positions:
        document.line(x_position, bottom, x_position, top)
    document.line(x_positions[0], top, x_positions[-1], top)
    document.line(x_positions[0], header_bottom, x_positions[-1], header_bottom)
    document.line(x_positions[0], bottom, x_positions[-1], bottom)

    headers = ["Date", "Description", "Reference", "Debit", "Balance"]
    for index, value in enumerate(headers):
        document.drawString(x_positions[index] + 4, 635, value)

    rows = [
        ("21/09/26", "TRANSFER TO VENDOR", "REF-001", "", "1,000.00"),
        ("25/09/26", "NEFT PAYMENT LONG", "REF-002", "200.00", "800.00"),
        ("26/09/26", "MONTHLY SERVICE FEE", "REF-003", "50.00", "750.00"),
    ]
    row_tops = [602, 570, 538]
    for row, row_top in zip(rows, row_tops, strict=True):
        for index, value in enumerate(row):
            if value:
                document.drawString(x_positions[index] + 4, row_top, value)
        if row[0] == "25/09/26":
            document.drawString(x_positions[1] + 4, row_top - 12, "WITH WRAPPED NARRATION")
    document.save()
    return output.getvalue()


def make_encrypted_pdf():
    source = pikepdf.new()
    source.add_blank_page(page_size=(300, 400))
    output = io.BytesIO()
    source.save(output, encryption=pikepdf.Encryption(owner="owner", user="secret", R=6))
    return output.getvalue()


def test_pdf_table_preview_returns_page_table_dimensions_and_raw_rows():
    source = make_table_pdf([
        ["Account", "Amount"],
        ["A-001", "1,250.00"],
        ["Ångström", "=1+1"],
    ])

    result = extract_pdf_tables(source)

    assert result["page_count"] == 1
    assert result["tables"] == [{
        "page_number": 1,
        "table_number": 1,
        "row_count": 3,
        "column_count": 2,
        "preview_rows": [
            ["Account", "Amount"],
            ["A-001", "1,250.00"],
            ["Ångström", "=1+1"],
        ],
    }]


def test_pdf_table_preview_does_not_claim_unruled_prose_is_a_table():
    source = make_table_pdf([["A paragraph with two words but no table grid."]])
    assert extract_pdf_tables(source)["tables"] == []


def test_pdf_table_preview_splits_wrapped_date_rows_using_grid_columns():
    result = extract_pdf_tables(make_unruled_date_table_pdf())

    assert len(result["tables"]) == 1
    table = result["tables"][0]
    assert table["row_count"] == 4
    assert table["column_count"] == 5
    assert table["preview_rows"] == [
        ["Date", "Description", "Reference", "Debit", "Balance"],
        ["21/09/26", "TRANSFER TO VENDOR", "REF-001", "", "1,000.00"],
        ["25/09/26", "NEFT PAYMENT LONG WITH WRAPPED NARRATION", "REF-002", "200.00", "800.00"],
        ["26/09/26", "MONTHLY SERVICE FEE", "REF-003", "50.00", "750.00"],
    ]


def test_pdf_table_export_keeps_identifiers_and_neutralizes_formula_cells():
    source = make_table_pdf([
        ["ID", "Formula-like text"],
        ["000042", "=1+1"],
        ["A-07", "@SUM(A1:A2)"],
    ])

    csv_bytes, csv_type = export_pdf_table(source, 1, 1, "csv")
    xlsx_bytes, xlsx_type = export_pdf_table(source, 1, 1, "xlsx")

    assert csv_type == "text/csv; charset=utf-8"
    assert csv_bytes.startswith(b"\xef\xbb\xbf")
    assert b"000042" in csv_bytes
    assert b"'=1+1" in csv_bytes
    assert xlsx_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    worksheet = load_workbook(io.BytesIO(xlsx_bytes), data_only=False).active
    assert worksheet.cell(2, 1).value == "000042"
    assert worksheet.cell(2, 2).value == "'=1+1"
    assert worksheet.cell(3, 2).value == "'@SUM(A1:A2)"
    assert all(cell.data_type != "f" for row in worksheet.iter_rows() for cell in row)


def test_pdf_table_export_supports_legacy_xls_without_evaluating_formula_like_text():
    source = make_table_pdf([
        ["ID", "Formula-like text"],
        ["000042", "=1+1"],
        ["A-07", "@SUM(A1:A2)"],
    ])

    xls_bytes, media_type = export_pdf_table(source, 1, 1, "xls")

    workbook = xlrd.open_workbook(file_contents=xls_bytes, on_demand=True)
    try:
        sheet = workbook.sheet_by_index(0)
        assert media_type == "application/vnd.ms-excel"
        assert sheet.nrows == 3
        assert sheet.ncols == 2
        assert sheet.cell_value(1, 0) == "000042"
        assert sheet.cell_value(1, 1) == "'=1+1"
        assert sheet.cell_value(2, 1) == "'@SUM(A1:A2)"
    finally:
        workbook.release_resources()


def test_pdf_table_export_rejects_missing_table_and_unknown_format():
    source = make_table_pdf([["A", "B"], ["1", "2"]])
    with pytest.raises(PdfTableExportError, match="unavailable"):
        export_pdf_table(source, 2, 1, "csv")
    with pytest.raises(PdfTableExportError, match="CSV, XLS or XLSX"):
        export_pdf_table(source, 1, 1, "json")


def test_pdf_table_engine_rejects_empty_oversized_corrupt_and_encrypted_inputs(monkeypatch):
    from officekit.engines.engine_pdf_tables import MAX_PDF_BYTES

    with pytest.raises(PdfTableInputError):
        extract_pdf_tables(b"")
    with pytest.raises(PdfTableInputError, match="size"):
        extract_pdf_tables(b"x" * (MAX_PDF_BYTES + 1))
    with pytest.raises(PdfTableInputError, match="could not be read"):
        extract_pdf_tables(b"not a PDF")
    with pytest.raises(PdfTableInputError, match="password-protected"):
        extract_pdf_tables(make_encrypted_pdf())


def test_pdf_table_engine_enforces_page_limit(monkeypatch):
    source = make_table_pdf([["A", "B"], ["1", "2"]])
    monkeypatch.setattr("officekit.engines.engine_pdf_tables.MAX_PDF_PAGES", 0)
    with pytest.raises(PdfTableInputError, match="1 to 50 pages"):
        extract_pdf_tables(source)


def test_pdf_table_api_previews_and_exports_only_the_selected_table():
    client = TestClient(app)
    source = make_table_pdf([["Product", "Count"], ["Tea", "3"]])

    preview = client.post("/api/pdf/tables", files={"file": ("inventory.pdf", source, "application/pdf")})
    assert preview.status_code == 200, preview.text
    assert preview.json()["tables"][0]["preview_rows"] == [["Product", "Count"], ["Tea", "3"]]

    exported = client.post(
        "/api/pdf/tables/export",
        files={"file": ("inventory.pdf", source, "application/pdf")},
        data={"page_number": "1", "table_number": "1", "format": "csv"},
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    assert b"Product,Count" in exported.content
    assert b"Tea,3" in exported.content

    exported_xlsx = client.post(
        "/api/pdf/tables/export",
        files={"file": ("inventory.pdf", source, "application/pdf")},
        data={"page_number": "1", "table_number": "1", "format": "xlsx"},
    )
    assert exported_xlsx.status_code == 200, exported_xlsx.text
    assert exported_xlsx.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    workbook = load_workbook(io.BytesIO(exported_xlsx.content), data_only=False)
    assert workbook.active.cell(2, 1).value == "Tea"
    assert workbook.active.cell(2, 2).value == "3"

    exported_xls = client.post(
        "/api/pdf/tables/export",
        files={"file": ("inventory.pdf", source, "application/pdf")},
        data={"page_number": "1", "table_number": "1", "format": "xls"},
    )
    assert exported_xls.status_code == 200, exported_xls.text
    assert exported_xls.headers["content-type"].startswith("application/vnd.ms-excel")
    assert "pdf-table-page-01-table-01.xls" in exported_xls.headers["content-disposition"]
    legacy_workbook = xlrd.open_workbook(file_contents=exported_xls.content, on_demand=True)
    try:
        assert legacy_workbook.sheet_by_index(0).cell_value(1, 0) == "Tea"
        assert legacy_workbook.sheet_by_index(0).cell_value(1, 1) == "3"
    finally:
        legacy_workbook.release_resources()

    invalid_selection = client.post(
        "/api/pdf/tables/export",
        files={"file": ("inventory.pdf", source, "application/pdf")},
        data={"page_number": "2", "table_number": "1", "format": "csv"},
    )
    assert invalid_selection.status_code == 422
    assert "unavailable" in invalid_selection.json()["detail"]

    invalid_format = client.post(
        "/api/pdf/tables/export",
        files={"file": ("inventory.pdf", source, "application/pdf")},
        data={"page_number": "1", "table_number": "1", "format": "json"},
    )
    assert invalid_format.status_code == 422

    invalid_type = client.post(
        "/api/pdf/tables",
        files={"file": ("inventory.txt", b"not pdf", "text/plain")},
    )
    assert invalid_type.status_code == 415


def test_pdf_table_api_exports_reconstructed_wrapped_rows_without_summary_spill():
    client = TestClient(app)
    source = make_unruled_date_table_pdf()

    preview = client.post(
        "/api/pdf/tables",
        files={"file": ("statement.pdf", source, "application/pdf")},
    )
    assert preview.status_code == 200, preview.text
    table = preview.json()["tables"][0]
    assert table["row_count"] == 4
    assert [row[0] for row in table["preview_rows"]] == [
        "Date", "21/09/26", "25/09/26", "26/09/26",
    ]

    exported = client.post(
        "/api/pdf/tables/export",
        files={"file": ("statement.pdf", source, "application/pdf")},
        data={"page_number": "1", "table_number": "1", "format": "csv"},
    )
    assert exported.status_code == 200, exported.text
    rows = list(csv.reader(io.StringIO(exported.content.decode("utf-8-sig"))))
    assert len(rows) == 4
    assert rows[2] == [
        "25/09/26", "NEFT PAYMENT LONG WITH WRAPPED NARRATION", "REF-002", "200.00", "800.00",
    ]
