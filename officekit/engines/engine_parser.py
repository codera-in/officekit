"""
OmniConvert - Core Extraction Engine
Extracts tables, transactions, and structured data from:
- Native Text PDFs (pdfplumber)
- Images (PNG, JPG, TIFF, WebP) / Scanned Statements (pytesseract OCR)
- Tabular spreadsheets (CSV, Excel)
Includes automatic financial balance reconciliation check.
"""

import io
import re
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
import math
import sys
from PIL import Image
from officekit.engines.engine_statement_exports import export_to_csv, export_to_excel
from officekit.engines.engine_ocr import ImageTextRecognitionUnavailable, extract_image_text_rows
import officekit.engines.engine_macos_ocr as engine_macos_ocr
import officekit.engines.engine_rapidocr as engine_rapidocr

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

pytesseract = None


class StatementPdfReadError(ValueError):
    """A malformed or unreadable statement PDF, without parser details."""

    public_message = "The PDF could not be read. If it is password-protected, unlock it first."


def _load_pytesseract():
    global pytesseract
    if pytesseract is None:
        try:
            import pytesseract as pytesseract_module
        except ImportError:
            return None
        pytesseract = pytesseract_module
    return pytesseract


DATE_PATTERNS = [
    r'^\d{4}[-/.]\d{2}[-/.]\d{2}$',     # 2024-01-31
    r'^\d{2}[-/.]\d{2}[-/.]\d{4}$',     # 31/01/2024 or 01/31/2024
    r'^\d{2}[-/.]\d{2}[-/.]\d{2}$',       # 31/01/24
    r'^[A-Za-z]{3}\s+\d{1,2}(?:,?\s+\d{4})?$', # Jan 31, 2024
    r'^\d{1,2}\s+[A-Za-z]{3}(?:\s+\d{4})?$', # 31 Jan 2024
    r'^\d{1,2}[-/.][A-Za-z]{3,9}[-/.]\d{2,4}$', # 31-Jan-2024, 30-Sep-2026
]

SUPPORTED_NUMBER_LOCALES = frozenset(("auto", "en-US", "en-IN", "de-DE", "fr-FR"))
SUPPORTED_DATE_ORDERS = frozenset(("auto", "DMY", "MDY", "YMD"))
STATEMENT_DATE_TOKEN_RE = re.compile(
    r"\b(?:\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|"
    r"[A-Za-z]{3}\s+\d{1,2}(?:,?\s+\d{4})?|\d{1,2}\s+[A-Za-z]{3,9}(?:\s+\d{4})?)\b"
)


def normalize_statement_date(value: Any, date_order: str = "auto") -> str:
    """Normalize unambiguous dates and preserve ambiguous or invalid source text."""
    if not isinstance(date_order, str) or date_order not in SUPPORTED_DATE_ORDERS:
        raise ValueError("Unsupported statement date order")
    raw = "" if value is None else str(value)
    text = raw.strip()
    if not text:
        return raw

    for pattern in (
        "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%b %d, %Y", "%b %d %Y",
        "%B %d, %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y",
    ):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue

    year_first = re.fullmatch(r"(\d{4})([-/.])(\d{1,2})\2(\d{1,2})", text)
    if year_first:
        try:
            return datetime.strptime(text, f"%Y{year_first.group(2)}%m{year_first.group(2)}%d").date().isoformat()
        except ValueError:
            return raw

    day_month_year = re.fullmatch(r"(\d{1,2})([-/.])(\d{1,2})\2(\d{4})", text)
    if not day_month_year:
        return raw

    first, separator, second, year = day_month_year.groups()
    selected_order = date_order
    if selected_order == "auto":
        first_number, second_number = int(first), int(second)
        if first_number > 12 >= second_number:
            selected_order = "DMY"
        elif second_number > 12 >= first_number:
            selected_order = "MDY"
        else:
            return raw
    if selected_order == "YMD":
        return raw

    month, day = (second, first) if selected_order == "DMY" else (first, second)
    try:
        return datetime.strptime(f"{year}-{int(month):02d}-{int(day):02d}", "%Y-%m-%d").date().isoformat()
    except ValueError:
        return raw


def clean_amount(val: Any, number_locale: str = "auto") -> Optional[float]:
    """Normalize statement amounts using explicit conventions or conservative auto mode."""
    if not isinstance(number_locale, str) or number_locale not in SUPPORTED_NUMBER_LOCALES:
        raise ValueError("Unsupported statement number locale")
    if val is None or val.__class__.__name__ in {'NAType', 'NaTType'}:
        return None
    try:
        if math.isnan(val):
            return None
    except (TypeError, ValueError, OverflowError):
        pass
    s = str(val).strip()
    if not s or s.lower() in ('-', 'none', 'null', 'n/a'):
        return None
    
    is_negative = False
    if s.startswith('(') and s.endswith(')'):
        is_negative = True
        s = s[1:-1]
    elif s.endswith('-'):
        is_negative = True
        s = s[:-1]
    elif s.startswith('-'):
        is_negative = True
        s = s[1:]
    elif re.search(r'\bdr\b', s, re.IGNORECASE):
        is_negative = True
    
    # Keep decimal/group separators long enough to distinguish locale rules.
    s = re.sub(r'[^\d.,\s]', '', s).strip()
    if not s or not re.search(r'\d', s):
        return None

    def valid_thousands_groups(groups):
        if not groups or not all(group.isdigit() for group in groups):
            return False
        western = 1 <= len(groups[0]) <= 3 and all(len(group) == 3 for group in groups[1:])
        indian = (
            1 <= len(groups[0]) <= 2 and len(groups[-1]) == 3 and
            all(len(group) == 2 for group in groups[1:-1])
        )
        return western or indian

    if number_locale != "auto":
        decimal_separator, grouping_separator, grouping_style = {
            "en-US": (".", ",", "western"),
            "en-IN": (".", ",", "indian"),
            "de-DE": (",", ".", "western"),
            "fr-FR": (",", "space", "western"),
        }[number_locale]

        def valid_locale_groups(groups):
            if not groups or not all(group.isdigit() for group in groups):
                return False
            if grouping_style == "indian":
                return 1 <= len(groups[0]) <= 2 and len(groups[-1]) == 3 and all(
                    len(group) == 2 for group in groups[1:-1]
                )
            return 1 <= len(groups[0]) <= 3 and all(len(group) == 3 for group in groups[1:])

        group_pattern = r"[ \u00a0\u202f]" if grouping_separator == "space" else re.escape(grouping_separator)
        has_grouping = bool(re.search(group_pattern, s)) if grouping_separator == "space" else grouping_separator in s
        if decimal_separator in s:
            if s.count(decimal_separator) != 1:
                return None
            whole, fraction = s.rsplit(decimal_separator, 1)
            if not fraction.isdigit() or not whole:
                return None
        else:
            whole, fraction = s, None

        if has_grouping:
            groups = re.split(group_pattern, whole)
            if not valid_locale_groups(groups):
                return None
            whole_digits = "".join(groups)
        else:
            if not whole.isdigit():
                return None
            whole_digits = whole
        normalized = whole_digits if fraction is None else whole_digits + "." + fraction
        try:
            num = float(normalized)
            if not math.isfinite(num):
                return None
            return -num if is_negative else num
        except ValueError:
            return None

    # Automatic mode preserves values whose separator can be either decimal or grouping punctuation.
    s = re.sub(r"\s+", "", s)
    if ',' in s and '.' in s:
        decimal_separator = ',' if s.rfind(',') > s.rfind('.') else '.'
        grouping_separator = '.' if decimal_separator == ',' else ','
        whole, fraction = s.rsplit(decimal_separator, 1)
        if not fraction.isdigit() or not whole:
            return None
        groups = whole.split(grouping_separator)
        if grouping_separator in whole:
            if not valid_thousands_groups(groups):
                return None
        elif not whole.isdigit():
            return None
        normalized = ''.join(groups) + '.' + fraction
    elif ',' in s or '.' in s:
        separator = ',' if ',' in s else '.'
        if s.count(separator) > 1:
            groups = s.split(separator)
            if not valid_thousands_groups(groups):
                return None
            normalized = ''.join(groups)
        else:
            whole, fraction = s.split(separator, 1)
            if not whole.isdigit() or not fraction.isdigit():
                return None
            # In automatic mode a single separator followed by three digits can
            # be either a decimal value or a grouped integer (for example,
            # 1.234 means 1.234 or 1,234 depending on locale). Preserve that
            # ambiguity instead of silently changing a financial amount.
            if len(fraction) == 3 and valid_thousands_groups([whole, fraction]):
                return None
            elif separator == ',' and len(fraction) > 2:
                return None
            else:
                normalized = whole + '.' + fraction
    else:
        normalized = s
    try:
        num = float(normalized)
        if not math.isfinite(num):
            return None
        return -num if is_negative else num
    except ValueError:
        return None


