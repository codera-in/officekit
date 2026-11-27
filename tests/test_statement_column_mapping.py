"""Regression tests for user-selected statement column mapping."""

import csv
import io
import json
import unittest

from fastapi.testclient import TestClient

from app import app
from officekit.engines.engine_parser import parse_statement_table


class StatementColumnMappingEngineTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            ["Value Date", "Transaction Date", "Narration", "Reference", "Debit", "Credit", "Closing Balance"],
            ["26/09/26", "25/09/26", "Coffee shop", "REF-1", "10.00", "", "990.00"],
            ["27/09/26", "26/09/26", "Salary", "REF-2", "", "20.00", "1010.00"],
        ]

    def test_manual_mapping_overrides_ambiguous_header_guesses_and_reconciles(self):
        result = parse_statement_table(
            self.rows,
            opening_balance=1000.0,
            column_mapping={
                "date": 1,
                "desc": 2,
                "debit": 4,
                "credit": 5,
                "balance": 6,
                "amount": None,
            },
        )

        self.assertEqual([row["date"] for row in result["transactions"]], ["25/09/26", "26/09/26"])
        self.assertEqual([row["description"] for row in result["transactions"]], ["Coffee shop", "Salary"])
        self.assertEqual([row["debit"] for row in result["transactions"]], [10.0, None])
        self.assertEqual([row["credit"] for row in result["transactions"]], [None, 20.0])
        self.assertEqual(result["reconciliation"]["status"], "verified")
        self.assertEqual(result["reconciliation"]["checked_rows"], 2)

    def test_mapping_rejects_unknown_missing_duplicate_and_out_of_range_columns(self):
        invalid_mappings = (
            [],
            {"date": 1, "desc": 2, "mystery": 3},
            {"date": 1},
            {"date": None, "desc": 2},
            {"date": 1, "desc": None},
            {"date": 1, "desc": 1},
            {"date": 1, "desc": 2, "balance": 99},
            {"date": True, "desc": 2},
            {"date": 1, "desc": 2, "debit": 4, "amount": 3},
        )
        for mapping in invalid_mappings:
            with self.subTest(mapping=mapping):
                with self.assertRaises(ValueError):
                    parse_statement_table(self.rows, column_mapping=mapping)


class StatementColumnMappingApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.csv_bytes = (
            "Value Date,Transaction Date,Narration,Reference,Debit,Credit,Closing Balance\r\n"
            "26/09/26,25/09/26,Coffee shop,REF-1,10.00,,990.00\r\n"
            "27/09/26,26/09/26,Salary,REF-2,,20.00,1010.00\r\n"
        ).encode()
        self.mapping = {
            "date": 1,
            "desc": 2,
            "debit": 4,
            "credit": 5,
            "amount": None,
            "balance": 6,
        }

    def test_multipart_reparse_applies_mapping_and_exports_the_mapped_rows(self):
        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement.csv", self.csv_bytes, "text/csv")},
            data={"column_mapping": json.dumps(self.mapping)},
        )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual([row["date"] for row in result["transactions"]], ["25/09/26", "26/09/26"])
        self.assertEqual(result["column_mapping"]["date"], 1)
        self.assertEqual(result["reconciliation"]["status"], "partial")
        self.assertEqual(result["reconciliation"]["checked_rows"], 1)

        export = self.client.post("/api/export/csv", json=result)
        self.assertEqual(export.status_code, 200, export.text)
        exported_rows = list(csv.DictReader(io.StringIO(export.text)))
        self.assertEqual([row["Date"] for row in exported_rows], ["25/09/26", "26/09/26"])
        self.assertEqual([row["Description"] for row in exported_rows], ["Coffee shop", "Salary"])

    def test_invalid_mapping_shape_semantics_and_json_are_422(self):
        invalid_mappings = (
            "not-json",
            '{"date": 0, "date": 1, "desc": 2}',
            json.dumps({"date": 1, "desc": 2, "extra": 3}),
            json.dumps({"date": True, "desc": 2}),
            json.dumps({"date": 1, "desc": 2, "debit": 4, "amount": 3}),
            json.dumps({"date": 1, "desc": 1}),
            json.dumps({"date": 1, "desc": 2, "balance": 99}),
        )
        for mapping in invalid_mappings:
            with self.subTest(mapping=mapping):
                response = self.client.post(
                    "/api/extract/statement",
                    files={"file": ("statement.csv", self.csv_bytes, "text/csv")},
                    data={"column_mapping": mapping},
                )
                self.assertEqual(response.status_code, 422, response.text)

    def test_oversized_mapping_is_rejected_by_multipart_validation(self):
        response = self.client.post(
            "/api/extract/statement",
            files={"file": ("statement.csv", self.csv_bytes, "text/csv")},
            data={"column_mapping": " " * 2049},
        )
        self.assertEqual(response.status_code, 422, response.text)


if __name__ == "__main__":
    unittest.main()
