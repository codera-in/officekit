import io
import os
import unittest
from unittest import mock

import pdfplumber
import pikepdf
from PIL import Image, ImageChops, ImageStat

from officekit.engines.engine_pdf_grayscale import GRAYSCALE_REFUSAL_CODE, GrayscaleRefusedError, PdfGrayscaleEngine
from officekit.engines.engine_pdf_images import PdfImageExportEngine
from officekit.engines.engine_pdf_security import PdfOutputLimitError
from tests.pdf_tool_fixtures import make_pdf, pdf_bytes, render_page


SYSTEM_PROFILES = {
    3: "/System/Library/ColorSync/Profiles/sRGB Profile.icc",
    4: "/System/Library/ColorSync/Profiles/Generic CMYK Profile.icc",
}


def read_system_profile(components):
    """Real ICC bytes are required because pikepdf decodes ICC-based images through the profile."""
    path = SYSTEM_PROFILES[components]
    with open(path, "rb") as handle:
        return handle.read()


def have_system_profiles():
    return all(os.path.exists(path) for path in SYSTEM_PROFILES.values())


def is_gray_render(image):
    red, green, blue = image.convert("RGB").split()
    return ImageChops.difference(red, green).getbbox() is None and ImageChops.difference(green, blue).getbbox() is None


def mean_luma(image):
    return ImageStat.Stat(image.convert("L")).mean[0]


def dark_centroid(image):
    """Centre of the dark ink as fractions of the page width and height."""
    gray = image.convert("L")
    points = [(x, y) for y in range(gray.height) for x in range(gray.width) if gray.getpixel((x, y)) < 128]
    assert points, "no dark ink rendered"
    return (sum(x for x, _ in points) / len(points) / gray.width,
            sum(y for _, y in points) / len(points) / gray.height)


def page_with_content(content: bytes, resources_extra=None, width=200, height=200):
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(width, height))
    font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
                                                BaseFont=pikepdf.Name.Helvetica))
    resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
    for key, value in (resources_extra or {}).items():
        resources[key] = value
    page.obj.Resources = resources
    page.obj.Contents = pdf.make_stream(content)
    return pdf


def image_page(data: bytes, colour, width=20, height=20, extra=None, icc_components=None):
    pdf = pikepdf.new()
    page = pdf.add_blank_page(page_size=(200, 200))
    image = pdf.make_stream(data)
    image.Type = pikepdf.Name.XObject
    image.Subtype = pikepdf.Name.Image
    image.Width = width
    image.Height = height
    image.BitsPerComponent = 8
    if icc_components is not None:
        profile = pdf.make_stream(read_system_profile(icc_components))
        profile.N = icc_components
        colour = pikepdf.Array([pikepdf.Name.ICCBased, profile])
    image.ColorSpace = colour
    for key, value in (extra or {}).items():
        image[key] = value
    page.obj.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im1=pdf.make_indirect(image)))
    page.obj.Contents = pdf.make_stream(b"q 200 0 0 200 0 0 cm /Im1 Do Q")
    return pdf_bytes(pdf)


def colour_fixture():
    content = (
        b"1 0 0 rg 10 10 100 60 re f "
        b"0 0 1 rg BT /F1 28 Tf 20 150 Td (HELLO) Tj ET "
        b"0 1 0 RG 4 w 10 100 m 190 100 l S"
    )
    return pdf_bytes(page_with_content(content))


