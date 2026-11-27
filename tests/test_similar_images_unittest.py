"""Pure image-hash tests that do not require Pillow or a desktop runtime."""

import unittest
import base64
import builtins
import os
import tempfile
import math
import platform
import random
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from officekit.engines.engine_similar_images import SimilarImageEngine, SimilarImageDependencyError

try:
    from PIL import Image, ImageDraw, ImageEnhance
except ImportError:
    Image = None
    ImageDraw = None
    ImageEnhance = None


class SimilarImageHashTests(unittest.TestCase):
    @staticmethod
    def _burst_scene(subject_x: int = 9) -> bytes:
        pixels = []
        for y in range(32):
            for x in range(32):
                value = 35 + x // 2 + y // 3
                if (x - 16) ** 2 + (y - 15) ** 2 <= 50:
                    value = 165
                if (x - subject_x) ** 2 + (y - 22) ** 2 <= 8:
                    value = 95
                pixels.append(value)
        return bytes(pixels)

    def test_perceptual_hash_is_stable_for_uniform_brightness_changes(self):
        black = bytes([0] * 1024)
        gray = bytes([128] * 1024)
        white = bytes([255] * 1024)

        self.assertEqual(SimilarImageEngine.perceptual_hash(black), 0)
        self.assertEqual(SimilarImageEngine.perceptual_hash(black), SimilarImageEngine.perceptual_hash(gray))
        self.assertEqual(SimilarImageEngine.perceptual_hash(gray), SimilarImageEngine.perceptual_hash(white))

    def test_perceptual_hash_matches_direct_dct_reference(self):
        pixels = bytes((x * 29 + y * 47 + x * y * 3) % 256 for y in range(32) for x in range(32))
        cosine = tuple(
            tuple(math.cos((2 * position + 1) * frequency * math.pi / 64) for position in range(32))
            for frequency in range(8)
        )
        coefficients = []
        for vertical in range(8):
            for horizontal in range(8):
                if vertical == 0 and horizontal == 0:
                    continue
                coefficients.append(sum(
                    pixels[y * 32 + x] * cosine[vertical][y] * cosine[horizontal][x]
                    for y in range(32)
                    for x in range(32)
                ))
        ordered = sorted(coefficients)
        median = (ordered[31] + ordered[32]) / 2
        expected = 0
        for coefficient in coefficients:
            expected = (expected << 1) | int(coefficient > median)

        self.assertEqual(SimilarImageEngine.perceptual_hash(pixels), expected)

    def test_perceptual_hash_is_stable_for_identical_pixels_and_tolerant_of_small_noise(self):
        pixels = bytearray((x * 7 + y * 11) % 256 for y in range(32) for x in range(32))
        slightly_changed = bytearray(pixels)
        for index in (0, 117, 511, 900):
            slightly_changed[index] = min(255, slightly_changed[index] + 1)

        first = SimilarImageEngine.perceptual_hash(bytes(pixels))
        same = SimilarImageEngine.perceptual_hash(bytes(pixels))
        noisy = SimilarImageEngine.perceptual_hash(bytes(slightly_changed))

        self.assertEqual(first, same)
        self.assertLessEqual(SimilarImageEngine.hamming_distance(first, noisy), 8)

    def test_burst_like_scene_survives_exposure_camera_shift_and_subject_motion(self):
        base = self._burst_scene()
        exposed = bytes(min(255, round(value * 1.12 + 4)) for value in base)
        shifted = bytes(
            base[y * 32 + x - 1] if x > 0 else 35
            for y in range(32)
            for x in range(32)
        )
        moving_subject = self._burst_scene(subject_x=11)
        hashes = [SimilarImageEngine.perceptual_hash(image) for image in (base, exposed, shifted, moving_subject)]
        report = SimilarImageEngine.group_hashes(
            [(f"burst-{index}.jpg", value) for index, value in enumerate(hashes)], threshold=8
        )

        self.assertEqual(report["groups"], [{"files": ["burst-0.jpg", "burst-1.jpg", "burst-2.jpg", "burst-3.jpg"]}])

    def test_burst_recall_includes_crop_noise_and_two_pixel_camera_motion(self):
        base = self._burst_scene()
        shifted = bytes(
            base[(y - 2) * 32 + (x - 2)] if x >= 2 and y >= 2 else 35
            for y in range(32)
            for x in range(32)
        )
        cropped = bytes(
            base[(y * 28 // 32 + 2) * 32 + (x * 28 // 32 + 2)]
            for y in range(32)
            for x in range(32)
        )
        zoom_crop = bytes(
            base[(y * 24 // 32 + 4) * 32 + (x * 24 // 32 + 4)]
            for y in range(32)
            for x in range(32)
        )
        jpeg_like_noise = bytes(
            max(0, min(255, value + ((index * 17) % 7) - 3))
            for index, value in enumerate(base)
        )
        moving_subject = self._burst_scene(subject_x=12)
        unrelated_scenes = {
            "checkerboard": bytes(
                230 if (x // 4 + y // 4) % 2 == 0 else 20
                for y in range(32)
                for x in range(32)
            ),
            "horizontal_stripes": bytes(
                230 if y // 2 % 2 == 0 else 20 for y in range(32) for _x in range(32)
            ),
            "vertical_stripes": bytes(
                230 if x // 2 % 2 == 0 else 20 for _y in range(32) for x in range(32)
            ),
            "inverse_gradient": bytes(
                255 - ((x * 3 + y * 2) % 256) for y in range(32) for x in range(32)
            ),
        }
        variants = {
            "exposure_up": bytes(min(255, round(value * 1.18 + 8)) for value in base),
            "exposure_down": bytes(max(0, round(value * 0.82 - 6)) for value in base),
            "camera_shift_2px": shifted,
            "small_center_crop": cropped,
            "camera_zoom_crop": zoom_crop,
            "jpeg_like_noise": jpeg_like_noise,
            "subject_motion": moving_subject,
        }

        reference = SimilarImageEngine._perceptual_fingerprint(base)
        distances = {
            name: SimilarImageEngine._fingerprint_distance(
                reference, SimilarImageEngine._perceptual_fingerprint(pixels)
            )
            for name, pixels in variants.items()
        }
        missed = {name: distance for name, distance in distances.items() if distance > 8}
        self.assertEqual(missed, {}, f"Burst variants missed at the default threshold: {missed}")
        unrelated_hashes = {
            name: SimilarImageEngine._perceptual_fingerprint(pixels)
            for name, pixels in unrelated_scenes.items()
        }
        unrelated_distances = {
            name: SimilarImageEngine._fingerprint_distance(reference, fingerprint)
            for name, fingerprint in unrelated_hashes.items()
        }
        false_positives = {name: distance for name, distance in unrelated_distances.items() if distance <= 8}
        self.assertEqual(false_positives, {}, f"Unrelated scenes matched the burst: {false_positives}")

        report = SimilarImageEngine.group_hashes(
            [("burst-reference.jpg", reference)] + [
                (f"burst-{name}.jpg", SimilarImageEngine._perceptual_fingerprint(pixels))
                for name, pixels in variants.items()
            ] + [(f"unrelated-{name}.jpg", fingerprint) for name, fingerprint in unrelated_hashes.items()],
            threshold=8,
        )
        burst_group = next(
            group for group in report["groups"]
            if "burst-reference.jpg" in group["files"]
        )
        self.assertEqual(len(burst_group["files"]), len(variants) + 1, report)
        self.assertFalse(any(name.startswith("unrelated-") for name in burst_group["files"]))

    def test_burst_recall_includes_zoom_crops_with_off_center_framing(self):
        base = self._burst_scene()

        def zoom_crop(left: int, top: int, width: int = 24) -> bytes:
            return bytes(
                base[(top + y * width // 32) * 32 + left + x * width // 32]
                for y in range(32)
                for x in range(32)
            )

        reference = SimilarImageEngine._perceptual_fingerprint(base)
        for index, (left, top) in enumerate(((0, 0), (8, 0), (0, 8), (8, 8))):
            with self.subTest(left=left, top=top):
                crop = SimilarImageEngine._perceptual_fingerprint(zoom_crop(left, top))
                report = SimilarImageEngine.group_hashes(
                    [("wide.jpg", reference), (f"zoom-{index}.jpg", crop)], threshold=8
                )
                self.assertEqual(
                    report["groups"],
                    [{"files": ["wide.jpg", f"zoom-{index}.jpg"]}],
                    report,
                )

    def test_burst_recall_includes_small_handheld_camera_rotation(self):
        base = self._burst_scene()

        def rotate_luma(pixels: bytes, degrees: float) -> bytes:
            angle = math.radians(degrees)
            cosine = math.cos(angle)
            sine = math.sin(angle)
            center = 15.5
            rotated = bytearray(32 * 32)
            for y in range(32):
                for x in range(32):
                    dx = x - center
                    dy = y - center
                    source_x = round(cosine * dx + sine * dy + center)
                    source_y = round(-sine * dx + cosine * dy + center)
                    rotated[y * 32 + x] = (
                        pixels[source_y * 32 + source_x]
                        if 0 <= source_x < 32 and 0 <= source_y < 32
                        else 35
                    )
            return bytes(rotated)

        reference = SimilarImageEngine._perceptual_fingerprint(base)
        rotated_hashes = []
        for degrees in (-7.0, -5.0, -3.0, -1.5, 1.5, 3.0, 5.0, 7.0):
            with self.subTest(degrees=degrees):
                rotated = SimilarImageEngine._perceptual_fingerprint(rotate_luma(base, degrees))
                distance = SimilarImageEngine._fingerprint_distance(reference, rotated)
                self.assertLessEqual(distance, 8, f"{degrees}° rotation exceeded the default burst threshold")
                rotated_hashes.append((f"burst-{degrees}.jpg", rotated))

        report = SimilarImageEngine.group_hashes(
            [("burst-reference.jpg", reference), *rotated_hashes], threshold=8
        )
        self.assertEqual(len(report["groups"]), 1, report)
        self.assertEqual(len(report["groups"][0]["files"]), len(rotated_hashes) + 1, report)

    def test_fingerprint_variants_are_bounded_and_compared_by_best_alignment(self):
        with self.assertRaises(ValueError):
            SimilarImageEngine._fingerprint(())
        self.assertEqual(
            len(SimilarImageEngine._fingerprint((0,) * SimilarImageEngine.MAX_FINGERPRINTS)),
            SimilarImageEngine.MAX_FINGERPRINTS,
        )
        with self.assertRaises(ValueError):
            SimilarImageEngine._fingerprint((0,) * (SimilarImageEngine.MAX_FINGERPRINTS + 1))
        with self.assertRaises(ValueError):
            SimilarImageEngine._fingerprint((0, True))
        with self.assertRaises(ValueError):
            SimilarImageEngine._fingerprint([0, 1])

    def test_center_crop_fingerprint_validation_and_dimensions(self):
        pixels = bytes(range(256)) * 4
        for size in SimilarImageEngine.FINGERPRINT_CROP_SIZES:
            self.assertEqual(len(SimilarImageEngine._center_crop_luma(pixels, size)), 1024)
        self.assertEqual(len(SimilarImageEngine._crop_luma(pixels, 24, 8, 8)), 1024)
        for invalid in (True, 24.0, 32, 0):
            with self.assertRaises(ValueError):
                SimilarImageEngine._center_crop_luma(pixels, invalid)
        for crop in ((24, -1, 0), (24, 0, 9), (24, 9, 0), (24, True, 0), (33, 0, 0)):
            with self.subTest(crop=crop), self.assertRaises(ValueError):
                SimilarImageEngine._crop_luma(pixels, *crop)
        with self.assertRaises(ValueError):
            SimilarImageEngine._center_crop_luma(bytearray(pixels), 24)

        self.assertEqual(SimilarImageEngine._fingerprint_distance((0b0000, 0b1111), (0b0011,)), 2)

    def test_hash_inputs_and_thresholds_are_bounded(self):
        for invalid in (b"short", [0] * 1024, None):
            with self.subTest(invalid_type=type(invalid).__name__):
                with self.assertRaises(ValueError):
                    SimilarImageEngine.perceptual_hash(invalid)
        for invalid in (-1, 1 << 64, True, 1.5):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    SimilarImageEngine.hamming_distance(0, invalid)

    def test_similarity_groups_reject_transitive_chain_matches(self):
        images = [
            ("alpha.png", 0b0000),
            ("beta.png", 0b0001),
            ("bridge.png", 0b0011),
            ("gamma.png", 0b11000000),
            ("delta.png", 0b11000001),
        ]

        report = SimilarImageEngine.group_hashes(images, threshold=1)

        self.assertEqual(report["pairs"], [
            {"left": "beta.png", "right": "alpha.png", "distance": 1},
            {"left": "delta.png", "right": "gamma.png", "distance": 1},
        ])
        self.assertEqual(report["groups"], [
            {"files": ["alpha.png", "beta.png"]},
            {"files": ["delta.png", "gamma.png"]},
        ])

    def test_similarity_threshold_and_duplicate_names_are_rejected(self):
        for threshold in (-1, 65, True, 2.5):
            with self.subTest(threshold=threshold):
                with self.assertRaises(ValueError):
                    SimilarImageEngine.group_hashes([], threshold=threshold)
        with self.assertRaises(ValueError):
            SimilarImageEngine.group_hashes([("same.png", 0), ("same.png", 1)], threshold=1)
        for unsafe in ("/tmp/private.jpg", "../private.jpg", "C:/private.jpg", "folder\\private.jpg"):
            with self.subTest(name=unsafe), self.assertRaises(ValueError):
                SimilarImageEngine.group_hashes([(unsafe, 0)], threshold=1)
        for malformed in (["one.png"], None):
            with self.subTest(record=malformed), self.assertRaises(ValueError):
                SimilarImageEngine.group_hashes([malformed], threshold=1)

    def test_scan_reports_unsupported_files_as_skipped_and_decode_failures_as_incomplete(self):
        files = [("one.jpg", "/private/one.jpg"), ("notes.txt", "/private/notes.txt"), ("broken.png", "/private/broken.png")]
        with patch.object(SimilarImageEngine, "_hash_image", side_effect=[10, ValueError("Image could not be decoded")]):
            report = SimilarImageEngine.scan_files(files, threshold=4)

        self.assertEqual(report["scanned_images"], 1)
        self.assertEqual(report["skipped_files"], ["notes.txt"])
        self.assertEqual(report["errors"], [{"name": "broken.png", "message": "Image could not be decoded"}])
        self.assertFalse(report["complete"])
        self.assertNotIn("/private", str(report))
        self.assertEqual(report["frames_per_file"], 1)

    def test_heic_remains_an_explicitly_skipped_format_outside_macos(self):
        with patch("officekit.engines.engine_similar_images.sys.platform", "linux"), patch.object(
            SimilarImageEngine, "_hash_image"
        ) as decode:
            report = SimilarImageEngine.scan_files([("iphone.heic", "/private/iphone.heic")])

        self.assertEqual(report["scanned_images"], 0)
        self.assertEqual(report["skipped_files"], ["iphone.heic"])
        self.assertTrue(report["complete"])
        decode.assert_not_called()

    def test_scan_propagates_missing_image_dependency(self):
        with patch.object(SimilarImageEngine, "_hash_image", side_effect=SimilarImageDependencyError("unavailable")):
            with self.assertRaises(SimilarImageDependencyError):
                SimilarImageEngine.scan_files([("one.jpg", "/private/one.jpg")])

    def test_hash_image_reports_missing_decoder_dependency(self):
        original_import = builtins.__import__

        def without_pillow(name, *args, **kwargs):
            if name == "PIL":
                raise ImportError("Pillow is unavailable")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_pillow):
            with self.assertRaisesRegex(SimilarImageDependencyError, "Image decoding is unavailable"):
                SimilarImageEngine._hash_image("unused.jpg")

    def test_image_source_open_rejects_symlinks_and_non_regular_files(self):
        if not hasattr(os, "symlink"):
            self.skipTest("Symlinks are unavailable on this platform")
        with tempfile.TemporaryDirectory() as directory:
            outside = os.path.join(directory, "outside.jpg")
            link = os.path.join(directory, "linked.jpg")
            with open(outside, "wb") as target:
                target.write(b"not an image")
            os.symlink(outside, link)

            with self.assertRaises(ValueError):
                SimilarImageEngine._open_image_source(link)
            with self.assertRaises(ValueError):
                SimilarImageEngine._open_image_source(directory)

    def test_image_source_open_rejects_empty_or_non_string_paths(self):
        for path in (None, ""):
            with self.subTest(path=path), self.assertRaises(ValueError):
                SimilarImageEngine._open_image_source(path)

    @unittest.skipIf(sys.platform == "win32", "Symlink/inode swap verification is POSIX-specific")
    def test_image_source_open_closes_descriptor_when_opened_file_identity_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            selected = os.path.join(directory, "selected.jpg")
            with open(selected, "wb") as source:
                source.write(b"selected image bytes")
            actual_fstat = os.fstat
            actual_close = os.close
            closed_descriptors = []

            def mismatched_fstat(descriptor):
                details = actual_fstat(descriptor)
                return SimpleNamespace(
                    st_mode=details.st_mode,
                    st_dev=details.st_dev,
                    st_ino=details.st_ino + 1,
                )

            def track_close(descriptor):
                closed_descriptors.append(descriptor)
                actual_close(descriptor)

            with patch("officekit.engines.engine_similar_images.os.fstat", side_effect=mismatched_fstat), patch(
                "officekit.engines.engine_similar_images.os.close", side_effect=track_close
            ):
                with self.assertRaises(ValueError):
                    SimilarImageEngine._open_image_source(selected)

            self.assertEqual(len(closed_descriptors), 1)
            with self.assertRaises(OSError):
                actual_fstat(closed_descriptors[0])

    @unittest.skipIf(sys.platform == "win32", "Symlink/inode swap verification is POSIX-specific")
    def test_image_source_open_detects_a_symlink_swap_during_open(self):
        if not hasattr(os, "symlink"):
            self.skipTest("Symlinks are unavailable on this platform")
        with tempfile.TemporaryDirectory() as directory:
            selected = os.path.join(directory, "selected.jpg")
            outside = os.path.join(directory, "outside.jpg")
            with open(selected, "wb") as source:
                source.write(b"selected image bytes")
            with open(outside, "wb") as target:
                target.write(b"outside image bytes")
            original_open = os.open

            def swap_before_open(path, flags, *args, **kwargs):
                if os.fspath(path) == selected:
                    os.unlink(selected)
                    os.symlink(outside, selected)
                return original_open(path, flags, *args, **kwargs)

            with patch("officekit.engines.engine_similar_images.os.open", side_effect=swap_before_open):
                with self.assertRaises(ValueError):
                    SimilarImageEngine._open_image_source(selected)

    @unittest.skipIf(sys.platform == "win32", "NTFS 1-second stat mtime granularity prevents subsecond in-place change detection")
    def test_image_source_snapshot_detects_same_size_in_place_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            selected = os.path.join(directory, "selected.jpg")
            with open(selected, "wb") as source:
                source.write(b"image-a")
            opened, before = SimilarImageEngine._open_image_source(selected)
            try:
                with open(selected, "wb") as changed:
                    changed.write(b"image-b")
                after = os.fstat(opened.fileno())
                self.assertFalse(SimilarImageEngine._same_file_snapshot(before, after))
            finally:
                opened.close()

    def test_scan_bounds_file_count_before_decoding(self):
        consumed = []

        def too_many():
            for index in range(100_000):
                consumed.append(index)
                yield f"{index}.jpg", f"/private/{index}.jpg"

        with patch.object(SimilarImageEngine, "_hash_image") as decode:
            with self.assertRaises(ValueError):
                SimilarImageEngine.scan_files(too_many())
        self.assertEqual(len(consumed), SimilarImageEngine.MAX_FILES + 1)
        decode.assert_not_called()

    def test_scan_rejects_invalid_threshold_and_malformed_records_before_decoding(self):
        with patch.object(SimilarImageEngine, "_hash_image") as decode:
            with self.assertRaises(ValueError):
                SimilarImageEngine.scan_files([], threshold=True)
            with self.assertRaises(ValueError):
                SimilarImageEngine.scan_files([("only.jpg",)])
        decode.assert_not_called()

    def test_grouping_bounds_lazy_iterables_before_materializing_them(self):
        consumed = []

        def too_many():
            for index in range(100_000):
                consumed.append(index)
                yield f"{index}.jpg", 0

        with self.assertRaises(ValueError):
            SimilarImageEngine.group_hashes(too_many())
        self.assertEqual(len(consumed), SimilarImageEngine.MAX_FILES + 1)

    def test_scan_rejects_absolute_names_and_duplicate_names_before_decoding(self):
        for selection in (
            [("/private/photo.jpg", "/private/photo.jpg")],
            [("photo.jpg", "/private/one.jpg"), ("photo.jpg", "/private/two.jpg")],
        ):
            with self.subTest(selection=selection), patch.object(SimilarImageEngine, "_hash_image") as decode:
                with self.assertRaises(ValueError):
                    SimilarImageEngine.scan_files(selection)
                decode.assert_not_called()

    @unittest.skipIf(Image is None, "Pillow is required for decoded-image integration coverage")
    def test_scanner_matches_a_burst_like_brightness_variant(self):
        with tempfile.TemporaryDirectory() as directory:
            first_path = os.path.join(directory, "burst-a.png")
            second_path = os.path.join(directory, "burst-b.jpg")
            first = Image.new("RGB", (96, 96), (90, 130, 155))
            draw = ImageDraw.Draw(first)
            draw.rectangle((8, 8, 52, 74), fill=(220, 180, 100))
            draw.ellipse((46, 25, 89, 83), fill=(40, 70, 100))
            first.save(first_path)
            ImageEnhance.Brightness(first).enhance(1.035).save(second_path, quality=95)

            report = SimilarImageEngine.scan_files(
                [("burst-a.png", first_path), ("burst-b.jpg", second_path)], threshold=8
            )

        self.assertTrue(report["complete"])
        self.assertEqual(report["scanned_images"], 2)
        self.assertEqual(report["groups"], [{"files": ["burst-a.png", "burst-b.jpg"]}])
        self.assertLessEqual(report["pairs"][0]["distance"], 8)

    @unittest.skipIf(Image is None, "Pillow is required for decoded-image integration coverage")
    def test_real_jpeg_decode_groups_photo_like_burst_variants_without_unrelated_scene(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Image.new("RGB", (640, 420), (91, 142, 180))
            draw = ImageDraw.Draw(base)
            draw.rectangle((0, 265, 639, 419), fill=(94, 112, 73))
            draw.ellipse((430, 45, 505, 120), fill=(248, 211, 116))
            for index, height in enumerate((145, 185, 125, 205, 165)):
                left = 25 + index * 88
                roof = 265 - height
                draw.polygon(((left - 8, roof + 25), (left + 38, roof), (left + 86, roof + 25)), fill=(108 + index * 7, 68, 55))
                draw.rectangle((left, roof + 25, left + 78, 265), fill=(202, 181 - index * 8, 148))
                draw.rectangle((left + 15, roof + 48, left + 32, roof + 72), fill=(54, 94, 111))
                draw.rectangle((left + 48, roof + 48, left + 64, roof + 72), fill=(54, 94, 111))
            for x, y in ((115, 280), (295, 300), (540, 286)):
                draw.ellipse((x - 38, y - 82, x + 38, y - 6), fill=(46, 83, 48))
                draw.rectangle((x - 5, y - 8, x + 5, y + 56), fill=(88, 64, 46))

            unrelated = Image.new("RGB", (640, 420), (34, 31, 60))
            unrelated_draw = ImageDraw.Draw(unrelated)
            unrelated_draw.rectangle((0, 220, 639, 419), fill=(36, 130, 145))
            for x in range(30, 640, 70):
                unrelated_draw.ellipse((x, 75, x + 44, 119), fill=(220, 75, 120))
                unrelated_draw.line((x + 22, 119, x + 22, 220), fill=(194, 194, 206), width=8)

            paths = {
                "burst-base.jpg": os.path.join(directory, "burst-base.jpg"),
                "burst-exposure.jpg": os.path.join(directory, "burst-exposure.jpg"),
                "burst-crop.jpg": os.path.join(directory, "burst-crop.jpg"),
                "burst-rotation.jpg": os.path.join(directory, "burst-rotation.jpg"),
                "unrelated-scene.jpg": os.path.join(directory, "unrelated-scene.jpg"),
            }
            base.save(paths["burst-base.jpg"], quality=94)
            ImageEnhance.Brightness(base).enhance(1.12).save(paths["burst-exposure.jpg"], quality=82)
            cropped = base.crop((12, 8, 628, 412)).resize(base.size, Image.Resampling.LANCZOS)
            cropped.save(paths["burst-crop.jpg"], quality=86)
            base.rotate(2.5, resample=Image.Resampling.BICUBIC, fillcolor=(91, 142, 180)).save(
                paths["burst-rotation.jpg"], quality=88
            )
            unrelated.save(paths["unrelated-scene.jpg"], quality=90)

            report = SimilarImageEngine.scan_files(
                list((name, path) for name, path in paths.items()), threshold=8
            )

        self.assertTrue(report["complete"], report)
        self.assertEqual(report["scanned_images"], 5)
        burst_group = next(group for group in report["groups"] if "burst-base.jpg" in group["files"])
        self.assertEqual(
            burst_group["files"],
            ["burst-base.jpg", "burst-crop.jpg", "burst-exposure.jpg", "burst-rotation.jpg"],
        )
        self.assertNotIn("unrelated-scene.jpg", burst_group["files"])

    @unittest.skipIf(Image is None, "Pillow is required for decoded-image integration coverage")
    def test_cc0_photographs_group_realistic_variants_without_cross_scene_matches(self):
        fixture_root = Path(__file__).parent / "fixtures" / "similar-images" / "cc0"
        sources = {
            "dog-portrait": fixture_root / "dog-portrait.jpg",
            "dog-on-road": fixture_root / "dog-on-road.jpg",
            "dandelion": fixture_root / "dandelion.jpg",
            "landscape": fixture_root / "landscape.jpg",
        }
        self.assertTrue(all(path.is_file() for path in sources.values()))

        with tempfile.TemporaryDirectory() as directory:
            selections = []
            expected_groups = []
            for scene_name, source_path in sources.items():
                with Image.open(source_path) as source:
                    self.assertLessEqual(max(source.size), 512)
                    self.assertEqual(source.getexif(), {})
                    base = source.convert("RGB")

                names = {
                    "base": f"{scene_name}-base.jpg",
                    "exposure": f"{scene_name}-exposure.jpg",
                    "center-zoom": f"{scene_name}-center-zoom.jpg",
                    "off-center-zoom": f"{scene_name}-off-center-zoom.jpg",
                    "shift": f"{scene_name}-shift.jpg",
                    "rotation": f"{scene_name}-rotation.jpg",
                    "compression": f"{scene_name}-compression.jpg",
                }
                paths = {key: os.path.join(directory, name) for key, name in names.items()}
                base.save(paths["base"], quality=94)
                ImageEnhance.Brightness(base).enhance(1.20).save(paths["exposure"], quality=72)

                crop_box = (
                    round(base.width * 0.10), round(base.height * 0.10),
                    round(base.width * 0.90), round(base.height * 0.90),
                )
                base.crop(crop_box).resize(base.size, Image.Resampling.LANCZOS).save(
                    paths["center-zoom"], quality=82
                )
                off_center_box = (
                    round(base.width * 0.10), round(base.height * 0.02),
                    round(base.width * 0.95), round(base.height * 0.98),
                )
                base.crop(off_center_box).resize(base.size, Image.Resampling.LANCZOS).save(
                    paths["off-center-zoom"], quality=78
                )
                shifted = base.transform(
                    base.size,
                    Image.Transform.AFFINE,
                    (1, 0, 7, 0, 1, -5),
                    resample=Image.Resampling.BICUBIC,
                    fillcolor=(255, 255, 255),
                )
                shifted.save(paths["shift"], quality=76)
                base.rotate(5, resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255)).save(
                    paths["rotation"], quality=78
                )
                base.save(paths["compression"], quality=35)
                selections.extend((names[key], paths[key]) for key in names)
                expected_groups.append(sorted(names.values()))

            report = SimilarImageEngine.scan_files(selections, threshold=8)

        self.assertTrue(report["complete"], report)
        self.assertEqual(report["scanned_images"], 28)
        self.assertEqual(report["groups"], [{"files": group} for group in sorted(expected_groups)], report)

    @unittest.skipIf(Image is None, "Pillow is required for decoded-image integration coverage")
    def test_seeded_photo_burst_corpus_keeps_each_scene_separate(self):
        """Check recall and false-positive behavior across many varied photo-like scenes."""
        with tempfile.TemporaryDirectory() as directory:
            selections = []
            expected_groups = []
            for seed in range(12):
                rng = random.Random(8_400 + seed)
                sky = (48 + seed * 7 % 90, 108 + seed * 11 % 70, 155 + seed * 13 % 80)
                scene = Image.new("RGB", (320, 240), sky)
                draw = ImageDraw.Draw(scene)
                horizon = 132 + rng.randrange(-18, 19)
                ground = (54 + seed * 9 % 95, 83 + seed * 5 % 80, 48 + seed * 3 % 45)
                draw.rectangle((0, horizon, 319, 239), fill=ground)

                for ridge in range(3):
                    ridge_y = horizon - 25 - ridge * 17
                    points = [(0, horizon)]
                    points.extend(
                        (x, ridge_y + rng.randrange(-13, 14))
                        for x in range(0, 321, 32)
                    )
                    points.append((319, horizon))
                    shade = tuple(max(0, min(255, channel - ridge * 13)) for channel in sky)
                    draw.polygon(points, fill=shade)

                for _ in range(7):
                    x = rng.randrange(8, 312)
                    y = rng.randrange(horizon + 7, 226)
                    size = rng.randrange(7, 20)
                    leaf = (rng.randrange(25, 95), rng.randrange(70, 155), rng.randrange(25, 85))
                    draw.ellipse((x - size, y - size * 2, x + size, y), fill=leaf)
                    draw.rectangle((x - 2, y - 3, x + 2, min(239, y + size)), fill=(75, 58, 42))

                for _ in range(5):
                    x = rng.randrange(0, 320)
                    y = rng.randrange(0, horizon)
                    radius = rng.randrange(2, 7)
                    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(244, 234, 203))

                base_name = f"scene-{seed:02}-base.jpg"
                bright_name = f"scene-{seed:02}-bright.jpg"
                shifted_name = f"scene-{seed:02}-shift.jpg"
                base_path = os.path.join(directory, base_name)
                bright_path = os.path.join(directory, bright_name)
                shifted_path = os.path.join(directory, shifted_name)
                scene.save(base_path, quality=94)

                bright = ImageEnhance.Brightness(scene).enhance(rng.uniform(0.92, 1.12))
                bright = bright.crop((3, 2, 317, 238)).resize(scene.size, Image.Resampling.LANCZOS)
                bright.save(bright_path, quality=78)

                shifted = scene.transform(
                    scene.size,
                    Image.Transform.AFFINE,
                    (1, 0, rng.choice((-3, -2, 2, 3)), 0, 1, rng.choice((-2, -1, 1, 2))),
                    resample=Image.Resampling.BICUBIC,
                    fillcolor=sky,
                )
                shifted.save(shifted_path, quality=82)
                selections.extend(((base_name, base_path), (bright_name, bright_path), (shifted_name, shifted_path)))
                expected_groups.append(sorted((base_name, bright_name, shifted_name)))

            report = SimilarImageEngine.scan_files(selections, threshold=8)

        self.assertTrue(report["complete"], report)
        self.assertEqual(report["scanned_images"], 36)
        self.assertEqual(report["groups"], [{"files": group} for group in sorted(expected_groups)])

    @unittest.skipUnless(platform.system() == "Darwin" and shutil.which("sips"), "macOS sips is required for HEIC integration coverage")
    def test_macos_scanner_groups_heic_and_heif_duplicates_without_matching_unrelated_scene(self):
        with tempfile.TemporaryDirectory() as directory:
            fixtures = Path(__file__).resolve().parent / "fixtures" / "similar-images" / "cc0" / "heic"
            heic_path = os.path.join(directory, "first.heic")
            heif_path = os.path.join(directory, "second.heif")
            unrelated_path = os.path.join(directory, "unrelated.heic")
            shutil.copyfile(fixtures / "still-medium.heic", heic_path)
            shutil.copyfile(fixtures / "still-medium.heic", heif_path)
            shutil.copyfile(fixtures / "still-high-quality.heic", unrelated_path)

            report = SimilarImageEngine.scan_files([
                ("first.heic", heic_path),
                ("second.heif", heif_path),
                ("unrelated.heic", unrelated_path),
            ])

        self.assertTrue(report["complete"], report)
        self.assertEqual(report["scanned_images"], 3)
        self.assertEqual(report["skipped_files"], [])
        self.assertEqual(report["groups"], [{"files": ["first.heic", "second.heif"]}])

    @unittest.skipUnless(platform.system() == "Darwin" and shutil.which("sips"), "macOS sips is required for HEIC integration coverage")
    def test_macos_heic_scanning_reserves_original_pixels_before_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            heic = os.path.join(directory, "photo.heic")
            fixture = Path(__file__).resolve().parent / "fixtures" / "similar-images" / "cc0" / "heic" / "still-medium.heic"
            shutil.copyfile(fixture, heic)

            with patch.object(SimilarImageEngine, "MAX_TOTAL_PIXELS", 100):
                report = SimilarImageEngine.scan_files([("photo.heic", heic)])

        self.assertEqual(report["scanned_images"], 0)
        self.assertEqual(report["errors"], [{
            "name": "photo.heic",
            "message": "Aggregate image scan work limit reached; select fewer or smaller images",
        }])

    @unittest.skipUnless(platform.system() == "Darwin", "macOS HEIC decoder contract")
    def test_macos_heic_size_cap_is_checked_before_starting_sips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "large.heic")
            with open(path, "wb") as image:
                image.write(b"oversized")
            with patch.object(SimilarImageEngine, "MAX_HEIC_BYTES", 4), patch(
                "officekit.engines.engine_similar_images.subprocess.run"
            ) as run:
                with self.assertRaisesRegex(ValueError, "file-size limit"):
                    SimilarImageEngine._macos_heic_copy(path)

        run.assert_not_called()

    @unittest.skipUnless(platform.system() == "Darwin", "macOS HEIC decoder contract")
    def test_macos_heic_decoder_failure_is_sanitized_and_cleans_temporary_copy(self):
        real_temporary_directory = tempfile.TemporaryDirectory
        created = []

        def tracked_temporary_directory(*args, **kwargs):
            temporary = real_temporary_directory(*args, **kwargs)
            created.append(temporary.name)
            return temporary

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "selected.heic")
            with open(path, "wb") as image:
                image.write(b"not a real HEIC")
            failure = SimpleNamespace(returncode=1, stdout=b"", stderr=b"/private/customer/path.heic")
            with patch("officekit.engines.engine_similar_images.tempfile.TemporaryDirectory", side_effect=tracked_temporary_directory), patch(
                "officekit.engines.engine_similar_images.subprocess.run", return_value=failure
            ):
                with self.assertRaisesRegex(ValueError, "could not be decoded") as raised:
                    SimilarImageEngine._macos_heic_copy(path)

        self.assertNotIn("/private/customer", str(raised.exception))
        self.assertEqual(len(created), 1)
        self.assertFalse(os.path.exists(created[0]))

    @unittest.skipUnless(platform.system() == "Darwin", "macOS HEIC decoder contract")
    def test_macos_heic_decoder_timeout_is_bounded_and_cleans_temporary_copy(self):
        real_temporary_directory = tempfile.TemporaryDirectory
        created = []

        def tracked_temporary_directory(*args, **kwargs):
            temporary = real_temporary_directory(*args, **kwargs)
            created.append(temporary.name)
            return temporary

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "selected.heic")
            with open(path, "wb") as image:
                image.write(b"test fixture")
            with patch("officekit.engines.engine_similar_images.tempfile.TemporaryDirectory", side_effect=tracked_temporary_directory), patch(
                "officekit.engines.engine_similar_images.subprocess.run", side_effect=subprocess.TimeoutExpired("sips", 20)
            ) as run:
                with self.assertRaisesRegex(ValueError, "time limit"):
                    SimilarImageEngine._macos_heic_copy(path)

        self.assertEqual(run.call_args.kwargs["timeout"], SimilarImageEngine.HEIC_DECODE_TIMEOUT_SECONDS)
        self.assertEqual(len(created), 1)
        self.assertFalse(os.path.exists(created[0]))

    @unittest.skipIf(Image is None, "Pillow is required for decoded-image integration coverage")
    def test_scanner_handles_transparent_pngs_without_false_background_differences(self):
        with tempfile.TemporaryDirectory() as directory:
            transparent_path = os.path.join(directory, "transparent.png")
            flattened_path = os.path.join(directory, "flattened.png")
            transparent = Image.new("RGBA", (80, 60), (0, 0, 0, 0))
            draw = ImageDraw.Draw(transparent)
            draw.rectangle((8, 8, 42, 52), fill=(30, 130, 90, 190))
            background = Image.new("RGBA", transparent.size, "white")
            Image.alpha_composite(background, transparent).convert("RGB").save(flattened_path)
            transparent.save(transparent_path)

            report = SimilarImageEngine.scan_files([
                ("transparent.png", transparent_path),
                ("flattened.png", flattened_path),
            ])

        self.assertTrue(report["complete"], report)
        self.assertEqual(report["groups"], [{"files": ["flattened.png", "transparent.png"]}])

    @unittest.skipIf(Image is None, "Pillow is required for decoded-image integration coverage")
    def test_hash_image_rejects_images_over_the_pixel_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            oversized_path = os.path.join(directory, "oversized.png")
            Image.new("RGB", (2, 2), "white").save(oversized_path)

            with patch.object(SimilarImageEngine, "MAX_PIXELS", 3):
                with self.assertRaisesRegex(ValueError, "dimensions exceed"):
                    SimilarImageEngine._hash_image(oversized_path)

    @unittest.skipIf(Image is None, "Pillow is required for decoded-image integration coverage")
    def test_scanner_enforces_aggregate_pixel_work_and_can_still_scan_later_small_images(self):
        with tempfile.TemporaryDirectory() as directory:
            large_paths = []
            for name, size in (("first.png", (32, 32)), ("over-budget.png", (32, 32)), ("small.png", (16, 16))):
                path = os.path.join(directory, name)
                Image.new("RGB", size, "white").save(path)
                large_paths.append((name, path))

            with patch.object(SimilarImageEngine, "MAX_TOTAL_PIXELS", 1_300):
                report = SimilarImageEngine.scan_files(large_paths)

        self.assertEqual(report["scanned_images"], 2)
        self.assertEqual(
            report["errors"],
            [{"name": "over-budget.png", "message": "Aggregate image scan work limit reached; select fewer or smaller images"}],
        )
        self.assertFalse(report["complete"])

    @unittest.skipIf(Image is None, "Pillow is required for decoded-image integration coverage")
    def test_hash_image_fails_if_file_snapshot_changes_after_decode(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = os.path.join(directory, "stable.png")
            Image.new("RGB", (24, 24), "white").save(image_path)

            with patch.object(SimilarImageEngine, "_same_file_snapshot", return_value=False):
                with self.assertRaisesRegex(ValueError, "changed while"):
                    SimilarImageEngine._hash_image(image_path)

    @unittest.skipIf(Image is None, "Pillow is required for decoded-image integration coverage")
    def test_scanner_recalls_zoomed_burst_frames_with_half_frame_center_crop(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Image.new("RGB", (640, 420), (91, 142, 180))
            draw = ImageDraw.Draw(base)
            draw.rectangle((0, 265, 639, 419), fill=(94, 112, 73))
            draw.ellipse((430, 45, 505, 120), fill=(248, 211, 116))
            for index, height in enumerate((145, 185, 125, 205, 165)):
                left = 25 + index * 88
                roof = 265 - height
                draw.polygon(((left - 8, roof + 25), (left + 38, roof), (left + 86, roof + 25)), fill=(108 + index * 7, 68, 55))
                draw.rectangle((left, roof + 25, left + 78, 265), fill=(202, 181 - index * 8, 148))
                draw.rectangle((left + 15, roof + 48, left + 32, roof + 72), fill=(54, 94, 111))
                draw.rectangle((left + 48, roof + 48, left + 64, roof + 72), fill=(54, 94, 111))
            for x, y in ((115, 280), (295, 300), (540, 286)):
                draw.ellipse((x - 38, y - 82, x + 38, y - 6), fill=(46, 83, 48))
                draw.rectangle((x - 5, y - 8, x + 5, y + 56), fill=(88, 64, 46))

            paths = {
                "wide.jpg": os.path.join(directory, "wide.jpg"),
                "zoom-half.jpg": os.path.join(directory, "zoom-half.jpg"),
                "zoom-two-thirds.jpg": os.path.join(directory, "zoom-two-thirds.jpg"),
            }
            base.save(paths["wide.jpg"], quality=92)
            half = base.crop((160, 105, 480, 315)).resize(base.size, Image.Resampling.LANCZOS)
            ImageEnhance.Brightness(half).enhance(1.07).save(paths["zoom-half.jpg"], quality=76)
            two_thirds = base.crop((107, 70, 533, 350)).resize(base.size, Image.Resampling.LANCZOS)
            two_thirds.save(paths["zoom-two-thirds.jpg"], quality=82)

            report = SimilarImageEngine.scan_files(
                [(name, path) for name, path in paths.items()], threshold=8
            )

        self.assertTrue(report["complete"], report)
        self.assertEqual(report["scanned_images"], 3)
        self.assertEqual(report["groups"], [{"files": sorted(paths)}], report)

    @unittest.skipIf(Image is None, "Pillow is required for decoded-image integration coverage")
    def test_scanner_normalizes_exif_orientation_before_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            camera_path = os.path.join(directory, "camera-orientation.jpg")
            normalized_path = os.path.join(directory, "normalized.jpg")
            image = Image.new("RGB", (120, 80), (32, 85, 124))
            draw = ImageDraw.Draw(image)
            draw.rectangle((5, 8, 37, 57), fill=(235, 181, 71))
            draw.ellipse((72, 11, 112, 54), fill=(170, 48, 71))
            orientation = Image.Exif()
            orientation[274] = 6
            image.save(camera_path, quality=96, exif=orientation)
            image.transpose(Image.Transpose.ROTATE_270).save(normalized_path, quality=96)

            report = SimilarImageEngine.scan_files(
                [
                    ("camera-orientation.jpg", camera_path),
                    ("normalized.jpg", normalized_path),
                ],
                threshold=8,
            )

        self.assertTrue(report["complete"], report)
        self.assertEqual(report["groups"], [{"files": ["camera-orientation.jpg", "normalized.jpg"]}])

    @unittest.skipIf(Image is None, "Pillow is required for decoded-image integration coverage")
    def test_scanner_marks_corrupt_jpeg_incomplete_without_returning_local_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            corrupt_path = os.path.join(directory, "customer-private-photo.jpg")
            with open(corrupt_path, "wb") as corrupt:
                corrupt.write(b"\xff\xd8\xff\xe0not-a-complete-jpeg")

            report = SimilarImageEngine.scan_files(
                [("customer-private-photo.jpg", corrupt_path)], threshold=8
            )

        self.assertFalse(report["complete"])
        self.assertEqual(report["errors"], [
            {"name": "customer-private-photo.jpg", "message": "Image could not be decoded"}
        ])
        self.assertNotIn(directory, str(report))
        self.assertEqual(report["groups"], [])

    @unittest.skipIf(Image is None, "Pillow is required for decoded-image integration coverage")
    def test_scanner_contains_png_decoder_syntax_errors_as_safe_per_file_failures(self):
        malformed_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
        )
        with tempfile.TemporaryDirectory() as directory:
            malformed_path = os.path.join(directory, "malformed-private.png")
            with open(malformed_path, "wb") as output:
                output.write(malformed_png)

            report = SimilarImageEngine.scan_files(
                [("malformed-private.png", malformed_path)], threshold=8
            )

        self.assertFalse(report["complete"])
        self.assertEqual(report["errors"], [
            {"name": "malformed-private.png", "message": "Image could not be decoded"}
        ])
        self.assertNotIn(directory, str(report))


if __name__ == "__main__":
    unittest.main()
