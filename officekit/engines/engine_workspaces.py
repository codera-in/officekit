"""Short-lived, process-owned workspaces for user-selected file operations."""

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import uuid
import zipfile
from pathlib import PurePosixPath
from typing import BinaryIO, Iterable

from officekit.engines.engine_file_ops import FileOpsEngine, StorageAnalyzerEngine
from officekit.engines.engine_file_type import FileTypeDetector
from officekit.engines.engine_similar_images import SimilarImageEngine


_WORKSPACE_ID = re.compile(r"^[a-f0-9]{32}$")
_ARTIFACT_ID = re.compile(r"^[a-f0-9]{32}$")
_WINDOWS_RESERVED_BASENAME = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE)
_WINDOWS_INVALID_PATH_CHARS = frozenset('<>:"|?*')
_CHUNK_SIZE = 65_536
_MAX_SPLIT_MANIFEST_BYTES = 1_048_576
_MAX_WORKSPACE_DIRECTORIES = 10_000
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _same_file_id(first: os.stat_result, second: os.stat_result) -> bool:
    if os.name == "nt":
        return True
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)


def _same_mtime(first: os.stat_result, second: os.stat_result) -> bool:
    if os.name == "nt":
        return int(first.st_mtime) == int(second.st_mtime)
    return first.st_mtime_ns == second.st_mtime_ns


class WorkspaceLimitError(ValueError):
    """Raised when an upload or extracted archive exceeds configured resource limits."""


