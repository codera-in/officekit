"""Delimited statement import must preserve CSV and TSV column boundaries."""

import ast
import unittest
from pathlib import Path
from officekit.engines.engine_statement_input import StatementInputError, parse_statement_delimited

ROOT = Path(__file__).resolve().parents[1]


class StatementInputTests(unittest.TestCase):
    def test_statement_route_delegates_delimited_files_to_the_shared_parser(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        route = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "extract_statement"
        )
        calls = {
            node.func.id
            for node in ast.walk(route)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("parse_statement_delimited", calls)
        handled_input_errors = [
            node for node in ast.walk(route)
            if isinstance(node, ast.ExceptHandler)
            and isinstance(node.type, ast.Name)
            and node.type.id == "StatementInputError"
        ]
        self.assertEqual(len(handled_input_errors), 1)
        self.assertIn("status_code=error.status_code", ast.unparse(handled_input_errors[0]))

    def test_tsv_uses_tabs_and_preserves_empty_columns(self):
        rows = parse_statement_delimited(
            b"Date\tDescription\tDebit\tCredit\n2026-08-01\tCoffee\t4.50\t\n",
            "tsv",
        )
        self.assertEqual(
            rows,
            [["Date", "Description", "Debit", "Credit"], ["2026-08-01", "Coffee", "4.50", ""]],
        )

    def test_csv_keeps_quoted_commas_and_quotes(self):
        rows = parse_statement_delimited(
            b'Date,Description,Amount\r\n2026-08-01,"Cafe, ""North""",4.50\r\n',
            ".CSV",
        )
        self.assertEqual(rows[1], ["2026-08-01", 'Cafe, "North"', "4.50"])

    def test_utf8_bom_and_non_ascii_text_are_preserved(self):
        rows = parse_statement_delimited(
            "\ufeffDate\tDescription\tAmount\n2026-08-01\tCafé\t4,50".encode("utf-8"),
            ".tsv",
        )
        self.assertEqual(rows[1], ["2026-08-01", "Café", "4,50"])

    def test_invalid_encoding_has_a_safe_actionable_error(self):
        with self.assertRaises(StatementInputError) as raised:
            parse_statement_delimited(b"Date,Description\n\xff", "csv")
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(str(raised.exception), "Save the statement as UTF-8 CSV or TSV, then try again.")

    def test_invalid_delimiter_input_is_not_silently_accepted(self):
        with self.assertRaises(StatementInputError) as raised:
            parse_statement_delimited(b'Date,Description\n2026-08-01,"unclosed', "csv")
        self.assertEqual(str(raised.exception), "The CSV or TSV file has invalid quoting.")

    def test_rejects_wrong_content_type_and_extension(self):
        for content, extension in (("text", "csv"), (b"data", "xlsx")):
            with self.subTest(extension=extension), self.assertRaises(StatementInputError):
                parse_statement_delimited(content, extension)


if __name__ == "__main__":
    unittest.main()
