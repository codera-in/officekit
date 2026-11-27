"""Safe, portable SQL INSERT script rendering for data conversion."""

from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal
from numbers import Integral, Real
from typing import Iterable


def _identifier(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 128
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{label} must be a non-empty, printable string up to 128 characters")
    return '"' + value.replace('"', '""') + '"'


def _as_python_scalar(value: object) -> object:
    """Normalize common NumPy scalar wrappers without importing NumPy."""
    if type(value).__module__.startswith("numpy") and hasattr(value, "item"):
        return value.item()
    return value


def _literal(raw_value: object) -> str:
    value = _as_python_scalar(raw_value)
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Decimal):
        if value.is_nan():
            return "NULL"
        if not value.is_finite():
            raise ValueError("SQL export does not support infinite numeric values")
        return str(value)
    if isinstance(value, Real):
        number = float(value)
        if math.isnan(number):
            return "NULL"
        if not math.isfinite(number):
            raise ValueError("SQL export does not support infinite numeric values")
        return repr(number)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        value = value.isoformat()
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("SQL text values cannot contain a NUL character")
        return "'" + value.replace("'", "''") + "'"
    raise ValueError(f"SQL export does not support cell type: {type(value).__name__}")


def render_insert_script(
    columns: Iterable[object], rows: Iterable[Iterable[object]], table_name: object = "exported_table"
) -> str:
    """Render a SQL script using validated identifiers and escaped scalar values."""
    table = _identifier(table_name, "Table name")
    column_list = list(columns)
    quoted_columns = [_identifier(column, "Column name") for column in column_list]
    if len({column.casefold() for column in column_list if isinstance(column, str)}) != len(column_list):
        raise ValueError("SQL export requires unique column names")
    if not quoted_columns:
        if any(True for _ in rows):
            raise ValueError("SQL export cannot render rows without columns")
        return ""

    prefix = f"INSERT INTO {table} ({', '.join(quoted_columns)}) VALUES "
    statements = []
    for row in rows:
        values = list(row)
        if len(values) != len(quoted_columns):
            raise ValueError("SQL export row width does not match the column count")
        statements.append(prefix + f"({', '.join(_literal(value) for value in values)});")
    return "\n".join(statements)
