import io
import json
import unittest
from unittest import mock

import pikepdf
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from officekit.engines.engine_images_to_pdf import ImagesToPdfEngine
from officekit.engines.engine_pdf_flatten import PdfFlattenEngine
from officekit.engines.engine_pdf_grayscale import PdfGrayscaleEngine
from officekit.engines.engine_pdf_images import PdfImageExportEngine
from officekit.engines.engine_pdf_page_tools import PageToolsEngine
from officekit.engines.engine_pdf_stamp import PdfStampEngine
from officekit.engines.engine_pdf_security import PDF_OUTPUT_LIMIT_ERROR
from officekit.engines.engine_uploads import RequestBodyLimitMiddleware
from officekit.routes import pdf_tools
from officekit.routes.common import PDF_INPUT_ERROR_MESSAGE
from officekit.routes.pdf_tools import (
    BODY_LIMITS,
    EXPOSE_HEADERS,
    INVALID_OPTIONS_MESSAGE,
    GrayscaleOptions,
    ResizeOptions,
    router,
)
from tests.pdf_tool_fixtures import make_annotated_pdf, make_form_pdf, make_pdf, make_png, pdf_bytes


def make_client(path_limits=None):
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, path_limits=path_limits or BODY_LIMITS)
    app.include_router(router)
    return TestClient(app)


WATERMARK = {"kind": "text", "text": "DRAFT", "font_size": 40, "color": "#FF0000", "opacity": 30,
             "angle": 45, "position": "center", "page_ranges": ""}
PAGE_NUMBERS = {"format": "page-of-total", "start": 1, "position": "bottom-center", "margin_mm": 10,
                "font_size": 12, "page_ranges": "", "count_skipped": False}
RESIZE = {"preset": "a4", "orientation": "keep", "mode": "scale", "anchor": "center", "page_ranges": ""}
GRAYSCALE = {"method": "vector"}
FLATTEN = {"scope": "all", "acknowledge_signature_loss": False}
ROTATE = {"angle": 90, "page_ranges": ""}

# (path, options) for every multipart PDF route that takes a single PDF and options.
PDF_ROUTES = [
    ("/api/pdf/page-rotations", ROTATE),
    ("/api/pdf/watermarks", WATERMARK),
    ("/api/pdf/watermarks/previews", dict(WATERMARK, preview_page=1)),
    ("/api/pdf/page-numbers", PAGE_NUMBERS),
    ("/api/pdf/page-numbers/previews", dict(PAGE_NUMBERS, preview_page=1)),
    ("/api/pdf/page-sizes", RESIZE),
    ("/api/pdf/grayscale-conversions", GRAYSCALE),
    ("/api/pdf/flattenings", FLATTEN),
]


def post_pdf(client, path, data, options=None, filename="source.pdf", extra_files=None):
    files = {"file": (filename, data, "application/pdf")}
    if extra_files:
        files.update(extra_files)
    form = {} if options is None else {"options": json.dumps(options)}
    return client.post(path, files=files, data=form)


def valid_pdf():
    return pdf_bytes(make_pdf([(612, 792), (612, 792)], text_prefix="P"))


def pdf_with_sizes(page_sizes):
    return pdf_bytes(make_pdf(page_sizes))


class BodyLimitMapTests(unittest.TestCase):
    def test_every_post_route_has_a_body_limit_and_header_list_covers_responses(self):
        posts = {route.path for route in router.routes if "POST" in getattr(route, "methods", set())}
        self.assertEqual(posts, set(BODY_LIMITS))
        for limit in BODY_LIMITS.values():
            self.assertGreater(limit, 64 * 1024 * 1024)
        for header in ("X-OfficeKit-Page-Count", "X-OfficeKit-Scale", "X-OfficeKit-Overlap-Pages",
                       "X-OfficeKit-Output-Input-Ratio", "X-OfficeKit-Flattened-Fields",
                       "X-OfficeKit-Flattened-Annotations", "X-OfficeKit-Grayscale-Method",
                       "X-OfficeKit-Affected-Pages"):
            self.assertIn(header, EXPOSE_HEADERS)

    def test_body_cap_rejects_before_parse(self):
        client = make_client({"/api/pdf/page-rotations": 1024})
        response = post_pdf(client, "/api/pdf/page-rotations", b"x" * 4096, ROTATE)
        self.assertEqual(response.status_code, 413)


