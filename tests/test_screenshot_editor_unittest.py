"""Bounded screenshot-edit engine tests; pixel integration skips without Pillow."""

import io
import json
import unittest
from unittest.mock import patch

from officekit.engines.engine_screenshot_editor import BoundedPngBuffer, ScreenshotEditError, ScreenshotEditorEngine, ScreenshotOutputLimitError

try:
    from PIL import Image, ImageDraw
    from PIL.PngImagePlugin import PngInfo
except ImportError:
    Image = None
    ImageDraw = None
    PngInfo = None


class ScreenshotEditorValidationTests(unittest.TestCase):
    def test_new_annotation_operations_validate_fields_points_and_ordered_dimensions(self):
        line = {"type": "line", "x": 1, "y": 1, "width": 20, "height": 19,
                "points": [[2, 2], [18, 18]], "color": "#ff0000"}
        rounded = {"type": "rounded_rectangle", "x": 1, "y": 1, "width": 20, "height": 19,
                   "color": "#ff0000", "stroke_width": 3, "outer_width": 2}
        stamp = {"type": "stamp", "stamp": "check", "x": 0, "y": 0, "width": 30, "height": 20,
                 "points": [[20, 10], [4, 4]]}
        operations = [line, rounded, stamp, {"type": "rotate"},
                      {"type": "pixelate", "x": 1, "y": 1, "width": 19, "height": 29, "block_size": 8}]
        normalized = ScreenshotEditorEngine.validate_operations(operations, (30, 20))
        self.assertEqual(normalized[0]["color"], "#FF0000")
        self.assertEqual(normalized[2]["stamp"], "check")
        self.assertEqual(normalized[4]["block_size"], 8)

        for operation, image_size in (
            ({**line, "points": [[2, 2], [2, 2]]}, (30, 20)),
            ({**stamp, "stamp": "smile"}, (30, 20)),
            ({**stamp, "points": [[20, 20]]}, (30, 20)),
            ({"type": "rotate", "degrees": 180}, (30, 20)),
            ({"type": "pixelate", "x": 1, "y": 1, "width": 5, "height": 5, "block_size": 1}, (30, 20)),
            ({"type": "pixelate", "x": 1, "y": 1, "width": 5, "height": 5, "block_size": 65}, (30, 20)),
        ):
            with self.subTest(operation=operation), self.assertRaises(ScreenshotEditError):
                ScreenshotEditorEngine.validate_operations([operation], image_size)

        with self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.validate_operations([
                {"type": "rotate"}, {"type": "pixelate", "x": 0, "y": 0, "width": 21, "height": 30},
            ], (30, 20))

    def test_rotate_and_pixelate_count_toward_cumulative_image_work(self):
        with self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.validate_operations([
                {"type": "rotate"},
                {"type": "pixelate", "x": 0, "y": 0, "width": 8000, "height": 5000, "block_size": 8},
            ], (8000, 5000))

    @unittest.skipIf(Image is None, "Pillow is unavailable")
    def test_new_shape_and_directional_stamp_exports_draw_expected_pixels(self):
        source = io.BytesIO()
        Image.new("RGB", (120, 90), "white").save(source, format="PNG")
        operations = [
            {"type": "rounded_rectangle", "x": 5, "y": 5, "width": 36, "height": 32,
             "color": "#FF0000", "stroke_width": 2, "outer_width": 1, "outer_color": "#0000FF"},
            {"type": "line", "x": 10, "y": 56, "width": 40, "height": 8,
             "points": [[12, 60], [48, 60]], "color": "#00AA00"},
            {"type": "stamp", "stamp": "check", "x": 48, "y": 8, "width": 54, "height": 44,
             "points": [[88, 32], [54, 12]]},
        ]
        output, dimensions = ScreenshotEditorEngine.edit_image(source.getvalue(), operations)
        with Image.open(io.BytesIO(output)) as edited:
            self.assertEqual(dimensions, (120, 90))
            self.assertEqual(edited.getpixel((5, 5)), (255, 255, 255))
            self.assertIn((0, 0, 255), {color for _, color in edited.getcolors(120 * 90)})
            self.assertIn((255, 0, 0), {color for _, color in edited.getcolors(120 * 90)})
            self.assertIn((0, 170, 0), {color for _, color in edited.getcolors(120 * 90)})
            self.assertEqual(edited.getpixel((119, 89)), (255, 255, 255))

    @unittest.skipIf(Image is None, "Pillow is unavailable")
    def test_every_directional_stamp_variant_renders_and_rejects_non_string_names(self):
        source = io.BytesIO()
        Image.new("RGB", (300, 70), "white").save(source, format="PNG")
        names = ("check", "question", "x", "alert", "heart")
        operations = [
            {"type": "stamp", "stamp": name, "x": index * 60, "y": 10, "width": 60, "height": 50,
             "points": [[index * 60 + 30, 35], [index * 60 + 5, 15]]}
            for index, name in enumerate(names)
        ]
        output, _ = ScreenshotEditorEngine.edit_image(source.getvalue(), operations)
        with Image.open(io.BytesIO(output)) as edited:
            colors = {color for _, color in edited.getcolors(300 * 70)}
            self.assertTrue({(31, 166, 91), (45, 115, 221), (218, 48, 57), (238, 108, 44), (226, 67, 125)} <= colors)
        with self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.validate_operations([{
                "type": "stamp", "stamp": [], "x": 0, "y": 0, "width": 30, "height": 30,
                "points": [[20, 20], [5, 5]],
            }], (30, 30))

    @unittest.skipIf(Image is None, "Pillow is unavailable")
    def test_pixelation_reduces_detail_only_inside_its_region(self):
        source = Image.new("RGB", (24, 16))
        for y in range(source.height):
            for x in range(source.width):
                source.putpixel((x, y), (x * 8, y * 12, 100))
        encoded = io.BytesIO()
        source.save(encoded, format="PNG")
        output, _ = ScreenshotEditorEngine.edit_image(encoded.getvalue(), [
            {"type": "pixelate", "x": 0, "y": 0, "width": 16, "height": 16, "block_size": 8},
        ])
        with Image.open(io.BytesIO(output)) as edited:
            self.assertEqual(edited.getpixel((0, 0)), edited.getpixel((7, 7)))
            self.assertEqual(edited.getpixel((8, 0)), edited.getpixel((15, 7)))
            self.assertNotEqual(edited.getpixel((0, 0)), edited.getpixel((8, 0)))
            self.assertEqual(edited.getpixel((20, 10)), source.getpixel((20, 10)))

    @unittest.skipIf(Image is None, "Pillow is unavailable")
    def test_clockwise_rotation_swaps_dimensions_and_remaps_following_edits(self):
        source = Image.new("RGB", (4, 2))
        source.putdata([
            (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
            (255, 0, 255), (0, 255, 255), (255, 128, 0), (80, 80, 80),
        ])
        encoded = io.BytesIO()
        source.save(encoded, format="PNG")
        output, dimensions = ScreenshotEditorEngine.edit_image(encoded.getvalue(), [
            {"type": "rotate"},
            {"type": "mask", "x": 1, "y": 0, "width": 1, "height": 1},
        ])
        with Image.open(io.BytesIO(output)) as edited:
            self.assertEqual(dimensions, (2, 4))
            self.assertEqual(edited.getpixel((1, 0)), (0, 0, 0))
            self.assertEqual(edited.getpixel((0, 0)), (255, 0, 255))
            self.assertEqual(edited.getpixel((1, 3)), (255, 255, 0))
            self.assertEqual(edited.getpixel((0, 3)), (80, 80, 80))

    def test_dual_color_paths_and_fixed_blur(self):
        path = {"type": "arrow", "x": 1, "y": 1, "width": 20, "height": 20,
                "points": [[2, 2], [19, 19]], "color": "#ff0000", "outer_color": "#0000ff",
                "stroke_width": 3, "outer_width": 2}
        validated = ScreenshotEditorEngine.validate_operations([path], (30, 30))[0]
        self.assertEqual(validated["outer_color"], "#0000FF")
        blur = {"type": "blur", "x": 0, "y": 0, "width": 2, "height": 2}
        self.assertEqual(ScreenshotEditorEngine.validate_operations([blur], (30, 30))[0]["radius"], 24)
        for fields in ({"points": [[True, 2], [19, 19]]}, {"points": [[2, 2], [29, 29]]},
                       {"stroke_width": 0}, {"outer_width": 33}, {"outer_color": "red"},
                       {"points": [[2, 2]]}, {"points": [[2, 2]] * 513}, {"points": [[2, float("nan")], [19, 19]]},
                       {"points": [[2, 2], [2, 2]]}):
            with self.subTest(fields=fields), self.assertRaises(ScreenshotEditError):
                ScreenshotEditorEngine.validate_operations([{**path, **fields}], (30, 30))
        freehand = {**path, "type": "freehand", "points": [[2, 2]] * 512}
        with self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.validate_operations([freehand] * 3, (30, 30))
        for size in (True, 7, 97, 24.5):
            with self.subTest(size=size), self.assertRaises(ScreenshotEditError):
                text = {key: value for key, value in path.items() if key != "points"}
                ScreenshotEditorEngine.validate_operations([{**text, "type": "text", "text": "Hi", "font_size": size}], (30, 30))

    @unittest.skipIf(Image is None, "Pillow is unavailable")
    def test_dual_color_annotation_pixels_and_clipping(self):
        source = io.BytesIO()
        Image.new("RGB", (100, 100), "white").save(source, format="PNG")
        base = {"x": 10, "y": 10, "width": 60, "height": 60, "color": "#FF0000",
                "outer_color": "#0000FF", "stroke_width": 3, "outer_width": 2}
        for kind in ("rectangle", "circle", "highlight", "text", "arrow", "freehand"):
            operation = {**base, "type": kind}
            if kind == "text":
                operation.update(text="Hi", font_size=32)
            if kind in ("arrow", "freehand"):
                operation["points"] = [[15, 30], [60, 30]]
            output, _ = ScreenshotEditorEngine.edit_image(source.getvalue(), [operation])
            with Image.open(io.BytesIO(output)) as edited:
                colors = {color for _, color in edited.convert("RGB").getcolors(10000)}
                self.assertIn((0, 0, 255), colors, kind)
                self.assertIn((255, 0, 0), colors, kind) if kind != "highlight" else None
                self.assertEqual(edited.getpixel((99, 99))[:3], (255, 255, 255))

    @unittest.skipIf(Image is None, "Pillow is unavailable")
    def test_annotation_export_draws_pixels_and_preserves_unmarked_regions(self):
        source = io.BytesIO()
        Image.new("RGB", (80, 60), "white").save(source, format="PNG")
        output, size = ScreenshotEditorEngine.edit_image(source.getvalue(), [
            {"type": "rectangle", "x": 5, "y": 5, "width": 20, "height": 20, "color": "#FF0000"},
            {"type": "text", "x": 30, "y": 5, "width": 45, "height": 30, "color": "#000000", "text": "Hi"},
        ])
        image = Image.open(io.BytesIO(output))
        self.assertEqual(size, (80, 60))
        self.assertEqual(image.getpixel((5, 5)), (255, 0, 0))
        self.assertEqual(image.getpixel((15, 15)), (255, 255, 255))
        self.assertEqual(image.getpixel((79, 59)), (255, 255, 255))
        self.assertTrue(any(image.getpixel((x, y)) != (255, 255, 255) for x in range(30, 75) for y in range(5, 35)))

    def test_annotations_are_bounded_and_validated(self):
        rectangle = {"type": "rectangle", "x": 0, "y": 0, "width": 20, "height": 20, "color": "#FF0000"}
        text = {**rectangle, "type": "text", "text": "Review this"}
        self.assertEqual(len(ScreenshotEditorEngine.validate_operations([rectangle, text], (40, 40))), 2)
        self.assertEqual(len(ScreenshotEditorEngine.validate_operations([
            {**rectangle, "type": "circle"}, {**rectangle, "type": "highlight"},
        ], (40, 40))), 2)
        for value in ("", "x" * 201, "bad\ntext", None):
            with self.subTest(value=value), self.assertRaises(ScreenshotEditError):
                ScreenshotEditorEngine.validate_operations([{**text, "text": value}], (40, 40))

    def test_bounded_png_buffer_accepts_exact_limit_and_rejects_write_or_truncate_overflow(self):
        output = BoundedPngBuffer(3)
        self.assertEqual(output.write(b"ab"), 2)
        self.assertEqual(output.write(b"c"), 1)
        self.assertEqual(output.getvalue(), b"abc")
        self.assertEqual(output.truncate(), 3)
        with self.assertRaises(ScreenshotEditError):
            output.write(b"d")
        with self.assertRaises(ScreenshotEditError):
            output.truncate(4)

    def test_error_message_and_operation_parser_reject_non_text_and_invalid_unicode(self):
        self.assertEqual(str(ScreenshotEditError()), ScreenshotEditError.public_message)
        for value in (None, "\ud800"):
            with self.subTest(value=type(value).__name__), self.assertRaises(ScreenshotEditError):
                ScreenshotEditorEngine.parse_operations_json(value)

    def test_validator_rejects_non_object_operations(self):
        with self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.validate_operations(["crop"], (8, 8))

    def test_crop_then_blur_uses_the_current_canvas_and_rejects_out_of_bounds(self):
        operations = [
            {"type": "crop", "x": 10, "y": 5, "width": 20, "height": 20},
            {"type": "blur", "x": 17, "y": 0, "width": 3, "height": 3, "radius": 2},
        ]
        normalized = ScreenshotEditorEngine.validate_operations(operations, (40, 40))
        self.assertEqual(len(normalized), 2)
        with self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.validate_operations(
                operations + [{"type": "mask", "x": 19, "y": 0, "width": 2, "height": 2}],
                (40, 40),
            )

    def test_mask_is_opaque_and_operation_objects_are_strict(self):
        valid = [{"type": "mask", "x": 0, "y": 0, "width": 2, "height": 2, "color": "#123456"}]
        self.assertEqual(ScreenshotEditorEngine.validate_operations(valid, (2, 2)), valid)
        for invalid in (
            [{"type": "mask", "x": 0, "y": 0, "width": 1, "height": 1, "color": "#00000080"}],
            [{"type": "mask", "x": True, "y": 0, "width": 1, "height": 1}],
            [{"type": "crop", "x": 0, "y": 0, "width": 1, "height": 1, "unexpected": True}],
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ScreenshotEditError):
                ScreenshotEditorEngine.validate_operations(invalid, (2, 2))

    def test_blur_radius_and_operation_count_are_bounded(self):
        base = {"type": "blur", "x": 0, "y": 0, "width": 1, "height": 1}
        for radius in (0, 101, True, 1.5):
            with self.subTest(radius=radius), self.assertRaises(ScreenshotEditError):
                ScreenshotEditorEngine.validate_operations([{**base, "radius": radius}], (2, 2))
        too_many = [{"type": "crop", "x": 0, "y": 0, "width": 1, "height": 1}] * 51
        with self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.validate_operations(too_many, (2, 2))

    def test_empty_and_unsupported_operations_are_rejected(self):
        for operations in ([], [{"type": "rotate", "degrees": 90}]):
            with self.subTest(operations=operations), self.assertRaises(ScreenshotEditError):
                ScreenshotEditorEngine.validate_operations(operations, (10, 10))

    def test_operation_json_parser_bounds_input_and_normalizes_deep_nesting(self):
        valid = [{"type": "crop", "x": 0, "y": 0, "width": 1, "height": 1}]
        self.assertEqual(ScreenshotEditorEngine.parse_operations_json(json.dumps(valid)), valid)
        with patch("officekit.engines.engine_screenshot_editor.json.loads", side_effect=UnicodeError), self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.parse_operations_json("[]")
        with self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.parse_operations_json("[" * 5000 + "]" * 5000)
        with patch.object(ScreenshotEditorEngine, "MAX_OPERATION_JSON_BYTES", 2, create=True):
            with self.assertRaises(ScreenshotEditError):
                ScreenshotEditorEngine.parse_operations_json("[] ")
        unicode_payload = '[{"type":"crop","x":0,"y":0,"width":1,"height":1,"note":"é"}]'
        byte_limit = len(unicode_payload.encode("utf-8")) - 1
        with patch.object(ScreenshotEditorEngine, "MAX_OPERATION_JSON_BYTES", byte_limit):
            with self.assertRaises(ScreenshotEditError):
                ScreenshotEditorEngine.parse_operations_json(unicode_payload)

    def test_image_byte_and_pixel_limits_fail_before_decoding(self):
        with patch.object(ScreenshotEditorEngine, "MAX_INPUT_BYTES", 2):
            with self.assertRaises(ScreenshotEditError):
                ScreenshotEditorEngine.edit_image(b"abc", [{"type": "crop", "x": 0, "y": 0, "width": 1, "height": 1}])
        with self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.validate_operations(
                [{"type": "crop", "x": 0, "y": 0, "width": 1, "height": 1}],
                (ScreenshotEditorEngine.MAX_DIMENSION, ScreenshotEditorEngine.MAX_DIMENSION),
            )

    @unittest.skipIf(Image is None, "Pillow is required for image-size boundary coverage")
    def test_editor_rejects_images_over_pixel_limit_before_and_after_orientation(self):
        source = Image.new("RGB", (2, 1), "white")
        payload = io.BytesIO()
        source.save(payload, format="PNG")
        operation = [{"type": "crop", "x": 0, "y": 0, "width": 1, "height": 1}]

        with patch.object(ScreenshotEditorEngine, "MAX_PIXELS", 1), self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.edit_image(payload.getvalue(), operation)

        with patch.object(ScreenshotEditorEngine, "MAX_PIXELS", 2), \
             patch("PIL.ImageOps.exif_transpose", return_value=Image.new("RGB", (2, 2))), \
             self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.edit_image(payload.getvalue(), operation)

    @unittest.skipIf(Image is None, "Pillow is required for image error mapping coverage")
    def test_editor_maps_unreadable_images_and_missing_pillow_to_safe_error(self):
        with self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.edit_image(b"not an image", [{"type": "crop", "x": 0, "y": 0, "width": 1, "height": 1}])

        original_import = __import__

        def fail_pillow_import(name, *args, **kwargs):
            if name == "PIL":
                raise ImportError("Pillow unavailable")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_pillow_import), self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.edit_image(b"valid bytes", [{"type": "crop", "x": 0, "y": 0, "width": 1, "height": 1}])

    @unittest.skipIf(Image is None, "Pillow is required for bounded PNG output coverage")
    def test_png_encoder_stops_writing_at_the_output_limit(self):
        source = Image.new("RGB", (16, 16), "red")
        payload = io.BytesIO()
        source.save(payload, format="PNG")
        observed_buffer_sizes = []
        original_save = Image.Image.save

        def observe_encoder_output(image, output, *args, **kwargs):
            try:
                return original_save(image, output, *args, **kwargs)
            finally:
                observed_buffer_sizes.append(output.tell())

        with patch.object(ScreenshotEditorEngine, "MAX_OUTPUT_BYTES", 32), \
             patch.object(Image.Image, "save", observe_encoder_output), \
             self.assertRaises(ScreenshotEditError):
            ScreenshotEditorEngine.edit_image(
                payload.getvalue(),
                [{"type": "mask", "x": 0, "y": 0, "width": 1, "height": 1}],
            )

        self.assertEqual(len(observed_buffer_sizes), 1)
        self.assertLessEqual(observed_buffer_sizes[-1], 32)

    def test_cumulative_pixel_work_is_bounded_across_valid_regions(self):
        operations = [
            {"type": "mask", "x": 0, "y": 0, "width": 4, "height": 4},
            {"type": "blur", "x": 0, "y": 0, "width": 4, "height": 4, "radius": 2},
        ]
        with patch.object(ScreenshotEditorEngine, "MAX_OPERATION_PIXELS", 24, create=True):
            with self.assertRaises(ScreenshotEditError):
                ScreenshotEditorEngine.validate_operations(operations, (4, 4))

    @unittest.skipIf(Image is None, "Pillow is required for screenshot pixel integration coverage")
    def test_crop_mask_and_blur_export_png_without_embedded_metadata(self):
        source = Image.new("RGBA", (8, 8), (255, 255, 255, 0))
        ImageDraw.Draw(source).rectangle((0, 0, 3, 3), fill="black")
        payload = io.BytesIO()
        metadata = PngInfo()
        metadata.add_text("Comment", "private metadata")
        source.save(payload, format="PNG", pnginfo=metadata)

        output, dimensions = ScreenshotEditorEngine.edit_image(
            payload.getvalue(), [
                {"type": "crop", "x": 0, "y": 0, "width": 6, "height": 6},
                {"type": "mask", "x": 4, "y": 4, "width": 2, "height": 2},
                {"type": "blur", "x": 0, "y": 0, "width": 4, "height": 4, "radius": 2},
            ]
        )
        self.assertEqual(dimensions, (6, 6))
        with Image.open(io.BytesIO(output)) as edited:
            self.assertEqual(edited.format, "PNG")
            self.assertEqual(edited.size, (6, 6))
            self.assertNotIn("Comment", edited.info)
            self.assertEqual(edited.getpixel((5, 5)), (0, 0, 0, 255))

    @unittest.skipIf(Image is None, "Pillow is required for annotation pixel integration coverage")
    def test_highlight_is_translucent_and_circle_marks_only_its_outline(self):
        source = io.BytesIO()
        Image.new("RGB", (40, 40), "white").save(source, format="PNG")
        output, _ = ScreenshotEditorEngine.edit_image(source.getvalue(), [
            {"type": "highlight", "x": 2, "y": 2, "width": 12, "height": 12, "color": "#FF0000"},
            {"type": "circle", "x": 20, "y": 20, "width": 16, "height": 16, "color": "#0000FF"},
        ])
        with Image.open(io.BytesIO(output)) as edited:
            highlighted = edited.getpixel((6, 6))
            self.assertTrue(highlighted[0] > highlighted[1] and 0 < highlighted[1] < 255)
            self.assertEqual(edited.getpixel((28, 28))[:3], (255, 255, 255))
            self.assertEqual(edited.getpixel((20, 28))[:3], (0, 0, 255))

    @unittest.skipIf(Image is None, "Pillow is required for JPEG pixel integration coverage")
    def test_jpeg_output_flattens_transparency_and_strips_metadata(self):
        source = Image.new("RGBA", (8, 8), (255, 0, 0, 0))
        payload = io.BytesIO()
        source.save(payload, format="PNG")
        output, dimensions = ScreenshotEditorEngine.edit_image(
            payload.getvalue(), [{"type": "mask", "x": 0, "y": 0, "width": 2, "height": 2}], "jpeg"
        )
        self.assertEqual(dimensions, (8, 8))
        with Image.open(io.BytesIO(output)) as edited:
            self.assertEqual(edited.format, "JPEG")
            self.assertEqual(edited.mode, "RGB")
            self.assertTrue(all(channel >= 252 for channel in edited.getpixel((7, 7))))
            self.assertFalse(edited.getexif())
            self.assertFalse(set(edited.info) - {"jfif", "jfif_version", "jfif_unit", "jfif_density"})

    @unittest.skipIf(Image is None, "Pillow is required for bounded JPEG output coverage")
    def test_jpeg_encoder_stops_at_output_limit_with_format_specific_error(self):
        source = Image.new("RGB", (16, 16), "red")
        payload = io.BytesIO()
        source.save(payload, format="PNG")
        with patch.object(ScreenshotEditorEngine, "MAX_OUTPUT_BYTES", 32), self.assertRaises(ScreenshotOutputLimitError) as error:
            ScreenshotEditorEngine.edit_image(
                payload.getvalue(), [{"type": "mask", "x": 0, "y": 0, "width": 1, "height": 1}], "jpeg"
            )
        self.assertEqual(error.exception.public_message, "Edited JPEG exceeds the 64 MiB output limit.")

    @unittest.skipIf(Image is None, "Pillow is required for EXIF orientation integration coverage")
    def test_editor_normalizes_exif_orientation_before_crop_coordinates(self):
        source = Image.new("RGB", (8, 4), "white")
        exif = source.getexif()
        exif[274] = 6
        payload = io.BytesIO()
        source.save(payload, format="JPEG", exif=exif, quality=100)

        output, dimensions = ScreenshotEditorEngine.edit_image(
            payload.getvalue(), [{"type": "crop", "x": 0, "y": 0, "width": 4, "height": 8}]
        )

        self.assertEqual(dimensions, (4, 8))
        with Image.open(io.BytesIO(output)) as edited:
            self.assertEqual(edited.size, (4, 8))
            self.assertNotIn("exif", edited.info)


if __name__ == "__main__":
    unittest.main()
