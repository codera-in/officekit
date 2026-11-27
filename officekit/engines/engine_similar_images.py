"""Local perceptual-hash matching for user-selected image copies.

This module only receives paths constructed by ``FileWorkspaceStore``. It never
walks user directories or returns absolute paths to callers.
"""

from __future__ import annotations

import math
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Iterable


class SimilarImageDependencyError(RuntimeError):
    """Raised when the optional image decoder is unavailable."""


class SimilarImagePixelBudgetError(ValueError):
    """The selected images exceed the bounded cumulative scan workload."""

    def __init__(self):
        super().__init__("Aggregate image scan work limit reached; select fewer or smaller images")


class SimilarImagePixelBudget:
    def __init__(self, limit: int):
        self.remaining = limit

    def reserve(self, pixels: int) -> None:
        if pixels > self.remaining:
            raise SimilarImagePixelBudgetError()
        self.remaining -= pixels


class SimilarImageEngine:
    HASH_SIZE = 32
    # Grouping compares only candidate pairs above FULL_COMPARE_LIMIT, so the cost
    # grows with the number of likely matches rather than with n squared.
    MAX_FILES = 10_000
    FULL_COMPARE_LIMIT = 600
    TIME_WINDOW_SECONDS = 600
    TIME_NEIGHBOURS = 40
    STEM_NEIGHBOURS = 50
    HASH_BLOCKS = 13
    BUCKET_LIMIT = 400
    CROWDED_NEIGHBOURS = 20
    CHECK_EVERY_PAIRS = 2_000
    MAX_PIXELS = 40_000_000
    MAX_TOTAL_PIXELS = 250_000_000_000
    MAX_HEIC_BYTES = 128 * 1024 * 1024
    MAX_HEIC_DECODED_BYTES = 4 * 1024 * 1024
    HEIC_DECODE_EDGE = 512
    HEIC_DECODE_TIMEOUT_SECONDS = 20
    FINGERPRINT_CROP_SIZES = (28, 24, 16)
    OFF_CENTER_CROP_SIZE = 24
    MAX_FINGERPRINTS = 9 + len(FINGERPRINT_CROP_SIZES) + 4
    BURST_CLUSTER_DISTANCE_LIMIT = 16
    SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
    MACOS_HEIC_EXTENSIONS = {".heic", ".heif"}
    _SIPS = "/usr/bin/sips"
    _COSINE = tuple(
        tuple(math.cos((2 * position + 1) * frequency * math.pi / 64) for position in range(32))
        for frequency in range(8)
    )

    @staticmethod
    def _validate_name(name: str) -> str:
        if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
            raise ValueError("Image names must be non-empty relative paths")
        path = PurePosixPath(name)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in name.split("/")):
            raise ValueError("Image names must be non-empty relative paths")
        if path.parts and ":" in path.parts[0]:
            raise ValueError("Drive-qualified image names are not allowed")
        return path.as_posix()

    @classmethod
    def perceptual_hash(cls, luma_32x32: bytes) -> int:
        """Return a 64-bit DCT perceptual hash for exactly 32x32 luma samples."""
        if not isinstance(luma_32x32, bytes) or len(luma_32x32) != 1024:
            raise ValueError("Expected exactly 1,024 luma bytes")

        # The two-dimensional transform is separable. Transform each row first,
        # then transform those results by column; this preserves the same 8x8
        # coefficient set while avoiding 32x32 work for each coefficient.
        horizontal_rows = [
            tuple(
                sum(luma_32x32[y * 32 + x] * cls._COSINE[frequency][x] for x in range(32))
                for frequency in range(8)
            )
            for y in range(32)
        ]
        coefficients: list[float] = []
        for vertical in range(8):
            vertical_weights = cls._COSINE[vertical]
            for horizontal in range(8):
                if vertical == 0 and horizontal == 0:
                    continue
                total = sum(
                    vertical_weights[y] * horizontal_rows[y][horizontal]
                    for y in range(32)
                )
                coefficients.append(total if abs(total) >= 1e-8 else 0.0)

        ordered = sorted(coefficients)
        median = (ordered[31] + ordered[32]) / 2
        result = 0
        for coefficient in coefficients:
            result = (result << 1) | int(coefficient > median)
        return result

    @staticmethod
    def hamming_distance(hash_a: int, hash_b: int) -> int:
        if any(type(value) is not int or not 0 <= value < (1 << 64) for value in (hash_a, hash_b)):
            raise ValueError("Perceptual hashes must be unsigned 64-bit integers")
        return (hash_a ^ hash_b).bit_count()

    @classmethod
    def _fingerprint(cls, value: int | tuple[int, ...]) -> tuple[int, ...]:
        if type(value) is int:
            cls.hamming_distance(value, value)
            return (value,)
        if (
            not isinstance(value, tuple)
            or not value
            or len(value) > cls.MAX_FINGERPRINTS
            or any(type(item) is not int or not 0 <= item < (1 << 64) for item in value)
        ):
            raise ValueError("Perceptual fingerprints contain an invalid number or value of hashes")
        return value

    @classmethod
    def _fingerprint_distance(cls, fingerprint_a: tuple[int, ...], fingerprint_b: tuple[int, ...]) -> int:
        # Fingerprints are validated once on entry, so the hot loop skips per-call checks.
        return min((hash_a ^ hash_b).bit_count() for hash_a in fingerprint_a for hash_b in fingerprint_b)

    @staticmethod
    def _shift_luma(luma: bytes, dx: int, dy: int) -> bytes:
        shifted = bytearray(32 * 32)
        for y in range(32):
            source_y = max(0, min(31, y - dy))
            for x in range(32):
                source_x = max(0, min(31, x - dx))
                shifted[y * 32 + x] = luma[source_y * 32 + source_x]
        return bytes(shifted)

    @classmethod
    def _center_crop_luma(cls, luma: bytes, crop_size: int) -> bytes:
        if type(crop_size) is not int or crop_size not in cls.FINGERPRINT_CROP_SIZES:
            raise ValueError("Unsupported center-crop fingerprint size")
        offset = (32 - crop_size) // 2
        return cls._crop_luma(luma, crop_size, offset, offset)

    @staticmethod
    def _crop_luma(luma: bytes, crop_size: int, left: int, top: int) -> bytes:
        if not isinstance(luma, bytes) or len(luma) != 1024:
            raise ValueError("Expected exactly 1,024 luma bytes")
        if (
            type(crop_size) is not int or not 1 <= crop_size <= 32
            or type(left) is not int or type(top) is not int
            or left < 0 or top < 0 or left + crop_size > 32 or top + crop_size > 32
        ):
            raise ValueError("Crop fingerprint must fit inside the 32x32 image")
        return bytes(
            luma[(top + y * crop_size // 32) * 32 + left + x * crop_size // 32]
            for y in range(32)
            for x in range(32)
        )

    @classmethod
    def _perceptual_fingerprint(cls, luma: bytes) -> tuple[int, ...]:
        """Hash alignment and center-crop variants to tolerate burst-photo motion and zoom."""
        aligned = tuple(
            cls.perceptual_hash(cls._shift_luma(luma, dx, dy))
            for dy in (-1, 0, 1)
            for dx in (-1, 0, 1)
        )
        cropped = tuple(
            cls.perceptual_hash(cls._center_crop_luma(luma, size))
            for size in cls.FINGERPRINT_CROP_SIZES
        )
        edge = 32 - cls.OFF_CENTER_CROP_SIZE
        off_center = tuple(
            cls.perceptual_hash(cls._crop_luma(luma, cls.OFF_CENTER_CROP_SIZE, left, top))
            for left, top in ((0, 0), (edge, 0), (0, edge), (edge, edge))
        )
        return aligned + cropped + off_center

    @staticmethod
    def _open_image_source(path: str):
        """Open one regular image without following a final-component symlink."""
        if not isinstance(path, str) or not path:
            raise ValueError("Image could not be decoded")
        descriptor = None
        try:
            before = os.lstat(path)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("Image could not be decoded")
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            descriptor = os.open(path, flags)
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (os.name != "nt" and (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino))
            ):
                raise ValueError("Image could not be decoded")
            source = os.fdopen(descriptor, "rb")
            descriptor = None
            return source, opened
        except OSError as error:
            raise ValueError("Image could not be decoded") from error
        finally:
            if descriptor is not None:
                os.close(descriptor)

    @staticmethod
    def _same_file_snapshot(before, after) -> bool:
        if os.name == "nt":
            return (before.st_size, int(before.st_mtime)) == (after.st_size, int(after.st_mtime))
        return (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        )

    @classmethod
    def _macos_heic_copy(
        cls, path: str, pixel_budget: SimilarImagePixelBudget | None = None
    ) -> tuple[tempfile.TemporaryDirectory, str]:
        """Decode a verified, bounded HEIC copy using the macOS system codec."""
        if sys.platform != "darwin":
            raise ValueError("HEIC scanning is supported on macOS only")

        temporary = tempfile.TemporaryDirectory(prefix="officekit-heic-")
        source_path = os.path.join(temporary.name, "selected.heic")
        output_path = os.path.join(temporary.name, "decoded.jpg")
        try:
            file_source, before = cls._open_image_source(path)
            with file_source, open(source_path, "xb") as copied:
                if before.st_size > cls.MAX_HEIC_BYTES:
                    raise ValueError("HEIC image exceeds the supported file-size limit")
                copied_bytes = 0
                while True:
                    chunk = file_source.read(64 * 1024)
                    if not chunk:
                        break
                    copied_bytes += len(chunk)
                    if copied_bytes > cls.MAX_HEIC_BYTES:
                        raise ValueError("HEIC image exceeds the supported file-size limit")
                    copied.write(chunk)
                after = os.fstat(file_source.fileno())
                if not cls._same_file_snapshot(before, after):
                    raise ValueError("Image changed while it was being scanned")

            dimensions = subprocess.run(
                [cls._SIPS, "-g", "pixelWidth", "-g", "pixelHeight", source_path],
                capture_output=True,
                check=False,
                timeout=cls.HEIC_DECODE_TIMEOUT_SECONDS,
            )
            if dimensions.returncode != 0:
                raise ValueError("Image could not be decoded")
            values = re.findall(rb"pixel(?:Width|Height):\s*(\d+)", dimensions.stdout)
            if len(values) != 2:
                raise ValueError("Image could not be decoded")
            width, height = (int(value) for value in values)
            if width <= 0 or height <= 0 or width * height > cls.MAX_PIXELS:
                raise ValueError("Image dimensions exceed the supported scan limit")
            if pixel_budget is not None:
                pixel_budget.reserve(width * height)

            decoded = subprocess.run(
                [cls._SIPS, "-s", "format", "jpeg", "-Z", str(cls.HEIC_DECODE_EDGE), source_path, "--out", output_path],
                capture_output=True,
                check=False,
                timeout=cls.HEIC_DECODE_TIMEOUT_SECONDS,
            )
            if decoded.returncode != 0:
                raise ValueError("Image could not be decoded")
            if not os.path.isfile(output_path) or os.path.getsize(output_path) > cls.MAX_HEIC_DECODED_BYTES:
                raise ValueError("Decoded HEIC image exceeds the supported output limit")
            return temporary, output_path
        except subprocess.TimeoutExpired as error:
            temporary.cleanup()
            raise ValueError("Image decoding exceeded the time limit") from error
        except FileNotFoundError as error:
            temporary.cleanup()
            raise SimilarImageDependencyError("macOS image decoding is unavailable") from error
        except Exception:
            temporary.cleanup()
            raise

    @staticmethod
    def capture_time(image) -> float | None:
        """EXIF capture time as seconds, or None when the picture has none."""
        try:
            from datetime import datetime

            exif = image.getexif()
            raw = exif.get_ifd(0x8769).get(0x9003) or exif.get(0x0132)
            if not isinstance(raw, str):
                return None
            return datetime.strptime(raw.strip()[:19], "%Y:%m:%d %H:%M:%S").timestamp()
        except (AttributeError, ValueError, OSError, SyntaxError, TypeError):
            return None

    @staticmethod
    def _name_stem(name: str) -> str:
        """Folder plus file name without the copy, edit and numbering decorations."""
        folder, _, leaf = name.casefold().rpartition("/")
        leaf = leaf.rsplit(".", 1)[0] if "." in leaf else leaf
        leaf = re.sub(r"(?:[ _-]?(?:copy|edited|edit|final))+$", "", leaf)
        leaf = re.sub(r"\s*\(\d+\)$", "", leaf)
        leaf = re.sub(r"^(img|dsc|pxl)_e(?=\d)", r"\1_", leaf)
        return f"{folder}/{leaf}"

    @classmethod
    def _candidate_pairs(
        cls,
        images: list[tuple[str, tuple[int, ...]]],
        threshold: int,
        capture_times: dict[str, float],
    ):
        """Yield index pairs worth comparing, each once.

        Up to ``FULL_COMPARE_LIMIT`` images every pair is compared. Beyond that a
        pair is a candidate when the two images were taken close together, share a
        file-name stem, or share a block of their primary hash (a multi-index
        lookup, exact for primary-hash distances up to ``HASH_BLOCKS - 1``). The
        pixel fingerprint still decides whether a candidate is similar.
        """
        count = len(images)
        if count <= cls.FULL_COMPARE_LIMIT:
            for left in range(count):
                for right in range(left + 1, count):
                    yield left, right
            return

        emitted: set[tuple[int, int]] = set()

        def offer(left: int, right: int):
            if left == right:
                return None
            pair = (left, right) if left < right else (right, left)
            if pair in emitted:
                return None
            emitted.add(pair)
            return pair

        # Capture time: neighbours in time order inside the window.
        timed = sorted(
            (capture_times[name], index)
            for index, (name, _) in enumerate(images)
            if name in capture_times
        )
        for position, (moment, index) in enumerate(timed):
            for other_moment, other in timed[position + 1: position + 1 + cls.TIME_NEIGHBOURS]:
                if other_moment - moment > cls.TIME_WINDOW_SECONDS:
                    break
                pair = offer(index, other)
                if pair:
                    yield pair

        # File-name stem: IMG_1234, IMG_E1234, IMG_1234 (1) and IMG_1234-copy meet.
        stems: dict[str, list[int]] = {}
        for index, (name, _) in enumerate(images):
            stems.setdefault(cls._name_stem(name), []).append(index)
        for members in stems.values():
            for position, index in enumerate(members):
                for other in members[position + 1: position + 1 + cls.STEM_NEIGHBOURS]:
                    pair = offer(index, other)
                    if pair:
                        yield pair

        # Primary hash: images sharing any whole block of bits become candidates.
        blocks = min(threshold + 1, cls.HASH_BLOCKS)
        bounds = [round(block * 64 / blocks) for block in range(blocks + 1)]
        for block in range(blocks):
            low, width = bounds[block], bounds[block + 1] - bounds[block]
            buckets: dict[int, list[int]] = {}
            for index, (_, fingerprint) in enumerate(images):
                buckets.setdefault((fingerprint[0] >> low) & ((1 << width) - 1), []).append(index)
            for members in buckets.values():
                if len(members) > cls.BUCKET_LIMIT:
                    # A crowded bucket (flat or near-blank pictures) is compared
                    # along the primary hash order instead of all against all.
                    members = sorted(members, key=lambda item: images[item][1][0])
                    reach = cls.CROWDED_NEIGHBOURS
                else:
                    reach = len(members)
                for position, index in enumerate(members):
                    for other in members[position + 1: position + 1 + reach]:
                        pair = offer(index, other)
                        if pair:
                            yield pair

    @classmethod
    def group_hashes(
        cls,
        images: Iterable[tuple[str, int | tuple[int, ...]]],
        threshold: int = 8,
        capture_times: dict[str, float] | None = None,
        check=None,
    ) -> dict:
        if type(threshold) is not int or not 0 <= threshold <= 64:
            raise ValueError("Similarity threshold must be an integer from 0 to 64")
        image_list = []
        for image in images:
            if len(image_list) >= cls.MAX_FILES:
                raise ValueError(f"At most {cls.MAX_FILES} images can be compared at once")
            image_list.append(image)
        seen: set[str] = set()
        normalized_images = []
        for image in image_list:
            if not isinstance(image, (tuple, list)) or len(image) != 2:
                raise ValueError("Each image needs a relative name and perceptual hash")
            name, value = image
            name = cls._validate_name(name)
            if name in seen:
                raise ValueError("Image names must be non-empty and unique")
            seen.add(name)
            normalized_images.append((name, cls._fingerprint(value)))

        count = len(normalized_images)
        # Only distances that can still matter are kept: a pair farther apart than
        # the larger of the threshold and the burst limit can never share a group.
        # A missing pair therefore means "too far apart".
        keep_limit = max(threshold, cls.BURST_CLUSTER_DISTANCE_LIMIT)
        neighbours: list[dict[int, int]] = [{} for _ in range(count)]
        for step, (left, right) in enumerate(
            cls._candidate_pairs(normalized_images, threshold, capture_times or {})
        ):
            if check is not None and step % cls.CHECK_EVERY_PAIRS == 0:
                check()
            distance = cls._fingerprint_distance(
                normalized_images[left][1], normalized_images[right][1]
            )
            if distance <= keep_limit:
                neighbours[left][right] = distance
                neighbours[right][left] = distance
        too_far = keep_limit + 1

        def distance_between(left: int, right: int) -> int:
            return neighbours[left].get(right, too_far)

        # Seed groups from the most connected candidate so the first listed file
        # is a useful representative, independent of filenames or import order.
        ordered_indices = sorted(
            range(count),
            key=lambda index: (
                -sum(distance <= threshold for distance in neighbours[index].values()),
                normalized_images[index][0].casefold(),
            ),
        )
        clusters: list[list[int]] = []
        for image_index in ordered_indices:
            for cluster in clusters:
                image = normalized_images[image_index]
                has_image_variants = len(image[1]) > 1 and all(
                    len(normalized_images[member][1]) > 1 for member in cluster
                )
                cluster_limit = cls.BURST_CLUSTER_DISTANCE_LIMIT if has_image_variants else threshold
                member_distances = [distance_between(image_index, member) for member in cluster]
                if (
                    member_distances
                    and distance_between(image_index, cluster[0]) <= threshold
                    and max(member_distances) <= cluster_limit
                ):
                    cluster.append(image_index)
                    break
            else:
                clusters.append([image_index])

        groups = [cluster for cluster in clusters if len(cluster) > 1]
        groups.sort(key=lambda cluster: normalized_images[cluster[0]][0].casefold())
        pairs = [
            {
                "left": normalized_images[cluster[0]][0],
                "right": normalized_images[candidate][0],
                "distance": distance_between(cluster[0], candidate),
            }
            for cluster in groups
            for candidate in cluster[1:]
        ]
        return {
            "pairs": pairs,
            # A group's first member is its similarity-ranked representative.
            # Image variants have bounded pairwise slack, but every image must
            # remain within the requested threshold of that representative.
            "groups": [{
                "files": sorted(normalized_images[index][0] for index in cluster)
            } for cluster in groups],
        }

    @classmethod
    def _hash_image(cls, path: str, pixel_budget: SimilarImagePixelBudget | None = None) -> tuple[int, ...]:
        try:
            from PIL import Image, ImageOps, UnidentifiedImageError
        except ImportError as error:
            raise SimilarImageDependencyError("Image decoding is unavailable") from error

        temporary = None
        try:
            if Path(path).suffix.lower() in cls.MACOS_HEIC_EXTENSIONS:
                temporary, decode_path = cls._macos_heic_copy(path, pixel_budget)
                with Image.open(decode_path) as source:
                    image = ImageOps.exif_transpose(source.copy())
                    luma = image.convert("L").resize((32, 32), Image.Resampling.LANCZOS)
                    return cls._perceptual_fingerprint(luma.tobytes())

            file_source, before = cls._open_image_source(path)
            with file_source:
                with Image.open(file_source) as source:
                    if source.width <= 0 or source.height <= 0 or source.width * source.height > cls.MAX_PIXELS:
                        raise ValueError("Image dimensions exceed the supported scan limit")
                    if pixel_budget is not None:
                        pixel_budget.reserve(source.width * source.height)
                    source.seek(0)  # Burst/photo formats with frames use the first frame only.
                    image = ImageOps.exif_transpose(source.copy())
                    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
                        rgba = image.convert("RGBA")
                        background = Image.new("RGBA", rgba.size, "white")
                        image = Image.alpha_composite(background, rgba)
                    luma = image.convert("L").resize((32, 32), Image.Resampling.LANCZOS)
                    fingerprint = cls._perceptual_fingerprint(luma.tobytes())
                after = os.fstat(file_source.fileno())
                if not cls._same_file_snapshot(before, after):
                    raise ValueError("Image changed while it was being scanned")
                return fingerprint
        except (UnidentifiedImageError, OSError, EOFError, SyntaxError, Image.DecompressionBombError) as error:
            raise ValueError("Image could not be decoded") from error
        finally:
            if temporary is not None:
                temporary.cleanup()

    @classmethod
    def scan_files(cls, files: Iterable[tuple[str, str]], threshold: int = 8) -> dict:
        if type(threshold) is not int or not 0 <= threshold <= 64:
            raise ValueError("Similarity threshold must be an integer from 0 to 64")
        file_list = []
        for item in files:
            if len(file_list) >= cls.MAX_FILES:
                raise ValueError(f"At most {cls.MAX_FILES} images can be compared at once")
            file_list.append(item)

        names: set[str] = set()
        validated_files = []
        for item in file_list:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                raise ValueError("Each input needs a relative name and local path")
            relative_name, path = item
            relative_name = cls._validate_name(relative_name)
            if relative_name in names or not isinstance(path, str) or not path:
                raise ValueError("Image inputs must have unique relative names and local paths")
            names.add(relative_name)
            validated_files.append((relative_name, path))

        hashes: list[tuple[str, int | tuple[int, ...]]] = []
        skipped: list[str] = []
        errors: list[dict[str, str]] = []
        pixel_budget = SimilarImagePixelBudget(cls.MAX_TOTAL_PIXELS)
        for relative_name, path in validated_files:
            extension = Path(relative_name).suffix.lower()
            if extension not in cls.SUPPORTED_EXTENSIONS and not (
                extension in cls.MACOS_HEIC_EXTENSIONS and sys.platform == "darwin"
            ):
                skipped.append(relative_name)
                continue
            try:
                hashes.append((relative_name, cls._hash_image(path, pixel_budget)))
            except SimilarImageDependencyError:
                raise
            except (ValueError, OSError) as error:
                errors.append({"name": relative_name, "message": str(error)[:160]})

        report = cls.group_hashes(hashes, threshold)
        report.update({
            "scanned_images": len(hashes),
            "skipped_files": sorted(skipped, key=str.casefold),
            "errors": sorted(errors, key=lambda item: item["name"].casefold()),
            "complete": not errors,
            "method": "dct-perceptual-hash",
            "frames_per_file": 1,
        })
        return report