def is_date(val: Any) -> bool:
    if not val:
        return False
    s = str(val).strip()
    for pattern in DATE_PATTERNS:
        if re.search(pattern, s, re.IGNORECASE):
            return True
    return False


def classify_columns(headers: List[str], sample_rows: List[List[Any]]) -> Dict[str, int]:
    """
    Intelligently map table columns to standard financial keys:
    - date_idx
    - desc_idx
    - debit_idx (withdrawal)
    - credit_idx (deposit)
    - amount_idx (combined amount)
    - balance_idx
    """
    mapping = {}
    lower_headers = [str(h).strip().lower() for h in headers]

    for idx, h in enumerate(lower_headers):
        tokens = set(re.findall(r'\b[a-z]+\b', h))
        if any(w in h for w in ['description', 'particulars', 'narrative', 'details', 'payee', 'memo']):
            if 'desc' not in mapping:
                mapping['desc'] = idx
        elif any(w in h for w in ['date', 'txn date', 'trans date', 'value date']):
            if 'date' not in mapping:
                mapping['date'] = idx
        elif any(w in h for w in ['balance', 'running bal', 'bal']):
            if 'balance' not in mapping:
                mapping['balance'] = idx
        elif any(
            token in {'debit', 'dr', 'outflow'} or token.startswith('withdrawal')
            for token in tokens
        ) or any(w in h for w in ['paid out', 'spent']):
            if 'debit' not in mapping:
                mapping['debit'] = idx
        elif any(
            token in {'credit', 'cr', 'inflow'} or token.startswith('deposit')
            for token in tokens
        ) or any(w in h for w in ['paid in', 'received']):
            if 'credit' not in mapping:
                mapping['credit'] = idx
        elif any(w in h for w in ['amount', 'txn amount', 'total']):
            if 'amount' not in mapping and 'debit' not in mapping and 'credit' not in mapping:
                mapping['amount'] = idx

    # Fallback to column contents if headers are generic (e.g. col_0, col_1)
    if 'date' not in mapping and sample_rows:
        for col_idx in range(len(headers)):
            col_vals = [r[col_idx] for r in sample_rows if col_idx < len(r)]
            if sum(1 for v in col_vals if is_date(v)) >= max(1, len(col_vals) * 0.4):
                mapping['date'] = col_idx
                break

    if 'desc' not in mapping:
        # Longest text column usually
        longest_idx = -1
        max_avg_len = 0
        for col_idx in range(len(headers)):
            if col_idx in mapping.values():
                continue
            col_vals = [str(r[col_idx]) for r in sample_rows if col_idx < len(r)]
            avg_len = sum(len(v) for v in col_vals) / max(1, len(col_vals))
            if avg_len > max_avg_len:
                max_avg_len = avg_len
                longest_idx = col_idx
        if longest_idx >= 0:
            mapping['desc'] = longest_idx

    return mapping


def _is_undated_statement_summary(row: List[Any]) -> bool:
    text = " ".join(str(cell or "") for cell in row).casefold()
    compact = re.sub(r"[^a-z0-9]", "", text)
    if not compact:
        return True
    if any(marker in compact for marker in (
        "statementsummary",
        "summaryoftransactions",
        "transactionsummary",
        "endofstatement",
        "endofsummary",
        "endofreport",
        "closingbalance",
        "closingbal",
    )):
        return True
    if (
        "count" in compact
        and "debit" in compact
        and "credit" in compact
        and ("openingbalance" in compact or "closingbalance" in compact)
    ):
        return True
    if (
        "total" in compact
        and any(m in compact for m in ("debit", "credit", "withdrawal", "deposit", "count", "turnover"))
    ):
        return True
    if re.search(r"^page\d+(?:of\d+)?$", compact):
        return True
    return False


def _header_row_score(row: List[Any]) -> int:
    """Score how strongly a row resembles a statement transaction header."""
    lower_cells = [str(c or "").strip().lower() for c in row if str(c or "").strip()]
    if not lower_cells:
        return 0
    score = 0
    has_date = False
    for cell in lower_cells:
        tokens = set(re.findall(r"\b[a-z]+\b", cell))
        if any(w in cell for w in ("txn date", "trans date", "transaction date", "value date", "posting date")) or "date" in tokens or "dates" in tokens:
            score += 15
            has_date = True
        elif any(w in cell for w in ("description", "particulars", "narration", "narrative", "details", "payee", "memo", "remarks")):
            score += 10
        elif any(t in {"debit", "dr", "outflow"} or t.startswith("withdrawal") for t in tokens) or any(w in cell for w in ("paid out", "spent")):
            score += 10
        elif any(t in {"credit", "cr", "inflow"} or t.startswith("deposit") for t in tokens) or any(w in cell for w in ("paid in", "received")):
            score += 10
        elif any(w in cell for w in ("balance", "bal", "running balance", "closing balance")):
            score += 5
        elif any(w in cell for w in ("amount", "total")):
            score += 5
    if not has_date:
        return min(score, 5)
    return score


