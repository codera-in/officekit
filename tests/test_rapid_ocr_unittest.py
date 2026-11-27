"""Offline RapidOCR prototype checks for raster statements."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from officekit.engines.engine_rapidocr import ImageTextRecognitionError, is_available, recognize_image


def _load_font(size: int = 38):
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    )
    for candidate in candidates:
        if Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


class RapidOcrTests(unittest.TestCase):
    def test_english_statement_rows_are_recognized_offline_with_cell_separators(self):
        image = Image.new("RGB", (2200, 720), "white")
        draw = ImageDraw.Draw(image)
        font = _load_font(38)
        columns = {"date": 70, "description": 390, "debit": 1080, "credit": 1450, "balance": 1800}
        for label, x in columns.items():
            draw.text((x, 55), label.upper(), font=font, fill="black")
        for y, values in (
            (230, {"date": "2026-01-02", "description": "Opening balance", "balance": "1000.00"}),
            (405, {"date": "2026-01-03", "description": "Coffee Shop", "debit": "25.00", "balance": "975.00"}),
        ):
            for column, value in values.items():
                draw.text((columns[column], y), value, font=font, fill="black")

        self.assertTrue(is_available())
        recognized = recognize_image(image)

        rows = [line.split("\t") for line in recognized.splitlines()]
        self.assertIn(["DATE", "DESCRIPTION", "DEBIT", "CREDIT", "BALANCE"], rows)
        self.assertIn(["2026-01-03", "Coffee Shop", "25.00", "", "975.00"], rows)

    def test_image_pixel_limit_is_enforced_before_model_execution(self):
        image = Image.new("RGB", (1, 1), "white")
        with patch("officekit.engines.engine_rapidocr.MAX_IMAGE_PIXELS", 0):
            with self.assertRaises(ImageTextRecognitionError):
                recognize_image(image)

    def test_engine_uses_explicit_bundled_model_paths_without_network_resolution(self):
        from officekit.engines.engine_rapidocr import MODEL_FILES, _get_engine

        with TemporaryDirectory() as temporary_directory:
            models = Path(temporary_directory)
            with (
                patch("officekit.engines.engine_rapidocr._engine", None),
                patch("officekit.engines.engine_rapidocr._models_directory", return_value=models),
                patch("rapidocr.RapidOCR") as rapid_ocr,
            ):
                _get_engine()

        params = rapid_ocr.call_args.kwargs["params"]
        self.assertEqual(params["Global.model_root_dir"], str(models))
        self.assertEqual(params["Det.model_path"], str(models / MODEL_FILES[0]))
        self.assertEqual(params["Cls.model_path"], str(models / MODEL_FILES[1]))
        self.assertEqual(params["Rec.model_path"], str(models / MODEL_FILES[2]))

if __name__ == "__main__":
    unittest.main()
