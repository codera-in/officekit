"""Spreadsheet cell safety helpers for untrusted imported text."""

import unicodedata
from typing import Any


def sanitize_spreadsheet_text(value: Any) -> Any:
    """Force text cells to remain text in spreadsheet applications.

    Spreadsheet programs may evaluate cells beginning with formula markers,
    even when CSV fields are quoted. A leading apostrophe makes such values
    display as text while preserving the imported content for readers.
    """
    if not isinstance(value, str):
        return value

    if not value:
        return value

    first_visible = value.lstrip()
    while first_visible and unicodedata.category(first_visible[0]) == "Cf":
        first_visible = first_visible[1:]
    starts_with_formula = first_visible.startswith(("=", "+", "-", "@")) and first_visible != "-"
    starts_with_control = unicodedata.category(value[0]) in {"Cc", "Cf"}
    return f"'{value}" if starts_with_formula or starts_with_control else value
