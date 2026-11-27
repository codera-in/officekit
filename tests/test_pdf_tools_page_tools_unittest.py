import io
import unittest
from unittest import mock

import pikepdf
import pypdfium2 as pdfium

from officekit.engines.engine_pdf_page_tools import PageToolsEngine
from officekit.engines.engine_pdf_security import PdfOutputLimitError
from officekit.engines.engine_pdf_tool_common import count_pages, page_rotation
from tests.pdf_tool_fixtures import make_pdf, pdf_bytes, render_page


def open_out(content):
    return pikepdf.open(io.BytesIO(content))


BODY_AND_INK = "BT /F1 24 Tf 20 20 Td (BODY 1) Tj ET 1 0 0 rg 200 200 80 80 re f"


def is_red(pixel):
    red, green, blue = pixel
    return red > 150 and green < 100 and blue < 100


def red_pixels(image):
    rgb = image.convert("RGB")
    return [(x, y) for y in range(rgb.height) for x in range(rgb.width) if is_red(rgb.getpixel((x, y)))]


def extract_text(content, index=0):
    document = pdfium.PdfDocument(content)
    try:
        return document[index].get_textpage().get_text_range()
    finally:
        document.close()


def red_centroid(image):
    points = red_pixels(image)
    assert points, "no red ink rendered"
    return sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points)


