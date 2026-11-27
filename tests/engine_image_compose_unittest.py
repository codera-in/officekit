"""Engine tests for collage, contact-sheet and icon-pack composition (image slice I17-I19)."""

import io
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from officekit.engines import engine_image_compose as compose
from officekit.engines.engine_file_converter import ImageWorkLimitError
from officekit.engines.engine_image_compose import (
    CollageLayout,
    ContactSheetLayout,
    ImageComposeEngine,
)
from officekit.engines.engine_image_tools import ImageToolInputError


def encode(image, image_format="PNG", **options):
    output = io.BytesIO()
    image.save(output, format=image_format, **options)
    return output.getvalue()


def decode(content):
    with Image.open(io.BytesIO(content)) as image:
        image.load()
        return image.copy()


def layout(**overrides):
    values = dict(
        columns=2, cell_width=100, cell_height=80, fit="contain", gap=10,
        padding=20, background="#FFFFFF", format="png",
    )
    values.update(overrides)
    return CollageLayout(**values)


class CollageCanvasTests(unittest.TestCase):
    def test_canvas_follows_the_exact_formula(self):
        self.assertEqual(ImageComposeEngine.collage_canvas(5, layout()), (250, 300))
        self.assertEqual(ImageComposeEngine.collage_canvas(2, layout(columns=1, gap=0, padding=0)), (100, 160))

    def test_canvas_overflow_is_rejected_from_the_layout_before_decoding(self):
        with self.assertRaises(ImageToolInputError) as raised:
            ImageComposeEngine.collage_canvas(10, layout(columns=10, cell_width=4000))
        self.assertEqual((raised.exception.code, raised.exception.status_code), ("CANVAS_TOO_LARGE", 422))

    def test_area_limit_is_enforced_separately_from_side_limit(self):
        # Each side is within 10,000 px, but the 9000 x 10000 canvas is 90 MP, over the 40 MP area limit.
        with self.assertRaises(ImageToolInputError) as raised:
            ImageComposeEngine.collage_canvas(2, layout(columns=1, cell_width=9000, cell_height=5000, gap=0, padding=0))
        self.assertEqual(raised.exception.code, "CANVAS_TOO_LARGE")