class OpenApiDeclarationTests(unittest.TestCase):
    BINARY_ROUTES = {
        "/api/pdf/page-rotations": "application/pdf",
        "/api/pdf/image-pdfs": "application/pdf",
        "/api/pdf/watermarks": "application/pdf",
        "/api/pdf/watermarks/previews": "image/png",
        "/api/pdf/page-numbers": "application/pdf",
        "/api/pdf/page-numbers/previews": "image/png",
        "/api/pdf/page-sizes": "application/pdf",
        "/api/pdf/grayscale-conversions": "application/pdf",
        "/api/pdf/flattenings": "application/pdf",
    }

    def test_every_binary_success_response_and_error_status_is_declared(self):
        app = FastAPI()
        app.include_router(router)
        paths = app.openapi()["paths"]
        for path, media in self.BINARY_ROUTES.items():
            with self.subTest(path=path):
                responses = paths[path]["post"]["responses"]
                self.assertIn(media, responses["200"]["content"])
                self.assertIn("413", responses)
                self.assertIn("422", responses)
        self.assertIn("409", paths["/api/pdf/flattenings"]["post"]["responses"])
        self.assertIn("application/json", paths["/api/pdf/inspections"]["post"]["responses"]["200"]["content"])


class RotationRouteTests(unittest.TestCase):
    def test_success_headers_and_content(self):
        response = post_pdf(make_client(), "/api/pdf/page-rotations", valid_pdf(),
                            {"angle": 90, "page_ranges": "2"}, filename="Résumé 2026.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertEqual(response.headers["X-OfficeKit-Affected-Pages"], "1")
        self.assertEqual(response.headers["X-OfficeKit-Page-Count"], "2")
        self.assertIn("filename*=UTF-8''R%C3%A9sum%C3%A9%202026-rotated.pdf", response.headers["Content-Disposition"])
        with pikepdf.open(io.BytesIO(response.content)) as pdf:
            self.assertEqual(int(pdf.pages[1].obj.get("/Rotate", 0)), 90)

    def test_path_components_are_removed_from_the_download_name(self):
        response = post_pdf(make_client(), "/api/pdf/page-rotations", valid_pdf(), ROTATE,
                            filename="../../etc/secret.pdf")
        self.assertIn('filename="secret-rotated.pdf"', response.headers["Content-Disposition"])
        self.assertNotIn("etc", response.headers["Content-Disposition"])

    def test_options_bounds_and_strict_json(self):
        client = make_client()
        invalid = [
            '{"angle": 45}', '{"angle": "90"}', '{"angle": 90, "page_ranges": "1", "extra": 1}',
            '{"angle": 90, "angle": 180}', "[]", "not json", '{"angle": 90, "page_ranges": "' + "1" * 4097 + '"}',
        ]
        for raw in invalid:
            with self.subTest(options=raw[:30]):
                response = client.post("/api/pdf/page-rotations",
                                       files={"file": ("a.pdf", valid_pdf(), "application/pdf")},
                                       data={"options": raw})
                self.assertEqual(response.status_code, 422)
        response = client.post("/api/pdf/page-rotations",
                               files={"file": ("a.pdf", valid_pdf(), "application/pdf")},
                               data={"options": " " * 4096 + "{}"})
        self.assertEqual(response.status_code, 422)

    def test_out_of_range_selection_is_422_with_fixed_copy(self):
        response = post_pdf(make_client(), "/api/pdf/page-rotations", valid_pdf(), {"angle": 90, "page_ranges": "9"})
        self.assertEqual(response.status_code, 422)
        # A bad selection is an option problem, not a bad PDF, so it gets the options copy.
        self.assertEqual(response.json()["detail"], INVALID_OPTIONS_MESSAGE)


def malformed_inputs():
    """Structurally broken PDFs that open but cannot be processed (CR-2)."""

    def with_page_entry(key, value):
        pdf = make_pdf([(300, 200)])
        setattr(pdf.pages[0].obj, key, value)
        return pdf_bytes(pdf)

    def text_annotation(**entries):
        pdf = make_pdf([(300, 200)])
        annotation = pdf.make_indirect(pikepdf.Dictionary(
            Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Text, Rect=pikepdf.Array([10, 10, 60, 60]), F=4, **entries))
        pdf.pages[0].obj.Annots = pikepdf.Array([annotation])
        return pdf_bytes(pdf)

    return {
        "zero_area_crop_box": with_page_entry("CropBox", pikepdf.Array([0, 0, 0, 0])),
        "zero_area_media_box": with_page_entry("MediaBox", pikepdf.Array([0, 0, 0, 0])),
        "non_numeric_rotate": with_page_entry("Rotate", pikepdf.String("ninety")),
        "annotation_list_entry_not_dictionary": with_page_entry("Annots", pikepdf.Array([1])),
        "appearance_not_dictionary": text_annotation(AP=5),
    }


class OptionAndLimitCopyTests(unittest.TestCase):
    """CR-4 and ARCH-11: option mistakes get the options copy; fixed limits get their own copy."""

    def test_grayscale_cross_field_mistakes_get_the_options_copy(self):
        client = make_client()
        path = "/api/pdf/grayscale-conversions"
        for options in (dict(method="vector", dpi=300), dict(method="raster")):
            with self.subTest(options=options):
                response = post_pdf(client, path, valid_pdf(), options)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"], INVALID_OPTIONS_MESSAGE)

    def test_resize_cross_field_mistakes_get_the_options_copy(self):
        client = make_client()
        path = "/api/pdf/page-sizes"
        cases = (
            dict(preset="custom", mode="scale", width="100"),
            dict(preset="custom", mode="scale", width="100", height="100"),
            dict(preset="a4", mode="scale", width="100", height="100", unit="mm"),
        )
        for options in cases:
            with self.subTest(options=options):
                response = post_pdf(client, path, valid_pdf(), options)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"], INVALID_OPTIONS_MESSAGE)

    def test_page_count_limit_has_its_own_fixed_copy(self):
        client = make_client()
        many = pdf_bytes(make_pdf([(612, 792)] * 101))
        response = post_pdf(client, "/api/pdf/grayscale-conversions", many, dict(method="raster", dpi=150))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Rasterized grayscale supports up to 100 pages.")

    def test_page_pixel_limit_has_its_own_fixed_copy(self):
        client = make_client()
        with mock.patch.object(PdfImageExportEngine, "MAX_PAGE_PIXELS", 10):
            response = post_pdf(client, "/api/pdf/grayscale-conversions", valid_pdf(), dict(method="raster", dpi=150))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "A page is too large to rasterize at this DPI.")


