"""Bounded exports for reports created from a selected temporary workspace."""

import csv
import io
from typing import Any

from officekit.engines.engine_spreadsheet_safety import sanitize_spreadsheet_text


MAX_FOLDER_COMPARISON_CSV_BYTES = 4 * 1024 * 1024


class WorkspaceExportLimitError(ValueError):
    """Raised when a workspace report export exceeds its response budget."""


def render_folder_comparison_csv(report: dict[str, Any]) -> bytes:
    """Render a validated folder comparison as a formula-safe UTF-8 CSV attachment."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow((
        "entry_type",
        "relative_path",
        "status",
        "folder_a_path",
        "folder_a_size_bytes",
        "folder_a_sha256",
        "folder_b_path",
        "folder_b_size_bytes",
        "folder_b_sha256",
    ))
    for item in report["files"]:
        writer.writerow((
            "file",
            sanitize_spreadsheet_text(item["path"]),
            item["status"],
            sanitize_spreadsheet_text(item["left_name"] or ""),
            item["left_size_bytes"] if item["left_size_bytes"] is not None else "",
            item["left_sha256"] or "",
            sanitize_spreadsheet_text(item["right_name"] or ""),
            item["right_size_bytes"] if item["right_size_bytes"] is not None else "",
            item["right_sha256"] or "",
        ))
    for item in report.get("directories", []):
        relative_path = item["path"]
        left_folder = report.get("left_folder", "")
        right_folder = report.get("right_folder", "")
        left_path = left_folder if relative_path == "." else f"{left_folder}/{relative_path}"
        right_path = right_folder if relative_path == "." else f"{right_folder}/{relative_path}"
        writer.writerow((
            "directory",
            sanitize_spreadsheet_text(relative_path),
            item["status"],
            sanitize_spreadsheet_text(left_path if item["status"] != "right-only" else ""),
            "",
            "",
            sanitize_spreadsheet_text(right_path if item["status"] != "left-only" else ""),
            "",
            "",
        ))
    content = output.getvalue().encode("utf-8")
    if len(content) > MAX_FOLDER_COMPARISON_CSV_BYTES:
        raise WorkspaceExportLimitError("The folder-comparison export exceeds the supported 4 MiB limit")
    return content