class CollageRenderTests(unittest.TestCase):
    def test_mixed_portrait_landscape_and_alpha_inputs_fill_the_exact_canvas(self):
        images = [
            encode(Image.new("RGBA", (20, 40), (255, 0, 0, 255))),
            encode(Image.new("RGB", (60, 30), (0, 255, 0))),
            encode(Image.new("RGBA", (30, 30), (0, 0, 255, 128))),
        ]
        content, media_type, size = ImageComposeEngine.build_collage(images, layout(columns=2))
        self.assertEqual(media_type, "image/png")
        self.assertEqual(size, ImageComposeEngine.collage_canvas(3, layout(columns=2)))
        self.assertEqual(decode(content).size, size)

    def test_upload_order_is_the_layout_order(self):
        red = encode(Image.new("RGB", (10, 10), (255, 0, 0)))
        green = encode(Image.new("RGB", (10, 10), (0, 255, 0)))
        content, _media, _size = ImageComposeEngine.build_collage(
            [red, green], layout(columns=2, cell_width=10, cell_height=10, gap=0, padding=0),
        )
        output = decode(content).convert("RGB")
        self.assertEqual(output.getpixel((5, 5)), (255, 0, 0))
        self.assertEqual(output.getpixel((15, 5)), (0, 255, 0))

    def test_cover_fills_the_cell_and_contain_keeps_the_background(self):
        tall = encode(Image.new("RGB", (10, 40), (10, 10, 10)))
        cover, _m, _s = ImageComposeEngine.build_collage(
            [tall, tall], layout(columns=2, cell_width=20, cell_height=20, gap=0, padding=0, fit="cover"),
        )
        self.assertEqual(decode(cover).convert("RGB").getpixel((0, 0)), (10, 10, 10))
        contain, _m, _s = ImageComposeEngine.build_collage(
            [tall, tall], layout(columns=2, cell_width=20, cell_height=20, gap=0, padding=0, fit="contain", background="#FF00FF"),
        )
        self.assertEqual(decode(contain).convert("RGB").getpixel((0, 0)), (255, 0, 255))

    def test_cover_of_an_elongated_strip_never_resizes_beyond_the_cell(self):
        # CR-1: a 1000 x 2 strip in a 100 x 100 cell must not be scaled to 50000 x 100 first.
        strip = encode(Image.new("RGB", (1000, 2), (10, 10, 10)))
        real_resize = Image.Image.resize
        sizes = []

        def bounded_resize(image, size, *args, **kwargs):
            sizes.append(tuple(size))
            if size[0] * size[1] > 10_000:
                raise AssertionError(f"unbounded intermediate resize {size}")
            return real_resize(image, size, *args, **kwargs)

        with mock.patch.object(Image.Image, "resize", bounded_resize):
            output, _media, _size = ImageComposeEngine.build_collage(
                [strip, strip], layout(columns=2, cell_width=100, cell_height=100, gap=0, padding=0, fit="cover", background="#FFFFFF"),
            )
        self.assertTrue(sizes)
        self.assertEqual(set(sizes), {(100, 100)})
        self.assertEqual(decode(output).convert("RGB").getpixel((50, 50)), (10, 10, 10))

    def test_transparent_background_stays_transparent_in_png(self):
        square = encode(Image.new("RGB", (10, 10), (1, 2, 3)))
        content, _m, _s = ImageComposeEngine.build_collage(
            [square, square], layout(columns=2, cell_width=10, cell_height=10, padding=5, background="transparent"),
        )
        self.assertEqual(decode(content).convert("RGBA").getpixel((0, 0))[3], 0)

    def test_jpeg_output_flattens_transparency_and_drops_exif(self):
        exif = Image.Exif()
        exif[0x010F] = "Source Make"
        source = encode(Image.new("RGBA", (10, 10), (1, 2, 3, 0)), exif=exif.tobytes())
        content, media_type, _size = ImageComposeEngine.build_collage(
            [source, source], layout(columns=2, cell_width=10, cell_height=10, gap=0, padding=0, background="transparent", format="jpeg"),
        )
        self.assertEqual(media_type, "image/jpeg")
        with Image.open(io.BytesIO(content)) as readback:
            self.assertNotIn("exif", readback.info)

    def test_preview_scales_the_layout_and_outputs_png(self):
        images = [encode(Image.new("RGB", (400, 300), (1, 2, 3)))] * 2
        content, media_type, size = ImageComposeEngine.build_collage(
            images, layout(columns=2, cell_width=400, cell_height=300), preview_max_edge=200,
        )
        self.assertEqual(media_type, "image/png")
        self.assertLessEqual(max(size), 200)
        self.assertEqual(decode(content).size, size)

    def test_too_few_or_too_many_inputs_are_rejected(self):
        one = encode(Image.new("RGB", (2, 2)))
        with self.assertRaises(ImageToolInputError) as too_few:
            ImageComposeEngine.build_collage([one], layout())
        self.assertEqual(too_few.exception.code, "INVALID_OPERATION")
        with self.assertRaises(ImageToolInputError) as too_many:
            ImageComposeEngine.build_collage([one] * 51, layout())
        self.assertEqual(too_many.exception.code, "INVALID_OPERATION")

    def test_truncated_pixel_data_is_a_stable_invalid_image_error(self):
        # CR-7: the header parses, the pixel load fails; the public error must still be INVALID_IMAGE.
        noise = Image.frombytes("RGB", (128, 128), bytes(range(256)) * (128 * 128 * 3 // 256))
        truncated = encode(noise, "JPEG", quality=95)[:1200]
        with self.assertRaises(ImageToolInputError) as raised:
            ImageComposeEngine.build_collage([truncated, truncated], layout())
        self.assertEqual(raised.exception.code, "INVALID_IMAGE")

    def test_malformed_input_is_a_stable_invalid_image_error(self):
        with self.assertRaises(ImageToolInputError) as raised:
            ImageComposeEngine.build_collage([encode(Image.new("RGB", (2, 2))), b"junk"], layout())
        self.assertEqual(raised.exception.code, "INVALID_IMAGE")


class ContactSheetTests(unittest.TestCase):
    def files(self, count, name="shot.png"):
        return [(f"{name[:-4]}{index}.png", encode(Image.new("RGB", (20, 20), (index % 255, 0, 0)))) for index in range(count)]

    def test_one_hundred_eighty_images_at_four_by_six_give_eight_pdf_pages(self):
        sheet = ContactSheetLayout(
            page="a4", orientation="portrait", columns=4, rows=6, show_names=True, format="pdf",
        )
        content, media_type, pages = ImageComposeEngine.build_contact_sheet(self.files(180), sheet)
        self.assertEqual(media_type, "application/pdf")
        self.assertEqual(pages, 8)
        self.assertIn(b"/Count 8", content)

    def test_png_zip_has_one_numbered_png_per_page(self):
        sheet = ContactSheetLayout(
            page="letter", orientation="landscape", columns=2, rows=2, show_names=False, format="png-zip",
        )
        content, media_type, pages = ImageComposeEngine.build_contact_sheet(self.files(5), sheet)
        self.assertEqual(media_type, "application/zip")
        self.assertEqual(pages, 2)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(archive.namelist(), ["contact-sheet-001.png", "contact-sheet-002.png"])
            page = decode(archive.read("contact-sheet-001.png"))
            self.assertEqual(page.size, (1650, 1275))

    def test_first_page_preview_is_one_png_and_still_reports_every_page(self):
        # UX-5: "Preview page 1" renders only page 1, as PNG, and the header still counts all pages.
        sheet = ContactSheetLayout(page="a4", orientation="portrait", columns=2, rows=2, show_names=False, format="pdf")
        with mock.patch.object(ImageDraw.ImageDraw, "text", autospec=True) as drawn:
            content, media_type, pages = ImageComposeEngine.build_contact_sheet(self.files(9), sheet, first_page_only=True)
        self.assertEqual((media_type, pages), ("image/png", 3))
        self.assertEqual(decode(content).size, (1240, 1754))
        drawn.assert_not_called()

    def test_names_off_draws_no_text(self):
        sheet = ContactSheetLayout(page="a4", orientation="portrait", columns=2, rows=2, show_names=False, format="png-zip")
        with mock.patch.object(ImageDraw.ImageDraw, "text", autospec=True) as drawn:
            ImageComposeEngine.build_contact_sheet(self.files(3), sheet)
        drawn.assert_not_called()

    def test_names_on_draws_labels(self):
        sheet = ContactSheetLayout(page="a4", orientation="portrait", columns=2, rows=2, show_names=True, format="png-zip")
        with mock.patch.object(ImageDraw.ImageDraw, "text", autospec=True, side_effect=ImageDraw.ImageDraw.text) as drawn:
            ImageComposeEngine.build_contact_sheet(self.files(3), sheet)
        self.assertEqual(drawn.call_count, 3)
        self.assertEqual([call.args[2] for call in drawn.call_args_list], ["shot0.png", "shot1.png", "shot2.png"])

    def test_pdf_refuses_before_drawing_when_all_pages_exceed_the_ceiling(self):
        # The PDF writer needs every page in memory, so the summed page bitmaps have an explicit ceiling.
        sheet = ContactSheetLayout(page="a4", orientation="portrait", columns=1, rows=1, show_names=False, format="pdf")
        page_bytes = 1240 * 1754 * 3
        with mock.patch.object(compose, "CONTACT_SHEET_RETAINED_PAGE_BYTES", page_bytes):
            with self.assertRaises(ImageWorkLimitError):
                ImageComposeEngine.build_contact_sheet(self.files(2), sheet)
            sheet_zip = ContactSheetLayout(
                page="a4", orientation="portrait", columns=1, rows=1, show_names=False, format="png-zip",
            )
            _content, media_type, pages = ImageComposeEngine.build_contact_sheet(self.files(2), sheet_zip)
        self.assertEqual((media_type, pages), ("application/zip", 2))

    def test_pdf_page_bytes_exactly_at_the_ceiling_still_render(self):
        sheet = ContactSheetLayout(page="a4", orientation="portrait", columns=1, rows=1, show_names=False, format="pdf")
        page_bytes = 1240 * 1754 * 3
        with mock.patch.object(compose, "CONTACT_SHEET_RETAINED_PAGE_BYTES", page_bytes):
            _content, media_type, pages = ImageComposeEngine.build_contact_sheet(self.files(1), sheet)
        self.assertEqual((media_type, pages), ("application/pdf", 1))

    def test_pdf_page_bytes_one_byte_over_the_ceiling_are_refused(self):
        sheet = ContactSheetLayout(page="a4", orientation="portrait", columns=1, rows=1, show_names=False, format="pdf")
        page_bytes = 1240 * 1754 * 3
        with mock.patch.object(compose, "CONTACT_SHEET_RETAINED_PAGE_BYTES", page_bytes - 1):
            with self.assertRaises(ImageWorkLimitError):
                ImageComposeEngine.build_contact_sheet(self.files(1), sheet)

    def test_long_and_unicode_names_are_truncated_in_the_middle(self):
        name = "a" * 200 + "終端-report.png"
        truncated = compose.truncate_middle(name, max_width=20, measure=len)
        self.assertLessEqual(len(truncated), 20)
        self.assertIn("…", truncated)
        self.assertTrue(truncated.startswith("aaa"))
        self.assertTrue(truncated.endswith("eport.png"))
        self.assertEqual(compose.truncate_middle("short.png", max_width=20, measure=len), "short.png")

    def test_names_are_nfc_normalised_and_controls_removed(self):
        self.assertEqual(compose.clean_name("é\x07.png"), "é.png")

    def test_empty_or_oversized_sheets_are_rejected(self):
        sheet = ContactSheetLayout(page="a4", orientation="portrait", columns=1, rows=1, show_names=True, format="pdf")
        with self.assertRaises(ImageToolInputError):
            ImageComposeEngine.build_contact_sheet([], sheet)
        with self.assertRaises(ImageToolInputError):
            ImageComposeEngine.build_contact_sheet(self.files(201), sheet)


class IconPackTests(unittest.TestCase):
    def archive(self, content, platforms=("web", "windows", "macos"), fit="pad"):
        data, upscaled = ImageComposeEngine.build_icon_pack(content, list(platforms), fit)
        return zipfile.ZipFile(io.BytesIO(data)), upscaled

    def test_zip_names_and_sizes_are_exact_for_every_platform(self):
        archive, _upscaled = self.archive(encode(Image.new("RGBA", (512, 512), (9, 9, 9, 255))))
        names = sorted(archive.namelist())
        self.assertEqual(names, sorted([
            "web/favicon.ico", "web/favicon-16x16.png", "web/favicon-32x32.png", "web/apple-touch-icon.png",
            "web/android-chrome-192x192.png", "web/android-chrome-512x512.png", "windows/app.ico",
            "macos/icon.iconset/icon_16x16.png", "macos/icon.iconset/icon_16x16@2x.png",
            "macos/icon.iconset/icon_32x32.png", "macos/icon.iconset/icon_32x32@2x.png",
            "macos/icon.iconset/icon_128x128.png", "macos/icon.iconset/icon_128x128@2x.png",
            "macos/icon.iconset/icon_256x256.png", "macos/icon.iconset/icon_256x256@2x.png",
            "macos/icon.iconset/icon_512x512.png", "macos/icon.iconset/icon_512x512@2x.png",
        ]))
        self.assertEqual(decode(archive.read("macos/icon.iconset/icon_512x512@2x.png")).size, (1024, 1024))
        self.assertEqual(decode(archive.read("web/android-chrome-192x192.png")).size, (192, 192))

    def test_icon_ico_files_hold_every_declared_resolution(self):
        archive, _upscaled = self.archive(encode(Image.new("RGBA", (512, 512), (9, 9, 9, 255))))
        with Image.open(io.BytesIO(archive.read("web/favicon.ico"))) as favicon:
            self.assertEqual(favicon.info["sizes"], {(16, 16), (32, 32), (48, 48)})
        with Image.open(io.BytesIO(archive.read("windows/app.ico"))) as windows:
            self.assertEqual(windows.info["sizes"], {(s, s) for s in (16, 24, 32, 48, 64, 128, 256)})

    def test_platform_selection_limits_the_folders(self):
        archive, _upscaled = self.archive(encode(Image.new("RGB", (64, 64))), platforms=("windows",))
        self.assertEqual(archive.namelist(), ["windows/app.ico"])

    def test_alpha_is_kept_except_for_apple_touch_icon(self):
        source = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        source.paste((200, 0, 0, 255), (16, 16, 48, 48))
        archive, _upscaled = self.archive(encode(source))
        self.assertEqual(decode(archive.read("web/favicon-32x32.png")).convert("RGBA").getpixel((0, 0))[3], 0)
        self.assertEqual(decode(archive.read("web/favicon-32x32.png")).convert("RGBA").getpixel((16, 16))[3], 255)
        touch = decode(archive.read("web/apple-touch-icon.png")).convert("RGBA")
        self.assertEqual(touch.getpixel((0, 0)), (255, 255, 255, 255))

    def test_non_square_pad_centres_on_transparent_square_and_crop_centres(self):
        wide = encode(Image.new("RGBA", (40, 20), (0, 200, 0, 255)))
        archive, _upscaled = self.archive(wide, platforms=("web",), fit="pad")
        padded = decode(archive.read("web/android-chrome-512x512.png")).convert("RGBA")
        self.assertEqual(padded.getpixel((0, 0))[3], 0)
        self.assertEqual(padded.getpixel((256, 256)), (0, 200, 0, 255))
        archive, _upscaled = self.archive(wide, platforms=("web",), fit="crop")
        cropped = decode(archive.read("web/android-chrome-512x512.png")).convert("RGBA")
        self.assertEqual(cropped.getpixel((0, 0)), (0, 200, 0, 255))

    def test_small_source_discloses_upscaled_sizes(self):
        _archive, upscaled = self.archive(encode(Image.new("RGB", (32, 32), (1, 2, 3))), platforms=("macos",))
        self.assertIn(1024, upscaled)
        self.assertNotIn(16, upscaled)
        self.assertEqual(upscaled, sorted(upscaled))
        self.assertEqual(len(upscaled), len(set(upscaled)))

    def test_multi_frame_input_uses_the_first_frame(self):
        frames = [Image.new("RGB", (8, 8), (250, 0, 0)).convert("P"), Image.new("RGB", (8, 8), (0, 0, 250)).convert("P")]
        output = io.BytesIO()
        frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:])
        archive, _upscaled = self.archive(output.getvalue(), platforms=("web",))
        pixel = decode(archive.read("web/favicon-16x16.png")).convert("RGB").getpixel((8, 8))
        self.assertGreater(pixel[0], 200)
        self.assertLess(pixel[2], 50)

    def test_unknown_platform_is_rejected(self):
        with self.assertRaises(ImageToolInputError) as raised:
            ImageComposeEngine.build_icon_pack(encode(Image.new("RGB", (4, 4))), ["linux"], "pad")
        self.assertEqual(raised.exception.code, "INVALID_OPERATION")