class OptionModelValidatorTests(unittest.TestCase):
    """QA-14: each cross-field rule is refused by the DTO itself, so the validator has a failing test of its own."""

    def test_custom_size_needs_width_height_and_unit(self):
        with self.assertRaises(ValidationError):
            ResizeOptions(preset="custom", width="100", mode="scale")
        ResizeOptions(preset="custom", width="100", height="200", unit="mm", mode="scale")

    def test_named_preset_takes_no_custom_size(self):
        with self.assertRaises(ValidationError):
            ResizeOptions(preset="a4", width="100", mode="scale")
        ResizeOptions(preset="a4", mode="scale")

    def test_vector_grayscale_takes_no_dpi_and_raster_needs_one(self):
        with self.assertRaises(ValidationError):
            GrayscaleOptions(method="vector", dpi=150)
        with self.assertRaises(ValidationError):
            GrayscaleOptions(method="raster")
        GrayscaleOptions(method="raster", dpi=300)


class MalformedInputTests(unittest.TestCase):
    def test_malformed_pdfs_never_reach_the_500_boundary(self):
        client = make_client()
        for label, data in malformed_inputs().items():
            for path, options in PDF_ROUTES:
                with self.subTest(case=label, path=path):
                    response = post_pdf(client, path, data, options)
                    self.assertEqual(response.status_code, 422)
                    self.assertEqual(response.json()["detail"], PDF_INPUT_ERROR_MESSAGE)
            with self.subTest(case=label, path="/api/pdf/inspections"):
                response = post_pdf(client, "/api/pdf/inspections", data)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"], PDF_INPUT_ERROR_MESSAGE)

    def test_zero_area_pages_return_422_for_every_geometry_route(self):
        client = make_client()
        data = malformed_inputs()["zero_area_crop_box"]
        for path, options in PDF_ROUTES:
            if path.endswith("/grayscale-conversions") or path.endswith("/flattenings") or \
                    path.endswith("/page-rotations"):
                continue
            with self.subTest(path=path):
                self.assertEqual(post_pdf(client, path, data, options).status_code, 422)


