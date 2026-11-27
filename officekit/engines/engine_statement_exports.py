"""CSV and XLSX serialization helpers for extracted statement transactions."""

import csv
import io
from typing import Any

from officekit.engines.engine_spreadsheet_safety import sanitize_spreadsheet_text


CSV_HEADERS = [
    "Date",
    "Description",
    "Debit (Withdrawal)",
    "Credit (Deposit)",
    "Balance",
    "Checksum Status",
]


def _empty_if_missing(value: Any) -> Any:
    return "" if value is None else value


def prepare_statement_export_rows(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map parser/API transactions to a shared, spreadsheet-safe export shape."""
    rows = []
    for transaction in transactions:
        rows.append({
            "Date": sanitize_spreadsheet_text(transaction.get("date", "")),
            "Description": sanitize_spreadsheet_text(transaction.get("description", "")),
            "Debit": transaction.get("debit"),
            "Credit": transaction.get("credit"),
            "Balance": transaction.get("balance"),
            "Checksum Status": sanitize_spreadsheet_text(transaction.get("status", "ok")),
        })
    return rows


def export_to_csv(transactions: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CSV_HEADERS)
    for row in prepare_statement_export_rows(transactions):
        writer.writerow([
            row["Date"],
            row["Description"],
            _empty_if_missing(row["Debit"]),
            _empty_if_missing(row["Credit"]),
            _empty_if_missing(row["Balance"]),
            row["Checksum Status"],
        ])
    return output.getvalue()


def export_to_excel(transactions: list[dict[str, Any]]) -> bytes:
    """Build an XLSX workbook, loading the optional spreadsheet dependency lazily."""
    import pandas as pd

    dataframe = pd.DataFrame(prepare_statement_export_rows(transactions), columns=[
        "Date", "Description", "Debit", "Credit", "Balance", "Checksum Status"
    ])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="Bank Statement")
    return output.getvalue()


def export_to_legacy_excel(transactions: list[dict[str, Any]]) -> bytes:
    """Build a bounded-compatible BIFF8 workbook for legacy spreadsheet apps."""
    import xlwt

    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Bank Statement")
    headers = ["Date", "Description", "Debit", "Credit", "Balance", "Checksum Status"]
    for column, value in enumerate(headers):
        sheet.write(0, column, value)
    for row_number, row in enumerate(prepare_statement_export_rows(transactions), start=1):
        values = [row["Date"], row["Description"], row["Debit"], row["Credit"], row["Balance"], row["Checksum Status"]]
        for column, value in enumerate(values):
            if value is not None:
                sheet.write(row_number, column, value)
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()
