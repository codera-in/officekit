"""Engine tests for the image tools slice (renditions, metadata, palette, data URI, comparison).

Fixtures are generated in memory with Pillow; nothing is read from the network.
"""

import base64
import hashlib
import io
import random
import struct
import unittest
from unittest import mock

from PIL import Image, ImageFile

from officekit.engines import engine_image_tools as tools
from officekit.engines.engine_conversion_errors import ConversionInputError
from officekit.engines.engine_file_converter import FileConverterEngine, ImageOutputLimitError, ImageWorkLimitError
from officekit.engines.engine_image_tools import ImageToolInputError, ImageToolsEngine, RenditionOp


def encode(image, image_format="PNG", **options):
    output = io.BytesIO()
    image.save(output, format=image_format, **options)
    return output.getvalue()


def decode(content):
    with Image.open(io.BytesIO(content)) as image:
        image.load()
        return image.copy()


def corner_fixture():
    """2x2 RGB with distinct corners: TL red, TR green, BL blue, BR white."""
    image = Image.new("RGB", (2, 2))
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((1, 0), (0, 255, 0))
    image.putpixel((0, 1), (0, 0, 255))
    image.putpixel((1, 1), (255, 255, 255))
    return image


def corners(image):
    return tuple(image.convert("RGB").getpixel(point) for point in ((0, 0), (1, 0), (0, 1), (1, 1)))


RED, GREEN, BLUE, WHITE = (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)


def render(content, *operations, output_format="png", **options):
    return ImageToolsEngine.render_rendition(content, list(operations), output_format, **options)


def no_file_writes():
    """Fail the test if any code opens a file for writing (QA-5 write guard)."""
    real_open = open

    def guarded(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"unexpected file write: {file!r}")
        return real_open(file, mode, *args, **kwargs)

    return mock.patch("builtins.open", guarded)


class RotateFlipTests(unittest.TestCase):
    def test_clockwise_turns_produce_exact_pixels(self):
        source = encode(corner_fixture())
        # Clockwise 90: TL<-BL, TR<-TL, BR<-TR, BL<-BR.
        cw90 = decode(render(source, RenditionOp("rotate", degrees_cw=90)).content)
        self.assertEqual(corners(cw90), (BLUE, RED, WHITE, GREEN))
        cw180 = decode(render(source, RenditionOp("rotate", degrees_cw=180)).content)
        self.assertEqual(corners(cw180), (WHITE, BLUE, GREEN, RED))
        cw270 = decode(render(source, RenditionOp("rotate", degrees_cw=270)).content)
        self.assertEqual(corners(cw270), (GREEN, WHITE, RED, BLUE))

    def test_clockwise_mapping_is_pinned_to_pillow_names(self):
        self.assertEqual(tools.CLOCKWISE_TRANSPOSE[90], Image.Transpose.ROTATE_270)
        self.assertEqual(tools.CLOCKWISE_TRANSPOSE[180], Image.Transpose.ROTATE_180)
        self.assertEqual(tools.CLOCKWISE_TRANSPOSE[270], Image.Transpose.ROTATE_90)

    def test_horizontal_and_vertical_flips_produce_exact_pixels(self):
        source = encode(corner_fixture())
        horizontal = decode(render(source, RenditionOp("flip", axis="horizontal")).content)
        self.assertEqual(corners(horizontal), (GREEN, RED, WHITE, BLUE))
        vertical = decode(render(source, RenditionOp("flip", axis="vertical")).content)
        self.assertEqual(corners(vertical), (BLUE, WHITE, RED, GREEN))

    def test_orientation_six_source_is_upright_with_tag_reset(self):
        exif = Image.Exif()
        exif[0x0112] = 6
        source = encode(corner_fixture(), exif=exif.tobytes())
        output = render(source, RenditionOp("adjust"), output_format="png")
        upright = decode(output.content)
        # Orientation 6 displays the stored pixels rotated 90 degrees clockwise.
        self.assertEqual(corners(upright), (BLUE, RED, WHITE, GREEN))
        with Image.open(io.BytesIO(output.content)) as image:
            orientation = image.getexif().get(0x0112)
        self.assertIn(orientation, (None, 1))

    def test_rejects_unknown_turn_and_axis(self):
        source = encode(corner_fixture())
        with self.assertRaises(ImageToolInputError) as rotate:
            render(source, RenditionOp("rotate", degrees_cw=45))
        self.assertEqual(rotate.exception.code, "INVALID_OPERATION")
        with self.assertRaises(ImageToolInputError) as flip:
            render(source, RenditionOp("flip", axis="diagonal"))
        self.assertEqual(flip.exception.code, "INVALID_OPERATION")


