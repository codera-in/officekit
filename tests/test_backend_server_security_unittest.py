"""Configuration-level security regression tests; deliberately stdlib-only."""

import ast
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_SOURCES = (REPO_ROOT / "app.py", REPO_ROOT / "desktop_main.py", REPO_ROOT / "backend_main.py")


def call_by_attribute(tree, attribute):
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attribute
    ]


def keyword_value(call, name):
    keyword = next(item for item in call.keywords if item.arg == name)
    return ast.literal_eval(keyword.value)


class BackendServerSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.trees = [ast.parse(path.read_text(encoding="utf-8")) for path in APP_SOURCES]

    def test_cors_allows_native_origins_and_the_opted_in_isolated_test_origin_without_credentials(self):
        middleware_call = next(
            call for call in call_by_attribute(self.trees[0], "add_middleware")
            if call.args and isinstance(call.args[0], ast.Name)
            and call.args[0].id == "CORSMiddleware"
        )

        self.assertEqual(
            ast.unparse(next(item.value for item in middleware_call.keywords if item.arg == "allow_origins")),
            "sorted(trusted_api_origins(os.environ))",
        )
        self.assertFalse(keyword_value(middleware_call, "allow_credentials"))
        self.assertEqual(set(keyword_value(middleware_call, "allow_methods")), {"GET", "POST", "PUT", "PATCH", "DELETE"})
        exposed = next(item.value for item in middleware_call.keywords if item.arg == "expose_headers")
        starred = [element for element in exposed.elts if isinstance(element, ast.Starred)]
        # Slice routers may only add headers through the vetted slice merge;
        # tests/test_tool_slots_unittest.py checks those header names.
        self.assertEqual([ast.unparse(element) for element in starred], ["*slice_expose_headers()"])
        self.assertEqual(
            {ast.literal_eval(element) for element in exposed.elts if not isinstance(element, ast.Starred)},
            {
                "X-OfficeKit-Output-Input-Ratio",
                "X-OfficeKit-Page-Count",
                "X-OfficeKit-Image-Width",
                "X-OfficeKit-Image-Height",
                "X-OfficeKit-Selected-Pages",
                "X-OfficeKit-Missing-Text-Pages",
                "X-OfficeKit-Extracted-Characters",
                "X-PDF-Geometry",
                "Content-Disposition",
                "Content-Length",
            },
        )

    def test_api_origin_middleware_rejects_unknown_browser_origins(self):
        middleware = next(
            node for node in ast.walk(self.trees[0])
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name == "restrict_untrusted_browser_origins"
        )
        source = (REPO_ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn("is_trusted_api_origin(origin, os.environ)", source)
        self.assertIn("status_code=403", ast.unparse(middleware))
        self.assertIn("request.url.path.startswith('/api/')", ast.unparse(middleware))

    def test_api_server_binds_only_to_loopback_without_reload_or_access_logs(self):
        server_calls = [
            call for tree in self.trees for call in call_by_attribute(tree, "run")
            if isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "uvicorn"
        ]

        self.assertEqual(len(server_calls), 3)
        for index, server_call in enumerate(server_calls):
            with self.subTest(source=server_call.lineno):
                self.assertEqual(keyword_value(server_call, "host"), "127.0.0.1")
                if index == 2:
                    self.assertEqual(ast.unparse(next(item.value for item in server_call.keywords if item.arg == "port")), "sidecar_api_port()")
                else:
                    self.assertEqual(keyword_value(server_call, "port"), 8000)
                self.assertFalse(keyword_value(server_call, "reload"))
                self.assertFalse(keyword_value(server_call, "access_log"))

    def test_bundled_sidecar_fails_closed_without_an_environment_token(self):
        source = (REPO_ROOT / "backend_main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        main_block = next(node for node in tree.body if isinstance(node, ast.If) and 'uvicorn.run' in ast.unparse(node))
        main_source = ast.unparse(main_block)

        self.assertIn("load_sidecar_api_token", source)
        self.assertIn("load_sidecar_api_token", main_source)
        self.assertLess(main_source.index('load_sidecar_api_token'), main_source.index('uvicorn.run'))
        freeze = next(node for node in tree.body if isinstance(node, ast.If) and 'freeze_support' in ast.unparse(node))
        app_import = next(node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module == 'app')
        self.assertLess(freeze.lineno, app_import.lineno)

    def test_packaged_api_requires_a_bearer_token_but_allows_cors_preflight(self):
        middleware = next(
            node for node in ast.walk(self.trees[0])
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "authenticate_officekit_api"
        )
        middleware_source = ast.unparse(middleware)
        source = (REPO_ROOT / "app.py").read_text(encoding="utf-8")

        self.assertIn("is_api_authorization_valid", middleware_source)
        self.assertIn("request.method != 'OPTIONS'", middleware_source)
        self.assertIn("status_code=401", middleware_source)
        self.assertIn('allow_headers=["Content-Type", "Authorization", "X-OfficeKit-Native-Grant"]', source)

    def test_tauri_provides_the_ephemeral_token_only_to_its_webview_and_sidecar(self):
        rust = (REPO_ROOT / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
        config = json.loads((REPO_ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))

        self.assertIn("Uuid::new_v4()", rust)
        self.assertIn('.env("OFFICEKIT_API_TOKEN", &api_token)', rust)
        self.assertIn("officekit_api_token", rust)
        self.assertTrue(config["app"]["withGlobalTauri"])


if __name__ == "__main__":
    unittest.main()
