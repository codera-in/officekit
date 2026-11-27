"""OCR failures must remain distinguishable from an empty but valid result."""

import importlib.util
import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_parser(image_open, recognize):
    image_module = types.ModuleType("PIL.Image")
    image_module.open = image_open
    pil = types.ModuleType("PIL")
    pil.Image = image_module
    tesseract = types.ModuleType("pytesseract")
    tesseract.image_to_string = recognize
    vision = types.ModuleType("engine_macos_ocr")
    vision.is_available = Mock(return_value=False)
    vision.recognize_image = Mock()
    rapidocr = types.ModuleType("engine_rapidocr")
    rapidocr.is_available = Mock(return_value=False)
    rapidocr.recognize_image = Mock()
    modules = {
        "PIL": pil,
        "PIL.Image": image_module,
        "pytesseract": tesseract,
        "engine_macos_ocr": vision,
        "engine_rapidocr": rapidocr,
    }

    with patch.object(sys, "dont_write_bytecode", True), patch.dict(sys.modules, modules):
        name = "officekit_parser_ocr_test"
        spec = importlib.util.spec_from_file_location(name, ROOT / "officekit/engines/engine_parser.py")
        parser = importlib.util.module_from_spec(spec)
        sys.modules[name] = parser
        try:
            spec.loader.exec_module(parser)
        finally:
            sys.modules.pop(name, None)
    parser.pytesseract = tesseract
    parser.engine_macos_ocr = vision
    parser.engine_rapidocr = rapidocr
    return parser


class OcrHandlingTests(unittest.TestCase):
    def test_macos_uses_vision_when_packaged_rapidocr_is_unavailable(self):
        image = object()
        parser = load_parser(lambda _stream: image, Mock(return_value="wrong provider"))
        parser.engine_macos_ocr.is_available.return_value = True
        parser.engine_macos_ocr.recognize_image.return_value = "2026-08-01   Coffee Shop   4.50"

        with patch.object(parser.sys, "platform", "darwin"):
            rows = parser.extract_text_from_image(b"image")

        self.assertEqual(rows, [["2026-08-01", "Coffee Shop", "4.50"]])
        parser.engine_macos_ocr.is_available.assert_called_once_with()
        parser.engine_macos_ocr.recognize_image.assert_called_once_with(image)

    def test_bundled_rapidocr_is_preferred_over_platform_specific_engines(self):
        image = object()
        parser = load_parser(lambda _stream: image, Mock(return_value="wrong provider"))
        parser.engine_rapidocr.is_available.return_value = True
        parser.engine_rapidocr.recognize_image.return_value = "2026-08-01\tCoffee Shop\t4.50"

        with patch.object(parser.sys, "platform", "darwin"):
            rows = parser.extract_text_from_image(b"image")

        self.assertEqual(rows, [["2026-08-01", "Coffee Shop", "4.50"]])
        parser.engine_rapidocr.recognize_image.assert_called_once_with(image)
        parser.engine_macos_ocr.is_available.assert_not_called()

    def test_recognition_failure_is_not_returned_as_no_extractable_rows(self):
        recognize = Mock(side_effect=RuntimeError("Tesseract executable failed"))
        parser = load_parser(lambda _stream: object(), recognize)

        with self.assertRaises(Exception) as raised:
            parser.extract_text_from_image(b"image")

        self.assertEqual(type(raised.exception).__name__, "ImageTextRecognitionError")
        self.assertEqual(raised.exception.status_code, 422)
        self.assertEqual(
            str(raised.exception),
            "Could not read this image. Try a clearer image or a text PDF.",
        )

    def test_missing_ocr_engine_has_a_distinct_actionable_error(self):
        parser = load_parser(lambda _stream: object(), Mock())
        parser.pytesseract = None

        with patch.dict(sys.modules, {"pytesseract": None}), self.assertRaises(Exception) as raised:
            parser.extract_text_from_image(b"image")

        self.assertEqual(type(raised.exception).__name__, "ImageTextRecognitionUnavailable")
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(
            str(raised.exception),
            "Image text recognition is unavailable on this computer.",
        )

    def test_missing_tesseract_binary_is_distinguished_from_bad_image_data(self):
        class TesseractNotFoundError(RuntimeError):
            pass

        parser = load_parser(lambda _stream: object(), Mock(side_effect=TesseractNotFoundError()))
        parser.pytesseract.TesseractNotFoundError = TesseractNotFoundError

        with self.assertRaises(Exception) as raised:
            parser.extract_text_from_image(b"image")

        self.assertEqual(type(raised.exception).__name__, "ImageTextRecognitionUnavailable")
        self.assertEqual(raised.exception.status_code, 503)

    def test_invalid_image_data_is_reported_as_an_image_processing_error(self):
        parser = load_parser(Mock(side_effect=ValueError("decoder detail")), Mock())

        with self.assertRaises(Exception) as raised:
            parser.extract_text_from_image(b"not an image")

        self.assertEqual(type(raised.exception).__name__, "ImageTextRecognitionError")
        self.assertEqual(raised.exception.status_code, 422)
        self.assertNotIn("decoder detail", str(raised.exception))

    def test_successful_empty_recognition_remains_an_empty_result(self):
        parser = load_parser(lambda _stream: object(), Mock(return_value=" \n "))
        self.assertEqual(parser.extract_text_from_image(b"image"), [])

    def test_multi_column_ocr_lines_keep_the_existing_row_split_behavior(self):
        parser = load_parser(
            lambda _stream: object(),
            Mock(return_value="2026-08-01   Coffee Shop   4.50\nnoise"),
        )
        self.assertEqual(
            parser.extract_text_from_image(b"image"),
            [["2026-08-01", "Coffee Shop", "4.50"]],
        )

    def test_statement_endpoint_maps_only_controlled_ocr_errors(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        route = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "extract_statement"
        )
        catches = [node for node in ast.walk(route) if isinstance(node, ast.ExceptHandler)]
        handler = next(
            node for node in catches
            if isinstance(node.type, ast.Tuple)
            and {name.id for name in node.type.elts if isinstance(name, ast.Name)}
            == {"ImageTextRecognitionUnavailable", "ImageTextRecognitionError"}
        )
        mapped = ast.unparse(handler)
        self.assertIn("status_code=error.status_code", mapped)
        self.assertIn("detail=str(error)", mapped)
        self.assertNotIn("traceback", mapped)


if __name__ == "__main__":
    unittest.main()
