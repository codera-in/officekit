from io import BytesIO

import pytest
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from officekit.engines.engine_conversion_errors import ConversionInputError
from officekit.engines.engine_media_models import MediaOperation
from officekit.engines.engine_media_optimizer import MediaOptimizerEngine
from officekit.engines.engine_media_pdf import MediaPdfCancelledError, MediaPdfEngine


def image_pdf_bytes(*, nested=False):
    from PIL import Image
    from reportlab.lib.utils import ImageReader

    image = Image.new("RGB", (300, 150), (30, 80, 140))
    output = BytesIO()
    pdf = Canvas(output, pagesize=(420, 600), invariant=1)
    if nested:
        pdf.beginForm("scan")
    pdf.drawImage(ImageReader(image), 0, 0, width=72, height=36)
    if nested:
        pdf.endForm()
        pdf.scale(2, 2)
        pdf.doForm("scan")
    pdf.save()
    return output.getvalue()


@pytest.mark.parametrize("nested,expected", [(False, 300), (True, 150)])
def test_pdf_image_dpi_uses_displayed_size_including_parent_form_transform(nested, expected):
    source = image_pdf_bytes(nested=nested)
    assert MediaPdfEngine.image_dpi_range(source) == pytest.approx((expected, expected))


def test_pdf_image_dpi_has_no_resolution_for_vector_only_pdf():
    assert MediaPdfEngine.image_dpi_range(pdf_bytes()) is None


def test_pdf_image_dpi_accounts_for_page_user_unit():
    from pypdf import PdfWriter
    from pypdf.generic import FloatObject, NameObject

    writer = PdfWriter(clone_from=BytesIO(image_pdf_bytes()))
    writer.pages[0][NameObject("/UserUnit")] = FloatObject(2)
    output = BytesIO()
    writer.write(output)
    assert MediaPdfEngine.image_dpi_range(output.getvalue()) == pytest.approx((150, 150))


def test_pdf_image_dpi_rejects_incomplete_form_scan(monkeypatch):
    monkeypatch.setattr(MediaPdfEngine, "MAX_DPI_SCAN_DEPTH", 1)
    with pytest.raises(ConversionInputError):
        MediaPdfEngine.image_dpi_range(image_pdf_bytes(nested=True))


@pytest.mark.parametrize("unit", [0, -1, float("nan"), float("inf"), 1e-309])
def test_pdf_image_dpi_rejects_invalid_or_overflowing_user_unit(unit, monkeypatch):
    from pypdf._page import PageObject

    monkeypatch.setattr(PageObject, "user_unit", property(lambda self: unit))
    with pytest.raises(ConversionInputError):
        MediaPdfEngine.image_dpi_range(image_pdf_bytes())


def test_pdf_image_dpi_closes_document_and_sanitizes_native_metadata_failure(monkeypatch):
    import pypdfium2 as pdfium

    opened = []
    real_open = MediaPdfEngine._open_pdfium

    def open_pdf(source):
        document = real_open(source)
        opened.append(document)
        return document

    def broken_metadata(self):
        raise RuntimeError("private-source-path")

    monkeypatch.setattr(MediaPdfEngine, "_open_pdfium", staticmethod(open_pdf))
    monkeypatch.setattr(pdfium.PdfImage, "get_px_size", broken_metadata)
    with pytest.raises(ConversionInputError) as failure:
        MediaPdfEngine.image_dpi_range(image_pdf_bytes())
    assert "private-source-path" not in str(failure.value)
    assert len(opened) == 1 and opened[0].raw is None


def test_pdf_image_dpi_rejects_pdf_encrypted_with_an_empty_password():
    from pypdf import PdfWriter

    writer = PdfWriter(clone_from=BytesIO(image_pdf_bytes()))
    writer.encrypt("")
    output = BytesIO()
    writer.write(output)
    with pytest.raises(ConversionInputError):
        MediaPdfEngine.image_dpi_range(output.getvalue())


@pytest.mark.parametrize("scale", [0, float("nan"), float("inf")])
def test_pdf_image_dpi_rejects_invalid_placement_matrix(scale, monkeypatch):
    import pypdfium2 as pdfium

    monkeypatch.setattr(pdfium.PdfImage, "get_matrix", lambda self: pdfium.PdfMatrix(scale, 0, 0, 1))
    with pytest.raises(ConversionInputError):
        MediaPdfEngine.image_dpi_range(image_pdf_bytes())


@pytest.mark.parametrize("source", [b"", b"not a pdf", None])
def test_pdf_image_dpi_rejects_invalid_input(source):
    with pytest.raises(ConversionInputError):
        MediaPdfEngine.image_dpi_range(source)


