"""Bounded extraction and spreadsheet export for selectable PDF tables."""

import csv
import io
import re
from typing import Any

import pdfplumber
from pdfminer.pdfparser import PDFSyntaxError
from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException

from officekit.engines.engine_spreadsheet_safety import sanitize_spreadsheet_text


class PdfTableInputError(ValueError):
    """The PDF is invalid or exceeds the supported table-extraction limits."""


class PdfTableExportError(ValueError):
    """The requested table or export format is not supported."""


MAX_PDF_BYTES = 64 * 1024 * 1024
MAX_PDF_PAGES = 50
MAX_PAGE_CHARACTERS = 20_000
MAX_DOCUMENT_CHARACTERS = 500_000
MAX_TABLES = 40
MAX_TABLE_ROWS = 2_000
MAX_TABLE_COLUMNS = 80
MAX_TOTAL_CELLS = 50_000
MAX_CELL_CHARACTERS = 8_000
MAX_TOTAL_CELL_CHARACTERS = 1_000_000
MAX_EXPORT_BYTES = 8 * 1024 * 1024
PREVIEW_ROWS = 12
DATE_TOKEN_RE = re.compile(
    r"\b(?:\d{1,4}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})\b"
)
DATE_CELL_RE = re.compile(rf"^(?:{DATE_TOKEN_RE.pattern})$")


def _reconstruct_collapsed_date_rows(page, table, source_rows: list[list[Any]]) -> list[list[str]]:
    """Split merged statement rows using the first date column and drawn grid."""
    header_index = None
    date_index = None
    for row_index, row in enumerate(source_rows[:5]):
        for cell_index, value in enumerate(row):
            token = re.sub(r"[^a-z]", "", str(value or "").casefold())
            if token in {"date", "transactiondate", "txndate", "transdate", "postingdate"}:
                header_index, date_index = row_index, cell_index
                break
        if date_index is not None:
            break
    if date_index is None or header_index is None:
        return []

    date_cell_values = [
        str(row[date_index] or "")
        for row in source_rows[header_index + 1:]
        if date_index < len(row)
    ]
    if not any(len(DATE_TOKEN_RE.findall(value)) > 1 for value in date_cell_values):
        return []

    try:
        header_cells = table.rows[header_index].cells
        date_cell_bounds = header_cells[date_index]
        if not date_cell_bounds:
            return []
        table_top, table_bottom = table.bbox[1], table.bbox[3]
        header_bottom = max(
            float(cell[3]) for cell in header_cells if cell is not None
        )
        column_bounds = [
            (float(cell[0]), float(cell[2])) if cell else None
            for cell in header_cells
        ]
        words = [
            word for word in page.extract_words(x_tolerance=1, y_tolerance=3, use_text_flow=False)
            if table_top <= float(word["top"]) < table_bottom
            and header_bottom - 1 <= float(word["top"])
            and float(word["bottom"]) <= table_bottom + 1
        ]
    except (AttributeError, IndexError, TypeError, ValueError):
        return []

    date_left, date_right = float(date_cell_bounds[0]), float(date_cell_bounds[2])
    anchors = sorted(
        (
            word for word in words
            if date_left <= (float(word["x0"]) + float(word["x1"])) / 2 < date_right
            and DATE_CELL_RE.fullmatch(str(word["text"]).strip())
        ),
        key=lambda word: (float(word["top"]), float(word["x0"])),
    )
    if len(anchors) < 2:
        return []

    last_anchor_top = float(anchors[-1]["top"])
    grid_left = min(left for left, _right in column_bounds if left is not None)
    grid_right = max(right for _left, right in column_bounds if right is not None)
    horizontal_boundaries = [
        float(edge["top"])
        for edge in page.edges
        if edge.get("orientation") == "h"
        and float(edge.get("x0", grid_left)) <= grid_left + 1
        and float(edge.get("x1", grid_right)) >= grid_right - 1
        and last_anchor_top < float(edge.get("top", table_bottom)) <= table_bottom + 1
    ]
    data_bottom = min(horizontal_boundaries) if horizontal_boundaries else table_bottom

    reconstructed = [
        [str(cell or "").strip() for cell in source_rows[header_index]]
    ]
    for anchor_index, anchor in enumerate(anchors):
        top = float(anchor["top"]) - 1
        bottom = (
            float(anchors[anchor_index + 1]["top"]) - 1
            if anchor_index + 1 < len(anchors)
            else data_bottom
        )
        cells = ["" for _ in column_bounds]
        line_groups: list[tuple[float, list[Any]]] = []
        for word in sorted(
            (word for word in words if top <= float(word["top"]) < bottom),
            key=lambda word: (float(word["top"]), float(word["x0"])),
        ):
            line = next(
                (line for line in reversed(line_groups) if abs(line[0] - float(word["top"])) <= 3),
                None,
            )
            if line is None:
                line = (float(word["top"]), [])
                line_groups.append(line)
            line[1].append(word)

        for line_top, line_words in line_groups:
            for column_index, bounds in enumerate(column_bounds):
                if bounds is None:
                    continue
                left, right = bounds
                matching = [
                    str(word["text"]) for word in sorted(line_words, key=lambda item: float(item["x0"]))
                    if left <= (float(word["x0"]) + float(word["x1"])) / 2 < right
                ]
                if matching:
                    cells[column_index] = " ".join((cells[column_index], " ".join(matching))).strip()
        cells[date_index] = str(anchor["text"]).strip()
        if any(cells):
            reconstructed.append(cells)

    return reconstructed if len(reconstructed) > 2 else []