class DensityTests(unittest.TestCase):
    def test_png_density_keeps_pixels_and_sets_dpi(self):
        image = Image.new("RGB", (3, 2), (10, 20, 30))
        image.putpixel((2, 1), (200, 100, 50))
        source = encode(image)
        result = render(source, RenditionOp("density", x=300, y=300, unit="inch"))
        self.assertEqual(result.density, (300.0, 300.0, "inch"))
        output = decode(result.content)
        self.assertEqual((output.width, output.height), (3, 2))
        self.assertEqual(list(output.convert("RGB").getdata()), list(image.getdata()))
        with Image.open(io.BytesIO(result.content)) as readback:
            self.assertAlmostEqual(readback.info["dpi"][0], 300, delta=0.5)

    def test_tiff_and_bmp_density_are_lossless(self):
        image = Image.new("RGB", (4, 3), (1, 2, 3))
        image.putpixel((0, 0), (250, 251, 252))
        for image_format, output_format in (("TIFF", "tiff"), ("BMP", "bmp")):
            with self.subTest(format=image_format):
                source = encode(image, image_format)
                result = render(source, RenditionOp("density", x=150, y=150, unit="inch"), output_format="same")
                self.assertEqual(list(decode(result.content).convert("RGB").getdata()), list(image.getdata()))
                self.assertEqual(result.extension, output_format)
                with Image.open(io.BytesIO(result.content)) as readback:
                    self.assertAlmostEqual(readback.info["dpi"][0], 150, delta=0.5)

    def test_jpeg_density_rewrites_only_headers_and_keeps_scan_data(self):
        image = Image.new("RGB", (16, 16), (90, 140, 200))
        source = encode(image, "JPEG", quality=85, subsampling=0)
        result = render(source, RenditionOp("density", x=300, y=300, unit="inch"), output_format="same")
        # Scan data (from SOS marker to the end) is byte-identical.
        self.assertEqual(source[source.index(b"\xff\xda"):], result.content[result.content.index(b"\xff\xda"):])
        self.assertEqual(list(decode(result.content).getdata()), list(decode(source).getdata()))
        with Image.open(io.BytesIO(result.content)) as readback:
            self.assertAlmostEqual(readback.info["dpi"][0], 300, delta=0.5)

    def test_jpeg_density_in_centimetres_stores_dpi(self):
        source = encode(Image.new("RGB", (8, 8), (5, 5, 5)), "JPEG")
        result = render(source, RenditionOp("density", x=118, y=118, unit="cm"), output_format="same")
        self.assertEqual(result.density, (118.0 * 2.54, 118.0 * 2.54, "inch"))
        with Image.open(io.BytesIO(result.content)) as readback:
            self.assertAlmostEqual(readback.info["dpi"][0], 118 * 2.54, delta=0.5)

    def test_density_with_pixel_operation_applies_on_save(self):
        source = encode(corner_fixture())
        result = render(
            source,
            RenditionOp("flip", axis="horizontal"),
            RenditionOp("density", x=72, y=72, unit="inch"),
        )
        self.assertEqual(corners(decode(result.content)), (GREEN, RED, WHITE, BLUE))
        with Image.open(io.BytesIO(result.content)) as readback:
            self.assertAlmostEqual(readback.info["dpi"][0], 72, delta=0.5)

    def test_density_with_pixel_operation_rewrites_kept_exif_resolution(self):
        # CR-2: the PNG/JPEG density tags and the kept EXIF must describe the same resolution.
        exif = Image.Exif()
        exif[0x011A] = 72.0
        exif[0x011B] = 72.0
        exif[0x0128] = 2
        source = encode(corner_fixture(), "JPEG", quality=95, exif=exif.tobytes())
        result = render(
            source,
            RenditionOp("flip", axis="horizontal"),
            RenditionOp("density", x=300, y=300, unit="inch"),
            output_format="jpeg",
        )
        with Image.open(io.BytesIO(result.content)) as readback:
            kept = readback.getexif()
            self.assertAlmostEqual(float(kept[0x011A]), 300.0, delta=0.01)
            self.assertAlmostEqual(float(kept[0x011B]), 300.0, delta=0.01)
            self.assertEqual(kept[0x0128], 2)
            self.assertAlmostEqual(readback.info["dpi"][0], 300, delta=0.5)

    def test_webp_and_gif_outputs_reject_density(self):
        webp = encode(Image.new("RGB", (4, 4), (1, 1, 1)), "WEBP", lossless=True)
        gif = encode(Image.new("P", (4, 4), 0), "GIF")
        for source in (webp, gif):
            with self.subTest(source=source[:6]):
                with self.assertRaises(ImageToolInputError) as raised:
                    render(source, RenditionOp("density", x=300, y=300, unit="inch"), output_format="same")
                self.assertEqual(raised.exception.code, "DENSITY_UNSUPPORTED")

    def test_density_bounds_are_enforced_by_the_engine(self):
        source = encode(corner_fixture())
        for x in (0, 2401):
            with self.subTest(x=x), self.assertRaises(ConversionInputError):
                render(source, RenditionOp("density", x=x, y=300, unit="inch"))
        with self.assertRaises(ConversionInputError):
            render(source, RenditionOp("density", x=300, y=300, unit="mm"))


class GrayscaleTests(unittest.TestCase):
    def test_rgb_primaries_use_itu_601_luma(self):
        image = Image.new("RGB", (3, 1))
        image.putpixel((0, 0), RED)
        image.putpixel((1, 0), GREEN)
        image.putpixel((2, 0), BLUE)
        result = render(encode(image), RenditionOp("grayscale"))
        output = decode(result.content)
        self.assertEqual(output.mode, "L")
        expected = [0.299 * 255, 0.587 * 255, 0.114 * 255]
        for x, exact in enumerate(expected):
            self.assertAlmostEqual(output.getpixel((x, 0)), exact, delta=1)

    def test_transparent_pixels_keep_alpha_in_la_output(self):
        image = Image.new("RGBA", (2, 1), (200, 10, 10, 255))
        image.putpixel((1, 0), (30, 30, 30, 0))
        result = render(encode(image), RenditionOp("grayscale"))
        output = decode(result.content)
        self.assertEqual(output.mode, "LA")
        self.assertEqual(output.getpixel((1, 0))[1], 0)
        self.assertEqual(output.getpixel((0, 0))[1], 255)

    def test_rgb_icc_profile_is_dropped_for_grayscale_output(self):
        fake_profile = b"\x00" * 128
        source = encode(Image.new("RGB", (2, 2), (9, 9, 9)), icc_profile=fake_profile)
        result = render(source, RenditionOp("grayscale"))
        with Image.open(io.BytesIO(result.content)) as readback:
            self.assertNotIn("icc_profile", readback.info)


