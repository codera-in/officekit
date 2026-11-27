"""Binary-safe workspace split/join regressions with checksum verification."""

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from officekit.engines.engine_workspaces import FileWorkspaceStore, WorkspaceLimitError


class FileSplitJoinTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = FileWorkspaceStore(
            root=self.temporary.name,
            max_upload_bytes=4096,
            max_archive_bytes=4096,
            max_upload_files=16,
            max_archive_files=16,
        )
        self.workspace_id = self.store.create_workspace()

    def tearDown(self):
        self.temporary.cleanup()

    def _artifact_entries(self, artifact, workspace_id=None):
        path = self.store.artifact_path(workspace_id or self.workspace_id, artifact["artifact_id"])
        with zipfile.ZipFile(path) as bundle:
            return {name: bundle.read(name) for name in bundle.namelist()}

    def _artifact_bytes(self, artifact, workspace_id=None):
        path = self.store.artifact_path(workspace_id or self.workspace_id, artifact["artifact_id"])
        with open(path, "rb") as source:
            return source.read()

    def test_split_and_join_round_trip_arbitrary_binary_bytes(self):
        original = bytes(range(256)) + b"\x00\xffOfficeKit\x00"
        self.store.add_files(self.workspace_id, [("archive.bin", io.BytesIO(original))])

        split = self.store.create_split_artifact(self.workspace_id, "archive.bin", chunk_size=64)
        split_entries = self._artifact_entries(split)
        manifest = json.loads(split_entries["split-manifest.json"])
        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["total_size_bytes"], len(original))
        self.assertEqual(manifest["file_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(len(manifest["parts"]), 5)
        for part in manifest["parts"]:
            data = split_entries[part["name"]]
            self.assertEqual(len(data), part["size_bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), part["sha256"])

        join_workspace = self.store.create_workspace()
        self.store.add_files(join_workspace, [("parts.zip", io.BytesIO(self._artifact_bytes(split)))])
        joined = self.store.create_join_artifact(
            join_workspace, "parts.zip", "restored.bin"
        )
        joined_entries = self._artifact_entries(joined, join_workspace)

        self.assertEqual(joined["total_bytes"], len(original))
        self.assertEqual(joined["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(joined_entries["joined/restored.bin"], original)

    def test_split_archive_size_estimate_matches_the_written_zip(self):
        original = bytes(range(32))
        self.store.add_files(self.workspace_id, [("measure.bin", io.BytesIO(original))])

        split = self.store.create_split_artifact(self.workspace_id, "measure.bin", chunk_size=7)
        artifact_path = self.store.artifact_path(self.workspace_id, split["artifact_id"])
        entries = self._artifact_entries(split)
        manifest = json.loads(entries["split-manifest.json"])
        expected_size = self.store._stored_zip_size_bytes(
            [("split-manifest.json", len(entries["split-manifest.json"]))]
            + [(part["name"], part["size_bytes"]) for part in manifest["parts"]]
        )

        self.assertEqual(os.path.getsize(artifact_path), expected_size)

    def test_split_preflights_zip_overhead_before_creating_archive(self):
        restrictive = FileWorkspaceStore(
            root=os.path.join(self.temporary.name, "limited"),
            max_upload_bytes=4096,
            max_archive_bytes=64,
            max_upload_files=16,
            max_archive_files=16,
        )
        workspace_id = restrictive.create_workspace()
        restrictive.add_files(workspace_id, [("source.bin", io.BytesIO(b"12345678"))])

        with patch("officekit.engines.engine_workspaces.zipfile.ZipFile") as zip_writer:
            with self.assertRaisesRegex(WorkspaceLimitError, "Split archive exceeds"):
                restrictive.create_split_artifact(workspace_id, "source.bin", chunk_size=4)

        zip_writer.assert_not_called()
        self.assertEqual(os.listdir(os.path.join(self.temporary.name, "limited", workspace_id)), ["input"])

    def test_split_handles_empty_and_exact_chunk_boundary_files(self):
        self.store.add_files(self.workspace_id, [
            ("empty.dat", io.BytesIO(b"")),
            ("exact.dat", io.BytesIO(b"12345678")),
        ])

        empty_split = self.store.create_split_artifact(self.workspace_id, "empty.dat", chunk_size=4)
        exact_split = self.store.create_split_artifact(self.workspace_id, "exact.dat", chunk_size=4)
        empty_entries = self._artifact_entries(empty_split)
        exact_entries = self._artifact_entries(exact_split)
        empty_manifest = json.loads(empty_entries["split-manifest.json"])
        exact_manifest = json.loads(exact_entries["split-manifest.json"])

        self.assertEqual(len(empty_manifest["parts"]), 1)
        self.assertEqual(empty_manifest["parts"][0]["size_bytes"], 0)
        self.assertEqual(empty_entries[empty_manifest["parts"][0]["name"]], b"")
        self.assertEqual([part["size_bytes"] for part in exact_manifest["parts"]], [4, 4])
        empty_workspace = self.store.create_workspace()
        self.store.add_files(empty_workspace, [("empty-parts.zip", io.BytesIO(self._artifact_bytes(empty_split)))])
        joined_empty = self.store.create_join_artifact(empty_workspace, "empty-parts.zip", "empty.dat")
        self.assertEqual(self._artifact_entries(joined_empty, empty_workspace)["joined/empty.dat"], b"")

    def test_split_rejects_invalid_chunk_sizes_and_unknown_sources(self):
        self.store.add_files(self.workspace_id, [("source.bin", io.BytesIO(b"1234"))])
        for invalid in (0, -1, True, 1.5, 4097):
            with self.subTest(chunk_size=invalid), self.assertRaises(ValueError):
                self.store.create_split_artifact(self.workspace_id, "source.bin", invalid)
        with self.assertRaises(FileNotFoundError):
            self.store.create_split_artifact(self.workspace_id, "missing.bin", 4)
        self.store.add_files(self.workspace_id, [("many.bin", io.BytesIO(b"x" * 16))])
        with self.assertRaisesRegex(ValueError, "too many parts"):
            self.store.create_split_artifact(self.workspace_id, "many.bin", 1)

    def test_join_rejects_a_part_that_does_not_match_its_manifest(self):
        original = b"the expected file data"
        self.store.add_files(self.workspace_id, [("source.bin", io.BytesIO(original))])
        split = self.store.create_split_artifact(self.workspace_id, "source.bin", chunk_size=8)
        entries = self._artifact_entries(split)
        part_name = json.loads(entries["split-manifest.json"])["parts"][0]["name"]
        damaged = io.BytesIO()
        with zipfile.ZipFile(damaged, "w", compression=zipfile.ZIP_STORED) as bundle:
            for name, data in entries.items():
                bundle.writestr(name, b"tampered" if name == part_name else data)
        join_workspace = self.store.create_workspace()
        self.store.add_files(join_workspace, [("damaged.zip", io.BytesIO(damaged.getvalue()))])

        with self.assertRaisesRegex(ValueError, "checksum"):
            self.store.create_join_artifact(join_workspace, "damaged.zip", "restored.bin")
        outputs = os.path.join(self.temporary.name, join_workspace, "outputs")
        self.assertFalse(os.path.exists(outputs))

    def test_join_rejects_malformed_manifest_and_unsafe_output_name(self):
        for index, payload in enumerate((b"{", b"[]", b'{"version":true}')):
            name = f"malformed-{index}.zip"
            archive_buffer = io.BytesIO()
            with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_STORED) as bundle:
                bundle.writestr("split-manifest.json", payload)
            self.store.add_files(self.workspace_id, [(name, io.BytesIO(archive_buffer.getvalue()))])
            with self.subTest(manifest=payload), self.assertRaises(ValueError):
                self.store.create_join_artifact(self.workspace_id, name, "output.bin")
        valid_split = self.store.create_split_artifact(self.workspace_id, "malformed-0.zip", chunk_size=32)
        valid_archive = self._artifact_bytes(valid_split)
        other_workspace = self.store.create_workspace()
        self.store.add_files(other_workspace, [("parts.zip", io.BytesIO(valid_archive))])
        with self.assertRaises(ValueError):
            self.store.create_join_artifact(other_workspace, "parts.zip", "../escape.bin")

    def test_join_rejects_duplicate_json_fields_extra_entries_and_compressed_parts(self):
        self.store.add_files(self.workspace_id, [("source.bin", io.BytesIO(b"12345678"))])
        split = self.store.create_split_artifact(self.workspace_id, "source.bin", chunk_size=4)
        entries = self._artifact_entries(split)
        valid_manifest = entries["split-manifest.json"]
        variants = []
        duplicate_field = valid_manifest.replace(b'"version":1', b'"version":1,"version":1', 1)
        variants.append(("duplicate-manifest-field.zip", "stored", duplicate_field, False))
        variants.append(("extra-entry.zip", "stored", valid_manifest, True))
        variants.append(("compressed.zip", "deflated", valid_manifest, False))

        for name, compression, manifest, extra in variants:
            buffer = io.BytesIO()
            zip_compression = zipfile.ZIP_DEFLATED if compression == "deflated" else zipfile.ZIP_STORED
            with zipfile.ZipFile(buffer, "w", compression=zip_compression) as bundle:
                bundle.writestr("split-manifest.json", manifest)
                for part in json.loads(valid_manifest)["parts"]:
                    bundle.writestr(part["name"], entries[part["name"]])
                if extra:
                    bundle.writestr("unexpected.bin", b"extra")
            workspace_id = self.store.create_workspace()
            self.store.add_files(workspace_id, [(name, io.BytesIO(buffer.getvalue()))])
            with self.subTest(archive=name), self.assertRaises(ValueError):
                self.store.create_join_artifact(workspace_id, name, "output.bin")
            self.assertFalse(os.path.exists(os.path.join(self.temporary.name, workspace_id, "outputs")))

    def test_join_rejects_missing_or_reordered_parts(self):
        self.store.add_files(self.workspace_id, [("source.bin", io.BytesIO(b"0123456789"))])
        split = self.store.create_split_artifact(self.workspace_id, "source.bin", chunk_size=4)
        entries = self._artifact_entries(split)
        valid_manifest = json.loads(entries["split-manifest.json"])
        reordered_manifest = dict(valid_manifest)
        reordered_manifest["parts"] = list(reversed(valid_manifest["parts"]))
        variants = (("missing-part.zip", valid_manifest, 1), ("reordered-part.zip", reordered_manifest, 0))

        for archive_name, manifest, omit_last in variants:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as bundle:
                bundle.writestr("split-manifest.json", json.dumps(manifest).encode("utf-8"))
                part_names = [part["name"] for part in valid_manifest["parts"]]
                if omit_last:
                    part_names = part_names[:-1]
                for name in part_names:
                    bundle.writestr(name, entries[name])
            workspace_id = self.store.create_workspace()
            self.store.add_files(workspace_id, [(archive_name, io.BytesIO(buffer.getvalue()))])
            with self.subTest(archive=archive_name), self.assertRaises(ValueError):
                self.store.create_join_artifact(workspace_id, archive_name, "output.bin")
            self.assertFalse(os.path.exists(os.path.join(self.temporary.name, workspace_id, "outputs")))

    def test_split_rejects_a_source_replaced_by_a_symlink_before_open(self):
        if not hasattr(os, "symlink"):
            self.skipTest("Symlinks are unavailable on this platform")
        self.store.add_files(self.workspace_id, [("source.bin", io.BytesIO(b"private"))])
        outside = os.path.join(self.temporary.name, "outside.bin")
        with open(outside, "wb") as target:
            target.write(b"outside secret")
        source_path = os.path.join(self.temporary.name, self.workspace_id, "input", "source.bin")
        original_open = self.store._open_workspace_file

        def swap_before_open(path):
            os.unlink(path)
            os.symlink(outside, path)
            return original_open(path)

        with patch.object(self.store, "_open_workspace_file", side_effect=swap_before_open):
            with self.assertRaises(FileNotFoundError):
                self.store.create_split_artifact(self.workspace_id, "source.bin", chunk_size=4)
        self.assertFalse(os.path.exists(os.path.join(self.temporary.name, self.workspace_id, "outputs")))

    @unittest.skipIf(sys.platform == "win32", "Symlink/inode swap verification is POSIX-specific")
    def test_join_rejects_a_split_archive_replaced_by_a_symlink_before_open(self):
        if not hasattr(os, "symlink"):
            self.skipTest("Symlinks are unavailable on this platform")
        self.store.add_files(self.workspace_id, [("source.bin", io.BytesIO(b"private"))])
        split = self.store.create_split_artifact(self.workspace_id, "source.bin", chunk_size=4)
        split_bytes = self._artifact_bytes(split)
        other_workspace = self.store.create_workspace()
        self.store.add_files(other_workspace, [("parts.zip", io.BytesIO(split_bytes))])
        outside = os.path.join(self.temporary.name, "outside.zip")
        with open(outside, "wb") as target:
            target.write(split_bytes)
        archive_path = os.path.join(self.temporary.name, other_workspace, "input", "parts.zip")
        original_os_open = os.open
        observed = []

        def swap_before_open(path, flags, *args, **kwargs):
            observed.append(os.fspath(path))
            if os.path.basename(os.fspath(path)) == "parts.zip":
                os.unlink(path)
                os.symlink(outside, path)
            return original_os_open(path, flags, *args, **kwargs)

        with patch("officekit.engines.engine_workspaces.os.open", side_effect=swap_before_open):
            with self.assertRaises(FileNotFoundError):
                self.store.create_join_artifact(other_workspace, "parts.zip", "output.bin")
        self.assertTrue(any(os.path.basename(path) == "parts.zip" for path in observed), observed)
        self.assertFalse(os.path.exists(os.path.join(self.temporary.name, other_workspace, "outputs")))

    def test_split_and_join_reject_symlinked_output_directories(self):
        if not hasattr(os, "symlink"):
            self.skipTest("Symlinks are unavailable on this platform")
        self.store.add_files(self.workspace_id, [("source.bin", io.BytesIO(b"private"))])
        split_workspace = self.store.create_workspace()
        self.store.add_files(split_workspace, [("source.bin", io.BytesIO(b"private"))])
        split_outside = os.path.join(self.temporary.name, "split-outside")
        os.mkdir(split_outside)
        os.symlink(split_outside, os.path.join(self.temporary.name, split_workspace, "outputs"))

        with self.assertRaises(FileNotFoundError):
            self.store.create_split_artifact(split_workspace, "source.bin", chunk_size=4)
        self.assertEqual(os.listdir(split_outside), [])

        split = self.store.create_split_artifact(self.workspace_id, "source.bin", chunk_size=4)
        join_workspace = self.store.create_workspace()
        self.store.add_files(join_workspace, [("parts.zip", io.BytesIO(self._artifact_bytes(split)))])
        join_outside = os.path.join(self.temporary.name, "join-outside")
        os.mkdir(join_outside)
        os.symlink(join_outside, os.path.join(self.temporary.name, join_workspace, "outputs"))

        with self.assertRaises(FileNotFoundError):
            self.store.create_join_artifact(join_workspace, "parts.zip", "joined.bin")
        self.assertEqual(os.listdir(join_outside), [])


if __name__ == "__main__":
    unittest.main()
