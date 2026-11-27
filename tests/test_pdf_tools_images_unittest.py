import io
import re
import unittest
from pathlib import Path
from unittest import mock

import pikepdf
from PIL import Image

from officekit.engines.engine_images_to_pdf import ImageInputError, ImagesToPdfEngine
from officekit.engines.engine_pdf_security import PdfOutputLimitError
from tests.pdf_tool_fixtures import make_jpeg, make_png, render_page


def encode(image, fmt, **options):
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **options)
    return buffer.getvalue()


def build(images, page_size="a4", orientation="auto", fit="contain", margin_mm=10):
    return ImagesToPdfEngine.build(images, page_size, orientation, fit, margin_mm)


def page_boxes(data):
    with pikepdf.open(io.BytesIO(data)) as pdf:
        return [[float(v) for v in page.mediabox] for page in pdf.pages]


def centre_colour(data, index):
    image = render_page(data, index)
    return image.getpixel((image.size[0] // 2, image.size[1] // 2))[:3]


def corner_colour(data, index):
    return render_page(data, index).getpixel((2, 2))[:3]


class FitAndPageSizeTests(unittest.TestCase):
    """A 60 x 30 red PNG on A4 landscape with no margin: contain leaves white bands, cover fills the page."""

    def build_fit(self, fit):
        return build([make_png(60, 30, (255, 0, 0))], page_size="a4", orientation="landscape", fit=fit, margin_mm=0)

    def test_contain_leaves_a_white_band_at_the_corner(self):
        output = self.build_fit("contain")
        self.assertEqual(corner_colour(output, 0), (255, 255, 255))
        self.assertEqual(centre_colour(output, 0), (255, 0, 0))

    def test_cover_fills_the_corner(self):
        output = self.build_fit("cover")
        self.assertEqual(corner_colour(output, 0), (255, 0, 0))

    def test_actual_draws_the_natural_size_centred(self):
        # 60 px at the default 96 DPI is 45 pt, so the red block is small and the corner stays white.
        output = self.build_fit("actual")
        self.assertEqual(corner_colour(output, 0), (255, 255, 255))
        self.assertEqual(centre_colour(output, 0), (255, 0, 0))

    def test_image_page_size_is_clamped_to_the_pdf_page_limit(self):
        # 4000 px tagged at 1 DPI would be 288,000 pt. The page is clamped to 14,400 pt and the aspect is kept.
        wide = encode(Image.new("RGB", (4000, 100), (1, 2, 3)), "PNG", dpi=(1, 1))
        width, height = page_boxes(build([wide], page_size="image", fit="contain", margin_mm=0))[0][2:]
        self.assertAlmostEqual(width, 14_400.0, places=3)
        self.assertAlmostEqual(height, 360.0, places=3)

    def test_non_finite_zero_and_negative_dpi_fall_back_to_the_default(self):
        for value in ((float("inf"), 72), (float("nan"), 72), (0, 0), (-5, 72)):
            with self.subTest(value=value):
                self.assertEqual(ImagesToPdfEngine._dpi(value), ImagesToPdfEngine.DEFAULT_DPI)


class ImagesToPdfTests(unittest.TestCase):
    def test_order_and_page_count_follow_the_batch(self):
        colours = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
        images = [make_png(60, 60, color) for color in colours]
        output = build(images, fit="cover", margin_mm=0)
        self.assertEqual(len(page_boxes(output)), 3)
        for index, colour in enumerate(colours):
            self.assertLess(sum(abs(a - b) for a, b in zip(centre_colour(output, index), colour)), 40)

    def test_auto_orientation_matches_each_image(self):
        landscape = make_png(200, 100)
        portrait = make_png(100, 200)
        boxes = page_boxes(build([landscape, portrait]))
        self.assertGreater(boxes[0][2], boxes[0][3])
        self.assertLess(boxes[1][2], boxes[1][3])

    def test_forced_orientation(self):
        boxes = page_boxes(build([make_png(100, 200)], orientation="landscape"))
        self.assertGreater(boxes[0][2], boxes[0][3])
        boxes = page_boxes(build([make_png(200, 100)], orientation="portrait"))
        self.assertLess(boxes[0][2], boxes[0][3])

    def test_exif_orientation_six_and_eight_swap_the_page(self):
        for orientation in (6, 8):
            with self.subTest(orientation=orientation):
                # Stored 40x20 with EXIF rotation displays as 20x40, so auto picks portrait.
                image = Image.new("RGB", (40, 20), (10, 10, 10))
                exif = Image.Exif()
                exif[0x0112] = orientation
                data = encode(image, "PNG", exif=exif.tobytes())
                boxes = page_boxes(build([data]))
                self.assertLess(boxes[0][2], boxes[0][3])

    def test_jpeg_without_orientation_is_passed_through_undecoded(self):
        output = build([make_jpeg(80, 60)], fit="contain")
        with pikepdf.open(io.BytesIO(output)) as pdf:
            xobjects = pdf.pages[0].Resources.XObject
            image = next(iter(xobjects.values()))
            filters = [str(name) for name in image.Filter] if isinstance(image.Filter, pikepdf.Array) \
                else [str(image.Filter)]
            self.assertIn("/DCTDecode", filters)

    def test_alpha_is_composited_on_white(self):
        transparent = make_png(40, 40, (0, 0, 0), alpha=0)
        output = build([transparent], fit="cover", margin_mm=0)
        self.assertEqual(centre_colour(output, 0), (255, 255, 255))

    def test_page_size_image_uses_pixels_at_dpi(self):
        image = Image.new("RGB", (100, 50), (1, 2, 3))
        data = encode(image, "PNG", dpi=(50, 50))
        boxes = page_boxes(build([data], page_size="image"))
        self.assertAlmostEqual(boxes[0][2], 144.0, places=3)
        self.assertAlmostEqual(boxes[0][3], 72.0, places=3)

    def test_actual_fit_uses_image_dpi(self):
        image = Image.new("RGB", (96, 96), (9, 9, 9))
        data = encode(image, "PNG", dpi=(96, 96))
        output = build([data], page_size="letter", fit="actual", margin_mm=0)
        boxes = page_boxes(output)
        self.assertEqual([round(v, 3) for v in boxes[0]], [0, 0, 612, 792])
        self.assertEqual(centre_colour(output, 0), (9, 9, 9))

    def test_fixed_pages_and_margins(self):
        self.assertEqual(page_boxes(build([make_png(10, 10)], page_size="letter"))[0][2:], [612.0, 792.0])
        self.assertEqual(page_boxes(build([make_png(10, 10)], page_size="legal", orientation="landscape"))[0][2:],
                         [1008.0, 612.0])
        self.assertAlmostEqual(page_boxes(build([make_png(10, 10)], page_size="a4"))[0][2], 595.2756, places=3)

    def test_two_hundred_images_build_and_201_is_refused(self):
        images = [make_png(4, 4, (index % 255, 0, 0)) for index in range(200)]
        output = build(images)
        self.assertEqual(len(page_boxes(output)), 200)
        with self.assertRaises(ValueError):
            build(images + [make_png(4, 4)])
        with self.assertRaises(ValueError):
            build([])

    def test_option_validation(self):
        image = make_png(10, 10)
        invalid_calls = [
            dict(page_size="a3"), dict(orientation="diagonal"), dict(fit="stretch"),
            dict(margin_mm=51), dict(margin_mm=-1), dict(margin_mm=True),
        ]
        for overrides in invalid_calls:
            with self.subTest(**overrides), self.assertRaises(ValueError):
                build([image], **overrides)

    def test_unreadable_and_disallowed_images_name_only_the_position(self):
        good = make_png(10, 10)
        with self.assertRaises(ImageInputError) as raised:
            build([good, b"not an image"])
        self.assertEqual(str(raised.exception), "Image 2 could not be read.")
        svg = b"<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'></svg>"
        with self.assertRaises(ImageInputError):
            build([good, svg])
        with self.assertRaises(ImageInputError):
            build([b""])

    def test_shipped_total_pixel_budget_refuses_before_any_decode(self):
        # CR-7: the real 150 M budget (about 450 MB decoded RGB) is enforced from the headers alone.
        self.assertEqual(ImagesToPdfEngine.MAX_TOTAL_PIXELS, 150_000_000)
        big = mock.MagicMock()
        big.format = "PNG"
        big.size = (6000, 6000)
        big.mode = "RGB"
        big.info = {}
        big.getexif.return_value = {}
        big.__enter__.return_value = big
        big.__exit__.return_value = False
        with mock.patch("officekit.engines.engine_images_to_pdf.Image.open", return_value=big), \
                self.assertRaises(ImageInputError) as raised:
            ImagesToPdfEngine._read_headers([b"header-only"] * 5)
        self.assertEqual(raised.exception.position, 5)
        self.assertEqual(big.size, (6000, 6000))

    def test_pixel_budgets_are_checked_before_decode(self):
        image = make_png(20, 20)
        with mock.patch.object(ImagesToPdfEngine, "MAX_IMAGE_PIXELS", 100), self.assertRaises(ImageInputError):
            build([image])
        with mock.patch.object(ImagesToPdfEngine, "MAX_TOTAL_PIXELS", 500), self.assertRaises(ImageInputError) as raised:
            build([image, image, image])
        self.assertEqual(raised.exception.position, 2)

    def test_output_cap_stops_serialisation(self):
        with mock.patch.object(ImagesToPdfEngine, "MAX_OUTPUT_BYTES", 64), self.assertRaises(PdfOutputLimitError):
            build([make_png(60, 60)])

    def test_inputs_are_not_modified(self):
        data = make_png(20, 20)
        snapshot = bytes(data)
        build([data])
        self.assertEqual(data, snapshot)


class SliceCapMirrorTests(unittest.TestCase):
    """ARCH-12: the slice keeps a copy of the images caps for its limit line. The engine is the authority, so the
    copy must equal it, or the copy on screen drifts silently."""

    def test_slice_caps_equal_the_engine_caps(self):
        slice_source = (Path(__file__).resolve().parents[1] / "assets" / "officekit-slice-pdf-tools.js").read_text(encoding="utf-8")
        files = int(re.search(r"const MAX_IMAGE_FILES = (\d+);", slice_source).group(1))
        megapixels = int(re.search(r"const MAX_IMAGE_MEGAPIXELS = (\d+);", slice_source).group(1))
        self.assertEqual(files, ImagesToPdfEngine.MAX_IMAGES)
        self.assertEqual(megapixels * 1_000_000, ImagesToPdfEngine.MAX_IMAGE_PIXELS)


if __name__ == "__main__":
    unittest.main()