class AdjustTests(unittest.TestCase):
    def gradient(self):
        image = Image.new("RGB", (16, 16))
        for x in range(16):
            for y in range(16):
                image.putpixel((x, y), (x * 15, y * 15, (x + y) * 8))
        return image

    def test_all_zero_settings_are_byte_identical_pixels(self):
        image = self.gradient()
        result = render(encode(image), RenditionOp("adjust", brightness=0, contrast=0, saturation=0))
        self.assertEqual(list(decode(result.content).convert("RGB").getdata()), list(image.getdata()))

    def test_extreme_brightness_clips_to_black_and_white(self):
        image = Image.new("RGB", (2, 1))
        image.putpixel((0, 0), (200, 200, 200))
        image.putpixel((1, 0), (10, 10, 10))
        bright = decode(render(encode(image), RenditionOp("adjust", brightness=100)).content).convert("RGB")
        self.assertEqual(bright.getpixel((0, 0)), (255, 255, 255))
        dark = decode(render(encode(image), RenditionOp("adjust", brightness=-100)).content).convert("RGB")
        self.assertEqual(dark.getpixel((1, 0)), (0, 0, 0))
        self.assertEqual(dark.getpixel((0, 0)), (0, 0, 0))

    def test_extreme_saturation_removes_colour_and_keeps_grey_stable(self):
        image = Image.new("RGB", (2, 1))
        image.putpixel((0, 0), (200, 100, 50))
        image.putpixel((1, 0), (90, 90, 90))
        result = decode(render(encode(image), RenditionOp("adjust", saturation=-100)).content).convert("RGB")
        red, green, blue = result.getpixel((0, 0))
        self.assertTrue(red == green == blue)
        self.assertEqual(result.getpixel((1, 0)), (90, 90, 90))

    def test_alpha_plane_is_unchanged(self):
        image = Image.new("RGBA", (2, 1), (120, 120, 120, 77))
        image.putpixel((1, 0), (240, 10, 10, 0))
        output = decode(render(encode(image), RenditionOp("adjust", brightness=50, contrast=40, saturation=30)).content)
        self.assertEqual(output.mode, "RGBA")
        self.assertEqual([pixel[3] for pixel in output.getdata()], [77, 0])

    def test_preview_agrees_with_downscaled_export_within_tolerance(self):
        image = Image.new("RGB", (400, 300))
        for x in range(400):
            for y in range(300):
                image.putpixel((x, y), (x * 255 // 399, y * 255 // 299, (x + y) * 255 // 698))
        source = encode(image)
        operations = (RenditionOp("adjust", brightness=30, contrast=20, saturation=-20),)
        export = decode(render(source, *operations).content).convert("RGB")
        preview = decode(render(source, *operations, preview_max_edge=200).content).convert("RGB")
        self.assertEqual(preview.size, (200, 150))
        reduced = export.resize((200, 150), Image.Resampling.LANCZOS)
        total = sum(abs(a - b) for pixel_a, pixel_b in zip(preview.getdata(), reduced.getdata()) for a, b in zip(pixel_a, pixel_b))
        self.assertLessEqual(total / (200 * 150 * 3), 1.5)

    def test_rejects_out_of_range_adjustment(self):
        source = encode(corner_fixture())
        with self.assertRaises(ConversionInputError):
            render(source, RenditionOp("adjust", brightness=101))


class BorderTests(unittest.TestCase):
    def test_output_size_is_content_plus_twice_the_width(self):
        source = encode(Image.new("RGB", (4, 3), (1, 2, 3)))
        result = render(source, RenditionOp("border", width=2, fill="#00FF00", fill_opacity=100))
        self.assertEqual((result.width, result.height), (8, 7))
        self.assertEqual(decode(result.content).size, (8, 7))

    def test_rounded_corners_are_transparent_in_png(self):
        source = encode(Image.new("RGB", (10, 10), (1, 2, 3)))
        result = render(source, RenditionOp("border", width=4, corner_radius=6, fill="#FFFFFF", fill_opacity=100))
        output = decode(result.content).convert("RGBA")
        self.assertEqual(output.getpixel((0, 0))[3], 0)
        self.assertEqual(output.getpixel((output.width // 2, 0))[3], 255)
        self.assertEqual(output.getpixel((output.width // 2, output.height // 2)), (1, 2, 3, 255))

    def test_jpeg_target_flattens_onto_the_fill_colour(self):
        source = encode(Image.new("RGBA", (10, 10), (1, 2, 3, 255)))
        result = render(
            source,
            RenditionOp("border", width=4, corner_radius=6, fill="#0000FF", fill_opacity=100),
            output_format="jpeg",
        )
        self.assertIn("alpha_flattened", result.warnings)
        corner = decode(result.content).convert("RGB").getpixel((0, 0))
        self.assertLess(corner[0], 40)
        self.assertGreater(corner[2], 200)

    def test_border_fill_opacity_sets_border_alpha(self):
        source = encode(Image.new("RGB", (4, 4), (1, 2, 3)))
        result = render(source, RenditionOp("border", width=2, fill="#FF0000", fill_opacity=50))
        border_pixel = decode(result.content).convert("RGBA").getpixel((0, 4))
        self.assertEqual(border_pixel[3], round(50 * 255 / 100))

    def test_width_and_radius_bounds_are_enforced(self):
        source = encode(corner_fixture())
        with self.assertRaises(ConversionInputError):
            render(source, RenditionOp("border", width=2001))
        with self.assertRaises(ConversionInputError):
            render(source, RenditionOp("border", width=1, corner_radius=5001))

    def test_radius_above_half_the_shorter_side_is_rejected(self):
        source = encode(Image.new("RGB", (4, 4), (1, 2, 3)))
        with self.assertRaises(ImageToolInputError) as raised:
            render(source, RenditionOp("border", width=2, corner_radius=20))
        self.assertEqual(raised.exception.code, "CORNER_RADIUS_TOO_LARGE")

    def test_preview_scales_pixel_units_to_match_the_export(self):
        source = encode(Image.new("RGB", (400, 300), (30, 60, 90)))
        operations = (RenditionOp("border", width=10, fill="#FFFFFF", fill_opacity=100),)
        export = decode(render(source, *operations).content).convert("RGB")
        preview = decode(render(source, *operations, preview_max_edge=200).content).convert("RGB")
        self.assertEqual(preview.size, (210, 160))
        reduced = export.resize(preview.size, Image.Resampling.LANCZOS)
        total = sum(abs(a - b) for pixel_a, pixel_b in zip(preview.getdata(), reduced.getdata()) for a, b in zip(pixel_a, pixel_b))
        self.assertLessEqual(total / (210 * 160 * 3), 1.5)


class BatchRenditionTests(unittest.TestCase):
    def test_three_file_batch_returns_zip_with_unique_names(self):
        import zipfile

        files = [
            ("shot.png", encode(Image.new("RGB", (3, 3), (1, 1, 1)))),
            ("shot.png", encode(Image.new("RGB", (3, 3), (2, 2, 2)))),
            ("../other.jpg", encode(Image.new("RGB", (3, 3), (3, 3, 3)), "JPEG")),
        ]
        archive = ImageToolsEngine.render_rendition_batch(
            files, [RenditionOp("border", width=1, fill="#FFFFFF", fill_opacity=100)], "png",
        )
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            self.assertEqual(zipped.namelist(), ["shot_edited.png", "shot_edited (2).png", "other_edited.png"])
            for name in zipped.namelist():
                self.assertEqual(decode(zipped.read(name)).size, (5, 5))


class ShareWorkAndGuardTests(unittest.TestCase):
    def test_frame_pixels_over_limit_are_rejected_before_load(self):
        source = encode(Image.new("RGB", (4, 4)))
        with mock.patch.object(tools, "FRAME_PIXELS", 10), mock.patch.object(
            ImageFile.ImageFile, "load", side_effect=AssertionError("decoded before the limit check"),
        ):
            with self.assertRaises(ImageWorkLimitError):
                render(source, RenditionOp("flip", axis="horizontal"))

    def test_side_over_limit_is_rejected_before_load(self):
        source = encode(Image.new("RGB", (4, 4)))
        with mock.patch.object(tools, "MAX_SIDE", 3), mock.patch.object(
            ImageFile.ImageFile, "load", side_effect=AssertionError("decoded before the limit check"),
        ):
            with self.assertRaises(ImageWorkLimitError):
                render(source, RenditionOp("flip", axis="horizontal"))

    def test_total_pixels_across_frames_are_rejected(self):
        frames = [Image.new("RGB", (4, 4), (60 * index, 0, 0)).convert("P") for index in range(3)]
        output = io.BytesIO()
        frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:])
        with mock.patch.object(tools, "TOTAL_PIXELS", 20):
            with self.assertRaises(ImageWorkLimitError):
                render(output.getvalue(), RenditionOp("flip", axis="horizontal"))

    def test_frame_count_over_limit_is_rejected(self):
        frames = [Image.new("RGB", (2, 2), (60 * index, 0, 0)).convert("P") for index in range(3)]
        output = io.BytesIO()
        frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:])
        with mock.patch.object(tools, "MAX_FRAMES", 2):
            with self.assertRaises(ImageWorkLimitError):
                render(output.getvalue(), RenditionOp("flip", axis="horizontal"))

    def test_output_bytes_over_limit_raise_output_error(self):
        noise = random.Random(7).getrandbits(8 * 64 * 64 * 3).to_bytes(64 * 64 * 3, "little")
        source = encode(Image.frombytes("RGB", (64, 64), noise))
        with mock.patch.object(FileConverterEngine, "MAX_RESIZE_OUTPUT_BYTES", 200):
            with self.assertRaises(ImageOutputLimitError):
                render(source, RenditionOp("flip", axis="horizontal"))

    def test_cumulative_work_budget_is_enforced(self):
        source = encode(Image.new("RGB", (10, 10)))
        with mock.patch.object(tools, "MAX_RENDITION_WORK_PIXELS", 150):
            with self.assertRaises(ImageWorkLimitError):
                render(
                    source,
                    RenditionOp("flip", axis="horizontal"),
                    RenditionOp("flip", axis="vertical"),
                )

    def test_decompression_bomb_maps_to_invalid_image(self):
        source = encode(Image.new("RGB", (20, 20)))
        with mock.patch.object(Image, "MAX_IMAGE_PIXELS", 100):
            with self.assertRaises(ImageToolInputError) as raised:
                render(source, RenditionOp("flip", axis="horizontal"))
        self.assertEqual(raised.exception.code, "INVALID_IMAGE")

    def test_malformed_and_unsupported_inputs_raise_stable_codes(self):
        with self.assertRaises(ImageToolInputError) as malformed:
            render(b"not an image", RenditionOp("flip", axis="horizontal"))
        self.assertEqual(malformed.exception.code, "INVALID_IMAGE")
        ppm = b"P6\n1 1\n255\n\x00\x00\x00"
        with self.assertRaises(ImageToolInputError) as unsupported:
            render(ppm, RenditionOp("flip", axis="horizontal"))
        self.assertEqual(unsupported.exception.code, "UNSUPPORTED_FORMAT")

    def test_rendering_writes_no_file(self):
        # QA-5: bytes are immutable, so the guard is that no file is written while the source is rendered.
        source = encode(corner_fixture())
        with no_file_writes():
            render(source, RenditionOp("flip", axis="horizontal"))


def truncated_jpeg():
    """Valid JPEG header, scan data cut in half: Image.open succeeds, the pixel load fails (CR-7)."""
    noise = Image.frombytes("RGB", (256, 256), bytes(random.Random(7).randrange(256) for _ in range(256 * 256 * 3)))
    full = encode(noise, "JPEG", quality=95)
    return full[: len(full) // 2]


class TruncatedPixelDataTests(unittest.TestCase):
    def test_truncated_pixels_in_a_rendition_are_invalid_image_not_a_crash(self):
        with self.assertRaises(ImageToolInputError) as raised:
            render(truncated_jpeg(), RenditionOp("flip", axis="horizontal"))
        self.assertEqual(raised.exception.code, "INVALID_IMAGE")

    def test_truncated_pixels_in_a_palette_are_invalid_image(self):
        with self.assertRaises(ImageToolInputError) as raised:
            ImageToolsEngine.palette(truncated_jpeg())
        self.assertEqual(raised.exception.code, "INVALID_IMAGE")

    def test_truncated_pixels_in_a_comparison_are_invalid_image(self):
        with self.assertRaises(ImageToolInputError) as raised:
            ImageToolsEngine.compare(truncated_jpeg(), encode(Image.new("RGB", (256, 256))))
        self.assertEqual(raised.exception.code, "INVALID_IMAGE")


class ColourProfileTests(unittest.TestCase):
    def test_converted_cmyk_source_drops_its_cmyk_profile(self):
        # CR-5: RGB pixels converted from CMYK must not carry the CMYK source profile.
        cmyk = Image.new("CMYK", (8, 8), (0, 255, 255, 0))
        source = encode(cmyk, "JPEG", quality=95, icc_profile=b"CMYK-SOURCE-PROFILE")
        with Image.open(io.BytesIO(source)) as probe:
            self.assertEqual(probe.info.get("icc_profile"), b"CMYK-SOURCE-PROFILE")
        result = render(source, RenditionOp("flip", axis="horizontal"), output_format="png")
        with Image.open(io.BytesIO(result.content)) as readback:
            self.assertNotIn("icc_profile", readback.info)
        self.assertIn("color_mode_converted", result.warnings)

    def test_unconverted_rgb_source_keeps_its_profile(self):
        source = encode(Image.new("RGB", (4, 4), (9, 9, 9)), "PNG", icc_profile=b"RGB-PROFILE")
        result = render(source, RenditionOp("flip", axis="horizontal"), output_format="png")
        with Image.open(io.BytesIO(result.content)) as readback:
            self.assertEqual(readback.info.get("icc_profile"), b"RGB-PROFILE")
        self.assertNotIn("color_mode_converted", result.warnings)

    def test_palette_png_keeps_its_profile_because_expansion_keeps_the_colour_space(self):
        palette = Image.new("P", (4, 4), 0)
        source = encode(palette, "PNG", icc_profile=b"P3-PROFILE")
        result = render(source, RenditionOp("flip", axis="horizontal"), output_format="png")
        with Image.open(io.BytesIO(result.content)) as readback:
            self.assertEqual(readback.info.get("icc_profile"), b"P3-PROFILE")
        self.assertNotIn("color_mode_converted", result.warnings)


def known_exif_jpeg():
    """JPEG with a date, camera make and a San Francisco GPS fixture (degrees, minutes, seconds)."""
    exif = Image.Exif()
    exif[0x010F] = "Canon"
    exif[0x0132] = "2024:05:01 12:34:56"
    exif_ifd = exif.get_ifd(0x8769)
    exif_ifd[0x9003] = "2024:05:01 12:34:56"
    exif_ifd[0x829D] = 2.8
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (37.0, 46.0, 29.7)
    gps[3] = "W"
    gps[4] = (122.0, 25.0, 10.2)
    gps[5] = 0
    gps[6] = 16
    return encode(Image.new("RGB", (6, 4), (40, 80, 120)), "JPEG", exif=exif.tobytes())


class MetadataReportTests(unittest.TestCase):
    def entries(self, report):
        return {(entry["group"], entry["tag"]): entry for entry in report["groups"]}

    def test_known_gps_and_date_fixture_reads_back(self):
        report = ImageToolsEngine.metadata_report(known_exif_jpeg())
        entries = self.entries(report)
        self.assertEqual(entries[("date", "DateTimeOriginal")]["value"], "2024:05:01 12:34:56")
        self.assertEqual(entries[("date", "DateTimeOriginal")]["status"], "present")
        self.assertEqual(entries[("camera", "Make")]["value"], "Canon")
        self.assertEqual(entries[("exposure", "FNumber")]["value"], "2.8")
        self.assertEqual((report["format"], report["width"], report["height"], report["frames"]), ("JPEG", 6, 4, 1))

    def test_location_is_withheld_by_default_and_no_coordinate_leaves_the_engine(self):
        content = known_exif_jpeg()
        report = ImageToolsEngine.metadata_report(content)
        self.assertEqual(report["location"], {"present": True, "withheld": True})
        self.assertFalse([entry for entry in report["groups"] if entry["group"] == "location"])
        text = repr(report)
        for coordinate in ("37.77", "122.42", "16.0", "-122"):
            self.assertNotIn(coordinate, text)

    def test_location_is_returned_when_explicitly_requested(self):
        report = ImageToolsEngine.metadata_report(known_exif_jpeg(), include_location=True)
        self.assertTrue(report["location"]["present"])
        self.assertFalse(report["location"]["withheld"])
        self.assertAlmostEqual(report["location"]["latitude"], 37 + 46 / 60 + 29.7 / 3600, places=5)
        self.assertAlmostEqual(report["location"]["longitude"], -(122 + 25 / 60 + 10.2 / 3600), places=5)
        self.assertAlmostEqual(report["location"]["altitude_m"], 16.0, places=3)
        self.assertEqual(self.entries(report)[("location", "GPSLatitude")]["status"], "present")

    def test_unicode_artist_and_utf16_user_comment_decode(self):
        exif = Image.Exif()
        exif[0x013B] = "Zoë Ño".encode("utf-8")
        exif.get_ifd(0x8769)[0x9286] = b"UNICODE\x00" + "写真".encode("utf-16-be")
        content = encode(Image.new("RGB", (2, 2)), "JPEG", exif=exif.tobytes())
        entries = self.entries(ImageToolsEngine.metadata_report(content))
        self.assertEqual(entries[("image", "Artist")]["value"], "Zoë Ño")
        self.assertEqual(entries[("image", "UserComment")]["value"], "写真")

    def test_unknown_user_comment_charset_is_unsupported_not_guessed(self):
        exif = Image.Exif()
        exif.get_ifd(0x8769)[0x9286] = b"XYZ\x00\x00\x00\x00\x00hi"
        content = encode(Image.new("RGB", (2, 2)), "JPEG", exif=exif.tobytes())
        entry = self.entries(ImageToolsEngine.metadata_report(content))[("image", "UserComment")]
        self.assertEqual((entry["status"], entry["value"]), ("unsupported", ""))

    def test_truncated_gps_pointer_is_malformed_and_location_is_not_present(self):
        # Little-endian TIFF with one IFD0 entry: GPSInfo (0x8825, LONG) pointing past the end of the data.
        entry = struct.pack("<HHII", 0x8825, 4, 1, 0x7FFF0000)
        tiff = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", 1) + entry + struct.pack("<I", 0)
        content = encode(Image.new("RGB", (2, 2)), "JPEG", exif=b"Exif\x00\x00" + tiff)
        report = ImageToolsEngine.metadata_report(content, include_location=True)
        self.assertFalse(report["location"]["present"])
        self.assertEqual(self.entries(report)[("location", "GPSLatitude")]["status"], "malformed")

    def test_missing_fields_are_reported_as_missing(self):
        report = ImageToolsEngine.metadata_report(encode(Image.new("RGB", (2, 2)), "PNG"))
        entries = self.entries(report)
        self.assertEqual(entries[("camera", "Make")]["status"], "missing")
        self.assertEqual(entries[("camera", "Make")]["value"], "")
        self.assertEqual(report["location"], {"present": False, "withheld": False})

    def test_long_values_are_truncated_and_control_characters_removed(self):
        exif = Image.Exif()
        exif[0x013B] = ("A\x01" + "b" * 1000).encode("utf-8")
        content = encode(Image.new("RGB", (2, 2)), "JPEG", exif=exif.tobytes())
        value = self.entries(ImageToolsEngine.metadata_report(content))[("image", "Artist")]["value"]
        self.assertEqual(len(value), 512)
        self.assertTrue(value.startswith("Ab"))

    def test_icc_xmp_and_iptc_flags_and_frame_count(self):
        frames = [Image.new("RGB", (3, 3), (60 * index, 0, 0)).convert("P") for index in range(3)]
        output = io.BytesIO()
        frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:])
        report = ImageToolsEngine.metadata_report(output.getvalue())
        self.assertEqual((report["format"], report["frames"]), ("GIF", 3))
        icc_png = encode(Image.new("RGB", (2, 2)), "PNG", icc_profile=b"\x00" * 128)
        self.assertTrue(ImageToolsEngine.metadata_report(icc_png)["has_icc"])
        self.assertFalse(ImageToolsEngine.metadata_report(icc_png)["has_xmp"])

    def test_malformed_exif_bytes_do_not_crash_the_report(self):
        content = encode(Image.new("RGB", (2, 2)), "PNG", exif=b"Exif\x00\x00garbage-not-tiff")
        report = ImageToolsEngine.metadata_report(content)
        self.assertEqual(self.entries(report)[("date", "DateTimeOriginal")]["status"], "missing")

    def test_metadata_is_read_from_the_header_without_the_decode_pixel_budget(self):
        # CR-8: the EXIF viewer decodes no pixels, so a frame over the decode budget still reports.
        content = encode(Image.new("RGB", (4, 4)), "PNG")
        with mock.patch.object(tools, "FRAME_PIXELS", 10):
            report = ImageToolsEngine.metadata_report(content)
        self.assertEqual((report["width"], report["height"]), (4, 4))

    def test_reading_metadata_writes_no_file(self):
        # QA-5: bytes are immutable, so the guard is that no file is written while the source is read.
        content = known_exif_jpeg()
        with no_file_writes():
            ImageToolsEngine.metadata_report(content, include_location=True)

    def test_unsupported_input_is_rejected_with_a_stable_code(self):
        with self.assertRaises(ImageToolInputError) as raised:
            ImageToolsEngine.metadata_report(b"not an image")
        self.assertEqual(raised.exception.code, "INVALID_IMAGE")


class PaletteTests(unittest.TestCase):
    def test_solid_colour_gives_one_swatch_at_full_share(self):
        palette = ImageToolsEngine.palette(encode(Image.new("RGB", (10, 10), (200, 30, 30))))
        self.assertEqual(len(palette["colors"]), 1)
        swatch = palette["colors"][0]
        self.assertEqual((swatch["hex"], swatch["rgb"], swatch["share"], swatch["pixels"]), ("#C81E1E", [200, 30, 30], 1.0, 100))
        self.assertEqual((palette["sampled_pixels"], palette["excluded_transparent_pixels"]), (100, 0))

    def test_two_colour_split_reports_seventy_and_thirty_percent(self):
        image = Image.new("RGB", (10, 10), (0, 0, 255))
        for x in range(7):
            for y in range(10):
                image.putpixel((x, y), (255, 0, 0))
        palette = ImageToolsEngine.palette(encode(image), count=2)
        shares = [(swatch["hex"], swatch["share"], swatch["pixels"]) for swatch in palette["colors"]]
        self.assertEqual(shares, [("#FF0000", 0.7, 70), ("#0000FF", 0.3, 30)])

    def test_transparent_background_is_excluded_from_sampling(self):
        image = Image.new("RGBA", (10, 10), (255, 255, 255, 0))
        for x in range(4):
            for y in range(4):
                image.putpixel((x, y), (0, 200, 0, 255))
        palette = ImageToolsEngine.palette(encode(image))
        self.assertEqual([swatch["hex"] for swatch in palette["colors"]], ["#00C800"])
        self.assertEqual((palette["sampled_pixels"], palette["excluded_transparent_pixels"]), (16, 84))

    def test_alpha_threshold_decides_which_partly_transparent_pixels_count(self):
        image = Image.new("RGBA", (2, 1), (10, 10, 10, 255))
        image.putpixel((1, 0), (250, 250, 250, 100))
        kept_default = ImageToolsEngine.palette(encode(image))
        kept_low = ImageToolsEngine.palette(encode(image), alpha_threshold=50)
        self.assertEqual(kept_default["excluded_transparent_pixels"], 1)
        self.assertEqual(kept_low["excluded_transparent_pixels"], 0)

    def test_repeat_runs_are_identical(self):
        image = Image.new("RGB", (64, 48))
        for x in range(64):
            for y in range(48):
                image.putpixel((x, y), (x * 3, y * 5, (x * y) % 256))
        content = encode(image)
        first = ImageToolsEngine.palette(content, count=5)
        second = ImageToolsEngine.palette(content, count=5)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first["colors"]), 5)
        self.assertAlmostEqual(sum(swatch["share"] for swatch in first["colors"]), 1.0, delta=0.001)

    def test_fully_transparent_image_is_rejected(self):
        with self.assertRaises(ImageToolInputError) as raised:
            ImageToolsEngine.palette(encode(Image.new("RGBA", (4, 4), (0, 0, 0, 0))))
        self.assertEqual(raised.exception.code, "NO_OPAQUE_PIXELS")

    def test_count_and_threshold_bounds_are_enforced(self):
        content = encode(Image.new("RGB", (2, 2)))
        for count in (0, 13):
            with self.subTest(count=count), self.assertRaises(ImageToolInputError) as raised:
                ImageToolsEngine.palette(content, count=count)
            self.assertEqual(raised.exception.code, "INVALID_OPERATION")
        for threshold in (0, 256):
            with self.subTest(threshold=threshold), self.assertRaises(ImageToolInputError) as raised:
                ImageToolsEngine.palette(content, alpha_threshold=threshold)
            self.assertEqual(raised.exception.code, "INVALID_OPERATION")

    def test_animated_input_uses_the_first_frame_only(self):
        frames = [Image.new("RGB", (4, 4), (250, 0, 0)).convert("P"), Image.new("RGB", (4, 4), (0, 0, 250)).convert("P")]
        output = io.BytesIO()
        frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:])
        palette = ImageToolsEngine.palette(output.getvalue())
        self.assertEqual(len(palette["colors"]), 1)
        red, green, blue = palette["colors"][0]["rgb"]
        self.assertGreater(red, 240)
        self.assertEqual((green, blue), (0, 0))

    def test_large_input_is_sampled_at_bounded_size(self):
        palette = ImageToolsEngine.palette(encode(Image.new("RGB", (1200, 900), (9, 9, 9))))
        self.assertEqual(palette["sampled_pixels"], 256 * 192)


