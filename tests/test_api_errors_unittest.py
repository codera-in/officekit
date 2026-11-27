"""Safe client-facing server error payload and handler boundary tests."""

import ast
import unittest
from pathlib import Path

from officekit.engines.engine_api_errors import internal_error_payload


ROOT = Path(__file__).resolve().parents[1]


class ApiErrorTests(unittest.TestCase):
    def test_internal_error_payload_is_generic_and_contains_no_runtime_details(self):
        payload = internal_error_payload()

        self.assertEqual(
            payload,
            {"error": {"code": "internal_error", "message": "The operation could not be completed. Try again."}},
        )
        self.assertNotIn("traceback", str(payload).lower())
        self.assertNotIn("diagnostic", str(payload).lower())

    def test_global_handler_uses_the_safe_payload_without_serializing_exception(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        handler = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "safe_internal_error_handler"
        )
        body = ast.unparse(handler)

        self.assertIn("internal_error_payload()", body)
        self.assertNotIn("str(exc)", body)
        self.assertNotIn("traceback", body)
        self.assertNotIn("exc.__traceback__", body)

    def test_file_conversion_routes_only_expose_controlled_input_errors(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        conversion_routes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name in {"convert_image_endpoint", "convert_data_endpoint"}
        }

        self.assertEqual(set(conversion_routes), {"convert_image_endpoint", "convert_data_endpoint"})
        for route in conversion_routes.values():
            with self.subTest(route=route.name):
                handlers = [node for node in ast.walk(route) if isinstance(node, ast.ExceptHandler)]
                self.assertTrue(handlers, "conversion failures must be handled explicitly")
                allowed_errors = {"ConversionInputError"}
                if route.name == "convert_image_endpoint":
                    allowed_errors.add("ImageOutputLimitError")
                self.assertTrue(
                    all(
                        isinstance(handler.type, ast.Name)
                        and handler.type.id in allowed_errors
                        for handler in handlers
                    ),
                    "routes must map only declared safe domain exceptions; unexpected errors use the generic 500 handler",
                )
                exposed_exception_details = [
                    call
                    for call in ast.walk(route)
                    if isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "str"
                    and call.args
                    and isinstance(call.args[0], ast.Name)
                    and call.args[0].id == "error"
                ]
                self.assertFalse(exposed_exception_details)

    def test_image_conversion_quality_is_constrained_at_the_http_boundary(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        route = next(
            node for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "convert_image_endpoint"
        )
        quality = next(arg for arg in route.args.args if arg.arg == "quality")
        form = quality.annotation
        self.assertIsInstance(form, ast.Name)
        self.assertEqual(form.id, "int")
        default = route.args.defaults[-1]
        self.assertIsInstance(default, ast.Call)
        self.assertIsInstance(default.func, ast.Name)
        self.assertEqual(default.func.id, "Form")
        constraints = {keyword.arg: ast.literal_eval(keyword.value) for keyword in default.keywords}
        self.assertEqual(constraints["ge"], 1)
        self.assertEqual(constraints["le"], 100)

    def test_uploaded_file_downloads_use_the_safe_attachment_filename_builder(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        conversion_routes = {
            node.name: node
            for node in tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name in {
                "convert_image_endpoint", "convert_data_endpoint",
                "api_unlock_pdf", "api_protect_pdf",
            }
        }

        self.assertEqual(
            set(conversion_routes),
            {"convert_image_endpoint", "convert_data_endpoint", "api_unlock_pdf", "api_protect_pdf"},
        )
        for route in conversion_routes.values():
            with self.subTest(route=route.name):
                calls = [
                    node for node in ast.walk(route)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "content_disposition_attachment"
                ]
                self.assertEqual(len(calls), 1)

    def test_pdf_engine_failures_do_not_serialize_library_exceptions(self):
        source = (ROOT / "officekit/engines/engine_pdf_security.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = {
            node.name: node
            for class_node in tree.body
            if isinstance(class_node, ast.ClassDef) and class_node.name == "PdfSecurityEngine"
            for node in class_node.body
            if isinstance(node, ast.FunctionDef)
        }

        for name in ("remove_password", "protect_pdf", "merge_pdfs", "split_pdf"):
            with self.subTest(method=name):
                method = methods[name]
                calls_to_stringify_exceptions = [
                    node for node in ast.walk(method)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "str"
                ]
                self.assertFalse(calls_to_stringify_exceptions)
                exception_handlers = [
                    node for node in ast.walk(method) if isinstance(node, ast.ExceptHandler)
                ]
                self.assertTrue(exception_handlers)
                self.assertTrue(all(handler.name is None for handler in exception_handlers))
                self.assertFalse(
                    any(
                        isinstance(node, ast.JoinedStr)
                        for handler in exception_handlers
                        for node in ast.walk(handler)
                    )
                )

    def test_pdf_engine_uses_one_fixed_processing_error_for_failure_messages(self):
        source = (ROOT / "officekit/engines/engine_pdf_security.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        engine = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "PdfSecurityEngine"
        )
        module_messages = [
            node.value for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "PDF_PROCESSING_ERROR" for target in node.targets)
        ]
        self.assertEqual(len(module_messages), 1)
        self.assertIsInstance(module_messages[0], ast.Constant)
        self.assertIsInstance(module_messages[0].value, str)
        for method in engine.body:
            if isinstance(method, ast.FunctionDef) and method.name in {
                "remove_password", "protect_pdf", "merge_pdfs", "split_pdf"
            }:
                references = [
                    node for node in ast.walk(method)
                    if isinstance(node, ast.Name) and node.id == "PDF_PROCESSING_ERROR"
                ]
                self.assertEqual(len(references), 1, method.name)

    def test_pdf_passwords_are_bounded_at_http_and_engine_boundaries(self):
        app_tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        validation_tree = ast.parse((ROOT / "officekit/engines/engine_pdf_validation.py").read_text(encoding="utf-8"))
        password_limit = next(
            ast.literal_eval(node.value)
            for node in validation_tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "MAX_PDF_PASSWORD_CHARACTERS"
                for target in node.targets
            )
        )
        routes = {
            node.name: node
            for node in app_tree.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name in {"api_unlock_pdf", "api_protect_pdf"}
        }
        self.assertEqual(set(routes), {"api_unlock_pdf", "api_protect_pdf"})
        for route_name, minimum in (("api_unlock_pdf", None), ("api_protect_pdf", 1)):
            route = routes[route_name]
            password = next(arg for arg in route.args.args if arg.arg == "password")
            default = next(
                item for item in route.args.defaults
                if isinstance(item, ast.Call)
                and isinstance(item.func, ast.Name)
                and item.func.id == "Form"
                and item.args
            )
            constraints = {
                keyword.arg: (
                    password_limit
                    if isinstance(keyword.value, ast.Name)
                    and keyword.value.id == "MAX_PDF_PASSWORD_CHARACTERS"
                    else ast.literal_eval(keyword.value)
                )
                for keyword in default.keywords
            }
            self.assertEqual(constraints.get("max_length"), password_limit)
            self.assertEqual(constraints.get("min_length"), minimum)

        pdf_engine = ast.parse((ROOT / "officekit/engines/engine_pdf_security.py").read_text(encoding="utf-8"))
        methods = {
            node.name: node
            for class_node in pdf_engine.body
            if isinstance(class_node, ast.ClassDef) and class_node.name == "PdfSecurityEngine"
            for node in class_node.body
            if isinstance(node, ast.FunctionDef)
        }
        for name in ("remove_password", "protect_pdf"):
            with self.subTest(method=name):
                self.assertTrue(
                    any(
                        isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "is_valid_pdf_password"
                        for node in ast.walk(methods[name])
                    )
                )


if __name__ == "__main__":
    unittest.main()