def _extract_pdf_tables(pdf_bytes: bytes, *, include_export_rows: bool) -> dict[str, Any]:
    if not isinstance(pdf_bytes, bytes) or not 1 <= len(pdf_bytes) <= MAX_PDF_BYTES:
        raise PdfTableInputError("The PDF is empty or exceeds the supported size.")

    try:
        tables = []
        total_characters = 0
        total_cells = 0
        total_cell_characters = 0
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page_count = len(pdf.pages)
            if not 1 <= page_count <= MAX_PDF_PAGES:
                raise PdfTableInputError("Choose a PDF with 1 to 50 pages.")
            for page_number, page in enumerate(pdf.pages, start=1):
                page_characters = len(page.chars)
                total_characters += page_characters
                if page_characters > MAX_PAGE_CHARACTERS or total_characters > MAX_DOCUMENT_CHARACTERS:
                    raise PdfTableInputError("This PDF has too much selectable text to inspect safely.")

                source_tables = page.extract_tables() or []
                detected_tables = page.find_tables()
                for table_index, source_rows in enumerate(source_tables):
                    if not isinstance(source_rows, list) or not source_rows:
                        continue
                    if table_index < len(detected_tables):
                        reconstructed_rows = _reconstruct_collapsed_date_rows(
                            page, detected_tables[table_index], source_rows
                        )
                        if reconstructed_rows:
                            source_rows = reconstructed_rows
                    table_number = table_index + 1
                    if len(source_rows) > MAX_TABLE_ROWS:
                        raise PdfTableInputError("A PDF table exceeds the supported row limit.")

                    normalized_rows = []
                    width = 0
                    for source_row in source_rows:
                        if not isinstance(source_row, (list, tuple)):
                            raise PdfTableInputError("The PDF table structure is not supported.")
                        if len(source_row) > MAX_TABLE_COLUMNS:
                            raise PdfTableInputError("A PDF table exceeds the supported column limit.")
                        row = [str(cell or "").strip() for cell in source_row]
                        if any(len(cell) > MAX_CELL_CHARACTERS for cell in row):
                            raise PdfTableInputError("A PDF table cell exceeds the supported text limit.")
                        width = max(width, len(row))
                        normalized_rows.append(row)

                    normalized_rows = [row + [""] * (width - len(row)) for row in normalized_rows]
                    normalized_rows = [row for row in normalized_rows if any(cell for cell in row)]
                    if not normalized_rows:
                        continue
                    total_cells += len(normalized_rows) * width
                    total_cell_characters += sum(len(cell) for row in normalized_rows for cell in row)
                    if total_cells > MAX_TOTAL_CELLS:
                        raise PdfTableInputError("This PDF contains more table cells than OfficeKit can export safely.")
                    if total_cell_characters > MAX_TOTAL_CELL_CHARACTERS:
                        raise PdfTableInputError("This PDF contains more table text than OfficeKit can export safely.")
                    table = {
                        "page_number": page_number,
                        "table_number": table_number,
                        "row_count": len(normalized_rows),
                        "column_count": width,
                        "preview_rows": normalized_rows[:PREVIEW_ROWS],
                    }
                    if include_export_rows:
                        table["_rows"] = normalized_rows
                    tables.append(table)
                    if len(tables) > MAX_TABLES:
                        raise PdfTableInputError("This PDF contains more tables than OfficeKit can export safely.")
        return {"page_count": page_count, "tables": tables}
    except PdfTableInputError:
        raise
    except (PDFSyntaxError, MalformedPDFException, PdfminerException, OSError, ValueError):
        raise PdfTableInputError("This PDF could not be read. It may be damaged or password-protected.") from None


