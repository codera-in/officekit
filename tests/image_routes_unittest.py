"""HTTP tests for the image slice routes, mounted on a fresh FastAPI app."""

import base64
import io
import json
import unittest
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from officekit.engines import engine_file_converter
from officekit.engines import engine_image_tools
from officekit.engines.engine_uploads import RequestBodyLimitMiddleware
from officekit.routes import image as image_routes


def encode(image, image_format="PNG", **options):
    output = io.BytesIO()
    image.save(output, format=image_format, **options)
    return output.getvalue()


def decode(content):
    with Image.open(io.BytesIO(content)) as image:
        image.load()
        return image.copy()


def no_file_writes():
    """Fail the test if any code opens a file for writing (QA-5 write guard)."""
    real_open = open

    def guarded(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"unexpected file write: {file!r}")
        return real_open(file, mode, *args, **kwargs)

    return mock.patch("builtins.open", guarded)


def make_client(limits=True):
    app = FastAPI()
    if limits:
        app.add_middleware(RequestBodyLimitMiddleware, path_limits=image_routes.BODY_LIMITS)
    app.include_router(image_routes.router)
    return TestClient(app)


client = make_client()
PNG = encode(Image.new("RGB", (4, 3), (200, 30, 30)))
RENDITION_OPS = json.dumps({"operations": [{"type": "flip", "axis": "horizontal"}]})


def post_image(path, content=PNG, name="shot.png", mime="image/png", **data):
    return client.post(path, data=data, files={"file": (name, content, mime)})


class RouteInventoryTests(unittest.TestCase):
    def test_binary_success_headers_are_declared_in_the_openapi_document(self):
        # The success headers the contract names are described by the spec, not only by prose.
        app = FastAPI()
        app.include_router(image_routes.router)
        paths = app.openapi()["paths"]
        expected = {
            "/api/data-uri-images": {"X-Content-Type-Options"},
            "/api/image-renditions": {"X-OfficeKit-Image-Width", "X-OfficeKit-Image-Height", "X-OfficeKit-Image-Density"},
            "/api/icon-packs": {"X-OfficeKit-Upscaled-Sizes"},
            "/api/image-collages": {"X-OfficeKit-Image-Width", "X-OfficeKit-Image-Height"},
            "/api/contact-sheets": {"X-OfficeKit-Page-Count"},
        }
        for path, names in expected.items():
            with self.subTest(path=path):
                declared = paths[path]["post"]["responses"]["200"]["headers"]
                self.assertEqual(set(declared), names)

    def test_every_post_path_has_a_body_cap_and_the_expose_headers_are_declared(self):
        post_paths = sorted({route.path for route in image_routes.router.routes if "POST" in route.methods})
        self.assertEqual(post_paths, sorted(image_routes.BODY_LIMITS))
        for path, limit in image_routes.BODY_LIMITS.items():
            self.assertIsInstance(limit, int)
            self.assertGreater(limit, 0, path)
        self.assertEqual(
            set(image_routes.EXPOSE_HEADERS),
            {"X-OfficeKit-Image-Density", "X-OfficeKit-Upscaled-Sizes"},
        )

    def test_paths_are_plural_nouns_without_verbs(self):
        for path in image_routes.BODY_LIMITS:
            self.assertTrue(path.startswith("/api/"))
            for verb in ("create", "resize", "convert", "encode", "decode", "compare", "render"):
                self.assertNotIn(verb, path)


