import random
import time
import unittest
from datetime import datetime
from unittest.mock import patch

from officekit.engines.engine_similar_images import SimilarImageEngine

MASK = (1 << 64) - 1


def flipped(value, bits):
    for bit in bits:
        value ^= 1 << bit
    return value


def noise(count, seed=7):
    generator = random.Random(seed)
    return [(f"noise/{index}.jpg", generator.getrandbits(64)) for index in range(count)]


def groups_of(report):
    return sorted(tuple(group["files"]) for group in report["groups"])


class SimilarImageScaleTest(unittest.TestCase):
    def test_limit_is_ten_thousand_and_rejects_one_more(self):
        self.assertEqual(SimilarImageEngine.MAX_FILES, 10_000)
        consumed = []

        def too_many():
            for index in range(20_000):
                consumed.append(index)
                yield f"{index}.jpg", 0

        with self.assertRaises(ValueError):
            SimilarImageEngine.group_hashes(too_many())
        self.assertEqual(len(consumed), 10_001)

    def test_large_selection_finds_near_duplicates_without_a_full_matrix(self):
        images = noise(2_000)
        base = images[0][1]
        images.append(("copies/original.jpg", base))
        images.append(("copies/resaved.jpg", flipped(base, (3, 40, 61))))
        started = time.monotonic()
        report = SimilarImageEngine.group_hashes(images, 8)
        self.assertLess(time.monotonic() - started, 20)
        self.assertIn(("copies/original.jpg", "copies/resaved.jpg", "noise/0.jpg"), groups_of(report))

    def test_candidate_path_matches_all_pairs_for_close_hashes(self):
        generator = random.Random(3)
        images = []
        for index in range(300):
            base = generator.getrandbits(64)
            images.append((f"a/{index}.jpg", base))
            if index % 3 == 0:
                images.append((f"b/{index}.jpg", flipped(base, generator.sample(range(64), 6))))
        full = SimilarImageEngine.group_hashes(images, 8)
        with patch.object(SimilarImageEngine, "FULL_COMPARE_LIMIT", 0):
            candidate = SimilarImageEngine.group_hashes(images, 8)
        self.assertEqual(groups_of(full), groups_of(candidate))
        self.assertEqual(len(full["groups"]), 100)

    def far_apart_variants(self):
        # Primary hashes differ in every bit; the second fingerprint hash matches.
        first = (0x0123456789ABCDEF, 0xFEDCBA9876543210)
        second = (first[0] ^ MASK, first[1])
        return first, second

    def test_matching_name_stem_makes_far_apart_fingerprints_candidates(self):
        first, second = self.far_apart_variants()
        images = [(f"noise/{name}", (value,)) for name, value in noise(700)]
        images += [("trip/IMG_0042.jpg", first), ("trip/IMG_E0042.jpg", second)]
        images = [(name, value if isinstance(value, tuple) else (value,)) for name, value in images]
        with_names = SimilarImageEngine.group_hashes(images, 8)
        self.assertIn(("trip/IMG_0042.jpg", "trip/IMG_E0042.jpg"), groups_of(with_names))

    def test_close_capture_time_makes_far_apart_fingerprints_candidates(self):
        first, second = self.far_apart_variants()
        images = [(name, (value,)) for name, value in noise(700)]
        images += [("one/alpha.jpg", first), ("two/zulu.jpg", second)]
        self.assertEqual(groups_of(SimilarImageEngine.group_hashes(images, 8)), [])
        moment = datetime(2026, 3, 4, 10, 0, 0).timestamp()
        times = {"one/alpha.jpg": moment, "two/zulu.jpg": moment + 90}
        report = SimilarImageEngine.group_hashes(images, 8, times)
        self.assertIn(("one/alpha.jpg", "two/zulu.jpg"), groups_of(report))
        distant = {"one/alpha.jpg": moment, "two/zulu.jpg": moment + 86_400 * 400}
        self.assertEqual(groups_of(SimilarImageEngine.group_hashes(images, 8, distant)), [])

    def test_check_callback_runs_and_can_cancel(self):
        images = [(name, (value,)) for name, value in noise(700)]
        calls = []

        def stop():
            calls.append(1)
            raise InterruptedError("cancelled")

        with self.assertRaises(InterruptedError):
            SimilarImageEngine.group_hashes(images, 8, None, stop)
        self.assertEqual(len(calls), 1)

    def test_name_stem_removes_copy_edit_and_number_decorations(self):
        stem = SimilarImageEngine._name_stem
        self.assertEqual(stem("Trip/IMG_0042.JPG"), stem("Trip/IMG_E0042.jpg"))
        self.assertEqual(stem("Trip/IMG_0042.jpg"), stem("Trip/IMG_0042 (1).jpg"))
        self.assertEqual(stem("Trip/photo.png"), stem("Trip/photo-copy.png"))
        self.assertNotEqual(stem("Trip/IMG_0042.jpg"), stem("Trip/IMG_0043.jpg"))
        self.assertNotEqual(stem("Trip/IMG_0042.jpg"), stem("Home/IMG_0042.jpg"))

    def test_capture_time_reads_exif_and_ignores_missing_or_bad_values(self):
        from PIL import Image

        image = Image.new("RGB", (4, 4))
        self.assertIsNone(SimilarImageEngine.capture_time(image))
        exif = image.getexif()
        exif[0x0132] = "2026:03:04 10:00:00"
        image.info["exif"] = exif.tobytes()
        self.assertEqual(
            SimilarImageEngine.capture_time(image), datetime(2026, 3, 4, 10, 0, 0).timestamp()
        )
        exif[0x0132] = "not a date"
        self.assertIsNone(SimilarImageEngine.capture_time(image))


if __name__ == "__main__":
    unittest.main()