def is_statement_candidate_table(table: List[List[str]]) -> bool:
    """Return True if a table has structure or rows consistent with statement transactions."""
    if not table or len(table) < 2:
        return False

    for row in table[:5]:
        if not row or not any(row):
            continue
        if _header_row_score(row) >= 15:
            return True

    dated_rows = 0
    for row in table:
        cells = [str(c or "").strip() for c in row if str(c or "").strip()]
        if any(is_date(c) for c in cells) and any(_is_statement_amount_text(c) for c in cells):
            dated_rows += 1
            if dated_rows >= 2:
                return True

    if dated_rows >= 1 and len(table) <= 6:
        return True

    return False


def pdf_page_has_selectable_text(pdf_bytes: bytes, page_index: int) -> bool:
    """Return True if the specified PDF page contains substantial selectable vector text."""
    if not pdfplumber:
        return False
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if 0 <= page_index < len(pdf.pages):
                text = pdf.pages[page_index].extract_text() or ""
                words = re.findall(r"\b[A-Za-z]{2,}\b", text)
                return len(words) >= 6 and len(text.strip()) >= 40
    except Exception:
        pass
    return False



def _is_statement_amount_text(value: Any) -> bool:
    """Distinguish numeric amount cells from narration/reference spillover."""
    text = str(value or "").strip()
    if clean_amount(text) is None:
        return False
    without_currency = re.sub(r"(?i)\b(?:dr|cr|rs|[a-z]{3})\b", "", text)
    return not re.search(r"[A-Za-z]", without_currency) and bool(re.search(r"\d", without_currency))


def extract_tables_from_pdf(pdf_bytes: bytes) -> List[List[List[str]]]:
    """Extract raw tables across all pages in a vector PDF."""
    return [table for page_tables in extract_pdf_page_tables(pdf_bytes) for table in page_tables]


def _extract_pdf_text_column_table(page, use_table_cells: bool = True) -> List[List[str]]:
    """Recover an aligned, unruled statement table from PDF word coordinates."""
    try:
        # Bank statements often omit literal space glyphs between positioned
        # words. A wider tolerance joins those words into a single token, which
        # then hides narration boundaries in the transaction description.
        # Bank statements often omit literal space glyphs between positioned
        # words. A wider tolerance joins those words into a single token, which
        # then hides narration boundaries in the transaction description.
        words = page.extract_words(x_tolerance=1, y_tolerance=3, use_text_flow=False)
    except (AttributeError, TypeError, ValueError):
        return []
    if not words:
        return []

    lines = []
    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        line = next((candidate for candidate in reversed(lines) if abs(candidate["top"] - word["top"]) <= 3), None)
        if line is None:
            line = {"top": word["top"], "words": []}
            lines.append(line)
        line["words"].append(word)

    header_aliases = {
        "date": ("date", "dates"),
        "description": ("description", "particulars", "narration", "details", "payee", "memo"),
        # Keep non-transaction columns as positional boundaries. Dropping these
        # anchors shifts reference/value-date cells into nearby money columns.
        "ignore": ("chqrefno", "valuedt", "valuedate", "referenceno", "refno"),
        "debit": ("debit", "withdrawal", "withdrawals", "withdrawalamt", "dr", "outflow"),
        "credit": ("credit", "deposit", "deposits", "depositamt", "cr", "inflow"),
        "balance": ("balance", "bal", "closingbalance", "runningbalance"),
        "amount": ("amount",),
    }
    # Prefer table-cell bounds when pdfplumber can infer them. Header text is
    # often centered while transaction values are left/right aligned, so header
    # word origins alone are not reliable column boundaries.
    columns_with_bounds = []
    used_table_bounds = False
    header_index = None
    try:
        for table in page.find_tables() if use_table_cells else []:
            for row_index, header_row in enumerate(table.extract()[:5]):
                table_row = table.rows[row_index]
                found_cells = []
                for cell_index, value in enumerate(header_row):
                    if cell_index >= len(table_row.cells) or not table_row.cells[cell_index]:
                        continue
                    token = re.sub(r"[^a-z]", "", str(value or "").casefold())
                    name = next(
                        (column for column, aliases in header_aliases.items() if token in aliases),
                        "ignore",
                    )
                    cell = table_row.cells[cell_index]
                    found_cells.append((float(cell[0]), float(cell[2]), name))
                names = {name for _, _, name in found_cells}
                if (
                    "date" in names
                    and "description" in names
                    and names.intersection({"debit", "credit", "balance", "amount"})
                ):
                    columns_with_bounds = sorted(found_cells)
                    used_table_bounds = True
                    header_top = min(
                        float(table_row.cells[index][1])
                        for index in range(min(len(header_row), len(table_row.cells)))
                        if table_row.cells[index]
                    )
                    header_index = min(
                        range(len(lines)),
                        key=lambda index: abs(float(lines[index]["top"]) - header_top),
                    )
                    break
            if columns_with_bounds:
                break
    except (AttributeError, TypeError, ValueError):
        columns_with_bounds = []

    if not columns_with_bounds:
        header_index = None
        header_columns = []
        for index, line in enumerate(lines):
            found = []
            header_words = sorted(line["words"], key=lambda item: item["x0"])
            prefixes = {"transaction", "txn", "trans", "value", "posting", "effective", "running", "closing", "available", "current"}
            for word_index, word in enumerate(header_words):
                token = re.sub(r"[^a-z]", "", word["text"].casefold())
                for column, aliases in header_aliases.items():
                    if token in aliases:
                        anchor = float(word["x0"])
                        if word_index:
                            previous = header_words[word_index - 1]
                            previous_token = re.sub(r"[^a-z]", "", previous["text"].casefold())
                            if previous_token in prefixes and anchor - float(previous["x1"]) <= 12:
                                anchor = float(previous["x0"])
                        found.append((anchor, column))
                        break
            names = {name for _, name in found}
            financial_headers = names.intersection({"debit", "credit", "balance", "amount"})
            if "date" in names and "description" in names and financial_headers:
                # Use each x position once; adjacent aliases are not separate output columns.
                header_columns = sorted(found)
                header_index = index
                break
        if header_index is None:
            return []

        anchors = []
        for x_position, name in header_columns:
            if anchors and abs(anchors[-1][0] - x_position) < 2:
                if name == "balance" or name == "description":
                    anchors[-1] = (anchors[-1][0], name)
                continue
            anchors.append((x_position, name))
        columns_with_bounds = []
        for index, (x_position, name) in enumerate(anchors):
            left = (
                float("-inf")
                if index == 0
                else (anchors[index - 1][0] + x_position) / 2
            )
            right = (
                float("inf")
                if index == len(anchors) - 1
                else (x_position + anchors[index + 1][0]) / 2
            )
            columns_with_bounds.append((left, right, name))

    columns = [(left, name) for left, _right, name in columns_with_bounds]
    if len(columns) < 3:
        return []

    def row_cells(line):
        cells = ["" for _ in columns]
        for word in sorted(line["words"], key=lambda item: item["x0"]):
            word_position = (
                (float(word["x0"]) + float(word["x1"])) / 2
                if used_table_bounds
                else float(word["x0"])
            )
            matching_column = next(
                (
                    index for index, (left, right, _name) in enumerate(columns_with_bounds)
                    if left <= word_position < right
                ),
                None,
            )
            if matching_column is None:
                matching_column = max(
                    0,
                    min(len(columns) - 1, next(
                        (index for index, (left, _right, _name) in enumerate(columns_with_bounds[1:], start=1)
                         if word_position < left),
                        len(columns) - 1,
                    ) - 1),
                )
            column_index = matching_column
            cells[column_index] = " ".join(part for part in (cells[column_index], word["text"]) if part)
        return cells

    headers = [name.title() for _, name in columns]
    date_column = next((index for index, (_, name) in enumerate(columns) if name == "date"), None)
    description_column = next((index for index, (_, name) in enumerate(columns) if name == "description"), None)
    amount_columns = {
        index for index, (_, name) in enumerate(columns)
        if name in {"debit", "credit", "balance", "amount"}
    }
    extracted_rows = [headers]
    last_transaction_top = None
    for line in lines[header_index + 1:]:
        cells = row_cells(line)
        if not any(cells):
            continue
        raw_date = cells[date_column] if date_column is not None else ""
        description = cells[description_column] if description_column is not None else ""
        financial_values = [
            cells[index] for index in amount_columns
            if cells[index] and _is_statement_amount_text(cells[index])
        ]
        if not is_date(raw_date) and _is_undated_statement_summary(cells):
            continue
        if not is_date(raw_date):
            is_opening_baseline = (
                bool(financial_values)
                and bool(description)
                and any(
                    marker in description.casefold()
                    for marker in ("opening balance", "opening bal", "brought forward", "b/f", "bal b/f")
                )
            )
            if is_opening_baseline:
                extracted_rows.append(cells)
                last_transaction_top = float(line["top"])
                continue
            if (
                not financial_values and description and extracted_rows[1:]
                and last_transaction_top is not None
                # PDF leading is expressed in points; some bank templates wrap
                # descriptions at 20-point intervals even when the text is a
                # continuation of the same dated row.
                and float(line["top"]) - last_transaction_top <= 24
            ):
                previous = extracted_rows[-1]
                if description_column is not None and (
                    is_date(previous[date_column])
                    or any(
                        m in previous[description_column].casefold()
                        for m in ("opening balance", "opening bal", "brought forward", "b/f", "bal b/f")
                    )
                ):
                    continuation_parts = [description]
                    continuation_parts.extend(
                        cells[index]
                        for index in amount_columns
                        if cells[index] and not _is_statement_amount_text(cells[index])
                    )
                    previous[description_column] = " ".join(
                        part for part in (previous[description_column], *continuation_parts) if part
                    ).strip()
                    last_transaction_top = float(line["top"])
                    continue
            # Ignore page notes and detached metadata rather than emitting them as transactions.
            continue
        extracted_rows.append(cells)
        last_transaction_top = float(line["top"])
    extracted = extracted_rows if len(extracted_rows) > 1 else []
    if extracted and columns_with_bounds and use_table_cells:
        # Some vector PDFs expose misleading inferred cells even though their
        # text positions remain useful. Keep whichever reconstruction carries
        # stronger transaction and narration evidence.
        anchor_extraction = _extract_pdf_text_column_table(page, use_table_cells=False)
        if _statement_table_quality(anchor_extraction) > _statement_table_quality(extracted):
            return anchor_extraction
    return extracted


