"""Dependency-free contracts for the PDF compression preset policy."""

import unittest

from officekit.engines.engine_pdf_compression_policy import compression_options, compression_ratio


class PdfCompressionPolicyTests(unittest.TestCase):
    def test_named_presets_select_distinct_lossless_levels(self):
        fast = compression_options("fast")
        balanced = compression_options("balanced")
        maximum = compression_options("maximum")

        self.assertEqual(
            [fast["compression_level"], balanced["compression_level"], maximum["compression_level"]],
            [3, 6, 9],
        )
        self.assertTrue(all(option["recompress_flate"] for option in (fast, balanced, maximum)))
        self.assertTrue(all(option["compress_streams"] for option in (fast, balanced, maximum)))
        self.assertEqual({option["object_streams"] for option in (fast, balanced, maximum)}, {"generate"})

    def test_legacy_preset_names_are_explicit_aliases(self):
        self.assertEqual(compression_options("screen"), compression_options("fast"))
        self.assertEqual(compression_options("ebook"), compression_options("balanced"))
        self.assertEqual(compression_options("printer"), compression_options("maximum"))
        self.assertEqual(compression_options("  SCREEN  "), compression_options("fast"))

    def test_unknown_or_malformed_preset_is_rejected(self):
        for value in ("", "lossy", None, 1, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    compression_options(value)

    def test_compression_ratio_reports_expansion_instead_of_clamping(self):
        self.assertEqual(compression_ratio(120, 100), 1.2)

    def test_compression_ratio_rejects_invalid_sizes(self):
        for original, result in (
            (0, 1),
            (-1, 1),
            (1, -1),
            (True, 1),
            (1, False),
            (1.5, 1),
        ):
            with self.subTest(original=original, result=result):
                with self.assertRaises(ValueError):
                    compression_ratio(original, result)


if __name__ == "__main__":
    unittest.main()