class RenditionRouteTests(unittest.TestCase):
    def test_flip_returns_pixels_size_and_attachment_headers(self):
        response = post_image("/api/image-renditions", operations=RENDITION_OPS)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(response.headers["content-disposition"].split(";")[0], "attachment")
        self.assertIn('filename="shot_edited.png"', response.headers["content-disposition"])
        self.assertEqual(response.headers["X-OfficeKit-Image-Width"], "4")
        self.assertEqual(response.headers["X-OfficeKit-Image-Height"], "3")
        self.assertNotIn("X-OfficeKit-Image-Density", response.headers)

    def test_density_header_is_sent_for_density_operations(self):
        operations = json.dumps({"operations": [{"type": "density", "x": 300, "y": 300, "unit": "inch"}]})
        response = post_image("/api/image-renditions", operations=operations)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-OfficeKit-Image-Density"], "300,300,inch")

    def test_animated_gif_keeps_every_frame(self):
        frames = [Image.new("RGB", (4, 4), (60 * index, 0, 0)).convert("P") for index in range(3)]
        output = io.BytesIO()
        frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:])
        response = post_image(
            "/api/image-renditions", content=output.getvalue(), name="anim.gif", mime="image/gif",
            operations=RENDITION_OPS,
        )
        self.assertEqual(response.status_code, 200)
        with Image.open(io.BytesIO(response.content)) as result:
            self.assertEqual(result.n_frames, 3)

    def test_alpha_border_keeps_transparent_corners_in_png(self):
        operations = json.dumps({"operations": [{"type": "border", "width": 2, "corner_radius": 3}]})
        response = post_image("/api/image-renditions", content=encode(Image.new("RGBA", (6, 6), (1, 2, 3, 255))), operations=operations)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(decode(response.content).convert("RGBA").getpixel((0, 0))[3], 0)

    def test_unicode_and_path_filenames_become_safe_attachment_names(self):
        response = post_image(
            "/api/image-renditions", name="../secret/résumé 日本.png", operations=RENDITION_OPS,
        )
        disposition = response.headers["content-disposition"]
        self.assertNotIn("secret", disposition)
        self.assertNotIn("../", disposition)
        self.assertIn("filename*=UTF-8''", disposition)
        self.assertTrue(disposition.isascii())

    def test_unsupported_extension_is_415_and_svg_is_not_an_image_rendition(self):
        response = post_image("/api/image-renditions", name="note.txt", mime="text/plain", operations=RENDITION_OPS)
        self.assertEqual(response.status_code, 415)
        response = post_image("/api/image-renditions", name="icon.svg", mime="image/svg+xml", operations=RENDITION_OPS)
        self.assertEqual(response.status_code, 415)

    def test_malformed_image_is_422_with_a_stable_code_and_no_parser_text(self):
        response = post_image("/api/image-renditions", content=b"not an image", operations=RENDITION_OPS)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json(), {"detail": "The image file is invalid or cannot be decoded.", "code": "INVALID_IMAGE"})

    def test_operations_are_strict_bounded_and_ordered(self):
        bad_bodies = [
            {"operations": [{"type": "flip", "axis": "horizontal", "extra": 1}]},
            {"operations": [{"type": "rotate", "degrees_cw": 45}]},
            {"operations": [{"type": "rotate", "degrees_cw": "90"}]},
            {"operations": [{"type": "adjust", "brightness": 101}]},
            {"operations": [{"type": "border", "width": 2001}]},
            {"operations": [{"type": "border", "width": 1, "fill": "red"}]},
            {"operations": [{"type": "density", "x": 300, "y": 300, "unit": "inch"}, {"type": "flip", "axis": "vertical"}]},
            {"operations": [{"type": "density", "x": 300, "y": 300, "unit": "inch"}] * 2},
            {"operations": []},
            {"operations": [{"type": "flip", "axis": "vertical"}] * 9},
            {"operations": [{"type": "flip", "axis": "vertical"}], "extra": True},
        ]
        for body in bad_bodies:
            with self.subTest(body=body):
                response = post_image("/api/image-renditions", operations=json.dumps(body))
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["code"], "INVALID_OPTIONS")

    def test_duplicate_keys_and_oversized_operation_text_are_rejected(self):
        duplicate = '{"operations": [{"type": "flip", "type": "flip", "axis": "vertical"}]}'
        response = post_image("/api/image-renditions", operations=duplicate)
        self.assertEqual(response.json()["code"], "INVALID_OPTIONS")
        huge = json.dumps({"operations": [{"type": "flip", "axis": "vertical"}], "pad": "x" * (16 * 1024)})
        response = post_image("/api/image-renditions", operations=huge)
        self.assertEqual(response.status_code, 422)

    def test_framework_validation_422s_carry_the_stable_code(self):
        # ARCH-1: the contract promises a stable code on every error, including framework validation.
        response = post_image("/api/image-renditions", operations=RENDITION_OPS, quality=0, format="jpeg")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json(),
            {"detail": "Request contains invalid or unsupported values.", "code": "INVALID_OPTIONS"},
        )

    def test_numeric_form_fields_have_exact_bounds(self):
        for quality, expected in ((0, 422), (1, 200), (100, 200), (101, 422)):
            with self.subTest(quality=quality):
                response = post_image("/api/image-renditions", operations=RENDITION_OPS, quality=quality, format="jpeg")
                self.assertEqual(response.status_code, expected)
        for edge, expected in ((63, 422), (64, 200), (2048, 200), (2049, 422)):
            with self.subTest(edge=edge):
                response = post_image("/api/image-renditions", operations=RENDITION_OPS, preview_max_edge=edge)
                self.assertEqual(response.status_code, expected)

    def test_preview_returns_png_scaled_to_the_edge(self):
        big = encode(Image.new("RGB", (400, 200), (9, 9, 9)))
        response = post_image("/api/image-renditions", content=big, operations=RENDITION_OPS, preview_max_edge=100)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertEqual(decode(response.content).size, (100, 50))

    def test_output_over_the_cap_is_413_and_work_over_the_budget_is_413(self):
        noise = random_png(64)
        with mock.patch.object(engine_file_converter.FileConverterEngine, "MAX_RESIZE_OUTPUT_BYTES", 200):
            response = post_image("/api/image-renditions", content=noise, operations=RENDITION_OPS)
        self.assertEqual((response.status_code, response.json()["code"]), (413, "TOO_LARGE_OUTPUT"))
        with mock.patch.object(engine_image_tools, "MAX_RENDITION_WORK_PIXELS", 10):
            response = post_image("/api/image-renditions", operations=RENDITION_OPS)
        self.assertEqual((response.status_code, response.json()["code"]), (413, "TOO_LARGE_WORK"))

    def test_body_cap_rejects_before_parsing_when_declared_size_is_too_large(self):
        oversized = b"x" * (image_routes.MAX_UPLOAD_BYTES + image_routes.MAX_MULTIPART_OVERHEAD_BYTES + 1)
        response = client.post(
            "/api/image-renditions",
            headers={"content-type": "multipart/form-data; boundary=zz"},
            content=oversized,
        )
        self.assertEqual(response.status_code, 413)

    def test_a_request_writes_no_file(self):
        # QA-5: bytes are immutable, so the guard is that a request never writes a file.
        with no_file_writes():
            post_image("/api/image-renditions", operations=RENDITION_OPS)


