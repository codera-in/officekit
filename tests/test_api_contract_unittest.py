"""Keep the human-readable API surface inventory aligned with FastAPI routes."""

import ast
import re
import unittest
from pathlib import Path
from officekit.engines.engine_spreadsheet_safety import sanitize_spreadsheet_text
from officekit.engines.engine_units import UnitConverterEngine
from officekit.engines.engine_colors import ColorConverterEngine


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROUTE = re.compile(r"\| `(GET|POST|PUT|PATCH|DELETE) ([^`]+)` \|")


def documented_implemented_routes(contract):
    section = re.search(
        r"^## Implemented routes\s*$([\s\S]*?)(?=^## |\Z)",
        contract,
        re.MULTILINE,
    )
    if section is None:
        raise AssertionError("API contract must contain an Implemented routes section")
    return {(method, path) for method, path in CONTRACT_ROUTE.findall(section.group(1))}


def implemented_routes(source):
    tree = ast.parse(source)
    routes = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            method = decorator.func.attr.upper()
            if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"} or not decorator.args:
                continue
            path = decorator.args[0]
            if isinstance(path, ast.Constant) and isinstance(path.value, str):
                routes.add((method, path.value))
    return routes


class ApiContractTests(unittest.TestCase):
    def test_result_export_has_typed_format_options_and_documented_snapshot_contract(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("/api/export/result", app_source)
        self.assertTrue(any(
            isinstance(node, ast.ClassDef) and node.name == "ResultExportRequest"
            for node in tree.body
        ))
        self.assertIn('"/api/export/result": 8 * 1024 * 1024', app_source)
        self.assertIn('format: Literal["markdown", "html", "json", "csv", "xlsx", "pptx", "pdf", "png", "jpeg"]', app_source)
        self.assertIn('"csv": ("text/csv; charset=utf-8", "csv")', app_source)
        self.assertIn('"xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx")', app_source)
        self.assertIn('"pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx")', app_source)
        self.assertIn('"pdf": ("application/pdf", "pdf")', app_source)
        contract = (ROOT / "API-CONTRACT.md").read_text(encoding="utf-8")
        route_line = next(line for line in contract.splitlines() if "POST /api/export/result" in line)
        self.assertTrue(all(f"`{format_name}`" in route_line for format_name in ("markdown", "html", "json", "csv", "xlsx", "pptx", "pdf", "png", "jpeg")))
        self.assertIn("neutralizes spreadsheet formulas", route_line)

    def test_devtools_url_component_operations_are_typed_and_documented(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        model = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "DevToolsFormatRequest"
        )
        operation = next(
            node.annotation for node in model.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "operation"
        )
        self.assertEqual(operation.value.id, "Literal")
        operations = set(ast.literal_eval(operation.slice))
        self.assertTrue({"url_encode", "url_decode"}.issubset(operations))
        contract = (ROOT / "API-CONTRACT.md").read_text(encoding="utf-8")
        route_line = next(line for line in contract.splitlines() if "POST /api/devtools/process" in line)
        self.assertTrue(all(f"`{name}`" in route_line for name in ("url_encode", "url_decode")))

    def test_color_converter_api_models_and_contract_match_supported_formats(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("/api/colors/convert", source)
        for class_name in ("ColorConvertRequest", "ColorConvertResponse"):
            self.assertTrue(any(
                isinstance(node, ast.ClassDef) and node.name == class_name
                for node in tree.body
            ), class_name)
        request_model = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "ColorConvertRequest"
        )
        request_fields = {
            item.target.id: item
            for item in request_model.body
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
        }
        self.assertEqual(
            {
                keyword.arg: ast.literal_eval(keyword.value)
                for keyword in request_fields["value"].value.keywords
            },
            {"min_length": 1, "max_length": 128, "strict": True},
        )
        for field_name in ("source_format", "target_format"):
            literal = request_fields[field_name].annotation
            self.assertEqual(literal.value.id, "Literal")
            self.assertEqual(set(ast.literal_eval(literal.slice)), set(ColorConverterEngine.FORMATS))
        contract = (ROOT / "API-CONTRACT.md").read_text(encoding="utf-8")
        route_line = next(line for line in contract.splitlines() if "POST /api/colors/convert" in line)
        self.assertTrue(all(f"`{format_name}`" in route_line for format_name in ColorConverterEngine.FORMATS))

    def test_unit_converter_engine_and_typed_api_categories_stay_in_sync(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        expected = set(UnitConverterEngine.CONVERSION_TREES) | {"temperature"}
        for class_name in ("UnitsConvertRequest", "UnitsConvertResponse"):
            model = next(
                node for node in tree.body
                if isinstance(node, ast.ClassDef) and node.name == class_name
            )
            category = next(
                node.annotation for node in model.body
                if isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "category"
            )
            values = ast.literal_eval(category.slice)
            self.assertEqual(set(values), expected, class_name)
        contract = (ROOT / "API-CONTRACT.md").read_text(encoding="utf-8")
        route_line = next(line for line in contract.splitlines() if "POST /api/units/convert" in line)
        self.assertTrue(all(f"`{category}`" in route_line for category in expected))

    def test_spreadsheet_text_sanitizer_neutralizes_formula_and_control_prefixes(self):
        for marker in ("=", "+", "-", "@"):
            with self.subTest(marker=marker):
                self.assertEqual(sanitize_spreadsheet_text(f"{marker}1+1"), f"'{marker}1+1")
                self.assertEqual(sanitize_spreadsheet_text(f"  {marker}1+1"), f"'  {marker}1+1")
                self.assertEqual(sanitize_spreadsheet_text(f"\u00a0{marker}1+1"), f"'\u00a0{marker}1+1")
        for marker in ("\t", "\r", "\n", "\ufeff"):
            with self.subTest(marker=repr(marker)):
                self.assertEqual(sanitize_spreadsheet_text(f"{marker}=1+1"), f"'{marker}=1+1")
        self.assertEqual(sanitize_spreadsheet_text(" \u200b=1+1"), "' \u200b=1+1")
        self.assertEqual(sanitize_spreadsheet_text("\u00a0\ufeff=1+1"), "'\u00a0\ufeff=1+1")
        self.assertEqual(sanitize_spreadsheet_text("Client Invoice Payment"), "Client Invoice Payment")
        self.assertEqual(sanitize_spreadsheet_text("東京"), "東京")
        self.assertEqual(sanitize_spreadsheet_text("-"), "-")
        self.assertEqual(sanitize_spreadsheet_text("-1+cmd"), "'-1+cmd")
        self.assertEqual(sanitize_spreadsheet_text(""), "")
        self.assertIsNone(sanitize_spreadsheet_text(None))
        self.assertEqual(sanitize_spreadsheet_text(42), 42)

    def test_tabular_converter_sanitizes_cells_before_spreadsheet_exports(self):
        converter = (ROOT / "officekit/engines/engine_file_converter.py").read_text(encoding="utf-8")
        self.assertIn("from officekit.engines.engine_spreadsheet_safety import sanitize_spreadsheet_text", converter)
        self.assertIn(
            "if target_ext in {'csv', 'tsv', 'xlsx', 'excel'}:\n"
            "            df = df.map(sanitize_spreadsheet_text)",
            converter,
        )

    def test_contract_lists_exactly_the_routes_implemented_by_app(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        contract = (ROOT / "API-CONTRACT.md").read_text(encoding="utf-8")
        documented = documented_implemented_routes(contract)

        self.assertEqual(documented, implemented_routes(app_source))

    def test_hosted_licensing_routes_are_not_part_of_the_implemented_inventory(self):
        contract = (ROOT / "API-CONTRACT.md").read_text(encoding="utf-8")
        hosted = contract.split("## Hosted licensing API", 1)[1]
        documented = documented_implemented_routes(contract)

        self.assertIn("operated privately", " ".join(hosted.split()))
        self.assertNotIn(("POST", "/v1/license-activation-challenges"), documented)
        self.assertNotIn(("POST", "/v1/license-activations"), documented)

    def test_file_workspaces_expose_bounded_import_rename_extract_download_and_clear_routes(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        expected = {
            ("POST", "/api/workspaces"),
            ("GET", "/api/workspaces/{workspace_id}"),
            ("POST", "/api/workspaces/{workspace_id}/extractions"),
            ("POST", "/api/workspaces/{workspace_id}/splits"),
            ("POST", "/api/workspaces/{workspace_id}/joins"),
            ("POST", "/api/workspaces/{workspace_id}/rename-previews"),
            ("POST", "/api/workspaces/{workspace_id}/renamed-artifacts"),
            ("POST", "/api/workspaces/{workspace_id}/duplicate-reports"),
            ("POST", "/api/workspaces/{workspace_id}/storage-reports"),
            ("POST", "/api/workspaces/{workspace_id}/folder-comparisons"),
            ("POST", "/api/workspaces/{workspace_id}/similar-image-reports"),
            ("POST", "/api/workspaces/{workspace_id}/hash-reports"),
            ("POST", "/api/workspaces/{workspace_id}/file-type-reports"),
            ("GET", "/api/workspaces/{workspace_id}/artifacts/{artifact_id}"),
            ("DELETE", "/api/workspaces/{workspace_id}"),
        }

        self.assertTrue(expected.issubset(implemented_routes(app_source)))

    def test_file_split_join_routes_have_strict_typed_contracts_and_checksum_guards(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        workspace_source = (ROOT / "officekit/engines/engine_workspaces.py").read_text(encoding="utf-8")
        tree = ast.parse(app_source)
        required_models = {
            "WorkspaceSplitRequest", "WorkspaceJoinRequest",
            "WorkspaceSplitPartResponse", "WorkspaceSplitResponse", "WorkspaceJoinResponse",
        }
        self.assertTrue(required_models.issubset({
            node.name for node in tree.body if isinstance(node, ast.ClassDef)
        }))
        self.assertIn('"/api/workspaces/{workspace_id}/splits"', app_source)
        self.assertIn('"/api/workspaces/{workspace_id}/joins"', app_source)
        self.assertIn('ConfigDict(extra="forbid")', app_source)
        self.assertIn('zipfile.ZIP_STORED', workspace_source)
        self.assertIn('Split part checksum does not match its manifest', workspace_source)
        self.assertIn('Joined file checksum does not match its manifest', workspace_source)
        self.assertIn('getattr(os, "O_NOFOLLOW", 0)', workspace_source)
        contract = (ROOT / "API-CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("POST /api/workspaces/{workspace_id}/splits", contract)
        self.assertIn("POST /api/workspaces/{workspace_id}/joins", contract)

    def test_workspace_hash_route_is_typed_scoped_and_streaming(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        workspace_source = (ROOT / "officekit/engines/engine_workspaces.py").read_text(encoding="utf-8")
        self.assertIn('response_model=WorkspaceHashResponse', app_source)
        self.assertIn('algorithm: Literal["sha256", "sha512"] = "sha256"', app_source)
        self.assertIn('digest.update(chunk)', workspace_source)
        self.assertIn('source.read(FileWorkspaceStore.HASH_CHUNK_SIZE)', workspace_source)
        self.assertIn('getattr(os, "O_NOFOLLOW", 0)', workspace_source)

    def test_folder_comparison_route_is_bounded_and_reuses_workspace_hashing(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        workspace_source = (ROOT / "officekit/engines/engine_workspaces.py").read_text(encoding="utf-8")
        self.assertIn("class WorkspaceFolderComparisonRequest(BaseModel)", app_source)
        self.assertIn('response_model=WorkspaceFolderComparisonResponse', app_source)
        self.assertIn('self.hash_files(workspace_id, selected_names, algorithm="sha256")', workspace_source)
        self.assertIn("Compared folders exceed the workspace file-count limit", workspace_source)
        self.assertIn("folder-comparison summary does not match its file results", app_source.lower())

    def test_high_risk_calculators_have_exact_typed_routes(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        expected = {
            ("POST", "/api/calculator/loan-emi"),
            ("POST", "/api/calculator/compound-interest"),
            ("POST", "/api/calculator/vat-sales-tax"),
            ("POST", "/api/calculator/freelance-rate"),
            ("POST", "/api/calculator/break-even"),
            ("POST", "/api/calculator/margin-markup"),
            ("POST", "/api/calculator/depreciation"),
            ("POST", "/api/calculator/simple-interest"),
            ("POST", "/api/calculator/percent-of"),
            ("POST", "/api/calculator/percentage-change"),
            ("POST", "/api/calculator/discount"),
        }
        self.assertTrue(expected.issubset(implemented_routes(app_source)))
        self.assertIn("response_model=LoanResponse", app_source)
        self.assertIn("response_model=VatResponse", app_source)
        self.assertIn("response_model=FreelanceResponse", app_source)
        self.assertIn("response_model=CompoundInterestResponse", app_source)
        self.assertIn("response_model=BreakEvenResponse", app_source)
        self.assertIn("response_model=MarginMarkupResponse", app_source)
        self.assertIn("response_model=DepreciationResponse", app_source)
        self.assertIn("response_model=SimpleInterestResponse", app_source)
        self.assertIn("response_model=PercentOfResponse", app_source)
        self.assertIn("response_model=PercentageChangeResponse", app_source)
        self.assertIn("response_model=DiscountResponse", app_source)
        self.assertIn("response_model=MathEvalResponse", app_source)
        self.assertIn("response_model=UnitsConvertResponse", app_source)

    def test_tool_search_query_is_bounded_consistently_at_http_and_engine_boundaries(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        search_source = (ROOT / "officekit/engines/engine_comms.py").read_text(encoding="utf-8")
        self.assertIn('q: str = Query(default="", max_length=256)', app_source)
        self.assertIn("MAX_TOOL_SEARCH_QUERY_LENGTH = 256", search_source)
        self.assertIn('"keywords": TOOL_SEARCH_KEYWORDS.get(tool["id"], [])', search_source)

    def test_every_direct_file_route_uses_the_bounded_stream_reader(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        expected = {
            "extract_statement",
            "convert_image_endpoint",
            "api_strip_image_metadata",
            "list_data_conversion_sheets_endpoint",
            "convert_data_endpoint",
            "api_unlock_pdf",
            "api_protect_pdf",
        }
        observed = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in expected:
                continue
            if any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Name)
                and call.func.id == "read_api_upload"
                and call.args
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id == "file"
                for statement in node.body
                for call in ast.walk(statement)
            ):
                observed.add(node.name)
        self.assertEqual(observed, expected)

    def test_request_body_limits_cover_all_file_routes_and_selected_workspaces(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        expected = {
            "/api/extract/statement",
            "/api/convert/image",
            "/api/image/metadata",
            "/api/images/resize",
            "/api/screenshot/edit",
            "/api/privacy/pii/scan",
            "/api/privacy/pii/redact",
            "/api/convert/data",
            "/api/convert/data/sheets",
            "/api/pdf/unlock",
            "/api/pdf-documents",
            "/api/pdf-signing-providers",
            "/api/pdf-signing-providers/native",
            "/api/pdf-documents/*/revisions",
            "/api/pdf-documents/*/signatures",
            "/api/pdf-documents/*/ocr-reviews",
            "/api/pdf/protect",
            "/api/pdf/page-counts",
            "/api/pdf/merge",
            "/api/pdf/split",
            "/api/pdf/pages/delete",
            "/api/pdf/pages/reorder",
            "/api/pdf/split/groups",
            "/api/pdf/compress",
            "/api/pdf/metadata",
            "/api/pdf/images",
            "/api/pdf/page-thumbnails",
            "/api/pdf/tables",
            "/api/pdf/tables/export",
            "/api/pdf/text",
            "/api/devtools/process",
            "/api/crypto/hashes",
            "/api/workspaces",
            "/api/file-selections",
            "/api/file-output-grants",
            "/api/license/entitlement",
            "/api/file-jobs",
            "/api/file-jobs/*/cancellations",
            "/api/media-jobs",
            "/api/media-pipelines",
            "/api/media-preset-zones",
            "/api/media-preset-zones/*",
            "/api/media-image-stagings",
            "/api/media-watermark-stagings",
            "/api/media-import-previews",
            "/api/media-jobs/*/cancellations",
            "/api/storage-scans",
            "/api/storage-cleanup-plans",
            "/api/storage-cleanup-plans/*/execution",
            "/api/workspaces/*/extractions",
            "/api/workspaces/*/hash-reports",
            "/api/workspaces/*/file-type-reports",
            "/api/workspaces/*/folder-comparisons",
            "/api/workspaces/*/rename-previews",
            "/api/workspaces/*/renamed-artifacts",
            "/api/workspaces/*/splits",
            "/api/workspaces/*/joins",
            "/api/workspaces/*/duplicate-reports",
            "/api/workspaces/*/storage-reports",
            "/api/workspaces/*/similar-image-reports",
            "/api/export/csv",
            "/api/export/excel",
            "/api/export/xls",
            "/api/export/result",
            "/api/trash-restore-grants",
            "/api/trash-restorations",
        }
        observed = set()
        observed_limits = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != "add_middleware" or not node.args:
                continue
            middleware = node.args[0]
            if not isinstance(middleware, ast.Name) or middleware.id != "RequestBodyLimitMiddleware":
                continue
            for keyword in node.keywords:
                limits = keyword.value
                if keyword.arg == "path_limits" and isinstance(limits, ast.Call):
                    # Core caps merged with the slice routers' caps (checked in test_tool_slots_unittest).
                    self.assertEqual(ast.unparse(limits.func), "merge_body_limits")
                    self.assertEqual(ast.unparse(limits.args[1]), "slice_body_limits()")
                    limits = limits.args[0]
                if keyword.arg == "path_limits" and isinstance(limits, ast.Dict):
                    for key, value in zip(limits.keys, limits.values, strict=True):
                        if isinstance(key, ast.Constant) and isinstance(key.value, str):
                            observed.add(key.value)
                            observed_limits[key.value] = ast.unparse(value)
        self.assertEqual(observed, expected)
        self.assertEqual(
            observed_limits["/api/screenshot/edit"],
            "MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES",
        )
        self.assertEqual(observed_limits["/api/media-jobs"], "1024 * 1024")
        self.assertEqual(observed_limits["/api/media-preset-zones/*"], "16 * 1024")
        self.assertEqual(
            observed_limits["/api/media-image-stagings"],
            "MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES",
        )
        self.assertEqual(observed_limits["/api/media-import-previews"], "8 * 1024")
        self.assertEqual(observed_limits["/api/media-jobs/*/cancellations"], "1024")
        workspace_json_routes = {
            route for route in expected
            if route.startswith("/api/workspaces/*/")
        }
        self.assertEqual(
            {route: observed_limits[route] for route in workspace_json_routes},
            {route: "8 * 1024 * 1024" for route in workspace_json_routes},
        )

    def test_password_generator_has_typed_response_and_bounded_query(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('response_model=PasswordResponse', app_source)
        self.assertIn('length: int = Query(default=16, ge=12, le=256)', app_source)
        self.assertIn('password: str = PydanticField(min_length=12, max_length=256)', app_source)
        self.assertIn('theoretical_search_space_bits: float = PydanticField(gt=0, le=2048)', app_source)
        self.assertIn('PrivacySecurityEngine.password_search_space_bits(length, include_symbols)', app_source)

    def test_pdf_password_contract_matches_the_revision_six_normalized_utf8_limit(self):
        contract = (ROOT / "API-CONTRACT.md").read_text(encoding="utf-8")
        for route in ("/api/pdf/unlock", "/api/pdf/protect"):
            row = next(line for line in contract.splitlines() if f"`POST {route}`" in line)
            self.assertIn("NFKC-normalized UTF-8 encodings ≤127 bytes", row)
            self.assertNotIn("4,096 UTF-8 bytes", row)

    def test_hash_route_has_typed_outputs_and_bounded_strict_inputs(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('response_model=HashGenResponse, response_model_exclude_none=True', app_source)
        self.assertIn('text: str = PydanticField(max_length=PrivacySecurityEngine.MAX_HASH_INPUT_BYTES, strict=True)', app_source)
        self.assertIn('max_length=PrivacySecurityEngine.MAX_HMAC_SECRET_BYTES', app_source)
        self.assertIn('md5: str = PydanticField(pattern=r"^[0-9a-f]{32}$")', app_source)

    def test_devtools_route_has_bounded_operation_contract_and_typed_responses(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        engine_source = (ROOT / "officekit/engines/engine_devtools.py").read_text(encoding="utf-8")
        contract = (ROOT / "API-CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn('content: str = PydanticField(max_length=DevToolsEngine.MAX_TEXT_BYTES, strict=True)', app_source)
        self.assertIn('"yaml_to_json", "base64_encode", "base64_decode"', app_source)
        self.assertIn('"url_encode", "url_decode", "jwt_decode"', app_source)
        self.assertIn('response_model=DevToolsResultResponse | JwtDecodeResponse', app_source)
        self.assertIn('is_verified: Literal[False]', app_source)
        self.assertIn("MAX_JSON_DEPTH = 128", engine_source)
        self.assertIn("MAX_JSON_NODES = 100_000", engine_source)
        self.assertIn("JSON object keys must be unique", engine_source)
        self.assertIn("parse_float=parse_finite_decimal", engine_source)
        self.assertIn("decimal values retain precision and exponent range", contract)

    def test_support_contract_is_typed_bounded_paginated_and_local_only(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        engine_source = (ROOT / "officekit/engines/engine_comms.py").read_text(encoding="utf-8")
        contract = (ROOT / "API-CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn('ticket_type: Literal["bug", "support", "feature", "testimonial"]', app_source)
        self.assertIn('response_model=TicketResponse', app_source)
        self.assertIn('limit: int = Query(default=100, ge=1, le=100)', app_source)
        self.assertIn('os.replace(temporary_path, TICKETS_FILE)', engine_source)
        self.assertIn('ticket store is unreadable; existing data was preserved', engine_source)
        self.assertIn('Local application storage; atomic writes', contract)
        self.assertIn('display_name?, publication_consent?', contract)
        self.assertIn('saved_locally', contract)
        self.assertIn('legacy `received` records are represented as `saved_locally`', contract)

    def test_file_type_route_is_workspace_scoped_bounded_and_typed(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        workspace_source = (ROOT / "officekit/engines/engine_workspaces.py").read_text(encoding="utf-8")
        self.assertIn('response_model=FileTypeReportResponse', app_source)
        self.assertIn('StringConstraints(min_length=1, max_length=1024, strict=True)', app_source)
        self.assertIn('PydanticField(min_length=1, max_length=1000)', app_source)
        self.assertIn('source.read(FileTypeDetector.MAX_HEADER_BYTES)', workspace_source)
        self.assertIn('getattr(os, "O_NOFOLLOW", 0)', workspace_source)

    def test_statement_exports_use_bounded_typed_requests_and_safe_spreadsheet_text(self):
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        parser_source = (ROOT / "officekit/engines/engine_statement_exports.py").read_text(encoding="utf-8")
        parser_dispatch_source = (ROOT / "officekit/engines/engine_parser.py").read_text(encoding="utf-8")
        contract = (ROOT / "API-CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("class StatementExportTransaction(BaseModel)", app_source)
        self.assertIn("class StatementExportRequest(BaseModel)", app_source)
        self.assertIn("transactions: List[StatementExportTransaction] = PydanticField(default_factory=list, max_length=10_000)", app_source)
        self.assertIn('"/api/export/csv": 8 * 1024 * 1024', app_source)
        self.assertIn('"/api/export/excel": 8 * 1024 * 1024', app_source)
        self.assertIn("sanitize_spreadsheet_text", parser_source)
        self.assertGreaterEqual(parser_source.count("prepare_statement_export_rows(transactions)"), 2)
        self.assertIn("from officekit.engines.engine_statement_exports import export_to_csv, export_to_excel", parser_dispatch_source)
        self.assertIn("spreadsheet-formula injection", contract.lower())
        self.assertIn("10,000 objects", contract)
        self.assertIn('status: Literal["ok", "reconciliation_warning", "baseline", "unverified"]', app_source)

    def test_statement_reconciliation_contract_is_explicitly_tristate(self):
        contract = (ROOT / "API-CONTRACT.md").read_text(encoding="utf-8")
        route = next(line for line in contract.splitlines() if "POST /api/extract/statement" in line)
        self.assertIn('`verified`, `partial`, `discrepancy` or `unverified`', route)
        self.assertIn('`valid`: true, false or null', route)
        self.assertIn("number_locale", route)
        self.assertIn("date_order", route)
        self.assertIn("en-US", route)
        self.assertIn("en-IN", route)
        self.assertIn("de-DE", route)
        self.assertIn("fr-FR", route)
        self.assertIn("DMY", route)
        self.assertIn("MDY", route)
        self.assertIn('`baseline` or `unverified`', contract)

    def test_native_dictation_permissions_hotkey_and_paste_are_declared(self):
        contract = (ROOT / "API-CONTRACT.md").read_text(encoding="utf-8")
        rust = (ROOT / "src-tauri/src/lib.rs").read_text(encoding="utf-8")
        swift = (ROOT / "src-tauri/macos-dictation.swift").read_text(encoding="utf-8")
        for command in (
            "dictation_accessibility_permission",
            "dictation_request_accessibility_permission",
            "dictation_hotkey_status",
            "dictation_hotkey_enable",
            "dictation_hotkey_disable",
            "dictation_paste_text",
            "dictation_cleanup_and_paste",
        ):
            self.assertIn(f"`{command}`", contract)
            self.assertIn(command, rust)
        self.assertIn("officekit_dictation_paste_text", swift)
        self.assertIn("262,144 UTF-8 bytes", contract)
        self.assertIn("restores the prior clipboard contents", contract)
        self.assertNotIn("asyncAfter(deadline: .now() + .milliseconds(750)", swift)
        self.assertIn("Retain the complete transcript", swift)
        self.assertIn("target-changed-clipboard-retained", rust)
        self.assertIn("POST /api/dictate/cleanup", contract)
        self.assertIn("authenticated `POST /api/dictate/cleanup` at `127.0.0.1:8000`", contract)

    def test_statement_export_routes_reject_untyped_or_unbounded_payloads(self):
        tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
        routes = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                if decorator.func.attr == "post" and decorator.args and isinstance(decorator.args[0], ast.Constant):
                    routes[decorator.args[0].value] = node
        for path in ("/api/export/csv", "/api/export/excel", "/api/export/xls"):
            args = routes[path].args.args
            self.assertGreaterEqual(len(args), 1)
            self.assertEqual(ast.unparse(args[0].annotation), "StatementExportRequest")


if __name__ == "__main__":
    unittest.main()
