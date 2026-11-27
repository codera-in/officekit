"""Searchable PDF result-export fidelity, pagination and safety tests."""

import unittest
import os
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import patch

from pypdf import PdfReader

from officekit.engines.engine_result_exports import ResultExportEngine


class ResultPdfExportTests(unittest.TestCase):
    def setUp(self):
        self.exported_at = datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)
        self.snapshot = {
            "tool_id": "loan_emi",
            "title": "Loan summary",
            "created_at": "2026-10-06T09:30:00+05:30",
            "inputs": [{"name": "Principal", "value": 250000, "unit": "INR"}],
            "results": [
                {"name": "Monthly payment", "value": 5135.77, "unit": "INR/month"},
                {"name": "Paid off", "value": False, "unit": None},
            ],
            "assumptions": ["Fixed nominal rate", "Fees excluded"],
            "tables": [{
                "title": "Schedule",
                "columns": ["Month", "Balance"],
                "rows": [[1, 200000], [2, 150000]],
            }],
        }

    def _reader(self, snapshot=None, include_attribution=False):
        content = ResultExportEngine.pdf(
            snapshot or self.snapshot, self.exported_at, include_attribution,
        )
        self.assertTrue(content.startswith(b"%PDF-"))
        self.assertLessEqual(len(content), ResultExportEngine.MAX_PDF_BYTES)
        return PdfReader(BytesIO(content))

    @staticmethod
    def _text(reader):
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    def test_pdf_is_searchable_and_preserves_values_units_assumptions_and_timestamps(self):
        reader = self._reader()
        text = self._text(reader)
        for expected in (
            "Loan summary", "Principal", "250000", "INR", "Monthly payment",
            "5135.77", "INR/month", "Paid off", "false", "Fixed nominal rate",
            "Fees excluded", "Schedule", "200000", "150000",
            "Operation time: 2026-10-06T09:30:00+05:30",
            "Exported: 2026-10-06T04:00:00+00:00",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, text)

    def test_pdf_embeds_optional_visible_and_metadata_attribution_only_when_requested(self):
        plain = self._reader()
        plain_text = self._text(plain)
        self.assertNotIn("officekit.app", plain_text)
        self.assertNotEqual(plain.metadata.author, "OfficeKit")
        self.assertNotEqual(plain.metadata.creator, "OfficeKit")

        branded = self._reader(include_attribution=True)
        self.assertIn("Generated with OfficeKit · officekit.app", self._text(branded))
        self.assertEqual(branded.metadata.author, "OfficeKit")

    def test_pdf_escapes_markup_and_replaces_xml_forbidden_controls_as_literal_text(self):
        candidate = dict(self.snapshot)
        candidate["title"] = "Result <script>alert(1)</script>\x00"
        candidate["assumptions"] = ["Literal & safe\x01"]
        reader = self._reader(candidate)
        text = self._text(reader)
        self.assertIn("Result <script>alert(1)</script>[control U+0000]", text)
        self.assertIn("Literal & safe[control U+0001]", text)

    def test_pdf_shapes_and_extracts_tamil_text_and_mixed_latin_text(self):
        candidate = dict(self.snapshot)
        candidate["title"] = "OfficeKit · கணக்கீட்டு முடிவு"
        candidate["results"] = [{"name": "மாதத் தவணை", "value": 5135.77, "unit": "INR/month"}]
        text = self._text(self._reader(candidate))
        self.assertIn("கணக்கீட்டு முடிவு", text)
        self.assertIn("மாதத் தவணை", text)
        self.assertIn("5135.77", text)
        from reportlab.pdfbase.pdfmetrics import getFont
        self.assertEqual(os.path.basename(getFont("OfficeKitTamil").face.filename), "NotoSansTamil-Regular.ttf")

    def test_pdf_repeats_table_headers_and_paginates_wide_tables_without_dropping_cells(self):
        candidate = dict(self.snapshot)
        candidate["tables"] = [{
            "title": "Wide schedule",
            "columns": [f"Column {index}" for index in range(1, 15)],
            "rows": [[f"cell-{row}-{column}" for column in range(1, 15)] for row in range(1, 61)],
        }]
        reader = self._reader(candidate)
        text = self._text(reader)
        self.assertGreaterEqual(len(reader.pages), 3)
        self.assertIn("cell-1-1", text)
        self.assertIn("cell-60-14", text)
        self.assertIn("Columns 1-6", text)
        header_pages = sum("Column 1" in (page.extract_text() or "") for page in reader.pages)
        self.assertGreaterEqual(header_pages, 3)
        self.assertTrue(all(f"Page {index}" in (page.extract_text() or "") for index, page in enumerate(reader.pages, 1)))

    def test_pdf_rejects_excessive_page_work_before_rendering(self):
        candidate = dict(self.snapshot)
        candidate["tables"] = [{
            "title": "Too large",
            "columns": [f"Column {index}" for index in range(1, 41)],
            "rows": [[0] * 40 for _ in range(1_000)],
        }]
        with self.assertRaisesRegex(ValueError, "PDF report exceeds the supported page limit"):
            ResultExportEngine.pdf(candidate, self.exported_at)

    def test_pdf_rejects_output_over_the_attachment_size_limit(self):
        with patch.object(ResultExportEngine, "MAX_PDF_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "PDF output exceeds the 8 MiB export limit"):
                ResultExportEngine.pdf(self.snapshot, self.exported_at)

    def test_pdf_rejects_text_without_a_supported_embedded_glyph(self):
        candidate = dict(self.snapshot)
        candidate["results"] = [{"name": "Unsupported glyph", "value": "\U0001f680", "unit": None}]
        with self.assertRaisesRegex(ValueError, "PDF fonts cannot display one or more result characters"):
            ResultExportEngine.pdf(candidate, self.exported_at)

    def test_dispatch_includes_pdf_and_keeps_unknown_formats_rejected(self):
        result = ResultExportEngine.export(self.snapshot, "pdf", self.exported_at)
        self.assertTrue(result.startswith(b"%PDF-"))
        with self.assertRaisesRegex(ValueError, "Unsupported result export format"):
            ResultExportEngine.export(self.snapshot, "docx", self.exported_at)


if __name__ == "__main__":
    unittest.main()
