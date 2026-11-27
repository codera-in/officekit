"""HTTP tests for the developer slice router, mounted on a fresh FastAPI app."""

import base64
import json
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from officekit.engines.engine_uploads import RequestBodyLimitMiddleware
from officekit.routes import developer
from officekit.routes.developer import BODY_LIMITS, FIXED_MESSAGES

MARKER = "ZZ-ECHO-MARKER-7431"


def build_client():
    app = FastAPI()
    app.add_middleware(RequestBodyLimitMiddleware, path_limits=BODY_LIMITS)
    app.include_router(developer.router)
    return TestClient(app)


class DeveloperRouteInventoryTests(unittest.TestCase):
    def post_paths(self):
        return {
            route.path
            for route in developer.router.routes
            if "POST" in getattr(route, "methods", set())
        }

    def test_body_caps_equal_the_post_route_inventory(self):
        self.assertEqual(set(BODY_LIMITS), self.post_paths())
        self.assertEqual(set(FIXED_MESSAGES), self.post_paths())

    def test_text_analyses_route_is_mounted_with_its_cap(self):
        self.assertIn("/api/developer/text-analyses", self.post_paths())
        self.assertEqual(BODY_LIMITS["/api/developer/text-analyses"], 8 * 1024 * 1024)

    def test_text_analyses_returns_graphemes_and_longest_line(self):
        client = build_client()
        response = client.post("/api/developer/text-analyses", json={"text": "é\nab"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["graphemes"], 4)
        self.assertEqual(response.json()["longest_line_graphemes"], 2)
        self.assertEqual(response.json()["lines"], 2)
        rejected = client.post("/api/developer/text-analyses", json={"text": "x", "extra": 1})
        self.assertEqual(rejected.json(), {"detail": FIXED_MESSAGES["/api/developer/text-analyses"]})

    def test_body_caps_are_positive_integers_and_no_headers_are_exposed(self):
        for path, limit in BODY_LIMITS.items():
            self.assertIs(type(limit), int, path)
            self.assertGreater(limit, 0, path)
        self.assertEqual(developer.EXPOSE_HEADERS, ())

    def test_every_success_response_has_a_typed_openapi_schema(self):
        app = FastAPI()
        app.include_router(developer.router)
        schema = app.openapi()
        for route in developer.router.routes:
            for method in route.methods:
                operation = schema["paths"][route.path][method.lower()]
                content = operation["responses"]["200"]["content"]["application/json"]["schema"]
                self.assertIn("$ref", content, (method, route.path))


class DeveloperRouteSuccessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = build_client()

    def post(self, path, body):
        return self.client.post(path, json=body)

    def test_json_diffs_success_and_no_location_header(self):
        response = self.post("/api/developer/json-diffs", {"original": '{"a":1,"b":2}', "changed": '{"b":2,"a":2}'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("location", response.headers)
        body = response.json()
        self.assertEqual(body["changes"], [{"path": "/a", "kind": "changed", "before": "1", "after": "2"}])
        self.assertEqual(body["counts"], {"added": 0, "removed": 0, "changed": 1, "type_changed": 0})
        self.assertFalse(body["equal"])

    def test_text_diffs_success_and_patch_shape(self):
        response = self.post("/api/developer/text-diffs", {"original": "a\nb\n", "changed": "a\nc\n"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([row["op"] for row in body["rows"]], ["equal", "change"])
        self.assertTrue(body["patch"].startswith("--- original\n+++ changed\n"))
        self.assertEqual(body["rows"][1]["left_no"], 2)
        self.assertNotIn("left_spans", body["rows"][0])
        self.assertEqual(body["line_endings"], {"original": "lf", "changed": "lf"})

    def test_text_case_success(self):
        response = self.post("/api/developer/text-case-conversions", {"text": "straße", "style": "upper", "locale": "de"})
        self.assertEqual(response.status_code, 422)
        response = self.post("/api/developer/text-case-conversions", {"text": "straße", "style": "upper"})
        self.assertEqual(response.json(), {"result": "STRASSE", "style": "upper", "locale": "root"})

    def test_timestamp_success(self):
        response = self.post(
            "/api/developer/timestamp-conversions",
            {"value": "0", "input_type": "unix_seconds", "target_zones": ["UTC"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["instant_utc"], "1970-01-01T00:00:00Z")
        self.assertEqual(response.json()["unix_microseconds"], "0")

    def test_time_zones_get_success_without_body(self):
        response = self.client.get("/api/developer/time-zones")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("UTC", body["zones"])
        self.assertLessEqual(len(body["zones"]), 1000)

    def test_uuids_success_for_each_version(self):
        for body in ({"version": 4, "count": 3}, {"version": 7, "count": 3}):
            response = self.post("/api/developer/uuids", body)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.json()["uuids"]), 3)
        response = self.post("/api/developer/uuids", {"version": 5, "namespace": "dns", "name": "python.org"})
        self.assertEqual(response.json()["uuids"], ["886313e1-3b8a-5372-9b90-0c9aee199e5d"])

    def test_qr_png_and_svg_success(self):
        png = self.post("/api/developer/qr-codes", {"payload": "https://example.com", "size_px": 256})
        self.assertEqual(png.status_code, 200)
        self.assertTrue(base64.b64decode(png.json()["data"]).startswith(b"\x89PNG"))
        svg = self.post("/api/developer/qr-codes", {"payload": "https://example.com", "format": "svg"})
        self.assertTrue(svg.json()["data"].startswith("<svg"))


class DeveloperRouteValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = build_client()

    def assert_fixed_422(self, path, body=None, raw=None):
        if raw is None:
            response = self.client.post(path, json=body)
        else:
            response = self.client.post(path, content=raw, headers={"content-type": "application/json"})
        self.assertEqual(response.status_code, 422, (path, body, raw))
        self.assertEqual(response.json(), {"detail": FIXED_MESSAGES[path]})
        self.assertNotIn(MARKER, response.text)
        return response

    def test_extra_fields_are_rejected_on_every_post_route(self):
        valid = {
            developer.JSON_DIFF_PATH: {"original": "1", "changed": "2"},
            developer.TEXT_DIFF_PATH: {"original": "a", "changed": "b"},
            developer.TEXT_CASE_PATH: {"text": "a", "style": "lower"},
            developer.TIMESTAMP_PATH: {"value": "0", "input_type": "unix_seconds", "target_zones": ["UTC"]},
            developer.UUIDS_PATH: {"version": 4},
            developer.QR_PATH: {"payload": "a"},
        }
        for path, body in valid.items():
            self.assert_fixed_422(path, dict(body, **{MARKER: 1}))

    def test_wrong_types_and_out_of_range_values_are_rejected(self):
        self.assert_fixed_422(developer.JSON_DIFF_PATH, {"original": 1, "changed": "2"})
        self.assert_fixed_422(developer.JSON_DIFF_PATH, {"original": "1", "changed": "2", "array_order": "sorted"})
        self.assert_fixed_422(developer.TEXT_DIFF_PATH, {"original": "a", "changed": "b", "unicode_nfc": "yes"})
        self.assert_fixed_422(developer.TEXT_DIFF_PATH, {"original": "a", "changed": "b", "context": 21})
        self.assert_fixed_422(developer.TEXT_DIFF_PATH, {"original": "a", "changed": "b", "context": "3"})
        self.assert_fixed_422(developer.TEXT_CASE_PATH, {"text": "a", "style": "shout"})
        self.assert_fixed_422(developer.TIMESTAMP_PATH, {"value": "", "input_type": "unix_seconds", "target_zones": ["UTC"]})
        self.assert_fixed_422(developer.TIMESTAMP_PATH, {"value": "0", "input_type": "unix_seconds", "target_zones": []})
        self.assert_fixed_422(developer.TIMESTAMP_PATH, {"value": "0", "input_type": "unix_seconds", "target_zones": ["UTC"] * 9})
        self.assert_fixed_422(developer.UUIDS_PATH, {"version": 3})
        self.assert_fixed_422(developer.UUIDS_PATH, {"version": 4, "count": 0})
        self.assert_fixed_422(developer.UUIDS_PATH, {"version": 4, "count": 1001})
        self.assert_fixed_422(developer.UUIDS_PATH, {"version": 4, "count": "2"})
        self.assert_fixed_422(developer.QR_PATH, {"payload": "a", "size_px": 127})
        self.assert_fixed_422(developer.QR_PATH, {"payload": "a", "error_correction": "X"})
        self.assert_fixed_422(developer.QR_PATH, {"payload": "a", "format": "gif"})

    def test_missing_fields_invalid_json_and_non_object_bodies(self):
        self.assert_fixed_422(developer.JSON_DIFF_PATH, {"original": "1"})
        self.assert_fixed_422(developer.QR_PATH, raw='{"payload": "' + MARKER)
        self.assert_fixed_422(developer.UUIDS_PATH, raw="[1, 2]")

    def test_engine_input_errors_map_to_the_fixed_message_without_echo(self):
        self.assert_fixed_422(developer.JSON_DIFF_PATH, {"original": '{"' + MARKER + '":1,"' + MARKER + '":2}', "changed": "{}"})
        self.assert_fixed_422(developer.TIMESTAMP_PATH, {"value": MARKER, "input_type": "unix_seconds", "target_zones": ["UTC"]})
        self.assert_fixed_422(developer.TIMESTAMP_PATH, {"value": "0", "input_type": "local_datetime", "target_zones": ["UTC"], "source_zone": MARKER})
        self.assert_fixed_422(developer.UUIDS_PATH, {"version": 5, "namespace": MARKER, "name": "a"})
        self.assert_fixed_422(developer.QR_PATH, {"payload": "é" * 1477, "error_correction": "L"})
        self.assert_fixed_422(developer.TEXT_DIFF_PATH, {"original": "a" * 1_048_577, "changed": "b"})

    def test_text_case_engine_limit_maps_to_the_text_message(self):
        self.assert_fixed_422(developer.TEXT_CASE_PATH, {"text": "ŉ" * 524_288, "style": "upper"})

    def test_uuid_body_cap_admits_the_largest_valid_escaped_name(self):
        self.assertEqual(BODY_LIMITS[developer.UUIDS_PATH], 8 * 1024)
        name = "\u0001" * developer.MAX_UUID_NAME_CHARS
        response = self.client.post(
            developer.UUIDS_PATH,
            json={"version": 5, "namespace": "dns", "name": name},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["uuids"]), 1)
        self.assert_fixed_422(
            developer.UUIDS_PATH,
            {"version": 5, "namespace": "dns", "name": name + "\u0001"},
        )

    def test_text_routes_accept_exactly_one_mebibyte_of_utf8(self):
        three_byte = "€" * 349_525
        response = self.client.post("/api/developer/text-analyses", json={"text": three_byte + "a"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["utf8_bytes"], 1_048_576)
        self.assert_fixed_422(developer.TEXT_ANALYSIS_PATH, {"text": three_byte + "ab"})

    def test_oversized_declared_body_is_rejected_with_413_before_parsing(self):
        oversized = b'{"version": 4, "count": 1, "name": "' + b"a" * (8 * 1024) + b'"}'
        response = self.client.post(
            developer.UUIDS_PATH,
            content=oversized,
            headers={"content-type": "application/json"},
        )
        self.assertEqual(response.status_code, 413)

    def test_normal_bodies_under_the_cap_are_accepted(self):
        response = self.client.post(developer.UUIDS_PATH, json={"version": 4, "count": 1000})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["uuids"]), 1000)

    def test_json_text_is_never_echoed_in_the_success_envelope_of_errors(self):
        response = self.client.post(developer.QR_PATH, json={"payload": MARKER * 200})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(json.loads(response.text), {"detail": FIXED_MESSAGES[developer.QR_PATH]})


if __name__ == "__main__":
    unittest.main()
