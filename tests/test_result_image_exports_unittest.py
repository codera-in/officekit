"""Actual pixel and API attachment checks for shareable result images."""

from datetime import datetime, timezone
from io import BytesIO
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app import app
from officekit.engines.engine_result_exports import ResultExportEngine


EXPORTED_AT = datetime(2026, 10, 7, 9, 30, tzinfo=timezone.utc)


def snapshot():
    return {
        "tool_id": "loan_emi",
        "title": "Loan repayment estimate",
        "created_at": "2026-10-07T09:00:00+00:00",
        "inputs": [
            {"name": "Principal", "value": 50000, "unit": "USD"},
            {"name": "Annual rate", "value": 6.5, "unit": "%"},
            {"name": "Term", "value": 60, "unit": "months"},
        ],
        "results": [
            {"name": "Monthly payment", "value": 978.16, "unit": "USD"},
            {"name": "Total interest", "value": 8690.0, "unit": "USD"},
        ],
        "assumptions": ["Fixed annual rate; monthly payments; no fees or extra repayments."],
        "tables": [{"title": "Schedule", "columns": ["Month", "Payment"], "rows": [[1, 978.16]]}],
    }


class ResultImageExportTests(unittest.TestCase):
    def test_png_and_jpeg_are_real_single_page_summary_images(self):
        png = ResultExportEngine.export(snapshot(), "png", EXPORTED_AT)
        jpeg = ResultExportEngine.export(snapshot(), "jpeg", EXPORTED_AT)

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(jpeg.startswith(b"\xff\xd8\xff"))
        with Image.open(BytesIO(png)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size[0], 1275)
            self.assertIn(image.size[1], (1650, 1651))
            self.assertEqual(image.info, {})
        with Image.open(BytesIO(jpeg)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.size[0], 1275)
            self.assertIn(image.size[1], (1650, 1651))
            self.assertEqual(dict(image.getexif()), {})

    def test_attribution_is_visible_in_rendered_content_and_explicit_image_metadata(self):
        without_attribution = ResultExportEngine.export(snapshot(), "png", EXPORTED_AT)
        with_attribution = ResultExportEngine.export(snapshot(), "png", EXPORTED_AT, True)
        self.assertNotEqual(with_attribution, without_attribution)

        with Image.open(BytesIO(with_attribution)) as png:
            self.assertEqual(png.info["Software"], "OfficeKit")
            self.assertEqual(png.info["Description"], "Generated with OfficeKit · officekit.app")
            with Image.open(BytesIO(without_attribution)) as original:
                self.assertNotEqual(
                    png.crop((900, 1550, 1260, 1630)).tobytes(),
                    original.crop((900, 1550, 1260, 1630)).tobytes(),
                )

        jpeg = ResultExportEngine.export(snapshot(), "jpeg", EXPORTED_AT, True)
        with Image.open(BytesIO(jpeg)) as image:
            metadata = image.getexif()
            self.assertEqual(metadata[305], "OfficeKit")
            self.assertEqual(metadata[270], "Generated with OfficeKit - officekit.app")

    def test_image_export_rejects_summaries_that_would_truncate_across_pages(self):
        oversized = snapshot()
        oversized["assumptions"] = [f"Assumption {index}: " + ("Details. " * 60) for index in range(80)]

        with self.assertRaisesRegex(ValueError, "one-page image"):
            ResultExportEngine.export(oversized, "png", EXPORTED_AT)

    def test_summary_image_still_validates_table_data_that_is_not_rendered(self):
        invalid = snapshot()
        invalid["tables"][0]["columns"] = [f"column-{index}" for index in range(41)]

        with self.assertRaisesRegex(ValueError, "40"):
            ResultExportEngine.export(invalid, "png", EXPORTED_AT)

    def test_image_export_enforces_output_size_limit(self):
        with patch.object(ResultExportEngine, "MAX_IMAGE_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "8 MiB"):
                ResultExportEngine.export(snapshot(), "jpeg", EXPORTED_AT)

    def test_result_image_http_attachments_have_decodable_pixels_and_safe_names(self):
        client = TestClient(app)
        payload = snapshot()
        payload["include_attribution"] = True

        for fmt, media_type, signature, extension in (
            ("png", "image/png", b"\x89PNG\r\n\x1a\n", ".png"),
            ("jpeg", "image/jpeg", b"\xff\xd8\xff", ".jpg"),
        ):
            with self.subTest(format=fmt):
                response = client.post("/api/export/result", json={**payload, "format": fmt})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(response.headers["content-type"].startswith(media_type))
                self.assertIn(f"loan_emi-result{extension}", response.headers["content-disposition"])
                self.assertTrue(response.content.startswith(signature))
                with Image.open(BytesIO(response.content)) as image:
                    self.assertEqual(image.size[0], 1275)
                    self.assertIn(image.size[1], (1650, 1651))

    def test_unsupported_image_format_is_rejected_by_the_typed_http_contract(self):
        response = TestClient(app).post(
            "/api/export/result",
            json={**snapshot(), "format": "gif"},
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
