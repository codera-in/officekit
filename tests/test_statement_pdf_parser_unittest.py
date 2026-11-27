"""Page-table joining must not turn repeated bank-statement headers into transactions."""

import unittest
import io
from types import SimpleNamespace
from unittest.mock import patch

from officekit.engines.engine_parser import (
    _extract_pdf_text_column_table,
    classify_columns,
    extract_pdf_page_tables,
    extract_pdf_statement_summary,
    flatten_statement_tables,
    parse_statement_table,
    statement_page_needs_ocr,
    statement_page_quality,
    verify_statement_against_pdf,
)


class StatementPdfTableJoinTests(unittest.TestCase):
    def test_abbreviated_withdrawal_deposit_headers_preserve_checked_rows(self):
        rows = [
            ["Date", "Narration", "Chq./Ref.No.", "ValueDt", "WithdrawalAmt.", "DepositAmt.", "ClosingBalance"],
            ["20/09/26", "Opening balance", "", "", "", "", "1000.00"],
            [
                "21/09/26 25/09/26 25/09/26 25/09/26",
                "FOREIGN INWARD REMITTANCE LONG BANK NARRATION",
                "REF12345678",
                "25/09/26",
                "",
                "",
                "",
            ],
            ["26/09/26", "MONTHLY SERVICE FEE", "", "26/09/26", "10.00", "", "990.00"],
        ]

        mapping = classify_columns(rows[0], rows[1:])
        result = parse_statement_table(rows)

        self.assertEqual(mapping, {"date": 0, "desc": 1, "debit": 4, "credit": 5, "balance": 6})
        self.assertEqual(result["transactions"][1]["debit"], 10.0)
        self.assertEqual(result["transactions"][1]["status"], "ok")
        self.assertEqual(result["excluded_rows"], [{"row_index": 2, "reason": "multiple_dates"}])
        self.assertEqual(result["reconciliation"]["status"], "partial")
        self.assertEqual(result["reconciliation"]["checked_rows"], 1)
        self.assertEqual(result["reconciliation"]["unverified_rows"], 1)

    def test_multi_date_extraction_row_is_not_exported_as_one_transaction(self):
        rows = [
            ["Date", "Description", "Debit", "Credit", "Balance"],
            [
                "21/09/26 25/09/26 25/09/26 25/09/26",
                "FOREIGN INWARD REMITTANCE TXN000000RO NETBANK",
                "-", "-", "-",
            ],
            ["24/09/26 25/09/26", "SECOND AMBIGUOUS TRANSFER", "-", "-", "-"],
            ["STATEMENT SUMMARY: -", "", "", "", ""],
            ["-", "OpeningBalanceDrCount CrCount Debits Credits ClosingBal", "", "", ""],
            ["26/09/26", "MONTHLY SERVICE FEE", "10.00", "", "990.00"],
        ]

        result = parse_statement_table(rows)

        self.assertEqual([item["date"] for item in result["transactions"]], ["26/09/26"])
        self.assertEqual(result["transactions"][0]["description"], "MONTHLY SERVICE FEE")
        self.assertEqual(result["excluded_rows"], [
            {"row_index": 1, "reason": "multiple_dates"},
            {"row_index": 2, "reason": "multiple_dates"},
        ])
        self.assertEqual(result["raw_rows"], rows)

    def test_page_quality_distinguishes_empty_complete_and_merged_vector_tables(self):
        merged = [[
            "Date", "Description", "Debit", "Credit", "Balance",
        ], ["01/01/2026 02/01/2026", "Opening balance Coffee Shop", "", "", ""]]
        complete = [
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["01/01/2026", "Opening balance", "", "", "1000.00"],
            ["02/01/2026", "Coffee Shop", "25.00", "", "975.00"],
        ]

        self.assertEqual(statement_page_quality([]), (0, 0))
        self.assertTrue(statement_page_needs_ocr([]))
        self.assertTrue(statement_page_needs_ocr([merged]))
        self.assertFalse(statement_page_needs_ocr([complete]))
        self.assertEqual(statement_page_quality([complete])[0] > statement_page_quality([merged])[0], True)

    def test_page_quality_counts_row_evidence_without_repeating_header_baselines(self):
        first = [["Date", "Description", "Amount"], ["2026-01-01", "Opening", "100.00"]]
        second = [["Date", "Description", "Amount"], ["2026-01-02", "Purchase", "5.00"]]
        original = [first, second]

        first_quality = statement_page_quality([first])
        second_quality = statement_page_quality([second])
        combined_quality = statement_page_quality(original)

        self.assertEqual(combined_quality, (first_quality[0] + 23, first_quality[1] + second_quality[1]))
        self.assertEqual(original, [first, second])

    def test_page_without_a_recognizable_date_column_needs_ocr(self):
        self.assertTrue(statement_page_needs_ocr([
            [["Description", "Amount"], ["Coffee Shop", "25.00"]],
            [["Account", "Balance"], ["Checking", "100.00"]],
        ]))

    def test_page_without_statement_headers_needs_ocr(self):
        self.assertTrue(statement_page_needs_ocr([
            [["Column A", "Column B"], ["unrelated", "content"]],
        ]))

    def test_page_with_multiple_date_tokens_and_numeric_values_needs_ocr(self):
        self.assertTrue(statement_page_needs_ocr([[
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["2026-01-02", "2026-01-03 Coffee Shop", "25.00", "", "975.00"],
        ]]))

    def test_separate_value_date_column_does_not_trigger_recovery_ocr(self):
        self.assertFalse(statement_page_needs_ocr([[
            ["Date", "Description", "Reference", "ValueDt", "Debit", "Credit", "Balance"],
            [
                "21/09/26", "FOREIGN INWARD REMITTANCE TXN000000RO", "50100000000001",
                "25/09/26", "", "1,718,697.40", "1,737,613.76",
            ],
            [
                "25/09/26", "NEFT TRANSFER", "50100244908374", "25/09/26",
                "200,000.00", "", "1,537,613.76",
            ],
        ]]))

    def test_page_with_one_valid_date_but_no_financial_value_needs_ocr(self):
        self.assertTrue(statement_page_needs_ocr([[
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["2026-01-02", "Coffee Shop", "", "", ""],
        ]]))

    def test_complete_table_does_not_hide_a_weak_table_on_the_same_page(self):
        complete = [
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["2026-01-02", "Opening balance", "", "", "1000.00"],
            ["2026-01-03", "Coffee Shop", "25.00", "", "975.00"],
        ]
        weak = [
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["2026-01-04 2026-01-05", "Merged transfer rows", "", "", ""],
        ]

        self.assertTrue(statement_page_needs_ocr([complete, weak]))

    def test_multiple_complete_tables_do_not_trigger_recovery_ocr(self):
        first = [
            ["Date", "Description", "Amount", "Balance"],
            ["2026-01-02", "Opening balance", "", "1000.00"],
            ["2026-01-03", "Coffee Shop", "25.00", "975.00"],
        ]
        second = [
            ["Date", "Description", "Amount", "Balance"],
            ["2026-01-04", "Grocery Store", "50.00", "925.00"],
        ]

        self.assertFalse(statement_page_needs_ocr([first, second]))

    def test_repeated_header_is_removed_after_initial_metadata_and_whitespace_variation(self):
        tables = [
            [
                ["Account statement", ""],
                ["Date", "Description", "Deposit", "Balance"],
                ["2024-01-01", "Opening balance", "", "1000.00"],
            ],
            [
                [" Date ", "Description", "Deposit", " Balance "],
                ["2024-01-02", "Client payment", "50.00", "1050.00"],
            ],
        ]

        rows = flatten_statement_tables(tables)

        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[1], ["Date", "Description", "Deposit", "Balance"])
        self.assertEqual(rows[-1][1], "Client payment")

    def test_distinct_section_headers_and_all_data_rows_are_preserved(self):
        tables = [
            [["Date", "Description", "Amount"], ["2024-01-01", "Payment", "10.00"]],
            [["Date", "Description", "Balance"], ["2024-01-02", "Closing", "90.00"]],
        ]

        rows = flatten_statement_tables(tables)

        self.assertEqual(rows, [
            ["Date", "Description", "Amount"],
            ["2024-01-01", "Payment", "10.00"],
            ["Date", "Description", "Balance"],
            ["2024-01-02", "Closing", "90.00"],
        ])

    def test_empty_tables_produce_no_rows(self):
        self.assertEqual(flatten_statement_tables([]), [])

    def test_undated_statement_summary_and_balance_count_rows_are_not_transactions(self):
        rows = [
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["2025-01-01", "Opening balance", "", "", "1000.00"],
            ["", "STATEMENT SUMMARY: -", "", "", ""],
            ["", "OpeningBalanceDrCount CrCount Debits Credits ClosingBal", "", "", ""],
            ["2025-01-02", "Client payment", "", "250.00", "1250.00"],
        ]

        result = parse_statement_table(rows)

        self.assertEqual(len(result["transactions"]), 2)
        self.assertEqual([item["description"] for item in result["transactions"]], ["Opening balance", "Client payment"])
        self.assertEqual(result["reconciliation"]["status"], "verified")