def test_pdf_image_dpi_checks_page_and_object_scan_bounds(monkeypatch):
    monkeypatch.setattr(MediaPdfEngine, "MAX_PAGES", 1)
    with pytest.raises(ConversionInputError):
        MediaPdfEngine.image_dpi_range(pdf_bytes(((420, 600), (420, 600))))
    monkeypatch.setattr(MediaPdfEngine, "MAX_DPI_SCAN_OBJECTS", 1)
    with pytest.raises(ConversionInputError):
        MediaPdfEngine.image_dpi_range(image_pdf_bytes(nested=True))


def pdf_bytes(page_sizes=((420, 600),), text="OfficeKit visual PDF fixture"):
    output = BytesIO()
    pdf = Canvas(output, pagesize=page_sizes[0], invariant=1)
    for index, page_size in enumerate(page_sizes):
        if index:
            pdf.setPageSize(page_size)
        pdf.drawString(36, page_size[1] - 48, text)
        pdf.showPage()
    pdf.save()
    return output.getvalue()


def operation(operation_id, options):
    return MediaOperation.model_validate({"operationId": operation_id, "options": options})


def test_uncrop_pdf_restores_media_boxes_in_a_copy_and_preserves_searchable_content():
    source_reader = PdfReader(BytesIO(pdf_bytes()))
    source_writer = __import__("pypdf").PdfWriter(clone_from=source_reader)
    source_writer.pages[0].cropbox.lower_left = (80, 90)
    source_writer.pages[0].cropbox.upper_right = (300, 450)
    original = BytesIO()
    source_writer.write(original)
    source_bytes = original.getvalue()
    original_crop = tuple(float(value) for value in PdfReader(BytesIO(source_bytes)).pages[0].cropbox)

    result = MediaOptimizerEngine.execute(source_bytes, "cropped.pdf", [operation("pdf-uncrop", {})])

    restored = PdfReader(BytesIO(result.data)).pages[0]
    assert tuple(float(value) for value in restored.cropbox) == tuple(float(value) for value in restored.mediabox)
    assert tuple(float(value) for value in PdfReader(BytesIO(source_bytes)).pages[0].cropbox) == original_crop
    assert restored.extract_text().strip() == "OfficeKit visual PDF fixture"
    assert result.attributes == {"page_count": 1, "crop_boxes_restored": True}


def test_visual_optimization_is_bounded_and_explicitly_reports_flattening():
    source = pdf_bytes(((420, 600), (800, 600)))
    result = MediaOptimizerEngine.execute(source, "source.pdf", [operation("pdf-visual-optimize", {"dpi": 96, "quality": 72})])

    reader = PdfReader(BytesIO(result.data))
    assert result.extension == "pdf"
    assert result.media_type == "application/pdf"
    assert len(reader.pages) == 2
    assert reader.pages[0].extract_text() in (None, "")
    assert result.attributes == {
        "page_count": 2,
        "dpi": 96,
        "quality": 72,
        "visual_only": True,
        "searchable_text_preserved": False,
        "interactive_content_preserved": False,
        "attempts": 1,
    }
    assert source.startswith(b"%PDF")


def test_pdf_fit_size_reports_success_and_unreachable_targets_without_overclaiming():
    source = pdf_bytes()
    success = MediaOptimizerEngine.execute(source, "source.pdf", [operation("pdf-fit-size", {
        "target_bytes": 2_000_000,
        "dpi": 96,
        "quality": 75,
    })])
    assert success.attributes["target_met"] is True
    assert success.attributes["actual_bytes"] == len(success.data)
    assert success.attributes["actual_bytes"] <= 2_000_000

    too_small = MediaOptimizerEngine.execute(source, "source.pdf", [operation("pdf-fit-size", {
        "target_bytes": 1,
        "dpi": 72,
        "quality": 30,
    })])
    assert too_small.attributes["target_met"] is False
    assert too_small.attributes["actual_bytes"] == len(too_small.data)
    assert too_small.attributes["attempts"] <= MediaPdfEngine.MAX_FIT_ATTEMPTS


def test_pdf_page_crop_sets_a_centered_viewport_and_preserves_vector_text():
    source = pdf_bytes(((600, 800),), text="Keep this searchable")
    cropped = MediaOptimizerEngine.execute(source, "source.pdf", [operation("pdf-crop", {"pageSize": "mobile"})])

    before = PdfReader(BytesIO(source)).pages[0]
    after = PdfReader(BytesIO(cropped.data)).pages[0]
    assert len(PdfReader(BytesIO(cropped.data)).pages) == 1
    assert float(after.cropbox.width) == pytest.approx(450)
    assert float(after.cropbox.height) == pytest.approx(800)
    assert after.extract_text().strip() == "Keep this searchable"
    assert float(before.mediabox.width) == float(after.mediabox.width)
    assert cropped.attributes["vector_content_preserved"] is True
    assert cropped.attributes["crop_centered"] is True


