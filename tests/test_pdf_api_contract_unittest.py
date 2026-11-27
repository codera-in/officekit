import ast
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
APP_SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")
APP_TREE = ast.parse(APP_SOURCE)


class PdfApiContractTests(unittest.TestCase):
    def test_advertised_advanced_pdf_operations_have_bounded_http_routes(self):
        expected = {
            "/api/pdf/merge": ("AdvancedPdfEngine.merge_multiple", "/api/pdf/merge"),
            "/api/pdf/split": ("AdvancedPdfEngine.split_by_ranges", "/api/pdf/split"),
            "/api/pdf/pages/delete": ("AdvancedPdfEngine.delete_pages", "/api/pdf/pages/delete"),
            "/api/pdf/pages/reorder": ("AdvancedPdfEngine.reorder_pages", "/api/pdf/pages/reorder"),
            "/api/pdf/split/groups": ("AdvancedPdfEngine.split_by_groups", "/api/pdf/split/groups"),
            "/api/pdf/compress": ("AdvancedPdfEngine.compress_pdf", "/api/pdf/compress"),
            "/api/pdf/metadata": ("AdvancedPdfEngine.strip_metadata", "/api/pdf/metadata"),
            "/api/pdf/page-thumbnails": ("PdfImageExportEngine.render_page_thumbnails", "/api/pdf/page-thumbnails"),
            "/api/pdf/images": ("PdfImageExportEngine.render_pdf", "/api/pdf/images"),
        }
        routes = {}
        for node in APP_TREE.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "app":
                    continue
                if decorator.func.attr != "post" or not decorator.args:
                    continue
                path = decorator.args[0]
                if isinstance(path, ast.Constant) and isinstance(path.value, str):
                    routes[path.value] = node

        for route, (engine_method, body_limit_path) in expected.items():
            with self.subTest(route=route):
                self.assertTrue(route in routes, f"{route} must expose an advertised PDF engine operation")
                source = ast.get_source_segment(APP_SOURCE, routes[route])
                self.assertIn(engine_method, source)
                self.assertIn(body_limit_path, APP_SOURCE)

    def test_advanced_pdf_routes_map_bad_inputs_to_a_safe_422(self):
        expected_routes = {
            "/api/pdf/merge", "/api/pdf/split", "/api/pdf/pages/delete",
            "/api/pdf/pages/reorder", "/api/pdf/split/groups", "/api/pdf/compress",
            "/api/pdf/metadata", "/api/pdf/page-thumbnails", "/api/pdf/images",
        }
        route_nodes = []
        for node in APP_TREE.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == "app"
                        and decorator.func.attr == "post" and decorator.args
                        and isinstance(decorator.args[0], ast.Constant)
                        and decorator.args[0].value in expected_routes):
                    route_nodes.append(node)
        self.assertEqual({
            decorator.args[0].value
            for node in route_nodes
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
            and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == "app"
            and decorator.func.attr == "post" and decorator.args
            and isinstance(decorator.args[0], ast.Constant)
        }, expected_routes)
        for node in route_nodes:
            with self.subTest(route=node.name):
                self.assertTrue(any(
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "HTTPException"
                    and any(keyword.arg == "status_code" and isinstance(keyword.value, ast.Constant)
                            and keyword.value.value == 422 for keyword in child.keywords)
                    for child in ast.walk(node)
                ), "malformed PDF input must become a safe 422, not a false success or raw 500")


if __name__ == "__main__":
    unittest.main()