class FontLookupTests(unittest.TestCase):
    def test_bundled_sidecar_copy_is_tried_before_the_repo_asset(self):
        with tempfile.TemporaryDirectory() as bundle:
            with mock.patch.object(compose.sys, "_MEIPASS", bundle, create=True):
                candidates = compose._font_candidates()
        self.assertEqual(candidates[0], Path(bundle) / "fonts" / "NotoSans-Regular.ttf")
        self.assertEqual(candidates[-1].name, "NotoSans-Regular.ttf")
        self.assertTrue(candidates[-1].is_file())

    def test_bundled_copy_is_loaded_when_present(self):
        real_truetype = compose.ImageFont.truetype
        with tempfile.TemporaryDirectory() as bundle:
            font_dir = Path(bundle) / "fonts"
            font_dir.mkdir()
            shutil.copy(compose._font_candidates()[-1], font_dir / "NotoSans-Regular.ttf")
            with mock.patch.object(compose.sys, "_MEIPASS", bundle, create=True), mock.patch.object(
                compose.ImageFont, "truetype", side_effect=real_truetype,
            ) as truetype:
                font = compose._label_font(22)
        self.assertEqual(Path(truetype.call_args_list[0].args[0]), font_dir / "NotoSans-Regular.ttf")
        self.assertIsNotNone(font)

    def test_missing_font_falls_back_to_the_default_font(self):
        missing = Path("officekit-missing-font-does-not-exist.ttf")
        with mock.patch.object(compose, "_font_candidates", return_value=[missing]), mock.patch.object(
            compose.ImageFont, "load_default", return_value="default-font",
        ) as load_default:
            font = compose._label_font(22)
        self.assertEqual(font, "default-font")
        load_default.assert_called_once_with(22)


if __name__ == "__main__":
    unittest.main()