def _statement_table_base_quality(table: List[List[str]]) -> int:
    """Return header/schema evidence separately from transaction evidence."""
    if len(table) < 2:
        return 0
    header_index = next(
        (
            index for index, row in enumerate(table[:5])
            if any(token in " ".join(row).casefold() for token in ("date", "description", "particulars", "balance", "amount"))
        ),
        None,
    )
    if header_index is None:
        return 0
    headers = table[header_index]
    mapping = classify_columns(headers, table[header_index + 1:header_index + 11])
    if "date" not in mapping or "desc" not in mapping:
        return 0
    return 100 + min(len(mapping), 5) * 5


def _statement_table_quality(table: List[List[str]]) -> tuple[int, int]:
    """Prefer valid transaction/numeric coverage, then complete narration."""
    base_quality = _statement_table_base_quality(table)
    if not base_quality:
        return (0, 0)

    header_index = next(
        index for index, row in enumerate(table[:5])
        if any(token in " ".join(row).casefold() for token in ("date", "description", "particulars", "balance", "amount"))
    )
    headers = table[header_index]
    mapping = classify_columns(headers, table[header_index + 1:header_index + 11])

    valid_date_rows = 0
    numeric_fields = 0
    description_completeness = 0
    for row in table[header_index + 1:]:
        date_index = mapping["date"]
        if date_index >= len(row) or not is_date(row[date_index]):
            continue
        valid_date_rows += 1
        description_index = mapping["desc"]
        if description_index < len(row):
            # Keep this a tie-breaker: table structure and parseable amounts remain
            # the primary quality signals, while richer narration wins equal scores.
            description_completeness += min(12, len(str(row[description_index] or "").split()))
        for field in ("debit", "credit", "balance", "amount"):
            column_index = mapping.get(field)
            if column_index is not None and column_index < len(row) and clean_amount(row[column_index]) is not None:
                numeric_fields += 1
    return (base_quality + valid_date_rows * 20 + numeric_fields * 3, description_completeness)


def statement_page_quality(tables: List[List[List[str]]]) -> tuple[int, int]:
    """Score page evidence without rewarding duplicate table headers."""
    candidates = [
        (_statement_table_quality(table), _statement_table_base_quality(table))
        for table in tables
    ]
    candidates = [(quality, base) for quality, base in candidates if base]
    if not candidates:
        return (0, 0)
    # Header/schema confidence is page-level. Add row evidence across tables,
    # but count the schema baseline once so a weak duplicate extraction cannot
    # outweigh a more complete OCR recovery just by repeating the same header.
    score = max(base for _quality, base in candidates) + sum(
        quality[0] - base for quality, base in candidates
    )
    narration = sum(quality[1] for quality, _base in candidates)
    return (score, narration)


