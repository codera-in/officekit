"""Stdlib regression tests for storage-scan scope and symlink behavior."""

import tempfile
import unittest
from pathlib import Path
import os
import sys
import hashlib
from unittest.mock import patch

from officekit.engines.engine_file_ops import FileOpsEngine, StorageAnalyzerEngine


class StorageAnalyzerSafetyTests(unittest.TestCase):
    def test_duplicate_finder_includes_zero_byte_duplicates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            empty_a = root / "empty-a.bin"
            empty_b = root / "empty-b.bin"
            empty_a.touch()
            empty_b.touch()

            groups = FileOpsEngine.find_duplicate_files(temp_dir)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["size_bytes"], 0)
        self.assertEqual(set(groups[0]["files"]), {str(empty_a.resolve()), str(empty_b.resolve())})

    def test_duplicate_finder_does_not_count_symlink_aliases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.bin"
            second = root / "second.bin"
            alias = root / "alias.bin"
            first.write_bytes(b"same bytes")
            second.write_bytes(b"same bytes")
            try:
                alias.symlink_to(first)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")

            groups = FileOpsEngine.find_duplicate_files(temp_dir)

        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]["files"]), {str(first.resolve()), str(second.resolve())})

    def test_duplicate_scan_hashes_only_same_size_and_same_first_chunk_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prefix = b"p" * 4096
            duplicate = root / "duplicate.bin"
            same_prefix_different_content = root / "same-prefix.bin"
            different_prefix = root / "different-prefix.bin"
            exact_copy = root / "exact-copy.bin"
            duplicate.write_bytes(prefix + b"same-tail")
            same_prefix_different_content.write_bytes(prefix + b"diff-tail")
            different_prefix.write_bytes(b"q" * 4096 + b"same-tail")
            exact_copy.write_bytes(prefix + b"same-tail")

            real_open = os.open
            opens = {}

            def count_open(path, flags, *args, **kwargs):
                normalized = os.fspath(path)
                opens[normalized] = opens.get(normalized, 0) + 1
                return real_open(path, flags, *args, **kwargs)

            with patch("officekit.engines.engine_file_ops.os.open", side_effect=count_open):
                report = FileOpsEngine.find_duplicate_files_report(temp_dir)

        self.assertTrue(report["complete"])
        self.assertEqual(report["files_scanned"], 4)
        self.assertEqual(len(report["groups"]), 1)
        group = report["groups"][0]
        self.assertEqual(group["hash"], hashlib.sha256(prefix + b"same-tail").hexdigest())
        self.assertEqual(group["size_bytes"], len(prefix + b"same-tail"))
        self.assertEqual(
            group["files"],
            sorted([str(duplicate.resolve()), str(exact_copy.resolve())]),
        )
        self.assertEqual(opens[str(different_prefix.resolve())], 1)
        self.assertEqual(opens[str(duplicate.resolve())], 2)
        self.assertEqual(opens[str(same_prefix_different_content.resolve())], 2)
        self.assertEqual(opens[str(exact_copy.resolve())], 2)

    def test_duplicate_report_discloses_scan_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in ("a.bin", "b.bin", "c.bin"):
                (root / name).write_bytes(b"identical")

            report = FileOpsEngine.find_duplicate_files_report(temp_dir, max_entries=2)

        self.assertEqual(report["files_scanned"], 2)
        self.assertFalse(report["complete"])
        self.assertIn("entry limit", report["errors"][0]["error"])

    def test_duplicate_report_at_exact_entry_limit_is_complete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.bin").write_bytes(b"one")
            (root / "b.bin").write_bytes(b"different")

            report = FileOpsEngine.find_duplicate_files_report(temp_dir, max_entries=2)

        self.assertEqual(report["files_scanned"], 2)
        self.assertTrue(report["complete"])
        self.assertEqual(report["errors"], [])

    @unittest.skipIf(sys.platform == "win32", "In-place same-size mutation detection requires POSIX ctime and subsecond timestamps")
    def test_duplicate_report_rejects_a_file_changed_before_hashing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.bin"
            second = root / "second.bin"
            first.write_bytes(b"same bytes")
            second.write_bytes(b"same bytes")
            real_open = os.open

            def mutate_before_open(path, flags, *args, **kwargs):
                if os.fspath(path) == str(first.resolve()):
                    first.write_bytes(b"altered!!!")
                return real_open(path, flags, *args, **kwargs)

            with patch("officekit.engines.engine_file_ops.os.open", side_effect=mutate_before_open):
                report = FileOpsEngine.find_duplicate_files_report(temp_dir)

        self.assertFalse(report["complete"])
        self.assertEqual(report["groups"], [])
        self.assertTrue(any("changed during duplicate scan" in row["error"] for row in report["errors"]))

    @unittest.skipIf(sys.platform == "win32", "In-place same-size mutation detection requires POSIX ctime and subsecond timestamps")
    def test_duplicate_report_rejects_same_size_change_between_prefilter_and_full_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "a.bin"
            second = root / "b.bin"
            first.write_bytes(b"same bytes")
            second.write_bytes(b"same bytes")
            original_stat = first.stat()
            real_open = os.open
            calls = {}

            def mutate_after_prefilter(path, flags, *args, **kwargs):
                normalized = os.fspath(path)
                calls[normalized] = calls.get(normalized, 0) + 1
                if normalized == str(first.resolve()) and calls[normalized] == 2:
                    first.write_bytes(b"other text")
                    os.utime(first, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
                return real_open(path, flags, *args, **kwargs)

            with patch("officekit.engines.engine_file_ops.os.open", side_effect=mutate_after_prefilter):
                report = FileOpsEngine.find_duplicate_files_report(temp_dir)

        self.assertFalse(report["complete"])
        self.assertEqual(report["groups"], [])
        self.assertTrue(any("changed during duplicate scan" in row["error"] for row in report["errors"]))

    def test_protected_path_prefix_does_not_reject_sibling_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            protected = root / "private"
            sibling = root / "private-backups"
            protected.mkdir()
            sibling.mkdir()
            (sibling / "report.txt").write_text("ok", encoding="utf-8")
            original = StorageAnalyzerEngine.PROTECTED_SYSTEM_PATHS
            StorageAnalyzerEngine.PROTECTED_SYSTEM_PATHS = {str(protected)}
            try:
                result = StorageAnalyzerEngine.analyze_directory(str(sibling))
            finally:
                StorageAnalyzerEngine.PROTECTED_SYSTEM_PATHS = original

        self.assertEqual(result["total_files"], 1)
        self.assertEqual(result["total_size_bytes"], 2)

    def test_scan_root_containing_a_protected_subtree_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            protected = root / "system"
            protected.mkdir()
            (protected / "secret.txt").write_text("secret", encoding="utf-8")
            original = StorageAnalyzerEngine.PROTECTED_SYSTEM_PATHS
            StorageAnalyzerEngine.PROTECTED_SYSTEM_PATHS = {str(protected)}
            try:
                with self.assertRaises(PermissionError):
                    StorageAnalyzerEngine.analyze_directory(temp_dir)
            finally:
                StorageAnalyzerEngine.PROTECTED_SYSTEM_PATHS = original

    def test_symlinked_scan_root_resolving_to_protected_location_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            protected = root / "protected"
            protected.mkdir()
            (protected / "secret.txt").write_text("secret", encoding="utf-8")
            alias = root / "alias"
            try:
                alias.symlink_to(protected, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")
            original = StorageAnalyzerEngine.PROTECTED_SYSTEM_PATHS
            StorageAnalyzerEngine.PROTECTED_SYSTEM_PATHS = {str(protected)}
            try:
                with self.assertRaises(PermissionError):
                    StorageAnalyzerEngine.analyze_directory(str(alias))
            finally:
                StorageAnalyzerEngine.PROTECTED_SYSTEM_PATHS = original

    def test_file_and_directory_symlinks_are_not_counted_or_followed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scan = root / "scan"
            protected = root / "outside"
            scan.mkdir()
            protected.mkdir()
            (protected / "secret.txt").write_text("secret", encoding="utf-8")
            try:
                (scan / "secret-link").symlink_to(protected / "secret.txt")
                (scan / "folder-link").symlink_to(protected, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")

            result = StorageAnalyzerEngine.analyze_directory(str(scan))

        self.assertEqual(result["total_files"], 0)
        self.assertEqual(result["total_size_bytes"], 0)
        self.assertEqual(result["skipped_symlinks"], 2)
        self.assertFalse(result["complete"])

    def test_top_n_must_be_a_non_negative_integer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            for invalid in (-1, 1.5, True, "2"):
                with self.subTest(top_n=invalid):
                    with self.assertRaises(ValueError):
                        StorageAnalyzerEngine.analyze_directory(temp_dir, top_n=invalid)

    def test_zero_top_n_keeps_totals_and_returns_no_largest_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "item.txt").write_text("abc", encoding="utf-8")

            result = StorageAnalyzerEngine.analyze_directory(temp_dir, top_n=0)

        self.assertEqual(result["total_files"], 1)
        self.assertEqual(result["total_size_bytes"], 3)
        self.assertEqual(result["largest_files"], [])
        self.assertTrue(result["complete"])

    def test_walk_permission_error_is_reported_as_incomplete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            denied_path = str(Path(temp_dir) / "restricted")

            def walk_with_error(path, *, topdown, followlinks, onerror):
                error = PermissionError(13, "permission denied", denied_path)
                onerror(error)
                return iter(((path, [], []),))

            with patch("officekit.engines.engine_file_ops.os.walk", side_effect=walk_with_error):
                result = StorageAnalyzerEngine.analyze_directory(temp_dir)

        self.assertFalse(result["complete"])
        self.assertEqual(result["errors"][0]["path"], denied_path)
        self.assertIn("permission denied", result["errors"][0]["error"])

    def test_non_directory_scan_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "plain.txt"
            file_path.write_text("data", encoding="utf-8")

            with self.assertRaises(NotADirectoryError):
                StorageAnalyzerEngine.analyze_directory(str(file_path))


if __name__ == "__main__":
    unittest.main()
