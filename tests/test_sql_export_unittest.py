"""SQL export tests run without pandas or a database driver."""

import datetime as dt
import unittest
from decimal import Decimal

from officekit.engines.engine_sql_export import render_insert_script


class SqlExportTests(unittest.TestCase):
    def test_quotes_valid_identifiers_and_escapes_text(self):
        sql = render_insert_script(
            ["product", "description"],
            [("Mouse", "Bob's small mouse")],
            table_name="inventory",
        )
        self.assertEqual(
            sql,
            'INSERT INTO "inventory" ("product", "description") VALUES (\'Mouse\', \'Bob\'\'s small mouse\');',
        )

    def test_serializes_null_boolean_numeric_and_datetime_values(self):
        sql = render_insert_script(
            ["n", "flag", "missing", "amount", "created"],
            [(3, True, None, Decimal("12.30"), dt.date(2026, 10, 6))],
        )
        self.assertEqual(
            sql,
            'INSERT INTO "exported_table" ("n", "flag", "missing", "amount", "created") '
            "VALUES (3, TRUE, NULL, 12.30, '2026-10-06');",
        )

    def test_converts_nan_to_null_and_rejects_infinite_values(self):
        self.assertIn("VALUES (NULL);", render_insert_script(["value"], [(float("nan"),)]))
        for value in (float("inf"), float("-inf"), Decimal("Infinity")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                render_insert_script(["value"], [(value,)])

    def test_quotes_injection_shaped_and_human_readable_identifiers(self):
        sql = render_insert_script(
            ["product); DROP TABLE users;--", 'Customer "Name"'],
            [("Keyboard", "Ada")],
            table_name="inventory; DROP TABLE users",
        )
        self.assertEqual(
            sql,
            'INSERT INTO "inventory; DROP TABLE users" '
            '("product); DROP TABLE users;--", "Customer ""Name""") VALUES (\'Keyboard\', \'Ada\');',
        )

    def test_rejects_non_printable_oversized_or_duplicate_identifiers(self):
        for table, columns in (
            ("inventory\x00", ["name"]),
            ("inventory", ["bad\nname"]),
            ("inventory", ["x" * 129]),
            ("inventory", ["name", "Name"]),
        ):
            with self.subTest(table=table, columns=columns), self.assertRaises(ValueError):
                render_insert_script(columns, [("item",) * len(columns)], table_name=table)

    def test_rejects_nul_values_unsupported_cells_and_mismatched_rows(self):
        for columns, rows in (
            (["value"], [("bad\x00text",)]),
            (["value"], [([1, 2],)]),
            (["a", "b"], [(1,)]),
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                render_insert_script(columns, rows)

    def test_empty_rows_produce_no_sql_and_empty_columns_reject_values(self):
        self.assertEqual(render_insert_script(["id"], []), "")
        with self.assertRaises(ValueError):
            render_insert_script([], [(1,)])


if __name__ == "__main__":
    unittest.main()