def statement_page_needs_ocr(tables: List[List[List[str]]]) -> bool:
    """Request local OCR when a page has no structurally complete dated rows."""
    if not tables:
        return True
    has_complete_dated_table = False
    for table in tables:
        header_index = next(
            (
                index for index, row in enumerate(table[:5])
                if any(
                    token in " ".join(str(cell or "") for cell in row).casefold()
                    for token in ("date", "description", "particulars", "balance", "amount")
                )
            ),
            None,
        )
        if header_index is None:
            continue
        mapping = classify_columns(table[header_index], table[header_index + 1:header_index + 11])
        date_index = mapping.get("date")
        if date_index is None:
            continue
        description_index = mapping.get("desc")
        financial_indexes = [
            mapping[field] for field in ("debit", "credit", "balance", "amount")
            if field in mapping
        ]
        has_valid_dated_row = False
        for row in table[header_index + 1:]:
            raw_date = str(row[date_index] or "") if date_index < len(row) else ""
            date_tokens_in_column = STATEMENT_DATE_TOKEN_RE.findall(raw_date)
            if len(date_tokens_in_column) > 1 or (date_tokens_in_column and not is_date(raw_date)):
                return True
            if not is_date(raw_date):
                continue
            has_valid_dated_row = True
            # A value-date or reference column can legitimately contain
            # another date-shaped token. Recovery is warranted when dates
            # were merged into the transaction date or narration columns.
            row_text = (
                str(row[description_index] or "")
                if description_index is not None and description_index < len(row)
                else ""
            )
            if (
                len(date_tokens_in_column)
                + len(STATEMENT_DATE_TOKEN_RE.findall(row_text))
                > 1
            ):
                return True
            if not any(
                index < len(row) and clean_amount(row[index]) is not None
                for index in financial_indexes
            ):
                return True
        if has_valid_dated_row:
            has_complete_dated_table = True
    return not has_complete_dated_table


def extract_pdf_page_tables(pdf_bytes: bytes) -> List[List[List[List[str]]]]:
    """Extract page-local tables so scanned pages in mixed PDFs can use OCR."""
    if not pdfplumber:
        raise RuntimeError("pdfplumber is not installed.")

    from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException

    page_tables = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = []
                # Try explicit table extraction first
                extracted = page.extract_tables()
                if extracted:
                    for tbl in extracted:
                        cleaned_tbl = []
                        for row in tbl:
                            if any(cell and str(cell).strip() for cell in row):
                                cleaned_tbl.append([str(c or '').strip() for c in row])
                        if cleaned_tbl and is_statement_candidate_table(cleaned_tbl):
                            tables.append(cleaned_tbl)
                positional_table = _extract_pdf_text_column_table(page)
                if positional_table and is_statement_candidate_table(positional_table):
                    current_quality = tuple(
                        sum(_statement_table_quality(table)[index] for table in tables)
                        for index in range(2)
                    )
                    if _statement_table_quality(positional_table) > current_quality:
                        tables = [positional_table]
                if not tables:
                    # Fallback to line text clustering
                    text = page.extract_text()
                    if text:
                        lines = [l.strip() for l in text.split('\n') if l.strip()]
                        pseudo_table = []
                        for line in lines:
                            # Split by multi-spaces
                            tokens = [t.strip() for t in re.split(r'\s{2,}', line) if t.strip()]
                            if len(tokens) >= 2:
                                pseudo_table.append(tokens)
                        if pseudo_table and is_statement_candidate_table(pseudo_table):
                            tables.append(pseudo_table)
                page_tables.append(tables)
    except (MalformedPDFException, PdfminerException, OSError, ValueError) as error:
        raise StatementPdfReadError() from error
    return page_tables


def extract_pdf_opening_balance(pdf_bytes: bytes, number_locale: str = "auto") -> Optional[float]:
    """Read a uniquely labeled opening balance from a statement summary block."""
    if not pdfplumber:
        return None
    if not isinstance(number_locale, str) or number_locale not in SUPPORTED_NUMBER_LOCALES:
        raise ValueError("Unsupported statement number locale")

    from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException

    candidates = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                words = page.extract_words(x_tolerance=1, y_tolerance=3, use_text_flow=False)
                lines = []
                for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
                    line = next(
                        (item for item in reversed(lines) if abs(item["top"] - word["top"]) <= 3),
                        None,
                    )
                    if line is None:
                        line = {"top": float(word["top"]), "words": []}
                        lines.append(line)
                    line["words"].append(word)

                for line in lines:
                    line_words = sorted(line["words"], key=lambda item: float(item["x0"]))
                    tokens = [re.sub(r"[^a-z]", "", str(word["text"]).casefold()) for word in line_words]
                    joined = "".join(tokens)
                    opening_start = joined.find("openingbalance")
                    closing_at = joined.find("closingbal")
                    summary_markers = ("drcount", "crcount", "debits", "credits")
                    if (
                        opening_start < 0
                        or closing_at < 0
                        or sum(marker in joined for marker in summary_markers) < 2
                    ):
                        continue

                    spans = []
                    offset = 0
                    for word, token in zip(line_words, tokens, strict=True):
                        spans.append((offset, offset + len(token), word))
                        offset += len(token)

                    def x_for_character(position):
                        for start, end, word in spans:
                            if start <= position < end:
                                fraction = (position - start) / max(1, end - start)
                                return float(word["x0"]) + (float(word["x1"]) - float(word["x0"])) * fraction
                        return float(line_words[-1]["x1"])

                    opening_end = opening_start + len("openingbalance")
                    opening_left = x_for_character(opening_start)
                    opening_right = x_for_character(opening_end)
                    following_labels = [
                        joined.find(marker, opening_end)
                        for marker in (*summary_markers, "closingbal")
                    ]
                    following_labels = [position for position in following_labels if position >= opening_end]
                    opening_column_right = (
                        x_for_character(min(following_labels))
                        if following_labels
                        else opening_left + 120
                    )

                    # A few statement formats print the opening value on its
                    # label line; most place it on the next aligned line.
                    amount = None
                    amount_words = [
                        word for word in line_words
                        if opening_right <= float(word["x0"]) < opening_column_right
                        and clean_amount(word["text"], number_locale) is not None
                    ]
                    if len(amount_words) == 1:
                        amount = clean_amount(amount_words[0]["text"], number_locale)

                    if amount is None:
                        value_lines = []
                        for candidate_line in lines:
                            top = float(candidate_line["top"])
                            if not float(line["top"]) + 2 < top <= float(line["top"]) + 48:
                                continue
                            in_column = [
                                word for word in candidate_line["words"]
                                if opening_left - 4 <= (float(word["x0"]) + float(word["x1"])) / 2 < opening_column_right
                            ]
                            value = clean_amount(" ".join(str(word["text"]) for word in in_column), number_locale)
                            if value is not None:
                                value_lines.append((top, value))
                        if value_lines:
                            first_top = min(top for top, _value in value_lines)
                            nearest_values = [value for top, value in value_lines if abs(top - first_top) <= 3]
                            if len(nearest_values) == 1:
                                amount = nearest_values[0]

                    if amount is not None:
                        candidates.append(amount)
    except (MalformedPDFException, PdfminerException, OSError, ValueError) as error:
        raise StatementPdfReadError() from error

    if not candidates or any(abs(value - candidates[0]) > 0.005 for value in candidates[1:]):
        return None
    return candidates[0]