class RotatePagesTests(unittest.TestCase):
    def test_rotates_selected_pages_and_leaves_others(self):
        source = pdf_bytes(make_pdf([(300, 200), (200, 300), (300, 200)]))
        output, affected = PageToolsEngine.rotate_pages(source, 90, "1,3")
        self.assertEqual(affected, 2)
        with open_out(output) as pdf:
            self.assertEqual([page_rotation(page.obj) for page in pdf.pages], [90, 0, 90])

    def test_empty_selection_means_all_pages(self):
        source = pdf_bytes(make_pdf([(300, 200), (200, 300)]))
        output, affected = PageToolsEngine.rotate_pages(source, 270, "")
        self.assertEqual(affected, 2)
        with open_out(output) as pdf:
            self.assertEqual([page_rotation(page.obj) for page in pdf.pages], [270, 270])

    def test_inherited_rotate_is_resolved_before_relative_rotation(self):
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(300, 200))
        pdf.add_blank_page(page_size=(300, 200))
        pdf.Root.Pages.Rotate = 90
        source = pdf_bytes(pdf)
        output, _ = PageToolsEngine.rotate_pages(source, 90, "")
        with open_out(output) as result:
            self.assertEqual([page_rotation(page.obj) for page in result.pages], [180, 180])

    def test_apply_twice_and_four_quarter_turns(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        once, _ = PageToolsEngine.rotate_pages(source, 90, "")
        twice, _ = PageToolsEngine.rotate_pages(once, 90, "")
        with open_out(twice) as pdf:
            self.assertEqual(page_rotation(pdf.pages[0].obj), 180)
        current = source
        for _ in range(4):
            current, _ = PageToolsEngine.rotate_pages(current, 90, "")
        with open_out(current) as pdf:
            self.assertEqual(page_rotation(pdf.pages[0].obj), 0)

    def test_rendered_orientation_swaps_width_and_height(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        output, _ = PageToolsEngine.rotate_pages(source, 90, "")
        image = render_page(output, 0)
        self.assertEqual(image.size, (200, 300))

    def test_content_stream_bytes_are_unchanged(self):
        source = pdf_bytes(make_pdf([(300, 200)], text_prefix="KEEP "))
        with open_out(source) as before:
            before_bytes = before.pages[0].Contents.read_bytes()
        output, _ = PageToolsEngine.rotate_pages(source, 180, "")
        with open_out(output) as after:
            self.assertEqual(after.pages[0].Contents.read_bytes(), before_bytes)

    def test_mixed_sizes_keep_page_boxes(self):
        source = pdf_bytes(make_pdf([(300, 200), (200, 400)]))
        output, _ = PageToolsEngine.rotate_pages(source, 90, "")
        with open_out(output) as pdf:
            self.assertEqual([float(page.mediabox[2]) for page in pdf.pages], [300, 200])

    def test_source_bytes_are_not_mutated(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        snapshot = bytes(source)
        PageToolsEngine.rotate_pages(source, 90, "")
        self.assertEqual(source, snapshot)

    def test_invalid_angles_and_ranges_are_rejected(self):
        source = pdf_bytes(make_pdf([(300, 200), (300, 200)]))
        for angle in (0, 45, 360, True, "90"):
            with self.subTest(angle=angle), self.assertRaises(ValueError):
                PageToolsEngine.rotate_pages(source, angle, "")
        for ranges in ("3", "2-1", "1,1", "0", "1-9", "1 2"):
            with self.subTest(ranges=ranges), self.assertRaises(ValueError):
                PageToolsEngine.rotate_pages(source, 90, ranges)

    def test_malformed_encrypted_and_empty_inputs(self):
        with self.assertRaises(ValueError):
            PageToolsEngine.rotate_pages(b"", 90, "")
        with self.assertRaises(pikepdf.PdfError):
            PageToolsEngine.rotate_pages(b"not a pdf", 90, "")
        encrypted = io.BytesIO()
        pdf = make_pdf([(300, 200)])
        pdf.save(encrypted, encryption=pikepdf.Encryption(user="secret", owner="owner", R=6))
        with self.assertRaises(pikepdf.PasswordError):
            PageToolsEngine.rotate_pages(encrypted.getvalue(), 90, "")
        empty = pdf_bytes(pikepdf.new())
        with self.assertRaises(ValueError):
            PageToolsEngine.rotate_pages(empty, 90, "")

    def test_output_cap_stops_serialisation(self):
        source = pdf_bytes(make_pdf([(300, 200)] * 3))
        with mock.patch.object(PageToolsEngine, "MAX_OUTPUT_BYTES", 64), \
                self.assertRaises(PdfOutputLimitError):
            PageToolsEngine.rotate_pages(source, 90, "")

    def test_page_count_helper(self):
        self.assertEqual(count_pages(pdf_bytes(make_pdf([(300, 200)] * 4))), 4)


class ResizePagesTests(unittest.TestCase):
    def test_target_size_presets_and_unit_conversion(self):
        self.assertEqual(PageToolsEngine.target_size("a4"), (595.2756, 841.8898))
        self.assertEqual(PageToolsEngine.target_size("letter"), (612.0, 792.0))
        self.assertAlmostEqual(PageToolsEngine.target_size("custom", "210", "297", "mm")[0], 595.2756, places=3)
        self.assertAlmostEqual(PageToolsEngine.target_size("custom", "8.5", "11", "in")[1], 792.0, places=3)
        self.assertEqual(PageToolsEngine.target_size("custom", "300", "400", "pt"), (300.0, 400.0))
        with self.assertRaises(ValueError):
            PageToolsEngine.target_size("custom", "71.9", "400", "pt")
        with self.assertRaises(ValueError):
            PageToolsEngine.target_size("custom", "14401", "400", "pt")
        with self.assertRaises(ValueError):
            PageToolsEngine.target_size("custom", None, "400", "pt")
        with self.assertRaises(ValueError):
            PageToolsEngine.target_size("nope")

    def test_scale_to_fit_sets_media_and_crop_box_to_target(self):
        source = pdf_bytes(make_pdf([(612, 792)]))
        output, minimum = PageToolsEngine.resize_pages(
            source, target=(420.0, 595.0), orientation="keep", mode="scale", anchor="center", page_ranges="")
        with open_out(output) as pdf:
            page = pdf.pages[0]
            self.assertEqual([float(v) for v in page.mediabox], [0, 0, 420, 595])
            self.assertEqual([float(v) for v in page.cropbox], [0, 0, 420, 595])
        self.assertAlmostEqual(minimum, min(420 / 612, 595 / 792), places=6)

    def test_scale_to_fit_preserves_aspect_and_renders_target_size(self):
        source = pdf_bytes(make_pdf([(400, 200)]))
        output, minimum = PageToolsEngine.resize_pages(
            source, target=(300.0, 300.0), orientation="keep", mode="scale", anchor="center", page_ranges="")
        self.assertAlmostEqual(minimum, 0.75, places=6)
        self.assertEqual(render_page(output, 0).size, (300, 300))

    def test_canvas_mode_keeps_scale_one_and_anchor_offsets_content(self):
        source = pdf_bytes(make_pdf([(200, 100)], text_prefix="X"))
        output, minimum = PageToolsEngine.resize_pages(
            source, target=(400.0, 300.0), orientation="keep", mode="canvas", anchor="top-right", page_ranges="")
        self.assertEqual(minimum, 1.0)
        with open_out(output) as pdf:
            stream = pdf.pages[0].Contents.read_bytes().decode("ascii")
        self.assertIn("1.000000 0 0 1.000000 200.000000 200.000000 cm", stream)

    def test_orientation_rules(self):
        landscape_source = pdf_bytes(make_pdf([(600, 300)]))
        portrait_source = pdf_bytes(make_pdf([(300, 600)]))
        output, _ = PageToolsEngine.resize_pages(
            portrait_source, target=(400.0, 500.0), orientation="keep", mode="scale", anchor="center", page_ranges="")
        with open_out(output) as pdf:
            self.assertEqual(float(pdf.pages[0].mediabox[2]), 400)
        output, _ = PageToolsEngine.resize_pages(
            landscape_source, target=(400.0, 500.0), orientation="keep", mode="scale", anchor="center", page_ranges="")
        with open_out(output) as pdf:
            self.assertEqual(float(pdf.pages[0].mediabox[2]), 500)
        output, _ = PageToolsEngine.resize_pages(
            portrait_source, target=(400.0, 500.0), orientation="landscape", mode="scale", anchor="center",
            page_ranges="")
        with open_out(output) as pdf:
            self.assertEqual(float(pdf.pages[0].mediabox[2]), 500)

    def test_rotated_page_target_is_displayed_size(self):
        source = pdf_bytes(make_pdf([(600, 300)], rotate=90))
        output, _ = PageToolsEngine.resize_pages(
            source, target=(300.0, 400.0), orientation="portrait", mode="scale", anchor="center", page_ranges="")
        self.assertEqual(render_page(output, 0).size, (300, 400))

    def test_annotation_rect_moves_with_content(self):
        pdf = make_pdf([(600, 800)])
        annotation = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Text, Rect=pikepdf.Array([100, 100, 200, 200]),
            QuadPoints=pikepdf.Array([100, 200, 200, 200, 100, 100, 200, 100])))
        pdf.pages[0].obj.Annots = pikepdf.Array([annotation])
        source = pdf_bytes(pdf)
        output, minimum = PageToolsEngine.resize_pages(
            source, target=(300.0, 400.0), orientation="keep", mode="scale", anchor="center", page_ranges="")
        self.assertAlmostEqual(minimum, 0.5, places=6)
        with open_out(output) as result:
            rect = [float(v) for v in result.pages[0].Annots[0].Rect]
        self.assertEqual(rect, [50.0, 50.0, 100.0, 100.0])

    def test_selected_pages_only(self):
        source = pdf_bytes(make_pdf([(300, 200), (300, 200)]))
        output, _ = PageToolsEngine.resize_pages(
            source, target=(100.0, 100.0), orientation="keep", mode="scale", anchor="center", page_ranges="2")
        with open_out(output) as pdf:
            self.assertEqual(float(pdf.pages[0].mediabox[2]), 300)
            self.assertEqual(float(pdf.pages[1].mediabox[2]), 100)

    def test_invalid_mode_anchor_orientation_and_pages(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        with self.assertRaises(ValueError):
            PageToolsEngine.resize_pages(source, target=(300.0, 300.0), orientation="sideways", mode="scale",
                                         anchor="center", page_ranges="")
        with self.assertRaises(ValueError):
            PageToolsEngine.resize_pages(source, target=(300.0, 300.0), orientation="keep", mode="stretch",
                                         anchor="center", page_ranges="")
        with self.assertRaises(ValueError):
            PageToolsEngine.resize_pages(source, target=(300.0, 300.0), orientation="keep", mode="canvas",
                                         anchor="middle-ish", page_ranges="")
        with self.assertRaises(ValueError):
            PageToolsEngine.resize_pages(source, target=(300.0, 300.0), orientation="keep", mode="scale",
                                         anchor="center", page_ranges="5")

    def test_output_cap_and_source_unchanged(self):
        source = pdf_bytes(make_pdf([(300, 200)] * 2))
        snapshot = bytes(source)
        with mock.patch.object(PageToolsEngine, "MAX_OUTPUT_BYTES", 64), \
                self.assertRaises(PdfOutputLimitError):
            PageToolsEngine.resize_pages(source, target=(300.0, 300.0), orientation="keep", mode="scale",
                                         anchor="center", page_ranges="")
        self.assertEqual(source, snapshot)

    def test_scale_resize_keeps_page_text_and_rendered_ink(self):
        source = pdf_bytes(make_pdf([(400, 400)], content=lambda i, w, h: BODY_AND_INK))
        output, _ = PageToolsEngine.resize_pages(
            source, target=(300.0, 300.0), orientation="keep", mode="scale", anchor="center", page_ranges="")
        self.assertIn("BODY 1", extract_text(output))
        # 80 x 80 user units scaled by 0.75 is a 60 x 60 pixel square.
        self.assertGreater(len(red_pixels(render_page(output, 0))), 3000)

    def test_canvas_resize_keeps_page_text_and_rendered_ink(self):
        source = pdf_bytes(make_pdf([(400, 400)], content=lambda i, w, h: BODY_AND_INK))
        output, _ = PageToolsEngine.resize_pages(
            source, target=(500.0, 500.0), orientation="keep", mode="canvas", anchor="center", page_ranges="")
        self.assertIn("BODY 1", extract_text(output))
        self.assertGreater(len(red_pixels(render_page(output, 0))), 5000)

    def test_scale_resize_of_rotated_page_keeps_displayed_orientation(self):
        # /Rotate 90 shows the raw bottom-left corner at the displayed top-left.
        source = pdf_bytes(make_pdf([(300, 200)], rotate=90, content=lambda i, w, h: "1 0 0 rg 0 0 40 40 re f"))
        output, _ = PageToolsEngine.resize_pages(
            source, target=(300.0, 400.0), orientation="keep", mode="scale", anchor="center", page_ranges="")
        image = render_page(output, 0)
        self.assertEqual(image.size, (300, 400))
        centre_x, centre_y = red_centroid(image)
        self.assertLess(centre_x, 150)
        self.assertLess(centre_y, 200)

    def test_canvas_top_left_anchor_lands_at_displayed_top_left_for_every_rotation(self):
        # The square sits where the source's displayed top-left corner is, for each /Rotate.
        corners = {0: (0, 160), 90: (0, 0), 180: (360, 0), 270: (360, 160)}
        for rotation, (x0, y0) in corners.items():
            with self.subTest(rotation=rotation):
                source = pdf_bytes(make_pdf([(400, 200)], rotate=rotation,
                                            content=lambda i, w, h, x0=x0, y0=y0: f"1 0 0 rg {x0} {y0} 40 40 re f"))
                output, _ = PageToolsEngine.resize_pages(
                    source, target=(300.0, 400.0), orientation="keep", mode="canvas", anchor="top-left",
                    page_ranges="")
                centre_x, centre_y = red_centroid(render_page(output, 0))
                self.assertLess(centre_x, 40)
                self.assertLess(centre_y, 40)


if __name__ == "__main__":
    unittest.main()
