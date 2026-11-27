"""Trust-boundary and fidelity tests for structured result exports."""

import unittest
import csv
import io
import json
from datetime import datetime, timezone
from io import BytesIO

from openpyxl import load_workbook

from officekit.engines.engine_result_exports import ResultExportEngine


class ResultExportTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "tool_id": "loan_emi",
            "title": "Loan summary",
            "created_at": "2026-10-06T09:30:00+05:30",
            "inputs": [
                {"name": "Principal", "value": 250000, "unit": "INR"},
                {"name": "Annual rate", "value": 8.5, "unit": "%"},
            ],
            "results": [
                {"name": "Monthly payment", "value": 5135.77, "unit": "INR/month"},
                {"name": "Verified", "value": False, "unit": None},
            ],
            "assumptions": ["Fixed nominal rate", "Fees excluded"],
            "tables": [{
                "title": "Schedule",
                "columns": ["Month", "Payment | INR"],
                "rows": [[1, 5135.77], [2, 5135.77]],
            }],
        }
        self.exported_at = datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)

    def test_renders_complete_snapshot_provenance_assumptions_and_numeric_table(self):
        rendered = ResultExportEngine.markdown(self.snapshot, self.exported_at)
        self.assertIn("# Loan summary", rendered)
        self.assertIn("**Tool:** `loan_emi`", rendered)
        self.assertIn("**Operation time:** 2026-10-06T09:30:00+05:30", rendered)
        self.assertIn("**Exported:** 2026-10-06T04:00:00+00:00", rendered)
        self.assertIn("| Principal | 250000 | INR |", rendered)
        self.assertIn("| Verified | false |  |", rendered)
        self.assertIn("- Fixed nominal rate", rendered)
        self.assertIn("| Month | Payment &#124; INR |", rendered)
        self.assertIn("| 2 | 5135.77 |", rendered)

    def test_escapes_markdown_and_html_structure_in_user_supplied_text(self):
        self.snapshot["title"] = "Result <script>alert(1)</script>\x00"
        self.snapshot["assumptions"] = ["Literal [text](javascript:alert(1))\nsecond line"]
        self.snapshot["results"][0]["value"] = "`code` | <img src=x>"
        rendered = ResultExportEngine.markdown(self.snapshot, self.exported_at)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img", rendered)
        self.assertNotIn("\x00", rendered)
        self.assertIn("&#60;script&#62;", rendered)
        self.assertIn("U+0000", rendered)
        self.assertIn("\\[text\\]", rendered)
        self.assertIn("&#124;", rendered)
        self.assertIn("&#96;code&#96;", rendered)

    def test_optional_attribution_is_removable_and_off_by_default(self):
        plain = ResultExportEngine.markdown(self.snapshot, self.exported_at)
        branded = ResultExportEngine.markdown(self.snapshot, self.exported_at, include_attribution=True)
        self.assertNotIn("officekit.app", plain)
        self.assertIn("Generated with OfficeKit · officekit.app", branded)

    def test_html_export_is_standalone_semantic_and_escapes_untrusted_content(self):
        snapshot = dict(self.snapshot)
        snapshot["title"] = "Report <script>alert(1)</script>"
        rendered = ResultExportEngine.html(snapshot, self.exported_at)
        self.assertIn("<!doctype html>", rendered.lower())
        self.assertIn("<table>", rendered)
        self.assertIn("<th scope=\"col\">", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("https://", rendered)
        self.assertNotIn("<img", rendered)
        self.assertNotIn("officekit.app", rendered)

    def test_json_export_preserves_types_schema_and_optional_attribution(self):
        plain = json.loads(ResultExportEngine.json(self.snapshot, self.exported_at))
        branded = json.loads(ResultExportEngine.json(self.snapshot, self.exported_at, include_attribution=True))
        self.assertEqual(plain["schema_version"], "officekit.result.v1")
        self.assertEqual(plain["inputs"][0]["value"], 250000)
        self.assertIs(plain["results"][1]["value"], False)
        self.assertEqual(plain["exported_at"], "2026-10-06T04:00:00+00:00")
        self.assertNotIn("metadata", plain)
        self.assertEqual(branded["metadata"]["attribution"], "Generated with OfficeKit · officekit.app")

    def test_shared_result_export_dispatch_rejects_unknown_formats(self):
        self.assertTrue(ResultExportEngine.export(self.snapshot, "markdown", self.exported_at).startswith("# Loan summary"))
        with self.assertRaisesRegex(ValueError, "Unsupported result export format"):
            ResultExportEngine.export(self.snapshot, "docx", self.exported_at)

    def test_csv_export_contains_typed_inputs_results_assumptions_and_table_cells(self):
        rendered = ResultExportEngine.export(self.snapshot, "csv", self.exported_at)
        records = list(csv.DictReader(io.StringIO(rendered)))
        self.assertEqual(
            rendered.splitlines()[0],
            "record_type,section,name,value,unit,value_type,row_index,column_index",
        )
        self.assertIn({
            "record_type": "metadata", "section": "report", "name": "tool_id",
            "value": "loan_emi", "unit": "", "value_type": "string",
            "row_index": "", "column_index": "",
        }, records)
        self.assertIn({
            "record_type": "input", "section": "inputs", "name": "Principal",
            "value": "250000", "unit": "INR", "value_type": "integer",
            "row_index": "", "column_index": "",
        }, records)
        self.assertIn({
            "record_type": "result", "section": "results", "name": "Verified",
            "value": "false", "unit": "", "value_type": "boolean",
            "row_index": "", "column_index": "",
        }, records)
        self.assertIn({
            "record_type": "table_cell", "section": "Schedule", "name": "Payment | INR",
            "value": "5135.77", "unit": "", "value_type": "number",
            "row_index": "2", "column_index": "2",
        }, records)
        self.assertTrue(any(record["record_type"] == "assumption" for record in records))

    def test_csv_export_neutralizes_formula_cells_but_preserves_numeric_values(self):
        candidate = dict(self.snapshot)
        candidate["title"] = "=1+1"
        candidate["results"] = [
            {"name": "@SUM(A1:A2)", "value": "  +cmd|' /C calc'!A0", "unit": None},
            {"name": "Negative amount", "value": -15, "unit": "USD"},
            {"name": "Unicode formula", "value": "＝1+1\x00", "unit": None},
        ]
        candidate["tables"] = [{"title": "=Sheet1", "columns": ["-Heading"], "rows": [["\t=2+2"]]}]
        rendered = ResultExportEngine.csv(candidate, self.exported_at)
        records = list(csv.DictReader(io.StringIO(rendered)))
        self.assertEqual(next(row["value"] for row in records if row["name"] == "title"), "'=1+1")
        unsafe = next(row for row in records if row["record_type"] == "result")
        self.assertEqual(unsafe["name"], "'@SUM(A1:A2)")
        self.assertEqual(unsafe["value"], "'  +cmd|' /C calc'!A0")
        negative = next(row for row in records if row["name"] == "Negative amount")
        self.assertEqual(negative["value"], "-15")
        self.assertEqual(negative["value_type"], "integer")
        unicode_formula = next(row for row in records if row["name"] == "Unicode formula")
        self.assertEqual(unicode_formula["value"], "'＝1+1[control U+0000]")
        self.assertIn("[control U+0009]=2+2", rendered)
        self.assertNotIn("\t=2+2", rendered)

    def test_csv_attribution_is_optional_and_csv_rejects_invalid_export_options(self):
        plain = ResultExportEngine.csv(self.snapshot, self.exported_at)
        branded = ResultExportEngine.csv(self.snapshot, self.exported_at, include_attribution=True)
        self.assertNotIn("officekit.app", plain)
        self.assertIn("officekit.app", branded)
        self.assertTrue(ResultExportEngine.export(self.snapshot, "csv", self.exported_at))
        with self.assertRaisesRegex(ValueError, "Unsupported result export format"):
            ResultExportEngine.export(self.snapshot, "docx", self.exported_at)

    def test_csv_preserves_empty_table_headers(self):
        candidate = dict(self.snapshot)
        candidate["tables"] = [{"title": "No rows", "columns": ["Month", "Balance"], "rows": []}]
        records = list(csv.DictReader(io.StringIO(ResultExportEngine.csv(candidate, self.exported_at))))
        headers = [record for record in records if record["record_type"] == "table_column"]
        self.assertEqual([record["name"] for record in headers], ["Month", "Balance"])
        self.assertEqual([record["row_index"] for record in headers], ["0", "0"])

    def test_xlsx_export_preserves_typed_values_tables_metadata_and_attribution(self):
        rendered = ResultExportEngine.export(self.snapshot, "xlsx", self.exported_at)
        workbook = load_workbook(BytesIO(rendered), data_only=False)
        self.assertEqual(workbook.sheetnames, ["Result"])
        sheet = workbook["Result"]
        rows = list(sheet.iter_rows(values_only=True))
        self.assertEqual(rows[0][0], "OfficeKit result")
        self.assertIn(("Tool", "loan_emi"), [row[:2] for row in rows])
        self.assertIn(("Operation time", "2026-10-06T09:30:00+05:30"), [row[:2] for row in rows])
        self.assertIn(("Exported", "2026-10-06T04:00:00+00:00"), [row[:2] for row in rows])
        self.assertIn(("Input", "Principal", 250000, "INR"), [row[:4] for row in rows])
        self.assertIn(("Result", "Verified", False, None), [row[:4] for row in rows])
        self.assertIn(("Assumption", "Fixed nominal rate"), [row[:2] for row in rows])
        self.assertIn(("Schedule", "Month", "Payment | INR"), [row[:3] for row in rows])
        self.assertIn((None, 1, 5135.77), [row[:3] for row in rows])
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(workbook.properties.creator, "OfficeKit")

        branded_bytes = ResultExportEngine.export(self.snapshot, "xlsx", self.exported_at, True)
        branded = load_workbook(BytesIO(branded_bytes), data_only=False)["Result"]
        branded_rows = list(branded.iter_rows(values_only=True))
        self.assertIn(("Attribution", "Generated with OfficeKit · officekit.app"), [row[:2] for row in branded_rows])

    def test_xlsx_export_stores_untrusted_formula_like_text_as_literal_strings(self):
        candidate = dict(self.snapshot)
        candidate["title"] = "=HYPERLINK(\"https://example.invalid\",\"open\")"
        candidate["results"] = [{"name": "+SUM(A1:A2)", "value": "\t=1+1", "unit": None}]
        workbook = load_workbook(
            BytesIO(ResultExportEngine.export(candidate, "xlsx", self.exported_at)), data_only=False
        )
        sheet = workbook["Result"]
        self.assertEqual(workbook.properties.title, candidate["title"])
        result_row = next(
            row for row in sheet.iter_rows(values_only=False)
            if row[0].value == "Result" and row[1].value == "+SUM(A1:A2)"
        )
        self.assertEqual(result_row[2].value, "[control U+0009]=1+1")
        self.assertTrue(all(cell.data_type != "f" for row in sheet.iter_rows() for cell in row))

    def test_xlsx_export_rejects_cell_expansion_beyond_the_workbook_bound(self):
        candidate = dict(self.snapshot)
        candidate["inputs"] = []
        candidate["results"] = []
        candidate["assumptions"] = []
        candidate["tables"] = [{
            "title": "Wide",
            "columns": [f"C{column}" for column in range(40)],
            "rows": [[0] * 40 for _ in range(2_501)],
        }]
        with self.assertRaisesRegex(ValueError, "100,000-cell"):
            ResultExportEngine.xlsx(candidate, self.exported_at)

    def test_xlsx_export_replaces_xml_forbidden_controls_and_noncharacters(self):
        candidate = dict(self.snapshot)
        candidate["title"] = "Title\x00 and \ufffe"
        candidate["results"] = [{"name": "Control\x00", "value": "Forbidden\ufffe text", "unit": None}]
        workbook = load_workbook(
            BytesIO(ResultExportEngine.xlsx(candidate, self.exported_at)), data_only=False
        )
        result_row = next(
            row for row in workbook["Result"].iter_rows(values_only=True)
            if row[0] == "Result" and row[1] == "Control[control U+0000]"
        )
        self.assertEqual(workbook.properties.title, "Title[control U+0000] and [control U+FFFE]")
        self.assertEqual(result_row[2], "Forbidden[control U+FFFE] text")

    def test_rejects_naive_export_time_and_operation_time(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            ResultExportEngine.markdown(self.snapshot, datetime(2026, 10, 6, 4, 0))
        self.snapshot["created_at"] = "2026-10-06T09:30:00"
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            ResultExportEngine.markdown(self.snapshot, self.exported_at)

    def test_rejects_invalid_identifiers_timestamps_and_attribution_types(self):
        for tool_id in ("../secret", "UPPER_CASE", " "):
            candidate = dict(self.snapshot)
            candidate["tool_id"] = tool_id
            with self.subTest(tool_id=tool_id), self.assertRaisesRegex(ValueError, "Tool ID"):
                ResultExportEngine.markdown(candidate, self.exported_at)

        candidate = dict(self.snapshot)
        candidate["created_at"] = "not-a-timestamp"
        with self.assertRaisesRegex(ValueError, "ISO 8601"):
            ResultExportEngine.markdown(candidate, self.exported_at)
        with self.assertRaisesRegex(ValueError, "boolean"):
            ResultExportEngine.markdown(self.snapshot, self.exported_at, include_attribution=1)

    def test_rejects_empty_report_and_invalid_nested_shapes(self):
        candidate = dict(self.snapshot)
        candidate.update(inputs=[], results=[], assumptions=[], tables=[])
        with self.assertRaisesRegex(ValueError, "at least one"):
            ResultExportEngine.markdown(candidate, self.exported_at)

        candidate = dict(self.snapshot)
        candidate["inputs"] = [{"name": "Value", "value": [], "unit": None}]
        with self.assertRaisesRegex(ValueError, "string, number, boolean or null"):
            ResultExportEngine.markdown(candidate, self.exported_at)

        candidate = dict(self.snapshot)
        candidate["tables"] = [{"title": "Empty", "columns": [], "rows": []}]
        with self.assertRaisesRegex(ValueError, "between 1 and 40"):
            ResultExportEngine.markdown(candidate, self.exported_at)

    def test_enforces_aggregate_text_row_and_rendered_output_limits(self):
        candidate = dict(self.snapshot)
        candidate["assumptions"] = ["é" * 9_000 for _ in range(60)]
        with self.assertRaisesRegex(ValueError, "1,048,576 UTF-8 byte"):
            ResultExportEngine.markdown(candidate, self.exported_at)

        candidate = dict(self.snapshot)
        candidate["tables"] = [{"title": "Large", "columns": ["A"], "rows": [[1]] * 10_001}]
        with self.assertRaisesRegex(ValueError, "10,000 rows"):
            ResultExportEngine.markdown(candidate, self.exported_at)

        candidate = dict(self.snapshot)
        candidate["assumptions"] = ["|" * 10_000] * 100
        with self.assertRaisesRegex(ValueError, "4 MiB"):
            ResultExportEngine.markdown(candidate, self.exported_at)

    def test_rejects_extra_keys_invalid_values_and_table_shape_mismatch(self):
        for field, invalid in (
            ("unexpected", True),
            ("title", 42),
        ):
            candidate = dict(self.snapshot)
            candidate[field] = invalid
            with self.subTest(field=field), self.assertRaises(ValueError):
                ResultExportEngine.markdown(candidate, self.exported_at)

        candidate = dict(self.snapshot)
        candidate["results"] = [{"name": "Bad", "value": float("nan"), "unit": None}]
        with self.assertRaisesRegex(ValueError, "finite"):
            ResultExportEngine.markdown(candidate, self.exported_at)

        candidate = dict(self.snapshot)
        candidate["tables"] = [{"title": "Broken", "columns": ["A", "B"], "rows": [[1]]}]
        with self.assertRaisesRegex(ValueError, "column count"):
            ResultExportEngine.markdown(candidate, self.exported_at)

    def test_enforces_bounds_and_rejects_non_mapping_snapshots(self):
        for snapshot in (None, "bad"):
            with self.subTest(snapshot=snapshot), self.assertRaises(ValueError):
                ResultExportEngine.markdown(snapshot, self.exported_at)
        candidate = dict(self.snapshot)
        candidate["assumptions"] = ["a" * 10_001]
        with self.assertRaisesRegex(ValueError, "10,000"):
            ResultExportEngine.markdown(candidate, self.exported_at)


if __name__ == "__main__":
    unittest.main()
