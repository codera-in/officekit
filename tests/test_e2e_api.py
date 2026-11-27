"""
End-to-End (E2E) Integration Tests for OfficeKit FastAPI Endpoints
Tests full HTTP request/response lifecycles:
- Bank statement extraction and CSV/Excel/QBO exports
- PDF password removal and encryption
- Audio transcript meeting notes formatting
- Any-to-Any image and structured data conversions
- Financial Calculators API
- AppSumo Offline License Activation API
"""

import io
import csv
import json
import unittest
from unittest.mock import patch
from datetime import datetime
from fastapi.testclient import TestClient
import pikepdf
from PIL import Image
from openpyxl import Workbook, load_workbook
import xlwt

from app import app
from officekit.engines.engine_file_converter import FileConverterEngine

class TestOfficeKitE2E(unittest.TestCase):

    def setUp(self):
        self.client = TestClient(app)

    # 1. Module 1: Statement Extraction & Checksum E2E
    def test_e2e_statement_extraction(self):
        csv_content = (
            "Date,Description,Withdrawals,Deposits,Balance\n"
            "2024-01-01,Opening Balance,,,1000.00\n"
            "2024-01-05,Client Invoice Payment,,500.00,1500.00\n"
            "2024-01-10,Software SaaS Fee,50.00,,1450.00\n"
        )
        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement.csv", csv_content.encode("utf-8"), "text/csv")}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["reconciliation"]["valid"])
        self.assertEqual(len(data["transactions"]), 3)

        # Test CSV export endpoint
        csv_resp = self.client.post("/api/export/csv", json=data)
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("Client Invoice Payment", csv_resp.text)

        # Test Excel export endpoint
        xlsx_resp = self.client.post("/api/export/excel", json=data)
        self.assertEqual(xlsx_resp.status_code, 200)
        self.assertGreater(len(xlsx_resp.content), 100)

    def test_statement_pdf_with_separate_value_date_and_wrapped_narration_exports_correct_transactions(self):
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.pdfgen import canvas

        output = io.BytesIO()
        page = canvas.Canvas(output, pagesize=landscape(letter))
        page.setFont("Helvetica", 8)
        columns = ((30, "Date"), (115, "Description"), (390, "Reference"), (485, "Value Date"),
                   (565, "Debit"), (635, "Credit"), (715, "Balance"))
        for x, label in columns:
            page.drawString(x, 742, label)

        # A long credit narration wraps inside its column. Its value date and
        # reference must not be mistaken for extra transaction dates/text.
        page.drawString(30, 715, "21/09/26")
        page.drawString(115, 715, "FOREIGN INWARD REMITTANCE TXN000000RO")
        page.drawString(115, 703, "ORBITX NETWORK GROUP CUSTOMER CREDIT")
        page.drawString(390, 715, "50100000000001")
        page.drawString(485, 715, "25/09/26")
        page.drawRightString(700, 715, "1,718,697.40")
        page.drawRightString(780, 715, "1,737,613.76")

        rows = (
            ("25/09/26", "NEFT TRANSFER ONE", "50100244908374", "25/09/26", "200,000.00", "", "1,537,613.76"),
            ("25/09/26", "NEFT TRANSFER TWO", "50100244908375", "25/09/26", "200,000.00", "", "1,337,613.76"),
            ("25/09/26", "NEFT TRANSFER THREE", "50100244908376", "25/09/26", "150,000.00", "", "1,187,613.76"),
        )
        for (date, description, reference, value_date, debit, credit, balance), y in zip(rows, (670, 640, 610), strict=True):
            page.drawString(30, y, date)
            page.drawString(115, y, description)
            page.drawString(390, y, reference)
            page.drawString(485, y, value_date)
            if debit:
                page.drawRightString(620, y, debit)
            if credit:
                page.drawRightString(700, y, credit)
            page.drawRightString(780, y, balance)
        page.drawString(30, 555, "STATEMENT SUMMARY: -")
        page.drawString(115, 535, "OpeningBalance DrCount CrCount Debits Credits ClosingBal")
        page.save()

        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement-7-column-wrap.pdf", output.getvalue(), "application/pdf")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["column_mapping"], {"date": 0, "desc": 1, "debit": 3, "credit": 4, "balance": 5})
        self.assertEqual(len(payload["transactions"]), 4)
        self.assertEqual(payload["transactions"][0]["date"], "21/09/26")
        self.assertIn("ORBITX NETWORK GROUP CUSTOMER CREDIT", payload["transactions"][0]["description"])
        self.assertEqual(payload["transactions"][0]["credit"], 1718697.4)
        self.assertEqual(payload["transactions"][0]["balance"], 1737613.76)
        self.assertEqual(payload["transactions"][0]["status"], "unverified")
        self.assertEqual([item["debit"] for item in payload["transactions"][1:]], [200000.0, 200000.0, 150000.0])
        self.assertEqual([item["status"] for item in payload["transactions"][1:]], ["ok", "ok", "ok"])
        self.assertEqual(payload["reconciliation"]["status"], "partial")
        self.assertEqual(payload["reconciliation"]["checked_rows"], 3)
        self.assertEqual(payload["reconciliation"]["unverified_rows"], 1)
        self.assertFalse(any("STATEMENT SUMMARY" in item["description"] for item in payload["transactions"]))

        exported = self.client.post("/api/export/csv", json=payload)
        self.assertEqual(exported.status_code, 200, exported.text)
        csv_rows = list(csv.DictReader(io.StringIO(exported.text)))
        self.assertEqual(len(csv_rows), 4)
        self.assertEqual(csv_rows[0]["Date"], "21/09/26")
        self.assertIn("ORBITX NETWORK GROUP CUSTOMER CREDIT", csv_rows[0]["Description"])
        self.assertEqual(csv_rows[0]["Debit (Withdrawal)"], "")
        self.assertEqual(csv_rows[0]["Credit (Deposit)"], "1718697.4")
        self.assertEqual(csv_rows[0]["Balance"], "1737613.76")
        self.assertEqual(csv_rows[1]["Debit (Withdrawal)"], "200000.0")
        self.assertEqual(csv_rows[1]["Credit (Deposit)"], "")
        self.assertEqual(csv_rows[1]["Balance"], "1537613.76")
        self.assertEqual(csv_rows[0]["Checksum Status"], "unverified")
        self.assertEqual(csv_rows[1]["Checksum Status"], "ok")

    def test_multi_date_statement_row_is_disclosed_and_omitted_from_exports(self):
        csv_content = (
            "Date,Description,Debit,Credit,Balance\n"
            '"21/09/26 25/09/26 25/09/26 25/09/26","FOREIGN INWARD REMITTANCE TXN000000RO",,,\n'
            '"26/09/26","Monthly service fee",10.00,,990.00\n'
        )
        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("merged-dates.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["transactions"]), 1)
        self.assertEqual(payload["transactions"][0]["description"], "Monthly service fee")
        self.assertEqual(payload["excluded_rows"], [{"row_index": 1, "reason": "multiple_dates"}])

        csv_export = self.client.post("/api/export/csv", json=payload)
        self.assertEqual(csv_export.status_code, 200, csv_export.text)
        self.assertIn("Monthly service fee", csv_export.text)
        self.assertNotIn("FOREIGN INWARD REMITTANCE", csv_export.text)

    def test_excluded_multi_date_row_downgrades_reconciliation_to_partial(self):
        csv_content = (
            "Date,Description,Debit,Credit,Balance\n"
            '"20/09/26","Opening balance",,,"1,000.00"\n'
            '"21/09/26 25/09/26 25/09/26 25/09/26","FOREIGN INWARD REMITTANCE TXN000000RO",,,\n'
            '"26/09/26","Monthly service fee","10.00",,"990.00"\n'
        )
        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("merged-dates-with-balanced-rows.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["transactions"]), 2)
        self.assertEqual(payload["excluded_rows"], [{"row_index": 2, "reason": "multiple_dates"}])
        self.assertEqual(payload["reconciliation"]["status"], "partial")
        self.assertIsNone(payload["reconciliation"]["valid"])
        self.assertEqual(payload["reconciliation"]["checked_rows"], 1)
        self.assertEqual(payload["reconciliation"]["unverified_rows"], 1)

        csv_export = self.client.post("/api/export/csv", json=payload)
        self.assertEqual(csv_export.status_code, 200, csv_export.text)
        self.assertIn("Monthly service fee", csv_export.text)
        self.assertNotIn("FOREIGN INWARD REMITTANCE", csv_export.text)

    def test_european_decimal_csv_reconciles_through_the_http_route(self):
        # Quoted fields keep decimal commas inside the intended numeric columns.
        csv_content = (
            'Date,Description,Credit,Balance\n'
            '01/02/2024,Opening balance,,"1.000,00"\n'
            '02/02/2024,SEPA payment,"12,50","1.012,50"\n'
        )
        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement-eu.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["reconciliation"]["valid"])
        self.assertEqual(payload["reconciliation"]["status"], "verified")
        self.assertEqual(payload["transactions"][1]["credit"], 12.5)
        self.assertEqual(payload["transactions"][1]["balance"], 1012.5)

    def test_indian_grouped_rupee_csv_reconciles_through_the_http_route(self):
        csv_content = (
            'Date,Description,Credit,Balance\n'
            '01/04/2024,Opening balance,,"₹ 1,00,000.00"\n'
            '02/04/2024,UPI transfer,"₹ 2,500.00","₹ 1,02,500.00"\n'
        )
        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement-in.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertTrue(payload["reconciliation"]["valid"])
        self.assertEqual(payload["transactions"][1]["credit"], 2500.0)
        self.assertEqual(payload["transactions"][1]["balance"], 102500.0)

    def test_explicit_statement_number_locale_resolves_ambiguous_decimal_mark(self):
        csv_content = (
            'Date,Description,Credit,Balance\n'
            '2024-01-01,Opening balance,,"0,000"\n'
            '2024-01-02,Settlement,"1,234","1,234"\n'
        )
        response = self.client.post(
            "/api/extract/statement",
            data={"number_locale": "de-DE"},
            files={"file": ("statement.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["transactions"][1]["credit"], 1.234)
        self.assertEqual(payload["transactions"][1]["balance"], 1.234)
        self.assertEqual(payload["reconciliation"]["status"], "verified")

    def test_automatic_number_locale_does_not_guess_ambiguous_three_digit_comma_groups(self):
        csv_content = (
            'Date,Description,Credit,Balance\n'
            '2024-01-01,Opening balance,,"1,234"\n'
            '2024-01-02,Settlement,"1,234","2,468"\n'
        )
        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIsNone(payload["transactions"][0]["balance"])
        self.assertIsNone(payload["transactions"][1]["credit"])
        self.assertIsNone(payload["transactions"][1]["balance"])
        self.assertIsNone(payload["reconciliation"]["valid"])
        self.assertEqual(payload["reconciliation"]["status"], "unverified")

    def test_automatic_number_locale_does_not_guess_ambiguous_three_digit_period_groups(self):
        csv_content = (
            'Date,Description,Credit,Balance\n'
            '2024-01-01,Opening balance,,"1.234"\n'
            '2024-01-02,Settlement,"1.234","2.468"\n'
        )
        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIsNone(payload["transactions"][0]["balance"])
        self.assertIsNone(payload["transactions"][1]["credit"])
        self.assertIsNone(payload["transactions"][1]["balance"])
        self.assertIsNone(payload["reconciliation"]["valid"])
        self.assertEqual(payload["reconciliation"]["status"], "unverified")

    def test_explicit_indian_locale_reconciles_indian_grouped_rupee_statement(self):
        csv_content = (
            'Date,Description,Credit,Balance\n'
            '2024-01-01,Opening balance,,"₹ 1,00,000.00"\n'
            '2024-01-02,UPI transfer,"₹ 2,500.00","₹ 1,02,500.00"\n'
        )
        response = self.client.post(
            "/api/extract/statement",
            data={"number_locale": "en-IN"},
            files={"file": ("statement.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["transactions"][1]["credit"], 2500.0)
        self.assertEqual(payload["transactions"][1]["balance"], 102500.0)
        self.assertTrue(payload["reconciliation"]["valid"])

    def test_statement_number_locale_rejects_unsupported_values(self):
        response = self.client.post(
            "/api/extract/statement",
            data={"number_locale": "xx-YY"},
            files={"file": ("statement.csv", b"Date,Description,Credit,Balance\n", "text/csv")},
        )

        self.assertEqual(response.status_code, 422)

    def test_statement_date_order_normalizes_ambiguous_dates_only_when_requested(self):
        csv_content = (
            'Date,Description,Credit,Balance\n'
            '01/02/2024,Opening balance,,"0,000"\n'
            '02/02/2024,Settlement,"1,234","1,234"\n'
        )
        response = self.client.post(
            "/api/extract/statement",
            data={"number_locale": "de-DE", "date_order": "DMY"},
            files={"file": ("statement.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["transactions"][0]["date"], "2024-02-01")
        self.assertEqual(payload["transactions"][1]["date"], "2024-02-02")
        self.assertTrue(payload["reconciliation"]["valid"])

    def test_statement_date_order_rejects_unsupported_values(self):
        response = self.client.post(
            "/api/extract/statement",
            data={"date_order": "YDM"},
            files={"file": ("statement.csv", b"Date,Description,Credit,Balance\n", "text/csv")},
        )

        self.assertEqual(response.status_code, 422)

    def test_statement_without_a_checkable_balance_equation_is_explicitly_unverified(self):
        csv_content = (
            "Date,Description,Amount,Balance\n"
            "2024-01-01,Opening Balance,,100.00\n"
            "2024-01-02,Amount not detected,,95.00\n"
        )
        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIsNone(payload["reconciliation"]["valid"])
        self.assertEqual(payload["reconciliation"]["status"], "unverified")
        self.assertEqual(payload["reconciliation"]["checked_rows"], 0)
        self.assertEqual(payload["reconciliation"]["unverified_rows"], 1)
        self.assertEqual([row["status"] for row in payload["transactions"]], ["baseline", "unverified"])

        exported = self.client.post("/api/export/csv", json=payload)
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("unverified", exported.text)

    def test_statement_with_a_missing_intermediate_balance_does_not_reuse_a_stale_balance(self):
        csv_content = (
            "Date,Description,Debit,Credit,Balance\n"
            "2024-01-01,Opening Balance,,,100.00\n"
            "2024-01-02,Movement without balance,5.00,,\n"
            "2024-01-03,New observed balance,,20.00,120.00\n"
            "2024-01-04,Next movement,10.00,,110.00\n"
        )
        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement.csv", csv_content.encode("utf-8"), "text/csv")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIsNone(payload["reconciliation"]["valid"])
        self.assertEqual(payload["reconciliation"]["status"], "partial")
        self.assertEqual(payload["reconciliation"]["checked_rows"], 1)
        self.assertEqual(payload["reconciliation"]["unverified_rows"], 2)
        self.assertEqual(
            [row["status"] for row in payload["transactions"]],
            ["baseline", "unverified", "unverified", "ok"],
        )

    def test_statement_pdf_parser_errors_are_client_errors_without_parser_details(self):
        private_path = "/Users/private/customer statement.pdf"
        malformed_documents = [
            f"not a PDF: {private_path}".encode("utf-8"),
            b"%PDF-1.7\n1 0 obj <</Type /Page>> endobj\n%%EOF",
        ]
        for content in malformed_documents:
            with self.subTest(length=len(content)):
                response = self.client.post(
                    "/api/extract/statement",
                    files={"file": ("statement.pdf", content, "application/pdf")},
                )
                self.assertEqual(response.status_code, 422, response.text)
                self.assertNotIn(private_path, response.text)
                self.assertEqual(
                    response.json()["detail"],
                    "The PDF could not be read. If it is password-protected, unlock it first.",
                )

    def test_statement_pdf_extracts_structured_transactions_from_a_ruled_table(self):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

        pdf_buffer = io.BytesIO()
        table = Table([
            ["Date", "Description", "Withdrawals", "Deposits", "Balance"],
            ["2024-01-01", "Opening balance", "", "", "1000.00"],
            ["2024-01-05", "Client invoice", "", "500.00", "1500.00"],
            ["2024-01-10", "Service fee", "50.00", "", "1450.00"],
        ])
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ]))
        document = SimpleDocTemplate(pdf_buffer, pagesize=letter)
        document.build([table])

        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement.pdf", pdf_buffer.getvalue(), "application/pdf")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["transactions"]), 3)
        self.assertEqual(payload["transactions"][1]["description"], "Client invoice")
        self.assertEqual(payload["transactions"][1]["credit"], 500.0)
        self.assertEqual(payload["transactions"][2]["debit"], 50.0)
        self.assertTrue(payload["reconciliation"]["valid"])

    def test_statement_pdf_uses_an_unambiguous_summary_opening_balance(self):
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.pdfgen import canvas

        output = io.BytesIO()
        page = canvas.Canvas(output, pagesize=landscape(letter))
        page.setFont("Helvetica", 9)
        for x, label in ((30, "Date"), (120, "Description"), (400, "Debit"), (480, "Credit"), (560, "Balance")):
            page.drawString(x, 740, label)
        page.drawString(30, 715, "2026-01-02")
        page.drawString(120, 715, "Client payment")
        page.drawString(480, 715, "1,000.00")
        page.drawString(560, 715, "1,010.00")
        page.drawString(30, 690, "2026-01-03")
        page.drawString(120, 690, "Bank fee")
        page.drawString(400, 690, "1.00")
        page.drawString(560, 690, "1,009.00")

        summary_headers = (
            (100, "Opening Balance"), (235, "Dr Count"), (305, "Cr Count"),
            (380, "Debits"), (450, "Credits"), (530, "Closing Bal"),
        )
        for x, label in summary_headers:
            page.drawString(x, 590, label)
        summary_values = (
            (100, "10.00"), (245, "1"), (315, "1"),
            (380, "1.00"), (450, "1,000.00"), (530, "1,009.00"),
        )
        for x, value in summary_values:
            page.drawString(x, 570, value)
        page.save()

        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement.pdf", output.getvalue(), "application/pdf")},
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(len(payload["transactions"]), 2)
        self.assertEqual([item["status"] for item in payload["transactions"]], ["ok", "ok"])
        self.assertEqual(payload["reconciliation"]["checked_rows"], 2)
        self.assertEqual(payload["reconciliation"]["unverified_rows"], 0)
        self.assertTrue(payload["reconciliation"]["valid"])

    def test_statement_pdf_ignores_conflicting_opening_balance_summaries(self):
        from reportlab.lib.pagesizes import landscape, letter
        from reportlab.pdfgen import canvas
        from officekit.engines.engine_parser import extract_pdf_opening_balance

        output = io.BytesIO()
        page = canvas.Canvas(output, pagesize=landscape(letter))
        page.setFont("Helvetica", 9)
        for opening_balance in (10.0, 20.0):
            for x, label in (
                (100, "Opening Balance"), (235, "Dr Count"), (305, "Cr Count"),
                (380, "Debits"), (450, "Credits"), (530, "Closing Bal"),
            ):
                page.drawString(x, 590, label)
            for x, value in (
                (100, f"{opening_balance:.2f}"), (245, "1"), (315, "1"),
                (380, "1.00"), (450, "1,000.00"), (530, "1,009.00"),
            ):
                page.drawString(x, 570, value)
            page.showPage()
        page.save()

        self.assertIsNone(extract_pdf_opening_balance(output.getvalue()))

    def test_statement_pdf_does_not_count_repeated_page_headers_as_transactions(self):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

        pdf_buffer = io.BytesIO()
        rows = [["Date", "Description", "Withdrawals", "Deposits", "Balance"]]
        rows.append(["2024-01-01", "Opening balance", "", "", "1000.00"])
        rows.extend([
            ["2024-01-02", f"Deposit {index}", "", "1.00", f"{1000 + index:.2f}"]
            for index in range(1, 80)
        ])
        table = Table(rows, repeatRows=1, colWidths=[75, 190, 75, 75, 75])
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.35, colors.black),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        SimpleDocTemplate(pdf_buffer, pagesize=letter).build([table])

        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement.pdf", pdf_buffer.getvalue(), "application/pdf")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        transactions = response.json()["transactions"]
        self.assertEqual(len(transactions), 80)
        self.assertTrue(all(item["description"] != "Description" for item in transactions))
        self.assertEqual(transactions[-1]["balance"], 1079.0)

    def test_statement_combined_amount_does_not_infer_debit_from_merchant_name(self):
        csv_content = (
            "Date,Description,Amount,Balance\n"
            "2024-01-01,Opening balance,,100.00\n"
            "2024-01-02,Andrew Pharmacy,75.25,175.25\n"
        )
        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement.csv", csv_content.encode("utf-8"), "text/csv")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        transaction = response.json()["transactions"][1]
        self.assertEqual(transaction["credit"], 75.25)
        self.assertIsNone(transaction["debit"])
        self.assertTrue(response.json()["reconciliation"]["valid"])

    def test_statement_exports_treat_imported_formula_text_as_literal_and_bound_requests(self):
        payload = {
            "transactions": [
                {"date": "2024-01-01", "description": "=HYPERLINK(\"https://example.invalid\",\"open\")", "debit": 1.0, "status": "ok"},
                {"date": "\t=1+1", "description": "+SUM(1,2)", "credit": 2.0, "status": "reconciliation_warning"},
                {"date": "-1+1", "description": "@SUM(A1:A2)", "balance": 3.0, "status": "ok"},
            ]
        }
        csv_response = self.client.post("/api/export/csv", json=payload)
        self.assertEqual(csv_response.status_code, 200)
        rows = list(csv.reader(io.StringIO(csv_response.text)))
        self.assertEqual(rows[1][1], "'=HYPERLINK(\"https://example.invalid\",\"open\")")
        self.assertEqual(rows[2][0], "'\t=1+1")
        self.assertEqual(rows[2][1], "'+SUM(1,2)")
        self.assertEqual(rows[3][0], "'-1+1")
        self.assertEqual(rows[3][1], "'@SUM(A1:A2)")

        xlsx_response = self.client.post("/api/export/excel", json=payload)
        self.assertEqual(xlsx_response.status_code, 200)
        from openpyxl import load_workbook
        workbook = load_workbook(io.BytesIO(xlsx_response.content), data_only=False)
        sheet = workbook["Bank Statement"]
        for cell in ("B2", "A3", "B3", "A4", "B4"):
            with self.subTest(cell=cell):
                self.assertNotEqual(sheet[cell].data_type, "f")
                self.assertTrue(str(sheet[cell].value).startswith("'"))

        invalid_payloads = [
            {"transactions": [{"debit": "12.50"}]},
            {"transactions": [{"credit": True}]},
            {"transactions": [{"balance": 1e13}]},
            {"transactions": [{"status": "formula"}]},
            {"transactions": [{"description": 42}]},
            {"transactions": [{"description": "x" * 10_001}]},
            {"transactions": [{"date": "x" * 257}]},
            {"transactions": [{"debit": -0.01}]},
        ]
        for invalid in invalid_payloads:
            with self.subTest(invalid=invalid):
                self.assertEqual(self.client.post("/api/export/csv", json=invalid).status_code, 422)
        nonfinite_response = self.client.post(
            "/api/export/csv",
            content=json.dumps({"transactions": [{"credit": float("nan")}] }).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(nonfinite_response.status_code, 422)
        too_many = {"transactions": [{} for _ in range(10_001)]}
        self.assertEqual(self.client.post("/api/export/excel", json=too_many).status_code, 422)

        oversized_body = {"unused_parser_metadata": "x" * (8 * 1024 * 1024)}
        self.assertEqual(self.client.post("/api/export/csv", json=oversized_body).status_code, 413)

    def test_result_export_csv_returns_typed_attachment_and_rejects_invalid_snapshots(self):
        payload = {
            "format": "csv",
            "tool_id": "loan_emi",
            "title": "Loan summary",
            "created_at": "2026-10-06T09:30:00+05:30",
            "inputs": [{"name": "Principal", "value": 250000, "unit": "INR"}],
            "results": [
                {"name": "Payment", "value": 5135.77, "unit": "INR/month"},
                {"name": "User text", "value": "=1+1", "unit": None},
            ],
            "assumptions": ["Fixed rate"],
            "tables": [{"title": "Schedule", "columns": ["Month", "Balance"], "rows": [[1, 200000]]}],
            "include_attribution": True,
        }
        response = self.client.post("/api/export/result", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("text/csv", response.headers["content-type"])
        self.assertIn("loan_emi-result.csv", response.headers["content-disposition"])
        records = list(csv.DictReader(io.StringIO(response.text)))
        self.assertTrue(any(row["name"] == "Payment" and row["value_type"] == "number" for row in records))
        formula = next(row for row in records if row["name"] == "User text")
        self.assertEqual(formula["value"], "'=1+1")
        self.assertTrue(any(row["name"] == "attribution" and "officekit.app" in row["value"] for row in records))

        invalid_format = {**payload, "format": "docx"}
        self.assertEqual(self.client.post("/api/export/result", json=invalid_format).status_code, 422)
        invalid_time = {**payload, "created_at": "not-a-timestamp"}
        invalid_response = self.client.post("/api/export/result", json=invalid_time)
        self.assertEqual(invalid_response.status_code, 422)

    def test_result_export_xlsx_returns_literal_safe_workbook_attachment(self):
        from openpyxl import load_workbook

        payload = {
            "format": "xlsx",
            "tool_id": "loan_emi",
            "title": "=HYPERLINK(\"https://example.invalid\",\"open\")",
            "created_at": "2026-10-06T09:30:00+05:30",
            "inputs": [{"name": "Principal", "value": 250000, "unit": "INR"}],
            "results": [{"name": "Text result", "value": "=1+1", "unit": None}],
            "assumptions": ["Fixed rate"],
            "tables": [{"title": "Schedule", "columns": ["Month", "Balance"], "rows": [[1, 200000]]}],
            "include_attribution": True,
        }
        response = self.client.post("/api/export/result", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", response.headers["content-type"])
        self.assertIn("loan_emi-result.xlsx", response.headers["content-disposition"])
        workbook = load_workbook(io.BytesIO(response.content), data_only=False)
        sheet = workbook["Result"]
        self.assertEqual(workbook.properties.title, payload["title"])
        self.assertTrue(any(row[0].value == "Attribution" for row in sheet.iter_rows()))
        self.assertTrue(all(cell.data_type != "f" for row in sheet.iter_rows() for cell in row))

    def test_result_export_pptx_returns_paginated_powerpoint_attachment(self):
        from pptx import Presentation

        payload = {
            "format": "pptx",
            "tool_id": "loan_emi",
            "title": "Loan summary",
            "created_at": "2026-10-06T09:30:00+05:30",
            "inputs": [{"name": "Principal", "value": 250000, "unit": "INR"}],
            "results": [{"name": "Payment", "value": 5135.77, "unit": "INR/month"}],
            "assumptions": ["Fixed rate"],
            "tables": [{"title": "Schedule", "columns": ["Month", "Balance"], "rows": [[1, 200000]]}],
            "include_attribution": True,
        }
        response = self.client.post("/api/export/result", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            response.headers["content-type"],
        )
        self.assertIn("loan_emi-result.pptx", response.headers["content-disposition"])
        presentation = Presentation(io.BytesIO(response.content))
        all_text = []
        for slide in presentation.slides:
            for shape in slide.shapes:
                if shape.has_text_frame:
                    all_text.append(shape.text)
                if shape.has_table:
                    all_text.extend(cell.text for row in shape.table.rows for cell in row.cells)
        text = "\n".join(all_text)
        self.assertIn("Payment: 5135.77 INR/month", text)
        self.assertIn("Generated with OfficeKit · officekit.app", text)
        self.assertEqual(presentation.core_properties.author, "OfficeKit")
        self.assertEqual(self.client.post("/api/export/result", json={**payload, "format": "docx"}).status_code, 422)

        oversized_presentation = {
            **payload,
            "tables": [{
                "title": "Too many slides",
                "columns": [f"Column {column}" for column in range(40)],
                "rows": [[row * column for column in range(40)] for row in range(1_000)],
            }],
        }
        bounded = self.client.post("/api/export/result", json=oversized_presentation)
        self.assertEqual(bounded.status_code, 422)
        self.assertIn("supported slide limit", bounded.json()["detail"])

    def test_result_export_pdf_returns_searchable_bounded_attachment(self):
        from pypdf import PdfReader

        payload = {
            "format": "pdf",
            "tool_id": "loan_emi",
            "title": "Loan summary",
            "created_at": "2026-10-06T09:30:00+05:30",
            "inputs": [{"name": "Principal", "value": 250000, "unit": "INR"}],
            "results": [{"name": "Monthly payment", "value": 5135.77, "unit": "INR/month"}],
            "assumptions": ["Fixed nominal rate"],
            "tables": [{"title": "Schedule", "columns": ["Month", "Balance"], "rows": [[1, 200000]]}],
            "include_attribution": True,
        }
        response = self.client.post("/api/export/result", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.content.startswith(b"%PDF-"))
        self.assertLessEqual(len(response.content), 8 * 1_048_576)
        self.assertIn("application/pdf", response.headers["content-type"])
        self.assertIn("loan_emi-result.pdf", response.headers["content-disposition"])
        reader = PdfReader(io.BytesIO(response.content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("Monthly payment", text)
        self.assertIn("5135.77 INR/month", text)
        self.assertIn("Generated with OfficeKit · officekit.app", text)
        self.assertEqual(reader.metadata.author, "OfficeKit")

        unsupported_glyph = {**payload, "results": [{"name": "Value", "value": "🚀", "unit": None}]}
        bounded = self.client.post("/api/export/result", json=unsupported_glyph)
        self.assertEqual(bounded.status_code, 422)
        self.assertIn("PDF fonts cannot display", bounded.json()["detail"])

    # 2. Module 2: Dictate & Meeting Notes E2E
    def test_e2e_dictate_format_notes(self):
        payload = {
            "transcript": "We decided to launch on Monday. Sarah will send the contract and Alex will follow up."
        }
        response = self.client.post("/api/dictate/format-notes", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("Sarah", " ".join(data["action_items"]))
        self.assertIn("## ✅ Action Items & Next Steps", data["markdown"])

    def test_dictate_route_keeps_positive_contrastive_clauses(self):
        transcript = (
            "We will not ship today, but Sarah will publish the docs tomorrow. "
            "We have not chosen a launch date, but we approved the privacy approach."
        )
        response = self.client.post("/api/dictate/format-notes", json={"transcript": transcript})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            data["action_items"],
            ["Sarah will publish the docs tomorrow"],
        )
        self.assertEqual(
            data["decisions"],
            ["we approved the privacy approach"],
        )

    def test_dictate_route_keeps_new_subject_action_after_negated_clause(self):
        response = self.client.post(
            "/api/dictate/format-notes",
            json={"transcript": "Sarah won't send the file and she will update the release notes."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action_items"], ["she will update the release notes"])

    def test_dictate_route_keeps_new_group_action_after_negated_clause(self):
        response = self.client.post(
            "/api/dictate/format-notes",
            json={"transcript": "Sarah won't send the file, and the team will update the release notes."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["action_items"], ["the team will update the release notes"])

    def test_dictate_route_does_not_promote_pending_decisions(self):
        transcript = (
            "The decision is still pending. No final decision has been made. "
            "No final decision on the launch. The launch decision is not final. "
            "We need a decision on pricing by Friday. "
            "The team must make a decision before launch. Decision is required by Friday. "
            "We decided the launch date is Friday."
        )
        response = self.client.post("/api/dictate/format-notes", json={"transcript": transcript})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["decisions"], ["We decided the launch date is Friday"])
        self.assertEqual(data["action_items"], ["The team must make a decision before launch"])
        self.assertIn("The decision is still pending", data["summary"])
        self.assertIn("We need a decision on pricing by Friday", data["markdown"])
        self.assertIn("The team must make a decision before launch", data["markdown"])
        self.assertIn("Decision is required by Friday", data["markdown"])

    def test_dictate_route_keeps_tentative_will_statements_out_of_confirmed_actions(self):
        transcript = (
            "Sarah will try to finish the test run. David will probably share the build tomorrow. "
            "We will maybe move the launch to Friday. Alex will attempt to reproduce it. "
            "Priya will hopefully send the results. Omar will be trying to resolve it. "
            "Sarah will review the release checklist."
        )
        response = self.client.post("/api/dictate/format-notes", json={"transcript": transcript})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["action_items"], ["Sarah will review the release checklist"])
        self.assertIn("Sarah will try to finish the test run", data["summary"])
        self.assertIn("David will probably share the build tomorrow", data["summary"])
        self.assertIn("Alex will attempt to reproduce it", data["markdown"])
        self.assertIn("Priya will hopefully send the results", data["markdown"])
        self.assertIn("Omar will be trying to resolve it", data["markdown"])

    def test_dictate_route_does_not_promote_conditional_commitments(self):
        transcript = (
            "If the client approves the budget, Sarah will sign the order. "
            "Only if QA passes will David publish the release. "
            "Sarah will send the final draft on Friday."
        )
        response = self.client.post("/api/dictate/format-notes", json={"transcript": transcript})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["action_items"], ["Sarah will send the final draft on Friday"])
        self.assertIn("If the client approves the budget", data["summary"])
        self.assertIn("Only if QA passes", data["summary"])

    def test_dictate_route_does_not_treat_an_approved_draft_as_a_decision(self):
        response = self.client.post(
            "/api/dictate/format-notes",
            json={"transcript": "Sarah will send the approved draft on Friday. Sarah will present the chosen plan tomorrow. We approved the privacy approach."},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["action_items"],
            [
                "Sarah will send the approved draft on Friday",
                "Sarah will present the chosen plan tomorrow",
            ],
        )
        self.assertEqual(response.json()["decisions"], ["We approved the privacy approach"])

    def test_dictate_route_does_not_promote_static_readiness_to_action(self):
        transcript = (
            "We must be ready before review. Sarah must be available for questions. "
            "Sarah must be available and review the agenda. The team will review the agenda. "
            "Sarah must be ready, and the team will send the agenda."
        )
        response = self.client.post("/api/dictate/format-notes", json={"transcript": transcript})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            data["action_items"],
            [
                "Sarah must be available and review the agenda",
                "The team will review the agenda",
                "Sarah must be ready, and the team will send the agenda",
            ],
        )
        self.assertIn("We must be ready before review", data["summary"])
        self.assertIn("Sarah must be available for questions", data["markdown"])

    def test_dictate_route_does_not_promote_negative_directives_to_actions(self):
        transcript = (
            "Let's not publish before legal sign-off. "
            "Let's not publish today, but Sarah will publish the docs tomorrow. "
            "Let's not forget to send the invoice by Friday."
        )
        response = self.client.post("/api/dictate/format-notes", json={"transcript": transcript})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["action_items"],
            [
                "Sarah will publish the docs tomorrow",
                "Let's not forget to send the invoice by Friday",
            ],
        )

    def test_dictate_route_rejects_oversized_and_non_string_transcripts(self):
        at_limit = self.client.post(
            "/api/dictate/format-notes",
            json={"transcript": "x" * 262144},
        )
        oversized = self.client.post(
            "/api/dictate/format-notes",
            json={"transcript": "x" * 262145},
        )
        non_string = self.client.post(
            "/api/dictate/format-notes",
            json={"transcript": 42},
        )
        unknown_field = self.client.post(
            "/api/dictate/format-notes",
            json={"transcript": "A discussion took place.", "unexpected": "data"},
        )

        self.assertEqual(at_limit.status_code, 200)
        self.assertEqual(oversized.status_code, 422)
        self.assertEqual(non_string.status_code, 422)
        self.assertEqual(unknown_field.status_code, 422)
        self.assertNotIn("x" * 100, str(oversized.json()))

    # 3. Module 3: PDF Password Security E2E
    def test_e2e_pdf_password_security(self):
        # Create sample PDF
        pdf = pikepdf.new()
        pdf.add_blank_page()
        buf = io.BytesIO()
        pdf.save(buf)
        raw_pdf = buf.getvalue()

        # Protect PDF
        protect_resp = self.client.post(
            "/api/pdf/protect",
            files={"file": ("doc.pdf", raw_pdf, "application/pdf")},
            data={"password": "MySecretPass2026"}
        )
        self.assertEqual(protect_resp.status_code, 200)
        encrypted_pdf = protect_resp.content

        # Unlock PDF
        unlock_resp = self.client.post(
            "/api/pdf/unlock",
            files={"file": ("doc.pdf", encrypted_pdf, "application/pdf")},
            data={"password": "MySecretPass2026"}
        )
        self.assertEqual(unlock_resp.status_code, 200)
        unlocked_pdf = unlock_resp.content

        # Verify unlocked PDF opens with no password
        with pikepdf.open(io.BytesIO(unlocked_pdf)) as check_pdf:
            self.assertEqual(len(check_pdf.pages), 1)

        for path, file_bytes, password in (
            ("/api/pdf/protect", raw_pdf, ""),
            ("/api/pdf/protect", raw_pdf, "x" * 1025),
            ("/api/pdf/unlock", encrypted_pdf, "x" * 1025),
        ):
            with self.subTest(path=path, password_length=len(password)):
                invalid = self.client.post(
                    path,
                    files={"file": ("doc.pdf", file_bytes, "application/pdf")},
                    data={"password": password},
                )
                self.assertEqual(invalid.status_code, 422)

    def test_e2e_pdf_failures_do_not_disclose_parser_details(self):
        private_detail = b"not a PDF: /Users/private/customer-document.pdf"
        cases = (
            ("/api/pdf/unlock", {"password": "secret"}),
            ("/api/pdf/protect", {"password": "secret"}),
        )
        for path, data in cases:
            with self.subTest(path=path):
                response = self.client.post(
                    path,
                    files={"file": ("broken.pdf", private_detail, "application/pdf")},
                    data=data,
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json()["detail"],
                    "The PDF could not be processed. Verify that it is valid and try again.",
                )
                self.assertNotIn("/Users/private", response.text)

    # 4. Module 4 & 5: Any-to-Any File & Data Conversion E2E
    def test_e2e_image_conversion(self):
        img = Image.new('RGB', (50, 50), color='blue')
        buf = io.BytesIO()
        img.save(buf, format='PNG')

        resp = self.client.post(
            "/api/convert/image",
            files={"file": ("image.png", buf.getvalue(), "image/png")},
            data={"target_format": "webp", "quality": 85}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "image/webp")
        unicode_name = self.client.post(
            "/api/convert/image",
            files={"file": ("/private/résumé.png", buf.getvalue(), "image/png")},
            data={"target_format": "webp"},
        )
        self.assertEqual(unicode_name.status_code, 200)
        self.assertEqual(
            unicode_name.headers["content-disposition"],
            'attachment; filename="resume.webp"; filename*=UTF-8\'\'r%C3%A9sum%C3%A9.webp',
        )
        self.assertNotIn("private", unicode_name.headers["content-disposition"])

        for quality in ("0", "101", "-1"):
            with self.subTest(quality=quality):
                invalid_quality = self.client.post(
                    "/api/convert/image",
                    files={"file": ("image.png", buf.getvalue(), "image/png")},
                    data={"target_format": "webp", "quality": quality},
                )
                self.assertEqual(invalid_quality.status_code, 422)

    def test_e2e_invalid_conversion_input_has_safe_422_message(self):
        private_detail = b'/Users/private/customer statement.json: invalid secret field'
        image_response = self.client.post(
            "/api/convert/image",
            files={"file": ("private.png", private_detail, "image/png")},
            data={"target_format": "png"},
        )
        data_response = self.client.post(
            "/api/convert/data",
            files={"file": ("private.json", private_detail, "application/json")},
            data={"target_format": "json"},
        )

        self.assertEqual(image_response.status_code, 422)
        self.assertEqual(data_response.status_code, 422)
        for response in (image_response, data_response):
            with self.subTest(response=response):
                self.assertEqual(
                    response.json()["detail"],
                    "The file or requested format cannot be converted. Check the input and try again.",
                )
                self.assertNotIn("/Users/private", response.text)
                self.assertNotIn("secret field", response.text)

    def test_e2e_tabular_conversion_preserves_null_empty_and_literal_marker(self):
        source = json.dumps([{
            "null_value": None,
            "empty_value": "",
            "literal_marker": "\\N",
            "literal_escape": "\\starts-with-slash",
        }]).encode("utf-8")
        converted = self.client.post(
            "/api/convert/data",
            files={"file": ("values.json", source, "application/json")},
            data={"target_format": "csv", "null_token": "\\N"},
        )

        self.assertEqual(converted.status_code, 200, converted.text)
        csv_rows = list(csv.reader(io.StringIO(converted.content.decode("utf-8"))))
        self.assertEqual(csv_rows[1], ["\\N", "", "\\\\N", "\\\\starts-with-slash"])

        round_trip = self.client.post(
            "/api/convert/data",
            files={"file": ("values.csv", converted.content, "text/csv")},
            data={"target_format": "json", "null_token": "\\N"},
        )
        self.assertEqual(round_trip.status_code, 200, round_trip.text)
        self.assertEqual(json.loads(round_trip.content), json.loads(source))

    def test_e2e_tabular_conversion_rejects_unsafe_null_markers(self):
        source = b'[{"value":null}]'
        for null_token in (
            "x" * 65, "line\nbreak", "nul\x00byte", "=SUM(A1:A2)", "  +cmd", "\u200b@payload",
        ):
            with self.subTest(null_token=null_token):
                response = self.client.post(
                    "/api/convert/data",
                    files={"file": ("values.json", source, "application/json")},
                    data={"target_format": "csv", "null_token": null_token},
                )
                self.assertEqual(response.status_code, 422)

    def test_e2e_unexpected_conversion_failure_uses_generic_500(self):
        private_detail = "unexpected failure at /Users/private/customer-data"
        client = TestClient(app, raise_server_exceptions=False)
        with patch("app.FileConverterEngine.convert_data_file", side_effect=RuntimeError(private_detail)):
            response = client.post(
                "/api/convert/data",
                files={"file": ("valid.csv", b"name\nAda\n", "text/csv")},
                data={"target_format": "json"},
            )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json(),
            {"error": {"code": "internal_error", "message": "The operation could not be completed. Try again."}},
        )
        self.assertNotIn(private_detail, response.text)

    def test_e2e_data_conversion(self):
        csv_data = b"product,price\nKeyboard,49.99\n"
        resp = self.client.post(
            "/api/convert/data",
            files={"file": ("data.csv", csv_data, "text/csv")},
            data={"target_format": "json"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Keyboard", resp.text)

        for filename, content in (
            ("accounts.csv", b"account,amount\n001234,25.50\n000045,0\n"),
            ("accounts.tsv", b"account\tamount\n001234\t25.50\n000045\t0\n"),
        ):
            with self.subTest(filename=filename):
                preserved = self.client.post(
                    "/api/convert/data",
                    files={"file": (filename, content, "text/plain")},
                    data={"target_format": "json"},
                )
                self.assertEqual(preserved.status_code, 200)
                self.assertEqual(json.loads(preserved.content), [
                    {"account": "001234", "amount": 25.5},
                    {"account": "000045", "amount": 0},
                ])

        with patch("app.FileConverterEngine.MAX_TABULAR_CELLS", 5):
            bounded = self.client.post(
                "/api/convert/data",
                files={"file": ("wide.csv", b"a,b\n1,2\n3,4\n", "text/csv")},
                data={"target_format": "json"},
            )
        self.assertEqual(bounded.status_code, 422)
        self.assertEqual(
            bounded.json()["detail"],
            "The file or requested format cannot be converted. Check the input and try again.",
        )

        unicode_name = self.client.post(
            "/api/convert/data",
            files={"file": (r"C:\private\résumé.csv", csv_data, "text/csv")},
            data={"target_format": "json"},
        )
        self.assertEqual(unicode_name.status_code, 200)
        self.assertEqual(
            unicode_name.headers["content-disposition"],
            'attachment; filename="resume.json"; filename*=UTF-8\'\'r%C3%A9sum%C3%A9.json',
        )
        self.assertNotIn("private", unicode_name.headers["content-disposition"])

    def test_e2e_legacy_xls_import_and_malformed_workbook_use_safe_responses(self):
        workbook = xlwt.Workbook()
        sheet = workbook.add_sheet("Transactions")
        sheet.write(0, 0, "account")
        sheet.write(0, 1, "amount")
        sheet.write(1, 0, "000042")
        sheet.write(1, 1, 12.5)
        source = io.BytesIO()
        workbook.save(source)

        response = self.client.post(
            "/api/convert/data",
            files={"file": ("transactions.xls", source.getvalue(), "application/vnd.ms-excel")},
            data={"target_format": "json"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(json.loads(response.content), [{"account": "000042", "amount": 12.5}])

        malformed = self.client.post(
            "/api/convert/data",
            files={"file": ("private.xls", b"not an XLS workbook", "application/vnd.ms-excel")},
            data={"target_format": "json"},
        )
        self.assertEqual(malformed.status_code, 422)
        self.assertNotIn("xlrd", malformed.text.casefold())

    def test_xlsx_worksheet_discovery_and_selection_are_available_through_multipart_api(self):
        workbook = Workbook()
        transactions = workbook.active
        transactions.title = "Transactions"
        transactions.append(["account", "amount"])
        transactions.append([1234, 25.5])
        transactions["A2"].number_format = "000000"
        summary = workbook.create_sheet("Summary")
        summary.append(["code", "posted_at"])
        summary.append([45, datetime(2026, 10, 8)])
        summary["A2"].number_format = "000000"
        summary["B2"].number_format = "yyyy-mm-dd"
        workbook.active = 1
        source = io.BytesIO()
        workbook.save(source)
        workbook.close()
        file_part = ("book.xlsx", source.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        discovered = self.client.post("/api/convert/data/sheets", files={"file": file_part})
        self.assertEqual(discovered.status_code, 200, discovered.text)
        self.assertEqual(discovered.json(), {"sheets": ["Transactions", "Summary"]})

        default_sheet = self.client.post(
            "/api/convert/data",
            files={"file": file_part},
            data={"target_format": "json"},
        )
        self.assertEqual(default_sheet.status_code, 200, default_sheet.text)
        self.assertEqual(json.loads(default_sheet.content), [{"account": "001234", "amount": 25.5}])

        selected_sheet = self.client.post(
            "/api/convert/data",
            files={"file": file_part},
            data={"target_format": "json", "sheet_name": "Summary"},
        )
        self.assertEqual(selected_sheet.status_code, 200, selected_sheet.text)
        self.assertEqual(
            json.loads(selected_sheet.content),
            [{"code": "000045", "posted_at": "2026-10-08T00:00:00"}],
        )

    def test_xlsx_sheet_discovery_and_conversion_reject_invalid_workbook_selection_safely(self):
        workbook = Workbook()
        workbook.active.title = "Transactions"
        workbook.create_sheet("<img onerror=1>")
        source = io.BytesIO()
        workbook.save(source)
        workbook.close()
        xlsx = ("private.xlsx", source.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        discovered = self.client.post("/api/convert/data/sheets", files={"file": xlsx})
        self.assertEqual(discovered.status_code, 200, discovered.text)
        self.assertEqual(discovered.json(), {"sheets": ["Transactions", "<img onerror=1>"]})

        invalid_selection = self.client.post(
            "/api/convert/data",
            files={"file": xlsx},
            data={"target_format": "json", "sheet_name": "Missing"},
        )
        self.assertEqual(invalid_selection.status_code, 422)
        self.assertEqual(
            invalid_selection.json()["detail"],
            "The file or requested format cannot be converted. Check the input and try again.",
        )
        with patch.object(FileConverterEngine, "MAX_XLSX_SHEETS", 1):
            too_many_sheets = self.client.post("/api/convert/data/sheets", files={"file": xlsx})
        self.assertEqual(too_many_sheets.status_code, 422)
        self.assertEqual(
            too_many_sheets.json()["detail"],
            "The file or requested format cannot be converted. Check the input and try again.",
        )
        wrong_source = self.client.post(
            "/api/convert/data",
            files={"file": ("rows.csv", b"name\nAda\n", "text/csv")},
            data={"target_format": "json", "sheet_name": "Transactions"},
        )
        self.assertEqual(wrong_source.status_code, 422)
        for filename, content in (("not.xlsx", b"not a workbook"), ("rows.csv", b"a,b\n1,2\n")):
            with self.subTest(filename=filename):
                rejected = self.client.post(
                    "/api/convert/data/sheets",
                    files={"file": (filename, content, "application/octet-stream")},
                )
                self.assertEqual(rejected.status_code, 422)
                self.assertEqual(
                    rejected.json()["detail"],
                    "The file or requested format cannot be converted. Check the input and try again.",
                )

    def test_e2e_json_conversion_rejects_duplicate_keys_non_finite_and_deep_input(self):
        inputs = (
            b'[{"account":"first","account":"second"}]',
            b'[{"amount":NaN}]',
            b'[{"amount":1e309}]',
            b'["\\ud800"]',
            b"[" * 1100 + b"0" + b"]" * 1100,
        )
        for content in inputs:
            with self.subTest(content=content[:80]):
                response = self.client.post(
                    "/api/convert/data",
                    files={"file": ("records.json", content, "application/json")},
                    data={"target_format": "csv"},
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    response.json()["detail"],
                    "The file or requested format cannot be converted. Check the input and try again.",
                )

        sql_resp = self.client.post(
            "/api/convert/data",
            files={"file": ("inventory.csv", b"product,price\nKeyboard,49.99\n", "text/csv")},
            data={"target_format": "sql"},
        )
        self.assertEqual(sql_resp.status_code, 200)
        self.assertIn('INSERT INTO "exported_table"', sql_resp.text)

        injected_header = self.client.post(
            "/api/convert/data",
            files={"file": ("inventory.csv", b'"product); DROP TABLE users;--",price\nKeyboard,49.99\n', "text/csv")},
            data={"target_format": "sql"},
        )
        self.assertEqual(injected_header.status_code, 200)
        self.assertIn('"product); DROP TABLE users;--"', injected_header.text)

    def test_e2e_data_converter_exports_yaml_html_and_sql_and_rejects_unknown_formats(self):
        source = b"name,amount\nAda,12.50\n"
        expected_mime = {
            "yaml": "text/yaml; charset=utf-8",
            "html": "text/html; charset=utf-8",
            "sql": "application/sql",
        }
        for target, mime in expected_mime.items():
            with self.subTest(target=target):
                response = self.client.post(
                    "/api/convert/data",
                    files={"file": ("ledger.csv", source, "text/csv")},
                    data={"target_format": target},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["content-type"], mime)
                self.assertGreater(len(response.content), 0)
                self.assertIn("ledger." + target, response.headers["content-disposition"])

        yaml_source = b"- name: Ada\n  amount: 12.50\n"
        yaml_response = self.client.post(
            "/api/convert/data",
            files={"file": ("ledger.yml", yaml_source, "text/yaml")},
            data={"target_format": "json"},
        )
        self.assertEqual(yaml_response.status_code, 200)
        self.assertEqual(json.loads(yaml_response.content), [{"name": "Ada", "amount": 12.5}])

        for filename, target in (("unknown.dat", "json"), ("ledger.csv", "not-a-format")):
            with self.subTest(filename=filename, target=target):
                rejected = self.client.post(
                    "/api/convert/data",
                    files={"file": (filename, source, "application/octet-stream")},
                    data={"target_format": target},
                )
                self.assertEqual(rejected.status_code, 422)
                self.assertEqual(
                    rejected.json()["detail"],
                    "The file or requested format cannot be converted. Check the input and try again.",
                )

    def test_e2e_yaml_file_conversion_is_strict_and_preserves_exact_json_numbers(self):
        invalid_yaml = (
            b"name: first\nname: second\n",
            b"defaults: &defaults\n  amount: 1\nrow: *defaults\n",
            b"amount: .nan\n",
        )
        for content in invalid_yaml:
            with self.subTest(content=content):
                response = self.client.post(
                    "/api/convert/data",
                    files={"file": ("records.yaml", content, "application/yaml")},
                    data={"target_format": "json"},
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    response.json()["detail"],
                    "The file or requested format cannot be converted. Check the input and try again.",
                )

        source = b"amount: 0.123456789012345678901234567890\nflag: yes\ncode: 0012\n"
        response = self.client.post(
            "/api/convert/data",
            files={"file": ("exact.yml", source, "application/yaml")},
            data={"target_format": "json"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"0.123456789012345678901234567890", response.content)
        self.assertIn(b'"flag": "yes"', response.content)
        self.assertIn(b'"code": "0012"', response.content)

    def test_e2e_xlsx_converter_rejects_sheet_dimensions_over_shared_limits(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["first", "second"])
        sheet.append(["a", "b"])
        sheet.append(["c", "d"])
        source = io.BytesIO()
        workbook.save(source)
        workbook.close()

        with patch("app.FileConverterEngine.MAX_TABULAR_CELLS", 5):
            response = self.client.post(
                "/api/convert/data",
                files={"file": ("records.xlsx", source.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"target_format": "json"},
            )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "The file or requested format cannot be converted. Check the input and try again.",
        )

    def test_e2e_xlsx_converter_preserves_formatted_identifiers_and_iso_dates(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["account", "posted_at", "amount"])
        sheet.append([1234, datetime(2026, 10, 7), 25.5])
        sheet["A2"].number_format = "000000"
        sheet["B2"].number_format = "yyyy-mm-dd"
        source = io.BytesIO()
        workbook.save(source)
        workbook.close()

        response = self.client.post(
            "/api/convert/data",
            files={"file": ("ledger.xlsx", source.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"target_format": "json"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), [
            {"account": "001234", "posted_at": "2026-10-07T00:00:00", "amount": 25.5},
        ])

    def test_e2e_xlsx_converter_preserves_common_numeric_display_formats(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.append([
            "currency", "percentage", "negative", "zero", "rounded",
            "inr", "negative_inr", "weight", "escaped_percent", "condition",
        ])
        sheet.append([1234.5, 0.125, -1234.5, 0, 1.125, 1234567.5, -1234567.5, 2.5, 0.125, 1.25])
        sheet["A2"].number_format = "$#,##0.00"
        sheet["B2"].number_format = "0.0%"
        sheet["C2"].number_format = "#,##0.00;(#,##0.00)"
        sheet["D2"].number_format = '#,##0.00;(#,##0.00);"-"'
        sheet["E2"].number_format = "0.00"
        sheet["F2"].number_format = "[$₹-en-IN]#,##,##0.00"
        sheet["G2"].number_format = "[Red]-[$₹-en-IN]#,##,##0.00"
        sheet["H2"].number_format = '0.00" kg"'
        sheet["I2"].number_format = r"0.0\%"
        sheet["J2"].number_format = "[>=1]0.00;[Red](0.00)"
        source = io.BytesIO()
        workbook.save(source)
        workbook.close()

        response = self.client.post(
            "/api/convert/data",
            files={"file": ("formatted.xlsx", source.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"target_format": "json"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(json.loads(response.content), [{
            "currency": "$1,234.50",
            "percentage": "12.5%",
            "negative": "(1,234.50)",
            "zero": "-",
            "rounded": "1.13",
            "inr": "₹12,34,567.50",
            "negative_inr": "-₹12,34,567.50",
            "weight": "2.50 kg",
            "escaped_percent": "0.1%",
            "condition": 1.25,
        }])

        csv_response = self.client.post(
            "/api/convert/data",
            files={"file": ("formatted.xlsx", source.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"target_format": "csv"},
        )

        self.assertEqual(csv_response.status_code, 200, csv_response.text)
        self.assertEqual(
            list(csv.reader(io.StringIO(csv_response.content.decode("utf-8")))),
            [
                [
                    "currency", "percentage", "negative", "zero", "rounded",
                    "inr", "negative_inr", "weight", "escaped_percent", "condition",
                ],
                [
                    "$1,234.50", "12.5%", "(1,234.50)", "-", "1.13",
                    "₹12,34,567.50", "'-₹12,34,567.50", "2.50 kg", "0.1%", "1.25",
                ],
            ],
        )

    def test_e2e_json_nested_values_convert_to_csv_and_xlsx_without_python_repr(self):
        source = json.dumps([{
            "account": "001234",
            "items": [1, {"sku": "A-1"}],
            "metadata": {"active": True},
            "note": None,
        }]).encode("utf-8")
        items = '[1,{"sku":"A-1"}]'
        metadata = '{"active":true}'

        csv_response = self.client.post(
            "/api/convert/data",
            files={"file": ("nested.json", source, "application/json")},
            data={"target_format": "csv"},
        )
        self.assertEqual(csv_response.status_code, 200, csv_response.text)
        self.assertEqual(
            list(csv.reader(io.StringIO(csv_response.content.decode("utf-8")))),
            [["account", "items", "metadata", "note"], ["001234", items, metadata, ""]],
        )

        xlsx_response = self.client.post(
            "/api/convert/data",
            files={"file": ("nested.json", source, "application/json")},
            data={"target_format": "xlsx"},
        )
        self.assertEqual(xlsx_response.status_code, 200, xlsx_response.text)
        workbook = load_workbook(io.BytesIO(xlsx_response.content), data_only=True)
        try:
            sheet = workbook.active
            self.assertEqual([sheet.cell(2, column).value for column in range(1, 5)], ["001234", items, metadata, None])
        finally:
            workbook.close()

    # 5. Module 6: Financial Calculators E2E
    def test_e2e_calculators(self):
        math_result = self.client.post("/api/math/eval", json={"expression": "2 + 3 * 4"})
        self.assertEqual(math_result.status_code, 200)
        self.assertEqual(math_result.json()["result"], 14.0)
        scientific_result = self.client.post(
            "/api/math/eval",
            json={"expression": "sin(90) + asin(1)", "angle_mode": "degrees"},
        )
        self.assertEqual(scientific_result.status_code, 200)
        self.assertAlmostEqual(scientific_result.json()["result"], 91.0)
        self.assertEqual(scientific_result.json()["angle_mode"], "degrees")
        radians_result = self.client.post(
            "/api/math/eval", json={"expression": "sin(pi / 2)"}
        )
        self.assertEqual(radians_result.status_code, 200)
        self.assertAlmostEqual(radians_result.json()["result"], 1.0)
        self.assertEqual(radians_result.json()["angle_mode"], "radians")
        for payload in (
            {"expression": "2 ** 334"},
            {"expression": "True + 1"},
            {"expression": "1 / 0"},
            {"expression": " "},
            {"expression": "1" * 513},
            {"expression": "1 + 1", "debug": True},
            {"expression": "sin(90)", "angle_mode": "gradians"},
        ):
            with self.subTest(payload=payload):
                response = self.client.post("/api/math/eval", json=payload)
                self.assertEqual(response.status_code, 422)

        # Loan EMI
        emi_resp = self.client.post(
            "/api/calculator/loan-emi",
            json={"principal": 50000, "annual_interest_rate": 7.5, "tenure_years": 5}
        )
        self.assertEqual(emi_resp.status_code, 200)
        self.assertEqual(emi_resp.json()["monthly_emi"], 1001.9)
        self.assertEqual(len(emi_resp.json()["schedule"]), 60)
        self.assertEqual(emi_resp.json()["schedule"][-1]["remaining_balance"], 0.0)
        self.assertEqual(emi_resp.json()["assumptions"]["fees_and_extra_payments"], "excluded")

        zero_principal_loan = self.client.post(
            "/api/calculator/loan-emi",
            json={"principal": 0, "annual_interest_rate": 12.5, "tenure_years": 1},
        )
        self.assertEqual(zero_principal_loan.status_code, 200)
        self.assertEqual(zero_principal_loan.json()["monthly_emi"], 0.0)
        self.assertEqual(zero_principal_loan.json()["total_interest"], 0.0)
        self.assertEqual(zero_principal_loan.json()["total_payment"], 0.0)
        self.assertEqual(len(zero_principal_loan.json()["schedule"]), 12)
        self.assertTrue(all(row["remaining_balance"] == 0.0 for row in zero_principal_loan.json()["schedule"]))

        fractional_month_term = self.client.post(
            "/api/calculator/loan-emi",
            json={"principal": 50000, "annual_interest_rate": 7.5, "tenure_years": 1.001},
        )
        self.assertEqual(fractional_month_term.status_code, 422)

        break_even_resp = self.client.post(
            "/api/calculator/break-even",
            json={"fixed_costs": 1000, "price_per_unit": 50, "cost_per_unit": 20},
        )
        self.assertEqual(break_even_resp.status_code, 200)
        self.assertEqual(break_even_resp.json()["break_even_units"], 34)
        self.assertEqual(break_even_resp.json()["break_even_revenue"], 1700.0)
        invalid_break_even = self.client.post(
            "/api/calculator/break-even",
            json={"fixed_costs": -1, "price_per_unit": 50, "cost_per_unit": 20},
        )
        self.assertEqual(invalid_break_even.status_code, 422)

        depreciation = self.client.post(
            "/api/calculator/depreciation",
            json={"asset_cost": 10, "salvage_value": 0, "useful_life_years": 3},
        )
        self.assertEqual(depreciation.status_code, 200)
        depreciation_data = depreciation.json()
        self.assertEqual(
            [row["depreciation"] for row in depreciation_data["schedule"]],
            [3.33, 3.33, 3.34],
        )
        self.assertEqual(depreciation_data["schedule"][-1]["book_value"], 0.0)
        self.assertEqual(depreciation_data["assumptions"]["final_period"], "adjusted_to_salvage_value")

        for invalid_depreciation in (
            {"asset_cost": 10, "salvage_value": 11, "useful_life_years": 3},
            {"asset_cost": 10, "salvage_value": 0, "useful_life_years": 0},
            {"asset_cost": 10, "salvage_value": 0, "useful_life_years": 1.5},
            {"asset_cost": 10, "salvage_value": 0, "useful_life_years": 3, "debug": True},
        ):
            with self.subTest(depreciation=invalid_depreciation):
                response = self.client.post("/api/calculator/depreciation", json=invalid_depreciation)
                self.assertEqual(response.status_code, 422)

        simple_interest = self.client.post(
            "/api/calculator/simple-interest",
            json={"principal": 1000, "annual_rate_percent": 10, "time_value": 2, "time_unit": "years"},
        )
        self.assertEqual(simple_interest.status_code, 200)
        self.assertEqual(simple_interest.json()["interest_amount"], 200.0)
        self.assertEqual(simple_interest.json()["total_amount"], 1200.0)
        monthly_duration = self.client.post(
            "/api/calculator/simple-interest",
            json={"principal": 1000, "annual_rate_percent": 10, "time_value": 24, "time_unit": "months"},
        )
        self.assertEqual(monthly_duration.json()["interest_amount"], 200.0)
        for invalid_duration in (
            {"principal": 1000, "annual_rate_percent": 10, "time_value": 0, "time_unit": "years"},
            {"principal": 1000, "annual_rate_percent": 10, "time_value": 1, "time_unit": "days"},
        ):
            with self.subTest(duration=invalid_duration):
                response = self.client.post("/api/calculator/simple-interest", json=invalid_duration)
                self.assertEqual(response.status_code, 422)
        nonprofitable_break_even = self.client.post(
            "/api/calculator/break-even",
            json={"fixed_costs": 1000, "price_per_unit": 20, "cost_per_unit": 20},
        )
        self.assertEqual(nonprofitable_break_even.status_code, 422)
        boolean_break_even = self.client.post(
            "/api/calculator/break-even",
            json={"fixed_costs": True, "price_per_unit": 50, "cost_per_unit": 20},
        )
        self.assertEqual(boolean_break_even.status_code, 422)

        compound_resp = self.client.post(
            "/api/calculator/compound-interest",
            json={"principal": 1000, "annual_rate": 12, "years": 1,
                  "compound_freq": 1, "monthly_contribution": 100},
        )
        self.assertEqual(compound_resp.status_code, 200)
        annual_month_factor = 1.12 ** (1 / 12)
        expected_compound = 1000 * 1.12 + 100 * (1.12 - 1) / (annual_month_factor - 1)
        self.assertAlmostEqual(compound_resp.json()["future_value"], expected_compound, places=2)
        self.assertEqual(compound_resp.json()["total_invested"], 2200.0)
        self.assertEqual(compound_resp.json()["assumptions"]["contribution_timing"], "end_of_month")

        invalid_compound = self.client.post(
            "/api/calculator/compound-interest",
            json={"principal": 1000, "annual_rate": 12, "years": 1,
                  "compound_freq": 0},
        )
        self.assertEqual(invalid_compound.status_code, 422)
        nonfinite_compound = self.client.post(
            "/api/calculator/compound-interest",
            content='{"principal": NaN, "annual_rate": 12, "years": 1}',
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(nonfinite_compound.status_code, 422)
        boolean_compound = self.client.post(
            "/api/calculator/compound-interest",
            json={"principal": True, "annual_rate": 12, "years": 1},
        )
        self.assertEqual(boolean_compound.status_code, 422)

        # VAT
        vat_resp = self.client.post(
            "/api/calculator/vat-sales-tax",
            json={"amount": 100, "tax_rate_percent": 20, "is_inclusive": False}
        )
        self.assertEqual(vat_resp.status_code, 200)
        self.assertEqual(vat_resp.json()["gross_amount"], 120.0)
        self.assertEqual(vat_resp.json()["net_amount"], 100.0)
        self.assertEqual(vat_resp.json()["assumptions"]["jurisdiction"], "not_specified")
        invalid_vat = self.client.post(
            "/api/calculator/vat-sales-tax",
            json={"amount": 100, "tax_rate_percent": -1},
        )
        boolean_vat = self.client.post(
            "/api/calculator/vat-sales-tax",
            json={"amount": True, "tax_rate_percent": 20},
        )
        self.assertEqual(invalid_vat.status_code, 422)
        self.assertEqual(boolean_vat.status_code, 422)

        freelance_resp = self.client.post(
            "/api/calculator/freelance-rate",
            json={"target_annual_take_home": 80000, "billable_hours_per_week": 25,
                  "vacation_weeks": 4, "business_expenses_annual": 5000,
                  "tax_rate_percent": 25},
        )
        self.assertEqual(freelance_resp.status_code, 200)
        self.assertEqual(freelance_resp.json()["assumptions"]["jurisdiction"], "not_specified")
        impossible_freelance = self.client.post(
            "/api/calculator/freelance-rate",
            json={"target_annual_take_home": 80000, "tax_rate_percent": 100},
        )
        self.assertEqual(impossible_freelance.status_code, 422)

        margin_markup = self.client.post(
            "/api/calculator/margin-markup",
            json={"cost": 80, "revenue": 100},
        )
        self.assertEqual(margin_markup.status_code, 200)
        self.assertEqual(margin_markup.json()["gross_margin_percent"], 20.0)
        self.assertEqual(margin_markup.json()["markup_percent"], 25.0)
        half_cent_profit = self.client.post(
            "/api/calculator/margin-markup",
            json={"cost": 0, "revenue": 1.125},
        )
        self.assertEqual(half_cent_profit.status_code, 200)
        self.assertEqual(half_cent_profit.json()["profit"], 1.13)
        negative_half_cent_profit = self.client.post(
            "/api/calculator/margin-markup",
            json={"cost": 1.25, "revenue": 1.125},
        )
        self.assertEqual(negative_half_cent_profit.status_code, 200)
        self.assertEqual(negative_half_cent_profit.json()["profit"], -0.13)
        self.assertEqual(negative_half_cent_profit.json()["gross_margin_percent"], -11.11)
        zero_denominator = self.client.post(
            "/api/calculator/margin-markup",
            json={"cost": 10, "revenue": 0},
        )
        self.assertEqual(zero_denominator.status_code, 200)
        self.assertIsNone(zero_denominator.json()["gross_margin_percent"])
        self.assertEqual(zero_denominator.json()["markup_percent"], -100.0)
        boolean_amount = self.client.post(
            "/api/calculator/margin-markup",
            json={"cost": True, "revenue": 100},
        )
        self.assertEqual(boolean_amount.status_code, 422)
        overflow_client = TestClient(app, raise_server_exceptions=False)
        unrepresentable_margin = overflow_client.post(
            "/api/calculator/margin-markup",
            json={"cost": 1e12, "revenue": 1e-320},
        )
        self.assertEqual(unrepresentable_margin.status_code, 422)
        extra_field = self.client.post(
            "/api/calculator/margin-markup",
            json={"cost": 80, "revenue": 100, "currency": "USD"},
        )
        self.assertEqual(extra_field.status_code, 422)

    # 6. Legacy local activation must remain disabled until signed hosted activation ships.
    def test_e2e_legacy_local_license_activation_is_not_supported(self):
        email = "appsumo_buyer@example.com"
        response = self.client.post(
            "/api/license/activate",
            json={"email": email, "license_key": "AS-T1-ABCD-EF12-3456"},
        )

        self.assertEqual(response.status_code, 501)
        self.assertIn("online activation", response.json()["detail"].lower())

if __name__ == "__main__":
    unittest.main()