class ErrorBoundaryTests(unittest.TestCase):
    """Every PDF route: malformed, empty, encrypted and zero-page inputs fail safely."""

    def encrypted(self):
        output = io.BytesIO()
        make_pdf([(300, 200)]).save(output, encryption=pikepdf.Encryption(user="secret", owner="o", R=6))
        return output.getvalue()

    def test_bad_inputs_return_422_without_diagnostics(self):
        client = make_client()
        inputs = {
            "malformed": b"%PDF-1.4 /Root 99 0 R garbage /Users/private/secret.txt",
            "empty": b"",
            "encrypted": self.encrypted(),
            "zero-page": pdf_bytes(pikepdf.new()),
        }
        for path, options in PDF_ROUTES:
            for name, data in inputs.items():
                with self.subTest(route=path, input=name):
                    response = post_pdf(client, path, data, options)
                    self.assertEqual(response.status_code, 422)
                    text = response.text
                    for leaked in ("QPDF", "pikepdf", "secret", "private", "Traceback", "/Users"):
                        self.assertNotIn(leaked, text)

    def test_inspection_bad_inputs(self):
        client = make_client()
        for data in (b"%PDF garbage", b"", self.encrypted(), pdf_bytes(pikepdf.new())):
            response = post_pdf(client, "/api/pdf/inspections", data)
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["detail"], PDF_INPUT_ERROR_MESSAGE)

    def test_output_cap_returns_413_without_body_for_every_output_route(self):
        client = make_client()
        cases = [
            (PageToolsEngine, "/api/pdf/page-rotations", ROTATE, valid_pdf()),
            (PdfStampEngine, "/api/pdf/watermarks", WATERMARK, valid_pdf()),
            (PdfStampEngine, "/api/pdf/page-numbers", PAGE_NUMBERS, valid_pdf()),
            (PageToolsEngine, "/api/pdf/page-sizes", RESIZE, valid_pdf()),
            (PdfGrayscaleEngine, "/api/pdf/grayscale-conversions", GRAYSCALE, valid_pdf()),
            (PdfFlattenEngine, "/api/pdf/flattenings", FLATTEN, make_form_pdf()),
        ]
        for engine, path, options, data in cases:
            with self.subTest(route=path), mock.patch.object(engine, "MAX_OUTPUT_BYTES", 64):
                response = post_pdf(client, path, data, options)
                self.assertEqual(response.status_code, 413)
                self.assertEqual(response.json()["detail"], PDF_OUTPUT_LIMIT_ERROR)
                self.assertNotIn("content-disposition", response.headers)

    def test_images_output_cap(self):
        png = make_png(40, 40)
        with mock.patch.object(ImagesToPdfEngine, "MAX_OUTPUT_BYTES", 64):
            response = make_client().post(
                "/api/pdf/image-pdfs",
                files=[("files", ("a.png", png, "image/png")), ("files", ("b.png", png, "image/png"))],
                data={"options": json.dumps({"page_size": "a4", "orientation": "auto", "fit": "contain",
                                             "margin_mm": 10})},
            )
        self.assertEqual(response.status_code, 413)
        self.assertNotIn("content-disposition", response.headers)