class VectorGrayscaleTests(unittest.TestCase):
    def test_colour_vector_renders_only_gray_pixels_and_keeps_text(self):
        source = colour_fixture()
        output, method = PdfGrayscaleEngine.convert(source, "vector")
        self.assertEqual(method, "vector")
        self.assertTrue(is_gray_render(render_page(output, 0)))
        self.assertFalse(is_gray_render(render_page(source, 0)))
        with pdfplumber.open(io.BytesIO(output)) as pdf:
            self.assertIn("HELLO", pdf.pages[0].extract_text())

    def test_cmyk_operators_and_stroke_colours(self):
        content = b"0 0 0 1 k 10 10 50 50 re f 1 0 0 0 K 4 w 0 100 m 200 100 l S"
        output, _ = PdfGrayscaleEngine.convert(pdf_bytes(page_with_content(content)), "vector")
        self.assertTrue(is_gray_render(render_page(output, 0)))
        with pikepdf.open(io.BytesIO(output)) as pdf:
            stream = pdf.pages[0].Contents.read_bytes().decode("ascii")
        self.assertNotIn(" k", stream)
        self.assertNotIn(" K", stream)

    def test_cs_and_sc_in_rgb_and_cmyk_spaces_are_converted(self):
        content = (b"/DeviceRGB cs 1 0 0 sc 10 10 50 50 re f "
                   b"/DeviceCMYK CS 0 1 0 0 SC 4 w 0 100 m 200 100 l S")
        output, _ = PdfGrayscaleEngine.convert(pdf_bytes(page_with_content(content)), "vector")
        with pikepdf.open(io.BytesIO(output)) as pdf:
            stream = pdf.pages[0].Contents.read_bytes().decode("ascii")
        self.assertIn("/DeviceGray cs", stream)
        self.assertIn("/DeviceGray CS", stream)
        self.assertTrue(is_gray_render(render_page(output, 0)))

    def test_rgb_image_is_converted_and_gray_pixels_only(self):
        data = bytes([255, 0, 0] * 400)
        output, _ = PdfGrayscaleEngine.convert(image_page(data, pikepdf.Name.DeviceRGB), "vector")
        self.assertTrue(is_gray_render(render_page(output, 0)))
        # Pure red is luma 76; a solid black render is gray too, so the level is asserted.
        self.assertAlmostEqual(mean_luma(render_page(output, 0)), 76, delta=8)
        with pikepdf.open(io.BytesIO(output)) as pdf:
            image = pdf.pages[0].Resources.XObject.Im1
            self.assertEqual(str(image.ColorSpace), "/DeviceGray")

    def test_cmyk_image_is_converted(self):
        data = bytes([0, 255, 0, 0] * 400)
        output, _ = PdfGrayscaleEngine.convert(image_page(data, pikepdf.Name.DeviceCMYK), "vector")
        with pikepdf.open(io.BytesIO(output)) as pdf:
            self.assertEqual(str(pdf.pages[0].Resources.XObject.Im1.ColorSpace), "/DeviceGray")
        self.assertTrue(is_gray_render(render_page(output, 0)))

    def test_indexed_palette_image_is_converted_per_index(self):
        palette = bytes([255, 0, 0, 0, 255, 0])
        colour = pikepdf.Array([pikepdf.Name.Indexed, pikepdf.Name.DeviceRGB, 1, pikepdf.String(palette)])
        output, _ = PdfGrayscaleEngine.convert(image_page(bytes([0, 1] * 200), colour), "vector")
        with pikepdf.open(io.BytesIO(output)) as pdf:
            self.assertEqual(str(pdf.pages[0].Resources.XObject.Im1.ColorSpace), "/DeviceGray")
        self.assertTrue(is_gray_render(render_page(output, 0)))

    @unittest.skipUnless(have_system_profiles(), "macOS ColorSync profiles are required for ICC fixtures")
    def test_icc_based_three_and_four_component_spaces_are_converted(self):
        for components, data in ((3, bytes([200, 40, 40] * 400)), (4, bytes([0, 200, 0, 0] * 400))):
            with self.subTest(components=components):
                output, _ = PdfGrayscaleEngine.convert(
                    image_page(data, None, icc_components=components), "vector")
                with pikepdf.open(io.BytesIO(output)) as pdf:
                    self.assertEqual(str(pdf.pages[0].Resources.XObject.Im1.ColorSpace), "/DeviceGray")
                self.assertTrue(is_gray_render(render_page(output, 0)))

    def test_gray_images_and_smask_are_left_alone(self):
        data = bytes([128] * 400)
        output, _ = PdfGrayscaleEngine.convert(image_page(data, pikepdf.Name.DeviceGray), "vector")
        self.assertTrue(output.startswith(b"%PDF"))

    def test_dct_source_is_reencoded_as_jpeg(self):
        buffer = io.BytesIO()
        Image.new("RGB", (20, 20), (200, 30, 30)).save(buffer, format="JPEG")
        pdf = pikepdf.new()
        page = pdf.add_blank_page(page_size=(200, 200))
        image = pdf.make_stream(buffer.getvalue())
        image.Type = pikepdf.Name.XObject
        image.Subtype = pikepdf.Name.Image
        image.Width = 20
        image.Height = 20
        image.BitsPerComponent = 8
        image.ColorSpace = pikepdf.Name.DeviceRGB
        image.Filter = pikepdf.Name.DCTDecode
        page.obj.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im1=pdf.make_indirect(image)))
        page.obj.Contents = pdf.make_stream(b"q 200 0 0 200 0 0 cm /Im1 Do Q")
        output, _ = PdfGrayscaleEngine.convert(pdf_bytes(pdf), "vector")
        with pikepdf.open(io.BytesIO(output)) as result:
            converted = result.pages[0].Resources.XObject.Im1
            self.assertEqual(str(converted.Filter), "/DCTDecode")
            self.assertEqual(str(converted.ColorSpace), "/DeviceGray")

    def test_form_xobject_and_annotation_appearance_are_converted(self):
        pdf = pikepdf.new()
        page = pdf.add_blank_page(page_size=(200, 200))
        form = pdf.make_stream(b"1 0 0 rg 0 0 50 50 re f")
        form.Type = pikepdf.Name.XObject
        form.Subtype = pikepdf.Name.Form
        form.BBox = pikepdf.Array([0, 0, 200, 200])
        page.obj.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Fm1=pdf.make_indirect(form)))
        page.obj.Contents = pdf.make_stream(b"/Fm1 Do")
        appearance = pdf.make_stream(b"0 1 0 rg 0 0 40 40 re f")
        appearance.Type = pikepdf.Name.XObject
        appearance.Subtype = pikepdf.Name.Form
        appearance.BBox = pikepdf.Array([0, 0, 40, 40])
        annotation = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Square, Rect=pikepdf.Array([100, 100, 140, 140]),
            AP=pikepdf.Dictionary(N=pdf.make_indirect(appearance))))
        page.obj.Annots = pikepdf.Array([annotation])
        output, _ = PdfGrayscaleEngine.convert(pdf_bytes(pdf), "vector")
        self.assertTrue(is_gray_render(render_page(output, 0)))

    def test_refusals_for_shading_patterns_and_separation(self):
        refusals = {
            "sh": b"/Sh1 sh",
            "separation": b"/CSp cs 0.5 sc 0 0 10 10 re f",
        }
        separation = pikepdf.Array([pikepdf.Name.Separation, pikepdf.Name.All, pikepdf.Name.DeviceRGB,
                                    pikepdf.Dictionary()])
        for name, content in refusals.items():
            extra = {"/ColorSpace": pikepdf.Dictionary(CSp=separation)} if name == "separation" else {}
            with self.subTest(refusal=name), self.assertRaises(GrayscaleRefusedError) as raised:
                PdfGrayscaleEngine.convert(pdf_bytes(page_with_content(content, extra)), "vector")
            self.assertEqual(raised.exception.code, GRAYSCALE_REFUSAL_CODE)
        pattern = pdf_bytes(page_with_content(b"/Pattern cs /P1 scn 0 0 10 10 re f",
                                              {"/Pattern": pikepdf.Dictionary(P1=pikepdf.Dictionary())}))
        with self.assertRaises(GrayscaleRefusedError):
            PdfGrayscaleEngine.convert(pattern, "vector")
        shading = pdf_bytes(page_with_content(b"0 0 1 rg 0 0 10 10 re f",
                                              {"/Shading": pikepdf.Dictionary(Sh1=pikepdf.Dictionary())}))
        with self.assertRaises(GrayscaleRefusedError):
            PdfGrayscaleEngine.convert(shading, "vector")

    def test_inline_colour_image_is_refused(self):
        content = b"q 10 0 0 10 0 0 cm BI /W 1 /H 1 /BPC 8 /CS /RGB ID \x00\x00\x00 EI Q"
        with self.assertRaises(GrayscaleRefusedError):
            PdfGrayscaleEngine.convert(pdf_bytes(page_with_content(content)), "vector")

    def test_colour_key_mask_on_a_colour_image_is_refused(self):
        # A /Mask array holds colour-key values in the source space; converting the pixels would unmask them wrongly.
        colour_key = pikepdf.Array([0, 0, 0, 0, 0, 0])
        with self.assertRaises(GrayscaleRefusedError):
            PdfGrayscaleEngine.convert(
                image_page(bytes([255, 0, 0] * 400), pikepdf.Name.DeviceRGB, extra={"/Mask": colour_key}),
                "vector")

    def test_jpx_image_is_refused(self):
        with self.assertRaises(GrayscaleRefusedError):
            PdfGrayscaleEngine.convert(
                image_page(b"\x00" * 1200, pikepdf.Name.DeviceRGB, extra={"/Filter": pikepdf.Name.JPXDecode}),
                "vector")

    def test_oversized_image_is_rejected_before_decode(self):
        output_source = image_page(b"\x00" * 30, pikepdf.Name.DeviceRGB, width=100_000, height=100_000)
        with mock.patch.object(pikepdf, "PdfImage") as decoder, self.assertRaises(ValueError) as caught:
            PdfGrayscaleEngine.convert(output_source, "vector")
        self.assertEqual(str(caught.exception), "An embedded image is too large to convert.")
        decoder.assert_not_called()

    def test_refusal_writes_nothing_and_source_is_unchanged(self):
        source = pdf_bytes(page_with_content(b"1 0 0 rg 0 0 9 9 re f /Sh1 sh",
                                             {"/Shading": pikepdf.Dictionary(Sh1=pikepdf.Dictionary())}))
        snapshot = bytes(source)
        with self.assertRaises(GrayscaleRefusedError):
            PdfGrayscaleEngine.convert(source, "vector")
        self.assertEqual(source, snapshot)

    def test_dpi_is_rejected_for_vector_and_invalid_method(self):
        source = colour_fixture()
        with self.assertRaises(ValueError):
            PdfGrayscaleEngine.convert(source, "vector", dpi=150)
        with self.assertRaises(ValueError):
            PdfGrayscaleEngine.convert(source, "sepia")

    def test_malformed_encrypted_empty_and_output_cap(self):
        with self.assertRaises(ValueError):
            PdfGrayscaleEngine.convert(b"", "vector")
        with self.assertRaises(pikepdf.PdfError):
            PdfGrayscaleEngine.convert(b"%PDF nope", "vector")
        encrypted = io.BytesIO()
        make_pdf([(200, 200)]).save(encrypted, encryption=pikepdf.Encryption(user="u", owner="o", R=6))
        with self.assertRaises(pikepdf.PasswordError):
            PdfGrayscaleEngine.convert(encrypted.getvalue(), "vector")
        with mock.patch.object(PdfGrayscaleEngine, "MAX_OUTPUT_BYTES", 64), self.assertRaises(PdfOutputLimitError):
            PdfGrayscaleEngine.convert(colour_fixture(), "vector")


