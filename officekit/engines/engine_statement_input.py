"""Strict, delimiter-aware parsing for uploaded bank-statement text files."""

import csv
import io


MAX_STATEMENT_TEXT_BYTES = 64 * 1024 * 1024


class StatementInputError(ValueError):
    status_code = 422

    def __init__(self, public_message: str):
        super().__init__(public_message)


def parse_statement_delimited(content: bytes, extension: str) -> list[list[str]]:
    """Parse UTF-8 CSV or TSV while preserving quoted fields and delimiters."""
    if extension.lower().lstrip(".") not in {"csv", "tsv"}:
        raise StatementInputError("Upload a CSV or TSV statement.")
    if not isinstance(content, bytes):
        raise StatementInputError("The statement file could not be read.")
    if len(content) > MAX_STATEMENT_TEXT_BYTES:
        raise StatementInputError("The statement file is too large to process.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise StatementInputError(
            "Save the statement as UTF-8 CSV or TSV, then try again."
        ) from error

    delimiter = "\t" if extension.lower().lstrip(".") == "tsv" else ","
    try:
        return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True))
    except csv.Error as error:
        raise StatementInputError("The CSV or TSV file has invalid quoting.") from error