class ImagesRouteTests(unittest.TestCase):
    OPTIONS = {"page_size": "a4", "orientation": "auto", "fit": "contain", "margin_mm": 10}

    def test_batch_success_keeps_order_and_headers(self):
        first, second = make_png(30, 60), make_png(60, 30)
        response = make_client().post(
            "/api/pdf/image-pdfs",
            files=[("files", ("one.png", first, "image/png")), ("files", ("two.png", second, "image/png"))],
            data={"options": json.dumps(self.OPTIONS)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-OfficeKit-Page-Count"], "2")
        self.assertIn('filename="images.pdf"', response.headers["Content-Disposition"])

    def test_count_limits_and_unreadable_image_name_only_the_position(self):
        client = make_client()
        png = make_png(4, 4)
        response = client.post("/api/pdf/image-pdfs", files=[("files", ("a.png", png, "image/png"))] * 201,
                               data={"options": json.dumps(self.OPTIONS)})
        self.assertEqual(response.status_code, 422)
        response = client.post(
            "/api/pdf/image-pdfs",
            files=[("files", ("a.png", png, "image/png")), ("files", ("b.png", b"junk", "image/png"))],
            data={"options": json.dumps(self.OPTIONS)},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], "Image 2 could not be read.")

    def test_options_validation(self):
        client = make_client()
        png = make_png(4, 4)
        for options in ({"page_size": "a3", "orientation": "auto", "fit": "contain", "margin_mm": 10},
                        {"page_size": "a4", "orientation": "auto", "fit": "contain", "margin_mm": 51},
                        {"page_size": "a4", "orientation": "auto", "fit": "contain", "margin_mm": 10, "dpi": 1}):
            response = client.post("/api/pdf/image-pdfs", files=[("files", ("a.png", png, "image/png"))],
                                   data={"options": json.dumps(options)})
            self.assertEqual(response.status_code, 422)

    def test_total_upload_limit_returns_413(self):
        with mock.patch("officekit.routes.common.MAX_API_UPLOAD_BYTES", 100):
            png = make_png(40, 40)
            response = make_client().post("/api/pdf/image-pdfs",
                                          files=[("files", ("a.png", png, "image/png"))],
                                          data={"options": json.dumps(self.OPTIONS)})
        self.assertEqual(response.status_code, 413)


class InspectionRouteTests(unittest.TestCase):
    def test_json_report_and_no_source_mutation(self):
        source = pdf_bytes(make_pdf([(612, 792)]))
        snapshot = bytes(source)
        response = post_pdf(make_client(), "/api/pdf/inspections", source)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        body = response.json()
        self.assertEqual(body["page_count"], 1)
        self.assertEqual(len([entry for entry in body["docinfo"] if entry["standard"]]), 9)
        self.assertEqual(body["forms"], {"fields": 0, "signature_fields": 0, "signed": False, "xfa": False})
        self.assertEqual(source, snapshot)

    def test_annotations_and_forms_are_summarised(self):
        body = post_pdf(make_client(), "/api/pdf/inspections", make_annotated_pdf()).json()
        self.assertEqual(body["annotations"], 1)
        body = post_pdf(make_client(), "/api/pdf/inspections", make_form_pdf(xfa=True)).json()
        self.assertTrue(body["forms"]["xfa"])


class WatermarkRouteTests(unittest.TestCase):
    def test_text_success_and_preview(self):
        client = make_client()
        response = post_pdf(client, "/api/pdf/watermarks", valid_pdf(), WATERMARK, filename="Doc.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertIn('filename="Doc-watermarked.pdf"', response.headers["Content-Disposition"])
        self.assertEqual(response.headers["X-OfficeKit-Page-Count"], "2")
        preview = post_pdf(client, "/api/pdf/watermarks/previews", valid_pdf(), dict(WATERMARK, preview_page=2))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.headers["content-type"], "image/png")

    def test_text_outside_the_font_is_422_with_fixed_copy(self):
        response = post_pdf(make_client(), "/api/pdf/watermarks", valid_pdf(), dict(WATERMARK, text="漢字"))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], PdfStampEngine.UNSUPPORTED_GLYPH_MESSAGE)
        self.assertEqual(response.json()["detail"],
                         "The watermark text uses characters the bundled font can't draw. "
                         "Latin, Greek and Cyrillic are supported.")

    def test_preview_page_zero_is_first_landscape_page_and_negative_is_422(self):
        client = make_client()
        landscape = post_pdf(client, "/api/pdf/watermarks/previews", pdf_with_sizes([(200, 300), (300, 200)]),
                             dict(WATERMARK, preview_page=0))
        self.assertEqual(landscape.status_code, 200)
        self.assertEqual(landscape.headers["content-type"], "image/png")
        none = post_pdf(client, "/api/pdf/watermarks/previews", pdf_with_sizes([(200, 300)]),
                        dict(WATERMARK, preview_page=0))
        self.assertEqual(none.status_code, 422)
        negative = post_pdf(client, "/api/pdf/watermarks/previews", valid_pdf(),
                            dict(WATERMARK, preview_page=-1))
        self.assertEqual(negative.status_code, 422)

    def test_covered_accents_are_accepted(self):
        response = post_pdf(make_client(), "/api/pdf/watermarks", valid_pdf(), dict(WATERMARK, text="Résumé"))
        self.assertEqual(response.status_code, 200)

    def test_dto_bounds_are_enforced(self):
        client = make_client()
        invalid = [
            dict(WATERMARK, font_size=7), dict(WATERMARK, font_size=145),
            dict(WATERMARK, opacity=4), dict(WATERMARK, opacity=101),
            dict(WATERMARK, angle=-91), dict(WATERMARK, color="#fff"),
            dict(WATERMARK, position="middle"), dict(WATERMARK, text="x" * 401),
            dict(WATERMARK, kind="sticker"), dict(WATERMARK, text=""), dict(WATERMARK, text="x" * 201),
            dict(WATERMARK, text="A\x01B"), dict(WATERMARK, text=None), dict(WATERMARK, kind="image"),
        ]
        for options in invalid:
            with self.subTest(options=options):
                self.assertEqual(post_pdf(client, "/api/pdf/watermarks", valid_pdf(), options).status_code, 422)
        for options in (dict(WATERMARK, font_size=8, opacity=5, angle=-90),
                        dict(WATERMARK, font_size=144, opacity=100, angle=90),
                        dict(WATERMARK, text="x"), dict(WATERMARK, text="x" * 200)):
            with self.subTest(boundary=options):
                self.assertEqual(post_pdf(client, "/api/pdf/watermarks", valid_pdf(), options).status_code, 200)

    def test_watermark_text_over_200_characters_gets_the_fixed_options_message(self):
        response = post_pdf(make_client(), "/api/pdf/watermarks", valid_pdf(), dict(WATERMARK, text="x" * 201))
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], INVALID_OPTIONS_MESSAGE)

    def test_image_part_is_required_only_for_image_kind(self):
        client = make_client()
        image_options = dict(WATERMARK, kind="image", text=None)
        self.assertEqual(post_pdf(client, "/api/pdf/watermarks", valid_pdf(), image_options).status_code, 422)
        self.assertEqual(post_pdf(client, "/api/pdf/watermarks", valid_pdf(), WATERMARK,
                                  extra_files={"image": ("w.png", make_png(10, 10), "image/png")}).status_code, 422)
        response = post_pdf(client, "/api/pdf/watermarks", valid_pdf(), image_options,
                            extra_files={"image": ("w.png", make_png(40, 40, alpha=128), "image/png")})
        self.assertEqual(response.status_code, 200)

    def test_image_part_size_limit_is_413(self):
        with mock.patch.object(pdf_tools, "MAX_WATERMARK_IMAGE_BYTES", 16):
            response = post_pdf(make_client(), "/api/pdf/watermarks", valid_pdf(),
                                dict(WATERMARK, kind="image", text=None),
                                extra_files={"image": ("w.png", make_png(40, 40), "image/png")})
        self.assertEqual(response.status_code, 413)

    def test_bad_watermark_image_is_422(self):
        response = post_pdf(make_client(), "/api/pdf/watermarks", valid_pdf(),
                            dict(WATERMARK, kind="image", text=None),
                            extra_files={"image": ("w.png", b"not an image", "image/png")})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"], PdfStampEngine.IMAGE_ERROR_MESSAGE)