def extract_pdf_tables(pdf_bytes: bytes) -> dict[str, Any]:
    """Return selectable vector-text tables; scanned pages are intentionally not OCRed."""
    return _extract_pdf_tables(pdf_bytes, include_export_rows=False)


def export_pdf_table(pdf_bytes: bytes, page_number: int, table_number: int, export_format: str) -> tuple[bytes, str]:
    """Export one selected raw table without guessing headers or numeric types."""
    if export_format not in {"csv", "xls", "xlsx"}:
        raise PdfTableExportError("Choose CSV, XLS or XLSX export.")
    extracted = _extract_pdf_tables(pdf_bytes, include_export_rows=True)
    selected = next(
        (table for table in extracted["tables"]
         if table["page_number"] == page_number and table["table_number"] == table_number),
        None,
    )
    if selected is None:
        raise PdfTableExportError("The selected PDF table is unavailable. Preview the PDF again.")

    # Full table data stays on the local backend; the UI only sends its source
    # selection, never cells that could be forged or accidentally altered.
    rows = selected["_rows"]
    width = selected["column_count"]
    if export_format == "xls" and (len(rows) > 65_536 or width > 256):
        raise PdfTableExportError("The selected PDF table exceeds the legacy XLS row or column limit.")
    safe_rows = [
        [sanitize_spreadsheet_text(str(cell or "").strip()) for cell in row] + [""] * (width - len(row))
        for row in rows
    ]
    safe_rows = [row for row in safe_rows if any(row)]

    if export_format == "csv":
        output = io.StringIO(newline="")
        csv.writer(output, lineterminator="\r\n").writerows(safe_rows)
        content = output.getvalue().encode("utf-8-sig")
        media_type = "text/csv; charset=utf-8"
    elif export_format == "xlsx":
        try:
            from openpyxl import Workbook
            workbook = Workbook(write_only=True)
            sheet = workbook.create_sheet("PDF table")
            for row in safe_rows:
                sheet.append(row)
            output = io.BytesIO()
            workbook.save(output)
            content = output.getvalue()
        except Exception:
            raise PdfTableExportError("The selected PDF table could not be exported. Preview the PDF again.") from None
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        try:
            import xlwt

            workbook = xlwt.Workbook()
            sheet = workbook.add_sheet("PDF table")
            for row_index, row in enumerate(safe_rows):
                for column_index, value in enumerate(row):
                    sheet.write(row_index, column_index, value)
            output = io.BytesIO()
            workbook.save(output)
            content = output.getvalue()
        except Exception:
            raise PdfTableExportError("The selected PDF table could not be exported. Preview the PDF again.") from None
        media_type = "application/vnd.ms-excel"

    if not content or len(content) > MAX_EXPORT_BYTES:
        raise PdfTableExportError("The selected PDF table exceeds the supported export size.")
    return content, media_type
