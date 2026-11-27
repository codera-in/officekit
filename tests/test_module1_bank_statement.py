"""
TDD Tests for Module 1: Bank Statements & Financial Extraction
- Column classification
- Balance reconciliation verification & anomaly flagging
- Export to CSV, Excel, QBO (QuickBooks), OFX (Xero)
"""

import unittest
from officekit.engines.engine_parser import (
    parse_statement_table,
    export_to_csv,
    export_to_excel,
    export_to_qbo,
    export_to_ofx,
    clean_amount
)

class TestModule1BankStatementEngine(unittest.TestCase):

    def test_amount_cleaner_variations(self):
        self.assertEqual(clean_amount("$1,234.56"), 1234.56)
        self.assertEqual(clean_amount("(50.00)"), -50.00)
        self.assertEqual(clean_amount("100.00 CR"), 100.00)
        self.assertEqual(clean_amount("250.00 DR"), -250.00)
        self.assertEqual(clean_amount("-$75.25"), -75.25)
        self.assertEqual(clean_amount("DR $75.25"), -75.25)
        self.assertEqual(clean_amount("Andrew Pharmacy $75.25"), 75.25)
        self.assertIsNone(clean_amount("-"))
        self.assertIsNone(clean_amount("N/A"))

    def test_amount_cleaner_supports_unambiguous_comma_decimal_and_european_grouping(self):
        cases = {
            "1.234,56": 1234.56,
            "12.345.678,90": 12345678.90,
            "12,34,567.89": 1234567.89,
            "1,23,456.78": 123456.78,
            "1 234,56": 1234.56,
            "1\u00a0234,56": 1234.56,
            "1,23 CR": 1.23,
            "1,234.56": 1234.56,
            "(₹ 1,23,456.78)": -123456.78,
            "0,00": 0.0,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(clean_amount(value), expected)
        for malformed in ("1.23.45", "1,2,3", "12,3456", "1,,23", "1.234,"):
            with self.subTest(malformed=malformed):
                self.assertIsNone(clean_amount(malformed))

    def test_amount_cleaner_uses_explicit_locale_for_ambiguous_and_grouped_values(self):
        cases = (
            ("1,234", "auto", None),
            ("1.234", "auto", None),
            ("12.345", "auto", None),
            ("1234.567", "auto", 1234.567),
            ("1,234", "en-US", 1234.0),
            ("1.234", "en-US", 1.234),
            ("1.234", "de-DE", 1234.0),
            ("1,234", "de-DE", 1.234),
            ("1.234,56", "de-DE", 1234.56),
            ("1,234.56", "en-US", 1234.56),
            ("12,34,567.89", "en-IN", 1234567.89),
            ("₹ 1,23,456.78 CR", "en-IN", 123456.78),
            ("1\u202f234,56", "fr-FR", 1234.56),
            ("(1.234,56)", "de-DE", -1234.56),
        )
        for value, locale, expected in cases:
            with self.subTest(value=value, locale=locale):
                actual = clean_amount(value, locale)
                if expected is None:
                    self.assertIsNone(actual)
                else:
                    self.assertAlmostEqual(actual, expected)

    def test_amount_cleaner_rejects_wrong_locale_grouping_and_unknown_locales(self):
        for value, locale in (
            ("12,34.56", "en-US"),
            ("1,23,456.78", "en-US"),
            ("1.234,56", "en-US"),
            ("1 234,56", "de-DE"),
            ("12.34,56", "de-DE"),
            ("12,345,678.90", "en-IN"),
        ):
            with self.subTest(value=value, locale=locale):
                self.assertIsNone(clean_amount(value, locale))
        with self.assertRaisesRegex(ValueError, "number locale"):
            clean_amount("12.34", "xx-YY")

    def test_statement_date_normalization_requires_an_explicit_order_when_numeric_date_is_ambiguous(self):
        from officekit.engines.engine_parser import normalize_statement_date

        self.assertEqual(normalize_statement_date("01/02/2024"), "01/02/2024")
        self.assertEqual(normalize_statement_date("01/02/2024", "DMY"), "2024-02-01")
        self.assertEqual(normalize_statement_date("01/02/2024", "MDY"), "2024-01-02")
        self.assertEqual(normalize_statement_date("2024/02/01", "YMD"), "2024-02-01")
        self.assertEqual(normalize_statement_date("2024-02-29"), "2024-02-29")
        self.assertEqual(normalize_statement_date("2024-02-30"), "2024-02-30")
        self.assertEqual(normalize_statement_date("31/01/2024"), "2024-01-31")
        self.assertEqual(normalize_statement_date("01/31/2024"), "2024-01-31")
        self.assertEqual(normalize_statement_date("Feb 1, 2024"), "2024-02-01")
        self.assertEqual(normalize_statement_date("Feb 1 2024"), "2024-02-01")
        self.assertEqual(normalize_statement_date("1 February 2024"), "2024-02-01")
        self.assertEqual(normalize_statement_date("31/02/2024"), "31/02/2024")
        self.assertEqual(normalize_statement_date("01/02/24", "DMY"), "01/02/24")
        with self.assertRaisesRegex(ValueError, "date order"):
            normalize_statement_date("01/02/2024", [])

    def test_european_decimal_statement_reconciles_without_losing_minor_units(self):
        rows = [
            ["Date", "Description", "Credit", "Balance"],
            ["01/02/2024", "Opening balance", "", "1.000,00"],
            ["02/02/2024", "SEPA payment", "12,50", "1.012,50"],
        ]

        result = parse_statement_table(rows)

        self.assertTrue(result["reconciliation"]["valid"])
        self.assertEqual(result["reconciliation"]["status"], "verified")
        self.assertEqual(result["transactions"][1]["credit"], 12.5)
        self.assertEqual(result["transactions"][1]["balance"], 1012.5)

    def test_bank_statement_perfect_reconciliation(self):
        rows = [
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["2024-01-01", "Beginning Balance", "", "", "5000.00"],
            ["2024-01-05", "Client Retainer Deposit", "", "2500.00", "7500.00"],
            ["2024-01-08", "AWS Cloud Hosting", "150.00", "", "7350.00"],
            ["2024-01-12", "Office Supplies Store", "200.00", "", "7150.00"],
            ["2024-01-15", "Consulting Fee", "", "1000.00", "8150.00"]
        ]
        res = parse_statement_table(rows)
        self.assertTrue(res["reconciliation"]["valid"])
        self.assertEqual(res["reconciliation"]["discrepancies_count"], 0)
        self.assertEqual(len(res["transactions"]), 5)
        self.assertEqual(res["transactions"][0]["status"], "baseline")
        for tx in res["transactions"][1:]:
            self.assertEqual(tx["status"], "ok")
        self.assertEqual(res["reconciliation"]["status"], "verified")
        self.assertGreater(res["reconciliation"]["checked_rows"], 0)

    def test_summary_opening_balance_seeds_the_first_transaction_equation(self):
        rows = [
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["2026-01-02", "Client payment", "", "1000.00", "1010.00"],
            ["2026-01-03", "Bank fee", "1.00", "", "1009.00"],
        ]

        result = parse_statement_table(rows, opening_balance=10.0)

        self.assertEqual([item["status"] for item in result["transactions"]], ["ok", "ok"])
        self.assertEqual(result["reconciliation"]["checked_rows"], 2)
        self.assertTrue(result["reconciliation"]["valid"])

    def test_summary_opening_balance_must_be_a_finite_number(self):
        rows = [["Date", "Description", "Credit", "Balance"], ["2026-01-02", "Payment", "1", "1"]]

        for opening_balance in (True, float("nan"), float("inf"), "10.00"):
            with self.subTest(opening_balance=opening_balance):
                with self.assertRaisesRegex(ValueError, "finite number"):
                    parse_statement_table(rows, opening_balance=opening_balance)

    def test_bank_statement_detects_reconciliation_anomaly(self):
        rows = [
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["2024-01-01", "Beginning Balance", "", "", "1000.00"],
            ["2024-01-05", "Payment In", "", "500.00", "1500.00"],
            # Mismatch: should be 1200.00, but statement reports 1100.00 (missing $100)
            ["2024-01-10", "Utility Bill", "300.00", "", "1100.00"],
        ]
        res = parse_statement_table(rows)
        self.assertFalse(res["reconciliation"]["valid"])
        self.assertEqual(res["reconciliation"]["discrepancies_count"], 1)
        self.assertEqual(res["reconciliation"]["discrepancies"][0]["row_index"], 2)
        self.assertEqual(res["reconciliation"]["discrepancies"][0]["expected_balance"], 1200.00)
        self.assertEqual(res["reconciliation"]["discrepancies"][0]["reported_balance"], 1100.00)
        self.assertEqual(res["reconciliation"]["status"], "discrepancy")

    def test_empty_or_balance_free_input_is_unverified_not_successful(self):
        for rows in ([], [["Date", "Description"]], [
            ["Date", "Description", "Amount"],
            ["2024-01-01", "Client payment", "50.00"],
        ]):
            with self.subTest(rows=rows):
                result = parse_statement_table(rows)
                self.assertIsNone(result["reconciliation"]["valid"])
                self.assertEqual(result["reconciliation"]["status"], "unverified")
                self.assertEqual(result["reconciliation"]["checked_rows"], 0)

    def test_missing_transaction_amount_does_not_become_zero_during_reconciliation(self):
        rows = [
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["2024-01-01", "Opening balance", "", "", "100.00"],
            ["2024-01-02", "Unparsed transaction", "", "", "90.00"],
            ["2024-01-03", "Known transaction", "", "10.00", "100.00"],
        ]

        result = parse_statement_table(rows)

        self.assertIsNone(result["reconciliation"]["valid"])
        self.assertEqual(result["reconciliation"]["status"], "partial")
        self.assertEqual(result["reconciliation"]["checked_rows"], 1)
        self.assertEqual(result["reconciliation"]["unverified_rows"], 1)
        self.assertEqual(result["transactions"][0]["status"], "baseline")
        self.assertEqual(result["transactions"][1]["status"], "unverified")
        self.assertEqual(result["transactions"][2]["status"], "ok")

    def test_a_mismatch_remains_a_failure_even_when_another_row_is_unverified(self):
        rows = [
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["2024-01-01", "Opening balance", "", "", "100.00"],
            ["2024-01-02", "Unparsed transaction", "", "", "90.00"],
            ["2024-01-03", "Incorrect known transaction", "", "10.00", "99.00"],
        ]

        result = parse_statement_table(rows)

        self.assertFalse(result["reconciliation"]["valid"])
        self.assertEqual(result["reconciliation"]["status"], "discrepancy")
        self.assertEqual(result["reconciliation"]["checked_rows"], 1)
        self.assertEqual(result["reconciliation"]["unverified_rows"], 1)

    def test_missing_balance_breaks_the_equation_chain_until_a_new_baseline_exists(self):
        rows = [
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["2024-01-01", "Opening balance", "", "", "100.00"],
            ["2024-01-02", "Movement without balance", "5.00", "", ""],
            ["2024-01-03", "New observed balance", "", "20.00", "120.00"],
            ["2024-01-04", "Next movement", "10.00", "", "110.00"],
        ]

        result = parse_statement_table(rows)

        self.assertIsNone(result["reconciliation"]["valid"])
        self.assertEqual(result["reconciliation"]["status"], "partial")
        self.assertEqual(result["reconciliation"]["checked_rows"], 1)
        self.assertEqual(result["reconciliation"]["unverified_rows"], 2)
        self.assertEqual(
            [transaction["status"] for transaction in result["transactions"]],
            ["baseline", "unverified", "unverified", "ok"],
        )

    def test_qbo_export_is_unavailable_without_supported_institution_profile(self):
        transactions = [
            {"date": "2024-01-05", "description": "Client Deposit", "credit": 500.0, "debit": None, "balance": 1500.0},
            {"date": "2024-01-10", "description": "Office Supplies", "credit": None, "debit": 120.0, "balance": 1380.0}
        ]
        with self.assertRaisesRegex(ValueError, "supported QuickBooks financial-institution profile"):
            export_to_qbo(transactions, account_id="123456789")

    def test_ofx_xero_export(self):
        transactions = [
            {"date": "2024-01-05", "description": "Consulting Income", "credit": 1200.0, "debit": None, "balance": 2200.0}
        ]
        ofx_text = export_to_ofx(transactions)
        self.assertIn("<OFX>", ofx_text)
        self.assertIn("Consulting Income", ofx_text)
        self.assertIn("<TRNAMT>1200.0", ofx_text)

if __name__ == "__main__":
    unittest.main()