def random_png(side):
    import random

    noise = random.Random(3).getrandbits(8 * side * side * 3).to_bytes(side * side * 3, "little")
    return encode(Image.frombytes("RGB", (side, side), noise))


class BatchRouteTests(unittest.TestCase):
    def test_batch_returns_a_zip_with_unique_names(self):
        import zipfile

        response = client.post(
            "/api/image-rendition-batches",
            data={"operations": RENDITION_OPS},
            files=[
                ("files", ("a.png", PNG, "image/png")),
                ("files", ("a.png", PNG, "image/png")),
                ("files", ("b.png", PNG, "image/png")),
            ],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/zip")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(archive.namelist(), ["a_edited.png", "a_edited (2).png", "b_edited.png"])

    def test_more_than_fifty_files_is_413(self):
        files = [("files", (f"f{index}.png", PNG, "image/png")) for index in range(51)]
        response = client.post("/api/image-rendition-batches", data={"operations": RENDITION_OPS}, files=files)
        self.assertEqual((response.status_code, response.json()["code"]), (413, "TOO_LARGE_INPUT"))

    def test_a_non_image_in_the_batch_is_415(self):
        response = client.post(
            "/api/image-rendition-batches",
            data={"operations": RENDITION_OPS},
            files=[("files", ("a.png", PNG, "image/png")), ("files", ("a.txt", b"x", "text/plain"))],
        )
        self.assertEqual(response.status_code, 415)


class MetadataRouteTests(unittest.TestCase):
    def gps_jpeg(self):
        exif = Image.Exif()
        exif[0x0132] = "2024:05:01 12:34:56"
        gps = exif.get_ifd(0x8825)
        gps[1] = "N"
        gps[2] = (37.0, 46.0, 29.7)
        gps[3] = "W"
        gps[4] = (122.0, 25.0, 10.2)
        return encode(Image.new("RGB", (4, 4)), "JPEG", exif=exif.tobytes())

    def test_default_report_withholds_coordinates_and_matches_the_dto(self):
        response = post_image("/api/image-metadata-reports", content=self.gps_jpeg(), name="p.jpg", mime="image/jpeg")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["location"], {"present": True, "withheld": True, "latitude": None, "longitude": None, "altitude_m": None})
        text = response.text
        for coordinate in ("37.77", "122.4", "-122"):
            self.assertNotIn(coordinate, text)
        self.assertEqual(body["format"], "JPEG")

    def test_location_is_returned_only_when_requested(self):
        response = post_image(
            "/api/image-metadata-reports", content=self.gps_jpeg(), name="p.jpg", mime="image/jpeg", include_location="true",
        )
        body = response.json()
        self.assertFalse(body["location"]["withheld"])
        self.assertAlmostEqual(body["location"]["latitude"], 37.7749, places=3)

    def test_metadata_rejects_non_images(self):
        response = post_image("/api/image-metadata-reports", content=b"nope", name="x.png")
        self.assertEqual(response.json()["code"], "INVALID_IMAGE")