def test_pdf_page_crop_accepts_a_custom_aspect_ratio_and_preserves_vector_text():
    source = pdf_bytes(((600, 800),), text="Keep this searchable")
    cropped = MediaOptimizerEngine.execute(
        source, "source.pdf", [operation("pdf-crop", {"aspectRatio": "16:9"})]
    )

    after = PdfReader(BytesIO(cropped.data)).pages[0]
    assert float(after.cropbox.width) == pytest.approx(450)
    assert float(after.cropbox.height) == pytest.approx(800)
    assert after.extract_text().strip() == "Keep this searchable"
    assert cropped.attributes["aspect_ratio"] == "9:16"
    assert cropped.attributes["vector_content_preserved"] is True


def test_pdf_page_extend_adds_empty_area_without_clipping_vector_content():
    source = pdf_bytes(((600, 800),), text="Keep this searchable")
    extended = MediaOptimizerEngine.execute(
        source, "source.pdf", [operation("pdf-crop", {"aspectRatio": "9:16", "extend": True})]
    )

    page = PdfReader(BytesIO(extended.data)).pages[0]
    assert float(page.cropbox.width) == pytest.approx(600)
    assert float(page.cropbox.height) > 800
    assert float(page.mediabox.width) == pytest.approx(float(page.cropbox.width))
    assert float(page.mediabox.height) == pytest.approx(float(page.cropbox.height))
    assert page.extract_text().strip() == "Keep this searchable"
    assert extended.attributes["extended"] is True
    assert extended.attributes["crop_centered"] is False


def test_pdf_page_crop_can_force_landscape_layout():
    source = pdf_bytes(((600, 800),), text="Keep this searchable")
    cropped = MediaOptimizerEngine.execute(
        source, "source.pdf", [operation("pdf-crop", {
            "aspectRatio": "16:9", "pageLayout": "landscape",
        })]
    )
    page = PdfReader(BytesIO(cropped.data)).pages[0]
    assert float(page.cropbox.width) == pytest.approx(600)
    assert float(page.cropbox.height) == pytest.approx(337.5)
    assert page.extract_text().strip() == "Keep this searchable"


def test_pdf_crop_operation_resolves_device_name_inside_shared_typed_engine():
    source = pdf_bytes(((600, 800),), text="Keep this searchable")
    cropped = MediaOptimizerEngine.execute(
        source, "source.pdf", [operation("pdf-crop", {"deviceName": "iPad Air"})]
    )
    page = PdfReader(BytesIO(cropped.data)).pages[0]
    assert float(page.cropbox.width) / float(page.cropbox.height) == pytest.approx(41 / 59)
    assert cropped.attributes["aspect_ratio"] == "41:59"
    assert page.extract_text().strip() == "Keep this searchable"


def test_pdf_crop_preserves_page_rotation_and_uses_the_visible_orientation():
    source = pdf_bytes(((600, 800),))
    reader = PdfReader(BytesIO(source))
    rotated = BytesIO()
    from pypdf import PdfWriter

    writer = PdfWriter(clone_from=reader)
    writer.pages[0].rotate(90)
    writer.write(rotated)
    assert PdfReader(BytesIO(rotated.getvalue())).pages[0].rotation == 90
    cropped = MediaPdfEngine.crop_pages(rotated.getvalue(), {"page_size": "mobile"})
    page = PdfReader(BytesIO(cropped[0])).pages[0]

    assert page.rotation == 90
    assert float(page.cropbox.width) == pytest.approx(450)
    assert float(page.cropbox.height) == pytest.approx(800)


def test_pdf_visual_operation_checks_cancellation_and_input_limits():
    source = pdf_bytes()

    class Cancelled:
        @staticmethod
        def is_set():
            return True

    with pytest.raises(MediaPdfCancelledError):
        MediaPdfEngine.visual_optimize(source, {"dpi": 96, "quality": 70}, Cancelled())
    with pytest.raises(ConversionInputError):
        MediaPdfEngine.visual_optimize(b"not a pdf", {"dpi": 96, "quality": 70})
    with pytest.raises(ConversionInputError):
        MediaPdfEngine.crop_pages(b"%PDF-1.7", {"page_size": "letter"})


def test_pdf_visual_operation_rejects_documents_over_the_page_limit(monkeypatch):
    source = pdf_bytes()
    class FakePdf:
        def __len__(self):
            return MediaPdfEngine.MAX_PAGES + 1

        def close(self):
            self.closed = True

    fake = FakePdf()
    monkeypatch.setattr(MediaPdfEngine, "_open_pdfium", lambda _content: fake)
    with pytest.raises(ConversionInputError):
        MediaPdfEngine.visual_optimize(source, {"dpi": 96, "quality": 70})
    assert fake.closed is True
