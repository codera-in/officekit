"""
OfficeKit - File Utilities & Safe Storage Analysis Engine (Pillars 5 & 6)
High-performance local filesystem operations:
- Batch File Renamer (Sequence, Affix, Casing, Regex)
- Two-Phase Fast Exact Duplicate Finder (First 4KB chunk hash -> Full SHA-256)
- Safe Storage Analyzer (Folder sizes, large files, zero-byte scans, system-path safeguards)
"""

import os
import hashlib
import stat
from typing import List, Dict, Any, Optional


class FileOpsEngine:
    DUPLICATE_PREFILTER_BYTES = 4096


    @staticmethod
    def generate_rename_plan(
        filenames: List[str],
        pattern_type: str = "sequence",
        prefix: str = "",
        suffix: str = "",
        start_num: int = 1,
        digits: int = 3,
        casing: str = "kebab",
        find_text: str = "",
        replace_text: str = ""
    ) -> List[str]:
        """Calculates dry-run renamed filenames before applying."""
        results = []
        for idx, fname in enumerate(filenames):
            base, ext = os.path.splitext(fname)
            new_base = base

            if pattern_type == "sequence":
                num_str = str(start_num + idx).zfill(digits)
                new_base = f"{prefix}{num_str}{suffix}"
            elif pattern_type == "affix":
                new_base = f"{prefix}{base}{suffix}"
            elif pattern_type == "casing":
                clean_words = []
                current_word = []
                for character in base:
                    if character.isalnum():
                        current_word.append(character)
                    elif current_word:
                        clean_words.append("".join(current_word))
                        current_word = []
                if current_word:
                    clean_words.append("".join(current_word))
                if casing == "kebab":
                    new_base = "-".join(w.lower() for w in clean_words)
                elif casing == "snake":
                    new_base = "_".join(w.lower() for w in clean_words)
                elif casing == "camel":
                    new_base = clean_words[0].lower() + "".join(w.capitalize() for w in clean_words[1:]) if clean_words else ""
                elif casing == "title":
                    new_base = " ".join(w.capitalize() for w in clean_words)
            elif pattern_type == "replace" and find_text:
                new_base = base.replace(find_text, replace_text)

            results.append(f"{new_base}{ext}")
        return results

    @staticmethod
    def find_duplicate_files(root_dir: str) -> List[Dict[str, Any]]:
        """
        Backwards-compatible groups-only view of the bounded duplicate scan.
        """
        return FileOpsEngine.find_duplicate_files_report(root_dir)["groups"]

    @staticmethod
    def find_duplicate_files_report(root_dir: str, max_entries: int = 100_000) -> Dict[str, Any]:
        """Scan a directory for byte-identical regular files without following symlinks."""
        if type(max_entries) is not int or max_entries <= 0:
            raise ValueError("max_entries must be a positive integer")

        scan_root = os.path.realpath(os.path.abspath(os.fspath(root_dir)))
        if not os.path.isdir(scan_root):
            raise NotADirectoryError(f"Duplicate scan root is not a directory: {scan_root}")

        def signature(file_stat: os.stat_result) -> tuple:
            if os.name == "nt":
                return (file_stat.st_size, int(file_stat.st_mtime))
            return (
                file_stat.st_dev,
                file_stat.st_ino,
                file_stat.st_size,
                getattr(file_stat, "st_mtime_ns", int(file_stat.st_mtime * 1_000_000_000)),
                getattr(file_stat, "st_ctime_ns", int(file_stat.st_ctime * 1_000_000_000)),
            )

        size_map: Dict[int, List[tuple]] = {}
        errors = []
        skipped_symlinks = 0
        entries_seen = 0
        files_scanned = 0
        limit_reached = False

        def record_walk_error(error: OSError) -> None:
            errors.append({"path": error.filename or scan_root, "error": str(error)})

        for root, dirs, files in os.walk(
            scan_root, topdown=True, followlinks=False, onerror=record_walk_error
        ):
            kept_dirs = []
            for directory in dirs:
                if entries_seen >= max_entries:
                    limit_reached = True
                    break
                entries_seen += 1
                path = os.path.join(root, directory)
                if os.path.islink(path):
                    skipped_symlinks += 1
                else:
                    kept_dirs.append(directory)
            dirs[:] = [] if limit_reached else kept_dirs
            if limit_reached:
                break

            for file in files:
                if entries_seen >= max_entries:
                    limit_reached = True
                    break
                entries_seen += 1
                path = os.path.join(root, file)
                try:
                    file_stat = os.stat(path, follow_symlinks=False)
                    if stat.S_ISLNK(file_stat.st_mode):
                        skipped_symlinks += 1
                    elif stat.S_ISREG(file_stat.st_mode):
                        files_scanned += 1
                        size_map.setdefault(file_stat.st_size, []).append((path, signature(file_stat)))
                except OSError as error:
                    errors.append({"path": path, "error": str(error)})
            if limit_reached:
                dirs[:] = []
                break

        if limit_reached:
            errors.append({"path": scan_root, "error": f"Scan stopped at the {max_entries} entry limit"})

        prefix_map: Dict[tuple[int, bytes], List[tuple]] = {}
        for size_bytes, candidates in size_map.items():
            if len(candidates) < 2:
                continue
            for path, initial_signature in candidates:
                try:
                    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                    with os.fdopen(fd, "rb") as file_handle:
                        before = os.fstat(file_handle.fileno())
                        if not stat.S_ISREG(before.st_mode) or signature(before) != initial_signature:
                            errors.append({"path": path, "error": "File changed during duplicate scan"})
                            continue
                        prefix = file_handle.read(FileOpsEngine.DUPLICATE_PREFILTER_BYTES)
                        after = os.fstat(file_handle.fileno())
                        if signature(after) != initial_signature:
                            errors.append({"path": path, "error": "File changed during duplicate scan"})
                            continue
                        prefix_digest = hashlib.sha256(prefix).digest()
                        prefix_map.setdefault((size_bytes, prefix_digest), []).append((path, initial_signature))
                except OSError as error:
                    errors.append({"path": path, "error": str(error)})

        hash_map: Dict[str, List[tuple]] = {}
        for candidates in prefix_map.values():
            if len(candidates) < 2:
                continue
            for path, initial_signature in candidates:
                try:
                    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
                    with os.fdopen(fd, "rb") as file_handle:
                        before = os.fstat(file_handle.fileno())
                        if not stat.S_ISREG(before.st_mode) or signature(before) != initial_signature:
                            errors.append({"path": path, "error": "File changed during duplicate scan"})
                            continue
                        digest = hashlib.sha256()
                        while chunk := file_handle.read(65_536):
                            digest.update(chunk)
                        after = os.fstat(file_handle.fileno())
                        if signature(after) != initial_signature:
                            errors.append({"path": path, "error": "File changed during duplicate scan"})
                            continue
                        hash_map.setdefault(digest.hexdigest(), []).append((path, before.st_size))
                except OSError as error:
                    errors.append({"path": path, "error": str(error)})

        groups = []
        for digest, matches in hash_map.items():
            if len(matches) > 1:
                groups.append({
                    "hash": digest,
                    "size_bytes": matches[0][1],
                    "files": sorted(path for path, _ in matches),
                })
        groups.sort(key=lambda group: group["files"][0].casefold())

        return {
            "groups": groups,
            "files_scanned": files_scanned,
            "skipped_symlinks": skipped_symlinks,
            "complete": not errors and skipped_symlinks == 0,
            "errors": errors,
        }


