import io
import unittest
import zipfile
import base64
from unittest.mock import patch

from officekit.engines.engine_pdf_images import PdfImageExportEngine


class FakeBitmap:
    def __init__(self, payload):
        self.payload = payload
        self.closed = False

    def to_pil(self):
        return FakeImage(self.payload)

    def close(self):
        self.closed = True


class FakeImage:
    def __init__(self, payload):
        self.payload = payload
        self.mode = "RGBA"
        self.converted = None
        self.closed = False

    def copy(self):
        return FakeImage(self.payload)

    def convert(self, mode):
        self.converted = mode
        image = FakeImage(self.payload)
        image.mode = mode
        return image

    def save(self, target, format, **options):
        target.write(f"{format}:{self.payload}:{self.mode}".encode("ascii"))

    def close(self):
        self.closed = True


class FakePage:
    def __init__(self, width=612, height=792):
        self.width = width
        self.height = height
        self.scales = []
        self.closed = False
        self.bitmap = None

    def get_size(self):
        return self.width, self.height

    def render(self, **kwargs):
        self.scales.append(kwargs["scale"])
        self.bitmap = FakeBitmap(f"page-{len(self.scales)}")
        return self.bitmap

    def close(self):
        self.closed = True


class FakeDocument:
    def __init__(self, pages):
        self.pages = pages
        self.closed = False

    def __len__(self):
        return len(self.pages)

    def __getitem__(self, index):
        return self.pages[index]

    def close(self):
        self.closed = True


class FakePdfium:
    def __init__(self, pages):
        self.document = FakeDocument(pages)
        self.input_bytes = None

    def PdfDocument(self, content):
        self.input_bytes = content
        return self.document