SVG_SOURCE = b'<?xml version="1.0"?>\n<!-- icon -->\n<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><rect width="4" height="4"/></svg>\n'


class DataUriTests(unittest.TestCase):
    def test_png_byte_round_trip_preserves_sha256(self):
        content = encode(Image.new("RGB", (5, 3), (9, 8, 7)))
        encoded = ImageToolsEngine.encode_data_uri(content, "image/png")
        self.assertEqual(encoded["mime"], "image/png")
        self.assertEqual(encoded["byte_length"], len(content))
        self.assertEqual(encoded["data_uri_length"], len(encoded["data_uri"]))
        decoded, mime = ImageToolsEngine.decode_data_uri(encoded["data_uri"])
        self.assertEqual(mime, "image/png")
        self.assertEqual(hashlib.sha256(decoded).hexdigest(), hashlib.sha256(content).hexdigest())

    def test_tiff_data_uri_round_trips_through_its_paired_decoder(self):
        # CR-4: the encoder's output must be accepted by decode_data_uri.
        content = encode(Image.new("RGB", (5, 3), (9, 8, 7)), "TIFF")
        encoded = ImageToolsEngine.encode_data_uri(content, "image/tiff")
        self.assertTrue(encoded["data_uri"].startswith("data:image/tiff;base64,"))
        decoded, mime = ImageToolsEngine.decode_data_uri(encoded["data_uri"])
        self.assertEqual(mime, "image/tiff")
        self.assertEqual(decoded, content)

    def test_every_supported_signature_is_sniffed(self):
        samples = {
            "image/png": encode(Image.new("RGB", (2, 2))),
            "image/jpeg": encode(Image.new("RGB", (2, 2)), "JPEG"),
            "image/gif": encode(Image.new("RGB", (2, 2)).convert("P"), "GIF"),
            "image/webp": encode(Image.new("RGB", (2, 2)), "WEBP", lossless=True),
            "image/bmp": encode(Image.new("RGB", (2, 2)), "BMP"),
            "image/tiff": encode(Image.new("RGB", (2, 2)), "TIFF"),
            "image/svg+xml": SVG_SOURCE,
        }
        for mime, content in samples.items():
            with self.subTest(mime=mime):
                self.assertEqual(ImageToolsEngine.sniff_mime(content), mime)

    def test_declared_mime_must_match_the_sniffed_bytes(self):
        jpeg = encode(Image.new("RGB", (2, 2)), "JPEG")
        with self.assertRaises(ImageToolInputError) as raised:
            ImageToolsEngine.encode_data_uri(jpeg, "image/png")
        self.assertEqual((raised.exception.code, raised.exception.status_code), ("MIME_MISMATCH", 422))

    def test_unknown_signature_is_a_mismatch_not_a_guess(self):
        with self.assertRaises(ImageToolInputError) as raised:
            ImageToolsEngine.encode_data_uri(b"<html>not an image</html>", "image/png")
        self.assertEqual(raised.exception.code, "MIME_MISMATCH")

    def test_svg_is_detected_only_with_an_svg_root(self):
        self.assertEqual(ImageToolsEngine.sniff_mime(SVG_SOURCE), "image/svg+xml")
        self.assertEqual(ImageToolsEngine.sniff_mime(b"\xef\xbb\xbf" + SVG_SOURCE), "image/svg+xml")
        self.assertIsNone(ImageToolsEngine.sniff_mime(b"<html><svg></svg></html>"))
        encoded = ImageToolsEngine.encode_data_uri(SVG_SOURCE, "image/svg+xml")
        self.assertTrue(encoded["data_uri"].startswith("data:image/svg+xml;base64,"))

    def test_oversized_binary_is_rejected_before_encoding(self):
        content = b"\x89PNG\r\n\x1a\n" + b"0" * (8 * 1024 * 1024)
        with self.assertRaises(ImageToolInputError) as raised:
            ImageToolsEngine.encode_data_uri(content, "image/png")
        self.assertEqual((raised.exception.code, raised.exception.status_code), ("TOO_LARGE_BINARY", 413))

    def test_bad_base64_and_url_safe_alphabet_are_rejected(self):
        for uri in (
            "data:image/png;base64,@@@@",
            "data:image/png;base64,AAA",
            "data:image/png;base64,AA AA",
            "data:image/png;base64,--__",
        ):
            with self.subTest(uri=uri), self.assertRaises(ImageToolInputError) as raised:
                ImageToolsEngine.decode_data_uri(uri)
            self.assertEqual(raised.exception.code, "INVALID_DATA_URI")

    def test_grammar_rejects_other_media_types_and_missing_base64_marker(self):
        for uri in ("data:text/plain;base64,AAAA", "data:image/png,AAAA", "image/png;base64,AAAA"):
            with self.subTest(uri=uri), self.assertRaises(ImageToolInputError):
                ImageToolsEngine.decode_data_uri(uri)

    def test_decoded_declared_type_must_match_sniffed_bytes(self):
        jpeg = encode(Image.new("RGB", (2, 2)), "JPEG")
        uri = "data:image/png;base64," + base64.b64encode(jpeg).decode("ascii")
        with self.assertRaises(ImageToolInputError) as raised:
            ImageToolsEngine.decode_data_uri(uri)
        self.assertEqual(raised.exception.code, "MIME_MISMATCH")

    def test_oversized_uri_string_and_decoded_payload_are_bounded(self):
        with mock.patch.object(tools, "MAX_DATA_URI_CHARS", 40):
            with self.assertRaises(ImageToolInputError):
                ImageToolsEngine.decode_data_uri("data:image/png;base64," + "A" * 60)
        payload = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        uri = "data:image/png;base64," + base64.b64encode(payload).decode("ascii")
        with mock.patch.object(tools, "MAX_DATA_URI_BINARY_BYTES", 32):
            with self.assertRaises(ImageToolInputError) as raised:
                ImageToolsEngine.decode_data_uri(uri)
        self.assertEqual(raised.exception.status_code, 413)

    def test_svg_decode_returns_bytes_for_attachment_only(self):
        uri = "data:image/svg+xml;base64," + base64.b64encode(SVG_SOURCE).decode("ascii")
        decoded, mime = ImageToolsEngine.decode_data_uri(uri)
        self.assertEqual((decoded, mime), (SVG_SOURCE, "image/svg+xml"))


