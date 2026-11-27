"""
TDD Tests for Module 4: Universal Any-to-Any Image & Media Converters
- PNG ⇄ JPEG ⇄ WebP ⇄ BMP ⇄ TIFF ⇄ ICO ⇄ PDF
- Batch image resizing with aspect ratio preservation
- Multi-resolution ICO Favicon generation (16x16, 32x32, 48x48)
- Alpha transparency flattening for print
"""

import io
import unittest
from unittest.mock import patch
from PIL import Image
from officekit.engines.engine_file_converter import FileConverterEngine
from officekit.engines.engine_conversion_errors import ConversionInputError

class TestModule4ImageConverterEngine(unittest.TestCase):

    def _create_sample_png(self, size=(200, 200), mode='RGBA') -> bytes:
        img = Image.new(mode, size, color=(255, 0, 0, 128) if mode == 'RGBA' else (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return buf.getvalue()

    def test_image_cross_conversion_formats(self):
        png_data = self._create_sample_png()

        # 1. PNG to WebP
        webp_bytes, mime_webp = FileConverterEngine.convert_image(png_data, 'webp')
        self.assertEqual(mime_webp, 'image/webp')
        self.assertGreater(len(webp_bytes), 0)

        # 2. PNG to JPEG (Must flatten alpha to avoid crash)
        jpeg_bytes, mime_jpeg = FileConverterEngine.convert_image(png_data, 'jpg')
        self.assertEqual(mime_jpeg, 'image/jpeg')
        self.assertGreater(len(jpeg_bytes), 0)

        # 3. PNG to PDF
        pdf_bytes, mime_pdf = FileConverterEngine.convert_image(png_data, 'pdf')
        self.assertEqual(mime_pdf, 'application/pdf')
        self.assertGreater(len(pdf_bytes), 0)

        # 4. PNG to ICO Favicon
        ico_bytes, mime_ico = FileConverterEngine.convert_image(png_data, 'ico')
        self.assertEqual(mime_ico, 'image/x-icon')
        self.assertGreater(len(ico_bytes), 0)

    def test_jpeg_and_bmp_conversion_flatten_rgba_la_and_palette_alpha_onto_white(self):
        sources = []

        rgba = Image.new("RGBA", (72, 24))
        for x in range(72):
            color = ((255, 0, 0, 255), (255, 0, 0, 128), (0, 0, 255, 0))[x // 24]
            for y in range(24):
                rgba.putpixel((x, y), color)
        sources.append((rgba, None, ((255, 0, 0), (255, 127, 127), (255, 255, 255))))

        grayscale_alpha = Image.new("LA", (72, 24))
        for x in range(72):
            pixel = ((0, 255), (128, 128), (255, 0))[x // 24]
            for y in range(24):
                grayscale_alpha.putpixel((x, y), pixel)
        sources.append((grayscale_alpha, None, ((0, 0, 0), (191, 191, 191), (255, 255, 255))))

        palette = Image.new("P", (72, 24))
        palette_colors = [255, 0, 0, 0, 0, 255, 0, 255, 0] + [0] * (768 - 9)
        palette.putpalette(palette_colors)
        for x in range(72):
            for y in range(24):
                palette.putpixel((x, y), x // 24)
        sources.append((palette, bytes((255, 128, 0)), ((255, 0, 0), (127, 127, 255), (255, 255, 255))))

        for source, transparency, expected_samples in sources:
            encoded = io.BytesIO()
            options = {"transparency": transparency} if transparency is not None else {}
            source.save(encoded, format="PNG", **options)
            for target, mime in (("jpg", "image/jpeg"), ("bmp", "image/bmp")):
                converted, actual_mime = FileConverterEngine.convert_image(encoded.getvalue(), target, quality=100)

                self.assertEqual(actual_mime, mime)
                with Image.open(io.BytesIO(converted)) as result:
                    self.assertEqual(result.mode, "RGB")
                    self.assertEqual(result.size, source.size)
                    for index, expected in enumerate(expected_samples):
                        actual = result.getpixel((index * 24 + 12, 12))
                        self.assertTrue(
                            all(abs(channel - target_value) <= 8 for channel, target_value in zip(actual, expected)),
                            f"{source.mode} to {target} segment {index}: expected {expected}, got {actual}",
                        )

            source.close()

    def test_rgba_png_converts_to_bmp_instead_of_failing_on_unsupported_alpha(self):
        source = self._create_sample_png(size=(24, 24), mode="RGBA")

        converted, mime = FileConverterEngine.convert_image(source, "bmp")

        self.assertEqual(mime, "image/bmp")
        with Image.open(io.BytesIO(converted)) as result:
            self.assertEqual(result.format, "BMP")
            self.assertEqual(result.mode, "RGB")
            self.assertEqual(result.size, (24, 24))
            actual = result.getpixel((12, 12))
            self.assertTrue(all(abs(channel - target) <= 4 for channel, target in zip(actual, (255, 127, 127))), actual)

    def test_batch_image_resizing(self):
        png_data = self._create_sample_png(size=(800, 600))
        resized_bytes, (w, h) = FileConverterEngine.resize_image(png_data, max_width=400, max_height=300)
        self.assertEqual(w, 400)
        self.assertEqual(h, 300)

        # Check with aspect ratio preservation
        img = Image.open(io.BytesIO(resized_bytes))
        self.assertEqual(img.size, (400, 300))

    def test_invalid_image_bytes_raise_safe_conversion_input_error(self):
        with self.assertRaises(ConversionInputError) as caught:
            FileConverterEngine.convert_image(b"/Users/private/customer-image", "png")

        self.assertEqual(
            str(caught.exception),
            "The file or requested format cannot be converted. Check the input and try again.",
        )

    def test_image_quality_rejects_non_integer_and_out_of_range_values(self):
        sample = self._create_sample_png(mode="RGB")
        for quality in (0, 101, -1, 90.5, True, "90"):
            with self.subTest(quality=quality):
                with self.assertRaises(ConversionInputError):
                    FileConverterEngine.convert_image(sample, "jpeg", quality)

    def test_convert_image_rejects_non_boolean_metadata_preferences(self):
        sample = self._create_sample_png(mode="RGB")
        with self.assertRaises(ConversionInputError):
            FileConverterEngine.convert_image(sample, "jpeg", preserve_metadata="yes")

    def test_convert_image_applies_jpeg_orientation_before_dropping_exif(self):
        source_image = Image.new("RGB", (20, 10), (0, 0, 0))
        for y in range(10):
            for x in range(10):
                source_image.putpixel((x, y), (240, 20, 20))
            for x in range(10, 20):
                source_image.putpixel((x, y), (20, 20, 240))
        exif = Image.Exif()
        exif[274] = 6
        source = io.BytesIO()
        source_image.save(source, format="JPEG", quality=92, exif=exif)

        converted, mime = FileConverterEngine.convert_image(source.getvalue(), "png")
        self.assertEqual(mime, "image/png")
        with Image.open(io.BytesIO(converted)) as result:
            self.assertEqual(result.size, (10, 20))
            self.assertNotIn(274, result.getexif())
            top = result.convert("RGB").getpixel((5, 4))
            bottom = result.convert("RGB").getpixel((5, 15))
        self.assertGreater(top[0], top[2])
        self.assertGreater(bottom[2], bottom[0])

    def test_convert_image_preserves_icc_profile_and_dpi_for_supported_targets(self):
        profile = b"OfficeKit-test-ICC-profile"
        image = Image.new("RGB", (3, 2), color=(23, 114, 207))
        source = io.BytesIO()
        image.save(source, format="PNG", icc_profile=profile, dpi=(96, 144))

        converted, _mime = FileConverterEngine.convert_image(source.getvalue(), "png")
        with Image.open(io.BytesIO(converted)) as result:
            self.assertEqual(result.info.get("icc_profile"), profile)
            self.assertAlmostEqual(result.info["dpi"][0], 96, delta=1)
            self.assertAlmostEqual(result.info["dpi"][1], 144, delta=1)

    def test_strip_exif_preserves_indexed_palette_colors(self):
        palette = [0, 0, 0] * 256
        palette[3 * 7:3 * 7 + 3] = [245, 24, 81]
        palette[3 * 203:3 * 203 + 3] = [16, 173, 232]
        source = Image.new("P", (2, 1))
        source.putpalette(palette)
        source.putdata([7, 203])
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")
        expected = list(source.convert("RGB").get_flattened_data())

        cleaned = FileConverterEngine.strip_exif(buffer.getvalue())
        with Image.open(io.BytesIO(cleaned)) as result:
            actual = list(result.convert("RGB").get_flattened_data())

        self.assertEqual(actual, expected)

    def test_strip_exif_preserves_all_animated_gif_frames_and_durations(self):
        frames = [
            Image.new("RGB", (3, 2), color=(255, 0, 0)),
            Image.new("RGB", (3, 2), color=(0, 0, 255)),
        ]
        source = io.BytesIO()
        frames[0].save(
            source, format="GIF", save_all=True, append_images=frames[1:],
            duration=[120, 340], loop=0, disposal=2,
        )

        cleaned = FileConverterEngine.strip_exif(source.getvalue())
        with Image.open(io.BytesIO(cleaned)) as result:
            self.assertEqual(result.n_frames, 2)
            durations = []
            colors = []
            for frame_number in range(result.n_frames):
                result.seek(frame_number)
                durations.append(result.info.get("duration"))
                colors.append(result.convert("RGB").getpixel((1, 1)))

        self.assertEqual(durations, [120, 340])
        self.assertEqual(colors, [(255, 0, 0), (0, 0, 255)])

    def test_strip_exif_applies_orientation_before_removing_it(self):
        source_image = Image.new("RGB", (20, 10), (0, 0, 0))
        for y in range(10):
            for x in range(10):
                source_image.putpixel((x, y), (240, 20, 20))
            for x in range(10, 20):
                source_image.putpixel((x, y), (20, 20, 240))
        exif = Image.Exif()
        exif[274] = 6
        source = io.BytesIO()
        source_image.save(source, format="JPEG", quality=92, exif=exif)

        cleaned = FileConverterEngine.strip_exif(source.getvalue())
        with Image.open(io.BytesIO(cleaned)) as result:
            self.assertEqual(result.size, (10, 20))
            self.assertEqual(dict(result.getexif()), {})
            top = result.convert("RGB").getpixel((5, 4))
            bottom = result.convert("RGB").getpixel((5, 15))

        self.assertGreater(top[0], top[2])
        self.assertGreater(bottom[2], bottom[0])

    def test_strip_exif_preserves_png_color_profile_and_resolution(self):
        image = Image.new("RGB", (3, 2), color=(23, 114, 207))
        profile = b"OfficeKit-test-ICC-profile"
        source = io.BytesIO()
        image.save(source, format="PNG", icc_profile=profile, dpi=(96, 144))

        cleaned = FileConverterEngine.strip_exif(source.getvalue())
        with Image.open(io.BytesIO(cleaned)) as result:
            self.assertEqual(result.info.get("icc_profile"), profile)
            self.assertAlmostEqual(result.info["dpi"][0], 96, delta=1)
            self.assertAlmostEqual(result.info["dpi"][1], 144, delta=1)

    def test_strip_exif_preserves_multipage_tiff_frames(self):
        frames = [
            Image.new("RGB", (3, 2), color=(210, 30, 20)),
            Image.new("RGB", (3, 2), color=(20, 30, 210)),
        ]
        source = io.BytesIO()
        frames[0].save(source, format="TIFF", save_all=True, append_images=frames[1:])

        cleaned = FileConverterEngine.strip_exif(source.getvalue())
        with Image.open(io.BytesIO(cleaned)) as result:
            self.assertEqual(result.n_frames, 2)
            colors = []
            for frame in range(result.n_frames):
                result.seek(frame)
                colors.append(result.convert("RGB").getpixel((1, 1)))
        self.assertEqual(colors, [(210, 30, 20), (20, 30, 210)])

    def test_strip_exif_rejects_frames_over_the_pixel_budget_before_decoding(self):
        source = self._create_sample_png(size=(3, 2), mode="RGB")
        with patch.object(FileConverterEngine, "MAX_METADATA_FRAME_PIXELS", 5):
            with self.assertRaises(ConversionInputError):
                FileConverterEngine.strip_exif(source)

    def test_strip_exif_rejects_aggregate_animation_work_over_the_pixel_budget(self):
        frames = [Image.new("RGB", (2, 2), color=color) for color in ((255, 0, 0), (0, 0, 255))]
        source = io.BytesIO()
        frames[0].save(source, format="GIF", save_all=True, append_images=frames[1:])
        with patch.object(FileConverterEngine, "MAX_METADATA_TOTAL_PIXELS", 7):
            with self.assertRaises(ConversionInputError):
                FileConverterEngine.strip_exif(source.getvalue())

    def test_strip_exif_rejects_excessive_frame_count_before_decoding(self):
        frames = [Image.new("RGB", (1, 1), color=(index, 0, 0)) for index in range(3)]
        source = io.BytesIO()
        frames[0].save(source, format="GIF", save_all=True, append_images=frames[1:])
        with patch.object(FileConverterEngine, "MAX_METADATA_FRAMES", 2):
            with self.assertRaises(ConversionInputError):
                FileConverterEngine.strip_exif(source.getvalue())

    def test_convert_image_preserves_animated_webp_frames_timing_and_loop(self):
        frames = [
            Image.new("RGB", (3, 2), color=(230, 20, 10)),
            Image.new("RGB", (3, 2), color=(10, 20, 230)),
        ]
        source = io.BytesIO()
        frames[0].save(
            source, format="WEBP", save_all=True, append_images=frames[1:],
            duration=[100, 250], loop=2,
        )

        converted, mime = FileConverterEngine.convert_image(source.getvalue(), "webp", quality=90)
        self.assertEqual(mime, "image/webp")
        with Image.open(io.BytesIO(converted)) as result:
            self.assertEqual(result.n_frames, 2)
            durations = []
            for frame in range(result.n_frames):
                result.seek(frame)
                result.load()
                durations.append(result.info.get("duration"))
            self.assertEqual(result.info.get("loop"), 2)
        self.assertEqual(durations, [100, 250])

    def test_convert_image_rejects_animation_when_target_cannot_preserve_frames(self):
        frames = [
            Image.new("RGB", (3, 2), color=(235, 10, 5)),
            Image.new("RGB", (3, 2), color=(5, 10, 235)),
        ]
        source = io.BytesIO()
        frames[0].save(source, format="WEBP", save_all=True, append_images=frames[1:], duration=[100, 200])

        for target in ("png", "jpeg", "bmp", "pdf", "ico"):
            with self.subTest(target=target), self.assertRaises(ConversionInputError):
                FileConverterEngine.convert_image(source.getvalue(), target)

    def test_convert_image_preserves_multipage_tiff_and_rejects_single_frame_targets(self):
        frames = [
            Image.new("RGB", (3, 2), color=(220, 30, 20)),
            Image.new("RGB", (3, 2), color=(20, 30, 220)),
        ]
        source = io.BytesIO()
        frames[0].save(source, format="TIFF", save_all=True, append_images=frames[1:])

        converted, mime = FileConverterEngine.convert_image(source.getvalue(), "tiff")
        self.assertEqual(mime, "image/tiff")
        with Image.open(io.BytesIO(converted)) as result:
            self.assertEqual(result.n_frames, 2)
        with self.assertRaises(ConversionInputError):
            FileConverterEngine.convert_image(source.getvalue(), "jpeg")

    def test_convert_image_rejects_multiframe_work_over_configured_bounds(self):
        frames = [Image.new("RGB", (2, 2), color=color) for color in ((220, 30, 20), (20, 30, 220))]
        source = io.BytesIO()
        frames[0].save(source, format="TIFF", save_all=True, append_images=frames[1:])

        with patch.object(FileConverterEngine, "MAX_METADATA_FRAME_PIXELS", 3):
            with self.assertRaises(ConversionInputError):
                FileConverterEngine.convert_image(source.getvalue(), "tiff")
        with patch.object(FileConverterEngine, "MAX_METADATA_TOTAL_PIXELS", 7):
            with self.assertRaises(ConversionInputError):
                FileConverterEngine.convert_image(source.getvalue(), "tiff")
        with patch.object(FileConverterEngine, "MAX_METADATA_FRAMES", 1):
            with self.assertRaises(ConversionInputError):
                FileConverterEngine.convert_image(source.getvalue(), "tiff")

    def test_strip_exif_preserves_animated_webp_frames_and_timing(self):
        frames = [
            Image.new("RGB", (3, 2), color=(235, 15, 10)),
            Image.new("RGB", (3, 2), color=(10, 15, 235)),
        ]
        source = io.BytesIO()
        frames[0].save(
            source, format="WEBP", save_all=True, append_images=frames[1:],
            duration=[100, 250], loop=2,
        )
        source_bytes = source.getvalue()
        expected_colors = []
        with Image.open(io.BytesIO(source_bytes)) as original:
            for frame in range(original.n_frames):
                original.seek(frame)
                original.load()
                expected_colors.append(original.convert("RGB").getpixel((1, 1)))

        cleaned = FileConverterEngine.strip_exif(source_bytes)
        with Image.open(io.BytesIO(cleaned)) as result:
            self.assertEqual(result.n_frames, 2)
            durations = []
            colors = []
            for frame in range(result.n_frames):
                result.seek(frame)
                result.load()
                durations.append(result.info.get("duration"))
                colors.append(result.convert("RGB").getpixel((1, 1)))
            self.assertEqual(result.info.get("loop"), 2)
        self.assertEqual(durations, [100, 250])
        self.assertEqual(colors, expected_colors)

if __name__ == "__main__":
    unittest.main()
