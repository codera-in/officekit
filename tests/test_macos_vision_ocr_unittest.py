"""Resource bounds, protocol validation, and process behavior for macOS Vision OCR."""

import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image, ImageDraw, ImageFont
from fastapi.testclient import TestClient

from app import app
import officekit.engines.engine_rapidocr as engine_rapidocr
from officekit.engines.engine_macos_ocr import (
    MAX_IMAGE_BYTES,
    MAX_IMAGE_PIXELS,
    MAX_OCR_TEXT_BYTES,
    VisionOcrError,
    VisionOcrUnavailable,
    find_vision_helper,
    image_to_png_bytes,
    is_available,
    parse_vision_output,
    recognize_image,
)
from officekit.engines.engine_ocr import parse_ocr_text_rows
from officekit.engines.engine_parser import parse_statement_table


def vision_output(items):
    return json.dumps(items, ensure_ascii=False).encode("utf-8")


def text_box(text, x, y, width=0.08, height=0.02, confidence=0.99):
    return {
        "text": text,
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "confidence": confidence,
    }


import sys
@unittest.skipUnless(sys.platform == "darwin", "macOS Vision OCR is only supported on macOS")
class MacVisionOcrTests(unittest.TestCase):
    def test_helper_lookup_is_macos_only_and_prefers_bundled_sibling(self):
        with tempfile.TemporaryDirectory() as root:
            executable = Path(root) / "officekit-backend"
            helper = Path(root) / "officekit-vision-ocr"
            executable.write_bytes(b"backend")
            helper.write_bytes(b"helper")
            helper.chmod(0o700)

            self.assertEqual(
                find_vision_helper("darwin", str(executable), "/missing/officekit/engines/engine_macos_ocr.py"),
                helper,
            )
            self.assertIsNone(
                find_vision_helper("linux", str(executable), "/missing/officekit/engines/engine_macos_ocr.py")
            )

    def test_helper_lookup_finds_development_build_and_rejects_non_executable_files(self):
        with tempfile.TemporaryDirectory() as root:
            module = Path(root) / "officekit/engines/engine_macos_ocr.py"
            development_helper = Path(root) / ".build/backend-sidecar/dist/officekit-backend/officekit-vision-ocr"
            development_helper.parent.mkdir(parents=True)
            development_helper.write_bytes(b"helper")
            development_helper.chmod(0o700)

            self.assertEqual(
                find_vision_helper("darwin", "/missing/officekit-backend", str(module)),
                development_helper.resolve(),
            )
            development_helper.chmod(0o600)
            self.assertIsNone(
                find_vision_helper("darwin", "/missing/officekit-backend", str(module))
            )

    def test_image_encoder_enforces_type_dimensions_pixels_and_encoded_size(self):
        image = Image.new("RGB", (2, 3), "white")
        encoded = image_to_png_bytes(image, max_image_pixels=6)
        self.assertTrue(encoded.startswith(b"\x89PNG\r\n\x1a\n"))
        with self.assertRaises(VisionOcrError):
            image_to_png_bytes(object())
        with self.assertRaises(VisionOcrError):
            image_to_png_bytes(image, max_image_pixels=5)
        with self.assertRaises(VisionOcrError):
            image_to_png_bytes(image, max_image_pixels=0)
        with self.assertRaises(VisionOcrError):
            image_to_png_bytes(image, max_image_pixels=True)

        oversized = Image.new("RGB", (1, 1), "white")
        oversized.save = Mock(side_effect=lambda buffer, **kwargs: buffer.write(b"x" * 9))
        with self.assertRaises(VisionOcrError):
            image_to_png_bytes(oversized, max_image_bytes=8)

        broken_image = Image.new("RGB", (1, 1), "white")
        broken_image.save = Mock(side_effect=OSError("private encoder detail"))
        with self.assertRaises(VisionOcrError):
            image_to_png_bytes(broken_image)

    def test_vision_output_groups_columns_and_orders_rows_without_echoing_invalid_data(self):
        output = parse_vision_output(vision_output([
            text_box("Coffee Shop", 0.10, 0.20, 0.20),
            text_box("4.50", 0.72, 0.20, 0.06),
            text_box("2026-08-02", 0.10, 0.25, 0.12),
        ]))
        self.assertEqual(output.splitlines(), ["2026-08-02", "Coffee Shop   4.50"])

        words = parse_vision_output(vision_output([
            text_box("2026-08-02", 0.05, 0.20, 0.15, height=0.12),
            text_box("COFFEE", 0.24, 0.20, 0.09, height=0.12),
            text_box("SHOP", 0.345, 0.20, 0.06, height=0.12),
            text_box("4.50", 0.72, 0.20, 0.06, height=0.12),
        ]))
        self.assertEqual(parse_ocr_text_rows(words), [["2026-08-02", "COFFEE SHOP", "4.50"]])

    def test_vision_header_alignment_preserves_empty_financial_columns(self):
        aligned = parse_vision_output(vision_output([
            text_box("DATE", 0.05, 0.30, 0.06),
            text_box("DESCRIPTION", 0.20, 0.30, 0.16),
            text_box("DEBIT", 0.50, 0.30, 0.08),
            text_box("CREDIT", 0.66, 0.30, 0.09),
            text_box("BALANCE", 0.84, 0.30, 0.10),
            text_box("2026-08-02", 0.05, 0.20, 0.12),
            text_box("COFFEE SHOP", 0.20, 0.20, 0.13),
            text_box("25.00", 0.50, 0.20, 0.06),
            text_box("975.00", 0.84, 0.20, 0.08),
        ]))

        rows = parse_ocr_text_rows(aligned)

        self.assertEqual(rows[0], ["DATE", "DESCRIPTION", "DEBIT", "CREDIT", "BALANCE"])
        self.assertEqual(rows[1], ["2026-08-02", "COFFEE SHOP", "25.00", "", "975.00"])

        with self.assertRaises(VisionOcrError):
            parse_vision_output(b"not json")
        with self.assertRaises(VisionOcrError):
            parse_vision_output(vision_output([text_box("private", -0.1, 0.5)]))
        with self.assertRaises(VisionOcrError):
            parse_vision_output(vision_output([text_box("private", 0.1, 0.5, confidence=2)]))
        with self.assertRaises(VisionOcrError):
            parse_vision_output(vision_output([{"text": 1}]))
        with self.assertRaises(VisionOcrError):
            parse_vision_output(vision_output({"text": "not a list"}))
        with self.assertRaises(VisionOcrError):
            parse_vision_output(vision_output([text_box(" ", 0.1, 0.5)]))
        with self.assertRaises(VisionOcrError):
            parse_vision_output(vision_output([text_box("x" * 4097, 0.1, 0.5)]))
        with self.assertRaises(VisionOcrError):
            parse_vision_output(vision_output([text_box("x", 0.1, 0.5, width=True)]))
        with self.assertRaises(VisionOcrError):
            parse_vision_output(vision_output([text_box("x", 0.1, 0.5, width=float("inf"))]))
        with self.assertRaises(VisionOcrError):
            parse_vision_output(vision_output([text_box("x", 0.1, 0.5)] * 10), max_observations=9)
        with patch("officekit.engines.engine_macos_ocr.MAX_OCR_TEXT_BYTES", 2):
            with self.assertRaises(VisionOcrError):
                parse_vision_output(vision_output([text_box("abc", 0.1, 0.5)]))
        with patch("officekit.engines.engine_macos_ocr.MAX_OCR_OBSERVATIONS", 1):
            with self.assertRaises(VisionOcrError):
                parse_vision_output(vision_output([text_box("a", 0.1, 0.5)] * 2))
        self.assertEqual(parse_vision_output(b"[]"), "")
        with self.assertRaises(VisionOcrError):
            parse_vision_output("[]")
        with self.assertRaises(VisionOcrError):
            parse_vision_output(b"[]", max_observations=-1)
        with self.assertRaises(VisionOcrError):
            parse_vision_output(b" " * (MAX_OCR_TEXT_BYTES + 1))

    def test_vision_runner_receives_only_bounded_png_on_stdin_and_returns_text(self):
        image = Image.new("RGB", (2, 2), "white")
        result = SimpleNamespace(returncode=0, stdout=vision_output([text_box("Shop", 0.1, 0.2)]))
        runner = Mock(return_value=result)

        text = recognize_image(image, helper_path="/app/officekit-vision-ocr", runner=runner)

        self.assertEqual(text, "Shop")
        runner.assert_called_once()
        command, kwargs = runner.call_args.args[0], runner.call_args.kwargs
        self.assertEqual(command, ["/app/officekit-vision-ocr"])
        self.assertTrue(kwargs["input"].startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 60)
        self.assertTrue(kwargs["close_fds"])
        self.assertTrue(kwargs["capture_output"])
        self.assertFalse(kwargs["check"])

    def test_missing_helper_timeout_process_failure_and_bad_output_are_distinct_safe_errors(self):
        image = Image.new("RGB", (1, 1), "white")
        with self.assertRaises(VisionOcrUnavailable):
            recognize_image(image, helper_path=None, helper_lookup=lambda: None)

        for error in (
            subprocess.TimeoutExpired("vision", 60),
            FileNotFoundError("private path"),
        ):
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(VisionOcrUnavailable):
                    recognize_image(
                        image,
                        helper_path="/app/officekit-vision-ocr",
                        runner=Mock(side_effect=error),
                    )

        with self.assertRaises(VisionOcrUnavailable):
            recognize_image(
                image,
                helper_path="/app/officekit-vision-ocr",
                runner=Mock(return_value=SimpleNamespace(returncode=69, stdout=b"")),
            )

        for result in (
            SimpleNamespace(returncode=1, stdout=b"private engine error"),
            SimpleNamespace(returncode=0, stdout=b"\xff"),
            SimpleNamespace(returncode=0, stdout=b"x" * (MAX_OCR_TEXT_BYTES + 1)),
        ):
            with self.subTest(result=result):
                with self.assertRaises(VisionOcrError) as raised:
                    recognize_image(
                        image,
                        helper_path="/app/officekit-vision-ocr",
                        runner=Mock(return_value=result),
                    )
                self.assertNotIn("private", str(raised.exception))

    def test_availability_tracks_helper_lookup(self):
        with patch("officekit.engines.engine_macos_ocr.find_vision_helper", return_value=Path("/tmp/helper")):
            self.assertTrue(is_available())
        with patch("officekit.engines.engine_macos_ocr.find_vision_helper", return_value=None):
            self.assertFalse(is_available())

    @unittest.skipUnless(
        find_vision_helper() is not None and not engine_rapidocr.is_available(),
        "Vision OCR is a fallback; this build exercises the bundled RapidOCR provider instead.",
    )
    def test_bundled_vision_helper_recognizes_financial_statement_text_offline(self):
        image = Image.new("RGB", (1500, 300), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=52)
        draw.text((40, 35), "DATE        DESCRIPTION        AMOUNT", fill="black", font=font)
        draw.text((40, 125), "2026-08-02  COFFEE SHOP         4.50", fill="black", font=font)
        draw.text((40, 215), "2026-08-03  UTILITY BILL       24.95", fill="black", font=font)

        text = recognize_image(image)

        self.assertIn("2026-08-02", text)
        self.assertIn("COFFEE SHOP", text)
        self.assertIn("4.50", text)
        self.assertIn("2026-08-03", text)
        self.assertIn("24.95", text)
        rows = parse_ocr_text_rows(text)
        self.assertIn(["2026-08-02", "COFFEE SHOP", "4.50"], rows, repr(text))
        parsed = parse_statement_table(rows)
        self.assertEqual(parsed["transactions"][0]["description"], "COFFEE SHOP")
        self.assertEqual(parsed["transactions"][0]["credit"], 4.5)

        image_file = io.BytesIO()
        image.save(image_file, format="PNG")
        app_helper = (
            Path(__file__).resolve().parents[1]
            / "src-tauri/target/release/bundle/macos/OfficeKit.app/Contents/Resources/resources/officekit-backend/officekit-vision-ocr"
        )
        selected_helper = app_helper if app_helper.is_file() else find_vision_helper()
        with patch("officekit.engines.engine_macos_ocr.is_available", return_value=True), patch(
            "officekit.engines.engine_macos_ocr.recognize_image",
            side_effect=lambda source: recognize_image(source, helper_path=selected_helper),
        ):
            response = TestClient(app).post(
                "/api/extract/statement",
                files={"file": ("statement.png", image_file.getvalue(), "image/png")},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["transactions"][0]["description"], "COFFEE SHOP")
        self.assertEqual(response.json()["transactions"][0]["credit"], 4.5)


if __name__ == "__main__":
    unittest.main()
