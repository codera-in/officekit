"""Boundary tests for local workspace report attachments."""

import csv
import io
import unittest
from unittest.mock import patch

from officekit.engines.engine_workspace_exports import (
    WorkspaceExportLimitError,
    render_folder_comparison_csv,
)


class WorkspaceReportExportTests(unittest.TestCase):
    def test_folder_comparison_csv_preserves_typed_values_and_sanitizes_text(self):
        report = {"files": [{
            "path": "=SUM(1+1).csv",
            "status": "changed",
            "left_name": "before/=SUM(1+1).csv",
            "left_size_bytes": 4,
            "left_sha256": "a" * 64,
            "right_name": "after/=SUM(1+1).csv",
            "right_size_bytes": 5,
            "right_sha256": "b" * 64,
        }]}

        content = render_folder_comparison_csv(report)
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["relative_path"], "'=SUM(1+1).csv")
        self.assertEqual(rows[0]["folder_a_path"], "before/=SUM(1+1).csv")
        self.assertEqual(rows[0]["folder_a_size_bytes"], "4")
        self.assertEqual(rows[0]["folder_b_size_bytes"], "5")
        self.assertEqual(rows[0]["status"], "changed")

    def test_folder_comparison_csv_leaves_missing_sides_empty(self):
        report = {"files": [{
            "path": "new.txt",
            "status": "right-only",
            "left_name": None,
            "left_size_bytes": None,
            "left_sha256": None,
            "right_name": "after/new.txt",
            "right_size_bytes": 3,
            "right_sha256": "c" * 64,
        }]}

        rows = list(csv.DictReader(io.StringIO(render_folder_comparison_csv(report).decode("utf-8"))))

        self.assertEqual(rows[0]["folder_a_path"], "")
        self.assertEqual(rows[0]["folder_a_size_bytes"], "")
        self.assertEqual(rows[0]["folder_a_sha256"], "")
        self.assertEqual(rows[0]["folder_b_path"], "after/new.txt")

    def test_folder_comparison_csv_distinguishes_directory_rows_and_empty_folder_sides(self):
        report = {
            "left_folder": "before",
            "right_folder": "after",
            "files": [],
            "directories": [
                {"path": "empty-only", "status": "left-only"},
                {"path": "nested", "status": "identical"},
            ],
        }

        rows = list(csv.DictReader(io.StringIO(render_folder_comparison_csv(report).decode("utf-8"))))

        self.assertEqual([row["entry_type"] for row in rows], ["directory", "directory"])
        self.assertEqual(rows[0]["relative_path"], "empty-only")
        self.assertEqual(rows[0]["folder_a_path"], "before/empty-only")
        self.assertEqual(rows[0]["folder_b_path"], "")
        self.assertEqual(rows[1]["status"], "identical")

    def test_folder_comparison_csv_rejects_output_over_the_response_limit(self):
        report = {"files": [{
            "path": "safe.txt",
            "status": "identical",
            "left_name": "left/safe.txt",
            "left_size_bytes": 1,
            "left_sha256": "d" * 64,
            "right_name": "right/safe.txt",
            "right_size_bytes": 1,
            "right_sha256": "d" * 64,
        }]}
        with patch("officekit.engines.engine_workspace_exports.MAX_FOLDER_COMPARISON_CSV_BYTES", 8):
            with self.assertRaises(WorkspaceExportLimitError):
                render_folder_comparison_csv(report)


if __name__ == "__main__":
    unittest.main()
