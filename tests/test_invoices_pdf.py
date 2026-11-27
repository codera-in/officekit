import io
from pathlib import Path
import shutil
import sys

import pytest

from PIL import Image
from pypdf import PdfReader

from officekit.invoices.pdf import format_currency, normalize_logo, render_pdf
from officekit.invoices.models import Currency
from officekit.invoices import pdf
from officekit.invoices.domain import InvoiceError
from test_invoices_domain import world, save_draft


def test_global_currency_formatting_and_logo_normalization():
    assert format_currency("1234567.50", Currency().model_dump()) == "$1,234,567.50"
    assert format_currency("1234567.5", Currency(code="INR", symbol="₹", grouping="indian").model_dump()) == "₹12,34,567.50"
    image = io.BytesIO()
    Image.new("RGB", (12, 6), "red").save(image, "JPEG")
    raw, width, height = normalize_logo(image.getvalue())
    assert raw.startswith(b"\x89PNG") and (width, height) == (12, 6)


def test_currency_placements_grouping_and_zero_precision():
    assert format_currency("1234", Currency(precision=0, placement="after", symbol="€").model_dump()) == "1,234 €"
    assert format_currency("-12.50", Currency(placement="code", grouping="none").model_dump()) == "USD −12.50"
    assert format_currency("1234.56", Currency(decimal_separator=",", grouping_separator=".").model_dump()) == "$1.234,56"


def test_logo_failures_are_bounded_and_do_not_accept_active_content(monkeypatch):
    with pytest.raises(InvoiceError, match="decoded"):
        normalize_logo(b"<svg></svg>")
    source = io.BytesIO()
    Image.new("RGB", (1, 1)).save(source, "PNG")
    raw = source.getvalue()
    monkeypatch.setattr(pdf, "MAX_LOGO_BYTES", len(raw) - 1)
    with pytest.raises(InvoiceError, match="no larger"):
        normalize_logo(raw)
    monkeypatch.setattr(pdf, "MAX_LOGO_BYTES", len(raw))
    with pytest.raises(InvoiceError, match="normalized"):
        normalize_logo(raw)
    monkeypatch.setattr(pdf, "MAX_LOGO_BYTES", 10000)
    monkeypatch.setattr(pdf, "MAX_LOGO_PIXELS", 0)
    with pytest.raises(InvoiceError, match="dimensions"):
        normalize_logo(raw)
    monkeypatch.setattr(pdf, "MAX_LOGO_PIXELS", 100)
    gif = io.BytesIO()
    Image.new("RGB", (1, 1)).save(gif, "GIF")
    with pytest.raises(InvoiceError, match="dimensions"):
        normalize_logo(gif.getvalue())


def test_fonts_use_packaged_path_and_refuse_missing_fonts(tmp_path, monkeypatch):
    pdf.invoice_font.cache_clear()
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    with pytest.raises(InvoiceError, match="font is unavailable"):
        pdf.invoice_font()
    (tmp_path / "fonts").mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1] / "assets/fonts/NotoSans-Regular.ttf", tmp_path / "fonts/NotoSans-Regular.ttf")
    assert pdf.invoice_font() == "OfficeKitInvoice"
    pdf.invoice_font.cache_clear()


def test_all_pdf_layouts_render_snapshots_payments_logo_qr_and_wrapped_rows(world, tmp_path):
    service, repo, business, client = world
    document = save_draft(world)
    logo = io.BytesIO()
    Image.new("RGBA", (30, 15), "blue").save(logo, "PNG")
    repo.read_asset = lambda identifier: logo.getvalue()
    document["business"].update(address="Street 1\nCity", contact="contact@example.com", registrations=[{"label": "Tax ID", "value": "123", "visible": True}, {"label": "Private", "value": "hidden", "visible": False}])
    document["client"]["customer_reference"] = "Customer 042"
    document["draft"].update(notes="A < B & C", terms="Please pay within 14 days.", valid_until="2026-11-30")
    document["draft"]["lines"][0].update(section="Services", date="2026-10-25")
    document["payment_methods"] = [{"label": "Bank transfer", "fields": [{"label": "IBAN", "value": "DE123", "visible": True}, {"label": "Hidden", "value": "secret", "visible": False}], "link": "https://example.com/pay", "instructions": "Reference invoice number", "qr_payload": "https://example.com/pay"}]
    document["payment_methods"].append({"label": "Cash", "fields": [], "link": "", "instructions": "", "qr_payload": ""})
    document["totals"]["taxes"] = [{"label": "VAT", "rate": "0", "amount": "0.00", "registration_label": "Tax ID", "registration_number": "VAT42"}, {"label": "Duty", "rate": "0", "amount": "0.00", "registration_label": "", "registration_number": ""}]
    for layout in ("Classic", "Compact", "Bold"):
        document["template"].update(layout=layout, paper="Letter" if layout == "Bold" else "A4", logo_id="a" * 64, footer="Thanks", columns=["description", "unit", "date", "quantity", "rate", "amount"])
        data = render_pdf(document, repo)
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() for page in reader.pages)
        assert "Studio" in text and "IBAN: DE123" in text and "VAT42" in text
        assert "DRAFT" in text and "A < B & C" in text and "secret" not in text
        (tmp_path / f"invoice-{layout}.pdf").write_bytes(data)
    # A full multi-page document must repeat table headings without losing rows.
    document["draft"]["lines"] *= 100
    document["totals"]["lines"] *= 100
    for index, line in enumerate(document["draft"]["lines"]):
        line["description"] = f"Line {index} " + ("Wrapped description " * 10)
    document["state"] = "issued"
    data = render_pdf(document, repo)
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) > 1
    assert "Line 99" in "\n".join(page.extract_text() for page in reader.pages)


def test_pdf_rejects_unsupported_glyphs_and_output_budgets(world, monkeypatch):
    document = save_draft(world)
    document["business"]["name"] = "日本"
    with pytest.raises(InvoiceError, match="unsupported"):
        render_pdf(document)
    document["business"]["name"] = "Studio"
    monkeypatch.setattr(pdf, "MAX_PDF_PAGES", 0)
    with pytest.raises(InvoiceError, match="page limit"):
        render_pdf(document)
    monkeypatch.setattr(pdf, "MAX_PDF_PAGES", 100)
    monkeypatch.setattr(pdf, "MAX_PDF_BYTES", 10)
    with pytest.raises(InvoiceError, match="PDF size"):
        render_pdf(document)
    def invalid_layout(*args, **kwargs):
        raise pdf.LayoutError("invalid row")
    monkeypatch.setattr(pdf.SimpleDocTemplate, "build", invalid_layout)
    with pytest.raises(InvoiceError, match="could not fit"):
        render_pdf(document)