class PdfImageExportTests(unittest.TestCase):
    def test_renders_bounded_page_thumbnail_window_with_source_page_numbers(self):
        pages = [FakePage(300, 500), FakePage(612, 792), FakePage(400, 600)]
        pdfium = FakePdfium(pages)

        result = PdfImageExportEngine.render_page_thumbnails(
            b"pdf", [2, 3], pdfium_module=pdfium,
        )

        self.assertEqual(result["page_count"], 3)
        self.assertEqual([page["page_number"] for page in result["pages"]], [2, 3])
        self.assertEqual([page["width_points"] for page in result["pages"]], [612, 400])
        self.assertEqual(pages[0].scales, [])
        self.assertEqual(pages[1].scales, [240 / 792])
        self.assertEqual(pages[2].scales, [0.4])
        self.assertEqual(
            base64.b64decode(result["pages"][0]["data_base64"]),
            b"PNG:page-1:RGBA",
        )
        self.assertTrue(pdfium.document.closed)
        self.assertFalse(pages[0].closed)
        self.assertTrue(all(page.closed for page in pages[1:]))

    def test_thumbnail_validation_rejects_invalid_windows_and_page_count(self):
        for content, page_numbers, pages in (
            (b"", [1], [FakePage()]),
            (b"pdf", [], [FakePage()]),
            (b"pdf", [0], [FakePage()]),
            (b"pdf", [True], [FakePage()]),
            (b"pdf", [1] * 25, [FakePage()]),
            (b"pdf", [1, 1], [FakePage(), FakePage()]),
            (b"pdf", [2], [FakePage()]),
            (b"pdf", [1], [FakePage() for _ in range(2_001)]),
        ):
            with self.subTest(page_numbers=page_numbers, count=len(pages)):
                with self.assertRaises(ValueError):
                    PdfImageExportEngine.render_page_thumbnails(
                        content, page_numbers, pdfium_module=FakePdfium(pages),
                    )

    def test_thumbnail_rendering_rejects_invalid_dimensions_and_encoded_size(self):
        with self.assertRaises(ValueError):
            PdfImageExportEngine.render_page_thumbnails(
                b"pdf", [1], pdfium_module=FakePdfium([FakePage(width=float("nan"))]),
            )
        with patch.object(PdfImageExportEngine, "MAX_THUMBNAIL_RESPONSE_BYTES", 2):
            with self.assertRaises(ValueError):
                PdfImageExportEngine.render_page_thumbnails(
                    b"pdf", [1], pdfium_module=FakePdfium([FakePage()]),
                )

    def test_renders_every_page_to_ordered_jpeg_zip_at_requested_dpi(self):
        pages = [FakePage(), FakePage(width=300, height=500)]
        pdfium = FakePdfium(pages)

        archive, page_count = PdfImageExportEngine.render_pdf(b"%PDF-fake", "jpg", dpi=144, pdfium_module=pdfium)

        self.assertEqual(page_count, 2)
        self.assertEqual(pages[0].scales, [2.0])
        self.assertEqual(pages[1].scales, [2.0])
        self.assertTrue(pdfium.document.closed)
        self.assertTrue(all(page.closed for page in pages))
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            self.assertEqual(bundle.namelist(), ["page-001.jpg", "page-002.jpg"])
            self.assertEqual(bundle.read("page-001.jpg"), b"JPEG:page-1:RGB")
            self.assertEqual(bundle.read("page-002.jpg"), b"JPEG:page-1:RGB")

    def test_renders_png_with_alpha_preserved_and_safe_names(self):
        archive, count = PdfImageExportEngine.render_pdf(b"pdf", "png", dpi=72, pdfium_module=FakePdfium([FakePage()]))

        self.assertEqual(count, 1)
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            self.assertEqual(bundle.namelist(), ["page-001.png"])
            self.assertEqual(bundle.read("page-001.png"), b"PNG:page-1:RGBA")

    def test_rejects_unsupported_format_and_dpi_before_opening_pdf(self):
        for fmt, dpi, quality in (("pdf", 144, 90), ("gif", 144, 90), ("jpg", 35, 90),
                                  ("png", 301, 90), ("jpg", True, 90), ("png", 72.5, 90),
                                  ("jpg", 144, 0), ("jpg", 144, 101), ("png", 144, True)):
            with self.subTest(fmt=fmt, dpi=dpi, quality=quality):
                with self.assertRaises(ValueError):
                    PdfImageExportEngine.render_pdf(b"pdf", fmt, dpi=dpi, quality=quality, pdfium_module=FakePdfium([]))

    def test_rejects_empty_inputs_and_document_without_pages(self):
        with self.assertRaises(ValueError):
            PdfImageExportEngine.render_pdf(b"", "png", pdfium_module=FakePdfium([]))
        with self.assertRaises(ValueError):
            PdfImageExportEngine.render_pdf(b"pdf", "png", pdfium_module=FakePdfium([]))

    def test_rejects_more_than_maximum_page_count(self):
        pages = [FakePage() for _ in range(PdfImageExportEngine.MAX_PAGES + 1)]
        with self.assertRaises(ValueError):
            PdfImageExportEngine.render_pdf(b"pdf", "png", pdfium_module=FakePdfium(pages))

    def test_rejects_total_pixel_budget_and_oversized_pdf_before_rendering(self):
        pages = [FakePage(width=3600, height=2000) for _ in range(18)]
        pdfium = FakePdfium(pages)
        with self.assertRaises(ValueError):
            PdfImageExportEngine.render_pdf(b"pdf", "png", dpi=72, pdfium_module=pdfium)
        self.assertTrue(pdfium.document.closed)
        self.assertTrue(all(page.scales == [] for page in pages))

        with patch.object(PdfImageExportEngine, "MAX_PDF_BYTES", 3):
            with self.assertRaises(ValueError):
                PdfImageExportEngine.render_pdf(b"pdfx", "png", pdfium_module=FakePdfium([]))

    def test_rejects_page_exceeding_pixel_budget_before_rendering(self):
        page = FakePage(width=100_000, height=100_000)
        with self.assertRaises(ValueError):
            PdfImageExportEngine.render_pdf(b"pdf", "png", dpi=300, pdfium_module=FakePdfium([page]))
        self.assertEqual(page.scales, [])

    def test_rejects_output_over_archive_budget_and_closes_render_handles(self):
        page = FakePage()
        with patch.object(PdfImageExportEngine, "MAX_OUTPUT_BYTES", 4):
            with self.assertRaises(ValueError):
                PdfImageExportEngine.render_pdf(b"pdf", "png", pdfium_module=FakePdfium([page]))
        self.assertTrue(page.closed)
        self.assertTrue(page.bitmap.closed)


if __name__ == "__main__":
    unittest.main()
