import asyncio
import io
import json
import re
import unittest
from types import SimpleNamespace
from unittest import mock

from fastapi import APIRouter, HTTPException, UploadFile

import app as officekit_app
from officekit import routes, tool_catalog
from officekit.routes import common as route_common
from officekit.tool_catalog import __main__ as catalog_cli
from officekit.engines.engine_comms import TOOL_REGISTRY, TOOL_SEARCH_KEYWORDS


def slice_module(**attributes):
    return SimpleNamespace(**attributes)


class ToolCatalogSlotTests(unittest.TestCase):
    def test_slices_merge_in_fixed_order(self):
        first = slice_module(TOOLS=[{"id": "a"}], KEYWORDS={"a": ["alpha"]})
        second = slice_module(TOOLS=[{"id": "b"}, {"id": "c"}], KEYWORDS={"b": ["beta"]})
        with mock.patch.object(tool_catalog, "SLICES", (first, second)):
            self.assertEqual([tool["id"] for tool in tool_catalog.slice_tools()], ["a", "b", "c"])
            self.assertEqual(tool_catalog.slice_keywords(), {"a": ["alpha"], "b": ["beta"]})

    def test_registry_includes_every_slice_tool_once(self):
        ids = [tool["id"] for tool in TOOL_REGISTRY]
        self.assertEqual(len(ids), len(set(ids)))
        for tool in tool_catalog.slice_tools():
            self.assertIn(tool["id"], ids)
        self.assertLessEqual(set(tool_catalog.slice_keywords()), set(TOOL_SEARCH_KEYWORDS))


class SharedRouteHelperTests(unittest.TestCase):
    def test_app_uses_the_shared_limits_and_message(self):
        self.assertEqual(officekit_app.MAX_API_UPLOAD_BYTES, route_common.MAX_API_UPLOAD_BYTES)
        self.assertEqual(officekit_app.MAX_MULTIPART_OVERHEAD_BYTES, route_common.MAX_MULTIPART_OVERHEAD_BYTES)
        self.assertEqual(officekit_app.PDF_INPUT_ERROR_MESSAGE, route_common.PDF_INPUT_ERROR_MESSAGE)

    def test_read_api_upload_returns_bytes_and_maps_oversize_to_413(self):
        upload = UploadFile(io.BytesIO(b"abc"), filename="a.bin")
        self.assertEqual(asyncio.run(route_common.read_api_upload(upload)), b"abc")
        with mock.patch.object(route_common, "MAX_API_UPLOAD_BYTES", 2):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(route_common.read_api_upload(UploadFile(io.BytesIO(b"abc"), filename="a.bin")))
        self.assertEqual(raised.exception.status_code, 413)


class ToolCatalogCliTests(unittest.TestCase):
    def test_json_dump_lists_live_registry_and_slice_ids(self):
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            self.assertEqual(catalog_cli.main(["--json"]), 0)
        payload = json.loads(output.getvalue())
        self.assertEqual([tool["id"] for tool in payload["tools"]], [tool["id"] for tool in TOOL_REGISTRY])
        self.assertEqual(set(payload["slices"]), {"calculators", "developer", "files", "image", "pdf_tools", "invoices"})

    def test_other_arguments_print_usage(self):
        errors = io.StringIO()
        with mock.patch("sys.stderr", errors):
            self.assertEqual(catalog_cli.main([]), 2)
        self.assertIn("usage", errors.getvalue())


class RouterSlotTests(unittest.TestCase):
    def test_slices_merge_routers_limits_and_headers(self):
        first = slice_module(router=APIRouter(), BODY_LIMITS={"/api/a": 1}, EXPOSE_HEADERS=("X-A",))
        second = slice_module(router=APIRouter(), BODY_LIMITS={"/api/b": 2}, EXPOSE_HEADERS=())
        with mock.patch.object(routes, "SLICES", (first, second)):
            self.assertEqual(routes.slice_routers(), [first.router, second.router])
            self.assertEqual(routes.slice_body_limits(), {"/api/a": 1, "/api/b": 2})
            self.assertEqual(routes.slice_expose_headers(), ["X-A"])

    def test_duplicate_body_limit_paths_are_rejected(self):
        first = slice_module(BODY_LIMITS={"/api/a": 1})
        second = slice_module(BODY_LIMITS={"/api/a": 2})
        with mock.patch.object(routes, "SLICES", (first, second)):
            with self.assertRaisesRegex(ValueError, "/api/a"):
                routes.slice_body_limits()

    def test_slice_exposed_headers_are_officekit_scoped_and_unique(self):
        headers = routes.slice_expose_headers()
        self.assertEqual(len(headers), len(set(headers)))
        for header in headers:
            self.assertRegex(header, r"^X-OfficeKit-[A-Za-z0-9-]+$")

    def test_slice_body_limits_merge_without_overriding_core_limits(self):
        self.assertEqual(routes.merge_body_limits({"/api/core": 1}, {"/api/slice": 2}), {"/api/core": 1, "/api/slice": 2})
        with self.assertRaisesRegex(ValueError, "/api/core"):
            routes.merge_body_limits({"/api/core": 1}, {"/api/core": 2})
        for path, limit in routes.slice_body_limits().items():
            self.assertTrue(path.startswith("/api/"), path)
            self.assertIsInstance(limit, int)
            self.assertGreater(limit, 0)

    def test_every_slice_post_route_has_a_pre_parse_body_cap(self):
        limits = routes.slice_body_limits()
        for router in routes.slice_routers():
            for route in router.routes:
                if "POST" in getattr(route, "methods", set()):
                    pattern = re.sub(r"\{[^}]+\}", "*", route.path)
                    self.assertIn(pattern, limits, route.path)

    def test_every_slice_router_is_mounted(self):
        mounted = [getattr(route, "original_router", None) for route in officekit_app.app.routes]
        for router in routes.slice_routers():
            self.assertTrue(any(candidate is router for candidate in mounted))


if __name__ == "__main__":
    unittest.main()