def flatten_statement_tables(tables: List[List[List[str]]]) -> List[List[str]]:
    """Join page tables while dropping exact repeats of the first statement header."""
    candidate_tables = [table for table in tables if is_statement_candidate_table(table)]
    tables_to_join = candidate_tables if candidate_tables else tables

    first_header = None
    for table in tables_to_join:
        best_row = None
        best_score = 0
        for row in table[:5]:
            score = _header_row_score(row)
            if score > best_score:
                best_score = score
                best_row = tuple(" ".join(str(cell or "").split()).casefold() for cell in row)
        if best_row is not None and best_score >= 15:
            first_header = best_row
            break
        if first_header is None:
            for row in table[:5]:
                normalized = tuple(" ".join(str(cell or "").split()).casefold() for cell in row)
                words = " ".join(normalized)
                if any(token in words for token in ("date", "description", "particulars", "withdrawal", "deposit", "balance", "amount")):
                    first_header = normalized
                    break
        if first_header is not None:
            break

    rows = []
    header_seen = False
    for table in tables_to_join:
        for row in table:
            normalized = tuple(" ".join(str(cell or "").split()).casefold() for cell in row)
            if first_header is not None and normalized == first_header:
                if header_seen:
                    continue
                header_seen = True
            rows.append([str(cell or "").strip() for cell in row])
    return rows


def extract_text_from_image(image_bytes: bytes, timeout_seconds: float | None = None) -> List[List[str]]:
    """OCR an image to structured rows and tokens."""
    recognize = _select_image_recognizer()
    if timeout_seconds is not None:
        if recognize is engine_macos_ocr.recognize_image:
            recognize_with_timeout = lambda image, recognizer=recognize: recognizer(
                image, timeout_seconds=timeout_seconds
            )
        elif recognize is _recognize_tesseract_image:
            recognize_with_timeout = lambda image: _recognize_tesseract_image(image, timeout_seconds)
        else:
            recognize_with_timeout = recognize
        recognize = recognize_with_timeout
    return extract_image_text_rows(image_bytes, Image.open, recognize)


def _select_image_recognizer():
    if engine_rapidocr.is_available():
        return engine_rapidocr.recognize_image
    if sys.platform == "darwin" and engine_macos_ocr.is_available():
        return engine_macos_ocr.recognize_image
    if _load_pytesseract() is not None:
        return _recognize_tesseract_image
    return None


def _recognize_tesseract_image(image, timeout_seconds=None):
    """Call Tesseract while preserving the distinct missing-binary condition."""
    ocr_engine = _load_pytesseract()
    if ocr_engine is None:
        raise ImageTextRecognitionUnavailable()
    try:
        if timeout_seconds is not None:
            return ocr_engine.image_to_string(image, timeout=timeout_seconds)
        return ocr_engine.image_to_string(image)
    except Exception as error:
        unavailable_error = getattr(ocr_engine, "TesseractNotFoundError", None)
        if isinstance(unavailable_error, type) and isinstance(error, unavailable_error):
            raise ImageTextRecognitionUnavailable() from error
        raise


STATEMENT_COLUMN_FIELDS = frozenset(("date", "desc", "debit", "credit", "amount", "balance"))
REQUIRED_STATEMENT_COLUMN_FIELDS = frozenset(("date", "desc"))


def _validate_statement_column_mapping(
    headers: List[str], mapping: Dict[str, Optional[int]],
) -> Dict[str, int]:
    if not isinstance(mapping, dict) or any(field not in STATEMENT_COLUMN_FIELDS for field in mapping):
        raise ValueError("Choose a valid source column for each statement field.")
    if not REQUIRED_STATEMENT_COLUMN_FIELDS.issubset(mapping):
        raise ValueError("Date and description columns are required.")

    normalized: Dict[str, int] = {}
    for field, index in mapping.items():
        if index is None:
            if field in REQUIRED_STATEMENT_COLUMN_FIELDS:
                raise ValueError("Date and description columns are required.")
            continue
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(headers):
            raise ValueError("A selected source column is outside the statement table.")
        normalized[field] = index

    if len(set(normalized.values())) != len(normalized):
        raise ValueError("Each source column can be assigned to only one statement field.")
    if "amount" in normalized and ({"debit", "credit"} & normalized.keys()):
        raise ValueError("Choose a combined amount column or separate debit and credit columns.")
    return normalized