class StorageAnalyzerEngine:
    """Safe storage inspector with system folder exclusions."""

    PROTECTED_SYSTEM_PATHS = {
        "/System", "/private/etc", "/private/var/db", "/private/var/root",
        "/usr", "/bin", "/sbin", "C:\\Windows", "C:\\Program Files"
    }

    @classmethod
    def analyze_directory(cls, dir_path: str, top_n: int = 10) -> Dict[str, Any]:
        """Scans directory and returns breakdown of sizes, file count, and top largest files."""
        if type(top_n) is not int or top_n < 0:
            raise ValueError("top_n must be a non-negative integer")

        abs_path = os.path.realpath(os.path.abspath(os.fspath(dir_path)))
        if not os.path.isdir(abs_path):
            raise NotADirectoryError(f"Storage scan root is not a directory: {abs_path}")

        def normalized(path: str) -> str:
            return os.path.normcase(os.path.realpath(os.path.abspath(path)))

        normalized_root = normalized(abs_path)
        for protected_path in cls.PROTECTED_SYSTEM_PATHS:
            normalized_protected = normalized(protected_path)
            try:
                shared_scope = os.path.commonpath((normalized_root, normalized_protected))
                if shared_scope in {normalized_root, normalized_protected}:
                    raise PermissionError(
                        f"Selected scan scope '{abs_path}' overlaps a protected system directory."
                    )
            except ValueError:
                # Different Windows drives cannot contain one another.
                continue

        total_size = 0
        file_records = []
        folder_totals = {}
        skipped_symlinks = 0
        errors = []

        def record_walk_error(error: OSError) -> None:
            errors.append({"path": error.filename or abs_path, "error": str(error)})

        for root, dirs, files in os.walk(
            abs_path, topdown=True, followlinks=False, onerror=record_walk_error
        ):
            kept_dirs = []
            for directory in dirs:
                path = os.path.join(root, directory)
                if os.path.islink(path):
                    skipped_symlinks += 1
                else:
                    kept_dirs.append(directory)
            dirs[:] = kept_dirs

            for file in files:
                p = os.path.join(root, file)
                try:
                    file_stat = os.stat(p, follow_symlinks=False)
                    if stat.S_ISLNK(file_stat.st_mode):
                        skipped_symlinks += 1
                        continue
                    if not stat.S_ISREG(file_stat.st_mode):
                        errors.append({"path": p, "error": "Not a regular file"})
                        continue
                    sz = file_stat.st_size
                    total_size += sz
                    relative = os.path.relpath(p, abs_path).replace(os.sep, "/")
                    file_records.append({
                        "name": relative,
                        "path": p,
                        "size_bytes": sz,
                        "size_mb": round(sz / (1024 * 1024), 2)
                    })
                    path_parts = relative.split("/")[:-1]
                    for depth in range(1, len(path_parts) + 1):
                        folder_name = "/".join(path_parts[:depth])
                        aggregate = folder_totals.setdefault(folder_name, {"file_count": 0, "size_bytes": 0})
                        aggregate["file_count"] += 1
                        aggregate["size_bytes"] += sz
                except OSError as error:
                    errors.append({"path": p, "error": str(error)})
                    continue

        file_records.sort(key=lambda item: (-item["size_bytes"], item["name"].casefold()))
        largest_folders = [
            {"name": name, **totals}
            for name, totals in folder_totals.items()
        ]
        largest_folders.sort(key=lambda item: (-item["size_bytes"], item["name"].casefold()))

        return {
            "scanned_path": abs_path,
            "total_files": len(file_records),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "largest_files": file_records[:top_n],
            "largest_folders": largest_folders[:top_n],
            "complete": not errors and skipped_symlinks == 0,
            "skipped_symlinks": skipped_symlinks,
            "errors": errors
        }
