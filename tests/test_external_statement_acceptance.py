"""Opt-in acceptance checks for a privately supplied bank statement PDF.

Set OFFICEKIT_STATEMENT_REVIEW_PDF to run these checks. The source document is
read in place and is never copied into the repository or modified.
"""

import csv
import io
import os
import re
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook
import xlrd

from app import app


SOURCE_PDF = os.environ.get("OFFICEKIT_STATEMENT_REVIEW_PDF")


@unittest.skipUnless(SOURCE_PDF, "Set OFFICEKIT_STATEMENT_REVIEW_PDF for private-source acceptance")
class ExternalStatementAcceptanceTests(unittest.TestCase):
    def test_supplied_statement_exports_four_separate_reconciled_transactions_to_csv_and_xlsx(self):
        source_path = Path(SOURCE_PDF)
        source = source_path.read_bytes()
        with TestClient(app) as client:
            response = client.post(
                "/api/extract/statement",
                files={"file": (source_path.name, source, "application/pdf")},
            )
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()

            self.assertEqual(
                [row["date"] for row in result["transactions"]],
                ["21/09/26", "25/09/26", "25/09/26", "25/09/26"],
            )
            self.assertEqual([row["debit"] is None for row in result["transactions"]], [True, False, False, False])
            self.assertTrue(all(row["balance"] is not None for row in result["transactions"]))
            self.assertEqual(result["reconciliation"]["status"], "verified")
            self.assertEqual(result["reconciliation"]["checked_rows"], 4)

            csv_response = client.post("/api/export/csv", json=result)
            self.assertEqual(csv_response.status_code, 200)
            csv_rows = list(csv.DictReader(io.StringIO(csv_response.text)))
            self.assertEqual(len(csv_rows), 4)
            self.assertEqual([row["Date"] for row in csv_rows], ["21/09/26", "25/09/26", "25/09/26", "25/09/26"])
            self.assertEqual([row["Checksum Status"] for row in csv_rows], ["ok"] * 4)
            self.assertEqual(
                [row["Debit (Withdrawal)"] != "" for row in csv_rows],
                [False, True, True, True],
            )

            xlsx_response = client.post("/api/export/excel", json=result)
            self.assertEqual(xlsx_response.status_code, 200)
            workbook = load_workbook(io.BytesIO(xlsx_response.content), read_only=True, data_only=True)
            try:
                sheet = workbook["Bank Statement"]
                rows = list(sheet.iter_rows(values_only=True))
            finally:
                workbook.close()
            self.assertEqual(
                rows[0],
                ("Date", "Description", "Debit", "Credit", "Balance", "Checksum Status"),
            )
            self.assertEqual(len(rows), 5)
            self.assertEqual([row[0] for row in rows[1:]], ["21/09/26", "25/09/26", "25/09/26", "25/09/26"])
            self.assertEqual([row[2] is not None for row in rows[1:]], [False, True, True, True])
            self.assertTrue(all(row[4] is not None for row in rows[1:]))
            self.assertEqual([row[5] for row in rows[1:]], ["ok"] * 4)

            xls_response = client.post("/api/export/xls", json=result)
            self.assertEqual(xls_response.status_code, 200)
            self.assertEqual(xls_response.headers["content-type"], "application/vnd.ms-excel")
            legacy_book = xlrd.open_workbook(file_contents=xls_response.content, on_demand=True)
            try:
                legacy_sheet = legacy_book.sheet_by_index(0)
                self.assertEqual(legacy_sheet.nrows, 5)
                self.assertEqual(legacy_sheet.cell_value(1, 0), "21/09/26")
                self.assertNotEqual(legacy_sheet.cell_value(2, 2), "")
                self.assertNotEqual(legacy_sheet.cell_value(4, 4), "")
                self.assertEqual([legacy_sheet.cell_value(row, 5) for row in range(1, 5)], ["ok"] * 4)
            finally:
                legacy_book.release_resources()

        self.assertEqual(source_path.read_bytes(), source)

    def test_supplied_statement_pdf_table_preview_does_not_merge_multiple_dates_into_one_row(self):
        source_path = Path(SOURCE_PDF)
        source = source_path.read_bytes()
        with TestClient(app) as client:
            response = client.post(
                "/api/pdf/tables",
                files={"file": (source_path.name, source, "application/pdf")},
            )
            self.assertEqual(response.status_code, 200, response.text)
            tables = response.json()["tables"]
            date_pattern = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b")
            observed_dates = []
            export_selection = None
            export_preview_rows = None
            expected_dates = ["21/09/26", "25/09/26", "25/09/26", "25/09/26"]
            expected_headers = [
                "Date", "Narration", "Chq./Ref.No.", "ValueDt",
                "WithdrawalAmt.", "DepositAmt.", "ClosingBalance",
            ]
            for table in tables:
                rows = table["preview_rows"]
                if not rows:
                    continue
                headers = [re.sub(r"[^a-z]", "", cell.casefold()) for cell in rows[0]]
                date_index = next(
                    (index for index, header in enumerate(headers)
                     if header in {"date", "transactiondate", "txndate", "transdate", "postingdate"}),
                    None,
                )
                if date_index is None:
                    continue
                table_dates = []
                for row in rows[1:]:
                    if date_index >= len(row):
                        continue
                    date_tokens = date_pattern.findall(row[date_index])
                    self.assertLessEqual(
                        len(date_tokens),
                        1,
                        f"PDF table row merged multiple transaction dates: {row!r}",
                    )
                    table_dates.extend(date_tokens)
                if table_dates:
                    observed_dates.extend(table_dates)
                    export_selection = (table["page_number"], table["table_number"])
                    export_preview_rows = rows
                    self.assertEqual(rows[0], expected_headers)
                    self.assertEqual(
                        len(rows),
                        5,
                        "The preview must keep one header and four transaction rows.",
                    )
                    self.assertTrue(all(len(row) == len(expected_headers) for row in rows))
                    data_rows = rows[1:]
                    self.assertTrue(all(row[1].strip() and row[2].strip() for row in data_rows))
                    self.assertEqual([row[3] for row in data_rows], expected_dates)
                    self.assertEqual([bool(row[4]) for row in data_rows], [False, True, True, True])
                    self.assertEqual([bool(row[5]) for row in data_rows], [True, False, False, False])
                    self.assertTrue(all(row[6].strip() for row in data_rows))
            self.assertEqual(
                observed_dates,
                expected_dates,
                "The table preview must preserve all four transaction dates as separate rows.",
            )
            self.assertIsNotNone(export_selection, "The source PDF should expose a date-bearing table.")

            export_response = client.post(
                "/api/pdf/tables/export",
                files={"file": (source_path.name, source, "application/pdf")},
                data={
                    "page_number": str(export_selection[0]),
                    "table_number": str(export_selection[1]),
                    "format": "csv",
                },
            )
            self.assertEqual(export_response.status_code, 200, export_response.text)
            exported_rows = list(csv.reader(io.StringIO(export_response.content.decode("utf-8-sig"))))
            exported_dates = [
                row[date_index].strip()
                for row in exported_rows[1:]
                if date_index < len(row) and date_pattern.fullmatch(row[date_index].strip())
            ]
            self.assertEqual(
                exported_dates,
                expected_dates,
                "CSV export must preserve all four previewed transaction rows.",
            )
            self.assertEqual(exported_rows, export_preview_rows)

        self.assertEqual(source_path.read_bytes(), source)


if __name__ == "__main__":
    unittest.main()
