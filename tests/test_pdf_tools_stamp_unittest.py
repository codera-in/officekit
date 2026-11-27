import io
import json
import unittest
from pathlib import Path
from unittest import mock

import pdfplumber
import pikepdf
from PIL import Image, ImageChops

from officekit.engines import engine_pdf_stamp as stamp_module
from officekit.engines.engine_pdf_security import PdfOutputLimitError
from officekit.engines.engine_pdf_tool_common import PdfOptionError, selected_indexes
from officekit.engines.engine_pdf_stamp import (
    PageNumberSpec,
    PdfStampEngine,
    PdfStampInputError,
    WatermarkSpec,
    format_ranges,
    _roman,
)
from tests.pdf_tool_fixtures import make_pdf, make_png, pdf_bytes, render_page


def watermark_spec(**overrides):
    values = dict(kind="text", text="DRAFT", image=None, font_size=48, color="#FF0000", opacity=50,
                  angle=0, position="center", page_ranges="")
    values.update(overrides)
    return WatermarkSpec(**values)


def number_spec(**overrides):
    values = dict(number_format="number", template=None, start=1, position="bottom-center", margin_mm=10,
                  font_size=12, page_ranges="", count_skipped=False)
    values.update(overrides)
    return PageNumberSpec(**values)


def page_texts(data):
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def changed_bbox(before, after):
    return ImageChops.difference(before.convert("RGB"), after.convert("RGB")).getbbox()


def extgstate_alphas(data):
    alphas = set()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            stack = [page.obj.get("/Resources", pikepdf.Dictionary())]
            while stack:
                resources = stack.pop()
                for key in ("/XObject",):
                    for value in (resources.get(key) or {}).values():
                        nested = value.get("/Resources")
                        if nested is not None:
                            stack.append(nested)
                gs = resources.get("/ExtGState") or {}
                for state in gs.values():
                    if "/ca" in state:
                        alphas.add(round(float(state["/ca"]), 4))
    return alphas