class PageNumberRouteTests(unittest.TestCase):
    def test_success_and_overlap_header(self):
        response = post_pdf(make_client(), "/api/pdf/page-numbers", valid_pdf(), PAGE_NUMBERS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-OfficeKit-Overlap-Pages"], "")
        self.assertEqual(response.headers["X-OfficeKit-Page-Count"], "2")

    def test_preview_returns_png_with_overlap_header(self):
        response = post_pdf(make_client(), "/api/pdf/page-numbers/previews", valid_pdf(),
                            dict(PAGE_NUMBERS, preview_page=1))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertIn("X-OfficeKit-Overlap-Pages", response.headers)

    def test_cross_field_numbering_rules_are_dto_errors_with_the_options_message(self):
        client = make_client()
        for options in (dict(PAGE_NUMBERS, format="page", template="{n}"),
                        dict(PAGE_NUMBERS, format="custom")):
            with self.subTest(options=options):
                response = post_pdf(client, "/api/pdf/page-numbers", valid_pdf(), options)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"], INVALID_OPTIONS_MESSAGE)

    def test_invalid_numbering_options_are_422(self):
        client = make_client()
        invalid = [
            dict(PAGE_NUMBERS, format="fancy"), dict(PAGE_NUMBERS, format="custom", template="{x}"),
            dict(PAGE_NUMBERS, format="custom"), dict(PAGE_NUMBERS, format="roman-upper", start=0),
            dict(PAGE_NUMBERS, position="middle"), dict(PAGE_NUMBERS, margin_mm=51),
            dict(PAGE_NUMBERS, font_size=5), dict(PAGE_NUMBERS, start=10000),
            dict(PAGE_NUMBERS, count_skipped="yes"), dict(PAGE_NUMBERS, unknown=1),
            dict(PAGE_NUMBERS, format="page", template="{n}"), dict(PAGE_NUMBERS, format="custom", template="{n}}"),
        ]
        for options in invalid:
            with self.subTest(options=options):
                self.assertEqual(post_pdf(client, "/api/pdf/page-numbers", valid_pdf(), options).status_code, 422)


class ResizeRouteTests(unittest.TestCase):
    def test_success_reports_minimum_scale(self):
        response = post_pdf(make_client(), "/api/pdf/page-sizes", valid_pdf(), RESIZE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-OfficeKit-Scale"], "0.9727")
        self.assertIn('filename="source-resized.pdf"', response.headers["Content-Disposition"])

    def test_custom_size_accepts_decimal_json_numbers(self):
        options = {"preset": "custom", "width": 210.5, "height": 297, "unit": "mm", "orientation": "portrait",
                   "mode": "canvas", "anchor": "top-left", "page_ranges": ""}
        response = post_pdf(make_client(), "/api/pdf/page-sizes", valid_pdf(), options)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-OfficeKit-Scale"], "1.0000")

    def test_invalid_size_options_are_422(self):
        client = make_client()
        invalid = [
            dict(RESIZE, preset="a3"), dict(RESIZE, preset="custom", width="210", height="297"),
            dict(RESIZE, preset="custom", width="210.123", height="297", unit="mm"),
            dict(RESIZE, preset="custom", width="10", height="297", unit="mm"),
            dict(RESIZE, mode="stretch"), dict(RESIZE, anchor="middle"),
            dict(RESIZE, orientation="diagonal"),
        ]
        for options in invalid:
            with self.subTest(options=options):
                self.assertEqual(post_pdf(client, "/api/pdf/page-sizes", valid_pdf(), options).status_code, 422)


class GrayscaleRouteTests(unittest.TestCase):
    def colour_pdf(self):
        return pdf_bytes(make_pdf([(300, 200)], content=lambda *_: "1 0 0 rg 10 10 50 50 re f"))

    def test_vector_success_reports_method_and_ratio(self):
        response = post_pdf(make_client(), "/api/pdf/grayscale-conversions", self.colour_pdf(), GRAYSCALE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-OfficeKit-Grayscale-Method"], "vector")
        self.assertRegex(response.headers["X-OfficeKit-Output-Input-Ratio"], r"^\d+\.\d{4}$")

    def test_raster_success_and_dpi_rules(self):
        client = make_client()
        response = post_pdf(client, "/api/pdf/grayscale-conversions", self.colour_pdf(), {"method": "raster", "dpi": 150})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-OfficeKit-Grayscale-Method"], "raster")
        self.assertEqual(post_pdf(client, "/api/pdf/grayscale-conversions", self.colour_pdf(),
                                  {"method": "vector", "dpi": 150}).status_code, 422)
        self.assertEqual(post_pdf(client, "/api/pdf/grayscale-conversions", self.colour_pdf(),
                                  {"method": "raster", "dpi": 200}).status_code, 422)

    def test_refusal_returns_stable_code_and_fixed_message(self):
        shading = pdf_bytes(make_pdf([(300, 200)], content=lambda *_: "/Sh1 sh"))
        response = post_pdf(make_client(), "/api/pdf/grayscale-conversions", shading, GRAYSCALE)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "grayscale_needs_raster")


class FlattenRouteTests(unittest.TestCase):
    def test_success_reports_counts_and_structure(self):
        response = post_pdf(make_client(), "/api/pdf/flattenings", make_form_pdf(), FLATTEN)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-OfficeKit-Flattened-Fields"], "2")
        self.assertEqual(response.headers["X-OfficeKit-Flattened-Annotations"], "0")
        self.assertIn('filename="source-flattened.pdf"', response.headers["Content-Disposition"])

    def test_signed_field_is_409_until_acknowledged(self):
        client = make_client()
        response = post_pdf(client, "/api/pdf/flattenings", make_form_pdf(signed=True), FLATTEN)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "signature_ack_required")
        acknowledged = dict(FLATTEN, acknowledge_signature_loss=True)
        self.assertEqual(post_pdf(client, "/api/pdf/flattenings", make_form_pdf(signed=True), acknowledged).status_code,
                         200)

    def test_xfa_is_422_and_scope_must_be_known(self):
        client = make_client()
        response = post_pdf(client, "/api/pdf/flattenings", make_form_pdf(xfa=True), FLATTEN)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"]["code"], "xfa_unsupported")
        self.assertEqual(post_pdf(client, "/api/pdf/flattenings", make_form_pdf(), dict(FLATTEN, scope="text")).status_code,
                         422)


class HealthyRoutesTests(unittest.TestCase):
    def test_rotation_route_accepts_every_documented_angle(self):
        client = make_client()
        for angle in (90, 180, 270):
            with self.subTest(angle=angle):
                self.assertEqual(post_pdf(client, "/api/pdf/page-rotations", valid_pdf(),
                                          {"angle": angle, "page_ranges": ""}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