def parse_statement_table(
    rows: List[List[str]], number_locale: str = "auto", date_order: str = "auto",
    opening_balance: Optional[float] = None,
    column_mapping: Optional[Dict[str, Optional[int]]] = None,
) -> Dict[str, Any]:
    """Parse raw table rows into standardized normalized transactions + reconciliation."""
    if not isinstance(number_locale, str) or number_locale not in SUPPORTED_NUMBER_LOCALES:
        raise ValueError("Unsupported statement number locale")
    if not isinstance(date_order, str) or date_order not in SUPPORTED_DATE_ORDERS:
        raise ValueError("Unsupported statement date order")
    if opening_balance is not None and (
        isinstance(opening_balance, bool)
        or not isinstance(opening_balance, (int, float))
        or not math.isfinite(opening_balance)
    ):
        raise ValueError("Opening balance must be a finite number")
    if not rows or len(rows) < 2:
        return {
            "headers": [],
            "rows": [],
                "transactions": [],
                "excluded_rows": [],
                "reconciliation": {
                "valid": None,
                "status": "unverified",
                "total_transactions": 0,
                "checked_rows": 0,
                "unverified_rows": 0,
                "discrepancies_count": 0,
                "discrepancies": [],
            },
        }

    # Find the header row
    header_idx = 0
    best_score = 0
    for idx, r in enumerate(rows[:10]):
        score = _header_row_score(r)
        if score > best_score:
            best_score = score
            header_idx = idx

    if best_score < 15:
        for idx, r in enumerate(rows[:5]):
            text = " ".join(r).lower()
            if any(k in text for k in ['date', 'amount', 'balance', 'description', 'particulars']):
                header_idx = idx
                break

    headers = rows[header_idx]
    data_rows = rows[header_idx + 1:]

    col_map = (
        _validate_statement_column_mapping(headers, column_mapping)
        if column_mapping is not None
        else classify_columns(headers, data_rows[:10])
    )

    transactions = []
    excluded_rows = []
    prev_balance = float(opening_balance) if opening_balance is not None else None
    discrepancies = []
    checked_rows = 0
    unverified_rows = 0

    for r_idx, row in enumerate(data_rows):
        if not any(row):
            continue

        raw_date = row[col_map['date']] if 'date' in col_map and col_map['date'] < len(row) else ''
        if len(STATEMENT_DATE_TOKEN_RE.findall(str(raw_date or ""))) > 1:
            # A merged cell cannot be assigned to one transaction safely. Keep
            # the source row in raw_rows for review and count it as unchecked,
            # so other matched rows cannot make the whole statement look verified.
            excluded_rows.append({
                "row_index": header_idx + r_idx + 1,
                "reason": "multiple_dates",
            })
            unverified_rows += 1
            continue
        if not is_date(raw_date) and _is_undated_statement_summary(row):
            continue
        date_val = normalize_statement_date(raw_date, date_order)
        desc_val = row[col_map['desc']] if 'desc' in col_map and col_map['desc'] < len(row) else ''
        if not str(desc_val or '').strip():
            excluded_indices = {
                col_map.get('debit'),
                col_map.get('credit'),
                col_map.get('balance'),
                col_map.get('amount'),
            }
            candidate_texts = [
                str(cell or '').strip()
                for c_idx, cell in enumerate(row)
                if c_idx not in excluded_indices
                and str(cell or '').strip()
                and not is_date(cell)
                and clean_amount(str(cell or ''), number_locale) is None
            ]
            if candidate_texts:
                desc_val = " ".join(candidate_texts)
        
        debit_val = clean_amount(row[col_map['debit']], number_locale) if 'debit' in col_map and col_map['debit'] < len(row) else None
        credit_val = clean_amount(row[col_map['credit']], number_locale) if 'credit' in col_map and col_map['credit'] < len(row) else None
        balance_val = clean_amount(row[col_map['balance']], number_locale) if 'balance' in col_map and col_map['balance'] < len(row) else None

        # If only combined amount exists
        if debit_val is None and credit_val is None and 'amount' in col_map and col_map['amount'] < len(row):
            amt = clean_amount(row[col_map['amount']], number_locale)
            if amt is not None:
                if amt < 0:
                    debit_val = abs(amt)
                else:
                    credit_val = amt

        # Ensure positive magnitudes for debit & credit fields
        if debit_val is not None:
            debit_val = abs(debit_val)
        if credit_val is not None:
            credit_val = abs(credit_val)

        # A balance equation is only meaningful when both a previous/current
        # balance and a parsed movement amount exist. Missing amounts are not zero.
        has_movement_amount = debit_val is not None or credit_val is not None
        is_opening_bal_text = any(
            marker in str(desc_val).casefold()
            for marker in ("opening balance", "opening bal", "brought forward", "b/f", "bal b/f")
        )
        if balance_val is not None and not has_movement_amount and (
            prev_balance is None or is_opening_bal_text
        ):
            row_status = "baseline"
        elif prev_balance is not None and balance_val is not None and has_movement_amount:
            expected = prev_balance + (credit_val or 0.0) - (debit_val or 0.0)
            diff = abs(expected - balance_val)
            checked_rows += 1
            row_status = "ok"
            if diff > 0.02:  # allow 2 cents rounding
                row_status = "reconciliation_warning"
                discrepancies.append({
                    "row_index": r_idx,
                    "date": date_val,
                    "expected_balance": round(expected, 2),
                    "reported_balance": balance_val,
                    "diff": round(diff, 2)
                })
        else:
            row_status = "unverified"
            unverified_rows += 1

        if balance_val is not None:
            prev_balance = balance_val
        else:
            # Do not bridge a missing/unreadable row balance with an older
            # statement balance; the next observed balance starts a new baseline.
            prev_balance = None

        transactions.append({
            "id": r_idx + 1,
            "date": date_val,
            "description": desc_val,
            "debit": debit_val,
            "credit": credit_val,
            "balance": balance_val,
            "status": row_status,
            "raw": row
        })

    if discrepancies:
        reconciliation_status = "discrepancy"
        reconciliation_valid = False
    elif checked_rows == 0:
        reconciliation_status = "unverified"
        reconciliation_valid = None
    elif unverified_rows:
        reconciliation_status = "partial"
        reconciliation_valid = None
    else:
        reconciliation_status = "verified"
        reconciliation_valid = True

    return {
        "headers": headers,
        "raw_rows": rows,
        "transactions": transactions,
        "excluded_rows": excluded_rows,
        "column_mapping": col_map,
        "reconciliation": {
            "valid": reconciliation_valid,
            "status": reconciliation_status,
            "total_transactions": len(transactions),
            "checked_rows": checked_rows,
            "unverified_rows": unverified_rows,
            "discrepancies_count": len(discrepancies),
            "discrepancies": discrepancies
        }
    }


def export_to_ofx(transactions: List[Dict[str, Any]], account_id: str = "123456789") -> str:
    """Generates standard Open Financial Exchange (OFX) format for Xero, Sage, and accounting apps."""
    lines = [
        "OFXHEADER:100",
        "DATA:OFXSGML",
        "VERSION:102",
        "SECURITY:NONE",
        "ENCODING:USASCII",
        "CHARSET:1252",
        "COMPRESSION:NONE",
        "OLDFILEVERSION:NONE",
        "NEWFILEVERSION:NONE",
        "",
        "<OFX>",
        "<SIGNONMSGSRSV1>",
        "<SONRS>",
        "<STATUS><CODE>0<SEVERITY>INFO</STATUS>",
        "<DTSERVER>20260101000000",
        "<LANGUAGE>ENG",
        "</SONRS>",
        "</SIGNONMSGSRSV1>",
        "<BANKMSGSRSV1>",
        "<STMTTRNRS>",
        "<TRNUID>1001",
        "<STATUS><CODE>0<SEVERITY>INFO</STATUS>",
        "<STMTRS>",
        "<CURDEF>USD",
        f"<BANKACCTFROM><BANKID>000000000<ACCTID>{account_id}<ACCTTYPE>CHECKING</BANKACCTFROM>",
        "<BANKTRANLIST>"
    ]

    for idx, tx in enumerate(transactions):
        date_str = str(tx.get("date", "20260101")).replace("-", "").replace("/", "")[:8]
        desc = tx.get("description", "Transaction")
        debit = tx.get("debit")
        credit = tx.get("credit")
        amount = 0.0
        trn_type = "OTHER"

        if credit is not None:
            amount = float(credit)
            trn_type = "CREDIT"
        elif debit is not None:
            amount = -float(debit)
            trn_type = "DEBIT"

        lines.extend([
            "<STMTTRN>",
            f"<TRNTYPE>{trn_type}",
            f"<DTPOSTED>{date_str}",
            f"<TRNAMT>{amount}",
            f"<FITID>{date_str}{idx+1}",
            f"<NAME>{desc}",
            f"<MEMO>{desc}",
            "</STMTTRN>"
        ])

    lines.extend([
        "</BANKTRANLIST>",
        "<LEDGERBAL>",
        "<BALAMT>0.00",
        "<DTASOF>20260101",
        "</LEDGERBAL>",
        "</STMTRS>",
        "</STMTTRNRS>",
        "</BANKMSGSRSV1>",
        "</OFX>"
    ])
    return "\n".join(lines)


def export_to_qbo(transactions: List[Dict[str, Any]], account_id: str = "123456789") -> str:
    """Refuse a misleading QBO export until a supported institution profile exists.

    QuickBooks Web Connect files require institution-specific metadata and identifiers.
    The current statement extractor has neither, so generic OFX cannot safely be
    represented as an importable QBO file.
    """
    raise ValueError(
        "QBO export requires a supported QuickBooks financial-institution profile; "
        "generic OFX output is not a valid substitute."
    )


