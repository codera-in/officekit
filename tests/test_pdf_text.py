import io

import pytest

pytest.importorskip("pdfplumber")
pytest.importorskip("fastapi")
pytest.importorskip("reportlab")

from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from app import app
from officekit.engines.engine_pdf_text import PdfTextError, extract_pdf_text


def make_pdf(pages):
    output = io.BytesIO()
    document = canvas.Canvas(output)
    for page in pages:
        for line_index, line in enumerate(page):
            document.drawString(42, 780 - line_index * 18, line)
        document.showPage()
    document.save()
    return output.getvalue()


def test_extracts_selectable_text_in_page_order_and_preserves_unicode():
    result = extract_pdf_text(make_pdf([["Café — résumé"], ["Second page"]]))
    assert result["page_count"] == 2
    assert result["selected_pages"] == [1, 2]
    assert result["missing_text_pages"] == []
    assert "Café — résumé" in result["text"]
    assert result["text"].index("Page 1") < result["text"].index("Page 2")


def test_selected_pages_preserve_requested_order_and_markdown_headings():
    result = extract_pdf_text(make_pdf([["First"], ["Second"], ["Third"]]), "3, 1", "md")
    assert result["selected_pages"] == [3, 1]
    assert result["text"].index("## Page 3") < result["text"].index("## Page 1")
    assert "Third" in result["text"] and "First" in result["text"]


@pytest.mark.parametrize("ranges", ["0", "4", "3-1", "1,1", "1,,2", "x", "1-999999999999"])
def test_rejects_invalid_or_out_of_bounds_ranges(ranges):
    with pytest.raises(PdfTextError):
        extract_pdf_text(make_pdf([["First"], ["Second"], ["Third"]]), ranges)


def test_scanned_or_blank_pages_are_reported_and_all_blank_selection_fails():
    source = make_pdf([["Readable"], []])
    result = extract_pdf_text(source, "1-2")
    assert result["missing_text_pages"] == [2]
    assert "No selectable text" not in result["text"]
    with pytest.raises(PdfTextError, match="No selectable text"):
        extract_pdf_text(source, "2")


@pytest.mark.parametrize("source,format_name", [(b"", "txt"), (b"not a PDF", "txt"), (b"%PDF", "html")])
def test_rejects_invalid_input_and_output_format(source, format_name):
    with pytest.raises(PdfTextError):
        extract_pdf_text(source, output_format=format_name)


def test_enforces_page_character_and_encoded_output_limits(monkeypatch):
    source = make_pdf([["A readable page"], ["Second page"]])
    monkeypatch.setattr("officekit.engines.engine_pdf_text.MAX_PDF_PAGES", 1)
    with pytest.raises(PdfTextError, match="1–50 pages"):
        extract_pdf_text(source)

    monkeypatch.setattr("officekit.engines.engine_pdf_text.MAX_PDF_PAGES", 50)
    monkeypatch.setattr("officekit.engines.engine_pdf_text.MAX_PAGE_CHARACTERS", 3)
    with pytest.raises(PdfTextError, match="page exceeds"):
        extract_pdf_text(source, "1")

    monkeypatch.setattr("officekit.engines.engine_pdf_text.MAX_PAGE_CHARACTERS", 100_000)
    monkeypatch.setattr("officekit.engines.engine_pdf_text.MAX_OUTPUT_BYTES", 8)
    with pytest.raises(PdfTextError, match="8 MiB download limit"):
        extract_pdf_text(source, "1")


def test_maps_encrypted_pdf_parser_error_to_fixed_safe_message(monkeypatch):
    from pdfminer.pdfdocument import PDFPasswordIncorrect

    def raise_password_error(*_args, **_kwargs):
        raise PDFPasswordIncorrect

    monkeypatch.setattr("officekit.engines.engine_pdf_text.pdfplumber.open", raise_password_error)
    with pytest.raises(PdfTextError, match="invalid, encrypted, or could not be read"):
        extract_pdf_text(b"%PDF-1.4")


def test_api_returns_safe_download_and_explicit_missing_page_header():
    source = make_pdf([["First page"], []])
    response = TestClient(app).post(
        "/api/pdf/text",
        files={"file": ("statement.pdf", source, "application/pdf")},
        data={"page_ranges": "1-2", "format": "md"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment;" in response.headers["content-disposition"]
    assert response.headers["x-officekit-page-count"] == "2"
    assert response.headers["x-officekit-missing-text-pages"] == "2"
    assert "## Page 1" in response.text


def test_api_returns_actionable_error_for_scanned_only_pdf():
    source = make_pdf([[]])
    response = TestClient(app).post(
        "/api/pdf/text", files={"file": ("scan.pdf", source, "application/pdf")}
    )
    assert response.status_code == 422
    assert "scanned image PDF" in response.json()["detail"]


def test_api_rejects_non_pdf_names_and_invalid_page_selection():
    client = TestClient(app)
    source = make_pdf([["Page one"]])
    wrong_extension = client.post("/api/pdf/text", files={"file": ("notes.txt", source, "application/pdf")})
    assert wrong_extension.status_code == 415
    invalid_range = client.post(
        "/api/pdf/text",
        files={"file": ("notes.pdf", source, "application/pdf")},
        data={"page_ranges": "1, 1", "format": "txt"},
    )
    assert invalid_range.status_code == 422
    assert "selected more than once" in invalid_range.json()["detail"]
