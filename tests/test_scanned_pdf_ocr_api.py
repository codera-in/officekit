import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from PIL import ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import app as officekit_app
import officekit.engines.engine_rapidocr as engine_rapidocr


client = TestClient(officekit_app.app)


def _load_font(size: int = 38):
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _scanned_pdf_bytes():
    image = Image.new("RGB", (240, 120), "white")
    output = io.BytesIO()
    image.save(output, format="PDF")
    image.close()
    return output.getvalue()


def _raster_statement_pdf_bytes(rotation=0):
    image = Image.new("RGB", (2200, 720), "white")
    draw = ImageDraw.Draw(image)
    font = _load_font(38)
    columns = {"date": 70, "description": 390, "debit": 1080, "credit": 1450, "balance": 1800}
    for label, x in columns.items():
        draw.text((x, 55), label.upper(), font=font, fill="black")
    for y, values in (
        (230, {"date": "2026-01-02", "description": "Opening balance", "balance": "1000.00"}),
        (405, {"date": "2026-01-03", "description": "Coffee Shop", "debit": "25.00", "balance": "975.00"}),
    ):
        for column, value in values.items():
            draw.text((columns[column], y), value, font=font, fill="black")

    if rotation:
        rotated = image.rotate(rotation, expand=True)
        image.close()
        image = rotated
    page_size = (1056, 345) if rotation % 180 == 0 else (345, 1056)
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=page_size)
    pdf.drawImage(ImageReader(image), 0, 0, width=page_size[0], height=page_size[1])
    pdf.save()
    image.close()
    return output.getvalue()


def _weak_vector_raster_statement_pdf_bytes():
    image = Image.new("RGB", (1224, 1584), "white")
    draw = ImageDraw.Draw(image)
    font = _load_font(34)
    columns = {"date": 80, "description": 290, "debit": 700, "credit": 860, "balance": 1010}
    for label, x in columns.items():
        draw.text((x, 110), label.upper(), font=font, fill="black")
    for y, values in (
        (430, {"date": "2026-01-02", "description": "Opening balance", "balance": "1000.00"}),
        (760, {"date": "2026-01-03", "description": "Coffee Shop", "debit": "25.00", "balance": "975.00"}),
    ):
        for column, value in values.items():
            draw.text((columns[column], y), value, font=font, fill="black")

    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(612, 792))
    pdf.drawImage(ImageReader(image), 0, 0, width=612, height=792)
    image.close()
    hidden_items = (
        (40, 740, "Date"), (120, 740, "Description"), (350, 740, "Debit"),
        (420, 740, "Credit"), (500, 740, "Balance"),
        (40, 700, "2026-01-02 2026-01-03"), (120, 700, "Opening balance Coffee Shop"),
    )
    for x, y, value in hidden_items:
        text = pdf.beginText(x, y)
        text.setTextRenderMode(3)
        text.textOut(value)
        pdf.drawText(text)
    pdf.save()
    return output.getvalue()


