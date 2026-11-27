"""Standard-library tests for statement spreadsheet cell preparation."""

import csv
import io
import unittest
import xlrd
from fastapi.testclient import TestClient

from officekit.engines.engine_statement_exports import export_to_csv, export_to_legacy_excel, prepare_statement_export_rows
from app import app


class StatementExportTests(unittest.TestCase):
    def test_csv_export_writes_formula_shaped_imported_text_as_literal_cells(self):
        transactions = [
            {"date": "2024-01-01", "description": "=1+1", "debit": 12.5, "status": "ok"},
            {"date": "\t@SUM(A1:A2)", "description": "\u00a0\ufeff+1", "credit": 3, "status": "reconciliation_warning"},
            {"date": " \u200b-1+1", "description": "Client payment", "balance": -2.5},
            {"date": "東京", "description": "-not a formula", "extra": "ignored"},
            {"date": "2024-02-01", "description": "Zero amount", "debit": 0, "credit": 0, "balance": 0},
        ]

        rows = list(csv.reader(io.StringIO(export_to_csv(transactions))))

        self.assertEqual(rows[0], ["Date", "Description", "Debit (Withdrawal)", "Credit (Deposit)", "Balance", "Checksum Status"])
        self.assertEqual(rows[1], ["2024-01-01", "'=1+1", "12.5", "", "", "ok"])
        self.assertEqual(rows[2], ["'\t@SUM(A1:A2)", "'\u00a0\ufeff+1", "", "3", "", "reconciliation_warning"])
        self.assertEqual(rows[3], ["' \u200b-1+1", "Client payment", "", "", "-2.5", "ok"])
        self.assertEqual(rows[4], ["東京", "'-not a formula", "", "", "", "ok"])
        self.assertEqual(rows[5], ["2024-02-01", "Zero amount", "0", "0", "0", "ok"])

    def test_csv_export_handles_empty_input_with_headers_and_newline(self):
        output = export_to_csv([])

        self.assertEqual(
            output,
            "Date,Description,Debit (Withdrawal),Credit (Deposit),Balance,Checksum Status\r\n",
        )

    def test_excel_row_preparation_uses_the_same_sanitized_text_as_csv(self):
        rows = prepare_statement_export_rows([
            {"date": "=TODAY()", "description": " +SUM(1,2)", "debit": 0, "credit": None, "balance": 0, "status": "ok"}
        ])

        self.assertEqual(rows, [{
            "Date": "'=TODAY()",
            "Description": "' +SUM(1,2)",
            "Debit": 0,
            "Credit": None,
            "Balance": 0,
            "Checksum Status": "ok",
        }])

    def test_legacy_xls_export_preserves_identifiers_and_neutralizes_formula_text(self):
        content = export_to_legacy_excel([
            {"date": "2026-09-21", "description": "=1+1", "debit": 1250.5, "balance": 4000, "status": "ok"},
        ])

        workbook = xlrd.open_workbook(file_contents=content, on_demand=True)
        try:
            sheet = workbook.sheet_by_index(0)
            self.assertEqual(sheet.cell_value(0, 0), "Date")
            self.assertEqual(sheet.cell_value(1, 1), "'=1+1")
            self.assertEqual(sheet.cell_value(1, 2), 1250.5)
            self.assertEqual(sheet.cell_value(1, 4), 4000)
        finally:
            workbook.release_resources()

    def test_legacy_xls_export_api_returns_a_readable_workbook(self):
        response = TestClient(app).post("/api/export/xls", json={
            "transactions": [{"date": "2026-09-21", "description": "Rent", "debit": 200.0, "balance": 800.0}],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/vnd.ms-excel")
        self.assertIn("statement_export.xls", response.headers["content-disposition"])
        workbook = xlrd.open_workbook(file_contents=response.content, on_demand=True)
        try:
            sheet = workbook.sheet_by_index(0)
            self.assertEqual(sheet.cell_value(1, 1), "Rent")
            self.assertEqual(sheet.cell_value(1, 2), 200.0)
            self.assertEqual(sheet.cell_value(1, 4), 800.0)
        finally:
            workbook.release_resources()


if __name__ == "__main__":
    unittest.main()
