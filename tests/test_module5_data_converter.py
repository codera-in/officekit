"""
TDD Tests for Module 5: Structured Data & Code Converters
- JSON ⇄ CSV ⇄ Excel ⇄ TSV
- YAML ⇄ JSON
- SQL INSERT generator from tabular rows
"""

import unittest
import csv
import io
import json
import zipfile
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from openpyxl import Workbook, load_workbook
import xlwt
from officekit.engines.engine_file_converter import FileConverterEngine
from officekit.engines.engine_conversion_errors import ConversionInputError

class TestModule5StructuredDataConverter(unittest.TestCase):

    @staticmethod
    def _xlsx_bytes(rows):
        workbook = Workbook()
        sheet = workbook.active
        for row in rows:
            sheet.append(row)
        output = io.BytesIO()
        workbook.save(output)
        workbook.close()
        return output.getvalue()

    @staticmethod
    def _xls_bytes(rows):
        workbook = xlwt.Workbook()
        sheet = workbook.add_sheet("Transactions")
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                sheet.write(row_index, column_index, value)
        output = io.BytesIO()
        workbook.save(output)
        return output.getvalue()

    def test_legacy_xls_conversion_reads_text_identifiers_and_numeric_cells(self):
        source = self._xls_bytes([
            ["account", "amount"],
            ["000042", 12.5],
        ])

        converted, mime = FileConverterEngine.convert_data_file(source, "xls", "json")

        self.assertEqual(mime, "application/json")
        self.assertEqual(json.loads(converted), [{"account": "000042", "amount": 12.5}])

    def test_legacy_xls_conversion_rejects_corrupt_workbook_with_safe_error(self):
        with self.assertRaises(ConversionInputError):
            FileConverterEngine.convert_data_file(b"not an XLS workbook", "xls", "json")

    def test_legacy_xls_conversion_enforces_shared_table_limits(self):
        source = self._xls_bytes([
            ["first", "second"],
            ["a", "b"],
            ["c", "d"],
        ])
        for limit_name, limit in (
            ("MAX_TABULAR_ROWS", 1),
            ("MAX_TABULAR_COLUMNS", 1),
            ("MAX_TABULAR_CELLS", 5),
        ):
            with self.subTest(limit=limit_name), patch.object(FileConverterEngine, limit_name, limit):
                with self.assertRaises(ConversionInputError):
                    FileConverterEngine.convert_data_file(source, "xls", "json")

    def test_xlsx_conversion_enforces_shared_row_column_and_cell_limits_before_import(self):
        source = self._xlsx_bytes([
            ["first", "second"],
            ["a", "b"],
            ["c", "d"],
        ])
        for limit_name, limit in (
            ("MAX_TABULAR_ROWS", 1),
            ("MAX_TABULAR_COLUMNS", 1),
            ("MAX_TABULAR_CELLS", 5),
        ):
            with self.subTest(limit=limit_name), patch.object(FileConverterEngine, limit_name, limit):
                with self.assertRaises(ConversionInputError):
                    FileConverterEngine.convert_data_file(source, "xlsx", "json")

    def test_xlsx_conversion_accepts_normal_workbook_with_header_and_blank_cells(self):
        source = self._xlsx_bytes([
            ["account", "amount", "note"],
            ["001234", 25.5, None],
            ["000045", 0, "paid"],
        ])
        converted, mime = FileConverterEngine.convert_data_file(source, "xlsx", "json")

        self.assertEqual(mime, "application/json")
        self.assertEqual(json.loads(converted), [
            {"account": "001234", "amount": 25.5, "note": None},
            {"account": "000045", "amount": 0, "note": "paid"},
        ])

    def test_xlsx_conversion_preserves_zero_padded_number_formats_and_iso_dates(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["account", "posted_at", "amount"])
        sheet.append([1234, datetime(2026, 10, 7), 25.5])
        sheet["A2"].number_format = "000000"
        sheet["B2"].number_format = "yyyy-mm-dd"
        source = io.BytesIO()
        workbook.save(source)
        workbook.close()

        converted, _mime = FileConverterEngine.convert_data_file(source.getvalue(), "xlsx", "json")

        self.assertEqual(json.loads(converted), [
            {"account": "001234", "posted_at": "2026-10-07T00:00:00", "amount": 25.5},
        ])

    def test_xlsx_conversion_preserves_common_currency_percent_grouping_and_sections(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["currency", "percentage", "negative", "zero", "general", "unsupported"])
        sheet.append([1234.5, 0.125, -1234.5, 0, 42.5, 0.125])
        sheet["A2"].number_format = "$#,##0.00"
        sheet["B2"].number_format = "0.0%"
        sheet["C2"].number_format = "#,##0.00;(#,##0.00)"
        sheet["D2"].number_format = '#,##0.00;(#,##0.00);"-"'
        sheet["F2"].number_format = "[>=1]0.0;[Red](0.0)"
        source = io.BytesIO()
        workbook.save(source)
        workbook.close()

        converted, _mime = FileConverterEngine.convert_data_file(source.getvalue(), "xlsx", "json")

        self.assertEqual(json.loads(converted), [{
            "currency": "$1,234.50",
            "percentage": "12.5%",
            "negative": "(1,234.50)",
            "zero": "-",
            "general": 42.5,
            "unsupported": 0.125,
        }])

    def test_xlsx_number_format_rounding_optional_digits_and_explicit_negative_sign(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["rounded", "optional", "negative"])
        sheet.append([1.125, 1.2, -12.5])
        sheet["A2"].number_format = "0.00"
        sheet["B2"].number_format = "0.##"
        sheet["C2"].number_format = "0.00;-0.00"
        source = io.BytesIO()
        workbook.save(source)
        workbook.close()

        converted, _mime = FileConverterEngine.convert_data_file(source.getvalue(), "xlsx", "json")

        self.assertEqual(json.loads(converted), [{
            "rounded": "1.13",
            "optional": "1.2",
            "negative": "-12.50",
        }])

    def test_xlsx_single_section_number_format_keeps_implicit_negative_sign(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["amount"])
        sheet.append([-12.5])
        sheet["A2"].number_format = "0.00"
        source = io.BytesIO()
        workbook.save(source)
        workbook.close()

        converted, _mime = FileConverterEngine.convert_data_file(source.getvalue(), "xlsx", "json")

        self.assertEqual(json.loads(converted), [{"amount": "-12.50"}])

    def test_xlsx_conversion_preserves_indian_currency_grouping_and_quoted_units(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["inr", "negative_inr", "weight", "escaped_percent", "condition"])
        sheet.append([1234567.5, -1234567.5, 2.5, 0.125, 1.25])
        sheet["A2"].number_format = "[$₹-en-IN]#,##,##0.00"
        sheet["B2"].number_format = "[Red]-[$₹-en-IN]#,##,##0.00"
        sheet["C2"].number_format = '0.00" kg"'
        sheet["D2"].number_format = r"0.0\%"
        sheet["E2"].number_format = "[>=1]0.00;[Red](0.00)"
        source = io.BytesIO()
        workbook.save(source)
        workbook.close()

        converted, _mime = FileConverterEngine.convert_data_file(source.getvalue(), "xlsx", "json")

        self.assertEqual(json.loads(converted), [{
            "inr": "₹12,34,567.50",
            "negative_inr": "-₹12,34,567.50",
            "weight": "2.50 kg",
            "escaped_percent": "0.1%",
            "condition": 1.25,
        }])

    def test_xlsx_default_sheet_and_display_values_use_the_same_first_worksheet(self):
        workbook = Workbook()
        first = workbook.active
        first.title = "Transactions"
        first.append(["account", "amount"])
        first.append([1234, 25.5])
        first["A2"].number_format = "000000"
        active = workbook.create_sheet("Summary")
        active.append(["metric", "count"])
        active.append(["all", 7])
        active["B2"].number_format = "000"
        workbook.active = 1
        source = io.BytesIO()
        workbook.save(source)
        workbook.close()

        converted, _mime = FileConverterEngine.convert_data_file(source.getvalue(), "xlsx", "json")

        self.assertEqual(json.loads(converted), [{"account": "001234", "amount": 25.5}])

    def test_xlsx_conversion_selects_requested_sheet_and_preserves_its_display_values(self):
        workbook = Workbook()
        first = workbook.active
        first.title = "Transactions"
        first.append(["account", "amount"])
        first.append([1234, 25.5])
        first["A2"].number_format = "000000"
        second = workbook.create_sheet("Summary")
        second.append(["code", "posted_at"])
        second.append([45, datetime(2026, 10, 8)])
        second["A2"].number_format = "000000"
        second["B2"].number_format = "yyyy-mm-dd"
        source = io.BytesIO()
        workbook.save(source)
        workbook.close()

        converted, _mime = FileConverterEngine.convert_data_file(
            source.getvalue(), "xlsx", "json", sheet_name="Summary"
        )

        self.assertEqual(json.loads(converted), [{"code": "000045", "posted_at": "2026-10-08T00:00:00"}])

    def test_xlsx_sheet_discovery_is_ordered_bounded_and_rejects_corrupt_workbooks(self):
        workbook = Workbook()
        workbook.active.title = "Transactions"
        workbook.create_sheet("<img onerror=1>")
        source = io.BytesIO()
        workbook.save(source)
        workbook.close()

        self.assertEqual(
            FileConverterEngine.list_xlsx_sheet_names(source.getvalue()),
            ["Transactions", "<img onerror=1>"],
        )
        with patch.object(FileConverterEngine, "MAX_XLSX_SHEETS", 1):
            with self.assertRaises(ConversionInputError):
                FileConverterEngine.list_xlsx_sheet_names(source.getvalue())
        with self.assertRaises(ConversionInputError):
            FileConverterEngine.list_xlsx_sheet_names(b"not an Excel workbook")

    def test_xlsx_conversion_rejects_unknown_or_non_string_sheet_names(self):
        source = self._xlsx_bytes([["value"], [1]])
        for sheet_name in ("Missing", 0, True):
            with self.subTest(sheet_name=sheet_name), self.assertRaises(ConversionInputError):
                FileConverterEngine.convert_data_file(source, "xlsx", "json", sheet_name=sheet_name)

    def test_xlsx_conversion_rejects_unbounded_or_duplicate_zip_members(self):
        source = self._xlsx_bytes([["value"], ["small"]])
        with patch.object(FileConverterEngine, "MAX_XLSX_UNCOMPRESSED_BYTES", 1):
            with self.assertRaises(ConversionInputError):
                FileConverterEngine.convert_data_file(source, "xlsx", "json")

        duplicate_member = io.BytesIO()
        with zipfile.ZipFile(duplicate_member, "w") as archive:
            archive.writestr("xl/worksheets/sheet1.xml", b"<worksheet/>")
            archive.writestr("xl/worksheets/sheet1.xml", b"<worksheet/>")
        with self.assertRaises(ConversionInputError):
            FileConverterEngine.convert_data_file(duplicate_member.getvalue(), "xlsx", "json")

    def test_xlsx_conversion_rejects_false_huge_worksheet_dimensions(self):
        source = self._xlsx_bytes([["value"], ["small"]])
        malformed_dimensions = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(source), "r") as original, zipfile.ZipFile(
            malformed_dimensions, "w", compression=zipfile.ZIP_DEFLATED
        ) as rewritten:
            for entry in original.infolist():
                content = original.read(entry.filename)
                if entry.filename == "xl/worksheets/sheet1.xml":
                    content = content.replace(b'ref="A1:A2"', b'ref="A1:XFD1048576"')
                rewritten.writestr(entry.filename, content)
        with self.assertRaises(ConversionInputError):
            FileConverterEngine.convert_data_file(malformed_dimensions.getvalue(), "xlsx", "json")

    def test_xlsx_conversion_rejects_cells_outside_bounds_even_with_small_dimension(self):
        source = self._xlsx_bytes([["value"], ["small"]])
        misplaced_cell = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(source), "r") as original, zipfile.ZipFile(
            misplaced_cell, "w", compression=zipfile.ZIP_DEFLATED
        ) as rewritten:
            for entry in original.infolist():
                content = original.read(entry.filename)
                if entry.filename == "xl/worksheets/sheet1.xml":
                    content = content.replace(b'r="A2"', b'r="A1048576"')
                rewritten.writestr(entry.filename, content)
        with self.assertRaises(ConversionInputError):
            FileConverterEngine.convert_data_file(misplaced_cell.getvalue(), "xlsx", "json")

    def test_csv_and_tsv_preserve_leading_zero_identifiers_while_typing_numeric_columns(self):
        fixtures = (
            (b"account,amount,date,note\n001234,25.50,2026-10-07,\n000045,0,01/02/2026,\n000077,,,\n", "csv"),
            (b"account\tamount\tdate\tnote\n001234\t25.50\t2026-10-07\t\n000045\t0\t01/02/2026\t\n000077\t\t\t\n", "tsv"),
        )
        expected = [
            {"account": "001234", "amount": 25.5, "date": "2026-10-07", "note": ""},
            {"account": "000045", "amount": 0, "date": "01/02/2026", "note": ""},
            {"account": "000077", "amount": None, "date": "", "note": ""},
        ]
        for source, extension in fixtures:
            with self.subTest(extension=extension):
                converted, mime = FileConverterEngine.convert_data_file(source, extension, "json")
                self.assertEqual(mime, "application/json")
                self.assertEqual(json.loads(converted), expected)

                round_trip, _ = FileConverterEngine.convert_data_file(source, extension, extension)
                self.assertIn(b"001234", round_trip)
                self.assertIn(b"000045", round_trip)

                workbook_bytes, _ = FileConverterEngine.convert_data_file(source, extension, "xlsx")
                workbook = load_workbook(io.BytesIO(workbook_bytes), data_only=False)
                try:
                    sheet = workbook.active
                    self.assertEqual(sheet["A2"].value, "001234")
                    self.assertEqual(sheet["A3"].value, "000045")
                    self.assertEqual(sheet["B2"].value, 25.5)
                    self.assertEqual(sheet["B3"].value, 0)
                    self.assertEqual(sheet["C2"].value, "2026-10-07")
                    self.assertEqual(sheet["C3"].value, "01/02/2026")
                    self.assertIsNone(sheet["B4"].value)
                finally:
                    workbook.close()

    def test_delimited_conversion_keeps_high_precision_and_non_finite_numeric_text_literal(self):
        source = (
            b"reference,amount,max_safe,precise,overflow\n"
            b"0000001,0.001,999999999999999,1234567890123456789,1e309\n"
            b"0000002,2.5,999999999999998,1234567890123456790,2e309\n"
        )
        converted, _ = FileConverterEngine.convert_data_file(source, "csv", "json")
        self.assertEqual(json.loads(converted), [
            {"reference": "0000001", "amount": 0.001, "max_safe": 999999999999999, "precise": "1234567890123456789", "overflow": "1e309"},
            {"reference": "0000002", "amount": 2.5, "max_safe": 999999999999998, "precise": "1234567890123456790", "overflow": "2e309"},
        ])

    def test_delimited_conversion_rejects_malformed_rows_and_resource_overruns(self):
        malformed = b'a,b\n1,"unterminated\n'
        with self.assertRaises(ConversionInputError):
            FileConverterEngine.convert_data_file(malformed, "csv", "json")

        fixture = b"a,b\n1,2\n3,4\n"
        for limit_name, limit, data in (
            ("MAX_TABULAR_ROWS", 1, fixture),
            ("MAX_TABULAR_COLUMNS", 1, fixture),
            ("MAX_TABULAR_CELLS", 5, fixture),
        ):
            with self.subTest(limit=limit_name), patch.object(FileConverterEngine, limit_name, limit):
                with self.assertRaises(ConversionInputError):
                    FileConverterEngine.convert_data_file(data, "csv", "json")

    def test_csv_tsv_and_xlsx_outputs_keep_formula_shaped_text_literal(self):
        source = b"label,value\n=1+1,-2\n  @command,3\n"
        for target, delimiter in (("csv", ","), ("tsv", "\t")):
            with self.subTest(target=target):
                output, _ = FileConverterEngine.convert_data_file(source, "csv", target)
                rows = list(csv.reader(io.StringIO(output.decode("utf-8")), delimiter=delimiter))
                self.assertEqual(rows[1], ["'=1+1", "-2"])
                self.assertEqual(rows[2], ["'  @command", "3"])

        xlsx_output, _ = FileConverterEngine.convert_data_file(source, "csv", "xlsx")
        workbook = load_workbook(io.BytesIO(xlsx_output), data_only=False)
        try:
            sheet = workbook.active
            self.assertEqual(sheet["A2"].value, "'=1+1")
            self.assertEqual(sheet["A2"].data_type, "s")
            self.assertEqual(sheet["A3"].value, "'  @command")
            self.assertEqual(sheet["B2"].value, -2)
            self.assertNotEqual(sheet["B2"].data_type, "f")
        finally:
            workbook.close()

    def test_json_nested_values_export_as_compact_json_in_flat_formats(self):
        source = json.dumps([{
            "account": "001234",
            "items": [1, {"sku": "A-1"}],
            "metadata": {"active": True, "labels": ["one", "two"]},
            "note": None,
        }]).encode("utf-8")
        expected_items = '[1,{"sku":"A-1"}]'
        expected_metadata = '{"active":true,"labels":["one","two"]}'

        csv_output, _ = FileConverterEngine.convert_data_file(source, "json", "csv")
        self.assertEqual(
            list(csv.reader(io.StringIO(csv_output.decode("utf-8")))),
            [["account", "items", "metadata", "note"], ["001234", expected_items, expected_metadata, ""]],
        )

        xlsx_output, _ = FileConverterEngine.convert_data_file(source, "json", "xlsx")
        workbook = load_workbook(io.BytesIO(xlsx_output), data_only=True)
        try:
            sheet = workbook.active
            self.assertEqual(sheet["A2"].value, "001234")
            self.assertEqual(sheet["B2"].value, expected_items)
            self.assertEqual(sheet["C2"].value, expected_metadata)
            self.assertIsNone(sheet["D2"].value)
        finally:
            workbook.close()

    def test_delimited_null_token_round_trip_preserves_null_empty_and_escaped_literals(self):
        source = json.dumps([{
            "null_value": None,
            "empty_value": "",
            "literal_token": "\\N",
            "literal_escape": "\\starts-with-slash",
        }]).encode("utf-8")

        csv_output, _ = FileConverterEngine.convert_data_file(
            source, "json", "csv", null_token="\\N"
        )
        self.assertEqual(
            list(csv.reader(io.StringIO(csv_output.decode("utf-8")))),
            [
                ["null_value", "empty_value", "literal_token", "literal_escape"],
                ["\\N", "", "\\\\N", "\\\\starts-with-slash"],
            ],
        )

        json_output, _ = FileConverterEngine.convert_data_file(
            csv_output, "csv", "json", null_token="\\N"
        )
        self.assertEqual(json.loads(json_output), [{
            "null_value": None,
            "empty_value": "",
            "literal_token": "\\N",
            "literal_escape": "\\starts-with-slash",
        }])

        tsv_output, _ = FileConverterEngine.convert_data_file(
            source, "json", "tsv", null_token="\\N"
        )
        tsv_round_trip, _ = FileConverterEngine.convert_data_file(
            tsv_output, "tsv", "json", null_token="\\N"
        )
        self.assertEqual(json.loads(tsv_round_trip), json.loads(source))

    def test_delimited_null_token_is_optional_and_rejects_unsafe_values(self):
        source = b'[{"null_value":null,"empty_value":""}]'
        default_output, _ = FileConverterEngine.convert_data_file(source, "json", "csv")
        self.assertEqual(
            list(csv.reader(io.StringIO(default_output.decode("utf-8")))),
            [["null_value", "empty_value"], ["", ""]],
        )

        for null_token in (
            "", "x" * 65, "line\nbreak", "nul\x00byte", "=SUM(A1:A2)",
            "  +cmd", "\u200b@payload", 1, True,
        ):
            with self.subTest(null_token=null_token), self.assertRaises(ConversionInputError):
                FileConverterEngine.convert_data_file(
                    source, "json", "csv", null_token=null_token
                )

    def test_json_target_preserves_nested_structure_instead_of_flattening_it(self):
        source = b'[{"id":"001","attributes":{"enabled":true,"codes":["x","y"]}}]'

        converted, mime = FileConverterEngine.convert_data_file(source, "json", "json")

        self.assertEqual(mime, "application/json")
        self.assertEqual(json.loads(converted), [{
            "id": "001",
            "attributes": {"enabled": True, "codes": ["x", "y"]},
        }])

    def test_json_to_csv_and_back(self):
        json_data = b'[{"id": 1, "name": "Alpha", "price": 19.99}, {"id": 2, "name": "Beta", "price": 49.99}]'
        
        # JSON to CSV
        csv_bytes, mime = FileConverterEngine.convert_data_file(json_data, 'json', 'csv')
        self.assertEqual(mime, 'text/csv')
        csv_str = csv_bytes.decode('utf-8')
        self.assertIn('Alpha', csv_str)
        self.assertIn('49.99', csv_str)

        # CSV to JSON
        json_bytes, mime_json = FileConverterEngine.convert_data_file(csv_bytes, 'csv', 'json')
        self.assertEqual(mime_json, 'application/json')
        self.assertIn(b'Beta', json_bytes)

    def test_yaml_to_json_and_back(self):
        yaml_data = b"""
app: OfficeKit
version: 1.0
features:
  - bank_statement_ocr
  - privacy_first
"""
        json_bytes, mime = FileConverterEngine.convert_data_file(yaml_data, 'yaml', 'json')
        self.assertEqual(mime, 'application/json')
        self.assertIn(b'OfficeKit', json_bytes)

    def test_sql_insert_generator(self):
        csv_data = b"product,price,stock\nLaptop,999.00,15\nMouse,25.50,120\n"
        sql_bytes, mime = FileConverterEngine.convert_data_file(csv_data, 'csv', 'sql', table_name="inventory")
        self.assertEqual(mime, 'application/sql')
        sql_str = sql_bytes.decode('utf-8')
        self.assertIn('INSERT INTO "inventory"', sql_str)
        self.assertIn("Laptop", sql_str)
        self.assertIn("999.0", sql_str)

    def test_invalid_source_target_and_malformed_data_raise_safe_input_error(self):
        cases = (
            (b"{}", "unknown", "json"),
            (b'{"secret":', "json", "csv"),
            (b"name\nAda\n", "csv", "private_target"),
        )
        for input_bytes, source_ext, target_ext in cases:
            with self.subTest(source_ext=source_ext, target_ext=target_ext):
                with self.assertRaises(ConversionInputError) as caught:
                    FileConverterEngine.convert_data_file(input_bytes, source_ext, target_ext)
                self.assertEqual(
                    str(caught.exception),
                    "The file or requested format cannot be converted. Check the input and try again.",
                )

    def test_json_conversion_rejects_duplicate_keys_and_non_finite_numbers(self):
        for input_bytes in (
            b'[{"account":"first","account":"second"}]',
            b'[{"amount":NaN}]',
            b'[{"amount":Infinity}]',
            b'[{"amount":-Infinity}]',
            b'[{"amount":1e309}]',
            b'["\\ud800"]',
            b"[" * 1100 + b"0" + b"]" * 1100,
        ):
            with self.subTest(input=input_bytes), self.assertRaises(ConversionInputError):
                FileConverterEngine.convert_data_file(input_bytes, "json", "csv")

    def test_json_conversion_rejects_node_overrun_before_dataframe_creation(self):
        with patch.object(FileConverterEngine, "MAX_JSON_NODES", 3):
            with self.assertRaises(ConversionInputError):
                FileConverterEngine.convert_data_file(b"[1,2,3]", "json", "csv")

    def test_json_conversion_accepts_exact_depth_and_node_limits(self):
        with patch.object(FileConverterEngine, "MAX_JSON_DEPTH", 2), patch.object(
            FileConverterEngine, "MAX_JSON_NODES", 4
        ):
            output, _mime = FileConverterEngine.convert_data_file(b"[[0]]", "json", "csv")
        self.assertEqual(output.replace(b"\r\n", b"\n"), b"0\n0\n")

    def test_yaml_file_conversion_rejects_ambiguous_or_unbounded_documents(self):
        inputs = (
            b"name: first\nname: second\n",
            b"defaults: &defaults\n  amount: 1\nrow:\n  <<: *defaults\n",
            b"defaults: &defaults\n  amount: 1\nrow: *defaults\n",
            b"? [non, string, key]\n: value\n",
            b"amount: .nan\n",
            b"amount: .inf\n",
        )
        for source in inputs:
            with self.subTest(source=source), self.assertRaises(ConversionInputError):
                FileConverterEngine.convert_data_file(source, "yaml", "json")

    def test_yaml_file_json_export_preserves_exact_decimals_and_yaml12_text(self):
        source = b"amount: 0.123456789012345678901234567890\nflag: yes\ncode: 0012\nnested:\n  ratio: 0.987654321098765432109876543210\n  enabled: true\n"

        output, mime = FileConverterEngine.convert_data_file(source, "yaml", "json")

        self.assertEqual(mime, "application/json")
        self.assertIn(b"0.123456789012345678901234567890", output)
        self.assertEqual(json.loads(output), {
            "amount": 0.12345678901234568,
            "flag": "yes",
            "code": "0012",
            "nested": {"ratio": 0.9876543210987654, "enabled": True},
        })

        csv_output, _csv_mime = FileConverterEngine.convert_data_file(source, "yaml", "csv")
        self.assertIn(b"0.123456789012345678901234567890", csv_output)
        converted_nested = list(csv.reader(io.StringIO(csv_output.decode("utf-8"))))[1][3]
        self.assertEqual(
            json.loads(converted_nested, parse_float=Decimal),
            {"ratio": Decimal("0.987654321098765432109876543210"), "enabled": True},
        )

    def test_yaml_file_converter_enforces_shared_node_bound(self):
        with patch("officekit.engines.engine_devtools.DevToolsEngine.MAX_YAML_NODES", 2):
            with self.assertRaises(ConversionInputError):
                FileConverterEngine.convert_data_file(b"- first\n- second\n", "yaml", "json")

if __name__ == "__main__":
    unittest.main()