class WatermarkTextTests(unittest.TestCase):
    def test_center_text_is_visible_and_source_is_unchanged(self):
        source = pdf_bytes(make_pdf([(612, 792)], text_prefix="BODY "))
        snapshot = bytes(source)
        output = PdfStampEngine.watermark(source, watermark_spec())
        self.assertIn("DRAFT", page_texts(output)[0])
        self.assertIn("BODY 1", page_texts(output)[0])
        self.assertEqual(source, snapshot)

    def test_top_left_stamp_is_upright_on_rotated_page(self):
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                source = pdf_bytes(make_pdf([(400, 300)], rotate=rotation))
                output = PdfStampEngine.watermark(source, watermark_spec(
                    position="top-left", angle=0, font_size=36, opacity=100, color="#000000", text="X"))
                before = render_page(source, 0)
                after = render_page(output, 0)
                left, top, right, bottom = changed_bbox(before, after)
                self.assertLess(left, after.size[0] * 0.5)
                self.assertLess(top, after.size[1] * 0.5)

    def test_bottom_right_stamp_on_landscape_page(self):
        source = pdf_bytes(make_pdf([(600, 300)]))
        output = PdfStampEngine.watermark(source, watermark_spec(
            position="bottom-right", font_size=30, opacity=100, color="#000000", text="Z"))
        before = render_page(source, 0)
        after = render_page(output, 0)
        left, top, right, bottom = changed_bbox(before, after)
        self.assertGreater(left, after.size[0] * 0.5)
        self.assertGreater(top, after.size[1] * 0.5)

    def test_opacity_maps_to_extgstate_ca(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        output = PdfStampEngine.watermark(source, watermark_spec(opacity=25))
        self.assertIn(0.25, extgstate_alphas(output))

    def test_exact_page_range_is_stamped(self):
        source = pdf_bytes(make_pdf([(300, 200), (300, 200), (300, 200)]))
        output = PdfStampEngine.watermark(source, watermark_spec(page_ranges="2"))
        texts = page_texts(output)
        self.assertNotIn("DRAFT", texts[0])
        self.assertIn("DRAFT", texts[1])
        self.assertNotIn("DRAFT", texts[2])

    def test_tile_repeats_text_and_respects_tile_budget(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        output = PdfStampEngine.watermark(source, watermark_spec(position="tile", font_size=12, text="T"))
        self.assertGreater(page_texts(output)[0].count("T"), 4)
        with mock.patch.object(PdfStampEngine, "MAX_TILES_PER_PAGE", 1), \
                self.assertRaises(ValueError):
            PdfStampEngine.watermark(source, watermark_spec(position="tile", font_size=12, text="T"))

    def test_latin_greek_and_cyrillic_text_is_accepted(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        output = PdfStampEngine.watermark(source, watermark_spec(text="Résumé Ωμέγα Жизнь"))
        text = page_texts(output)[0]
        for word in ("Résumé", "Ωμέγα", "Жизнь"):
            self.assertIn(word, text)

    def test_uncovered_glyphs_are_refused_with_fixed_copy(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        for text in ("漢字", "Draft 😀"):
            with self.subTest(text=text), self.assertRaises(PdfStampInputError) as raised:
                PdfStampEngine.watermark(source, watermark_spec(text=text))
            self.assertEqual(str(raised.exception), PdfStampEngine.UNSUPPORTED_GLYPH_MESSAGE)

    def test_text_validation_bounds(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        invalid = [
            watermark_spec(text=""),
            watermark_spec(text="A" * 201),
            watermark_spec(text="bad\x07"),
            watermark_spec(text="bad\u0085"),
            watermark_spec(font_size=7),
            watermark_spec(font_size=145),
            watermark_spec(color="red"),
            watermark_spec(color="#GGGGGG"),
            watermark_spec(opacity=4),
            watermark_spec(opacity=101),
            watermark_spec(angle=91),
            watermark_spec(angle=-91),
            watermark_spec(position="middle"),
            watermark_spec(kind="sticker"),
            watermark_spec(kind="image", text=None, image=None),
        ]
        for spec in invalid:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                PdfStampEngine.watermark(source, spec)

    def test_boundary_values_are_accepted(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        for spec in (watermark_spec(text="A" * 200, font_size=8, opacity=5, angle=-90),
                     watermark_spec(font_size=144, opacity=100, angle=90, text="B")):
            with self.subTest(spec=spec):
                self.assertTrue(PdfStampEngine.watermark(source, spec).startswith(b"%PDF"))

    def test_output_cap_is_enforced(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        with mock.patch.object(PdfStampEngine, "MAX_OUTPUT_BYTES", 64), \
                self.assertRaises(PdfOutputLimitError):
            PdfStampEngine.watermark(source, watermark_spec())

    def test_malformed_encrypted_and_empty_inputs(self):
        with self.assertRaises(ValueError):
            PdfStampEngine.watermark(b"", watermark_spec())
        with self.assertRaises(pikepdf.PdfError):
            PdfStampEngine.watermark(b"%PDF nope", watermark_spec())
        encrypted = io.BytesIO()
        make_pdf([(300, 200)]).save(encrypted, encryption=pikepdf.Encryption(user="u", owner="o", R=6))
        with self.assertRaises(pikepdf.PasswordError):
            PdfStampEngine.watermark(encrypted.getvalue(), watermark_spec())
        with self.assertRaises(ValueError):
            PdfStampEngine.watermark(pdf_bytes(pikepdf.new()), watermark_spec())

    def test_bundled_font_path_coverage_is_checked_when_the_file_exists(self):
        tamil = "assets/fonts/NotoSansTamil-Regular.ttf"
        with mock.patch.object(PdfStampEngine, "WATERMARK_FONT_PATH", tamil):
            name, covers = PdfStampEngine._font()
            self.assertTrue(name.startswith("OfficeKitWatermarkSans"))
            self.assertTrue(covers("அ"))
            self.assertFalse(covers("\U0001F600"))
        # The default bundled font keeps its own registration, so the injected Tamil file cannot shadow it.
        default_name, default_covers = PdfStampEngine._font()
        self.assertNotEqual(default_name, name)
        self.assertTrue(default_covers("é"))
        self.assertFalse(default_covers("அ"))


def ink_size(image):
    """Width and height of the dark ink on the rendered page."""
    ink = image.convert("L").point(lambda value: 255 if value < 128 else 0)
    left, top, right, bottom = ink.getbbox()
    return right - left, bottom - top


class WatermarkOrientationTests(unittest.TestCase):
    def rendered_ink(self, source, angle):
        spec = watermark_spec(text="WWWWWWWW", color="#000000", opacity=100, angle=angle, font_size=40)
        return ink_size(render_page(PdfStampEngine.watermark(source, spec), 0))

    def test_angle_turns_the_text_and_zero_keeps_it_level(self):
        source = pdf_bytes(make_pdf([(400, 400)]))
        width, height = self.rendered_ink(source, 0)
        self.assertGreater(width, height * 2)
        for angle in (90, -90):
            with self.subTest(angle=angle):
                width, height = self.rendered_ink(source, angle)
                self.assertGreater(height, width * 2)

    def test_level_watermark_on_a_rotated_page_still_reads_level(self):
        # The page's own /Rotate must not turn an angle-0 watermark: it reads level on screen.
        source = pdf_bytes(make_pdf([(400, 400)], rotate=90))
        width, height = self.rendered_ink(source, 0)
        self.assertGreater(width, height * 2)


class WatermarkImageTests(unittest.TestCase):
    def test_png_alpha_is_kept_as_smask(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        png = make_png(60, 40, color=(0, 0, 0), alpha=128)
        output = PdfStampEngine.watermark(source, watermark_spec(kind="image", text=None, image=png))
        with pikepdf.open(io.BytesIO(output)) as pdf:
            found = False
            for page in pdf.pages:
                for value in (page.obj.get("/Resources", {}).get("/XObject") or {}).values():
                    nested = value.get("/Resources") or {}
                    for image in (nested.get("/XObject") or {}).values():
                        if "/SMask" in image:
                            found = True
            self.assertTrue(found)

    def test_image_limits_and_format(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        spec = watermark_spec(kind="image", text=None, image=make_png(10, 10))
        with mock.patch.object(PdfStampEngine, "MAX_IMAGE_PIXELS", 50), self.assertRaises(PdfStampInputError):
            PdfStampEngine.watermark(source, spec)
        with mock.patch.object(PdfStampEngine, "MAX_IMAGE_BYTES", 10), self.assertRaises(PdfStampInputError):
            PdfStampEngine.watermark(source, spec)
        with self.assertRaises(PdfStampInputError):
            PdfStampEngine.watermark(source, watermark_spec(kind="image", text=None, image=b"GIF89a not used"))
        gif = io.BytesIO()
        Image.new("RGB", (4, 4)).save(gif, format="GIF")
        with self.assertRaises(PdfStampInputError):
            PdfStampEngine.watermark(source, watermark_spec(kind="image", text=None, image=gif.getvalue()))

    def test_image_watermark_with_jpeg_source(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        buffer = io.BytesIO()
        Image.new("RGB", (80, 40), (10, 200, 10)).save(buffer, format="JPEG")
        output = PdfStampEngine.watermark(source, watermark_spec(kind="image", text=None, image=buffer.getvalue()))
        self.assertTrue(output.startswith(b"%PDF"))


class WatermarkPreviewTests(unittest.TestCase):
    def test_preview_is_png_with_bounded_long_edge(self):
        source = pdf_bytes(make_pdf([(2000, 1000)]))
        png = PdfStampEngine.watermark_preview(source, watermark_spec(), 1)
        image = Image.open(io.BytesIO(png))
        self.assertEqual(image.format, "PNG")
        self.assertLessEqual(max(image.size), 800)

    def test_preview_page_and_size_limits(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        with self.assertRaises(ValueError):
            PdfStampEngine.watermark_preview(source, watermark_spec(), 2)
        with mock.patch.object(PdfStampEngine, "PREVIEW_MAX_BYTES", 10), self.assertRaises(ValueError):
            PdfStampEngine.watermark_preview(source, watermark_spec(), 1)

    def test_preview_page_zero_renders_first_landscape_page(self):
        source = pdf_bytes(make_pdf([(200, 300), (300, 200)]))
        png = PdfStampEngine.watermark_preview(source, watermark_spec(), 0)
        width, height = Image.open(io.BytesIO(png)).size
        self.assertGreater(width, height)
        portrait_only = pdf_bytes(make_pdf([(200, 300)]))
        with self.assertRaises(PdfOptionError):
            PdfStampEngine.watermark_preview(portrait_only, watermark_spec(), 0)


class PageNumberTests(unittest.TestCase):
    def test_formats_render_expected_labels(self):
        source = pdf_bytes(make_pdf([(300, 200)] * 3))
        cases = {
            "number": ({}, ["1", "2", "3"]),
            "page": ({"number_format": "page"}, ["Page 1", "Page 2", "Page 3"]),
            "page-of-total": ({"number_format": "page-of-total"}, ["Page 1 of 3", "Page 2 of 3", "Page 3 of 3"]),
            "roman-lower": ({"number_format": "roman-lower", "start": 2}, ["ii", "iii", "iv"]),
            "roman-upper": ({"number_format": "roman-upper", "start": 4}, ["IV", "V", "VI"]),
            "custom": ({"number_format": "custom", "template": "{n}/{total}"}, ["1/3", "2/3", "3/3"]),
        }
        for name, (overrides, expected) in cases.items():
            with self.subTest(format=name):
                output, _ = PdfStampEngine.page_numbers(source, number_spec(**overrides))
                texts = page_texts(output)
                for text, label in zip(texts, expected):
                    self.assertIn(label, text)

    def test_roman_helpers(self):
        self.assertEqual(_roman(1994), "MCMXCIV")
        self.assertEqual(_roman(3999), "MMMCMXCIX")
        with self.assertRaises(ValueError):
            _roman(0)

    def test_skipped_pages_with_start_offset(self):
        source = pdf_bytes(make_pdf([(300, 200)] * 4))
        output, _ = PdfStampEngine.page_numbers(source, number_spec(start=5, page_ranges="2-3"))
        texts = page_texts(output)
        self.assertIn("5", texts[1])
        self.assertIn("6", texts[2])
        self.assertNotIn("7", texts[1] + texts[2])
        skipped_output, _ = PdfStampEngine.page_numbers(source, number_spec(start=5, page_ranges="2-3",
                                                                            count_skipped=True))
        skipped = page_texts(skipped_output)
        self.assertIn("6", skipped[1])
        self.assertIn("7", skipped[2])

    def test_crop_box_offset_and_rotation_place_label_upright(self):
        pdf = make_pdf([(400, 300)], rotate=90)
        pdf.pages[0].obj.CropBox = pikepdf.Array([100, 50, 300, 250])
        source = pdf_bytes(pdf)
        output, _ = PdfStampEngine.page_numbers(source, number_spec(
            position="top-left", font_size=24, margin_mm=0, number_format="page"))
        before = render_page(source, 0)
        after = render_page(output, 0)
        left, top, right, bottom = changed_bbox(before, after)
        self.assertLess(left, after.size[0] * 0.5)
        self.assertLess(top, after.size[1] * 0.5)

    def test_overlap_pages_are_reported(self):
        pdf = make_pdf([(300, 200), (300, 200)])
        big = b"BT /F1 120 Tf 0 0 Td (XXXX) Tj ET"
        pdf.pages[0].obj.Contents = pdf.make_stream(big)
        source = pdf_bytes(pdf)
        _, overlaps = PdfStampEngine.page_numbers(source, number_spec(position="bottom-left", margin_mm=0))
        self.assertEqual(overlaps, [1])

    def test_no_overlap_on_clean_pages(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        _, overlaps = PdfStampEngine.page_numbers(source, number_spec(position="bottom-left"))
        self.assertEqual(overlaps, [])

    def test_preview_returns_png_and_overlaps(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        png, overlaps = PdfStampEngine.page_numbers_preview(source, number_spec(), 1)
        self.assertEqual(Image.open(io.BytesIO(png)).format, "PNG")
        self.assertEqual(overlaps, [])

    def test_validation_bounds(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        invalid = [
            number_spec(number_format="fancy"),
            number_spec(number_format="custom"),
            number_spec(number_format="custom", template="{bad}"),
            number_spec(number_format="custom", template="{n}" * 40),
            number_spec(template="{n}"),
            number_spec(start=-1),
            number_spec(start=10_000),
            number_spec(number_format="roman-upper", start=0),
            number_spec(number_format="roman-upper", start=4000),
            number_spec(position="middle"),
            number_spec(margin_mm=51),
            number_spec(font_size=5),
            number_spec(font_size=37),
        ]
        for spec in invalid:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                PdfStampEngine.page_numbers(source, spec)

    def test_roman_limit_crossed_by_sequence(self):
        source = pdf_bytes(make_pdf([(300, 200)] * 2))
        with self.assertRaises(ValueError):
            PdfStampEngine.page_numbers(source, number_spec(number_format="roman-lower", start=3999))

    def test_uncovered_template_glyphs_are_refused(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        with self.assertRaises(PdfStampInputError):
            PdfStampEngine.page_numbers(source, number_spec(number_format="custom", template="第{n}页"))

    def test_covered_unicode_template_is_accepted(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        output, _ = PdfStampEngine.page_numbers(source, number_spec(number_format="custom", template="Página {n}"))
        self.assertIn("Página 1", page_texts(output)[0])

    def test_malformed_encrypted_empty_and_output_cap(self):
        with self.assertRaises(ValueError):
            PdfStampEngine.page_numbers(b"", number_spec())
        with self.assertRaises(pikepdf.PdfError):
            PdfStampEngine.page_numbers(b"%PDF nope", number_spec())
        encrypted = io.BytesIO()
        make_pdf([(300, 200)]).save(encrypted, encryption=pikepdf.Encryption(user="u", owner="o", R=6))
        with self.assertRaises(pikepdf.PasswordError):
            PdfStampEngine.page_numbers(encrypted.getvalue(), number_spec())
        with self.assertRaises(ValueError):
            PdfStampEngine.page_numbers(pdf_bytes(pikepdf.new()), number_spec())
        source = pdf_bytes(make_pdf([(300, 200)]))
        snapshot = bytes(source)
        with mock.patch.object(PdfStampEngine, "MAX_OUTPUT_BYTES", 64), \
                self.assertRaises(PdfOutputLimitError):
            PdfStampEngine.page_numbers(source, number_spec())
        self.assertEqual(source, snapshot)


class FormatRangesTests(unittest.TestCase):
    def test_compact_ranges_and_limit(self):
        self.assertEqual(format_ranges([1, 2, 3, 5]), "1-3,5")
        self.assertEqual(format_ranges([]), "")
        self.assertEqual(format_ranges([4, 1, 2]), "1-2,4")
        cut = format_ranges(list(range(1, 400, 2)), limit=20)
        self.assertLessEqual(len(cut), 20)
        self.assertTrue(cut.endswith("…"))


class PageNumberCountParityTests(unittest.TestCase):
    """ARCH-13, CR-11: the slice's dock count (numberedPageCount) must agree with the engine's labelled pages for
    every row of tests/pdf_page_range_counts.json. Refused rows are the selections the server never labels; the
    slice's count for them is the defensive clip and de-duplicate result, asserted by the node test on the same table."""

    FIXTURE = Path(__file__).with_name("pdf_page_range_counts.json")

    def test_engine_labels_the_count_the_slice_shows(self):
        rows = json.loads(self.FIXTURE.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(rows), 6)
        for row in rows:
            with self.subTest(selection=row["selection"], total=row["total"]):
                if row["valid"]:
                    self.assertEqual(len(selected_indexes(row["selection"], row["total"])), row["labelled"])
                else:
                    with self.assertRaises(PdfOptionError):
                        selected_indexes(row["selection"], row["total"])


if __name__ == "__main__":
    unittest.main()