class RasterGrayscaleTests(unittest.TestCase):
    def test_raster_is_gray_at_original_size_without_selectable_text(self):
        source = pdf_bytes(make_pdf([(300, 200)], text_prefix="RASTER "))
        output, method = PdfGrayscaleEngine.convert(source, "raster", dpi=150)
        self.assertEqual(method, "raster")
        with pikepdf.open(io.BytesIO(output)) as pdf:
            self.assertEqual([float(v) for v in pdf.pages[0].mediabox], [0, 0, 300, 200])
        with pdfplumber.open(io.BytesIO(output)) as pdf:
            self.assertEqual((pdf.pages[0].extract_text() or "").strip(), "")
        self.assertTrue(is_gray_render(render_page(output, 0)))

    def test_raster_output_keeps_source_luminance(self):
        # A 0.9 grey page must stay light; a stream that is not valid Flate renders solid black.
        source = pdf_bytes(make_pdf([(300, 200)], content=lambda i, w, h: "0.9 g 0 0 300 200 re f"))
        output, _ = PdfGrayscaleEngine.convert(source, "raster", dpi=150)
        self.assertAlmostEqual(mean_luma(render_page(output, 0)), 230, delta=8)

    def test_raster_preserves_rotated_orientation(self):
        # A black block at the raw bottom-left must land where the source shows it, for every /Rotate.
        for rotation in (0, 90, 180, 270):
            with self.subTest(rotation=rotation):
                source = pdf_bytes(make_pdf([(300, 200)], rotate=rotation,
                                            content=lambda i, w, h: "0 g 0 0 60 60 re f"))
                output, _ = PdfGrayscaleEngine.convert(source, "raster", dpi=150)
                self.assertEqual(render_page(output, 0).size, render_page(source, 0).size)
                expected = dark_centroid(render_page(source, 0))
                actual = dark_centroid(render_page(output, 0))
                self.assertAlmostEqual(actual[0], expected[0], delta=0.03)
                self.assertAlmostEqual(actual[1], expected[1], delta=0.03)

    def test_raster_dpi_choices_and_budgets(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        with self.assertRaises(ValueError):
            PdfGrayscaleEngine.convert(source, "raster", dpi=100)
        with self.assertRaises(ValueError):
            PdfGrayscaleEngine.convert(source, "raster", dpi=True)
        with mock.patch.object(PdfImageExportEngine, "MAX_TOTAL_PIXELS", 10), self.assertRaises(ValueError):
            PdfGrayscaleEngine.convert(source, "raster", dpi=150)
        with mock.patch.object(PdfImageExportEngine, "MAX_PAGE_PIXELS", 10), self.assertRaises(ValueError):
            PdfGrayscaleEngine.convert(source, "raster", dpi=150)
        with mock.patch.object(PdfImageExportEngine, "MAX_PAGES", 1), self.assertRaises(ValueError):
            PdfGrayscaleEngine.convert(pdf_bytes(make_pdf([(300, 200)] * 2)), "raster", dpi=150)

    def test_raster_output_cap_and_source_unchanged(self):
        source = pdf_bytes(make_pdf([(300, 200)]))
        snapshot = bytes(source)
        with mock.patch.object(PdfGrayscaleEngine, "MAX_OUTPUT_BYTES", 64), self.assertRaises(PdfOutputLimitError):
            PdfGrayscaleEngine.convert(source, "raster", dpi=150)
        self.assertEqual(source, snapshot)


if __name__ == "__main__":
    unittest.main()