class UnruledStatementPdfTests(unittest.TestCase):
    def test_small_positioned_word_gaps_remain_separate_in_statement_narration(self):
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase.pdfmetrics import stringWidth

        output = io.BytesIO()
        page = canvas.Canvas(output, pagesize=letter)
        page.setFont("Helvetica", 9)
        for x, label in ((40, "Date"), (140, "Description"), (350, "Debit"), (420, "Credit"), (490, "Balance")):
            page.drawString(x, 720, label)
        page.drawString(40, 700, "21/09/26")

        def draw_positioned_words(words, x, y):
            for word in words:
                page.drawString(x, y, word)
                x += stringWidth(word, "Helvetica", 9) + 1.5

        draw_positioned_words(["FOREIGN", "INR", "PACB", "INW-TXN000000R0-ORBITX"], 140, 700)
        draw_positioned_words(["NETWORK", "GROUP", "PTE", "LTD-SKYDO"], 140, 680)
        page.drawString(420, 700, "25.00")
        page.drawString(490, 700, "1025.00")
        page.save()

        page_tables = extract_pdf_page_tables(output.getvalue())
        rows = flatten_statement_tables([table for tables in page_tables for table in tables])
        result = parse_statement_table(rows)

        self.assertEqual(len(result["transactions"]), 1, rows)
        self.assertEqual(
            result["transactions"][0]["description"],
            "FOREIGN INR PACB INW-TXN000000R0-ORBITX NETWORK GROUP PTE LTD-SKYDO",
        )
        self.assertEqual(result["transactions"][0]["credit"], 25.0)

    def test_real_vector_pdf_keeps_long_transfer_rows_separate_from_undated_summary(self):
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        output = io.BytesIO()
        page = canvas.Canvas(output, pagesize=letter)
        page.setFont("Helvetica", 9)
        for x, label in ((40, "Date"), (140, "Description"), (350, "Debit"), (420, "Credit"), (490, "Balance")):
            page.drawString(x, 740, label)

        page.drawString(40, 716, "21/09/26")
        page.drawString(140, 716, "Opening balance")
        page.drawString(490, 716, "1,000.00")

        page.drawString(40, 696, "25/09/26")
        page.drawString(140, 696, "FOREIGN INWARD REMITTANCE")
        page.drawString(140, 676, "TXN000000RO ORBITX NETWORK GROUP")
        page.drawString(140, 656, "SKYDO NETFDR UTI0004034 JENNIFER")
        page.drawString(140, 636, "ANDERSSON NETBANK MUM HDFC")
        page.drawString(420, 696, "25.00")
        page.drawString(490, 696, "1,025.00")

        page.drawString(40, 616, "26/09/26")
        page.drawString(140, 616, "MONTHLY SERVICE FEE")
        page.drawString(350, 616, "10.00")
        page.drawString(490, 616, "1,015.00")

        page.drawString(40, 570, "STATEMENT SUMMARY: -")
        page.drawString(140, 550, "OpeningBalanceDrCount CrCount Debits Credits ClosingBal")
        page.save()

        import pdfplumber

        with pdfplumber.open(io.BytesIO(output.getvalue())) as pdf:
            words = pdf.pages[0].extract_words(x_tolerance=2, y_tolerance=3, use_text_flow=False)
            coordinate_table = _extract_pdf_text_column_table(pdf.pages[0])
        self.assertTrue(coordinate_table)
        self.assertIn("TXN000000RO", " ".join(coordinate_table[2]), repr([(word["x0"], word["top"], word["text"]) for word in words]))

        page_tables = extract_pdf_page_tables(output.getvalue())
        rows = flatten_statement_tables([table for tables in page_tables for table in tables])
        result = parse_statement_table(rows)

        self.assertEqual(len(result["transactions"]), 3, rows)
        self.assertEqual(result["transactions"][1]["date"], "25/09/26")
        self.assertEqual(
            result["transactions"][1]["description"],
            "FOREIGN INWARD REMITTANCE TXN000000RO ORBITX NETWORK GROUP SKYDO NETFDR UTI0004034 JENNIFER ANDERSSON NETBANK MUM HDFC",
        )
        self.assertEqual(result["transactions"][1]["credit"], 25.0)
        self.assertEqual(result["transactions"][2]["debit"], 10.0)
        self.assertEqual(result["reconciliation"]["status"], "verified")

    def test_extracts_aligned_columns_and_joins_wrapped_description_lines(self):
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        output = io.BytesIO()
        page = canvas.Canvas(output, pagesize=letter)
        page.setFont("Helvetica", 9)
        page.drawString(40, 750, "Account activity")
        for x, label in ((40, "Transaction Date"), (140, "Particulars"), (350, "Withdrawals"), (420, "Deposits"), (490, "Running Balance")):
            page.drawString(x, 720, label)
        page.drawString(40, 700, "2025-01-01")
        page.drawString(140, 700, "Opening balance")
        page.drawString(490, 700, "1000.00")
        page.drawString(40, 680, "2025-01-02")
        page.drawString(140, 680, "FOREIGN TRANSFER VIA")
        page.drawString(140, 668, "INTERNATIONAL CLEARING")
        page.drawString(420, 680, "250.00")
        page.drawString(490, 680, "1250.00")
        page.drawString(40, 648, "2025-01-03")
        page.drawString(140, 648, "MONTHLY SERVICE FEE")
        page.drawString(350, 648, "10.00")
        page.drawString(490, 648, "1240.00")
        page.drawString(40, 610, "STATEMENT SUMMARY")
        page.drawString(140, 610, "Opening balance 1000.00 Closing balance 1240.00")
        page.drawString(140, 590, "For assistance contact Customer Care")
        page.save()

        page_tables = extract_pdf_page_tables(output.getvalue())
        rows = flatten_statement_tables([table for tables in page_tables for table in tables])
        result = parse_statement_table(rows)

        self.assertEqual(len(result["transactions"]), 3, rows)
        self.assertEqual(result["transactions"][1]["description"], "FOREIGN TRANSFER VIA INTERNATIONAL CLEARING")
        self.assertEqual(result["transactions"][1]["credit"], 250.0)
        self.assertEqual(result["transactions"][2]["debit"], 10.0)
        self.assertEqual(result["reconciliation"]["status"], "verified")

    def test_coordinate_table_replaces_a_lower_quality_merged_extraction(self):
        class FakePage:
            def extract_tables(self):
                return [[
                    ["Date", "Description", "Debit", "Credit", "Balance"],
                    ["2025-01-02 2025-01-03", "MERGED TRANSFER AND FEE", "", "", ""],
                ]]

            def extract_words(self, **_options):
                entries = [
                    (40, 100, "Transaction"), (100, 100, "Date"), (160, 100, "Particulars"),
                    (350, 100, "Withdrawals"), (420, 100, "Deposits"),
                    (490, 100, "Running"), (535, 100, "Balance"),
                    (40, 120, "2025-01-01"), (160, 120, "Opening"), (200, 120, "balance"), (490, 120, "1000.00"),
                    (40, 140, "2025-01-02"), (160, 140, "FOREIGN"), (205, 140, "TRANSFER"),
                    (420, 140, "250.00"), (490, 140, "1250.00"),
                    (160, 152, "INTERNATIONAL"), (225, 152, "CLEARING"),
                    (40, 172, "2025-01-03"), (160, 172, "MONTHLY"), (200, 172, "FEE"),
                    (350, 172, "10.00"), (490, 172, "1240.00"),
                ]
                return [
                    {"x0": x, "x1": x + len(text) * 5, "top": top, "text": text}
                    for x, top, text in entries
                ]

        class FakePdf:
            pages = [FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch("officekit.engines.engine_parser.pdfplumber.open", return_value=FakePdf()):
            page_tables = extract_pdf_page_tables(b"synthetic pdf")

        extracted_rows = flatten_statement_tables([table for tables in page_tables for table in tables])
        result = parse_statement_table(extracted_rows)
        self.assertEqual(len(result["transactions"]), 3, extracted_rows)
        self.assertEqual(result["transactions"][1]["description"], "FOREIGN TRANSFER INTERNATIONAL CLEARING")
        self.assertEqual(result["transactions"][1]["credit"], 250.0)
        self.assertEqual(result["transactions"][2]["debit"], 10.0)

    def test_coordinate_table_keeps_reference_and_value_date_columns_from_shifting_amounts(self):
        class FakePage:
            def extract_tables(self):
                return [[
                    ["Date", "Narration", "Chq./Ref.No.", "ValueDt", "WithdrawalAmt.", "DepositAmt.", "ClosingBalance"],
                    ["21/09/26 25/09/26 25/09/26", "MERGED STATEMENT ROWS", "", "", "", "", ""],
                ]]

            def extract_words(self, **_options):
                entries = [
                    (40, 100, "Date"), (144, 100, "Narration"), (283, 100, "Chq./Ref.No."),
                    (360, 100, "ValueDt"), (405, 100, "Withdrawal"), (449, 100, "Amt."),
                    (491, 100, "DepositAmt."), (564, 100, "ClosingBalance"),
                    (33, 120, "01/09/26"), (72, 120, "Opening"), (114, 120, "balance"),
                    (362, 120, "01/09/26"), (584, 120, "1000.00"),
                    (33, 140, "02/09/26"), (72, 140, "CUSTOMER"), (114, 140, "PAYMENT"),
                    (290, 140, "000012345678"), (362, 140, "02/09/26"),
                    (506, 140, "50.00"), (584, 140, "1050.00"),
                    (33, 160, "03/09/26"), (72, 160, "MONTHLY"), (114, 160, "FEE"),
                    (290, 160, "000009876543"), (362, 160, "03/09/26"),
                    (434, 160, "10.00"), (584, 160, "1040.00"),
                ]
                return [
                    {"x0": x, "x1": x + len(text) * 5, "top": top, "text": text}
                    for x, top, text in entries
                ]

            def find_tables(self):
                bounds = (28.3, 67.7, 254.9, 356.9, 396.6, 474.5, 552.5, 630.8)
                header_cells = [
                    (bounds[index], 100, bounds[index + 1], 118)
                    for index in range(len(bounds) - 1)
                ]
                row = SimpleNamespace(cells=header_cells)
                return [SimpleNamespace(
                    rows=[row],
                    extract=lambda: [[
                        "Date", "Narration", "Chq./Ref.No.", "ValueDt",
                        "WithdrawalAmt.", "DepositAmt.", "ClosingBalance",
                    ]],
                )]

        class FakePdf:
            pages = [FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch("officekit.engines.engine_parser.pdfplumber.open", return_value=FakePdf()):
            page_tables = extract_pdf_page_tables(b"synthetic pdf")

        rows = flatten_statement_tables([table for tables in page_tables for table in tables])
        result = parse_statement_table(rows)

        self.assertEqual(len(result["transactions"]), 3, rows)
        self.assertEqual(result["transactions"][1]["credit"], 50.0)
        self.assertEqual(result["transactions"][1]["balance"], 1050.0)
        self.assertEqual(result["transactions"][2]["debit"], 10.0)
        self.assertEqual(result["transactions"][2]["balance"], 1040.0)
        self.assertEqual(result["reconciliation"]["status"], "verified")

    def test_coordinate_table_splits_merged_ddmmyy_dates_and_drops_summary_rows(self):
        class FakePage:
            def extract_tables(self):
                return [[
                    ["Date", "Description", "Debit", "Credit", "Balance"],
                    ["21/09/26 25/09/26 26/09/26", "OPENING BALANCE FOREIGN TRANSFER MONTHLY SERVICE FEE", "", "", ""],
                    ["", "STATEMENT SUMMARY: OpeningBalanceDrCount CrCount Debits Credits ClosingBal", "", "", ""],
                ]]

            def extract_words(self, **_options):
                entries = [
                    (40, 100, "Date"), (140, 100, "Description"), (350, 100, "Debit"),
                    (420, 100, "Credit"), (490, 100, "Balance"),
                    (40, 120, "21/09/26"), (140, 120, "Opening"), (180, 120, "balance"),
                    (490, 120, "1000.00"),
                    (40, 140, "25/09/26"), (140, 140, "FOREIGN"), (185, 140, "TRANSFER"),
                    (420, 140, "25.00"), (490, 140, "1025.00"),
                    (140, 160, "ORBITX"), (175, 160, "NETWORK"), (220, 160, "GROUP"),
                    (40, 180, "26/09/26"), (140, 180, "MONTHLY"), (190, 180, "SERVICE"),
                    (232, 180, "FEE"), (350, 180, "10.00"), (490, 180, "1015.00"),
                    (140, 220, "STATEMENT"), (205, 220, "SUMMARY:"),
                    (140, 240, "OpeningBalanceDrCount"), (275, 240, "CrCount"),
                    (320, 240, "Debits"), (370, 240, "Credits"), (420, 240, "ClosingBal"),
                ]
                return [
                    {"x0": x, "x1": x + len(text) * 5, "top": top, "text": text}
                    for x, top, text in entries
                ]

        class FakePdf:
            pages = [FakePage()]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with patch("officekit.engines.engine_parser.pdfplumber.open", return_value=FakePdf()):
            page_tables = extract_pdf_page_tables(b"synthetic pdf")

        rows = flatten_statement_tables([table for tables in page_tables for table in tables])
        result = parse_statement_table(rows)

        self.assertEqual(len(result["transactions"]), 3, rows)
        self.assertEqual([item["date"] for item in result["transactions"]], ["21/09/26", "25/09/26", "26/09/26"])
        self.assertEqual(result["transactions"][1]["description"], "FOREIGN TRANSFER ORBITX NETWORK GROUP")
        self.assertEqual(result["transactions"][1]["credit"], 25.0)
        self.assertEqual(result["transactions"][2]["debit"], 10.0)
        self.assertEqual(result["reconciliation"]["status"], "verified")

    def test_coordinate_table_keeps_description_wrapped_at_a_20_point_leading(self):
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        output = io.BytesIO()
        page = canvas.Canvas(output, pagesize=letter)
        page.setFont("Helvetica", 9)
        for x, label in ((40, "Date"), (140, "Description"), (350, "Debit"), (420, "Credit"), (490, "Balance")):
            page.drawString(x, 720, label)
        page.drawString(40, 700, "2025-01-01")
        page.drawString(140, 700, "Opening balance")
        page.drawString(490, 700, "1000.00")
        page.drawString(40, 680, "2025-01-02")
        page.drawString(140, 680, "FOREIGN TRANSFER")
        page.drawString(420, 680, "250.00")
        page.drawString(490, 680, "1250.00")
        page.drawString(140, 660, "NETWORK GROUP PAYMENT")
        page.drawString(40, 640, "2025-01-03")
        page.drawString(140, 640, "Card purchase")
        page.drawString(350, 640, "25.00")
        page.drawString(490, 640, "1225.00")
        page.save()

        page_tables = extract_pdf_page_tables(output.getvalue())

        rows = flatten_statement_tables([table for tables in page_tables for table in tables])
        result = parse_statement_table(rows)

        self.assertEqual(len(result["transactions"]), 3, rows)
        self.assertEqual(result["transactions"][1]["description"], "FOREIGN TRANSFER NETWORK GROUP PAYMENT")
        self.assertEqual(result["transactions"][1]["credit"], 250.0)
        self.assertEqual(result["transactions"][2]["description"], "Card purchase")

    def test_coordinate_table_does_not_merge_a_detached_note_beyond_the_leading_bound(self):
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        output = io.BytesIO()
        page = canvas.Canvas(output, pagesize=letter)
        page.setFont("Helvetica", 9)
        for x, label in ((40, "Date"), (140, "Description"), (350, "Debit"), (420, "Credit"), (490, "Balance")):
            page.drawString(x, 720, label)
        page.drawString(40, 700, "2025-01-01")
        page.drawString(140, 700, "Opening balance")
        page.drawString(490, 700, "1000.00")
        page.drawString(40, 680, "2025-01-02")
        page.drawString(140, 680, "Card purchase")
        page.drawString(350, 680, "25.00")
        page.drawString(490, 680, "975.00")
        page.drawString(140, 654, "Contact support for account help")
        page.save()

        page_tables = extract_pdf_page_tables(output.getvalue())
        rows = flatten_statement_tables([table for tables in page_tables for table in tables])
        result = parse_statement_table(rows)

        self.assertEqual(len(result["transactions"]), 2, rows)
        self.assertEqual(result["transactions"][1]["description"], "Card purchase")
        self.assertEqual(result["reconciliation"]["status"], "verified")

    def test_multi_page_pdf_with_summary_and_abbreviation_tables_filters_unrelated_tables(self):
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
        styles = getSampleStyleSheet()
        story = []

        # Page 1: Customer details & Account Summary table (no dates)
        story.append(Paragraph("PRIVATE & CONFIDENTIAL", styles["Normal"]))
        story.append(Paragraph("PRIYA RAMAN<br/>Anand Rao, 12 Example Street", styles["Normal"]))
        story.append(Spacer(1, 10))
        story.append(Paragraph("Summary of Account Statement Period 01-Sep-2026 to 30-Sep-2026", styles["Normal"]))
        summary_table = Table([
            ["Account Type", "Account No.", "Currency", "Account Balance", "Status", "Nomination Registered"],
            ["SAVINGS", "8726010000107907", "INR", "25,099.00", "ACTIVE", "YES"],
        ])
        summary_table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 1, colors.grey)]))
        story.append(summary_table)
        story.append(Paragraph("*** End of Summary ***", styles["Normal"]))
        story.append(PageBreak())

        # Page 2: Important Abbreviations legend table (no dates)
        story.append(Paragraph("Important Abbreviations", styles["Heading3"]))
        abbrev_table = Table([
            ["ATD", "Withdrawal at Non-DBS ATM", "ATW", "Withdrawal at DBS ATM", "PCD", "Purchased"],
            ["IB TRF", "Internet banking transfer", "MB TRF", "Mobile banking transfer", "AC TRF", "Account transfer"],
            ["POS", "Point of Sales", "TD", "Term Deposit", "UPI", "Unified Payment Interface"],
        ])
        abbrev_table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 1, colors.grey)]))
        story.append(abbrev_table)
        story.append(Spacer(1, 10))
        story.append(Paragraph("Taxes as per applicable guidelines. FATCA rules apply.", styles["Normal"]))
        story.append(PageBreak())

        # Page 3: Transaction Table with Opening Balance, transactions, and Closing Balance
        story.append(Paragraph("Account Name: PRIYA RAMAN", styles["Normal"]))
        story.append(Paragraph("Statement Period: 01-Sep-2026 To 30-Sep-2026 Currency: INR", styles["Normal"]))
        story.append(Spacer(1, 10))
        tx_table = Table([
            ["Transaction Date", "Value Date", "Details of transaction", "Debit", "Credit", "Balance"],
            ["", "", "Opening Balance", "", "", "25,000.00"],
            ["30-Sep-2026", "30-Sep-2026", "CREDIT INTEREST - Saving\n-8726010000107907", "", "99.00", "25,099.00"],
            ["", "", "Closing Balance", "", "", "25,099.00"],
        ])
        tx_table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 1, colors.black)]))
        story.append(tx_table)
        story.append(Spacer(1, 10))
        story.append(Paragraph("*** End of Statement ***", styles["Normal"]))

        doc.build(story)
        pdf_bytes = buf.getvalue()

        page_tables = extract_pdf_page_tables(pdf_bytes)
        self.assertEqual(len(page_tables), 3)
        self.assertEqual(len(page_tables[0]), 0, "Account summary must not be extracted as transaction table")
        self.assertEqual(len(page_tables[1]), 0, "Abbreviations legend must not be extracted as transaction table")
        self.assertEqual(len(page_tables[2]), 1, "Transaction table on page 3 must be extracted")

        rows = flatten_statement_tables([table for tables in page_tables for table in tables])
        result = parse_statement_table(rows)

        self.assertEqual(result["headers"], ["Transaction Date", "Value Date", "Details of transaction", "Debit", "Credit", "Balance"])
        self.assertEqual(result["column_mapping"], {"date": 0, "desc": 2, "debit": 3, "credit": 4, "balance": 5})
        self.assertEqual(len(result["transactions"]), 2)
        self.assertEqual(result["transactions"][0]["description"], "Opening Balance")
        self.assertEqual(result["transactions"][0]["status"], "baseline")
        self.assertEqual(result["transactions"][0]["balance"], 25000.0)
        self.assertEqual(result["transactions"][1]["date"], "30-Sep-2026")
        self.assertEqual(result["transactions"][1]["credit"], 99.0)
        self.assertEqual(result["transactions"][1]["balance"], 25099.0)
        self.assertEqual(result["transactions"][1]["status"], "ok")
        self.assertEqual(result["reconciliation"]["status"], "verified")
        self.assertEqual(result["reconciliation"]["valid"], True)

    def test_undated_closing_balance_and_boundary_markers_are_filtered_from_transactions(self):
        rows = [
            ["Transaction Date", "Details", "Debit", "Credit", "Balance"],
            ["", "Opening Balance", "", "", "5000.00"],
            ["05/10/2026", "Grocery Store", "150.00", "", "4850.00"],
            ["10/10/2026", "Salary Deposit", "", "2000.00", "6850.00"],
            ["", "Closing Balance", "", "", "6850.00"],
            ["", "*** End of Statement ***", "", "", ""],
        ]

        result = parse_statement_table(rows)

        self.assertEqual(len(result["transactions"]), 3)
        descriptions = [tx["description"] for tx in result["transactions"]]
        self.assertEqual(descriptions, ["Opening Balance", "Grocery Store", "Salary Deposit"])
        self.assertNotIn("Closing Balance", descriptions)
        self.assertNotIn("*** End of Statement ***", descriptions)
        self.assertEqual(result["reconciliation"]["status"], "verified")
        self.assertEqual(result["reconciliation"]["checked_rows"], 2)
        self.assertEqual(result["reconciliation"]["unverified_rows"], 0)


    def test_verify_statement_against_pdf_matches_summary_and_ledger_equations(self):
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=letter)
        styles = getSampleStyleSheet()
        story = [
            Paragraph("Bank Statement", styles["Heading1"]),
            Paragraph("Opening Balance: 1,000.00", styles["Normal"]),
            Paragraph("Total Debits: 150.00", styles["Normal"]),
            Paragraph("Total Credits: 500.00", styles["Normal"]),
            Paragraph("Closing Balance: 1,350.00", styles["Normal"]),
            Spacer(1, 10),
        ]
        tx_table = Table([
            ["Date", "Description", "Debit", "Credit", "Balance"],
            ["01/10/2026", "Grocery Store", "150.00", "", "850.00"],
            ["02/10/2026", "Consulting Fee", "", "500.00", "1,350.00"],
        ])
        tx_table.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 1, colors.black)]))
        story.append(tx_table)
        doc.build(story)
        pdf_bytes = buf.getvalue()

        summary = extract_pdf_statement_summary(pdf_bytes)
        self.assertEqual(summary["opening_balance"], 1000.0)
        self.assertEqual(summary["closing_balance"], 1350.0)
        self.assertEqual(summary["total_debits"], 150.0)
        self.assertEqual(summary["total_credits"], 500.0)

        transactions = [
            {"id": 1, "date": "01/10/2026", "description": "Grocery Store", "debit": 150.0, "credit": None, "balance": 850.0, "status": "ok"},
            {"id": 2, "date": "02/10/2026", "description": "Consulting Fee", "debit": None, "credit": 500.0, "balance": 1350.0, "status": "ok"},
        ]

        verification = verify_statement_against_pdf(transactions, pdf_bytes)
        self.assertEqual(verification["status"], "verified")
        self.assertTrue(verification["valid"])
        self.assertEqual(len(verification["unmatched_tokens"]), 0)
        for check in verification["checks"]:
            self.assertTrue(check["passed"], f"Check failed: {check}")


if __name__ == "__main__":
    unittest.main()

