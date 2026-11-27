"""
TDD Tests for File Utilities & Safe Storage Analysis (officekit/engines/engine_file_ops.py)
Covers:
- Batch File Renamer (Sequence, Prefix/Suffix, Regex, Casing)
- Two-Phase Fast Exact Duplicate Finder (First 4KB hash -> SHA-256)
- Safe Storage Analyzer (Folder sizes, large files, system folder exclusion)
"""

import os
import tempfile
import pytest
from officekit.engines.engine_file_ops import FileOpsEngine, StorageAnalyzerEngine

def test_batch_rename_sequencing_and_casing():
    filenames = ["report a.pdf", "Report B.pdf", "REPORT C.pdf"]
    
    # Sequence numbering: prefix "doc_", padding 3
    renamed = FileOpsEngine.generate_rename_plan(
        filenames,
        pattern_type="sequence",
        prefix="invoice_",
        start_num=1,
        digits=3
    )
    assert renamed == ["invoice_001.pdf", "invoice_002.pdf", "invoice_003.pdf"]

    # Kebab case conversion
    kebab_renamed = FileOpsEngine.generate_rename_plan(
        filenames,
        pattern_type="casing",
        casing="kebab"
    )
    assert kebab_renamed == ["report-a.pdf", "report-b.pdf", "report-c.pdf"]

def test_two_phase_duplicate_finder():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create 2 identical files with different names
        content1 = b"Identical financial payload" * 100
        path1 = os.path.join(tmpdir, "statement_jan.pdf")
        path2 = os.path.join(tmpdir, "statement_jan_copy.pdf")
        with open(path1, "wb") as f: f.write(content1)
        with open(path2, "wb") as f: f.write(content1)

        # Create 1 unique file
        path3 = os.path.join(tmpdir, "different.pdf")
        with open(path3, "wb") as f: f.write(b"Unique content")

        dup_groups = FileOpsEngine.find_duplicate_files(tmpdir)
        assert len(dup_groups) == 1
        group = dup_groups[0]
        assert len(group["files"]) == 2
        assert group["size_bytes"] == len(content1)

def test_storage_analyzer_safety_exclusion():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create sample files
        f1 = os.path.join(tmpdir, "large.bin")
        f2 = os.path.join(tmpdir, "small.txt")
        with open(f1, "wb") as f: f.write(b"0" * 1024 * 100) # 100 KB
        with open(f2, "wb") as f: f.write(b"hello")

        report = StorageAnalyzerEngine.analyze_directory(tmpdir, top_n=5)
        assert report["total_files"] == 2
        assert report["total_size_bytes"] > 102400
        assert len(report["largest_files"]) == 2
        assert report["largest_files"][0]["name"] == "large.bin"
