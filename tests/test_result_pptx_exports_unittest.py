"""PowerPoint result-export fidelity and safety regressions."""

import unittest
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import patch

from pptx import Presentation

from officekit.engines.engine_result_exports import ResultExportEngine


class ResultPptxExportTests(unittest.TestCase):
    def setUp(self):
        self.exported_at = datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)
        self.snapshot = {
            "tool_id": "loan_emi",
            "title": "Loan summary",
            "created_at": "2026-10-06T09:30:00+05:30",
            "inputs": [{"name": "Principal", "value": 250000, "unit": "INR"}],
            "results": [{"name": "Monthly payment", "value": 5135.77, "unit": "INR/month"}],
            "assumptions": ["Fixed nominal rate", "Fees excluded"],
            "tables": [{
                "title": "Schedule",
                "columns": ["Month", "Balance"],
                "rows": [[1, 200000], [2, 150000]],
            }],
        }

    def _presentation(self, snapshot=None, include_attribution=False):
        rendered = ResultExportEngine.pptx(
            snapshot or self.snapshot, self.exported_at, include_attribution,
        )
        return Presentation(BytesIO(rendered))

    @staticmethod
    def _all_text(presentation):
        text = []
        for slide in presentation.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    text.append(shape.text)
                if shape.has_table:
                    text.extend(cell.text for row in shape.table.rows for cell in row.cells)
        return "\n".join(text)

    def test_pptx_preserves_report_values_assumptions_table_and_dates(self):
        presentation = self._presentation()
        text = self._all_text(presentation)
        self.assertIn("Loan summary", text)
        self.assertIn("Principal: 250000 INR", text)
        self.assertIn("Monthly payment: 5135.77 INR/month", text)
        self.assertIn("Fixed nominal rate", text)
        self.assertIn("Operation time: 2026-10-06T09:30:00+05:30", text)
        self.assertIn("Exported: 2026-10-06T04:00:00+00:00", text)
        self.assertIn("Schedule", text)
        self.assertIn("150000", text)

    def test_pptx_attribution_is_optional_in_footer_and_metadata(self):
        plain = self._presentation()
        plain_text = self._all_text(plain)
        self.assertNotIn("officekit.app", plain_text)
        self.assertNotEqual(plain.core_properties.author, "OfficeKit")

        branded = self._presentation(include_attribution=True)
        branded_text = self._all_text(branded)
        self.assertIn("Generated with OfficeKit · officekit.app", branded_text)
        self.assertEqual(branded.core_properties.author, "OfficeKit")

    def test_pptx_preserves_formula_shaped_text_as_text_and_replaces_xml_controls(self):
        candidate = dict(self.snapshot)
        candidate["title"] = "=1+1\x00"
        candidate["results"] = [{"name": "Literal", "value": "=HYPERLINK(\"x\")\x01", "unit": None}]
        presentation = self._presentation(candidate)
        text = self._all_text(presentation)
        self.assertIn("=1+1[control U+0000]", text)
        self.assertIn("=HYPERLINK(\"x\")[control U+0001]", text)

    def test_pptx_splits_wide_and_long_tables_without_dropping_cells(self):
        candidate = dict(self.snapshot)
        candidate["tables"] = [{
            "title": "Wide schedule",
            "columns": [f"Column {index}" for index in range(1, 15)],
            "rows": [[f"cell-{row}-{column}" for column in range(1, 15)] for row in range(1, 46)],
        }]
        presentation = self._presentation(candidate)
        text = self._all_text(presentation)
        self.assertIn("cell-1-1", text)
        self.assertIn("cell-45-14", text)
        self.assertIn("Columns 1–6", text)
        self.assertIn("Rows 41–45", text)

    def test_pptx_handles_empty_sections_and_header_only_tables(self):
        candidate = dict(self.snapshot)
        candidate["inputs"] = []
        candidate["assumptions"] = []
        candidate["tables"] = [{"title": "No schedule yet", "columns": ["Month", "Balance"], "rows": []}]
        presentation = self._presentation(candidate)
        text = self._all_text(presentation)
        self.assertIn("Monthly payment: 5135.77 INR/month", text)
        self.assertIn("No schedule yet", text)
        self.assertIn("Month", text)
        self.assertIn("Balance", text)
        self.assertIn("Rows 0–0", text)

    def test_pptx_rejects_reports_that_exceed_explicit_slide_bound(self):
        candidate = dict(self.snapshot)
        candidate["tables"] = [{
            "title": "Very large",
            "columns": [f"Column {index}" for index in range(1, 41)],
            "rows": [[f"cell-{row}-{column}" for column in range(1, 41)] for row in range(1, 1_001)],
        }]
        with self.assertRaisesRegex(ValueError, "PowerPoint report exceeds the supported slide limit"):
            ResultExportEngine.pptx(candidate, self.exported_at)

    def test_pptx_rejects_output_over_the_attachment_size_limit(self):
        with patch.object(ResultExportEngine, "MAX_PPTX_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "PowerPoint output exceeds the 8 MiB export limit"):
                ResultExportEngine.pptx(self.snapshot, self.exported_at)

    def test_dispatch_rejects_unsupported_formats_after_registering_pptx(self):
        result = ResultExportEngine.export(self.snapshot, "pptx", self.exported_at)
        self.assertTrue(result.startswith(b"PK"))
        with self.assertRaisesRegex(ValueError, "Unsupported result export format"):
            ResultExportEngine.export(self.snapshot, "docx", self.exported_at)


if __name__ == "__main__":
    unittest.main()
