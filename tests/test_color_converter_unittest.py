"""Independent reference vectors and validation for local color conversion."""

import unittest

from officekit.engines.engine_colors import ColorConverterEngine


class ColorConverterTests(unittest.TestCase):
    def test_hex_rgb_hsl_hsv_reference_vectors(self):
        self.assertEqual(ColorConverterEngine.convert("#f00", "hex", "rgb"), "rgb(255, 0, 0)")
        self.assertEqual(ColorConverterEngine.convert("rgb(0, 255, 0)", "rgb", "hex"), "#00ff00")
        self.assertEqual(ColorConverterEngine.convert("hsl(240, 100%, 50%)", "hsl", "hex"), "#0000ff")
        self.assertEqual(ColorConverterEngine.convert("hsv(60, 100%, 100%)", "hsv", "rgb"), "rgb(255, 255, 0)")

    def test_alpha_is_preserved_between_hex_rgb_and_hsl(self):
        self.assertEqual(ColorConverterEngine.convert("#33669980", "hex", "rgb"), "rgba(51, 102, 153, 0.502)")
        self.assertEqual(ColorConverterEngine.convert("rgba(255, 0, 0, 0.5)", "rgb", "hex"), "#ff000080")
        self.assertEqual(ColorConverterEngine.convert("hsla(0, 100%, 50%, 0.25)", "hsl", "hex"), "#ff000040")

    def test_hue_wraps_and_achromatic_colors_are_supported(self):
        self.assertEqual(ColorConverterEngine.convert("hsl(480, 100%, 50%)", "hsl", "hex"), "#00ff00")
        self.assertEqual(ColorConverterEngine.convert("#808080", "hex", "hsl"), "hsl(0, 0%, 50.2%)")

    def test_rejects_invalid_formats_syntax_and_ranges(self):
        cases = (
            ("named red", "hex", "rgb"),
            ("#12", "hex", "rgb"),
            ("rgb(256, 0, 0)", "rgb", "hex"),
            ("rgb(1.5, 0, 0)", "rgb", "hex"),
            ("rgba(0, 0, 0, 1.1)", "rgb", "hex"),
            ("hsl(0, 101%, 50%)", "hsl", "hex"),
            ("hsv(0, 50%, -1%)", "hsv", "hex"),
            ("#ffffff", "cmyk", "rgb"),
            ("#ffffff", "hex", "cmyk"),
        )
        for value, source, target in cases:
            with self.subTest(value=value, source=source, target=target), self.assertRaises(ValueError):
                ColorConverterEngine.convert(value, source, target)

    def test_rejects_non_string_and_oversized_inputs(self):
        for value in (None, 12, "#" + "f" * 129):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ColorConverterEngine.convert(value, "hex", "rgb")

    def test_rejects_non_string_formats(self):
        for source, target in ((None, "rgb"), ([], "hex"), ("hex", {})):
            with self.subTest(source=source, target=target), self.assertRaises(ValueError):
                ColorConverterEngine.convert("#ffffff", source, target)

    def test_output_formatting_is_stable(self):
        self.assertEqual(ColorConverterEngine.convert("rgb(0, 1, 2)", "rgb", "hsv"), "hsv(210, 100%, 0.78%)")
        self.assertEqual(ColorConverterEngine.convert("#ffffff", "hex", "hex"), "#ffffff")


if __name__ == "__main__":
    unittest.main()