class PaletteRouteTests(unittest.TestCase):
    def test_solid_image_gives_one_swatch_and_bounds_are_exact(self):
        response = post_image("/api/image-palettes", content=encode(Image.new("RGB", (4, 4), (0, 0, 255))), count="6")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([swatch["hex"] for swatch in response.json()["colors"]], ["#0000FF"])
        for count, expected in ((0, 422), (1, 200), (12, 200), (13, 422)):
            with self.subTest(count=count):
                response = post_image("/api/image-palettes", count=str(count))
                self.assertEqual(response.status_code, expected)
        for threshold, expected in ((0, 422), (1, 200), (255, 200), (256, 422)):
            with self.subTest(threshold=threshold):
                response = post_image("/api/image-palettes", alpha_threshold=str(threshold))
                self.assertEqual(response.status_code, expected)

    def test_fully_transparent_image_is_422_no_opaque_pixels(self):
        response = post_image("/api/image-palettes", content=encode(Image.new("RGBA", (2, 2), (0, 0, 0, 0))))
        self.assertEqual(response.json()["code"], "NO_OPAQUE_PIXELS")


class DataUriRouteTests(unittest.TestCase):
    def test_encode_then_decode_round_trips_bytes_with_safe_headers(self):
        encoded = post_image("/api/data-uris", content=PNG)
        self.assertEqual(encoded.status_code, 200)
        uri = encoded.json()["data_uri"]
        decoded = client.post("/api/data-uri-images", json={"data_uri": uri})
        self.assertEqual(decoded.status_code, 200)
        self.assertEqual(decoded.content, PNG)
        self.assertEqual(decoded.headers["x-content-type-options"], "nosniff")
        self.assertEqual(decoded.headers["content-type"], "image/png")
        self.assertTrue(decoded.headers["content-disposition"].startswith("attachment"))

    def test_svg_is_accepted_for_encoding_and_served_as_an_attachment(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"></svg>'
        encoded = post_image("/api/data-uris", content=svg, name="icon.svg", mime="image/svg+xml")
        self.assertEqual(encoded.status_code, 200)
        decoded = client.post("/api/data-uri-images", json={"data_uri": encoded.json()["data_uri"]})
        self.assertEqual(decoded.headers["content-type"], "image/svg+xml")
        self.assertTrue(decoded.headers["content-disposition"].startswith("attachment"))
        self.assertEqual(decoded.headers["x-content-type-options"], "nosniff")

    def test_mime_mismatch_between_extension_and_bytes_is_422(self):
        jpeg = encode(Image.new("RGB", (2, 2)), "JPEG")
        response = post_image("/api/data-uris", content=jpeg, name="fake.png", mime="image/png")
        self.assertEqual((response.status_code, response.json()["code"]), (422, "MIME_MISMATCH"))

    def test_oversized_binary_is_413_and_bad_base64_is_422(self):
        oversized = b"\x89PNG\r\n\x1a\n" + b"0" * (8 * 1024 * 1024)
        response = post_image("/api/data-uris", content=oversized, name="big.png")
        self.assertEqual(response.status_code, 413)
        for uri in ("data:image/png;base64,@@@", "data:image/png;base64,AAA"):
            with self.subTest(uri=uri):
                response = client.post("/api/data-uri-images", json={"data_uri": uri})
                self.assertEqual((response.status_code, response.json()["code"]), (422, "INVALID_DATA_URI"))

    def test_decode_rejects_unknown_fields_and_oversized_strings(self):
        response = client.post("/api/data-uri-images", json={"data_uri": "x", "extra": 1})
        self.assertEqual(response.status_code, 422)
        response = client.post("/api/data-uri-images", json={"data_uri": "A" * (image_routes.MAX_DATA_URI_CHARACTERS + 1)})
        self.assertEqual(response.status_code, 422)


class IconPackRouteTests(unittest.TestCase):
    def test_icon_pack_zip_and_upscaled_header(self):
        import zipfile

        response = post_image("/api/icon-packs", content=encode(Image.new("RGB", (32, 32), (1, 2, 3))), platforms="web,windows")
        self.assertEqual(response.status_code, 200)
        self.assertIn("48", response.headers["X-OfficeKit-Upscaled-Sizes"].split(","))
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIn("windows/app.ico", archive.namelist())

    def test_platform_list_is_checked_for_membership_uniqueness_and_count(self):
        for platforms in ("linux", "web,web", "web,windows,macos,web", "web, windows"):
            with self.subTest(platforms=platforms):
                response = post_image("/api/icon-packs", platforms=platforms)
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["code"], "INVALID_OPTIONS")
        self.assertEqual(post_image("/api/icon-packs", platforms="").status_code, 422)

    def test_fit_must_be_pad_or_crop(self):
        response = post_image("/api/icon-packs", platforms="web", fit="stretch")
        self.assertEqual(response.status_code, 422)