class FileWorkspaceStore:
    """Store uploaded copies and generated artifacts under an unguessable workspace ID."""

    HASH_CHUNK_SIZE = _CHUNK_SIZE

    def __init__(
        self,
        root: str | None = None,
        max_upload_bytes: int = 536_870_912,
        max_upload_files: int = 1_000,
        max_archive_bytes: int = 536_870_912,
        max_archive_files: int = 10_000,
    ):
        if max_upload_bytes <= 0 or max_upload_files <= 0 or max_archive_bytes <= 0 or max_archive_files <= 0:
            raise ValueError("Workspace limits must be positive integers")
        self._temporary_root = tempfile.TemporaryDirectory(prefix="officekit-workspaces-") if root is None else None
        self.root = os.path.abspath(root if root is not None else self._temporary_root.name)
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        self.max_upload_bytes = max_upload_bytes
        self.max_upload_files = max_upload_files
        self.max_archive_bytes = max_archive_bytes
        self.max_archive_files = max_archive_files

    def create_workspace(self) -> str:
        workspace_id = uuid.uuid4().hex
        os.mkdir(os.path.join(self.root, workspace_id), mode=0o700)
        return workspace_id

    def _workspace_path(self, workspace_id: str) -> str:
        if not isinstance(workspace_id, str) or not _WORKSPACE_ID.fullmatch(workspace_id):
            raise FileNotFoundError("Workspace not found")
        path = os.path.join(self.root, workspace_id)
        try:
            metadata = os.lstat(path)
        except OSError as error:
            raise FileNotFoundError("Workspace not found") from error
        if not stat.S_ISDIR(metadata.st_mode):
            raise FileNotFoundError("Workspace not found")
        return path

    @staticmethod
    def _relative_name(name: str) -> str:
        if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
            raise ValueError("File name is invalid")
        if any(part in {"", ".", ".."} for part in name.split("/")):
            raise ValueError("File name must be a relative path without traversal")
        path = PurePosixPath(name)
        if path.is_absolute():
            raise ValueError("File name must be a relative path without traversal")
        if path.parts and ":" in path.parts[0]:
            raise ValueError("Drive-qualified file names are not allowed")
        if any(
            part.endswith((".", " "))
            or any(ord(character) < 32 or character in _WINDOWS_INVALID_PATH_CHARS for character in part)
            or _WINDOWS_RESERVED_BASENAME.fullmatch(part)
            for part in path.parts
        ):
            raise ValueError("File name contains characters or components unsupported on Windows")
        return path.as_posix()

    @staticmethod
    def _write_stream(source: BinaryIO, target: str, limit: int, total: int) -> tuple[int, int]:
        written = 0
        with open(target, "xb") as output:
            while True:
                chunk = source.read(_CHUNK_SIZE)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise ValueError("File contents must be bytes")
                written += len(chunk)
                total += len(chunk)
                if written > limit or total > limit:
                    raise WorkspaceLimitError("Uploaded files exceed the workspace size limit")
                output.write(chunk)
        return written, total

    @staticmethod
    def _inventory(directory: str) -> list[dict[str, int | str]]:
        result = []
        if not os.path.isdir(directory):
            return result
        for root, dirs, files in os.walk(directory, followlinks=False):
            dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(root, name))]
            for name in files:
                path = os.path.join(root, name)
                if os.path.islink(path) or not os.path.isfile(path):
                    continue
                relative = os.path.relpath(path, directory).replace(os.sep, "/")
                result.append({"name": relative, "size_bytes": os.path.getsize(path)})
        result.sort(key=lambda item: str(item["name"]).casefold())
        return result

    @staticmethod
    def _directory_inventory(directory: str) -> list[str]:
        result = []
        if not os.path.isdir(directory):
            return result
        for root, dirs, _files in os.walk(directory, followlinks=False):
            dirs[:] = [name for name in dirs if not os.path.islink(os.path.join(root, name))]
            for name in dirs:
                path = os.path.join(root, name)
                result.append(os.path.relpath(path, directory).replace(os.sep, "/"))
        result.sort(key=str.casefold)
        return result

    def get_workspace(self, workspace_id: str) -> dict:
        workspace = self._workspace_path(workspace_id)
        input_root = os.path.join(workspace, "input")
        return {
            "workspace_id": workspace_id,
            "files": self._inventory(input_root),
            "directories": self._directory_inventory(input_root),
        }

    @staticmethod
    def _portable_filename(name: str) -> str:
        safe_name = FileWorkspaceStore._relative_name(name)
        if "/" in safe_name or safe_name in {".", ".."}:
            raise ValueError("Renamed files must remain a single filename component")
        if any(ord(character) < 32 or character in '<>:"/\\|?*' for character in safe_name):
            raise ValueError("Renamed files contain characters unsupported by a target platform")
        if safe_name.endswith((".", " ")):
            raise ValueError("Renamed files cannot end with a dot or space")
        stem = safe_name.split(".", 1)[0].casefold()
        if stem in {"con", "prn", "aux", "nul", *(f"com{number}" for number in range(1, 10)), *(f"lpt{number}" for number in range(1, 10))}:
            raise ValueError("Renamed file uses a reserved platform name")
        return safe_name

    @staticmethod
    def _collision_key(name: str) -> str:
        return unicodedata.normalize("NFC", name).casefold()

    def preview_rename(
        self,
        workspace_id: str,
        filenames: list[str],
        pattern_type: str = "sequence",
        prefix: str = "",
        suffix: str = "",
        start_num: int = 1,
        digits: int = 3,
        casing: str = "kebab",
        find_text: str = "",
        replace_text: str = "",
    ) -> list[dict[str, int | str]]:
        workspace = self._workspace_path(workspace_id)
        if not isinstance(filenames, list) or not filenames:
            raise ValueError("Select at least one file to rename")
        if len(filenames) > self.max_upload_files:
            raise WorkspaceLimitError("Too many files selected for one rename operation")
        if pattern_type not in {"sequence", "affix", "casing", "replace"}:
            raise ValueError("Unsupported rename pattern")
        if pattern_type == "replace" and not find_text:
            raise ValueError("Enter text to find before previewing replacements")

        inventory = self._inventory(os.path.join(workspace, "input"))
        available = {str(item["name"]): int(item["size_bytes"]) for item in inventory}
        existing_keys = {self._collision_key(str(item["name"])) for item in inventory}
        selected = []
        selected_folded = set()
        for raw_name in filenames:
            name = self._relative_name(raw_name)
            if name not in available:
                raise FileNotFoundError(f"Selected file is not in this workspace: {name}")
            folded = self._collision_key(name)
            if folded in selected_folded:
                raise ValueError(f"File selected more than once: {name}")
            selected_folded.add(folded)
            selected.append(name)

        generated_names = FileOpsEngine.generate_rename_plan(
            [PurePosixPath(name).name for name in selected],
            pattern_type=pattern_type,
            prefix=prefix,
            suffix=suffix,
            start_num=start_num,
            digits=digits,
            casing=casing,
            find_text=find_text,
            replace_text=replace_text,
        )
        plan = []
        targets = set()
        for source, generated_name in zip(selected, generated_names, strict=True):
            target_name = self._portable_filename(generated_name)
            parent = PurePosixPath(source).parent
            target = target_name if str(parent) == "." else f"{parent.as_posix()}/{target_name}"
            folded_target = self._collision_key(target)
            if folded_target in targets:
                raise ValueError(f"Multiple selected files would have the same name: {target}")
            targets.add(folded_target)
            if folded_target in existing_keys - selected_folded:
                raise ValueError(f"A file with this name already exists: {target}")
            plan.append({"source": source, "target": target, "size_bytes": available[source]})
        return plan

    def create_renamed_artifact(self, workspace_id: str, filenames: list[str], **options) -> dict:
        plan = self.preview_rename(workspace_id, filenames, **options)
        workspace = self._workspace_path(workspace_id)
        input_root = os.path.realpath(os.path.join(workspace, "input"))
        artifact_id = uuid.uuid4().hex
        stage = os.path.join(workspace, f".rename-{artifact_id}")
        output_root = os.path.join(stage, "renamed")
        os.mkdir(stage, mode=0o700)
        os.mkdir(output_root, mode=0o700)
        total_bytes = 0
        artifact_path = os.path.join(workspace, "outputs", artifact_id)
        artifact_directory_created = False
        try:
            for item in plan:
                source = os.path.join(input_root, *PurePosixPath(str(item["source"])).parts)
                target = os.path.join(output_root, *PurePosixPath(str(item["target"])).parts)
                os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
                if os.path.islink(source) or not os.path.isfile(source):
                    raise FileNotFoundError("A selected workspace file is no longer available")
                total_bytes += self._copy_workspace_file(source, target, int(item["size_bytes"]))

            bundle_path = os.path.join(stage, "bundle.zip")
            with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for item in plan:
                    target = os.path.join(output_root, *PurePosixPath(str(item["target"])).parts)
                    bundle.write(target, arcname=f"renamed/{item['target']}")

            os.makedirs(os.path.dirname(artifact_path), mode=0o700, exist_ok=True)
            os.mkdir(artifact_path, mode=0o700)
            artifact_directory_created = True
            os.replace(bundle_path, os.path.join(artifact_path, "bundle.zip"))
            shutil.rmtree(stage, ignore_errors=True)
        except Exception:
            if artifact_directory_created:
                shutil.rmtree(artifact_path, ignore_errors=True)
            shutil.rmtree(stage, ignore_errors=True)
            raise

        return {
            "artifact_id": artifact_id,
            "file_count": len(plan),
            "total_bytes": total_bytes,
            "files": [str(item["target"]) for item in plan],
            "download_name": "renamed-files.zip",
        }

    def _copy_workspace_file(self, source_path: str, target_path: str, expected_size: int) -> int:
        """Copy a regular workspace file through a no-follow descriptor and verify stability."""
        try:
            before = os.lstat(source_path)
            if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
                raise FileNotFoundError("A selected workspace file is no longer available")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            descriptor = os.open(source_path, flags)
        except OSError as error:
            raise FileNotFoundError("A selected workspace file is no longer available") from error

        with os.fdopen(descriptor, "rb") as source:
            opened = os.fstat(source.fileno())
            if (
                not stat.S_ISREG(opened.st_mode)
                or not _same_file_id(opened, before)
                or opened.st_size != expected_size
            ):
                raise FileNotFoundError("A selected workspace file is no longer available")

            copied = 0
            with open(target_path, "xb") as target:
                while True:
                    chunk = source.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    copied += len(chunk)
                    if copied > expected_size or copied > self.max_upload_bytes:
                        raise ValueError("A selected workspace file changed during rename")
                    target.write(chunk)

            after = os.fstat(source.fileno())
            if (
                copied != expected_size
                or after.st_size != expected_size
                or not _same_mtime(after, before)
            ):
                raise ValueError("A selected workspace file changed during rename")
        return copied

    @staticmethod
    def _open_workspace_file(source_path: str):
        """Open a regular file without following a swapped final-component symlink."""
        try:
            before = os.lstat(source_path)
            if not stat.S_ISREG(before.st_mode):
                raise FileNotFoundError("A selected workspace file is no longer available")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            descriptor = os.open(source_path, flags)
        except OSError as error:
            raise FileNotFoundError("A selected workspace file is no longer available") from error

        try:
            source = os.fdopen(descriptor, "rb")
        except Exception:
            os.close(descriptor)
            raise
        try:
            opened = os.fstat(source.fileno())
        except OSError as error:
            source.close()
            raise FileNotFoundError("A selected workspace file is no longer available") from error
        if (
            not stat.S_ISREG(opened.st_mode)
            or not _same_file_id(opened, before)
            or opened.st_size != before.st_size
        ):
            source.close()
            raise FileNotFoundError("A selected workspace file is no longer available")
        return source, before

    @staticmethod
    def _verify_workspace_file_unchanged(source: BinaryIO, before) -> None:
        after = os.fstat(source.fileno())
        if (
            not _same_file_id(after, before)
            or after.st_size != before.st_size
            or not _same_mtime(after, before)
        ):
            raise ValueError("A selected workspace file changed during processing")

    def find_duplicate_report(self, workspace_id: str, max_entries: int = 10_000) -> dict:
        workspace = self._workspace_path(workspace_id)
        input_root = os.path.realpath(os.path.join(workspace, "input"))
        if type(max_entries) is not int or max_entries <= 0:
            raise ValueError("Scan entry limit must be a positive integer")
        report = FileOpsEngine.find_duplicate_files_report(input_root, max_entries=max_entries)

        def workspace_name(path: str) -> str | None:
            absolute_path = os.path.abspath(path)
            try:
                relative = os.path.relpath(absolute_path, input_root)
            except ValueError:
                return None
            if relative == ".":
                return None
            if relative == ".." or relative.startswith(f"..{os.sep}") or os.path.isabs(relative):
                return None
            return relative.replace(os.sep, "/")

        invalid_paths = False
        groups = []
        for group in report["groups"]:
            names = []
            for path in group["files"]:
                name = workspace_name(path)
                if name is None:
                    invalid_paths = True
                else:
                    names.append(name)
            groups.append({
                "hash": group["hash"],
                "size_bytes": group["size_bytes"],
                "files": sorted(names, key=str.casefold),
            })
        errors = [
            {
                "name": workspace_name(error["path"]),
                "message": "A file could not be read during the duplicate scan.",
            }
            for error in report["errors"]
        ]
        return {
            "groups": groups,
            "files_scanned": report["files_scanned"],
            "skipped_symlinks": report["skipped_symlinks"],
            "complete": report["complete"] and not invalid_paths,
            "errors": errors,
        }

    def storage_report(self, workspace_id: str, top_n: int = 10) -> dict:
        workspace = self._workspace_path(workspace_id)
        input_root = os.path.realpath(os.path.join(workspace, "input"))
        if type(top_n) is not int or not 0 <= top_n <= 1000:
            raise ValueError("Result limit must be an integer from 0 to 1,000")
        if not os.path.isdir(input_root):
            return {
                "total_files": 0,
                "total_size_bytes": 0,
                "total_size_mb": 0.0,
                "largest_files": [],
                "largest_folders": [],
                "complete": True,
                "skipped_symlinks": 0,
                "errors": [],
            }

        report = StorageAnalyzerEngine.analyze_directory(input_root, top_n=top_n)

        def workspace_name(path: str) -> str | None:
            absolute_path = os.path.abspath(path)
            try:
                relative = os.path.relpath(absolute_path, input_root)
            except ValueError:
                return None
            if relative in {".", ".."} or relative.startswith(f"..{os.sep}") or os.path.isabs(relative):
                return None
            return relative.replace(os.sep, "/")

        invalid_paths = False
        largest_files = []
        for item in report["largest_files"]:
            name = workspace_name(str(item["path"]))
            if name is None:
                invalid_paths = True
                continue
            largest_files.append({
                "name": name,
                "size_bytes": item["size_bytes"],
                "size_mb": item["size_mb"],
            })
        largest_folders = []
        for item in report["largest_folders"]:
            name = workspace_name(os.path.join(input_root, str(item["name"])))
            if name is None:
                invalid_paths = True
                continue
            largest_folders.append({
                "name": name,
                "file_count": item["file_count"],
                "size_bytes": item["size_bytes"],
            })
        errors = []
        for error in report["errors"]:
            name = workspace_name(str(error["path"]))
            if name is None:
                invalid_paths = True
            errors.append({
                "name": name,
                "message": "A file could not be read during the storage scan.",
            })
        return {
            "total_files": report["total_files"],
            "total_size_bytes": report["total_size_bytes"],
            "total_size_mb": report["total_size_mb"],
            "largest_files": largest_files,
            "largest_folders": largest_folders,
            "complete": report["complete"] and not invalid_paths,
            "skipped_symlinks": report["skipped_symlinks"],
            "errors": errors,
        }

    def compare_folders(self, workspace_id: str, left_folder: str, right_folder: str) -> dict:
        """Compare two imported folder copies by relative path, size and SHA-256."""
        self._workspace_path(workspace_id)
        left_prefix = self._relative_name(left_folder)
        right_prefix = self._relative_name(right_folder)
        if (
            left_prefix == right_prefix
            or left_prefix.startswith(f"{right_prefix}/")
            or right_prefix.startswith(f"{left_prefix}/")
        ):
            raise ValueError("Choose two distinct, non-overlapping workspace folders")

        input_root = os.path.join(self._workspace_path(workspace_id), "input")
        inventory = self._inventory(input_root)
        directory_names = set(self._directory_inventory(input_root))

        def scoped_files(prefix: str) -> dict[str, str]:
            marker = f"{prefix}/"
            return {
                name[len(marker):]: name
                for item in inventory
                if (name := str(item["name"])).startswith(marker)
            }

        left_files = scoped_files(left_prefix)
        right_files = scoped_files(right_prefix)
        if left_prefix not in directory_names or right_prefix not in directory_names:
            raise FileNotFoundError("Both selected folders must exist in the imported workspace")

        selected_names = sorted(
            [*left_files.values(), *right_files.values()],
            key=str.casefold,
        )
        if len(selected_names) > self.max_upload_files:
            raise WorkspaceLimitError("Compared folders exceed the workspace file-count limit")
        digest_report = self.hash_files(workspace_id, selected_names, algorithm="sha256") if selected_names else {"files": []}
        digests = {item["name"]: item for item in digest_report["files"]}

        results = []
        summary = {"identical": 0, "changed": 0, "left_only": 0, "right_only": 0}
        for relative_name in sorted(left_files.keys() | right_files.keys(), key=str.casefold):
            left_name = left_files.get(relative_name)
            right_name = right_files.get(relative_name)
            left = digests.get(left_name) if left_name else None
            right = digests.get(right_name) if right_name else None
            if left is None:
                status = "right-only"
                summary["right_only"] += 1
            elif right is None:
                status = "left-only"
                summary["left_only"] += 1
            elif left["size_bytes"] == right["size_bytes"] and left["digest"] == right["digest"]:
                status = "identical"
                summary["identical"] += 1
            else:
                status = "changed"
                summary["changed"] += 1
            results.append({
                "path": relative_name,
                "status": status,
                "left_name": left_name,
                "right_name": right_name,
                "left_size_bytes": left["size_bytes"] if left else None,
                "right_size_bytes": right["size_bytes"] if right else None,
                "left_sha256": left["digest"] if left else None,
                "right_sha256": right["digest"] if right else None,
            })

        def scoped_directories(prefix: str, files: dict[str, str]) -> dict[str, bool]:
            marker = f"{prefix}/"
            descendants = {
                name[len(marker):]: name
                for name in directory_names
                if name.startswith(marker)
            }
            descendant_files = set(files)
            result = {
                relative_name: not any(
                    name.startswith(f"{relative_name}/")
                    for name in [*descendants.keys(), *descendant_files]
                )
                for relative_name in descendants
            }
            result["."] = not descendants and not descendant_files
            return result

        left_directories = scoped_directories(left_prefix, left_files)
        right_directories = scoped_directories(right_prefix, right_files)
        directory_results = []
        directory_summary = {"identical": 0, "changed": 0, "left_only": 0, "right_only": 0}
        for relative_name in sorted(left_directories.keys() | right_directories.keys(), key=str.casefold):
            left_empty = left_directories.get(relative_name)
            right_empty = right_directories.get(relative_name)
            if left_empty is None:
                status = "right-only"
                directory_summary["right_only"] += 1
            elif right_empty is None:
                status = "left-only"
                directory_summary["left_only"] += 1
            elif left_empty != right_empty:
                status = "changed"
                directory_summary["changed"] += 1
            else:
                status = "identical"
                directory_summary["identical"] += 1
            directory_results.append({
                "path": relative_name,
                "status": status,
                "left_empty": left_empty,
                "right_empty": right_empty,
            })

        return {
            "left_folder": left_prefix,
            "right_folder": right_prefix,
            "files_compared": len(selected_names),
            "total_paths": len(results),
            "summary": summary,
            "files": results,
            "directory_summary": directory_summary,
            "directories": directory_results,
            "complete": True,
        }

    @staticmethod
    def _digest_stream(source: BinaryIO, digest, byte_limit: int) -> int:
        total = 0
        while True:
            chunk = source.read(FileWorkspaceStore.HASH_CHUNK_SIZE)
            if not chunk:
                return total
            if not isinstance(chunk, bytes):
                raise ValueError("Hash source must return bytes")
            total += len(chunk)
            if total > byte_limit:
                raise WorkspaceLimitError("Selected files exceed the workspace hash byte limit")
            digest.update(chunk)

    def hash_files(self, workspace_id: str, filenames: list[str], algorithm: str = "sha256") -> dict:
        """Hash selected imported copies only, using bounded streaming reads."""
        workspace = self._workspace_path(workspace_id)
        if not isinstance(algorithm, str) or algorithm not in {"sha256", "sha512"}:
            raise ValueError("Hash algorithm must be sha256 or sha512")
        if not isinstance(filenames, list) or not filenames or len(filenames) > self.max_upload_files:
            raise ValueError(f"Select between 1 and {self.max_upload_files} workspace files")

        selected = [self._relative_name(name) for name in filenames]
        if len(set(selected)) != len(selected):
            raise ValueError("Selected file names must be unique")

        input_root = os.path.realpath(os.path.join(workspace, "input"))
        inventory = {str(item["name"]) for item in self._inventory(os.path.join(workspace, "input"))}
        if any(name not in inventory for name in selected):
            raise FileNotFoundError("A selected workspace file is no longer available")

        results = []
        total_bytes = 0
        for name in selected:
            path = os.path.join(input_root, *name.split("/"))
            try:
                if os.path.commonpath((input_root, os.path.realpath(path))) != input_root:
                    raise FileNotFoundError
                before = os.lstat(path)
                if not stat.S_ISREG(before.st_mode):
                    raise FileNotFoundError
            except (OSError, ValueError) as error:
                raise FileNotFoundError("A selected workspace file is no longer available") from error

            if before.st_size > self.max_upload_bytes - total_bytes:
                raise WorkspaceLimitError("Selected files exceed the workspace hash byte limit")

            descriptor = None
            try:
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
                descriptor = os.open(path, flags)
                with os.fdopen(descriptor, "rb") as source:
                    descriptor = None
                    opened = os.fstat(source.fileno())
                    if (
                        not stat.S_ISREG(opened.st_mode)
                        or not _same_file_id(opened, before)
                    ):
                        raise FileNotFoundError("A selected workspace file is no longer available")
                    digest = hashlib.new(algorithm)
                    size_bytes = self._digest_stream(source, digest, self.max_upload_bytes - total_bytes)
                    after = os.fstat(source.fileno())
                    if (
                        size_bytes != before.st_size
                        or after.st_size != before.st_size
                        or not _same_mtime(after, before)
                    ):
                        raise ValueError("A selected file changed during hashing; retry the scan")
            except OSError as error:
                raise FileNotFoundError("A selected workspace file is no longer available") from error
            finally:
                if descriptor is not None:
                    os.close(descriptor)

            total_bytes += size_bytes
            results.append({"name": name, "size_bytes": size_bytes, "digest": digest.hexdigest()})

        return {
            "algorithm": algorithm,
            "total_files": len(results),
            "total_bytes": total_bytes,
            "complete": True,
            "files": results,
        }

    def similar_image_report(
        self, workspace_id: str, filenames: Iterable[str], threshold: int = 8
    ) -> dict:
        workspace = self._workspace_path(workspace_id)
        if type(threshold) is not int or not 0 <= threshold <= 64:
            raise ValueError("Similarity threshold must be an integer from 0 to 64")
        selected = list(filenames)
        if not selected or len(selected) > SimilarImageEngine.MAX_FILES:
            raise ValueError(f"Select between 1 and {SimilarImageEngine.MAX_FILES} files")
        normalized = [self._relative_name(name) for name in selected]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Selected image names must be unique")

        input_root = os.path.realpath(os.path.join(workspace, "input"))
        inventory = {item["name"] for item in self._inventory(os.path.join(workspace, "input"))}
        if any(name not in inventory for name in normalized):
            raise FileNotFoundError("A selected workspace file is no longer available")

        files = []
        for name in normalized:
            path = os.path.realpath(os.path.join(input_root, *name.split("/")))
            try:
                if os.path.commonpath((input_root, path)) != input_root or not os.path.isfile(path):
                    raise FileNotFoundError
            except (ValueError, FileNotFoundError) as error:
                raise FileNotFoundError("A selected workspace file is no longer available") from error
            files.append((name, path))
        return SimilarImageEngine.scan_files(files, threshold=threshold)

    def file_type_report(self, workspace_id: str, filenames: list[str]) -> dict:
        """Inspect bounded headers of selected workspace copies, never arbitrary host paths."""
        workspace = self._workspace_path(workspace_id)
        if not isinstance(filenames, list) or not filenames or len(filenames) > self.max_upload_files:
            raise ValueError(f"Select between 1 and {self.max_upload_files} workspace files")
        selected = [self._relative_name(name) for name in filenames]
        if len(set(selected)) != len(selected):
            raise ValueError("Selected file names must be unique")

        input_root = os.path.realpath(os.path.join(workspace, "input"))
        inventory = {str(item["name"]) for item in self._inventory(os.path.join(workspace, "input"))}
        if any(name not in inventory for name in selected):
            raise FileNotFoundError("A selected workspace file is no longer available")

        results = []
        for name in selected:
            path = os.path.join(input_root, *name.split("/"))
            descriptor = None
            try:
                if os.path.commonpath((input_root, os.path.realpath(path))) != input_root:
                    raise FileNotFoundError
                before = os.lstat(path)
                if not stat.S_ISREG(before.st_mode):
                    raise FileNotFoundError
                flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
                descriptor = os.open(path, flags)
                with os.fdopen(descriptor, "rb") as source:
                    descriptor = None
                    opened = os.fstat(source.fileno())
                    if (
                        not stat.S_ISREG(opened.st_mode)
                        or not _same_file_id(opened, before)
                        or opened.st_size != before.st_size
                    ):
                        raise FileNotFoundError
                    header = source.read(FileTypeDetector.MAX_HEADER_BYTES)
                    after = os.fstat(source.fileno())
                    if (
                        after.st_size != before.st_size
                        or not _same_mtime(after, before)
                    ):
                        raise ValueError("A selected file changed during inspection; retry the scan")
            except OSError as error:
                raise FileNotFoundError("A selected workspace file is no longer available") from error
            except ValueError:
                raise
            finally:
                if descriptor is not None:
                    os.close(descriptor)
            results.append(FileTypeDetector.detect(name, header, file_size=before.st_size))
        return {"total_files": len(results), "complete": True, "files": results}

    def add_files(
        self,
        workspace_id: str,
        files: Iterable[tuple[str, BinaryIO]],
        directories: Iterable[str] = (),
    ) -> list[dict[str, int | str]]:
        workspace = self._workspace_path(workspace_id)
        input_root = os.path.join(workspace, "input")
        raw_directories = list(directories)
        if len(raw_directories) > _MAX_WORKSPACE_DIRECTORIES:
            raise WorkspaceLimitError("Too many folders selected for one workspace")
        requested_directories = [self._relative_name(name) for name in raw_directories]
        directory_keys = [self._collision_key(name) for name in requested_directories]
        if len(set(directory_keys)) != len(directory_keys):
            raise ValueError("Selected folder names must be unique")
        os.makedirs(input_root, mode=0o700, exist_ok=True)
        stage = os.path.join(workspace, f".upload-{uuid.uuid4().hex}")
        os.mkdir(stage, mode=0o700)
        staged_names: set[str] = set()
        staged_records = []
        committed_paths = []
        created_directories = []
        existing = {self._collision_key(str(item["name"])) for item in self._inventory(input_root)}
        total_existing = sum(int(item["size_bytes"]) for item in self._inventory(input_root))
        total_new = 0
        try:
            for raw_name, source in files:
                if len(staged_records) >= self.max_upload_files:
                    raise WorkspaceLimitError("Too many files selected for one workspace")
                name = self._relative_name(raw_name)
                folded = self._collision_key(name)
                if folded in staged_names or folded in existing:
                    raise ValueError(f"Duplicate file name: {name}")
                staged_names.add(folded)
                target = os.path.join(stage, *PurePosixPath(name).parts)
                os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
                written, total_new = self._write_stream(
                    source, target, self.max_upload_bytes, total_new
                )
                if total_existing + total_new > self.max_upload_bytes:
                    raise WorkspaceLimitError("Uploaded files exceed the workspace size limit")
                staged_records.append({"name": name, "size_bytes": written})

            existing_directory_names = self._directory_inventory(input_root)
            existing_directory_keys = {self._collision_key(name): name for name in existing_directory_names}
            staged_file_names = {self._collision_key(str(record["name"])) for record in staged_records}
            all_file_names = existing | staged_file_names
            projected_directories = set(existing_directory_names)
            requested_directory_set = set(requested_directories)
            for name in [
                *(str(item["name"]) for item in self._inventory(input_root)),
                *(str(record["name"]) for record in staged_records),
                *requested_directories,
            ]:
                parts = PurePosixPath(name).parts
                for depth in range(1, len(parts)):
                    projected_directories.add("/".join(parts[:depth]))
                if name in requested_directory_set:
                    projected_directories.add(name)
                if len(projected_directories) > _MAX_WORKSPACE_DIRECTORIES:
                    raise WorkspaceLimitError("Workspace folder structure exceeds the 10,000-folder limit")
            for name, folded in zip(requested_directories, directory_keys, strict=True):
                existing_directory = existing_directory_keys.get(folded)
                if existing_directory is not None and existing_directory != name:
                    raise ValueError(f"Duplicate folder name: {name}")
                if folded in all_file_names:
                    raise ValueError(f"A selected folder conflicts with a file: {name}")
                if any(folded.startswith(f"{file_name}/") for file_name in all_file_names):
                    raise ValueError(f"A selected folder conflicts with a file: {name}")

            def ensure_directories(path: str) -> None:
                relative_parent = os.path.relpath(path, input_root)
                current = input_root
                if relative_parent == ".":
                    return
                for part in relative_parent.split(os.sep):
                    current = os.path.join(current, part)
                    if not os.path.exists(current):
                        os.mkdir(current, mode=0o700)
                        created_directories.append(current)
                    elif not os.path.isdir(current) or os.path.islink(current):
                        raise ValueError("An imported path conflicts with an existing file")

            for record in staged_records:
                name = str(record["name"])
                staged_path = os.path.join(stage, *PurePosixPath(name).parts)
                target = os.path.join(input_root, *PurePosixPath(name).parts)
                ensure_directories(os.path.dirname(target))
                # Hard-link publication is atomic and fails if another request created
                # the destination after the collision preflight; replace() would lose it.
                os.link(staged_path, target)
                committed_paths.append(target)
                os.unlink(staged_path)

            for name in sorted(requested_directories, key=lambda item: (item.count("/"), item.casefold())):
                target = os.path.join(input_root, *PurePosixPath(name).parts)
                ensure_directories(target)
                if os.path.exists(target) and (not os.path.isdir(target) or os.path.islink(target)):
                    raise ValueError(f"A selected folder conflicts with an existing file: {name}")
                if not os.path.exists(target):
                    os.mkdir(target, mode=0o700)
                    created_directories.append(target)
        except Exception:
            for committed in reversed(committed_paths):
                try:
                    os.unlink(committed)
                except OSError:
                    pass
            for created in reversed(created_directories):
                try:
                    os.rmdir(created)
                except OSError:
                    pass
            raise
        finally:
            shutil.rmtree(stage, ignore_errors=True)
        return staged_records

    @staticmethod
    def _reject_duplicate_manifest_keys(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Split manifest contains duplicate JSON fields")
            result[key] = value
        return result

    def _parse_split_manifest(self, content: bytes) -> dict:
        if len(content) > _MAX_SPLIT_MANIFEST_BYTES:
            raise WorkspaceLimitError("Split manifest exceeds the supported size limit")
        try:
            manifest = json.loads(
                content.decode("utf-8"),
                object_pairs_hook=self._reject_duplicate_manifest_keys,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Split manifest is not valid UTF-8 JSON") from error
        if not isinstance(manifest, dict) or set(manifest) != {
            "format", "version", "original_name", "total_size_bytes",
            "chunk_size_bytes", "file_sha256", "parts",
        }:
            raise ValueError("Split manifest has an unsupported structure")
        if manifest["format"] != "officekit-file-split" or type(manifest["version"]) is not int or manifest["version"] != 1:
            raise ValueError("Split manifest format or version is unsupported")
        self._relative_name(manifest["original_name"])
        total_size = manifest["total_size_bytes"]
        chunk_size = manifest["chunk_size_bytes"]
        digest = manifest["file_sha256"]
        parts = manifest["parts"]
        if type(total_size) is not int or not 0 <= total_size <= min(self.max_upload_bytes, self.max_archive_bytes):
            raise ValueError("Split manifest total size is invalid")
        if type(chunk_size) is not int or not 1 <= chunk_size <= min(self.max_upload_bytes, self.max_archive_bytes):
            raise ValueError("Split manifest chunk size is invalid")
        if not isinstance(digest, str) or not _SHA256_HEX.fullmatch(digest):
            raise ValueError("Split manifest file checksum is invalid")
        max_parts = min(self.max_upload_files - 1, self.max_archive_files - 1)
        expected_count = max(1, (total_size + chunk_size - 1) // chunk_size)
        if not isinstance(parts, list) or len(parts) != expected_count or len(parts) > max_parts:
            raise ValueError("Split manifest part count is invalid")

        seen = set()
        for index, part in enumerate(parts, start=1):
            if not isinstance(part, dict) or set(part) != {"index", "name", "size_bytes", "sha256"}:
                raise ValueError("Split manifest part is malformed")
            name = part["name"]
            expected_name = f"part-{index:05d}.bin"
            expected_size = min(chunk_size, max(0, total_size - (index - 1) * chunk_size))
            if (
                type(part["index"]) is not int or part["index"] != index
                or name != expected_name
                or type(part["size_bytes"]) is not int or part["size_bytes"] != expected_size
                or not isinstance(part["sha256"], str) or not _SHA256_HEX.fullmatch(part["sha256"])
            ):
                raise ValueError("Split manifest part order, name, size or checksum is invalid")
            folded = self._collision_key(self._relative_name(name))
            if folded in seen:
                raise ValueError("Split manifest contains duplicate part names")
            seen.add(folded)
        return manifest

    def _publish_zip_artifact(self, workspace: str, stage: str, artifact_id: str) -> None:
        workspace_root = os.path.realpath(workspace)
        output_root = os.path.join(workspace_root, "outputs")
        os.makedirs(output_root, mode=0o700, exist_ok=True)
        output_metadata = os.lstat(output_root)
        if (
            not stat.S_ISDIR(output_metadata.st_mode)
            or os.path.realpath(output_root) != output_root
            or os.path.commonpath((os.path.realpath(output_root), workspace_root)) != workspace_root
        ):
            raise FileNotFoundError("Workspace artifact directory is not available")
        artifact_path = os.path.join(output_root, artifact_id)
        if os.path.lexists(artifact_path):
            raise FileExistsError("Artifact identifier collision")
        os.rename(stage, artifact_path)

    @staticmethod
    def _stored_zip_size_bytes(entries: list[tuple[str, int]]) -> int:
        """Return ZIP_STORED size including local, central and end records."""
        return 22 + sum(
            size_bytes + 76 + 2 * len(name.encode("utf-8"))
            for name, size_bytes in entries
        )

    def create_split_artifact(self, workspace_id: str, filename: str, chunk_size: int = 52_428_800) -> dict:
        workspace = self._workspace_path(workspace_id)
        safe_name = self._relative_name(filename)
        max_bytes = min(self.max_upload_bytes, self.max_archive_bytes)
        if type(chunk_size) is not int or not 1 <= chunk_size <= max_bytes:
            raise ValueError("Chunk size must be a positive integer within the workspace limit")
        max_parts = min(self.max_upload_files - 1, self.max_archive_files - 1)
        input_root = os.path.realpath(os.path.join(workspace, "input"))
        source_path = os.path.join(input_root, *PurePosixPath(safe_name).parts)
        if os.path.commonpath((os.path.realpath(source_path), input_root)) != input_root:
            raise FileNotFoundError("Selected workspace file is not available")
        source, before = self._open_workspace_file(source_path)
        stage = None
        try:
            if before.st_size > max_bytes:
                raise WorkspaceLimitError("Selected file exceeds the split size limit")
            total_size = before.st_size
            part_count = max(1, (total_size + chunk_size - 1) // chunk_size)
            if part_count > max_parts:
                raise WorkspaceLimitError("Split would create too many parts for one workspace")

            artifact_id = uuid.uuid4().hex
            stage = os.path.join(workspace, f".split-{artifact_id}")
            os.mkdir(stage, mode=0o700)
            parts = []
            whole_digest = hashlib.sha256()
            bytes_read = 0
            for index in range(1, part_count + 1):
                part_name = f"part-{index:05d}.bin"
                part_path = os.path.join(stage, part_name)
                expected_part_size = min(chunk_size, total_size - bytes_read)
                part_digest = hashlib.sha256()
                part_bytes = 0
                with open(part_path, "xb") as output:
                    while part_bytes < expected_part_size:
                        chunk = source.read(min(_CHUNK_SIZE, expected_part_size - part_bytes))
                        if not chunk:
                            raise ValueError("Selected file changed while it was being split")
                        part_bytes += len(chunk)
                        bytes_read += len(chunk)
                        part_digest.update(chunk)
                        whole_digest.update(chunk)
                        output.write(chunk)
                parts.append({
                    "index": index,
                    "name": part_name,
                    "size_bytes": part_bytes,
                    "sha256": part_digest.hexdigest(),
                })
            if source.read(1):
                raise ValueError("Selected file changed while it was being split")
            self._verify_workspace_file_unchanged(source, before)
            manifest = {
                "format": "officekit-file-split",
                "version": 1,
                "original_name": safe_name,
                "total_size_bytes": bytes_read,
                "chunk_size_bytes": chunk_size,
                "file_sha256": whole_digest.hexdigest(),
                "parts": parts,
            }
            manifest_bytes = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if len(manifest_bytes) > _MAX_SPLIT_MANIFEST_BYTES:
                raise WorkspaceLimitError("Split manifest exceeds the supported size limit")
            estimated_archive_bytes = self._stored_zip_size_bytes(
                [("split-manifest.json", len(manifest_bytes))]
                + [(str(part["name"]), int(part["size_bytes"])) for part in parts]
            )
            if estimated_archive_bytes > max_bytes:
                raise WorkspaceLimitError("Split archive exceeds the workspace size limit")
            manifest_path = os.path.join(stage, "split-manifest.json")
            with open(manifest_path, "xb") as output:
                output.write(manifest_bytes)
            bundle_path = os.path.join(stage, "bundle.zip")
            with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
                bundle.write(manifest_path, arcname="split-manifest.json")
                for part in parts:
                    bundle.write(os.path.join(stage, str(part["name"])), arcname=str(part["name"]))
            if os.path.getsize(bundle_path) > max_bytes:
                raise WorkspaceLimitError("Split archive exceeds the workspace size limit")
            self._publish_zip_artifact(workspace, stage, artifact_id)
        except Exception:
            if stage is not None:
                shutil.rmtree(stage, ignore_errors=True)
            raise
        finally:
            source.close()
        return {
            "artifact_id": artifact_id,
            "original_name": safe_name,
            "total_bytes": total_size,
            "chunk_size_bytes": chunk_size,
            "chunk_count": part_count,
            "sha256": whole_digest.hexdigest(),
            "parts": parts,
            "download_name": f"{PurePosixPath(safe_name).name}.split.zip",
        }

    def create_join_artifact(self, workspace_id: str, archive_name: str, output_name: str) -> dict:
        workspace = self._workspace_path(workspace_id)
        safe_archive_name = self._relative_name(archive_name)
        safe_output_name = self._portable_filename(output_name)
        if len(safe_output_name.encode("utf-8")) > 255:
            raise ValueError("Joined output name exceeds 255 UTF-8 bytes")
        input_root = os.path.realpath(os.path.join(workspace, "input"))
        archive_path = os.path.join(input_root, *PurePosixPath(safe_archive_name).parts)
        if os.path.commonpath((os.path.realpath(archive_path), input_root)) != input_root:
            raise FileNotFoundError("Split archive is not available in this workspace")
        artifact_id = uuid.uuid4().hex
        stage = os.path.join(workspace, f".join-{artifact_id}")
        output_path = os.path.join(stage, safe_output_name)
        joined_digest = hashlib.sha256()
        joined_bytes = 0
        archive_source = None
        try:
            os.mkdir(stage, mode=0o700)
            archive_source, archive_metadata = self._open_workspace_file(archive_path)
            with zipfile.ZipFile(archive_source, "r") as archive:
                entries = archive.infolist()
                if len(entries) > self.max_archive_files:
                    raise WorkspaceLimitError("Split archive contains too many entries")
                indexed_entries = {}
                manifest_entry = None
                total_archive_bytes = 0
                for entry in entries:
                    if entry.flag_bits & 1 or entry.compress_type != zipfile.ZIP_STORED:
                        raise ValueError("Split archive must contain unencrypted stored files")
                    entry_mode = stat.S_IFMT(entry.external_attr >> 16)
                    if entry_mode not in {0, stat.S_IFREG}:
                        raise ValueError("Split archive contains a special file")
                    entry_name = self._relative_name(entry.filename)
                    folded = self._collision_key(entry_name)
                    if folded in indexed_entries or (manifest_entry is not None and folded == "split-manifest.json"):
                        raise ValueError("Split archive contains duplicate entry names")
                    total_archive_bytes += entry.file_size
                    if total_archive_bytes > self.max_archive_bytes + _MAX_SPLIT_MANIFEST_BYTES:
                        raise WorkspaceLimitError("Split archive exceeds the supported size limit")
                    if entry_name == "split-manifest.json":
                        if entry.file_size > _MAX_SPLIT_MANIFEST_BYTES:
                            raise WorkspaceLimitError("Split manifest exceeds the supported size limit")
                        manifest_entry = entry
                    else:
                        indexed_entries[entry_name] = entry
                if manifest_entry is None:
                    raise ValueError("Split archive is missing its manifest")
                if manifest_entry.file_size < 0 or manifest_entry.file_size > _MAX_SPLIT_MANIFEST_BYTES:
                    raise WorkspaceLimitError("Split manifest exceeds the supported size limit")
                with archive.open(manifest_entry) as source:
                    manifest_bytes = source.read(_MAX_SPLIT_MANIFEST_BYTES + 1)
                manifest = self._parse_split_manifest(manifest_bytes)
                expected_names = {str(part["name"]) for part in manifest["parts"]}
                if set(indexed_entries) != expected_names:
                    raise ValueError("Split archive entries do not match the manifest")

                with open(output_path, "xb") as output:
                    for part in manifest["parts"]:
                        entry = indexed_entries[str(part["name"])]
                        if entry.file_size != part["size_bytes"]:
                            raise ValueError("Split part size does not match its manifest")
                        part_digest = hashlib.sha256()
                        part_bytes = 0
                        with archive.open(entry) as source:
                            while part_bytes < part["size_bytes"]:
                                chunk = source.read(min(_CHUNK_SIZE, part["size_bytes"] - part_bytes))
                                if not chunk:
                                    raise ValueError("Split part ended before its manifest size")
                                part_bytes += len(chunk)
                                joined_bytes += len(chunk)
                                part_digest.update(chunk)
                                joined_digest.update(chunk)
                                output.write(chunk)
                            if source.read(1):
                                raise ValueError("Split part grew beyond its manifest size")
                        if part_digest.hexdigest() != part["sha256"]:
                            raise ValueError("Split part checksum does not match its manifest")
                if joined_bytes != manifest["total_size_bytes"]:
                    raise ValueError("Joined file size does not match its manifest")
                if joined_digest.hexdigest() != manifest["file_sha256"]:
                    raise ValueError("Joined file checksum does not match its manifest")
            self._verify_workspace_file_unchanged(archive_source, archive_metadata)
            bundle_path = os.path.join(stage, "bundle.zip")
            with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as bundle:
                bundle.write(output_path, arcname=f"joined/{safe_output_name}")
            if os.path.getsize(bundle_path) > min(self.max_upload_bytes, self.max_archive_bytes):
                raise WorkspaceLimitError("Joined output archive exceeds the workspace size limit")
            self._publish_zip_artifact(workspace, stage, artifact_id)
        except (zipfile.BadZipFile, OSError, RuntimeError) as error:
            shutil.rmtree(stage, ignore_errors=True)
            if isinstance(error, zipfile.BadZipFile):
                raise ValueError("File is not a valid OfficeKit split archive") from error
            raise
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        finally:
            if archive_source is not None:
                archive_source.close()
        return {
            "artifact_id": artifact_id,
            "output_name": safe_output_name,
            "total_bytes": joined_bytes,
            "part_count": len(manifest["parts"]),
            "sha256": joined_digest.hexdigest(),
            "download_name": f"{safe_output_name}.zip",
        }

    def extract_archive(self, workspace_id: str, archive_name: str, output_name: str) -> dict:
        workspace = self._workspace_path(workspace_id)
        safe_archive_name = self._relative_name(archive_name)
        if not isinstance(output_name, str) or not output_name or "/" in output_name or "\\" in output_name:
            raise ValueError("Output folder name must be one relative path component")
        safe_output_name = self._relative_name(output_name)
        if "/" in safe_output_name:
            raise ValueError("Output folder name must be one relative path component")
        source_path = os.path.join(workspace, "input", *PurePosixPath(safe_archive_name).parts)
        if not os.path.isfile(source_path) or os.path.islink(source_path):
            raise FileNotFoundError("Archive not found in this workspace")

        artifact_id = uuid.uuid4().hex
        output_root = os.path.join(workspace, "outputs")
        os.makedirs(output_root, mode=0o700, exist_ok=True)
        stage = os.path.join(workspace, f".extract-{artifact_id}")
        os.mkdir(stage, mode=0o700)
        archive_source = None
        files: list[str] = []
        total_bytes = 0
        seen_files: set[str] = set()
        seen_directories: dict[str, str] = {}
        try:
            archive_source, source_metadata = self._open_workspace_file(source_path)
            with zipfile.ZipFile(archive_source) as archive:
                entries = archive.infolist()
                if len(entries) > self.max_archive_files:
                    raise WorkspaceLimitError("Archive contains too many entries")
                output_dir = os.path.join(stage, safe_output_name)
                os.mkdir(output_dir, mode=0o700)
                for info in entries:
                    if info.flag_bits & 1:
                        raise ValueError("Encrypted archives are not supported")
                    name = info.filename.rstrip("/")
                    if not name:
                        continue
                    safe_name = self._relative_name(name)
                    mode = info.external_attr >> 16
                    entry_type = stat.S_IFMT(mode)
                    if entry_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                        raise ValueError("Archive contains a special file")
                    path_parts = PurePosixPath(safe_name).parts
                    normalized_parts = tuple(unicodedata.normalize("NFC", part) for part in path_parts)
                    key_parts = tuple(part.casefold() for part in normalized_parts)
                    folded = "/".join(key_parts)
                    is_directory = info.is_dir() or entry_type == stat.S_IFDIR
                    directory_depth = len(path_parts) if is_directory else len(path_parts) - 1
                    for depth in range(1, directory_depth + 1):
                        directory_key = "/".join(key_parts[:depth])
                        directory_name = "/".join(path_parts[:depth])
                        prior_name = seen_directories.get(directory_key)
                        if prior_name is not None and prior_name != directory_name:
                            raise ValueError(f"Archive contains colliding paths: {safe_name}")
                        seen_directories[directory_key] = directory_name
                    target = os.path.join(output_dir, *path_parts)
                    if is_directory:
                        if folded in seen_files:
                            raise ValueError(f"Archive file paths conflict: {safe_name}")
                        os.makedirs(target, mode=0o700, exist_ok=True)
                        continue
                    if folded in seen_files:
                        raise ValueError(f"Archive contains duplicate file paths: {safe_name}")
                    if folded in seen_directories:
                        raise ValueError(f"Archive file paths conflict: {safe_name}")
                    if any("/".join(key_parts[:index]) in seen_files for index in range(1, len(key_parts))):
                        raise ValueError("Archive file paths conflict")
                    seen_files.add(folded)
                    if info.file_size < 0 or total_bytes + info.file_size > self.max_archive_bytes:
                        raise WorkspaceLimitError("Archive exceeds the extracted size limit")
                    if any(
                        os.path.isfile(os.path.join(output_dir, *PurePosixPath(safe_name).parts[:index]))
                        for index in range(1, len(PurePosixPath(safe_name).parts))
                    ):
                        raise ValueError("Archive file paths conflict")
                    os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
                    written = 0
                    with archive.open(info) as source, open(target, "xb") as output:
                        while True:
                            chunk = source.read(_CHUNK_SIZE)
                            if not chunk:
                                break
                            written += len(chunk)
                            total_bytes += len(chunk)
                            if total_bytes > self.max_archive_bytes or written > info.file_size:
                                raise WorkspaceLimitError("Archive exceeds the extracted size limit")
                            output.write(chunk)
                    if written != info.file_size:
                        raise ValueError("Archive entry size did not match its contents")
                    files.append(safe_name)

            self._verify_workspace_file_unchanged(archive_source, source_metadata)

            bundle_path = os.path.join(stage, "bundle.zip")
            with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for name in sorted(files, key=str.casefold):
                    path = os.path.join(output_dir, *PurePosixPath(name).parts)
                    bundle.write(path, arcname=f"{safe_output_name}/{name}")
            artifact_path = os.path.join(output_root, artifact_id)
            if os.path.exists(artifact_path):
                raise FileExistsError("Artifact identifier collision")
            os.replace(stage, artifact_path)
        except (zipfile.BadZipFile, OSError, RuntimeError) as error:
            shutil.rmtree(stage, ignore_errors=True)
            if isinstance(error, zipfile.BadZipFile):
                raise ValueError("File is not a valid ZIP archive") from error
            raise
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        finally:
            if archive_source is not None:
                archive_source.close()

        files.sort(key=str.casefold)
        return {
            "artifact_id": artifact_id,
            "output_name": safe_output_name,
            "file_count": len(files),
            "total_bytes": total_bytes,
            "files": files,
            "download_name": f"{safe_output_name}.zip",
        }

    def artifact_path(self, workspace_id: str, artifact_id: str) -> str:
        workspace = self._workspace_path(workspace_id)
        if not isinstance(artifact_id, str) or not _ARTIFACT_ID.fullmatch(artifact_id):
            raise FileNotFoundError("Artifact not found")
        path = os.path.join(workspace, "outputs", artifact_id, "bundle.zip")
        if not os.path.isfile(path) or os.path.islink(path):
            raise FileNotFoundError("Artifact not found")
        return path

    def clear_workspace(self, workspace_id: str) -> None:
        path = self._workspace_path(workspace_id)
        shutil.rmtree(path)

    def close(self) -> None:
        if self._temporary_root is not None:
            self._temporary_root.cleanup()