def test_scanned_statement_pdf_uses_local_ocr_when_vector_extraction_has_no_rows(monkeypatch):
    monkeypatch.setattr(officekit_app, "extract_pdf_page_tables", lambda _content: [[]])
    monkeypatch.setattr(
        officekit_app,
        "extract_scanned_pdf_page_rows",
        lambda _content, _page_indexes: [[
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["2026-01-02", "Opening balance", "", "", "1000.00"],
            ["2026-01-03", "Coffee Shop", "25.00", "", "975.00"],
        ]],
        raising=False,
    )

    response = client.post(
        "/api/extract/statement",
        files={"file": ("scanned-statement.pdf", _scanned_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    result = response.json()
    coffee = next(row for row in result["transactions"] if row["description"] == "Coffee Shop")
    assert coffee["debit"] == 25.0
    assert coffee["balance"] == 975.0, result["raw_rows"]


def test_vector_statement_pdf_does_not_run_ocr_fallback(monkeypatch):
    monkeypatch.setattr(
        officekit_app,
        "extract_pdf_page_tables",
        lambda _content: [[[ ["Date", "Description", "Amount"], ["2026-01-03", "Coffee Shop", "25.00"] ]]],
    )
    monkeypatch.setattr(
        officekit_app,
        "extract_scanned_pdf_page_rows",
        lambda _content, _page_indexes: (_ for _ in ()).throw(AssertionError("OCR fallback should not run for vector text")),
        raising=False,
    )

    response = client.post(
        "/api/extract/statement",
        files={"file": ("vector-statement.pdf", _scanned_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200


def test_weak_vector_statement_table_uses_better_local_ocr_rows(monkeypatch):
    weak_rows = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["01/01/2026", "02/01/2026 Opening balance Coffee Shop", "", "", ""],
    ]
    ocr_rows = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["01/01/2026", "Opening balance", "", "", "1000.00"],
        ["02/01/2026", "Coffee Shop", "25.00", "", "975.00"],
    ]
    monkeypatch.setattr(officekit_app, "extract_pdf_page_tables", lambda _content: [[weak_rows]])
    calls = []
    monkeypatch.setattr(
        officekit_app,
        "extract_scanned_pdf_page_rows",
        lambda _content, page_indexes: calls.append(page_indexes) or [ocr_rows],
        raising=False,
    )

    response = client.post(
        "/api/extract/statement",
        files={"file": ("merged-vector-statement.pdf", _scanned_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert calls == [[0]]
    result = response.json()
    coffee = next(row for row in result["transactions"] if row["description"] == "Coffee Shop")
    assert coffee["debit"] == 25.0
    assert coffee["balance"] == 975.0
    assert coffee["status"] == "ok"


def test_ocr_recovers_weak_table_without_keeping_a_complete_table_as_a_short_circuit(monkeypatch):
    complete_table = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["2026-01-01", "Opening balance", "", "", "1000.00"],
        ["2026-01-02", "Coffee Shop", "25.00", "", "975.00"],
    ]
    weak_table = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["2026-01-03 2026-01-04", "Grocery Shop Salary", "", "", ""],
    ]
    recovered_rows = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["2026-01-01", "Opening balance", "", "", "1000.00"],
        ["2026-01-02", "Coffee Shop", "25.00", "", "975.00"],
        ["2026-01-03", "Grocery Shop", "10.00", "", "965.00"],
        ["2026-01-04", "Salary", "", "20.00", "985.00"],
    ]
    monkeypatch.setattr(
        officekit_app,
        "extract_pdf_page_tables",
        lambda _content: [[complete_table, weak_table]],
    )
    calls = []
    monkeypatch.setattr(
        officekit_app,
        "extract_scanned_pdf_page_rows",
        lambda _content, page_indexes: calls.append(page_indexes) or [recovered_rows],
        raising=False,
    )

    response = client.post(
        "/api/extract/statement",
        files={"file": ("mixed-quality-vector-statement.pdf", _scanned_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert calls == [[0]]
    payload = response.json()
    assert [row["description"] for row in payload["transactions"]] == [
        "Opening balance", "Coffee Shop", "Grocery Shop", "Salary",
    ]
    assert payload["reconciliation"]["status"] == "verified"


def test_weak_vector_statement_keeps_original_rows_when_local_ocr_is_unavailable(monkeypatch):
    from officekit.engines.engine_pdf_ocr import ScannedPdfOcrUnavailable

    weak_rows = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["01/01/2026", "02/01/2026 Opening balance Coffee Shop", "", "", ""],
    ]
    monkeypatch.setattr(officekit_app, "extract_pdf_page_tables", lambda _content: [[weak_rows]])
    calls = []

    def unavailable(_content, page_indexes):
        calls.append(page_indexes)
        raise ScannedPdfOcrUnavailable()

    monkeypatch.setattr(officekit_app, "extract_scanned_pdf_page_rows", unavailable, raising=False)

    response = client.post(
        "/api/extract/statement",
        files={"file": ("merged-vector-statement.pdf", _scanned_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert calls == [[0]]
    result = response.json()
    assert result["raw_rows"] == weak_rows
    assert result["reconciliation"]["status"] == "unverified"


def test_weak_vector_statement_keeps_original_rows_when_ocr_candidate_is_not_better(monkeypatch):
    weak_rows = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["01/01/2026", "02/01/2026 Opening balance Coffee Shop", "", "", ""],
    ]
    monkeypatch.setattr(officekit_app, "extract_pdf_page_tables", lambda _content: [[weak_rows]])
    calls = []
    monkeypatch.setattr(
        officekit_app,
        "extract_scanned_pdf_page_rows",
        lambda _content, page_indexes: calls.append(page_indexes) or [[
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["01/01/2026", "02/01/2026 Opening balance Coffee Shop", "", "", ""],
        ]],
        raising=False,
    )

    response = client.post(
        "/api/extract/statement",
        files={"file": ("merged-vector-statement.pdf", _scanned_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert calls == [[0]]
    assert response.json()["raw_rows"] == weak_rows


def test_weak_vector_statement_keeps_original_rows_when_ocr_returns_no_rows(monkeypatch):
    weak_rows = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["01/01/2026 02/01/2026", "Opening balance Coffee Shop", "", "", ""],
    ]
    monkeypatch.setattr(officekit_app, "extract_pdf_page_tables", lambda _content: [[weak_rows]])
    calls = []
    monkeypatch.setattr(
        officekit_app,
        "extract_scanned_pdf_page_rows",
        lambda _content, page_indexes: calls.append(page_indexes) or [[]],
        raising=False,
    )

    response = client.post(
        "/api/extract/statement",
        files={"file": ("merged-vector-statement.pdf", _scanned_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert calls == [[0]]
    assert response.json()["raw_rows"] == weak_rows


def test_ocr_does_not_replace_a_stronger_vector_statement_table(monkeypatch):
    vector_rows = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["01/01/2026", "Opening balance", "", "", "1000.00"],
        ["02/01/2026", "Coffee Shop", "25.00", "", "975.00"],
    ]
    monkeypatch.setattr(officekit_app, "extract_pdf_page_tables", lambda _content: [[vector_rows]])
    calls = []
    monkeypatch.setattr(
        officekit_app,
        "extract_scanned_pdf_page_rows",
        lambda _content, page_indexes: calls.append(page_indexes) or [[
            ["Date", "Description", "Amount"],
            ["02/01/2026", "Coffee Shop", "25.00"],
        ]],
        raising=False,
    )

    response = client.post(
        "/api/extract/statement",
        files={"file": ("complete-vector-statement.pdf", _scanned_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    assert calls == []
    result = response.json()
    assert result["raw_rows"] == vector_rows


def test_scanned_statement_error_states_are_safe_and_keep_actionable_status_codes(monkeypatch):
    from officekit.engines.engine_pdf_ocr import ScannedPdfOcrError, ScannedPdfOcrUnavailable

    monkeypatch.setattr(officekit_app, "extract_pdf_page_tables", lambda _content: [[]])
    monkeypatch.setattr(officekit_app, "extract_scanned_pdf_page_rows", lambda _content, _page_indexes: (_ for _ in ()).throw(ScannedPdfOcrUnavailable()))
    unavailable = client.post(
        "/api/extract/statement", files={"file": ("scan.pdf", _scanned_pdf_bytes(), "application/pdf")}
    )
    monkeypatch.setattr(officekit_app, "extract_scanned_pdf_page_rows", lambda _content, _page_indexes: (_ for _ in ()).throw(ScannedPdfOcrError()))
    unreadable = client.post(
        "/api/extract/statement", files={"file": ("scan.pdf", _scanned_pdf_bytes(), "application/pdf")}
    )

    assert unavailable.status_code == 503
    assert unavailable.json()["detail"] == ScannedPdfOcrUnavailable.public_message
    assert unreadable.status_code == 422
    assert unreadable.json()["detail"] == ScannedPdfOcrError.public_message


def test_scanned_statement_fallback_removes_repeated_headers_between_pages(monkeypatch):
    monkeypatch.setattr(officekit_app, "extract_pdf_page_tables", lambda _content: [[], []])
    monkeypatch.setattr(
        officekit_app,
        "extract_scanned_pdf_page_rows",
        lambda _content, _page_indexes: [
            [["Date", "Description", "Amount"], ["2026-01-02", "Coffee Shop", "25.00"]],
            [["Date", "Description", "Amount"], ["2026-01-03", "Train Ticket", "15.00"]],
        ],
        raising=False,
    )

    response = client.post(
        "/api/extract/statement",
        files={"file": ("scanned-pages.pdf", _scanned_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    assert [row["description"] for row in response.json()["transactions"]] == ["Coffee Shop", "Train Ticket"]


def test_mixed_vector_and_scanned_statement_pages_keep_document_order(monkeypatch):
    monkeypatch.setattr(
        officekit_app,
        "extract_pdf_page_tables",
        lambda _content: [
            [[["Date", "Description", "Amount"], ["2026-01-02", "Coffee Shop", "25.00"]]],
            [],
            [[["Date", "Description", "Amount"], ["2026-01-04", "Book Store", "35.00"]]],
        ],
    )
    monkeypatch.setattr(
        officekit_app,
        "extract_scanned_pdf_page_rows",
        lambda _content, page_indexes: [
            [["Date", "Description", "Amount"], ["2026-01-03", "Train Ticket", "15.00"]]
        ] if page_indexes == [1] else [],
        raising=False,
    )

    response = client.post(
        "/api/extract/statement",
        files={"file": ("mixed-statement.pdf", _scanned_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200
    assert [row["description"] for row in response.json()["transactions"]] == [
        "Coffee Shop", "Train Ticket", "Book Store"
    ]


def test_scanned_pdf_engine_renders_real_pdf_pages_before_ocr():
    from officekit.engines.engine_pdf_ocr import ScannedPdfOcrEngine

    observed_sizes = []

    def recognize_png(image_bytes, timeout_seconds):
        assert 0 < timeout_seconds <= 60
        with Image.open(io.BytesIO(image_bytes)) as page_image:
            observed_sizes.append(page_image.size)
        return [["2026-01-03", "Coffee Shop", "25.00"]]

    rows = ScannedPdfOcrEngine.extract_rows(_scanned_pdf_bytes(), image_text_extractor=recognize_png)

    assert rows == [["2026-01-03", "Coffee Shop", "25.00"]]
    assert len(observed_sizes) == 1
    assert observed_sizes[0][0] in (500, 501)
    assert observed_sizes[0][1] in (250, 251)


def test_scanned_pdf_retries_quarter_turns_only_when_upright_ocr_has_no_text(monkeypatch):
    from officekit.engines.engine_pdf_ocr import ScannedPdfOcrEngine

    observed_sizes = []

    def recognize_png(image_bytes, timeout_seconds):
        with Image.open(io.BytesIO(image_bytes)) as page_image:
            observed_sizes.append(page_image.size)
        return [] if len(observed_sizes) == 1 else [["2026-01-03", "Coffee Shop", "25.00"]]

    rows = ScannedPdfOcrEngine.extract_rows(
        _scanned_pdf_bytes(), image_text_extractor=recognize_png
    )

    assert rows == [["2026-01-03", "Coffee Shop", "25.00"]]
    assert observed_sizes[0][0] > observed_sizes[0][1]
    assert observed_sizes[1] == (observed_sizes[0][1], observed_sizes[0][0])


def test_scanned_pdf_prefers_the_retry_with_ordered_statement_columns():
    from officekit.engines.engine_pdf_ocr import ScannedPdfOcrEngine

    attempts = []

    def recognize_orientation(_image_bytes, timeout_seconds):
        attempts.append(timeout_seconds)
        if len(attempts) == 1:
            return [
                ["BALANCE", "CREDIT", "DEBIT", "DESCRIPTION", "DATE"],
                ["975.00", "", "25.00", "Shop Coffee", "2026-01-03"],
            ]
        if len(attempts) == 2:
            return [
                ["DATE", "DESCRIPTION", "DEBIT", "CREDIT", "BALANCE"],
                ["2026-01-03", "Coffee Shop", "25.00", "", "975.00"],
            ]
        return []

    rows = ScannedPdfOcrEngine.extract_rows(
        _scanned_pdf_bytes(), image_text_extractor=recognize_orientation
    )

    assert rows[0] == ["DATE", "DESCRIPTION", "DEBIT", "CREDIT", "BALANCE"]
    assert rows[1][1] == "Coffee Shop"
    assert len(attempts) == 4


def test_scanned_pdf_orientation_retry_respects_the_aggregate_pixel_budget(monkeypatch):
    from officekit.engines.engine_pdf_ocr import ScannedPdfOcrEngine, ScannedPdfOcrError

    observed_calls = []

    def recognize_empty(_image_bytes, timeout_seconds):
        observed_calls.append(timeout_seconds)
        return []

    monkeypatch.setattr(ScannedPdfOcrEngine, "MAX_TOTAL_PIXELS", 130_000)
    with pytest.raises(ScannedPdfOcrError):
        ScannedPdfOcrEngine.extract_rows(
            _scanned_pdf_bytes(), image_text_extractor=recognize_empty
        )

    assert len(observed_calls) == 1


@pytest.mark.skipif(
    not engine_rapidocr.is_available(),
    reason="The bundled RapidOCR runtime and offline models are required for this integration test.",
)
def test_local_ocr_extracts_transactions_from_a_raster_only_statement_pdf():
    response = client.post(
        "/api/extract/statement",
        files={"file": ("raster-statement.pdf", _raster_statement_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    coffee_rows = [row for row in result["transactions"] if row["description"] == "Coffee Shop"]
    assert coffee_rows, result["raw_rows"]
    coffee = coffee_rows[0]
    assert coffee["debit"] == 25.0
    assert coffee["balance"] == 975.0, result["raw_rows"]


@pytest.mark.skipif(
    not engine_rapidocr.is_available(),
    reason="The bundled RapidOCR runtime and offline models are required for this integration test.",
)
def test_local_ocr_recovers_transactions_from_a_quarter_turned_raster_statement_pdf():
    response = client.post(
        "/api/extract/statement",
        files={"file": ("rotated-raster-statement.pdf", _raster_statement_pdf_bytes(90), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    coffee_rows = [row for row in result["transactions"] if row["description"] == "Coffee Shop"]
    assert coffee_rows, result["raw_rows"]
    coffee = coffee_rows[0]
    assert coffee["debit"] == 25.0
    assert coffee["balance"] == 975.0, result["raw_rows"]


@pytest.mark.skipif(
    not engine_rapidocr.is_available(),
    reason="The bundled RapidOCR runtime and offline models are required for this integration test.",
)
def test_local_ocr_recovers_a_raster_statement_hidden_under_weak_vector_rows():
    response = client.post(
        "/api/extract/statement",
        files={"file": ("weak-vector-raster-statement.pdf", _weak_vector_raster_statement_pdf_bytes(), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    coffee_rows = [row for row in result["transactions"] if row["description"] == "Coffee Shop"]
    assert coffee_rows, result["raw_rows"]
    assert coffee_rows[0]["debit"] == 25.0
    assert coffee_rows[0]["balance"] == 975.0
    assert result["reconciliation"]["status"] == "verified"


@pytest.mark.skipif(
    not engine_rapidocr.is_available(),
    reason="The bundled RapidOCR runtime and offline models are required for this integration test.",
)
def test_local_ocr_recovers_the_packaged_weak_vector_statement_fixture():
    fixture = Path(__file__).parent / "fixtures" / "statements" / "weak-vector-raster-statement.pdf"
    response = client.post(
        "/api/extract/statement",
        files={"file": (fixture.name, fixture.read_bytes(), "application/pdf")},
    )

    assert response.status_code == 200, response.text
    result = response.json()
    coffee_rows = [row for row in result["transactions"] if row["description"] == "Coffee Shop"]
    assert coffee_rows, result["raw_rows"]
    assert coffee_rows[0]["debit"] == 25.0
    assert coffee_rows[0]["balance"] == 975.0
    assert result["reconciliation"]["status"] == "verified"


class _FakeBitmap:
    def __init__(self, size):
        self.image = Image.new("RGB", size, "white")
        self.closed = False

    def to_pil(self):
        return self.image

    def close(self):
        self.closed = True
        self.image.close()


class _FakePage:
    def __init__(self, size=(72, 72)):
        self.size = size
        self.closed = False
        self.bitmap = None

    def get_size(self):
        return self.size

    def render(self, **_options):
        self.bitmap = _FakeBitmap((150, 150))
        return self.bitmap

    def close(self):
        self.closed = True


class _FakeDocument:
    def __init__(self, pages):
        self.pages = pages
        self.closed = False

    def __len__(self):
        return len(self.pages)

    def __getitem__(self, index):
        return self.pages[index]

    def close(self):
        self.closed = True


class _FakePdfium:
    def __init__(self, pages):
        self.document = _FakeDocument(pages)

    def PdfDocument(self, _payload):
        return self.document


def test_scanned_pdf_bounds_page_count_pixels_output_and_closes_resources(monkeypatch):
    from officekit.engines.engine_ocr import ImageTextRecognitionUnavailable
    from officekit.engines.engine_pdf_ocr import ScannedPdfOcrEngine, ScannedPdfOcrError, ScannedPdfOcrUnavailable

    fake = _FakePdfium([_FakePage(), _FakePage()])
    monkeypatch.setattr(ScannedPdfOcrEngine, "MAX_PAGES", 1)
    with pytest.raises(ScannedPdfOcrError):
        ScannedPdfOcrEngine.extract_rows(b"pdf", lambda _image, **_options: [], fake)
    assert fake.document.closed
    assert not any(page.bitmap for page in fake.document.pages)

    monkeypatch.setattr(ScannedPdfOcrEngine, "MAX_PAGES", 20)
    monkeypatch.setattr(ScannedPdfOcrEngine, "MAX_TOTAL_PIXELS", 30_000)
    fake = _FakePdfium([_FakePage(), _FakePage()])
    recognized = []
    with pytest.raises(ScannedPdfOcrError):
        ScannedPdfOcrEngine.extract_rows(
            b"pdf", lambda _image, **_options: recognized.append(True) or [["2026-01-01", "25.00"]], fake
        )
    assert len(recognized) == 1
    assert fake.document.closed
    assert all(page.closed for page in fake.document.pages)

    monkeypatch.setattr(ScannedPdfOcrEngine, "MAX_TOTAL_PIXELS", 40_000_000)
    monkeypatch.setattr(ScannedPdfOcrEngine, "MAX_PAGE_PNG_BYTES", 1)
    fake = _FakePdfium([_FakePage()])
    with pytest.raises(ScannedPdfOcrError):
        ScannedPdfOcrEngine.extract_rows(b"pdf", lambda _image, **_options: [], fake)
    assert fake.document.closed
    assert fake.document.pages[0].bitmap.closed

    monkeypatch.setattr(ScannedPdfOcrEngine, "MAX_PAGE_PNG_BYTES", 16 * 1024 * 1024)
    fake = _FakePdfium([_FakePage(), _FakePage(), _FakePage()])
    page_results = ScannedPdfOcrEngine.extract_page_rows(
        b"pdf", lambda _image, **_options: [["selected"]], fake, page_indexes=[2]
    )
    assert page_results == [[ ["selected"] ]]
    assert fake.document.closed
    assert fake.document.pages[0].bitmap is None
    assert fake.document.pages[1].bitmap is None
    assert fake.document.pages[2].bitmap.closed

    with pytest.raises(ScannedPdfOcrError):
        ScannedPdfOcrEngine.extract_page_rows(
            b"pdf", lambda _image, **_options: [], _FakePdfium([_FakePage(), _FakePage()]), page_indexes=[0, 0]
        )

    monkeypatch.setattr(ScannedPdfOcrEngine, "MAX_PAGE_PNG_BYTES", 16 * 1024 * 1024)
    fake = _FakePdfium([_FakePage()])
    with pytest.raises(ScannedPdfOcrUnavailable):
        ScannedPdfOcrEngine.extract_rows(
            b"pdf", lambda _image, **_options: (_ for _ in ()).throw(ImageTextRecognitionUnavailable()), fake
        )
    assert fake.document.closed