class CollageRouteTests(unittest.TestCase):
    def layout(self, **overrides):
        values = dict(columns=2, cell_width=16, cell_height=16, fit="contain", gap=0, padding=0, background="#FFFFFF", format="png")
        values.update(overrides)
        return json.dumps(values)

    def test_upload_order_is_kept_and_headers_are_sent(self):
        red = encode(Image.new("RGB", (16, 16), (255, 0, 0)))
        green = encode(Image.new("RGB", (16, 16), (0, 255, 0)))
        response = client.post(
            "/api/image-collages",
            data={"layout": self.layout()},
            files=[("files", ("r.png", red, "image/png")), ("files", ("g.png", green, "image/png"))],
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual((response.headers["X-OfficeKit-Image-Width"], response.headers["X-OfficeKit-Image-Height"]), ("32", "16"))
        output = decode(response.content).convert("RGB")
        self.assertEqual(output.getpixel((8, 8)), (255, 0, 0))
        self.assertEqual(output.getpixel((24, 8)), (0, 255, 0))

    def test_too_few_images_and_canvas_overflow_are_422(self):
        one = [("files", ("r.png", PNG, "image/png"))]
        response = client.post("/api/image-collages", data={"layout": self.layout()}, files=one)
        self.assertEqual(response.status_code, 422)
        response = client.post(
            "/api/image-collages",
            data={"layout": self.layout(columns=10, cell_width=4000)},
            files=[("files", ("a.png", PNG, "image/png")), ("files", ("b.png", PNG, "image/png"))] * 5,
        )
        self.assertEqual((response.status_code, response.json()["code"]), (422, "CANVAS_TOO_LARGE"))

    def test_layout_bounds_are_strict(self):
        files = [("files", ("a.png", PNG, "image/png")), ("files", ("b.png", PNG, "image/png"))]
        for overrides in ({"cell_width": 15}, {"cell_width": 4001}, {"columns": 11}, {"gap": 201}, {"background": "red"}, {"unknown": 1}):
            with self.subTest(overrides=overrides):
                response = client.post("/api/image-collages", data={"layout": self.layout(**overrides)}, files=files)
                self.assertEqual(response.status_code, 422)

    def test_layout_text_over_four_kib_is_rejected_before_parsing(self):
        files = [("files", ("a.png", PNG, "image/png")), ("files", ("b.png", PNG, "image/png"))]
        oversized = json.dumps({**json.loads(self.layout()), "pad": "x" * (4 * 1024)})
        response = client.post("/api/image-collages", data={"layout": oversized}, files=files)
        self.assertEqual((response.status_code, response.json()["code"]), (422, "INVALID_OPTIONS"))

    def test_preview_is_png_within_the_edge(self):
        files = [("files", ("a.png", encode(Image.new("RGB", (400, 400))), "image/png")), ("files", ("b.png", encode(Image.new("RGB", (400, 400))), "image/png"))]
        response = client.post(
            "/api/image-collages",
            data={"layout": self.layout(cell_width=400, cell_height=400), "preview_max_edge": "128"},
            files=files,
        )
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(max(decode(response.content).size), 128)


class ContactSheetRouteTests(unittest.TestCase):
    def sheet(self, **overrides):
        values = dict(page="a4", orientation="portrait", columns=2, rows=2, show_names=True, format="pdf")
        values.update(overrides)
        return json.dumps(values)

    def test_pdf_and_zip_return_page_count_headers(self):
        files = [("files", (f"s{index}.png", PNG, "image/png")) for index in range(5)]
        response = client.post("/api/contact-sheets", data={"sheet": self.sheet()}, files=files)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertEqual(response.headers["X-OfficeKit-Page-Count"], "2")
        response = client.post("/api/contact-sheets", data={"sheet": self.sheet(format="png-zip")}, files=files)
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertEqual(response.headers["X-OfficeKit-Page-Count"], "2")

    def test_file_count_and_sheet_bounds_are_checked(self):
        too_many = [("files", (f"s{index}.png", PNG, "image/png")) for index in range(201)]
        response = client.post("/api/contact-sheets", data={"sheet": self.sheet()}, files=too_many)
        self.assertEqual(response.status_code, 422)
        files = [("files", ("s.png", PNG, "image/png"))]
        for overrides in ({"columns": 11}, {"rows": 21}, {"page": "b5"}, {"format": "tiff"}):
            with self.subTest(overrides=overrides):
                response = client.post("/api/contact-sheets", data={"sheet": self.sheet(**overrides)}, files=files)
                self.assertEqual(response.status_code, 422)

    def test_contact_sheet_inputs_share_the_128_mib_budget(self):
        # QA-4: the shared input budget is enforced across files, not per file.
        files = [("files", ("a.png", PNG, "image/png")), ("files", ("b.png", PNG, "image/png"))]
        with mock.patch.object(image_routes, "MAX_CONTACT_SHEET_INPUT_BYTES", len(PNG) + len(PNG) - 1):
            response = client.post("/api/contact-sheets", data={"sheet": self.sheet()}, files=files)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json()["code"], "TOO_LARGE_INPUT")

    def test_contact_sheet_first_page_preview_is_an_inline_png(self):
        files = [("files", ("a.png", PNG, "image/png"))]
        response = client.post("/api/contact-sheets", data={"sheet": self.sheet(preview_first_page=True)}, files=files)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertNotIn("content-disposition", response.headers)
        self.assertEqual(response.headers["X-OfficeKit-Page-Count"], "1")

    def test_contact_sheet_body_cap_is_the_128_mib_input_budget_plus_overhead(self):
        self.assertEqual(
            image_routes.BODY_LIMITS["/api/contact-sheets"],
            128 * 1024 * 1024 + 4 * 1024 * 1024,
        )
        self.assertEqual(image_routes.MAX_CONTACT_SHEET_INPUT_BYTES, 128 * 1024 * 1024)


