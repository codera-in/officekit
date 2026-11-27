"""Bounded, process-owned workspace tests for local file tools."""

import io
import hashlib
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import officekit.engines.engine_workspaces as engine_workspaces
from officekit.engines.engine_workspaces import FileWorkspaceStore, WorkspaceLimitError


def make_zip(entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


class FileWorkspaceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = FileWorkspaceStore(root=self.temporary.name, max_upload_bytes=1024, max_archive_bytes=32)
        self.workspace_id = self.store.create_workspace()

    def tearDown(self):
        self.temporary.cleanup()

    def test_imports_selected_file_bytes_into_private_workspace(self):
        result = self.store.add_files(self.workspace_id, [("folder/a.txt", io.BytesIO(b"hello"))])

        self.assertEqual(result, [{"name": "folder/a.txt", "size_bytes": 5}])
        stored = os.path.join(self.temporary.name, self.workspace_id, "input", "folder", "a.txt")
        with open(stored, "rb") as file:
            self.assertEqual(file.read(), b"hello")
        if os.name != "nt":
            self.assertEqual(os.stat(os.path.join(self.temporary.name, self.workspace_id)).st_mode & 0o777, 0o700)

    def test_imports_empty_directories_and_compares_directory_structure(self):
        self.store.add_files(
            self.workspace_id,
            [
                ("before/shared.txt", io.BytesIO(b"same")),
                ("after/shared.txt", io.BytesIO(b"same")),
            ],
            directories=[
                "before/empty-only",
                "before/nested/empty",
                "after/nested/empty",
                "after/added",
            ],
        )

        workspace = self.store.get_workspace(self.workspace_id)
        report = self.store.compare_folders(self.workspace_id, "before", "after")

        self.assertEqual(workspace["directories"], [
            "after", "after/added", "after/nested", "after/nested/empty",
            "before", "before/empty-only", "before/nested", "before/nested/empty",
        ])
        self.assertEqual(report["summary"], {"identical": 1, "changed": 0, "left_only": 0, "right_only": 0})
        self.assertEqual(report["directory_summary"], {"identical": 3, "changed": 0, "left_only": 1, "right_only": 1})
        self.assertEqual(report["directories"], [
            {"path": ".", "status": "identical", "left_empty": False, "right_empty": False},
            {"path": "added", "status": "right-only", "left_empty": None, "right_empty": True},
            {"path": "empty-only", "status": "left-only", "left_empty": True, "right_empty": None},
            {"path": "nested", "status": "identical", "left_empty": False, "right_empty": False},
            {"path": "nested/empty", "status": "identical", "left_empty": True, "right_empty": True},
        ])

    def test_compares_two_directories_when_the_selection_has_no_files(self):
        self.store.add_files(self.workspace_id, [], directories=["before", "after"])

        report = self.store.compare_folders(self.workspace_id, "before", "after")

        self.assertEqual(report["files_compared"], 0)
        self.assertEqual(report["files"], [])
        self.assertEqual(report["directories"], [{"path": ".", "status": "identical", "left_empty": True, "right_empty": True}])

    def test_marks_matching_folder_as_changed_when_only_one_side_is_empty(self):
        self.store.add_files(
            self.workspace_id,
            [("after/draft/readme.txt", io.BytesIO(b"content"))],
            directories=["before/draft"],
        )

        report = self.store.compare_folders(self.workspace_id, "before", "after")

        self.assertEqual(report["directory_summary"], {"identical": 1, "changed": 1, "left_only": 0, "right_only": 0})
        self.assertEqual(report["directories"], [
            {"path": ".", "status": "identical", "left_empty": False, "right_empty": False},
            {"path": "draft", "status": "changed", "left_empty": True, "right_empty": False},
        ])

    def test_rejects_unsafe_or_empty_uploaded_names(self):
        for name in (
            "", ".", "../escape.txt", "/absolute.txt", "C:/drive.txt", "folder\\escape.txt",
            "folder/file.txt:stream", "folder/trailing.", "folder/trailing ",
            "folder/CON.txt", "folder/NUL",
        ):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.store.add_files(self.workspace_id, [(name, io.BytesIO(b"x"))])

        for directories in (["../escape"], ["folder/../escape"], ["/absolute"], ["A", "a"]):
            with self.subTest(directories=directories), self.assertRaises(ValueError):
                self.store.add_files(self.workspace_id, [], directories=directories)
        with self.assertRaisesRegex(ValueError, "conflicts with a file"):
            self.store.add_files(self.workspace_id, [("blocker", io.BytesIO(b"x"))], directories=["blocker/child"])
        self.assertEqual(self.store.get_workspace(self.workspace_id)["files"], [])
        self.assertEqual(self.store.get_workspace(self.workspace_id)["directories"], [])

    def test_rejects_directory_count_over_limit_before_creating_workspace_paths(self):
        with self.assertRaises(WorkspaceLimitError):
            self.store.add_files(self.workspace_id, [], directories=[f"folder-{index}" for index in range(10_001)])

        self.assertEqual(self.store.get_workspace(self.workspace_id)["directories"], [])

    def test_rejects_upload_over_limit_and_rolls_back_partial_files(self):
        with self.assertRaises(ValueError):
            self.store.add_files(self.workspace_id, [("ok.txt", io.BytesIO(b"ok")), ("large.txt", io.BytesIO(b"x" * 1025))])

        input_root = os.path.join(self.temporary.name, self.workspace_id, "input")
        self.assertFalse(os.path.exists(os.path.join(input_root, "ok.txt")))

    def test_rejects_too_many_selected_files_before_import(self):
        limited = FileWorkspaceStore(root=self.temporary.name, max_upload_files=1)
        workspace_id = limited.create_workspace()

        with self.assertRaises(ValueError):
            limited.add_files(workspace_id, [("a.txt", io.BytesIO(b"a")), ("b.txt", io.BytesIO(b"b"))])

        self.assertEqual(limited.get_workspace(workspace_id)["files"], [])

    def test_rejects_duplicate_names_without_overwriting_existing_uploads(self):
        self.store.add_files(self.workspace_id, [("A.txt", io.BytesIO(b"first"))])

        with self.assertRaises(ValueError):
            self.store.add_files(self.workspace_id, [("a.TXT", io.BytesIO(b"second"))])

        path = os.path.join(self.temporary.name, self.workspace_id, "input", "A.txt")
        with open(path, "rb") as file:
            self.assertEqual(file.read(), b"first")

    def test_upload_commit_does_not_overwrite_a_file_created_after_collision_check(self):
        input_root = os.path.join(self.temporary.name, self.workspace_id, "input")
        raced_target = os.path.join(input_root, "race.txt")
        original_write = self.store._write_stream
        created = []

        def create_competing_file(source, staged_path, limit, total):
            result = original_write(source, staged_path, limit, total)
            with open(raced_target, "xb") as competitor:
                competitor.write(b"created concurrently")
            created.append(raced_target)
            return result

        with patch.object(self.store, "_write_stream", side_effect=create_competing_file):
            with self.assertRaises(FileExistsError):
                self.store.add_files(self.workspace_id, [("race.txt", io.BytesIO(b"ours"))])

        self.assertTrue(created)
        with open(raced_target, "rb") as competitor:
            self.assertEqual(competitor.read(), b"created concurrently")
        self.assertFalse(any(name.startswith(".upload-") for name in os.listdir(
            os.path.join(self.temporary.name, self.workspace_id)
        )))

    def test_upload_commit_failure_rolls_back_only_files_created_by_that_upload(self):
        original_link = engine_workspaces.os.link
        calls = []

        def fail_second_link(source, target, **options):
            calls.append((source, target))
            if len(calls) == 2:
                raise OSError("simulated filesystem failure")
            return original_link(source, target, **options)

        with patch("officekit.engines.engine_workspaces.os.link", side_effect=fail_second_link):
            with self.assertRaisesRegex(OSError, "simulated filesystem failure"):
                self.store.add_files(self.workspace_id, [
                    ("first.txt", io.BytesIO(b"first")),
                    ("second.txt", io.BytesIO(b"second")),
                ])

        self.assertEqual(len(calls), 2)
        self.assertEqual(self.store.get_workspace(self.workspace_id)["files"], [])

    def test_rejects_unicode_canonical_equivalent_names(self):
        self.store.add_files(self.workspace_id, [("Café.txt", io.BytesIO(b"first"))])

        with self.assertRaisesRegex(ValueError, "Duplicate file name"):
            self.store.add_files(self.workspace_id, [("Cafe\u0301.txt", io.BytesIO(b"second"))])

        files = self.store.get_workspace(self.workspace_id)["files"]
        self.assertEqual(len(files), 1)
        path = os.path.join(
            self.temporary.name, self.workspace_id, "input", *files[0]["name"].split("/")
        )
        with open(path, "rb") as stored:
            self.assertEqual(stored.read(), b"first")

        batch_workspace = self.store.create_workspace()
        with self.assertRaisesRegex(ValueError, "Duplicate file name"):
            self.store.add_files(batch_workspace, [
                ("Café.txt", io.BytesIO(b"first")),
                ("Cafe\u0301.txt", io.BytesIO(b"second")),
            ])
        self.assertEqual(self.store.get_workspace(batch_workspace)["files"], [])

    def test_extracts_safe_archive_and_creates_download_bundle(self):
        self.store.add_files(self.workspace_id, [("project.zip", io.BytesIO(make_zip([("docs/readme.txt", b"read me"), ("logo.svg", b"<svg/>")])) )])

        result = self.store.extract_archive(self.workspace_id, "project.zip", "extracted")

        self.assertEqual(result["file_count"], 2)
        self.assertEqual(result["files"], ["docs/readme.txt", "logo.svg"])
        with zipfile.ZipFile(self.store.artifact_path(self.workspace_id, result["artifact_id"])) as archive:
            self.assertEqual(archive.read("extracted/docs/readme.txt"), b"read me")

    def test_rejects_zip_slip_and_leaves_no_artifact(self):
        self.store.add_files(self.workspace_id, [("evil.zip", io.BytesIO(make_zip([("../escape.txt", b"bad")])) )])

        with self.assertRaises(ValueError):
            self.store.extract_archive(self.workspace_id, "evil.zip", "out")

        self.assertFalse(os.path.exists(os.path.join(self.temporary.name, "escape.txt")))

    def test_rejects_symlink_entries_in_archive(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = (0o120777 << 16)
            archive.writestr(info, "target")
        self.store.add_files(self.workspace_id, [("link.zip", io.BytesIO(buffer.getvalue()))])

        with self.assertRaises(ValueError):
            self.store.extract_archive(self.workspace_id, "link.zip", "out")

    def test_extract_archive_rejects_source_replaced_by_symlink_after_validation(self):
        self.store.add_files(self.workspace_id, [
            ("archive.zip", io.BytesIO(make_zip([("inside.txt", b"safe")]))),
        ])
        external_archive = os.path.join(self.temporary.name, "external.zip")
        with open(external_archive, "wb") as file:
            file.write(make_zip([("outside-secret.txt", b"must not be read")]))

        source_path = os.path.join(
            self.temporary.name, self.workspace_id, "input", "archive.zip"
        )
        original_islink = engine_workspaces.os.path.islink
        swapped = []

        def swap_after_validation(path):
            if os.path.abspath(os.fspath(path)) == os.path.abspath(source_path) and not original_islink(path):
                os.unlink(path)
                os.symlink(external_archive, path)
                swapped.append(path)
                return False
            return original_islink(path)

        with patch("officekit.engines.engine_workspaces.os.path.islink", side_effect=swap_after_validation):
            with self.assertRaises(FileNotFoundError):
                self.store.extract_archive(self.workspace_id, "archive.zip", "extracted")

        self.assertTrue(swapped, "test did not replace the archive after its path validation")
        workspace = os.path.join(self.temporary.name, self.workspace_id)
        outputs = os.path.join(workspace, "outputs")
        self.assertFalse(os.path.isdir(outputs) and os.listdir(outputs))
        self.assertFalse(any(name.startswith(".extract-") for name in os.listdir(workspace)))

    def test_rejects_canonical_path_and_file_directory_collisions_atomically(self):
        archive_cases = [
            [
                ("Caf\u00e9/report.txt", b"first"),
                ("Cafe\u0301/report.txt", b"second"),
            ],
            [("folder", b"file"), ("folder/report.txt", b"child")],
            [("folder/report.txt", b"child"), ("folder", b"file")],
        ]

        for index, entries in enumerate(archive_cases):
            with self.subTest(entries=entries):
                archive_name = f"collision-{index}.zip"
                self.store.add_files(self.workspace_id, [(archive_name, io.BytesIO(make_zip(entries)))])
                with self.assertRaisesRegex(ValueError, "collid|duplicate|conflict"):
                    self.store.extract_archive(self.workspace_id, archive_name, f"output-{index}")
                outputs = os.path.join(self.temporary.name, self.workspace_id, "outputs")
                self.assertFalse(os.path.isdir(outputs) and os.listdir(outputs))
                self.assertFalse(any(name.startswith(".extract-") for name in os.listdir(
                    os.path.join(self.temporary.name, self.workspace_id)
                )))

    def test_rejects_oversized_archives_and_output_name_collisions(self):
        self.store.add_files(self.workspace_id, [("large.zip", io.BytesIO(make_zip([("large.txt", b"x" * 33)])))])
        with self.assertRaises(ValueError):
            self.store.extract_archive(self.workspace_id, "large.zip", "out")

        self.store.add_files(self.workspace_id, [("small.zip", io.BytesIO(make_zip([("ok.txt", b"ok")])))])
        first = self.store.extract_archive(self.workspace_id, "small.zip", "out")
        second = self.store.extract_archive(self.workspace_id, "small.zip", "out")
        self.assertNotEqual(first["artifact_id"], second["artifact_id"])

    def test_rejects_nonexistent_workspace_and_archive(self):
        with self.assertRaises(FileNotFoundError):
            self.store.add_files("0" * 32, [("a.txt", io.BytesIO(b"x"))])
        with self.assertRaises(FileNotFoundError):
            self.store.extract_archive(self.workspace_id, "missing.zip", "out")

    def test_clear_removes_only_the_requested_workspace(self):
        other_id = self.store.create_workspace()
        self.store.add_files(self.workspace_id, [("a.txt", io.BytesIO(b"x"))])

        self.store.clear_workspace(self.workspace_id)

        with self.assertRaises(FileNotFoundError):
            self.store.get_workspace(self.workspace_id)
        self.assertEqual(self.store.get_workspace(other_id), {"workspace_id": other_id, "files": [], "directories": []})

    def test_hashes_only_selected_workspace_files_in_requested_order(self):
        self.store.add_files(self.workspace_id, [
            ("folder/a.txt", io.BytesIO(b"alpha")),
            ("folder/empty.txt", io.BytesIO(b"")),
            ("other.txt", io.BytesIO(b"not selected")),
        ])

        result = self.store.hash_files(self.workspace_id, ["folder/empty.txt", "folder/a.txt"])

        self.assertEqual(result["algorithm"], "sha256")
        self.assertEqual(result["total_bytes"], 5)
        self.assertEqual(result["files"], [
            {"name": "folder/empty.txt", "size_bytes": 0, "digest": hashlib.sha256(b"").hexdigest()},
            {"name": "folder/a.txt", "size_bytes": 5, "digest": hashlib.sha256(b"alpha").hexdigest()},
        ])

    def test_hashes_allow_sha512_and_reject_unknown_algorithms(self):
        self.store.add_files(self.workspace_id, [("a.txt", io.BytesIO(b"alpha"))])
        result = self.store.hash_files(self.workspace_id, ["a.txt"], algorithm="sha512")
        self.assertEqual(result["files"][0]["digest"], hashlib.sha512(b"alpha").hexdigest())

        for algorithm in ("md5", "sha1", "sha3_256", "SHA256", None):
            with self.subTest(algorithm=algorithm), self.assertRaises(ValueError):
                self.store.hash_files(self.workspace_id, ["a.txt"], algorithm=algorithm)

    def test_hash_rejects_empty_duplicate_missing_and_unsafe_selection(self):
        self.store.add_files(self.workspace_id, [("a.txt", io.BytesIO(b"alpha"))])
        for filenames in ([], ["a.txt", "a.txt"], ["missing.txt"], ["../outside.txt"], "a.txt"):
            with self.subTest(filenames=filenames), self.assertRaises((ValueError, FileNotFoundError)):
                self.store.hash_files(self.workspace_id, filenames)

        with self.assertRaisesRegex(ValueError, "between 1 and 1000"):
            self.store.hash_files(self.workspace_id, [f"{index}.txt" for index in range(1001)])

    def test_hash_rejects_files_changed_to_exceed_workspace_byte_budget(self):
        self.store.add_files(self.workspace_id, [("a.txt", io.BytesIO(b"alpha"))])
        path = os.path.join(self.temporary.name, self.workspace_id, "input", "a.txt")
        with open(path, "wb") as file:
            file.write(b"x" * 1025)

        with self.assertRaises(WorkspaceLimitError):
            self.store.hash_files(self.workspace_id, ["a.txt"])

    @unittest.skipIf(sys.platform == "win32", "Symlink/inode swap verification is POSIX-specific")
    def test_hash_rejects_symlink_and_path_swap_without_reading_external_file(self):
        self.store.add_files(self.workspace_id, [("link.txt", io.BytesIO(b"inside"))])
        input_root = os.path.join(self.temporary.name, self.workspace_id, "input")
        selected_path = os.path.realpath(os.path.join(input_root, "link.txt"))
        outside_path = os.path.join(self.temporary.name, "outside.txt")
        with open(outside_path, "wb") as file:
            file.write(b"secret external data")

        os.unlink(selected_path)
        try:
            os.symlink(outside_path, selected_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"platform does not permit test symlink creation: {error}")
        with self.assertRaises(FileNotFoundError):
            self.store.hash_files(self.workspace_id, ["link.txt"])

        os.unlink(selected_path)
        with open(selected_path, "wb") as file:
            file.write(b"inside")
        original_open = engine_workspaces.os.open
        swapped = []
        seen_paths = []

        def swap_before_open(path, flags, *args, **kwargs):
            seen_paths.append(path)
            if os.path.abspath(os.fspath(path)) == os.path.abspath(selected_path):
                swapped.append(path)
                os.unlink(path)
                os.symlink(outside_path, path)
            return original_open(path, flags, *args, **kwargs)

        with patch("officekit.engines.engine_workspaces.os.open", side_effect=swap_before_open):
            with self.assertRaises(FileNotFoundError):
                self.store.hash_files(self.workspace_id, ["link.txt"])
        self.assertTrue(swapped, msg=f"open paths were: {seen_paths!r}; expected: {selected_path!r}")

    def test_hash_stream_reads_in_bounded_chunks_and_reports_limit(self):
        class RecordingReader(io.BytesIO):
            def __init__(self, data):
                super().__init__(data)
                self.read_sizes = []

            def read(self, size=-1):
                self.read_sizes.append(size)
                return super().read(size)

        payload = b"x" * (FileWorkspaceStore.HASH_CHUNK_SIZE * 2 + 17)
        reader = RecordingReader(payload)
        digest = hashlib.sha256()
        read = FileWorkspaceStore._digest_stream(reader, digest, len(payload))
        self.assertEqual(read, len(payload))
        self.assertEqual(digest.hexdigest(), hashlib.sha256(payload).hexdigest())
        self.assertTrue(reader.read_sizes)
        self.assertTrue(all(size == FileWorkspaceStore.HASH_CHUNK_SIZE for size in reader.read_sizes))

        with self.assertRaises(WorkspaceLimitError):
            FileWorkspaceStore._digest_stream(RecordingReader(payload), hashlib.sha256(), len(payload) - 1)

    def test_file_type_report_detects_content_extension_mismatch_and_empty_files(self):
        self.store.add_files(self.workspace_id, [
            ("photos/renamed.jpg", io.BytesIO(b"\x89PNG\r\n\x1a\nimage payload")),
            ("statement.pdf", io.BytesIO(b"%PDF-1.7\nbody")),
            ("table.csv", io.BytesIO(b"name,value\na,1\n")),
            ("empty.bin", io.BytesIO(b"")),
            ("mystery.bin", io.BytesIO(b"\x00\xff\x02\x80")),
        ])

        report = self.store.file_type_report(self.workspace_id, [
            "photos/renamed.jpg", "statement.pdf", "table.csv", "empty.bin", "mystery.bin",
        ])

        self.assertEqual(report["total_files"], 5)
        self.assertTrue(report["complete"])
        detected = {item["name"]: item for item in report["files"]}
        self.assertEqual(detected["photos/renamed.jpg"]["detected_type"], "PNG")
        self.assertFalse(detected["photos/renamed.jpg"]["extension_matches"])
        self.assertTrue(detected["statement.pdf"]["extension_matches"])
        self.assertEqual(detected["table.csv"]["detected_type"], "Text")
        self.assertIsNone(detected["table.csv"]["extension_matches"])
        self.assertEqual(detected["empty.bin"]["detected_type"], "Empty file")
        self.assertEqual(detected["mystery.bin"]["detected_type"], "Unknown binary")
        self.assertNotIn(self.temporary.name, repr(report))

    def test_file_type_report_rejects_unsafe_duplicate_and_missing_selection(self):
        self.store.add_files(self.workspace_id, [("photo.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"))])

        for selection in ([], ["photo.png", "photo.png"], ["../outside.png"], ["missing.png"]):
            with self.subTest(selection=selection), self.assertRaises((ValueError, FileNotFoundError)):
                self.store.file_type_report(self.workspace_id, selection)

        with self.assertRaises(FileNotFoundError):
            self.store.file_type_report("0" * 32, ["photo.png"])

    def test_preview_rename_generates_safe_names_for_selected_workspace_files(self):
        self.store.add_files(self.workspace_id, [
            ("invoices/jan report.csv", io.BytesIO(b"jan")),
            ("invoices/feb report.csv", io.BytesIO(b"feb")),
            ("notes.txt", io.BytesIO(b"unchanged")),
        ])

        preview = self.store.preview_rename(
            self.workspace_id,
            ["invoices/jan report.csv", "invoices/feb report.csv"],
            pattern_type="sequence",
            prefix="invoice_",
            start_num=1,
            digits=2,
        )

        self.assertEqual(
            preview,
            [
                {"source": "invoices/jan report.csv", "target": "invoices/invoice_01.csv", "size_bytes": 3},
                {"source": "invoices/feb report.csv", "target": "invoices/invoice_02.csv", "size_bytes": 3},
            ],
        )

    def test_preview_rename_affixes_and_replaces_literal_text_without_losing_extensions(self):
        self.store.add_files(self.workspace_id, [
            ("before/photo one.jpg", io.BytesIO(b"one")),
            ("before/photo two.jpg", io.BytesIO(b"two")),
        ])

        affixed = self.store.preview_rename(
            self.workspace_id,
            ["before/photo one.jpg", "before/photo two.jpg"],
            pattern_type="affix",
            prefix="edited_",
            suffix="_final",
        )
        replaced = self.store.preview_rename(
            self.workspace_id,
            ["before/photo one.jpg"],
            pattern_type="replace",
            find_text="photo",
            replace_text="image",
        )

        self.assertEqual([item["target"] for item in affixed], [
            "before/edited_photo one_final.jpg", "before/edited_photo two_final.jpg"
        ])
        self.assertEqual(replaced[0]["target"], "before/image one.jpg")

    def test_preview_rename_preserves_unicode_letters_when_changing_case(self):
        self.store.add_files(self.workspace_id, [("Résumé файл 2.txt", io.BytesIO(b"ok"))])

        preview = self.store.preview_rename(
            self.workspace_id,
            ["Résumé файл 2.txt"],
            pattern_type="casing",
            casing="kebab",
        )

        self.assertEqual(preview[0]["target"], "résumé-файл-2.txt")

    def test_preview_rename_rejects_path_components_and_trailing_dots(self):
        self.store.add_files(self.workspace_id, [("report", io.BytesIO(b"ok"))])

        for options in (
            {"pattern_type": "replace", "find_text": "report", "replace_text": "nested/path"},
            {"pattern_type": "affix", "suffix": "."},
        ):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    self.store.preview_rename(self.workspace_id, ["report"], **options)

    def test_preview_rename_rejects_duplicates_missing_files_and_unsafe_targets(self):
        self.store.add_files(self.workspace_id, [("report.txt", io.BytesIO(b"data"))])

        for selected, options in (
            (["report.txt", "report.txt"], {}),
            (["missing.txt"], {}),
            (["report.txt"], {"pattern_type": "affix", "prefix": "../"}),
            (["report.txt"], {"pattern_type": "affix", "prefix": "CON."}),
            (["report.txt"], {"pattern_type": "replace", "find_text": "report", "replace_text": "bad?name"}),
            (["report.txt"], {"pattern_type": "replace", "find_text": ""}),
            (["report.txt"], {"pattern_type": "unknown"}),
            ([], {}),
        ):
            with self.subTest(selected=selected, options=options):
                with self.assertRaises((ValueError, FileNotFoundError)):
                    self.store.preview_rename(self.workspace_id, selected, **options)

    def test_preview_rename_rejects_selection_over_the_configured_file_limit(self):
        limited = FileWorkspaceStore(root=self.temporary.name, max_upload_files=1)
        workspace_id = limited.create_workspace()
        limited.add_files(workspace_id, [("one.txt", io.BytesIO(b"1"))])

        with self.assertRaises(ValueError):
            limited.preview_rename(workspace_id, ["one.txt", "two.txt"])

    def test_preview_rename_rejects_exact_and_casefolded_collisions(self):
        self.store.add_files(self.workspace_id, [
            ("source.txt", io.BytesIO(b"source")),
            ("target.txt", io.BytesIO(b"target")),
            ("REPORT.txt", io.BytesIO(b"other")),
            ("Café.txt", io.BytesIO(b"unicode")),
        ])

        for selected, options in (
            (["source.txt"], {"pattern_type": "replace", "find_text": "source", "replace_text": "target"}),
            (["source.txt"], {"pattern_type": "replace", "find_text": "source", "replace_text": "report"}),
            (["source.txt"], {"pattern_type": "replace", "find_text": "source", "replace_text": "Cafe\u0301"}),
        ):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    self.store.preview_rename(self.workspace_id, selected, **options)

    def test_preview_rename_rejects_two_selected_files_with_same_target_name(self):
        self.store.add_files(self.workspace_id, [
            ("a.txt", io.BytesIO(b"A")),
            ("b.txt", io.BytesIO(b"B")),
        ])

        with self.assertRaises(ValueError):
            self.store.preview_rename(
                self.workspace_id,
                ["a.txt", "b.txt"],
                pattern_type="replace",
                find_text="a",
                replace_text="b",
            )

    def test_create_renamed_artifact_is_downloadable_and_preserves_source_copies(self):
        self.store.add_files(self.workspace_id, [
            ("folder/first.txt", io.BytesIO(b"first")),
            ("folder/second.txt", io.BytesIO(b"second")),
        ])
        rename_request = {
            "pattern_type": "sequence",
            "prefix": "renamed_",
            "start_num": 1,
            "digits": 1,
        }
        before = self.store.preview_rename(
            self.workspace_id, ["folder/first.txt", "folder/second.txt"], **rename_request
        )

        result = self.store.create_renamed_artifact(
            self.workspace_id, ["folder/first.txt", "folder/second.txt"], **rename_request
        )

        self.assertEqual(result["file_count"], 2)
        with zipfile.ZipFile(self.store.artifact_path(self.workspace_id, result["artifact_id"])) as archive:
            self.assertEqual(archive.read("renamed/folder/renamed_1.txt"), b"first")
            self.assertEqual(archive.read("renamed/folder/renamed_2.txt"), b"second")
        workspace = self.store.get_workspace(self.workspace_id)
        self.assertEqual([item["name"] for item in workspace["files"]], ["folder/first.txt", "folder/second.txt"])
        self.assertEqual([item["target"] for item in before], ["folder/renamed_1.txt", "folder/renamed_2.txt"])

    def test_create_renamed_artifact_never_replaces_an_existing_empty_artifact_directory(self):
        self.store.add_files(self.workspace_id, [("report.txt", io.BytesIO(b"data"))])
        artifact_id = "e" * 32
        workspace_root = Path(self.temporary.name, self.workspace_id)
        collision = workspace_root / "outputs" / artifact_id
        collision.mkdir(parents=True)

        with patch("officekit.engines.engine_workspaces.uuid.uuid4", return_value=engine_workspaces.uuid.UUID(hex=artifact_id)):
            with self.assertRaises(FileExistsError):
                self.store.create_renamed_artifact(
                    self.workspace_id, ["report.txt"], pattern_type="affix", suffix="-copy"
                )

        self.assertTrue(collision.is_dir())
        self.assertEqual(list(collision.iterdir()), [])
        self.assertFalse(any(name.startswith(".rename-") for name in os.listdir(workspace_root)))
        self.assertEqual(self.store.get_workspace(self.workspace_id)["files"][0]["name"], "report.txt")

    def test_create_renamed_artifact_removes_its_reserved_directory_if_publish_fails(self):
        self.store.add_files(self.workspace_id, [("report.txt", io.BytesIO(b"data"))])
        artifact_id = "f" * 32
        workspace_root = Path(self.temporary.name, self.workspace_id)
        real_replace = os.replace

        def fail_bundle_publish(source, destination):
            if os.fspath(destination).endswith(os.path.join(artifact_id, "bundle.zip")):
                raise OSError("publish failed")
            return real_replace(source, destination)

        with patch("officekit.engines.engine_workspaces.uuid.uuid4", return_value=engine_workspaces.uuid.UUID(hex=artifact_id)), \
             patch("officekit.engines.engine_workspaces.os.replace", side_effect=fail_bundle_publish):
            with self.assertRaisesRegex(OSError, "publish failed"):
                self.store.create_renamed_artifact(
                    self.workspace_id, ["report.txt"], pattern_type="affix", suffix="-copy"
                )

        self.assertFalse((workspace_root / "outputs" / artifact_id).exists())
        self.assertFalse(any(name.startswith(".rename-") for name in os.listdir(workspace_root)))
        self.assertEqual(self.store.get_workspace(self.workspace_id)["files"][0]["name"], "report.txt")

    def test_create_renamed_artifact_does_not_publish_a_partial_artifact_on_failure(self):
        self.store.add_files(self.workspace_id, [("report.txt", io.BytesIO(b"data"))])

        with self.assertRaises(ValueError):
            self.store.create_renamed_artifact(
                self.workspace_id,
                ["report.txt"],
                pattern_type="affix",
                prefix="../",
            )

        workspace_root = os.path.join(self.temporary.name, self.workspace_id)
        self.assertEqual(os.listdir(os.path.join(workspace_root, "outputs")) if os.path.isdir(os.path.join(workspace_root, "outputs")) else [], [])
        self.assertEqual(self.store.get_workspace(self.workspace_id)["files"][0]["name"], "report.txt")

    def test_create_renamed_artifact_cleans_staging_when_copy_fails(self):
        self.store.add_files(self.workspace_id, [("report.txt", io.BytesIO(b"data"))])

        with patch.object(self.store, "_copy_workspace_file", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.store.create_renamed_artifact(
                    self.workspace_id, ["report.txt"], pattern_type="affix", suffix="-copy"
                )

        workspace_root = os.path.join(self.temporary.name, self.workspace_id)
        self.assertFalse(any(name.startswith(".rename-") for name in os.listdir(workspace_root)))
        self.assertFalse(os.path.exists(os.path.join(workspace_root, "outputs")))
        self.assertEqual(self.store.get_workspace(self.workspace_id)["files"][0]["name"], "report.txt")

    def test_create_renamed_artifact_rejects_a_source_replaced_by_symlink_after_validation(self):
        self.store.add_files(self.workspace_id, [("report.txt", io.BytesIO(b"private copy"))])
        source = Path(self.temporary.name, self.workspace_id, "input", "report.txt")
        external = Path(self.temporary.name, "outside.txt")
        external.write_bytes(b"outside secret")
        original_islink = os.path.islink
        original_preview = self.store.preview_rename
        plan_ready = False

        def validated_plan(*args, **kwargs):
            nonlocal plan_ready
            plan = original_preview(*args, **kwargs)
            plan_ready = True
            return plan

        def replace_after_islink_check(path):
            result = original_islink(path)
            if plan_ready and os.path.realpath(path) == os.path.realpath(source) and not result:
                source.unlink()
                try:
                    source.symlink_to(external)
                except OSError:
                    self.skipTest("symlink creation is unavailable")
            return result

        with patch.object(self.store, "preview_rename", side_effect=validated_plan), \
             patch("officekit.engines.engine_workspaces.os.path.islink", side_effect=replace_after_islink_check):
            try:
                self.store.create_renamed_artifact(
                    self.workspace_id, ["report.txt"], pattern_type="affix", suffix="-copy"
                )
            except FileNotFoundError:
                pass
            else:
                self.fail("Expected no-follow copy to reject a symlink inserted after rename validation")

        workspace_root = os.path.join(self.temporary.name, self.workspace_id)
        self.assertFalse(any(name.startswith(".rename-") for name in os.listdir(workspace_root)))
        self.assertFalse(os.path.exists(os.path.join(workspace_root, "outputs")))
        self.assertEqual(external.read_bytes(), b"outside secret")

    def test_create_renamed_artifact_fails_if_a_selected_source_disappears(self):
        self.store.add_files(self.workspace_id, [("report.txt", io.BytesIO(b"data"))])

        with patch.object(self.store, "preview_rename", return_value=[{
            "source": "report.txt", "target": "report-copy.txt", "size_bytes": 4,
        }]), patch("officekit.engines.engine_workspaces.os.path.isfile", return_value=False):
            with self.assertRaises(FileNotFoundError):
                self.store.create_renamed_artifact(self.workspace_id, ["report.txt"])

        workspace_root = os.path.join(self.temporary.name, self.workspace_id)
        self.assertFalse(any(name.startswith(".rename-") for name in os.listdir(workspace_root)))

    def test_duplicate_report_uses_workspace_relative_names_and_includes_empty_duplicates(self):
        self.store.add_files(self.workspace_id, [
            ("one/report.csv", io.BytesIO(b"same bytes")),
            ("two/copy.csv", io.BytesIO(b"same bytes")),
            ("empty-a.bin", io.BytesIO(b"")),
            ("empty-b.bin", io.BytesIO(b"")),
            ("unique.txt", io.BytesIO(b"different")),
        ])

        report = self.store.find_duplicate_report(self.workspace_id)

        self.assertTrue(report["complete"])
        groups_by_name = {tuple(group["files"]): group for group in report["groups"]}
        self.assertIn(("empty-a.bin", "empty-b.bin"), groups_by_name)
        self.assertIn(("one/report.csv", "two/copy.csv"), groups_by_name)
        self.assertEqual(groups_by_name[("empty-a.bin", "empty-b.bin")]["size_bytes"], 0)
        self.assertEqual(report["files_scanned"], 5)
        self.assertNotIn(self.temporary.name, repr(report))

    def test_duplicate_report_exposes_incomplete_scan_and_rejects_invalid_limits(self):
        self.store.add_files(self.workspace_id, [
            ("one.txt", io.BytesIO(b"same")),
            ("two.txt", io.BytesIO(b"same")),
        ])

        report = self.store.find_duplicate_report(self.workspace_id, max_entries=1)

        self.assertFalse(report["complete"])
        self.assertTrue(report["errors"])
        for limit in (0, -1, 1.5, True):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    self.store.find_duplicate_report(self.workspace_id, max_entries=limit)

    def test_duplicate_report_never_returns_paths_outside_its_workspace(self):
        report = {
            "groups": [{"hash": "f" * 64, "size_bytes": 1, "files": ["/private/outside/secret.txt"]}],
            "files_scanned": 2,
            "skipped_symlinks": 0,
            "complete": True,
            "errors": [{"path": "/private/outside/secret.txt", "error": "private path"}],
        }
        with patch("officekit.engines.engine_workspaces.FileOpsEngine.find_duplicate_files_report", return_value=report):
            result = self.store.find_duplicate_report(self.workspace_id)

        self.assertFalse(result["complete"])
        self.assertEqual(result["groups"][0]["files"], [])
        self.assertEqual(result["errors"][0], {
            "name": None,
            "message": "A file could not be read during the duplicate scan.",
        })
        self.assertNotIn("/private/outside", repr(result))

    def test_duplicate_report_marks_unmappable_relative_paths_incomplete(self):
        report = {
            "groups": [{"hash": "f" * 64, "size_bytes": 1, "files": ["/private/outside/file.txt"]}],
            "files_scanned": 1,
            "skipped_symlinks": 0,
            "complete": True,
            "errors": [],
        }
        with patch("officekit.engines.engine_workspaces.FileOpsEngine.find_duplicate_files_report", return_value=report), \
             patch("officekit.engines.engine_workspaces.os.path.relpath", side_effect=ValueError("different volumes")):
            result = self.store.find_duplicate_report(self.workspace_id)

        self.assertFalse(result["complete"])
        self.assertEqual(result["groups"][0]["files"], [])

    def test_storage_report_returns_nested_relative_names_and_no_host_paths(self):
        self.store.add_files(self.workspace_id, [
            ("docs/manual.pdf", io.BytesIO(b"x" * 12)),
            ("manual.pdf", io.BytesIO(b"y" * 5)),
        ])

        report = self.store.storage_report(self.workspace_id, top_n=10)

        self.assertEqual(report["total_files"], 2)
        self.assertEqual(report["total_size_bytes"], 17)
        self.assertEqual(report["largest_files"][0]["name"], "docs/manual.pdf")
        self.assertTrue(report["complete"])
        self.assertNotIn(self.temporary.name, repr(report))
        self.assertNotIn("scanned_path", report)

    def test_storage_report_includes_recursive_folder_totals_in_deterministic_order(self):
        self.store.add_files(self.workspace_id, [
            ("reports/january.csv", io.BytesIO(b"a" * 100)),
            ("reports/nested/q1.csv", io.BytesIO(b"b" * 300)),
            ("media/photo.jpg", io.BytesIO(b"c" * 50)),
            ("root.txt", io.BytesIO(b"d" * 20)),
        ])

        report = self.store.storage_report(self.workspace_id, top_n=2)

        self.assertEqual(report["total_files"], 4)
        self.assertEqual(report["total_size_bytes"], 470)
        self.assertEqual(report["largest_folders"], [
            {"name": "reports", "file_count": 2, "size_bytes": 400},
            {"name": "reports/nested", "file_count": 1, "size_bytes": 300},
        ])
        self.assertNotIn(self.temporary.name, repr(report))

    def test_storage_report_sorts_equal_size_files_and_folders_stably_and_honors_zero_limit(self):
        self.store.add_files(self.workspace_id, [
            ("zeta/same.bin", io.BytesIO(b"aa")),
            ("Alpha/same.bin", io.BytesIO(b"bb")),
        ])

        report = self.store.storage_report(self.workspace_id, top_n=10)
        empty_top = self.store.storage_report(self.workspace_id, top_n=0)

        self.assertEqual([item["name"] for item in report["largest_files"]], [
            "Alpha/same.bin", "zeta/same.bin",
        ])
        self.assertEqual([item["name"] for item in report["largest_folders"]], ["Alpha", "zeta"])
        self.assertEqual(empty_top["total_files"], 2)
        self.assertEqual(empty_top["total_size_bytes"], 4)
        self.assertEqual(empty_top["largest_files"], [])
        self.assertEqual(empty_top["largest_folders"], [])

    def test_storage_report_handles_empty_workspaces_and_validates_result_limit(self):
        report = self.store.storage_report(self.workspace_id)

        self.assertEqual(report, {
            "total_files": 0,
            "total_size_bytes": 0,
            "total_size_mb": 0.0,
            "largest_files": [],
            "largest_folders": [],
            "complete": True,
            "skipped_symlinks": 0,
            "errors": [],
        })
        for top_n in (-1, 1001, 1.5, True):
            with self.subTest(top_n=top_n):
                with self.assertRaises(ValueError):
                    self.store.storage_report(self.workspace_id, top_n=top_n)

    def test_storage_report_never_returns_diagnostics_with_host_paths(self):
        workspace_input = os.path.realpath(os.path.join(self.temporary.name, self.workspace_id, "input"))
        file_path = os.path.join(workspace_input, "a.txt")
        report = {
            "scanned_path": workspace_input,
            "total_files": 1,
            "total_size_bytes": 0,
            "total_size_mb": 0.0,
            "largest_files": [{"name": "a.txt", "path": file_path, "size_bytes": 0, "size_mb": 0.0}],
            "largest_folders": [{"name": "../outside", "file_count": 1, "size_bytes": 0}],
            "complete": False,
            "skipped_symlinks": 0,
            "errors": [{"path": file_path, "error": "private path text"}],
        }
        self.store.add_files(self.workspace_id, [("a.txt", io.BytesIO(b""))])
        with patch("officekit.engines.engine_workspaces.StorageAnalyzerEngine.analyze_directory", return_value=report):
            result = self.store.storage_report(self.workspace_id)

        self.assertNotIn(self.temporary.name, repr(result))
        self.assertEqual(result["errors"], [{
            "name": "a.txt", "message": "A file could not be read during the storage scan."
        }])
        self.assertEqual(result["largest_folders"], [])

    def test_folder_comparison_classifies_recursive_content_and_preserves_sources(self):
        self.store.add_files(self.workspace_id, [
            ("before/same.txt", io.BytesIO(b"unchanged")),
            ("after/same.txt", io.BytesIO(b"unchanged")),
            ("before/nested/changed.bin", io.BytesIO(b"old bytes")),
            ("after/nested/changed.bin", io.BytesIO(b"new bytes")),
            ("before/removed.txt", io.BytesIO(b"left")),
            ("after/added.txt", io.BytesIO(b"right")),
        ])

        report = self.store.compare_folders(self.workspace_id, "before", "after")

        self.assertEqual(report["summary"], {
            "identical": 1, "changed": 1, "left_only": 1, "right_only": 1,
        })
        self.assertEqual(report["files"], [
            {"path": "added.txt", "status": "right-only", "left_name": None,
             "right_name": "after/added.txt", "left_size_bytes": None, "right_size_bytes": 5,
             "left_sha256": None, "right_sha256": hashlib.sha256(b"right").hexdigest()},
            {"path": "nested/changed.bin", "status": "changed",
             "left_name": "before/nested/changed.bin", "right_name": "after/nested/changed.bin",
             "left_size_bytes": 9, "right_size_bytes": 9,
             "left_sha256": hashlib.sha256(b"old bytes").hexdigest(),
             "right_sha256": hashlib.sha256(b"new bytes").hexdigest()},
            {"path": "removed.txt", "status": "left-only", "left_name": "before/removed.txt",
             "right_name": None, "left_size_bytes": 4, "right_size_bytes": None,
             "left_sha256": hashlib.sha256(b"left").hexdigest(), "right_sha256": None},
            {"path": "same.txt", "status": "identical", "left_name": "before/same.txt",
             "right_name": "after/same.txt", "left_size_bytes": 9, "right_size_bytes": 9,
             "left_sha256": hashlib.sha256(b"unchanged").hexdigest(),
             "right_sha256": hashlib.sha256(b"unchanged").hexdigest()},
        ])
        self.assertTrue(report["complete"])
        self.assertEqual([item["name"] for item in self.store.get_workspace(self.workspace_id)["files"]], [
            "after/added.txt", "after/nested/changed.bin", "after/same.txt",
            "before/nested/changed.bin", "before/removed.txt", "before/same.txt",
        ])

    def test_folder_comparison_rejects_unsafe_overlapping_missing_and_over_budget_scopes(self):
        self.store.add_files(self.workspace_id, [
            ("before/a.txt", io.BytesIO(b"123")),
            ("after/a.txt", io.BytesIO(b"456")),
        ])
        for left, right in (
            ("../before", "after"), ("before", "before"),
            ("before", "before/nested"), ("missing", "after"),
        ):
            with self.subTest(left=left, right=right), self.assertRaises((ValueError, FileNotFoundError)):
                self.store.compare_folders(self.workspace_id, left, right)

        self.store.max_upload_bytes = 5
        with self.assertRaises(WorkspaceLimitError):
            self.store.compare_folders(self.workspace_id, "before", "after")

    def test_similar_image_report_passes_only_selected_workspace_files(self):
        self.store.add_files(self.workspace_id, [
            ("burst/one.jpg", io.BytesIO(b"one")),
            ("burst/two.jpg", io.BytesIO(b"two")),
            ("notes.txt", io.BytesIO(b"skip")),
        ])
        expected_input = os.path.realpath(os.path.join(self.temporary.name, self.workspace_id, "input"))
        fake_report = {
            "pairs": [{"left": "burst/one.jpg", "right": "burst/two.jpg", "distance": 2}],
            "groups": [{"files": ["burst/one.jpg", "burst/two.jpg"]}],
            "scanned_images": 2,
            "skipped_files": ["notes.txt"],
            "errors": [],
            "complete": True,
            "method": "dct-perceptual-hash",
            "frames_per_file": 1,
        }
        with patch("officekit.engines.engine_workspaces.SimilarImageEngine.scan_files", return_value=fake_report) as scan:
            report = self.store.similar_image_report(self.workspace_id, ["burst/one.jpg", "burst/two.jpg"])

        files = scan.call_args.args[0]
        self.assertEqual({name for name, _ in files}, {"burst/one.jpg", "burst/two.jpg"})
        self.assertTrue(all(path.startswith(expected_input + os.sep) for _, path in files))
        self.assertEqual(scan.call_args.kwargs, {"threshold": 8})
        self.assertEqual(report, fake_report)
        self.assertNotIn(self.temporary.name, repr(report))

    def test_similar_image_report_decodes_real_images_after_workspace_copy(self):
        from officekit.engines.engine_similar_images import SimilarImageEngine

        fixture_root = Path(__file__).parent / "fixtures" / "similar-images" / "cc0"
        self.store.max_upload_bytes = 1_000_000
        self.store.add_files(self.workspace_id, [
            ("burst/frame-01.jpg", io.BytesIO((fixture_root / "dog-portrait.jpg").read_bytes())),
            ("burst/frame-02.jpg", io.BytesIO((fixture_root / "dog-portrait.jpg").read_bytes())),
            ("other/flower.jpg", io.BytesIO((fixture_root / "dandelion.jpg").read_bytes())),
        ])

        report = self.store.similar_image_report(
            self.workspace_id,
            ["burst/frame-01.jpg", "burst/frame-02.jpg", "other/flower.jpg"],
        )

        self.assertEqual(report["scanned_images"], 3)
        self.assertTrue(report["complete"], report)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["groups"], [{"files": ["burst/frame-01.jpg", "burst/frame-02.jpg"]}])
        self.assertNotIn(self.temporary.name, repr(report))

    def test_similar_image_report_rejects_unselected_paths_and_duplicates(self):
        self.store.add_files(self.workspace_id, [("one.jpg", io.BytesIO(b"one"))])
        with self.assertRaises(ValueError):
            self.store.similar_image_report(self.workspace_id, ["../outside.jpg"])
        with self.assertRaises(ValueError):
            self.store.similar_image_report(self.workspace_id, ["one.jpg", "one.jpg"])
        with self.assertRaises(ValueError):
            self.store.similar_image_report(self.workspace_id, ["one.jpg"], threshold=65)


if __name__ == "__main__":
    unittest.main()