def extract_pdf_statement_summary(pdf_bytes: bytes, number_locale: str = "auto") -> Dict[str, Any]:
    """Extract declared statement summary totals (opening balance, closing balance, totals) from raw PDF text."""
    if not pdfplumber:
        return {}
    if not isinstance(number_locale, str) or number_locale not in SUPPORTED_NUMBER_LOCALES:
        raise ValueError("Unsupported statement number locale")

    from pdfplumber.utils.exceptions import MalformedPDFException, PdfminerException

    summary: Dict[str, Any] = {}
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                for line in text.split("\n"):
                    trimmed = line.strip()
                    if not trimmed:
                        continue

                    # Opening balance
                    m_open = re.search(
                        r"(?i)\b(?:opening\s+balance|bal(?:ance)?\s*b/?f|brought\s+forward)\b.*?([\d,.]+(?:\.\d{2})?)",
                        trimmed,
                    )
                    if m_open and "opening_balance" not in summary:
                        val = clean_amount(m_open.group(1), number_locale)
                        if val is not None:
                            summary["opening_balance"] = val
                            summary["opening_balance_page"] = page_idx + 1

                    # Closing balance
                    m_close = re.search(
                        r"(?i)\b(?:closing\s+balance|ending\s+balance|bal(?:ance)?\s*c/?f|carried\s+forward)\b.*?([\d,.]+(?:\.\d{2})?)",
                        trimmed,
                    )
                    if m_close and "closing_balance" not in summary:
                        val = clean_amount(m_close.group(1), number_locale)
                        if val is not None:
                            summary["closing_balance"] = val
                            summary["closing_balance_page"] = page_idx + 1

                    # Total debits / withdrawals
                    m_dr = re.search(
                        r"(?i)\btotal\s+(?:debits?|withdrawals?|paid\s+out)\b.*?([\d,.]+(?:\.\d{2})?)",
                        trimmed,
                    )
                    if m_dr and "total_debits" not in summary:
                        val = clean_amount(m_dr.group(1), number_locale)
                        if val is not None:
                            summary["total_debits"] = val

                    # Total credits / deposits
                    m_cr = re.search(
                        r"(?i)\btotal\s+(?:credits?|deposits?|paid\s+in)\b.*?([\d,.]+(?:\.\d{2})?)",
                        trimmed,
                    )
                    if m_cr and "total_credits" not in summary:
                        val = clean_amount(m_cr.group(1), number_locale)
                        if val is not None:
                            summary["total_credits"] = val
    except (MalformedPDFException, PdfminerException, OSError, ValueError):
        return {}

    return summary


def verify_statement_against_pdf(
    transactions: List[Dict[str, Any]],
    pdf_bytes: bytes,
    number_locale: str = "auto",
) -> Dict[str, Any]:
    """Cross-verify extracted transactions against declared PDF summary cards and verbatim tokens.

    Performs:
    1. Declared opening balance vs extracted baseline comparison.
    2. Declared closing balance vs extracted final running balance comparison.
    3. Net movement equation check: opening + sum(credits) - sum(debits) == declared closing balance.
    4. Declared totals check: sum(debits) == declared debits and sum(credits) == declared credits.
    5. Verbatim existence check: verifies extracted monetary amounts exist in the raw PDF text.
    """
    if not pdfplumber:
        return {"verified": None, "reason": "pdfplumber not available", "checks": []}

    summary = extract_pdf_statement_summary(pdf_bytes, number_locale)

    non_baseline_txs = [tx for tx in transactions if tx.get("status") != "baseline"]
    total_debits = sum(tx.get("debit") or 0.0 for tx in non_baseline_txs)
    total_credits = sum(tx.get("credit") or 0.0 for tx in non_baseline_txs)

    # Resolve opening balance: either baseline row or declared summary
    opening_bal = next(
        (tx["balance"] for tx in transactions if tx.get("status") == "baseline" and tx.get("balance") is not None),
        None,
    )
    if opening_bal is None:
        opening_bal = summary.get("opening_balance")

    last_bal = None
    for tx in reversed(transactions):
        if tx.get("balance") is not None:
            last_bal = tx["balance"]
            break

    checks: List[Dict[str, Any]] = []

    # Check 1: Declared opening balance vs baseline
    if summary.get("opening_balance") is not None and opening_bal is not None:
        diff = abs(summary["opening_balance"] - opening_bal)
        checks.append({
            "name": "opening_balance",
            "expected": summary["opening_balance"],
            "actual": opening_bal,
            "passed": diff <= 0.02,
        })

    # Check 2: Declared closing balance vs final running balance
    if summary.get("closing_balance") is not None and last_bal is not None:
        diff = abs(summary["closing_balance"] - last_bal)
        checks.append({
            "name": "closing_balance",
            "expected": summary["closing_balance"],
            "actual": last_bal,
            "passed": diff <= 0.02,
        })

    # Check 3: Net ledger movement vs declared closing balance
    if opening_bal is not None and summary.get("closing_balance") is not None:
        expected_close = round(opening_bal + total_credits - total_debits, 2)
        diff = abs(summary["closing_balance"] - expected_close)
        checks.append({
            "name": "net_movement_vs_closing",
            "expected": summary["closing_balance"],
            "actual": expected_close,
            "passed": diff <= 0.02,
        })

    # Check 4: Declared total debits
    if summary.get("total_debits") is not None:
        actual_debits = round(total_debits, 2)
        diff = abs(summary["total_debits"] - actual_debits)
        checks.append({
            "name": "total_debits",
            "expected": summary["total_debits"],
            "actual": actual_debits,
            "passed": diff <= 0.02,
        })

    # Check 5: Declared total credits
    if summary.get("total_credits") is not None:
        actual_credits = round(total_credits, 2)
        diff = abs(summary["total_credits"] - actual_credits)
        checks.append({
            "name": "total_credits",
            "expected": summary["total_credits"],
            "actual": actual_credits,
            "passed": diff <= 0.02,
        })

    # Check 6: Verbatim monetary token verification in PDF text
    unmatched_tokens: List[Dict[str, Any]] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pdf_text = " ".join(page.extract_text() or "" for page in pdf.pages)
            for tx in non_baseline_txs:
                for field in ("debit", "credit", "balance"):
                    amt = tx.get(field)
                    if amt is not None:
                        candidates = [f"{amt:.2f}", f"{amt:,.2f}", str(amt)]
                        if not any(token in pdf_text for token in candidates):
                            unmatched_tokens.append({
                                "transaction_id": tx.get("id"),
                                "field": field,
                                "value": amt,
                            })
    except Exception:
        pass

    all_passed = bool(checks) and all(c["passed"] for c in checks) and len(unmatched_tokens) == 0
    status = "verified" if all_passed else ("discrepancy" if any(not c["passed"] for c in checks) or unmatched_tokens else "unverified")

    return {
        "status": status,
        "valid": all_passed if checks else None,
        "declared_summary": summary,
        "checks": checks,
        "unmatched_tokens": unmatched_tokens,
    }