class ComparisonRouteTests(unittest.TestCase):
    def test_identical_images_report_no_changes_and_no_identity_wording(self):
        response = client.post(
            "/api/image-comparisons",
            files={"image_a": ("a.png", PNG, "image/png"), "image_b": ("b.png", PNG, "image/png")},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body["changed_pixels"], body["comparable"]), (0, True))
        self.assertNotIn("identical", response.text.lower())

    def test_size_mismatch_is_not_comparable_until_scaled(self):
        other = encode(Image.new("RGB", (8, 6), (200, 30, 30)))
        response = client.post(
            "/api/image-comparisons",
            files={"image_a": ("a.png", PNG, "image/png"), "image_b": ("b.png", other, "image/png")},
        )
        self.assertFalse(response.json()["comparable"])
        response = client.post(
            "/api/image-comparisons",
            data={"alignment": "scale-b-to-a"},
            files={"image_a": ("a.png", PNG, "image/png"), "image_b": ("b.png", other, "image/png")},
        )
        self.assertTrue(response.json()["scaled_b"])

    def test_alignment_and_threshold_bounds(self):
        files = {"image_a": ("a.png", PNG, "image/png"), "image_b": ("b.png", PNG, "image/png")}
        self.assertEqual(client.post("/api/image-comparisons", data={"alignment": "rotate"}, files=files).status_code, 422)
        self.assertEqual(client.post("/api/image-comparisons", data={"threshold": "256"}, files=files).status_code, 422)
        self.assertEqual(client.post("/api/image-comparisons", data={"threshold": "255"}, files=files).status_code, 200)

    def test_non_image_part_is_415(self):
        response = client.post(
            "/api/image-comparisons",
            files={"image_a": ("a.txt", b"x", "text/plain"), "image_b": ("b.png", PNG, "image/png")},
        )
        self.assertEqual(response.status_code, 415)


if __name__ == "__main__":
    unittest.main()