class CompareTests(unittest.TestCase):
    def grid(self, colour=(10, 20, 30), size=(4, 4)):
        return encode(Image.new("RGB", size, colour))

    def test_hidden_colour_under_transparency_is_not_counted(self):
        # CR-9: two fully transparent pixels that differ only in hidden RGB are the same visible pixel.
        a = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
        b = Image.new("RGBA", (2, 1), (200, 50, 9, 0))
        result = ImageToolsEngine.compare(encode(a), encode(b))
        self.assertEqual((result["changed_pixels"], result["max_channel_delta"]), (0, 0))

    def test_identical_files_report_zero_changed_pixels_without_identity_wording(self):
        content = self.grid()
        result = ImageToolsEngine.compare(content, content)
        self.assertTrue(result["comparable"])
        self.assertEqual(
            (result["compared_pixels"], result["changed_pixels"], result["changed_ratio"]),
            (16, 0, 0.0),
        )
        self.assertEqual((result["max_channel_delta"], result["mean_abs_delta"], result["changed_bbox"]), (0, 0.0, None))
        self.assertNotIn("identical", repr(result).lower())
        self.assertNotIn("same image", repr(result).lower())

    def test_one_changed_pixel_is_found_with_its_bounding_box(self):
        base = Image.new("RGB", (4, 4), (10, 20, 30))
        changed = base.copy()
        changed.putpixel((2, 1), (10, 20, 60))
        result = ImageToolsEngine.compare(encode(base), encode(changed))
        self.assertEqual((result["changed_pixels"], result["max_channel_delta"]), (1, 30))
        self.assertEqual(result["changed_bbox"], [2, 1, 3, 2])
        self.assertAlmostEqual(result["changed_ratio"], 1 / 16, places=6)

    def test_threshold_is_a_strict_per_channel_bound(self):
        base = Image.new("RGB", (2, 2), (10, 10, 10))
        changed = base.copy()
        changed.putpixel((0, 0), (15, 10, 10))
        at_threshold = ImageToolsEngine.compare(encode(base), encode(changed), threshold=5)
        below_threshold = ImageToolsEngine.compare(encode(base), encode(changed), threshold=4)
        self.assertEqual(at_threshold["changed_pixels"], 0)
        self.assertEqual(below_threshold["changed_pixels"], 1)
        self.assertEqual(at_threshold["threshold"], 5)

    def test_mean_absolute_delta_is_over_all_four_channels(self):
        base = Image.new("RGBA", (2, 2), (0, 0, 0, 255))
        changed = base.copy()
        changed.putpixel((0, 0), (10, 0, 0, 255))
        result = ImageToolsEngine.compare(encode(base), encode(changed))
        self.assertEqual(result["mean_abs_delta"], round(10 / 16, 3))

    def test_alpha_differences_count(self):
        base = Image.new("RGBA", (2, 1), (5, 5, 5, 255))
        changed = base.copy()
        changed.putpixel((1, 0), (5, 5, 5, 200))
        result = ImageToolsEngine.compare(encode(base), encode(changed))
        self.assertEqual(result["changed_pixels"], 1)
        self.assertEqual(result["changed_bbox"], [1, 0, 2, 1])

    def test_size_mismatch_is_not_comparable_until_scaling_is_chosen(self):
        result = ImageToolsEngine.compare(self.grid(size=(4, 4)), self.grid(size=(8, 8)))
        self.assertEqual((result["comparable"], result["reason"], result["scaled_b"]), (False, "size_mismatch", False))
        self.assertIsNone(result["changed_pixels"])
        self.assertIsNone(result["difference_png"])
        self.assertEqual((result["a"], result["b"]), ({"w": 4, "h": 4}, {"w": 8, "h": 8}))

        scaled = ImageToolsEngine.compare(
            self.grid(colour=(10, 20, 30), size=(4, 4)), self.grid(colour=(10, 20, 30), size=(8, 8)),
            alignment="scale-b-to-a",
        )
        self.assertTrue(scaled["comparable"])
        self.assertTrue(scaled["scaled_b"])
        self.assertEqual(scaled["changed_pixels"], 0)

    def test_orientation_is_applied_to_both_sides_before_comparison(self):
        exif = Image.Exif()
        exif[0x0112] = 6
        rotated_source = encode(corner_fixture(), exif=exif.tobytes())
        upright = ImageToolsEngine.render_rendition(
            rotated_source, [RenditionOp("adjust")], "png",
        ).content
        result = ImageToolsEngine.compare(rotated_source, upright)
        self.assertEqual(result["changed_pixels"], 0)

    def test_profiles_differ_when_only_one_side_has_a_profile(self):
        with_profile = encode(Image.new("RGB", (2, 2)), icc_profile=b"\x00" * 128)
        without_profile = encode(Image.new("RGB", (2, 2)))
        self.assertTrue(ImageToolsEngine.compare(with_profile, without_profile)["profiles_differ"])
        self.assertFalse(ImageToolsEngine.compare(without_profile, without_profile)["profiles_differ"])

    def test_difference_heatmap_is_a_bounded_png_data_uri(self):
        base = Image.new("RGB", (3000, 40), (10, 20, 30))
        changed = base.copy()
        changed.putpixel((5, 5), (200, 20, 30))
        result = ImageToolsEngine.compare(encode(base), encode(changed))
        self.assertTrue(result["difference_png"].startswith("data:image/png;base64,"))
        png = base64.b64decode(result["difference_png"].split(",", 1)[1])
        with Image.open(io.BytesIO(png)) as heatmap:
            self.assertLessEqual(max(heatmap.size), 2048)

    def test_animated_input_uses_the_first_frame(self):
        frames = [Image.new("RGB", (4, 4), (10, 20, 30)).convert("P"), Image.new("RGB", (4, 4), (250, 0, 0)).convert("P")]
        output = io.BytesIO()
        frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:])
        animated = output.getvalue()
        first_frame_png = ImageToolsEngine.render_rendition(animated, [RenditionOp("adjust")], "png").content
        result = ImageToolsEngine.compare(animated, first_frame_png)
        self.assertEqual(result["changed_pixels"], 0)
        self.assertEqual(result["compared_pixels"], 16)

    def test_bounds_and_inputs_are_validated(self):
        content = self.grid()
        with self.assertRaises(ConversionInputError):
            ImageToolsEngine.compare(content, content, alignment="rotate")
        with self.assertRaises(ConversionInputError):
            ImageToolsEngine.compare(content, content, threshold=256)
        with self.assertRaises(ImageToolInputError) as raised:
            ImageToolsEngine.compare(content, b"junk")
        self.assertEqual(raised.exception.code, "INVALID_IMAGE")

    def test_cumulative_pixel_work_is_budgeted_across_both_images(self):
        content = self.grid(size=(10, 10))
        with mock.patch.object(tools, "MAX_RENDITION_WORK_PIXELS", 150):
            with self.assertRaises(ImageWorkLimitError):
                ImageToolsEngine.compare(content, content)


if __name__ == "__main__":
    unittest.main()
