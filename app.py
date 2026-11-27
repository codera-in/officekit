"""
OmniConvert - FastAPI Server & Web Application
Mother of All Converters & Office Tools:
- Bank Statement & Tabular PDF/Image extraction to CSV/Excel
- Image to Image / PDF Converter
- Data format converters (CSV, Excel, JSON, TSV)
- Financial & Business Calculators (Loan EMI, Compound Interest, VAT, Freelance Rate)
"""

import os
import io
import json
import atexit
import logging
import re
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional, Dict, Any, List, Literal, Union
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response, HTMLResponse, JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field as PydanticField, StringConstraints, StrictBool, StrictFloat, StrictInt, StrictStr, ValidationError, field_validator, model_validator
from PIL import Image

from officekit.engines.engine_statement_input import StatementInputError, parse_statement_delimited
from officekit.engines.engine_calculators import CalculatorEngine
from officekit.engines.engine_file_converter import FileConverterEngine, ImageOutputLimitError, ImageWorkLimitError
from officekit.engines.engine_pdf_validation import (
    MAX_PDF_PASSWORD_CHARACTERS,
    is_valid_pdf_password,
)
from officekit.engines.engine_conversion_errors import ConversionInputError
from officekit.engines.engine_file_responses import content_disposition_attachment
from officekit.engines.engine_result_exports import ResultExportEngine
from officekit.engines.engine_api_security import (
    TRUSTED_API_HOSTS,
    TRUSTED_DESKTOP_ORIGINS,
    dev_unlock_enabled,
    is_api_authorization_valid,
    is_trusted_api_origin,
    resolve_api_auth_token,
    trusted_api_origins,
)
from officekit.engines.engine_api_errors import internal_error_payload
from officekit.engines.engine_release_profile import load_release_profile, ReleaseScopeMiddleware
from officekit.engines.engine_license_gate import (
    GATE_STATE,
    MAX_ENTITLEMENT_BODY_BYTES,
    NATIVE_GRANT_HEADER,
    EntitlementPushRequest,
    ErrorEnvelope,
    LicenseStatusResponse,
    ReleaseResponse,
    feature_for_route,
    feature_not_licensed_payload,
    invalid_entitlement_payload,
    is_free_route,
    is_gate_exempt,
    is_native_grant_valid,
    license_required_payload,
    load_native_grant_token,
    native_grant_required_payload,
)
from officekit.engines.engine_workspaces import FileWorkspaceStore, WorkspaceLimitError
from officekit.engines.engine_file_selections import FileSelectionStore, identity
from officekit.engines.engine_pdf_workspace import PdfWorkspace
from officekit.pdf_workspace_routes import create_pdf_router
from officekit.invoices.routes import create_invoice_router, BODY_LIMITS as INVOICE_BODY_LIMITS
from officekit.invoices.storage import InvoiceLibraries, invoice_bindings_path
from officekit.engines.engine_file_jobs import FileJobStore, SelectionRequest, OutputGrantRequest, FileJobRequest, ReleaseScopeError
from officekit.engines.engine_trash_restore import (
    TrashRecordPage,
    TrashRestoration,
    TrashRestoreGrant,
    TrashRestorer,
    TrashRestoreGrantRequest,
    TrashRestoreRequest,
)
from officekit.engines import engine_archive_manager
from officekit.engines.engine_media_jobs import MediaJobStore
from officekit.media_routes import create_media_router
from officekit.routes import merge_body_limits, slice_body_limits, slice_expose_headers, slice_routers
from officekit.routes.common import MAX_API_UPLOAD_BYTES, MAX_MULTIPART_OVERHEAD_BYTES, PDF_INPUT_ERROR_MESSAGE
from officekit.engines.engine_media_import import MediaImportStore
from officekit.engines.engine_media_staging import MediaStagingStore
from officekit.engines.engine_media_pipelines import MediaPipelineStore, media_pipeline_path
from officekit.engines.engine_media_folder_automation import MediaFolderAutomationStore
from officekit.engines.engine_media_preset_zones import MediaPresetZoneStore
from officekit.engines.engine_media_operation_defaults import MediaOperationDefaultsStore
from officekit.engines.engine_media_pipeline_triggers import MediaPipelineTriggerStore
from officekit.engines.engine_storage_cleaner import (
    storage_cleaner, ScanRequest, PlanRequest, EmptyRequest,
    StorageStatus, StoragePlan, StorageExecution, StorageCancellation, StorageExecutionProgress, StorageExecutionStop,
)
from officekit.engines.engine_workspace_exports import WorkspaceExportLimitError, render_folder_comparison_csv
from officekit.engines.engine_similar_images import SimilarImageDependencyError, SimilarImageEngine
from officekit.engines.engine_screenshot_editor import ScreenshotEditError, ScreenshotOutputLimitError, ScreenshotEditorEngine
from officekit.engines.engine_pii_redaction import PiiOcrUnavailable, PiiRedactionEngine, PiiRedactionError
from officekit.engines.engine_uploads import RequestBodyLimitMiddleware, UploadTooLargeError, read_bounded_upload
from officekit.engines.engine_network_diagnostics import NetworkDiagnosticError, NetworkDiagnostics
from officekit.engines.engine_network_dns import (
    DnsLookup,
    DnsLookupError,
    DnsLookupInputError,
    normalize_dkim_selector,
    normalize_dns_hostname,
    normalize_nameserver,
)
from officekit.engines.engine_network_interfaces import NetworkInterfaceError, NetworkInterfaceService
from officekit.engines.engine_network_health import NetworkHealthError, NetworkHealthService, NetworkHealthUnsupportedError
from officekit.engines.engine_system_resources import SystemResourceError, SystemResourceService
from officekit.engines.engine_system_metrics import SystemMetricsService, data_volume_path, macos_memory_used_percent
from officekit.engines.engine_system_info import SystemInfoService, SystemInfoUnavailableError, SystemInfoUnsupportedError
from officekit.engines.engine_process_manager import (
    ProcessManagerService,
    ProcessManagerError,
    ProcessNotFoundError,
    ProcessAccessDeniedError,
    ProcessSafetyError,
)

from fastapi import Request

logger = logging.getLogger("officekit.api")
MAX_IMAGE_RESPONSE_BYTES = MAX_API_UPLOAD_BYTES
MAX_IMAGE_BATCH_INPUT_BYTES = MAX_API_UPLOAD_BYTES
MAX_IMAGE_BATCH_FILES = 50
MAX_PDF_MERGE_FILES = 20
WorkspaceFileName = Annotated[str, StringConstraints(min_length=1, max_length=1024, strict=True)]
API_AUTH_TOKEN = resolve_api_auth_token(os.environ)
DEV_UNLOCK = dev_unlock_enabled(os.environ)
RELEASE_PROFILE = load_release_profile()
_APP_VERSION_PATTERN = re.compile(r"\d{1,4}\.\d{1,5}\.\d{1,6}")


def resolve_api_version(environment=os.environ) -> str:
    """Report the desktop app's version so the shell's health check matches after a version bump."""
    value = environment.get("OFFICEKIT_APP_VERSION", "")
    return value if _APP_VERSION_PATTERN.fullmatch(value) else "1.0.0"


async def read_api_upload(file: UploadFile) -> bytes:
    try:
        return await read_bounded_upload(file, MAX_API_UPLOAD_BYTES)
    except UploadTooLargeError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error


def extract_scanned_pdf_page_rows(pdf_bytes: bytes, page_indexes):
    from officekit.engines.engine_pdf_ocr import ScannedPdfOcrEngine

    return ScannedPdfOcrEngine.extract_page_rows(pdf_bytes, page_indexes=page_indexes)


def extract_pdf_page_tables(pdf_bytes):
    from officekit.engines.engine_parser import extract_pdf_page_tables as extract

    return extract(pdf_bytes)

app = FastAPI(
    title="OfficeKit - The Private All-in-One Office & Financial Toolkit",
    description="High-precision Bank Statement Extractor, Any-to-Any File Converter, Voice Dictation & Calculators",
    version=resolve_api_version(),
    docs_url=None if RELEASE_PROFILE.name == "private-beta" else "/docs",
    redoc_url=None if RELEASE_PROFILE.name == "private-beta" else "/redoc",
    openapi_url=None if RELEASE_PROFILE.name == "private-beta" else "/openapi.json",
)
app.add_middleware(ReleaseScopeMiddleware, profile=lambda: RELEASE_PROFILE)
app.add_middleware(
    RequestBodyLimitMiddleware,
    path_limits=merge_body_limits({
        "/api/extract/statement": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/convert/image": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/image/metadata": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/images/resize": MAX_IMAGE_BATCH_INPUT_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/screenshot/edit": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/privacy/pii/scan": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/privacy/pii/redact": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/convert/data": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/convert/data/sheets": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/unlock": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf-documents": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf-signing-providers": 2 * 1024 * 1024 + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf-signing-providers/native": 16 * 1024,
        "/api/pdf-documents/*/revisions": 32 * 1024 * 1024,
        "/api/pdf-documents/*/signatures": 16 * 1024,
        "/api/pdf-documents/*/ocr-reviews": 16 * 1024,
        "/api/pdf/protect": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/page-counts": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/merge": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/split": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/pages/delete": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/pages/reorder": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/split/groups": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/compress": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/metadata": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/images": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/page-thumbnails": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/tables": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/tables/export": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/pdf/text": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/export/csv": 8 * 1024 * 1024,
        "/api/export/excel": 8 * 1024 * 1024,
        "/api/export/xls": 8 * 1024 * 1024,
        "/api/export/result": 8 * 1024 * 1024,
        "/api/devtools/process": 8 * 1024 * 1024,
        "/api/crypto/hashes": 8 * 1024 * 1024,
        "/api/workspaces": 536_870_912 + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/license/entitlement": MAX_ENTITLEMENT_BODY_BYTES,
        "/api/file-selections": 1024 * 1024,
        **{re.sub(r"\{[^}]+\}", "*", route): limit for route, limit in INVOICE_BODY_LIMITS.items()},
        "/api/file-output-grants": 32 * 1024,
        "/api/file-jobs": 1024 * 1024,
        "/api/file-jobs/*/cancellations": 1024,
        "/api/media-jobs": 1024 * 1024,
        "/api/media-import-previews": 8 * 1024,
        "/api/media-image-stagings": MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/media-watermark-stagings": 5 * 1024 * 1024 + MAX_MULTIPART_OVERHEAD_BYTES,
        "/api/media-pipelines": 128 * 1024,
        "/api/media-preset-zones": 16 * 1024,
        "/api/media-preset-zones/*": 16 * 1024,
        "/api/media-jobs/*/cancellations": 1024,
        "/api/storage-scans": 1024,
        "/api/storage-cleanup-plans": 32 * 1024,
        "/api/storage-cleanup-plans/*/execution": 1024,
        "/api/trash-restore-grants": 8 * 1024,
        "/api/trash-restorations": 8 * 1024,
        "/api/workspaces/*/extractions": 8 * 1024 * 1024,
        "/api/workspaces/*/hash-reports": 8 * 1024 * 1024,
        "/api/workspaces/*/file-type-reports": 8 * 1024 * 1024,
        "/api/workspaces/*/folder-comparisons": 8 * 1024 * 1024,
        "/api/workspaces/*/rename-previews": 8 * 1024 * 1024,
        "/api/workspaces/*/renamed-artifacts": 8 * 1024 * 1024,
        "/api/workspaces/*/splits": 8 * 1024 * 1024,
        "/api/workspaces/*/joins": 8 * 1024 * 1024,
        "/api/workspaces/*/duplicate-reports": 8 * 1024 * 1024,
        "/api/workspaces/*/storage-reports": 8 * 1024 * 1024,
        "/api/workspaces/*/similar-image-reports": 8 * 1024 * 1024,
    }, slice_body_limits()),
)


@app.get("/api/health")
def api_health():
    """Versioned identity probe used by the Tauri shell before exposing the UI."""
    return {"status": "ok", "service": "officekit-api", "version": app.version}


@app.get("/api/release", response_model=ReleaseResponse)
def api_release():
    """Release profile (what this build ships), build version and the active edition (None while
    locked); carries no licence secrets."""
    entitlement = GATE_STATE.current()
    return {
        **RELEASE_PROFILE.payload(),
        "version": app.version,
        "edition": None if entitlement is None else entitlement.edition,
    }


@app.middleware("http")
async def restrict_untrusted_browser_origins(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.url.path.startswith("/api/") and not is_trusted_api_origin(origin, os.environ):
        return JSONResponse(status_code=403, content={"detail": "Browser request origin is not allowed."})
    return await call_next(request)


@app.middleware("http")
async def require_live_entitlement(request: Request, call_next):
    """Licence gate; defined before authentication so it runs after it. Fails closed on unknown routes."""
    path = request.url.path
    if (
        not DEV_UNLOCK
        and path.startswith("/api/")
        and request.method != "OPTIONS"
        and not is_gate_exempt(path, request.method)
        and not is_free_route(path, request.method)
    ):
        entitlement = GATE_STATE.current()
        if entitlement is None:
            return JSONResponse(status_code=403, content=license_required_payload())
        feature = feature_for_route(request.method, path)
        if feature is not None and feature not in entitlement.features:
            return JSONResponse(status_code=403, content=feature_not_licensed_payload())
    return await call_next(request)


@app.middleware("http")
async def authenticate_officekit_api(request: Request, call_next):
    if (
        request.url.path.startswith("/api/")
        and request.method != "OPTIONS"
        and API_AUTH_TOKEN is not None
        and not is_api_authorization_valid(request.headers.get("authorization"), API_AUTH_TOKEN)
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "OfficeKit desktop authentication is required."},
        )
    return await call_next(request)


# Refuse a Host header that is not the loopback address, so a DNS-rebinding page cannot reach the API.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(TRUSTED_API_HOSTS))

# Registered after the function middlewares above so CORS is the OUTERMOST layer (Starlette makes
# the last-added middleware outermost). The webview is cross-origin to the loopback sidecar, so the
# 401 and licence-gate 403 envelopes must pass through CORS or the browser hides them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(trusted_api_origins(os.environ)),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-OfficeKit-Native-Grant"],
    expose_headers=[
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
        *slice_expose_headers(),
    ],
)


@app.exception_handler(Exception)
async def safe_internal_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled OfficeKit API exception")
    return JSONResponse(status_code=500, content=internal_error_payload())


@app.exception_handler(RequestValidationError)
async def safe_validation_error_handler(request: Request, exc: RequestValidationError):
    # Pydantic errors include the rejected input value. Echoing it can both expose
    # private input and make JSON serialization fail for non-finite numbers.
    return JSONResponse(
        status_code=422,
        content={"detail": "Request contains invalid or unsupported values."},
    )

# ==========================================
# 1. Bank Statement & PDF/Image Extractor API
# ==========================================

class StatementColumnMappingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    date: StrictInt
    desc: StrictInt
    debit: Optional[StrictInt] = None
    credit: Optional[StrictInt] = None
    amount: Optional[StrictInt] = None
    balance: Optional[StrictInt] = None


def _parse_statement_column_mapping(value: Optional[str]) -> Optional[Dict[str, Optional[int]]]:
    if value is None:
        return None

    def reject_duplicate_keys(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate mapping field")
            result[key] = item
        return result

    try:
        decoded = json.loads(value, object_pairs_hook=reject_duplicate_keys)
        mapping = StatementColumnMappingRequest.model_validate(decoded, strict=True)
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(status_code=422, detail="Statement column mapping is invalid.") from None
    return mapping.model_dump(exclude_none=True)


@app.post("/api/extract/statement")
async def extract_statement(
    file: UploadFile = File(...),
    number_locale: Literal["auto", "en-US", "en-IN", "de-DE", "fr-FR"] = Form(default="auto"),
    date_order: Literal["auto", "DMY", "MDY", "YMD"] = Form(default="auto"),
    column_mapping: Optional[str] = Form(default=None, max_length=2048),
):
    """Extracts bank statement transactions from PDF or Image with balance checksum verification."""
    from officekit.engines.engine_ocr import (
        ImageTextRecognitionError,
        ImageTextRecognitionUnavailable,
    )
    from officekit.engines.engine_parser import (
        StatementPdfReadError,
        extract_pdf_opening_balance,
        extract_text_from_image,
        flatten_statement_tables,
        parse_statement_table,
        pdf_page_has_selectable_text,
        statement_page_needs_ocr,
        statement_page_quality,
        verify_statement_against_pdf,
    )
    from officekit.engines.engine_pdf_ocr import (
        ScannedPdfOcrError,
        ScannedPdfOcrUnavailable,
    )

    mapping_override = _parse_statement_column_mapping(column_mapping)
    content = await read_api_upload(file)
    filename = (file.filename or "").lower()

    rows = []
    opening_balance = None
    if filename.endswith(".pdf"):
        try:
            page_tables = extract_pdf_page_tables(content)
            opening_balance = extract_pdf_opening_balance(content, number_locale)
        except StatementPdfReadError as error:
            raise HTTPException(status_code=422, detail=StatementPdfReadError.public_message) from error
        recovery_page_indexes = []
        for index, tables in enumerate(page_tables):
            if tables:
                if statement_page_needs_ocr(tables):
                    recovery_page_indexes.append(index)
            else:
                if not pdf_page_has_selectable_text(content, index):
                    recovery_page_indexes.append(index)
        if recovery_page_indexes:
            missing_vector_pages = any(not page_tables[index] for index in recovery_page_indexes)
            try:
                recovered_page_rows = extract_scanned_pdf_page_rows(content, recovery_page_indexes)
            except (ScannedPdfOcrError, ScannedPdfOcrUnavailable) as error:
                if missing_vector_pages and not any(page_tables):
                    raise HTTPException(status_code=error.status_code, detail=error.public_message) from error
                # OCR is a recovery attempt for weak vector pages. Preserve their
                # source extraction when the local recognizer is unavailable or
                # rejects the page, rather than turning a readable PDF into an error.
                recovered_page_rows = [[] for _ in recovery_page_indexes]
            for page_index, page_rows in zip(recovery_page_indexes, recovered_page_rows, strict=True):
                if page_rows and statement_page_quality([page_rows]) > statement_page_quality(page_tables[page_index]):
                    page_tables[page_index] = [page_rows]
        rows = flatten_statement_tables(
            [table for page_tables_for_page in page_tables for table in page_tables_for_page]
        )
    elif filename.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff")):
        try:
            rows = extract_text_from_image(content)
        except (ImageTextRecognitionUnavailable, ImageTextRecognitionError) as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    elif filename.endswith((".csv", ".tsv")):
        try:
            rows = parse_statement_delimited(content, filename.rsplit(".", 1)[1])
        except StatementInputError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    else:
        raise HTTPException(status_code=400, detail="Unsupported file format. Please upload PDF, PNG, JPG, or CSV.")

    if not rows:
        raise HTTPException(status_code=422, detail="No extractable text or tables found in document.")

    try:
        result = parse_statement_table(
            rows,
            number_locale=number_locale,
            date_order=date_order,
            opening_balance=opening_balance,
            column_mapping=mapping_override,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Statement column mapping is invalid.") from None

    if filename.endswith(".pdf"):
        result["pdf_verification"] = verify_statement_against_pdf(
            result["transactions"],
            content,
            number_locale=number_locale,
        )

    return result


class StatementExportTransaction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: str = PydanticField(default="", max_length=256, strict=True)
    description: str = PydanticField(default="", max_length=10_000, strict=True)
    debit: Optional[float] = PydanticField(default=None, ge=0, le=1e12, allow_inf_nan=False)
    credit: Optional[float] = PydanticField(default=None, ge=0, le=1e12, allow_inf_nan=False)
    balance: Optional[float] = PydanticField(default=None, ge=-1e12, le=1e12, allow_inf_nan=False)
    status: Literal["ok", "reconciliation_warning", "baseline", "unverified"] = "ok"

    @field_validator("debit", "credit", "balance", mode="before")
    @classmethod
    def reject_non_numeric_amounts(cls, value):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Amounts must be JSON numbers or null")
        return value


class StatementExportRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transactions: List[StatementExportTransaction] = PydanticField(default_factory=list, max_length=10_000)


ResultExportText = Annotated[str, StringConstraints(max_length=10_000, strict=True)]
ResultExportNote = Annotated[str, StringConstraints(min_length=1, max_length=10_000, strict=True)]
ResultExportScalar = Union[ResultExportText, StrictInt, StrictFloat, StrictBool, None]


class ResultExportValueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = PydanticField(min_length=1, max_length=160)
    value: ResultExportScalar
    unit: Optional[StrictStr] = PydanticField(default=None, max_length=80)


class ResultExportTableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: StrictStr = PydanticField(min_length=1, max_length=160)
    columns: List[StrictStr] = PydanticField(min_length=1, max_length=40)
    rows: List[List[ResultExportScalar]] = PydanticField(max_length=10_000)


class ResultExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["markdown", "html", "json", "csv", "xlsx", "pptx", "pdf", "png", "jpeg"]
    tool_id: StrictStr = PydanticField(min_length=1, max_length=80)
    title: StrictStr = PydanticField(min_length=1, max_length=160)
    created_at: StrictStr = PydanticField(min_length=1, max_length=40)
    inputs: List[ResultExportValueRequest] = PydanticField(max_length=1_000)
    results: List[ResultExportValueRequest] = PydanticField(max_length=1_000)
    assumptions: List[ResultExportNote] = PydanticField(max_length=100)
    tables: List[ResultExportTableRequest] = PydanticField(max_length=20)
    include_attribution: StrictBool = False


@app.post("/api/export/result")
def export_result(data: ResultExportRequest):
    snapshot = data.model_dump(exclude={"format", "include_attribution"})
    try:
        content = ResultExportEngine.export(
            snapshot,
            data.format,
            datetime.now(timezone.utc),
            include_attribution=data.include_attribution,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    formats = {
        "markdown": ("text/markdown", "md"),
        "html": ("text/html", "html"),
        "json": ("application/json", "json"),
        "csv": ("text/csv; charset=utf-8", "csv"),
        "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
        "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "pptx"),
        "pdf": ("application/pdf", "pdf"),
        "png": ("image/png", "png"),
        "jpeg": ("image/jpeg", "jpg"),
    }
    media_type, extension = formats[data.format]
    filename = content_disposition_attachment(f"{data.tool_id}-result.{extension}")
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": filename},
    )


@app.post("/api/export/csv")
async def export_statement_csv(data: StatementExportRequest):
    """Export parsed transactions list directly to CSV."""
    from officekit.engines.engine_parser import export_to_csv

    transactions = [transaction.model_dump() for transaction in data.transactions]
    csv_str = export_to_csv(transactions)
    return Response(
        content=csv_str,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=statement_export.csv"}
    )


@app.post("/api/export/excel")
async def export_statement_excel(data: StatementExportRequest):
    """Export parsed transactions list directly to XLSX Excel."""
    from officekit.engines.engine_parser import export_to_excel

    transactions = [transaction.model_dump() for transaction in data.transactions]
    excel_bytes = export_to_excel(transactions)
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=statement_export.xlsx"}
    )


@app.post("/api/export/xls")
async def export_statement_legacy_excel(data: StatementExportRequest):
    """Export parsed transactions to a legacy BIFF8 workbook."""
    from officekit.engines.engine_statement_exports import export_to_legacy_excel

    transactions = [transaction.model_dump() for transaction in data.transactions]
    xls_bytes = export_to_legacy_excel(transactions)
    return Response(
        content=xls_bytes,
        media_type="application/vnd.ms-excel",
        headers={"Content-Disposition": "attachment; filename=statement_export.xls"}
    )


# ==========================================
# 2. Any-to-Any File & Image Converter API
# ==========================================

@app.post("/api/convert/image")
async def convert_image_endpoint(
    file: UploadFile = File(...),
    target_format: str = Form(...),
    quality: int = Form(90, ge=1, le=100),
):
    """Converts images between PNG, JPG, WebP, BMP, TIFF, ICO, PDF."""
    content = await read_api_upload(file)
    try:
        out_bytes, mime = FileConverterEngine.convert_image(content, target_format, quality)
        if len(out_bytes) > MAX_IMAGE_RESPONSE_BYTES:
            raise HTTPException(status_code=413, detail="The converted image exceeds the supported 64 MiB limit.")
        ext = target_format.lower().replace('.', '')
        base_name = os.path.splitext(file.filename or "converted")[0]
        return Response(
            content=out_bytes,
            media_type=mime,
            headers={"Content-Disposition": content_disposition_attachment(f"{base_name}.{ext}")}
        )
    except ImageOutputLimitError as error:
        raise HTTPException(status_code=413, detail="The converted image exceeds the supported 64 MiB limit.") from error
    except ConversionInputError as error:
        raise HTTPException(status_code=422, detail=ConversionInputError.public_message) from error


@app.post("/api/image/metadata")
async def api_strip_image_metadata(file: UploadFile = File(...)):
    """Remove image EXIF locally while preserving decoded image and animation content."""
    filename = (file.filename or "image").replace("\\", "/").rsplit("/", 1)[-1]
    source_extension = os.path.splitext(filename)[1].lower()
    if source_extension not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}:
        raise HTTPException(status_code=415, detail="Choose a supported image file.")

    content = await read_api_upload(file)
    try:
        cleaned = FileConverterEngine.strip_exif(content)
        if len(cleaned) > MAX_IMAGE_RESPONSE_BYTES:
            raise HTTPException(status_code=413, detail="The image output exceeds the supported 64 MiB limit.")
        with Image.open(io.BytesIO(cleaned)) as result:
            output_format = result.format or "PNG"
    except HTTPException:
        raise
    except ConversionInputError as error:
        raise HTTPException(status_code=422, detail=ConversionInputError.public_message) from error

    formats = {
        "JPEG": ("jpg", "image/jpeg"),
        "PNG": ("png", "image/png"),
        "WEBP": ("webp", "image/webp"),
        "BMP": ("bmp", "image/bmp"),
        "TIFF": ("tiff", "image/tiff"),
        "GIF": ("gif", "image/gif"),
    }
    extension, media_type = formats.get(output_format.upper(), (None, None))
    if extension is None:
        raise HTTPException(status_code=422, detail=ConversionInputError.public_message)
    base_name = os.path.splitext(filename)[0] or "image"
    return Response(
        content=cleaned,
        media_type=media_type,
        headers={"Content-Disposition": content_disposition_attachment(f"{base_name}_metadata_removed.{extension}")},
    )


@app.post("/api/image/resize")
async def api_resize_image(
    file: UploadFile = File(...),
    max_width: int = Form(..., ge=1, le=10_000),
    max_height: int = Form(..., ge=1, le=10_000),
):
    """Resize a local image without upscaling and preserve supported frames."""
    filename = (file.filename or "image").replace("\\", "/").rsplit("/", 1)[-1]
    source_extension = os.path.splitext(filename)[1].lower()
    if source_extension not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}:
        raise HTTPException(status_code=415, detail="Choose a supported image file.")

    content = await read_api_upload(file)
    try:
        resized, (width, height) = FileConverterEngine.resize_image(content, max_width, max_height)
        if len(resized) > MAX_IMAGE_RESPONSE_BYTES:
            raise HTTPException(status_code=413, detail="The resized image exceeds the supported 64 MiB limit.")
        with Image.open(io.BytesIO(resized)) as output_image:
            output_format = (output_image.format or "").upper()
    except HTTPException:
        raise
    except ImageOutputLimitError as error:
        raise HTTPException(status_code=413, detail="The resized image exceeds the supported 64 MiB limit.") from error
    except ConversionInputError as error:
        raise HTTPException(status_code=422, detail=ConversionInputError.public_message) from error

    formats = {
        "JPEG": ("jpg", "image/jpeg"),
        "PNG": ("png", "image/png"),
        "WEBP": ("webp", "image/webp"),
        "BMP": ("bmp", "image/bmp"),
        "TIFF": ("tiff", "image/tiff"),
        "GIF": ("gif", "image/gif"),
    }
    extension, media_type = formats.get(output_format, (None, None))
    if extension is None:
        raise HTTPException(status_code=422, detail=ConversionInputError.public_message)
    base_name = os.path.splitext(filename)[0] or "image"
    return Response(
        content=resized,
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition_attachment(f"{base_name}_resized.{extension}"),
            "X-OfficeKit-Image-Width": str(width),
            "X-OfficeKit-Image-Height": str(height),
        },
    )


@app.post("/api/images/resize")
async def api_resize_images(
    files: List[UploadFile] = File(...),
    max_width: int = Form(..., ge=1, le=10_000),
    max_height: int = Form(..., ge=1, le=10_000),
):
    """Resize up to 50 local images into a bounded ZIP attachment."""
    if not files:
        raise HTTPException(status_code=422, detail="Choose at least one image.")
    if len(files) > MAX_IMAGE_BATCH_FILES:
        raise HTTPException(status_code=413, detail="A batch can contain at most 50 images.")

    supported_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
    batch = []
    total_bytes = 0
    try:
        for file in files:
            filename = (file.filename or "image").replace("\\", "/").rsplit("/", 1)[-1]
            if os.path.splitext(filename)[1].lower() not in supported_extensions:
                raise HTTPException(status_code=415, detail="Choose supported image files.")
            remaining = MAX_IMAGE_BATCH_INPUT_BYTES - total_bytes
            if remaining == 0:
                if await file.read(1):
                    raise HTTPException(status_code=413, detail="The image batch exceeds the supported 64 MiB input limit.")
                content = b""
            else:
                content = await read_bounded_upload(file, remaining)
            total_bytes += len(content)
            batch.append((filename, content))
    except UploadTooLargeError as error:
        raise HTTPException(status_code=413, detail="The image batch exceeds the supported 64 MiB input limit.") from error

    try:
        archive = FileConverterEngine.resize_images_to_zip(batch, max_width, max_height)
    except ImageWorkLimitError as error:
        raise HTTPException(
            status_code=413,
            detail="The image batch requires too much processing; select fewer or smaller images.",
        ) from error
    except ImageOutputLimitError as error:
        raise HTTPException(status_code=413, detail="The resized image batch exceeds the supported 64 MiB output limit.") from error
    except ConversionInputError as error:
        raise HTTPException(status_code=422, detail=ConversionInputError.public_message) from error

    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition_attachment("resized_images.zip")},
    )


class ScreenshotRegionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: StrictInt = PydanticField(ge=0, le=40_000)
    y: StrictInt = PydanticField(ge=0, le=40_000)
    width: StrictInt = PydanticField(ge=1, le=40_000)
    height: StrictInt = PydanticField(ge=1, le=40_000)


class ScreenshotCropRequest(ScreenshotRegionRequest):
    type: Literal["crop"]


class ScreenshotBlurRequest(ScreenshotRegionRequest):
    type: Literal["blur"]
    radius: StrictInt = PydanticField(default=24, ge=1, le=100)


class ScreenshotPixelateRequest(ScreenshotRegionRequest):
    type: Literal["pixelate"]
    block_size: StrictInt = PydanticField(default=12, ge=2, le=64)


class ScreenshotRotateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["rotate"]


class ScreenshotMaskRequest(ScreenshotRegionRequest):
    type: Literal["mask"]
    color: str = PydanticField(default="#000000", pattern=r"^#[0-9A-Fa-f]{6}$", strict=True)


class ScreenshotRectangleRequest(ScreenshotMaskRequest):
    type: Literal["rectangle"]
    outer_color: str | None = PydanticField(default=None, pattern=r"^#[0-9A-Fa-f]{6}$", strict=True)
    stroke_width: StrictInt = PydanticField(default=3, ge=1, le=32)
    outer_width: StrictInt = PydanticField(default=2, ge=1, le=32)


class ScreenshotRoundedRectangleRequest(ScreenshotRectangleRequest):
    type: Literal["rounded_rectangle"]


class ScreenshotCircleRequest(ScreenshotRectangleRequest):
    type: Literal["circle"]


class ScreenshotHighlightRequest(ScreenshotRectangleRequest):
    type: Literal["highlight"]


class ScreenshotPathRequest(ScreenshotRectangleRequest):
    type: Literal["arrow", "freehand", "line"]
    points: List[tuple[StrictInt, StrictInt]] = PydanticField(min_length=2, max_length=512)

    @model_validator(mode="after")
    def validate_points(self):
        if self.type in {"arrow", "line"} and (len(self.points) != 2 or self.points[0] == self.points[1]):
            raise ValueError("Line and arrow require two distinct endpoints")
        if any(not (self.x <= x < self.x + self.width and self.y <= y < self.y + self.height) for x, y in self.points):
            raise ValueError("Path outside annotation bounds")
        return self


class ScreenshotTextRequest(ScreenshotRectangleRequest):
    type: Literal["text"]
    text: str = PydanticField(min_length=1, max_length=200, strict=True)
    font_size: StrictInt = PydanticField(default=24, ge=8, le=96)


class ScreenshotStampRequest(ScreenshotRegionRequest):
    model_config = ConfigDict(extra="forbid")

    type: Literal["stamp"]
    stamp: Literal["check", "question", "x", "alert", "heart"]
    points: List[tuple[StrictInt, StrictInt]] = PydanticField(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_points(self):
        if self.points[0] == self.points[1]:
            raise ValueError("Stamp pointer requires distinct endpoints")
        if any(not (self.x <= x < self.x + self.width and self.y <= y < self.y + self.height) for x, y in self.points):
            raise ValueError("Stamp pointer outside annotation bounds")
        return self


ScreenshotOperationRequest = Annotated[
    Union[ScreenshotCropRequest, ScreenshotBlurRequest, ScreenshotPixelateRequest, ScreenshotRotateRequest, ScreenshotMaskRequest, ScreenshotRectangleRequest, ScreenshotRoundedRectangleRequest, ScreenshotCircleRequest, ScreenshotHighlightRequest, ScreenshotPathRequest, ScreenshotStampRequest, ScreenshotTextRequest],
    PydanticField(discriminator="type"),
]


class ScreenshotEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: List[ScreenshotOperationRequest] = PydanticField(min_length=1, max_length=50)

    @model_validator(mode="after")
    def validate_total_points(self):
        if sum(len(getattr(operation, "points", [])) for operation in self.operations) > 1024:
            raise ValueError("Too many annotation points")
        return self


@app.post("/api/screenshot/edit")
async def edit_screenshot_endpoint(
    file: UploadFile = File(...),
    operations: str = Form(..., max_length=32_768),
    format: Literal["png", "jpeg"] = Form(default="png"),
):
    """Annotate, crop, rotate, blur, pixelate and opaquely mask a selected image locally."""
    try:
        payload = ScreenshotEditorEngine.parse_operations_json(operations)
        request = ScreenshotEditRequest.model_validate({"operations": payload})
    except (ScreenshotEditError, ValidationError):
        raise HTTPException(status_code=422, detail=ScreenshotEditError.public_message) from None
    content = await read_api_upload(file)
    try:
        edited, _dimensions = ScreenshotEditorEngine.edit_image(
            content, [operation.model_dump(mode="json", exclude_none=True) for operation in request.operations], format
        )
    except ScreenshotOutputLimitError as error:
        raise HTTPException(status_code=413, detail=error.public_message) from error
    except ScreenshotEditError as error:
        raise HTTPException(status_code=422, detail=ScreenshotEditError.public_message) from error
    extension = "jpg" if format == "jpeg" else "png"
    return Response(
        content=edited,
        media_type="image/jpeg" if format == "jpeg" else "image/png",
        headers={"Content-Disposition": content_disposition_attachment(f"screenshot-edited.{extension}")},
    )


@app.post("/api/privacy/pii/scan")
async def scan_personal_information_endpoint(file: UploadFile = File(...)):
    """Find likely personal information in one user-selected file using local processing."""
    content = await read_api_upload(file)
    try:
        return PiiRedactionEngine.scan(file.filename or "", content)
    except PiiOcrUnavailable as error:
        raise HTTPException(status_code=503, detail=error.public_message) from error
    except PiiRedactionError as error:
        raise HTTPException(status_code=422, detail=error.public_message) from error


@app.post("/api/privacy/pii/redact")
async def redact_personal_information_endpoint(
    file: UploadFile = File(...),
    selected_ids: str = Form(..., max_length=128_000),
    mode: str = Form("mask", max_length=16),
):
    """Create a separate copy with selected matches partially masked or fully redacted."""
    try:
        parsed_ids = json.loads(selected_ids)
        if not isinstance(parsed_ids, list) or len(parsed_ids) > PiiRedactionEngine.MAX_MATCHES or any(
            not isinstance(item, str) for item in parsed_ids
        ):
            raise ValueError("invalid selected identifiers")
    except (json.JSONDecodeError, ValueError, RecursionError) as error:
        raise HTTPException(status_code=422, detail="The selected matches are invalid. Scan the file again.") from error
    content = await read_api_upload(file)
    try:
        output, filename, media_type = PiiRedactionEngine.redact(file.filename or "", content, parsed_ids, mode=mode)
    except PiiOcrUnavailable as error:
        raise HTTPException(status_code=503, detail=error.public_message) from error
    except PiiRedactionError as error:
        raise HTTPException(status_code=422, detail=error.public_message) from error
    return Response(
        content=output,
        media_type=media_type,
        headers={"Content-Disposition": content_disposition_attachment(filename)},
    )


@app.post("/api/convert/data/sheets")
async def list_data_conversion_sheets_endpoint(file: UploadFile = File(...)):
    """List the bounded worksheet names in a selected XLSX workbook."""
    content = await read_api_upload(file)
    source_ext = os.path.splitext(file.filename or "")[1].replace('.', '').lower()
    try:
        if source_ext != "xlsx":
            raise ConversionInputError()
        return {"sheets": FileConverterEngine.list_xlsx_sheet_names(content)}
    except ConversionInputError as error:
        raise HTTPException(status_code=422, detail=ConversionInputError.public_message) from error


@app.post("/api/convert/data")
async def convert_data_endpoint(
    file: UploadFile = File(...),
    target_format: str = Form(...),
    sheet_name: Optional[str] = Form(default=None),
    null_token: Optional[str] = Form(default=None, max_length=64),
):
    """Converts tabular data files, optionally preserving nulls with a delimited marker."""
    content = await read_api_upload(file)
    source_ext = os.path.splitext(file.filename or "")[1].replace('.', '')
    try:
        out_bytes, mime = FileConverterEngine.convert_data_file(
            content, source_ext, target_format, sheet_name=sheet_name, null_token=null_token
        )
        target_ext = target_format.lower().replace('.', '')
        base_name = os.path.splitext(file.filename or "data_converted")[0]
        return Response(
            content=out_bytes,
            media_type=mime,
            headers={"Content-Disposition": content_disposition_attachment(f"{base_name}.{target_ext}")}
        )
    except ConversionInputError as error:
        raise HTTPException(status_code=422, detail=ConversionInputError.public_message) from error


# ==========================================
# 3. High-Traffic Financial Calculators API
# ==========================================

class LoanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)
    annual_interest_rate: float = PydanticField(ge=0, le=1000, allow_inf_nan=False)
    tenure_years: float = PydanticField(ge=1 / 12, le=100, allow_inf_nan=False)

    @field_validator("principal", "annual_interest_rate", "tenure_years", mode="before")
    @classmethod
    def numeric_fields_reject_boolean_and_string_coercion(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Value must be a JSON number")
        return value


class LoanScheduleItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    month: int = PydanticField(ge=1, le=1200)
    payment: float = PydanticField(ge=0)
    principal_paid: float = PydanticField(ge=0)
    interest_paid: float = PydanticField(ge=0)
    remaining_balance: float = PydanticField(ge=0)


class LoanAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate_basis: Literal["nominal_annual"]
    payment_frequency: Literal["monthly"]
    currency_precision: Literal["0.01"]
    fees_and_extra_payments: Literal["excluded"]
    final_payment: Literal["adjusted_to_zero_balance"]


class LoanResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    monthly_emi: float = PydanticField(ge=0)
    total_interest: float = PydanticField(ge=0)
    total_payment: float = PydanticField(ge=0)
    tenure_months: int = PydanticField(ge=1, le=1200)
    preview_schedule: List[LoanScheduleItem]
    schedule: List[LoanScheduleItem]
    assumptions: LoanAssumptions

class CompoundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)
    annual_rate: float = PydanticField(gt=-100, le=1000, allow_inf_nan=False)
    years: float = PydanticField(ge=0, le=100, allow_inf_nan=False)
    compound_freq: int = PydanticField(default=12, ge=1, le=365, strict=True)
    monthly_contribution: float = PydanticField(
        default=0.0, ge=0, le=1e12, allow_inf_nan=False
    )

    @field_validator("principal", "annual_rate", "years", "monthly_contribution", mode="before")
    @classmethod
    def numeric_fields_reject_boolean_and_string_coercion(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Value must be a JSON number")
        return value


class CompoundInterestHistoryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: float
    total_balance: float
    total_invested: float
    total_interest: float


class CompoundInterestAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate_basis: Literal["nominal_annual"]
    monthly_accrual: Literal["equivalent_effective_monthly_rate"]
    contribution_timing: Literal["end_of_month"]
    fractional_month: Literal["interest_only"]


class CompoundInterestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    future_value: float
    total_invested: float
    total_interest_earned: float
    growth_history: List[CompoundInterestHistoryItem]
    assumptions: CompoundInterestAssumptions


class BreakEvenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fixed_costs: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)
    price_per_unit: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)
    cost_per_unit: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)

    @field_validator("fixed_costs", "price_per_unit", "cost_per_unit", mode="before")
    @classmethod
    def numeric_fields_reject_boolean_and_string_coercion(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Value must be a JSON number")
        return value


class BreakEvenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    break_even_units: int = PydanticField(ge=0)
    break_even_revenue: float = PydanticField(ge=0)
    contribution_margin: float = PydanticField(gt=0)


class DepreciationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_cost: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)
    salvage_value: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)
    useful_life_years: int = PydanticField(ge=1, le=100, strict=True)

    @field_validator("asset_cost", "salvage_value", mode="before")
    @classmethod
    def monetary_fields_reject_boolean_and_string_coercion(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Value must be a JSON number")
        return value


class DepreciationYear(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int = PydanticField(ge=1, le=100)
    depreciation: float = PydanticField(ge=0)
    book_value: float = PydanticField(ge=0)


class DepreciationAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["straight_line"]
    currency_precision: Literal["0.01"]
    rounding: Literal["half_up"]
    final_period: Literal["adjusted_to_salvage_value"]


class DepreciationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    annual_depreciation: float = PydanticField(ge=0)
    total_depreciable: float = PydanticField(ge=0)
    schedule: List[DepreciationYear]
    assumptions: DepreciationAssumptions


class SimpleInterestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)
    annual_rate_percent: float = PydanticField(ge=0, le=1000, allow_inf_nan=False)
    time_value: float = PydanticField(gt=0, le=1200, allow_inf_nan=False)
    time_unit: Literal["years", "months"]

    @field_validator("principal", "annual_rate_percent", "time_value", mode="before")
    @classmethod
    def numeric_fields_reject_boolean_and_string_coercion(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Value must be a JSON number")
        return value


class SimpleInterestAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["simple_interest"]
    rate_basis: Literal["nominal_annual"]
    currency_precision: Literal["0.01"]
    rounding: Literal["half_up"]
    compounding: Literal["none"]


class SimpleInterestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    principal: float = PydanticField(ge=0)
    annual_rate_percent: float = PydanticField(ge=0, le=1000)
    time_value: float = PydanticField(gt=0, le=1200)
    time_unit: Literal["years", "months"]
    time_in_years: float = PydanticField(gt=0, le=100)
    interest_amount: float = PydanticField(ge=0)
    total_amount: float = PydanticField(ge=0)
    assumptions: SimpleInterestAssumptions

class VatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)
    tax_rate_percent: float = PydanticField(ge=0, le=1000, allow_inf_nan=False)
    is_inclusive: bool = PydanticField(default=False, strict=True)

    @field_validator("amount", "tax_rate_percent", mode="before")
    @classmethod
    def numeric_fields_reject_boolean_and_string_coercion(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Value must be a JSON number")
        return value


class VatAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate_source: Literal["user_supplied"]
    jurisdiction: Literal["not_specified"]
    currency_precision: Literal["0.01"]
    rounding: Literal["half_up"]


class VatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    net_amount: float = PydanticField(ge=0)
    tax_amount: float = PydanticField(ge=0)
    gross_amount: float = PydanticField(ge=0)
    tax_rate_percent: float = PydanticField(ge=0, le=1000)
    is_inclusive: bool
    assumptions: VatAssumptions

class FreelanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_annual_take_home: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)
    billable_hours_per_week: float = PydanticField(default=30.0, gt=0, le=168, allow_inf_nan=False)
    vacation_weeks: float = PydanticField(default=4.0, ge=0, lt=52, allow_inf_nan=False)
    business_expenses_annual: float = PydanticField(default=5000.0, ge=0, le=1e12, allow_inf_nan=False)
    tax_rate_percent: float = PydanticField(default=25.0, ge=0, lt=100, allow_inf_nan=False)

    @field_validator(
        "target_annual_take_home", "billable_hours_per_week", "vacation_weeks",
        "business_expenses_annual", "tax_rate_percent", mode="before",
    )
    @classmethod
    def numeric_fields_reject_boolean_and_string_coercion(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Value must be a JSON number")
        return value


class FreelanceAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tax_treatment: Literal["gross_up_target_then_add_expenses"]
    working_days_per_week: Literal[5]
    jurisdiction: Literal["not_specified"]


class FreelanceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recommended_hourly_rate: float = PydanticField(ge=0)
    recommended_day_rate: float = PydanticField(ge=0)
    gross_annual_revenue_needed: float = PydanticField(ge=0)
    total_annual_billable_hours: float = PydanticField(gt=0)
    assumptions: FreelanceAssumptions


class MarginMarkupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cost: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)
    revenue: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)

    @field_validator("cost", "revenue", mode="before")
    @classmethod
    def numeric_fields_reject_boolean_and_string_coercion(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Value must be a JSON number")
        return value


class MarginMarkupAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    margin_denominator: Literal["revenue"]
    markup_denominator: Literal["cost"]


class MarginMarkupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profit: float
    gross_margin_percent: float | None
    markup_percent: float | None
    cost: float
    revenue: float
    assumptions: MarginMarkupAssumptions


class PercentageRequestBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("percent", "value", "original_value", "new_value", "price", "discount_percent", mode="before", check_fields=False)
    @classmethod
    def percentage_inputs_require_json_numbers(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Value must be a JSON number")
        return value


class PercentOfRequest(PercentageRequestBase):
    percent: float = PydanticField(ge=0, le=1_000_000, allow_inf_nan=False)
    value: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)


class PercentageChangeRequest(PercentageRequestBase):
    original_value: float = PydanticField(gt=0, le=1e12, allow_inf_nan=False)
    new_value: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)


class DiscountRequest(PercentageRequestBase):
    price: float = PydanticField(ge=0, le=1e12, allow_inf_nan=False)
    discount_percent: float = PydanticField(ge=0, le=100, allow_inf_nan=False)


class PercentageAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rounding: Literal["half_up"]
    precision: Literal["0.01"]
    currency: Literal["not_inferred"]
    taxes: Literal["excluded"]


class PercentOfResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    percent: float
    value: float
    result: float
    assumptions: PercentageAssumptions


class PercentageChangeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original_value: float
    new_value: float
    change_value: float
    change_percent: float
    direction: Literal["increase", "decrease", "no_change"]
    assumptions: PercentageAssumptions


class DiscountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price: float
    discount_percent: float
    savings: float
    discounted_price: float
    assumptions: PercentageAssumptions

@app.post("/api/calculator/loan-emi", response_model=LoanResponse)
def api_loan_emi(req: LoanRequest) -> LoanResponse:
    try:
        return LoanResponse.model_validate(CalculatorEngine.calculate_loan_emi(
            req.principal, req.annual_interest_rate, req.tenure_years
        ))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

@app.post("/api/calculator/compound-interest", response_model=CompoundInterestResponse)
def api_compound(req: CompoundRequest) -> CompoundInterestResponse:
    return CompoundInterestResponse.model_validate(
        CalculatorEngine.calculate_compound_interest(
            req.principal,
            req.annual_rate,
            req.years,
            req.compound_freq,
            req.monthly_contribution,
        )
    )


@app.post("/api/calculator/break-even", response_model=BreakEvenResponse)
def api_break_even(req: BreakEvenRequest) -> BreakEvenResponse:
    try:
        return BreakEvenResponse.model_validate(CalculatorEngine.calculate_break_even(
            req.fixed_costs, req.price_per_unit, req.cost_per_unit
        ))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/calculator/depreciation", response_model=DepreciationResponse)
def api_depreciation(req: DepreciationRequest) -> DepreciationResponse:
    try:
        return DepreciationResponse.model_validate(CalculatorEngine.calculate_depreciation(
            req.asset_cost, req.salvage_value, req.useful_life_years
        ))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/calculator/simple-interest", response_model=SimpleInterestResponse)
def api_simple_interest(req: SimpleInterestRequest) -> SimpleInterestResponse:
    try:
        return SimpleInterestResponse.model_validate(CalculatorEngine.calculate_simple_interest(
            req.principal, req.annual_rate_percent, req.time_value, req.time_unit
        ))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

@app.post("/api/calculator/vat-sales-tax", response_model=VatResponse)
def api_vat(req: VatRequest) -> VatResponse:
    return VatResponse.model_validate(CalculatorEngine.calculate_vat_salestax(
        req.amount, req.tax_rate_percent, req.is_inclusive
    ))

@app.post("/api/calculator/freelance-rate", response_model=FreelanceResponse)
def api_freelance(req: FreelanceRequest) -> FreelanceResponse:
    try:
        return FreelanceResponse.model_validate(CalculatorEngine.calculate_freelance_invoice_rate(
            req.target_annual_take_home,
            req.billable_hours_per_week,
            req.vacation_weeks,
            req.business_expenses_annual,
            req.tax_rate_percent,
        ))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/calculator/margin-markup", response_model=MarginMarkupResponse)
def api_margin_markup(req: MarginMarkupRequest) -> MarginMarkupResponse:
    try:
        return MarginMarkupResponse.model_validate(
            CalculatorEngine.calculate_margin_markup(req.cost, req.revenue)
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/calculator/percent-of", response_model=PercentOfResponse)
def api_percent_of(req: PercentOfRequest) -> PercentOfResponse:
    try:
        return PercentOfResponse.model_validate(CalculatorEngine.calculate_percent_of(req.percent, req.value))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/calculator/percentage-change", response_model=PercentageChangeResponse)
def api_percentage_change(req: PercentageChangeRequest) -> PercentageChangeResponse:
    try:
        return PercentageChangeResponse.model_validate(
            CalculatorEngine.calculate_percentage_change(req.original_value, req.new_value)
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/calculator/discount", response_model=DiscountResponse)
def api_discount(req: DiscountRequest) -> DiscountResponse:
    try:
        return DiscountResponse.model_validate(CalculatorEngine.calculate_discount(req.price, req.discount_percent))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


from officekit.engines.engine_license import LicenseManager

class ActivateLicenseRequest(BaseModel):
    email: str
    license_key: str

@app.get("/api/license/status", response_model=LicenseStatusResponse)
def get_license_status():
    """Report the in-memory entitlement; carries no key, email, activation id or token."""
    entitlement = GATE_STATE.current()
    if entitlement is None:
        return {"activated": False, "edition": None, "features": [], "valid_until_epoch": None}
    return {
        "activated": True,
        "edition": entitlement.edition,
        "features": sorted(entitlement.features),
        "valid_until_epoch": entitlement.valid_until_epoch,
    }


def _native_grant_rejection(request: Request) -> Optional[JSONResponse]:
    """401 unless the caller presents the shell-only grant token; unset or malformed env token denies all."""
    expected = load_native_grant_token(os.environ, API_AUTH_TOKEN)
    if not is_native_grant_valid(request.headers.get(NATIVE_GRANT_HEADER), expected):
        return JSONResponse(status_code=401, content=native_grant_required_payload())
    return None


@app.put(
    "/api/license/entitlement",
    status_code=204,
    responses={401: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}},
    # The body is parsed by hand so the grant header is checked before any body validation; the
    # request DTO is declared here so OpenAPI (and clients generated from it) still describe it.
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": EntitlementPushRequest.model_json_schema()}},
        }
    },
)
async def put_license_entitlement(request: Request):
    """Native shell pushes the entitlement summary it verified; the webview never holds the grant."""
    rejection = _native_grant_rejection(request)
    if rejection is not None:
        return rejection
    raw = await request.body()
    try:
        pushed = EntitlementPushRequest.model_validate(json.loads(raw.decode("utf-8")))
    except (ValueError, ValidationError, RecursionError):
        return JSONResponse(status_code=422, content=invalid_entitlement_payload())
    GATE_STATE.install(pushed.edition, pushed.features, pushed.valid_for_seconds)
    return Response(status_code=204)


@app.delete("/api/license/entitlement", status_code=204, responses={401: {"model": ErrorEnvelope}})
def delete_license_entitlement(request: Request):
    rejection = _native_grant_rejection(request)
    if rejection is not None:
        return rejection
    GATE_STATE.clear()
    return Response(status_code=204)

@app.post("/api/license/activate")
def activate_license(req: ActivateLicenseRequest):
    """Reject local activation until signed hosted entitlements are integrated."""
    raise HTTPException(
        status_code=501,
        detail="Online activation is not available in this build.",
    )

# ==========================================
# 4. Dictate & Meeting Notes Generator API
# ==========================================
from officekit.engines.engine_dictate import MAX_TRANSCRIPT_CHARACTERS, MeetingDictateEngine
from officekit.engines.engine_dictation_cleanup import (
    MAX_CONTEXT_LABEL_CHARACTERS,
    MAX_CONTEXT_TEXT_CHARACTERS,
    DictationCleanupEngine,
    validate_context as validate_dictation_context,
)

class MeetingNotesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transcript: StrictStr = PydanticField(max_length=MAX_TRANSCRIPT_CHARACTERS)

class DictationCleanupContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    app_name: Optional[StrictStr] = PydanticField(default=None, max_length=MAX_CONTEXT_LABEL_CHARACTERS)
    bundle_id: Optional[StrictStr] = PydanticField(default=None, max_length=MAX_CONTEXT_LABEL_CHARACTERS)
    field_role: Optional[StrictStr] = PydanticField(default=None, max_length=MAX_CONTEXT_LABEL_CHARACTERS)
    field_text: Optional[StrictStr] = PydanticField(default=None, max_length=MAX_CONTEXT_TEXT_CHARACTERS)

class DictationCleanupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    transcript: StrictStr = PydanticField(max_length=MAX_TRANSCRIPT_CHARACTERS)
    dictionary: Dict[StrictStr, StrictStr] = PydanticField(default_factory=dict, max_length=256)
    mode: Literal["rules", "smart"] = "rules"
    language: Optional[StrictStr] = PydanticField(default=None, max_length=8)
    context: Optional[DictationCleanupContext] = None
    words: List[StrictStr] = PydanticField(default_factory=list, max_length=256)
    include_steps: bool = False

class DictationCleanupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cleaned_text: StrictStr = PydanticField(max_length=MAX_TRANSCRIPT_CHARACTERS + 2)
    engine: Literal["rules", "smart_rules"] = "rules"
    fallback_reason: Optional[Literal["disabled", "unavailable", "timeout", "guard"]] = None

class DictationDictionaryChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_text: StrictStr = PydanticField(alias="from", max_length=MAX_TRANSCRIPT_CHARACTERS)
    to_text: StrictStr = PydanticField(alias="to", max_length=128)

class DictationCleanupSteps(BaseModel):
    model_config = ConfigDict(extra="forbid")
    after_smart: Optional[StrictStr] = PydanticField(default=None, max_length=MAX_TRANSCRIPT_CHARACTERS)
    dictionary_changes: List[DictationDictionaryChange] = PydanticField(default_factory=list, max_length=50)

class DictationCleanupStepsResponse(DictationCleanupResponse):
    steps: DictationCleanupSteps

@app.post("/api/dictate/format-notes")
def api_format_notes(req: MeetingNotesRequest):
    """Formats raw spoken transcript into structured meeting minutes with action items."""
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript text cannot be empty.")
    return MeetingDictateEngine.format_meeting_notes(req.transcript)

@app.post(
    "/api/dictate/cleanup",
    response_model=Union[DictationCleanupStepsResponse, DictationCleanupResponse],
    response_model_by_alias=True,
)
def api_cleanup_dictation(req: DictationCleanupRequest):
    """Apply deterministic cleanup, explicit dictionary corrections and the plain word list."""
    if not req.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript text cannot be empty.")
    try:
        if req.context is not None:
            validate_dictation_context(req.context.model_dump())
        cleaned_text, steps = DictationCleanupEngine.clean_with_steps(
            req.transcript,
            dictionary=req.dictionary,
            mode=req.mode,
            language=req.language,
            words=req.words,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=422,
            detail="Transcript or dictionary entries contain unsupported content.",
        ) from error
    engine = "smart_rules" if req.mode == "smart" else "rules"
    if not req.include_steps:
        return DictationCleanupResponse(cleaned_text=cleaned_text, engine=engine)
    return DictationCleanupStepsResponse(
        cleaned_text=cleaned_text,
        engine=engine,
        steps=DictationCleanupSteps(
            after_smart=steps["after_smart"],
            dictionary_changes=[
                DictationDictionaryChange(**{"from": change["from"], "to": change["to"]})
                for change in steps["dictionary_changes"]
            ],
        ),
    )

# ==========================================
# 5. PDF Password Remover & Security API
# ==========================================
from officekit.engines.engine_pdf_security import PDF_OUTPUT_LIMIT_ERROR, PDF_PASSWORD_ERROR, PdfOutputLimitError, PdfSecurityEngine

@app.post("/api/pdf/unlock")
async def api_unlock_pdf(file: UploadFile = File(...), password: str = Form("", max_length=MAX_PDF_PASSWORD_CHARACTERS)):
    """Removes password protection from a PDF."""
    if not is_valid_pdf_password(password, require_non_empty=False):
        raise HTTPException(status_code=422, detail=PDF_PASSWORD_ERROR)
    content = await read_api_upload(file)
    unlocked_bytes, success, msg = PdfSecurityEngine.remove_password(content, password)
    if not success:
        raise HTTPException(status_code=413 if msg == PDF_OUTPUT_LIMIT_ERROR else 400, detail=msg)
    base_name = os.path.splitext(file.filename or "unlocked")[0]
    return Response(
        content=unlocked_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition_attachment(f"{base_name}_unlocked.pdf")
        }
    )

@app.post("/api/pdf/protect")
async def api_protect_pdf(
    file: UploadFile = File(...),
    password: str = Form(..., min_length=1, max_length=MAX_PDF_PASSWORD_CHARACTERS),
):
    """Encrypts a PDF with AES-256 password protection."""
    if not is_valid_pdf_password(password, require_non_empty=True):
        raise HTTPException(status_code=422, detail=PDF_PASSWORD_ERROR)
    content = await read_api_upload(file)
    encrypted_bytes, success, msg = PdfSecurityEngine.protect_pdf(content, password)
    if not success:
        raise HTTPException(status_code=413 if msg == PDF_OUTPUT_LIMIT_ERROR else 400, detail=msg)
    base_name = os.path.splitext(file.filename or "protected")[0]
    return Response(
        content=encrypted_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition_attachment(f"{base_name}_protected.pdf")
        }
    )

# ==========================================
# 6. High-Performance Batch & Modular Endpoints
# ==========================================
from officekit.engines.engine_jobs import DynamicJobEngine
from officekit.engines.engine_pdf_advanced import AdvancedPdfEngine
from officekit.engines.engine_pdf_images import PdfImageExportEngine
import pikepdf
from officekit.engines.engine_units import UnitConverterEngine
from officekit.engines.engine_math import MathEvaluator
from officekit.engines.engine_colors import ColorConverterEngine
from officekit.engines.engine_file_ops import FileOpsEngine, StorageAnalyzerEngine
from officekit.engines.engine_devtools import DevToolsEngine, PrivacySecurityEngine
from typing import List

batch_job_engine = DynamicJobEngine()


@app.post("/api/pdf/page-counts")
async def api_pdf_page_counts(files: List[UploadFile] = File(...)):
    """Inspect ordered PDF inputs for the merge preview without returning filenames."""
    if not 1 <= len(files) <= MAX_PDF_MERGE_FILES:
        raise HTTPException(status_code=422, detail="Select between 1 and 20 PDF files to inspect.")

    results = []
    total_bytes = 0
    total_pages = 0
    ready_count = 0
    unreadable_count = 0
    for index, file in enumerate(files):
        content = await read_api_upload(file)
        total_bytes += len(content)
        if total_bytes > MAX_API_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Combined PDF inputs exceed the 64 MiB processing limit.")

        try:
            if not content:
                raise ValueError("empty PDF")
            with pikepdf.open(io.BytesIO(content)) as pdf:
                page_count = len(pdf.pages)
        except (ValueError, OSError, pikepdf.PdfError, pikepdf.PasswordError):
            results.append({"index": index, "page_count": None, "status": "unreadable"})
            unreadable_count += 1
            continue

        results.append({"index": index, "page_count": page_count, "status": "ready"})
        total_pages += page_count
        ready_count += 1

    return {
        "files": results,
        "total_pages": total_pages,
        "ready_count": ready_count,
        "unreadable_count": unreadable_count,
    }


@app.post("/api/pdf/merge")
async def api_merge_pdfs(files: List[UploadFile] = File(...)):
    """Merge two to twenty selected PDFs without accepting host filesystem paths."""
    if not 2 <= len(files) <= MAX_PDF_MERGE_FILES:
        raise HTTPException(status_code=422, detail="Select between 2 and 20 PDF files to merge.")
    contents = []
    source_labels = []
    total_bytes = 0
    for file in files:
        content = await read_api_upload(file)
        if not content:
            raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE)
        total_bytes += len(content)
        if total_bytes > MAX_API_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Combined PDF inputs exceed the 64 MiB processing limit.")
        contents.append(content)
        source_labels.append((file.filename or "").replace("\\", "/").rsplit("/", 1)[-1])
    try:
        merged = AdvancedPdfEngine.merge_multiple(contents, source_labels=source_labels)
    except PdfOutputLimitError:
        raise HTTPException(status_code=413, detail=PDF_OUTPUT_LIMIT_ERROR) from None
    except (ValueError, OSError, pikepdf.PdfError, pikepdf.PasswordError, pikepdf.OutlineStructureError):
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE) from None
    return Response(
        content=merged,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition_attachment("merged.pdf")},
    )


@app.post("/api/pdf/split")
async def api_split_pdf(
    file: UploadFile = File(...),
    page_ranges: str = Form(..., max_length=4096),
):
    """Extract selected pages in the exact order expressed by 1-based ranges."""
    content = await read_api_upload(file)
    if not content:
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE)
    try:
        split = AdvancedPdfEngine.split_by_ranges(content, page_ranges)
    except PdfOutputLimitError:
        raise HTTPException(status_code=413, detail=PDF_OUTPUT_LIMIT_ERROR) from None
    except (ValueError, OSError, pikepdf.PdfError, pikepdf.PasswordError):
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE) from None
    return Response(
        content=split,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition_attachment("selected-pages.pdf")},
    )


@app.post("/api/pdf/pages/delete")
async def api_delete_pdf_pages(
    file: UploadFile = File(...),
    page_ranges: str = Form(..., max_length=4096),
):
    """Remove selected 1-based page ranges while preserving the source upload."""
    content = await read_api_upload(file)
    if not content:
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE)
    try:
        output = AdvancedPdfEngine.delete_pages(content, page_ranges)
    except PdfOutputLimitError:
        raise HTTPException(status_code=413, detail=PDF_OUTPUT_LIMIT_ERROR) from None
    except (ValueError, OSError, pikepdf.PdfError, pikepdf.PasswordError):
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE) from None
    return Response(
        content=output,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition_attachment("deleted-pages.pdf")},
    )


@app.post("/api/pdf/pages/reorder")
async def api_reorder_pdf_pages(
    file: UploadFile = File(...),
    page_order: str = Form(..., max_length=4096),
):
    """Reorder every page using an exact 1-based sequence; preserve source links."""
    content = await read_api_upload(file)
    if not content:
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE)
    try:
        output = AdvancedPdfEngine.reorder_pages(content, page_order)
    except PdfOutputLimitError:
        raise HTTPException(status_code=413, detail=PDF_OUTPUT_LIMIT_ERROR) from None
    except (ValueError, OSError, pikepdf.PdfError, pikepdf.PasswordError):
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE) from None
    return Response(
        content=output,
        media_type="application/pdf",
        headers={"Content-Disposition": content_disposition_attachment("reordered.pdf")},
    )


@app.post("/api/pdf/split/groups")
async def api_split_pdf_groups(
    file: UploadFile = File(...),
    groups: str = Form(..., max_length=16_384),
):
    """Create a ZIP containing named, non-overlapping page-group PDFs."""
    content = await read_api_upload(file)
    if not content:
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE)
    try:
        parsed_groups = DevToolsEngine._parse_json(groups)
        archive_bytes = AdvancedPdfEngine.split_by_groups(content, parsed_groups)
    except PdfOutputLimitError:
        raise HTTPException(status_code=413, detail=PDF_OUTPUT_LIMIT_ERROR) from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except (OSError, pikepdf.PdfError, pikepdf.PasswordError):
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE) from None
    return Response(
        content=archive_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition_attachment("split-pages.zip")},
    )


@app.post("/api/pdf/compress")
async def api_compress_pdf(
    file: UploadFile = File(...),
    preset: str = Form("balanced", max_length=32),
):
    """Losslessly recompress streams; return the true output/input size ratio."""
    content = await read_api_upload(file)
    if not content:
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE)
    try:
        compressed, ratio = AdvancedPdfEngine.compress_pdf(content, preset)
    except PdfOutputLimitError:
        raise HTTPException(status_code=413, detail=PDF_OUTPUT_LIMIT_ERROR) from None
    except (ValueError, OSError, RuntimeError, pikepdf.PdfError, pikepdf.PasswordError):
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE) from None
    source_name = os.path.splitext(file.filename or "document")[0]
    return Response(
        content=compressed,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition_attachment(f"{source_name}_compressed.pdf"),
            "X-OfficeKit-Output-Input-Ratio": f"{ratio:.8f}",
        },
    )


@app.post("/api/pdf/metadata")
async def api_strip_pdf_metadata(file: UploadFile = File(...)):
    """Remove standard document-info and XMP metadata from a selected PDF."""
    content = await read_api_upload(file)
    if not content:
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE)
    try:
        cleaned = AdvancedPdfEngine.strip_metadata(content)
    except PdfOutputLimitError:
        raise HTTPException(status_code=413, detail=PDF_OUTPUT_LIMIT_ERROR) from None
    except (ValueError, OSError, pikepdf.PdfError, pikepdf.PasswordError):
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE) from None
    source_name = os.path.splitext(file.filename or "document")[0]
    return Response(
        content=cleaned,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition_attachment(f"{source_name}_metadata_removed.pdf")
        },
    )


class PdfPageThumbnailResponseItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_number: StrictInt = PydanticField(ge=1, le=2_000)
    width_points: float = PydanticField(gt=0, allow_inf_nan=False)
    height_points: float = PydanticField(gt=0, allow_inf_nan=False)
    data_base64: StrictStr = PydanticField(min_length=1, max_length=22_369_622)


class PdfPageThumbnailsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_count: StrictInt = PydanticField(ge=1, le=2_000)
    pages: List[PdfPageThumbnailResponseItem] = PydanticField(min_length=1, max_length=24)

    @model_validator(mode="after")
    def page_numbers_must_be_unique_and_in_range(self):
        page_numbers = [page.page_number for page in self.pages]
        if any(number > self.page_count for number in page_numbers) or len(set(page_numbers)) != len(page_numbers):
            raise ValueError("Thumbnail pages must be unique source pages within the document.")
        return self


class PdfTablePreviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_number: StrictInt = PydanticField(ge=1, le=50)
    table_number: StrictInt = PydanticField(ge=1, le=40)
    row_count: StrictInt = PydanticField(ge=1, le=2_000)
    column_count: StrictInt = PydanticField(ge=1, le=80)
    preview_rows: List[List[StrictStr]] = PydanticField(max_length=12)


class PdfTablePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_count: StrictInt = PydanticField(ge=1, le=50)
    tables: List[PdfTablePreviewItem] = PydanticField(max_length=40)


@app.post("/api/pdf/tables", response_model=PdfTablePreviewResponse)
async def api_pdf_table_preview(file: UploadFile = File(...)):
    """Preview selectable PDF tables without guessing headers or running OCR."""
    from officekit.engines.engine_pdf_tables import PdfTableInputError, extract_pdf_tables

    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Choose a PDF file.")
    content = await read_api_upload(file)
    try:
        result = extract_pdf_tables(content)
    except PdfTableInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    return result


@app.post("/api/pdf/tables/export")
async def api_pdf_table_export(
    file: UploadFile = File(...),
    page_number: int = Form(..., ge=1, le=50),
    table_number: int = Form(..., ge=1, le=40),
    export_format: Literal["csv", "xls", "xlsx"] = Form(..., alias="format"),
):
    """Export one selected, re-extracted PDF table as formula-safe CSV, XLS or XLSX."""
    from officekit.engines.engine_pdf_tables import (
        PdfTableExportError,
        PdfTableInputError,
        export_pdf_table,
    )

    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Choose a PDF file.")
    content = await read_api_upload(file)
    try:
        output, media_type = export_pdf_table(content, page_number, table_number, export_format)
    except PdfTableInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except PdfTableExportError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    extension = export_format
    filename = f"pdf-table-page-{page_number:02d}-table-{table_number:02d}.{extension}"
    return Response(
        content=output,
        media_type=media_type,
        headers={"Content-Disposition": content_disposition_attachment(filename)},
    )


@app.post("/api/pdf/text")
async def api_pdf_text_extract(
    file: UploadFile = File(...),
    page_ranges: str = Form("", max_length=4096),
    output_format: Literal["txt", "md"] = Form("txt", alias="format"),
):
    """Extract selectable page text as a bounded text or Markdown attachment."""
    from officekit.engines.engine_pdf_text import PdfTextError, extract_pdf_text

    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="Choose a PDF file.")
    content = await read_api_upload(file)
    try:
        result = extract_pdf_text(content, page_ranges, output_format)
    except PdfTextError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    filename = "extracted-text.md" if output_format == "md" else "extracted-text.txt"
    media_type = "text/markdown" if output_format == "md" else "text/plain"
    return Response(
        content=result["text"].encode("utf-8"),
        media_type=media_type,
        headers={
            "Content-Disposition": content_disposition_attachment(filename),
            "X-OfficeKit-Page-Count": str(result["page_count"]),
            "X-OfficeKit-Selected-Pages": ",".join(map(str, result["selected_pages"])),
            "X-OfficeKit-Missing-Text-Pages": ",".join(map(str, result["missing_text_pages"])),
            "X-OfficeKit-Extracted-Characters": str(result["character_count"]),
        },
    )


@app.post("/api/pdf/page-thumbnails", response_model=PdfPageThumbnailsResponse)
async def api_render_pdf_page_thumbnails(
    file: UploadFile = File(...),
    page_numbers: str = Form(..., max_length=4_096),
):
    """Return an ordered bounded set of local PDF page thumbnails."""
    content = await read_api_upload(file)
    try:
        parts = page_numbers.split(",")
        if not 1 <= len(parts) <= PdfImageExportEngine.MAX_THUMBNAIL_WINDOW or any(
            not re.fullmatch(r"[0-9]+", part) for part in parts
        ):
            raise ValueError("Invalid thumbnail page list")
        requested_pages = [int(part) for part in parts]
        result = PdfImageExportEngine.render_page_thumbnails(
            content, requested_pages,
        )
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE) from None
    return result


@app.post("/api/pdf/images")
async def api_render_pdf_images(
    file: UploadFile = File(...),
    target_format: str = Form("png", max_length=16),
    dpi: int = Form(150, ge=PdfImageExportEngine.MIN_DPI, le=PdfImageExportEngine.MAX_DPI),
    quality: int = Form(90, ge=1, le=100),
):
    """Render every selected PDF page to a bounded, ordered PNG/JPEG ZIP."""
    content = await read_api_upload(file)
    try:
        archive, page_count = PdfImageExportEngine.render_pdf(content, target_format, dpi=dpi, quality=quality)
    except (ValueError, OSError, RuntimeError):
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE) from None
    source_name = os.path.splitext(file.filename or "document")[0]
    safe_base_name = re.sub(r"[^A-Za-z0-9._-]+", "_", source_name).strip("._-")[:80] or "document"
    return Response(
        content=archive,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition_attachment(f"{safe_base_name}_pages.zip"),
            "X-OfficeKit-Page-Count": str(page_count),
        },
    )

class SystemResourceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu_count: StrictInt = PydanticField(ge=1, le=1024)
    cpu_percent: float = PydanticField(ge=0, le=100, allow_inf_nan=False)
    cpu_sample_interval_seconds: float = PydanticField(ge=0.1, le=0.1, allow_inf_nan=False)
    total_ram_gb: float = PydanticField(gt=0, allow_inf_nan=False)
    available_ram_gb: float = PydanticField(ge=0, allow_inf_nan=False)
    memory_total_bytes: StrictInt = PydanticField(gt=0, le=2**70)
    memory_available_bytes: StrictInt = PydanticField(ge=0, le=2**70)
    memory_used_estimate_bytes: StrictInt = PydanticField(ge=0, le=2**70)
    memory_percent: float = PydanticField(ge=0, le=100, allow_inf_nan=False)
    optimal_workers: StrictInt = PydanticField(ge=1, le=32)
    cached: StrictBool
    sample_age_ms: StrictInt = PydanticField(ge=0, le=60_000)


class SystemInfoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    os_name: Literal["macOS"]
    os_version: StrictStr = PydanticField(min_length=1, max_length=16)
    architecture: StrictStr = PydanticField(min_length=1, max_length=32)
    logical_cpu_count: StrictInt = PydanticField(ge=1, le=1024)
    physical_cpu_count: Optional[StrictInt] = PydanticField(default=None, ge=1, le=1024)
    memory_total_bytes: StrictInt = PydanticField(gt=0, le=2**70)
    memory_total_gb: float = PydanticField(gt=0, allow_inf_nan=False)
    privacy_notice: StrictStr = PydanticField(max_length=180)
    report_text: StrictStr = PydanticField(min_length=1, max_length=512)


system_info_service = SystemInfoService()


@app.get("/api/system/info", response_model=SystemInfoResponse)
def get_system_info():
    """Return a redacted support summary without host, account or device identifiers."""
    try:
        return system_info_service.snapshot()
    except SystemInfoUnsupportedError as error:
        raise HTTPException(status_code=501, detail="System information is not supported on this platform.") from error
    except SystemInfoUnavailableError as error:
        raise HTTPException(status_code=503, detail="System information is unavailable.") from error


system_resource_service = SystemResourceService()
system_metrics_service = SystemMetricsService(
    resource_service=system_resource_service,
    memory_percent_provider=macos_memory_used_percent,
    disk_path=data_volume_path(),
)


class SystemMemoryBreakdownResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_bytes: StrictInt = PydanticField(ge=0)
    used_bytes: StrictInt = PydanticField(ge=0)
    app_bytes: StrictInt = PydanticField(ge=0)
    wired_bytes: StrictInt = PydanticField(ge=0)
    compressed_bytes: StrictInt = PydanticField(ge=0)
    free_bytes: StrictInt = PydanticField(ge=0)


class SystemSwapResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    used_bytes: StrictInt | None = PydanticField(default=None, ge=0)
    total_bytes: StrictInt = PydanticField(ge=0)
    percent: float = PydanticField(ge=0, le=100, allow_inf_nan=False)


class SystemCpuBreakdownResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_percent: float = PydanticField(ge=0, le=100, allow_inf_nan=False)
    system_percent: float = PydanticField(ge=0, le=100, allow_inf_nan=False)
    idle_percent: float = PydanticField(ge=0, le=100, allow_inf_nan=False)


class SystemCpuTopologyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: StrictStr = PydanticField(max_length=64)
    performance_cores: StrictInt | None = PydanticField(default=None, ge=1, le=256)
    efficiency_cores: StrictInt | None = PydanticField(default=None, ge=1, le=256)


class SystemVolumeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = PydanticField(max_length=40)
    used_bytes: StrictInt = PydanticField(ge=0)
    total_bytes: StrictInt = PydanticField(ge=1)


class SystemNetworkDetailsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interface: StrictStr = PydanticField(max_length=16)
    local_address: StrictStr | None = PydanticField(default=None, max_length=15)
    sent_total_bytes: StrictInt = PydanticField(ge=0)
    received_total_bytes: StrictInt = PydanticField(ge=0)


class SystemBluetoothDeviceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = PydanticField(max_length=40)
    percent: StrictInt = PydanticField(ge=0, le=100)


class SystemDiskDetailsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    used_bytes: StrictInt | None = PydanticField(default=None, ge=0)
    total_bytes: StrictInt | None = PydanticField(default=None, ge=0)
    read_total_bytes: StrictInt | None = PydanticField(default=None, ge=0)
    write_total_bytes: StrictInt | None = PydanticField(default=None, ge=0)
    volumes: list[SystemVolumeResponse] | None = PydanticField(default=None, max_length=8)
    read_bytes_per_second: float | None = PydanticField(default=None, ge=0, allow_inf_nan=False)
    write_bytes_per_second: float | None = PydanticField(default=None, ge=0, allow_inf_nan=False)


class SystemGpuMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    utilization_percent: float | None = PydanticField(default=None, ge=0, le=100, allow_inf_nan=False)
    renderer_percent: float | None = PydanticField(default=None, ge=0, le=100, allow_inf_nan=False)
    tiler_percent: float | None = PydanticField(default=None, ge=0, le=100, allow_inf_nan=False)
    model: StrictStr | None = PydanticField(default=None, max_length=48)
    core_count: StrictInt | None = PydanticField(default=None, ge=1, le=256)


class SystemBatteryMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    percent: float | None = PydanticField(default=None, ge=0, le=100, allow_inf_nan=False)
    power_source: Literal["ac", "battery"] | None = None
    state: Literal["charging", "charged", "discharging", "unknown"]
    time_remaining_seconds: StrictInt | None = PydanticField(default=None, ge=0)
    cycle_count: StrictInt | None = PydanticField(default=None, ge=0)
    designed_capacity_mah: StrictInt | None = PydanticField(default=None, ge=0)
    full_charge_capacity_mah: StrictInt | None = PydanticField(default=None, ge=0)
    health_percent: float | None = PydanticField(default=None, ge=0, le=100, allow_inf_nan=False)
    condition: StrictStr | None = PydanticField(default=None, max_length=40)
    adapter_watts: float | None = PydanticField(default=None, ge=1, le=500, allow_inf_nan=False)
    voltage_v: float | None = PydanticField(default=None, ge=0, le=40, allow_inf_nan=False)
    current_a: float | None = PydanticField(default=None, ge=-20, le=20, allow_inf_nan=False)
    power_w: float | None = PydanticField(default=None, ge=-800, le=800, allow_inf_nan=False)
    temperature_c: float | None = PydanticField(default=None, ge=-20, le=100, allow_inf_nan=False)


class SystemSensorMetricResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = PydanticField(max_length=60)
    current_c: float = PydanticField(ge=-20, le=150, allow_inf_nan=False)
    high_c: float | None = PydanticField(default=None, ge=-20, le=150, allow_inf_nan=False)


class SystemMetricsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cpu_percent: float | None = PydanticField(ge=0, le=100, allow_inf_nan=False)
    memory_percent: float | None = PydanticField(ge=0, le=100, allow_inf_nan=False)
    storage_percent: float | None = PydanticField(ge=0, le=100, allow_inf_nan=False)
    volume_label: StrictStr
    upload_bytes_per_second: float | None = PydanticField(ge=0, allow_inf_nan=False)
    download_bytes_per_second: float | None = PydanticField(ge=0, allow_inf_nan=False)
    captured_at: StrictStr
    sample_age_ms: StrictInt = PydanticField(ge=0)
    reasons: dict[str, str]
    memory: SystemMemoryBreakdownResponse | None = None
    memory_pressure: Literal["normal", "warning", "critical"] | None = None
    swap: SystemSwapResponse | None = None
    cpu_breakdown: SystemCpuBreakdownResponse | None = None
    load_average: list[float] | None = None
    uptime_seconds: StrictInt | None = PydanticField(default=None, ge=0)
    disk: SystemDiskDetailsResponse | None = None
    cpu_cores_percent: list[float] | None = None
    gpu: SystemGpuMetricsResponse | None = None
    battery: SystemBatteryMetricsResponse | None = None
    sensors: list[SystemSensorMetricResponse] | None = PydanticField(default=None, max_length=16)
    cpu_topology: SystemCpuTopologyResponse | None = None
    network: SystemNetworkDetailsResponse | None = None
    bluetooth: list[SystemBluetoothDeviceResponse] | None = PydanticField(default=None, max_length=8)


@app.get("/api/system/metrics", response_model=SystemMetricsResponse)
def api_system_metrics():
    return system_metrics_service.snapshot()


@app.get("/api/system/resources", response_model=SystemResourceResponse)
def get_system_resources():
    """Return a bounded local CPU/memory sample; repeated requests are cached for one second."""
    try:
        return system_resource_service.snapshot()
    except SystemResourceError as error:
        raise HTTPException(status_code=503, detail="System resource information is unavailable.") from error


process_manager_service = ProcessManagerService()


class ProcessItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pid: StrictInt = PydanticField(ge=0, le=4_194_304)
    name: StrictStr = PydanticField(max_length=128)
    app_name: StrictStr | None = PydanticField(default=None, max_length=128)
    cpu_percent: float = PydanticField(ge=0, allow_inf_nan=False)
    gpu_percent: float | None = PydanticField(default=None, ge=0, le=100, allow_inf_nan=False)
    memory_bytes: StrictInt = PydanticField(ge=0)
    memory_mb: float = PydanticField(ge=0, allow_inf_nan=False)
    memory_percent: float = PydanticField(ge=0, le=100, allow_inf_nan=False)
    status: StrictStr = PydanticField(max_length=32)
    is_killable: StrictBool


class ProcessApplicationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = PydanticField(max_length=128)
    pid: StrictInt = PydanticField(ge=0, le=4_194_304)
    process_count: StrictInt = PydanticField(ge=1, le=100_000)
    process_names: list[Annotated[StrictStr, StringConstraints(max_length=128, strict=True)]] = PydanticField(max_length=4)
    cpu_percent: float = PydanticField(ge=0, allow_inf_nan=False)
    gpu_percent: float | None = PydanticField(default=None, ge=0, le=100, allow_inf_nan=False)
    memory_bytes: StrictInt = PydanticField(ge=0)
    memory_mb: float = PydanticField(ge=0, allow_inf_nan=False)
    memory_percent: float = PydanticField(ge=0, le=100, allow_inf_nan=False)
    status: StrictStr = PydanticField(max_length=32)
    is_killable: StrictBool


class ProcessListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    processes: list[ProcessItem] = PydanticField(max_length=100)
    applications: list[ProcessApplicationItem] = PydanticField(default_factory=list, max_length=100)
    total_applications: StrictInt = PydanticField(default=0, ge=0)
    total_count: StrictInt = PydanticField(ge=0)
    captured_at: StrictStr


class ProcessTerminateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pid: StrictInt = PydanticField(ge=2, le=4_194_304)
    force: StrictBool = False


class ProcessTerminateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    success: StrictBool
    pid: StrictInt
    name: StrictStr
    message: StrictStr


@app.get("/api/system/processes", response_model=ProcessListResponse)
def get_system_processes(
    limit: int = Query(default=30, ge=1, le=100),
    sort_by: Literal["cpu", "memory", "gpu"] = Query(default="cpu"),
):
    """Return a bounded snapshot of active processes sorted by resource consumption."""
    try:
        return process_manager_service.list_processes(limit=limit, sort_by=sort_by)
    except Exception as error:
        raise HTTPException(status_code=503, detail="Process list is unavailable.") from error


@app.post("/api/system/processes/terminate", response_model=ProcessTerminateResponse)
def terminate_process(req: ProcessTerminateRequest):
    """Safely terminate a user-space process with strict bounds and protection."""
    try:
        return process_manager_service.terminate_process(req.pid, force=req.force)
    except ProcessSafetyError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ProcessNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ProcessAccessDeniedError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail="Process termination could not be completed.") from error


class NetworkPingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: StrictStr = PydanticField(min_length=1, max_length=253)
    count: StrictInt = PydanticField(default=4, ge=1, le=10)
    timeout_seconds: Union[StrictFloat, StrictInt] = PydanticField(default=3.0, ge=0.1, le=10)

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def timeout_must_be_a_json_number(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Timeout must be a JSON number")
        return value


class NetworkLatencyResponse(BaseModel):
    min: float
    avg: float
    max: float


class NetworkPingResponse(BaseModel):
    target: str
    status: Literal[
        "reachable", "partial_loss", "no_reply", "incomplete", "permission_denied", "timed_out",
    ]
    packets_sent: Optional[int] = None
    packets_received: Optional[int] = None
    packet_loss_percent: Optional[float] = None
    latency_ms: Optional[NetworkLatencyResponse] = None


class NetworkDnsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hostname: StrictStr = PydanticField(min_length=1, max_length=1024)
    record_type: Literal["A", "AAAA", "CNAME", "NS", "MX", "TXT", "SPF", "DKIM"] = "A"
    nameserver: Optional[StrictStr] = PydanticField(default=None, max_length=45)
    timeout_seconds: Union[StrictFloat, StrictInt] = PydanticField(default=3.0, ge=0.2, le=5.0)
    selector: Optional[StrictStr] = PydanticField(default=None, max_length=63)

    @model_validator(mode="after")
    def selector_belongs_to_dkim(self):
        if self.record_type == "DKIM":
            try:
                self.selector = normalize_dkim_selector(self.selector)
            except DnsLookupInputError as error:
                raise ValueError("A DKIM selector is required") from error
        elif self.selector is not None:
            raise ValueError("A selector is only used for DKIM lookups")
        return self

    @field_validator("hostname")
    @classmethod
    def hostname_must_be_a_dns_name(cls, value):
        try:
            return normalize_dns_hostname(value)
        except DnsLookupInputError as error:
            raise ValueError("A valid DNS hostname is required") from error

    @field_validator("nameserver")
    @classmethod
    def nameserver_must_be_an_ip(cls, value):
        try:
            return normalize_nameserver(value)
        except DnsLookupInputError as error:
            raise ValueError("Nameserver must be an IPv4 or IPv6 address") from error

    @field_validator("timeout_seconds", mode="before")
    @classmethod
    def timeout_must_be_a_json_number(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Timeout must be a JSON number")
        return value


class NetworkDnsMxRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preference: StrictInt = PydanticField(ge=0, le=65535)
    exchange: StrictStr = PydanticField(min_length=1, max_length=253)


class NetworkDnsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hostname: StrictStr
    record_type: Literal["A", "AAAA", "CNAME", "NS", "MX", "TXT", "SPF", "DKIM"]
    status: Literal["success", "nxdomain", "no_records", "timed_out", "resolver_error"]
    records: List[Union[StrictStr, NetworkDnsMxRecord]] = PydanticField(max_length=100)
    truncated: StrictBool
    nameserver: Optional[StrictStr]
    duration_ms: StrictInt = PydanticField(ge=0, le=10_000)


class NetworkInterfaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_addresses: StrictBool = False


class NetworkInterfaceAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family: Literal["IPv4", "IPv6"]
    address: StrictStr = PydanticField(min_length=1, max_length=128)
    netmask: Optional[StrictStr] = PydanticField(default=None, max_length=128)
    broadcast: Optional[StrictStr] = PydanticField(default=None, max_length=128)


class NetworkInterfaceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = PydanticField(min_length=1, max_length=128)
    is_up: Optional[StrictBool]
    address_count: StrictInt = PydanticField(ge=0, le=2048)
    addresses_hidden: StrictBool
    addresses: List[NetworkInterfaceAddress] = PydanticField(max_length=32)


class NetworkInterfacesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_addresses: StrictBool
    privacy_notice: StrictStr = PydanticField(max_length=160)
    interfaces: List[NetworkInterfaceEntry] = PydanticField(max_length=64)
    truncated: StrictBool


class NetworkHealthRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NetworkHealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["healthy", "router_slow", "internet_slow", "offline", "incomplete", "router_unmeasured", "no_route"]
    headline: StrictStr = PydanticField(max_length=80)
    detail: StrictStr = PydanticField(max_length=180)
    interface: StrictStr | None = PydanticField(default=None, max_length=64)
    link_type: Literal["wifi", "wired", "unknown"]
    sample_count: StrictInt = PydanticField(ge=0, le=3)
    router_median_ms: float | None = PydanticField(default=None, ge=0, le=10000, allow_inf_nan=False)
    router_loss_percent: float | None = PydanticField(default=None, ge=0, le=100, allow_inf_nan=False)
    internet_median_ms: float | None = PydanticField(default=None, ge=0, le=10000, allow_inf_nan=False)
    internet_loss_percent: float = PydanticField(ge=0, le=100, allow_inf_nan=False)
    checked_at: StrictStr = PydanticField(max_length=40)


dns_lookup_service = DnsLookup()
network_interface_service = NetworkInterfaceService()
network_health_service = NetworkHealthService()


@app.post("/api/network/health", response_model=NetworkHealthResponse)
def check_network_health(_req: NetworkHealthRequest):
    """Compare the active gateway with fixed internet endpoints on explicit request."""
    try:
        return network_health_service.check()
    except NetworkHealthUnsupportedError as error:
        raise HTTPException(status_code=501, detail=str(error)) from error
    except NetworkHealthError as error:
        raise HTTPException(status_code=503, detail="Network health information is unavailable.") from error


@app.post("/api/network/dns", response_model=NetworkDnsResponse)
def lookup_dns_records(req: NetworkDnsRequest):
    """Query selected DNS records using the system resolver or an explicit IP resolver."""
    try:
        return dns_lookup_service.lookup(
            req.hostname,
            record_type=req.record_type,
            nameserver=req.nameserver,
            timeout_seconds=float(req.timeout_seconds),
            selector=req.selector,
        )
    except DnsLookupInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except DnsLookupError as error:
        raise HTTPException(status_code=503, detail="DNS lookup is unavailable.") from error


@app.post("/api/network/interfaces", response_model=NetworkInterfacesResponse)
def list_network_interfaces(req: NetworkInterfaceRequest):
    """Summarize local IPv4/IPv6 interfaces; addresses require explicit opt-in."""
    try:
        return network_interface_service.list_interfaces(include_addresses=req.include_addresses)
    except NetworkInterfaceError as error:
        raise HTTPException(status_code=503, detail="Network interface information is unavailable.") from error


@app.post("/api/network/ping", response_model=NetworkPingResponse)
def ping_network_target(req: NetworkPingRequest):
    """Measure actual ICMP response and packet loss using the native macOS ping tool."""
    try:
        return NetworkDiagnostics.ping(req.target, req.count, float(req.timeout_seconds))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except NetworkDiagnosticError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from None

class UnitCatalogOption(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: StrictStr = PydanticField(min_length=1, max_length=50)
    label: StrictStr = PydanticField(min_length=1, max_length=80)


class UnitCatalogCategory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: StrictStr = PydanticField(min_length=1, max_length=50)
    label: StrictStr = PydanticField(min_length=1, max_length=80)
    units: List[UnitCatalogOption] = PydanticField(min_length=2, max_length=256)


class UnitCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    categories: List[UnitCatalogCategory] = PydanticField(min_length=1, max_length=32)


@app.get("/api/units/catalog", response_model=UnitCatalogResponse)
def get_unit_catalog() -> UnitCatalogResponse:
    """Expose the converter's canonical categories and deduplicated unit choices."""
    return UnitCatalogResponse.model_validate(UnitConverterEngine.catalog())


class UnitsConvertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float = PydanticField(ge=-1e100, le=1e100, allow_inf_nan=False)
    category: Literal[
        "length", "area", "volume", "mass", "speed", "time",
        "energy", "power", "pressure", "force", "frequency", "angle",
        "digital_storage", "temperature", "typography",
    ]
    from_unit: str = PydanticField(min_length=1, max_length=50, strict=True)
    to_unit: str = PydanticField(min_length=1, max_length=50, strict=True)

    @field_validator("value", mode="before")
    @classmethod
    def value_must_be_json_number(cls, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Value must be a JSON number")
        return value


class UnitsConvertResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: float = PydanticField(allow_inf_nan=False)
    category: Literal[
        "length", "area", "volume", "mass", "speed", "time",
        "energy", "power", "pressure", "force", "frequency", "angle",
        "digital_storage", "temperature", "typography",
    ]
    from_unit: str
    to_unit: str


@app.post("/api/units/convert", response_model=UnitsConvertResponse)
def api_convert_units(req: UnitsConvertRequest) -> UnitsConvertResponse:
    try:
        result = UnitConverterEngine.convert(req.value, req.category, req.from_unit, req.to_unit)
        return UnitsConvertResponse(
            result=result,
            category=req.category,
            from_unit=req.from_unit,
            to_unit=req.to_unit,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


class ColorConvertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = PydanticField(min_length=1, max_length=128, strict=True)
    source_format: Literal["hex", "rgb", "hsl", "hsv"]
    target_format: Literal["hex", "rgb", "hsl", "hsv"]


class ColorConvertResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str
    source_format: Literal["hex", "rgb", "hsl", "hsv"]
    target_format: Literal["hex", "rgb", "hsl", "hsv"]


@app.post("/api/colors/convert", response_model=ColorConvertResponse)
def api_convert_color(req: ColorConvertRequest) -> ColorConvertResponse:
    try:
        converted = ColorConverterEngine.convert(req.value, req.source_format, req.target_format)
        return ColorConvertResponse(
            value=converted,
            source_format=req.source_format,
            target_format=req.target_format,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

class MathEvalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expression: str = PydanticField(min_length=1, max_length=512, strict=True)
    angle_mode: Literal["radians", "degrees"] = "radians"

    @field_validator("expression")
    @classmethod
    def expression_must_not_be_whitespace(cls, value):
        if not value.strip():
            raise ValueError("Expression must contain a calculation")
        return value


class MathEvalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: float = PydanticField(allow_inf_nan=False)
    expression: str
    angle_mode: Literal["radians", "degrees"]


@app.post("/api/math/eval", response_model=MathEvalResponse)
def api_eval_math(req: MathEvalRequest):
    try:
        result = MathEvaluator.evaluate(req.expression, angle_mode=req.angle_mode)
        return MathEvalResponse(result=result, expression=req.expression, angle_mode=req.angle_mode)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

class DevToolsFormatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = PydanticField(max_length=DevToolsEngine.MAX_TEXT_BYTES, strict=True)
    operation: Literal[
        "format_json", "json_to_yaml", "yaml_to_json", "base64_encode", "base64_decode",
        "url_encode", "url_decode", "jwt_decode",
    ]


class DevToolsResultResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: str


class JwtDecodeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    header: Dict[str, Any]
    payload: Dict[str, Any]
    is_verified: Literal[False]
    notice: str


@app.post("/api/devtools/process", response_model=DevToolsResultResponse | JwtDecodeResponse)
def api_devtools_process(req: DevToolsFormatRequest):
    try:
        op = req.operation
        if op == 'format_json':
            return {"result": DevToolsEngine.format_json(req.content)}
        if op == 'json_to_yaml':
            return {"result": DevToolsEngine.json_to_yaml(req.content)}
        if op == 'yaml_to_json':
            return {"result": DevToolsEngine.yaml_to_json(req.content)}
        if op == 'base64_encode':
            return {"result": DevToolsEngine.base64_encode(req.content)}
        if op == 'base64_decode':
            return {"result": DevToolsEngine.base64_decode(req.content)}
        if op == 'url_encode':
            return {"result": DevToolsEngine.url_encode(req.content)}
        if op == 'url_decode':
            return {"result": DevToolsEngine.url_decode(req.content)}
        return DevToolsEngine.decode_jwt(req.content)
    except (ValueError, RecursionError) as error:
        raise HTTPException(status_code=422, detail="Developer-tool input is invalid or exceeds supported limits.") from error

class HashGenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = PydanticField(max_length=PrivacySecurityEngine.MAX_HASH_INPUT_BYTES, strict=True)
    secret: Optional[str] = PydanticField(
        default=None,
        max_length=PrivacySecurityEngine.MAX_HMAC_SECRET_BYTES,
        strict=True,
    )


class HashGenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    md5: str = PydanticField(pattern=r"^[0-9a-f]{32}$")
    sha1: str = PydanticField(pattern=r"^[0-9a-f]{40}$")
    sha256: str = PydanticField(pattern=r"^[0-9a-f]{64}$")
    sha512: str = PydanticField(pattern=r"^[0-9a-f]{128}$")
    crc32: str = PydanticField(pattern=r"^[0-9a-f]{8}$")
    hmac_sha256: Optional[str] = PydanticField(default=None, pattern=r"^[0-9a-f]{64}$")


@app.post("/api/crypto/hashes", response_model=HashGenResponse, response_model_exclude_none=True)
def api_crypto_hashes(req: HashGenRequest):
    try:
        return PrivacySecurityEngine.generate_hashes(req.text, req.secret)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


class PasswordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = PydanticField(min_length=12, max_length=256)
    theoretical_search_space_bits: float = PydanticField(gt=0, le=2048)


@app.post("/api/crypto/password", response_model=PasswordResponse)
def api_crypto_password(
    response: Response,
    length: int = Query(default=16, ge=12, le=256),
    include_symbols: bool = Query(default=True),
):
    response.headers["Cache-Control"] = "no-store"
    return PasswordResponse(
        password=PrivacySecurityEngine.generate_password(length, include_symbols),
        theoretical_search_space_bits=PrivacySecurityEngine.password_search_space_bits(length, include_symbols),
    )


class PassphraseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    word_count: StrictInt = PydanticField(default=6, ge=6, le=12)
    separator: Literal[" ", ".", "_"] = " "


class PassphraseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passphrase: str = PydanticField(min_length=1, max_length=512, strict=True)
    word_count: StrictInt = PydanticField(ge=6, le=12)
    separator: Literal[" ", ".", "_"]
    theoretical_search_space_bits: float = PydanticField(gt=0, le=256, allow_inf_nan=False)


@app.post("/api/crypto/passphrase", response_model=PassphraseResponse)
def api_crypto_passphrase(req: PassphraseRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        passphrase = PrivacySecurityEngine.generate_passphrase(req.word_count, req.separator)
        return PassphraseResponse(
            passphrase=passphrase,
            word_count=req.word_count,
            separator=req.separator,
            theoretical_search_space_bits=PrivacySecurityEngine.passphrase_search_space_bits(req.word_count),
        )
    except ValueError as error:
        raise HTTPException(status_code=503, detail="Passphrase generation is unavailable.") from error

class RenamePlanRequest(BaseModel):
    filenames: List[WorkspaceFileName] = PydanticField(min_length=1, max_length=1000)
    pattern_type: Literal["sequence", "affix", "casing", "replace"] = "sequence"
    prefix: str = PydanticField(default="", max_length=128)
    suffix: str = PydanticField(default="", max_length=128)
    start_num: int = PydanticField(default=1, ge=0, le=9_999_999_999)
    digits: int = PydanticField(default=3, ge=1, le=12)
    casing: Literal["kebab", "snake", "camel", "title"] = "kebab"
    find_text: str = PydanticField(default="", max_length=256)
    replace_text: str = PydanticField(default="", max_length=256)

@app.post("/api/files/rename-plan")
def api_rename_plan(req: RenamePlanRequest):
    return {
        "renamed": FileOpsEngine.generate_rename_plan(
            req.filenames,
            pattern_type=req.pattern_type,
            prefix=req.prefix,
            suffix=req.suffix,
            start_num=req.start_num,
            digits=req.digits,
            casing=req.casing,
            find_text=req.find_text,
            replace_text=req.replace_text,
        )
    }


workspace_store = FileWorkspaceStore()
atexit.register(workspace_store.close)
file_selection_store = FileSelectionStore()
invoice_libraries = InvoiceLibraries(file_selection_store, invoice_bindings_path(os.path.dirname(media_pipeline_path())))
app.include_router(create_invoice_router(invoice_libraries, release_profile=RELEASE_PROFILE.name))
file_job_store = FileJobStore(file_selection_store, release_profile=RELEASE_PROFILE.name)
trash_restorer = TrashRestorer(storage_cleaner.ledger, os.path.join(storage_cleaner.home, '.Trash'), file_selection_store,
                               native_token=file_selection_store.native_token)
TRASH_BETA_MESSAGE = 'This operation is not available in the OfficeKit private beta.'
media_import_store = MediaImportStore()
media_image_staging_store = MediaStagingStore()
media_watermark_staging_store = MediaStagingStore(max_image_bytes=5 * 1024 * 1024, max_images=10)
media_pipeline_store = MediaPipelineStore()
media_preset_zone_store = MediaPresetZoneStore(media_pipeline_store)
media_operation_defaults_store = MediaOperationDefaultsStore()
media_pipeline_trigger_store = MediaPipelineTriggerStore(media_pipeline_store)
media_job_store = MediaJobStore(
    file_selection_store,
    import_store=media_import_store,
    image_staging_store=media_image_staging_store,
    watermark_staging_store=media_watermark_staging_store,
)
media_folder_automation_store = MediaFolderAutomationStore(file_selection_store, media_pipeline_store, media_job_store)
pdf_workspace_store = PdfWorkspace()
app.include_router(create_pdf_router(pdf_workspace_store, file_selection_store))
app.include_router(create_media_router(
    media_job_store,
    media_import_store,
    media_image_staging_store,
    media_pipeline_store,
    media_folder_automation_store,
    media_watermark_staging_store,
    media_preset_zone_store,
    media_operation_defaults_store,
    media_pipeline_trigger_store,
))
for slice_router in slice_routers():
    app.include_router(slice_router)
atexit.register(pdf_workspace_store.close)
atexit.register(file_selection_store.close)
atexit.register(file_job_store.close)
atexit.register(media_job_store.close)
atexit.register(media_folder_automation_store.close)
atexit.register(media_import_store.close)


class FileSelectionResponse(BaseModel):
    id: str
    displayNames: list[str]
    access: Literal["read", "read-write"]
    expiresAt: float


class FileSelectionSubsetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    fileIds: list[Annotated[StrictStr, StringConstraints(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]] = PydanticField(min_length=1, max_length=30)


class FileManifestItemResponse(BaseModel):
    id: str
    name: str
    size_bytes: int


class FileManifestResponse(FileSelectionResponse):
    files: list[FileManifestItemResponse]
    offset: int
    hasMore: bool


class ImageSummaryFolderResponse(BaseModel):
    name: str
    images: int


class ImageSummaryResponse(BaseModel):
    folders: list[ImageSummaryFolderResponse]
    images: int
    skipped: int
    limit: int


class ArchiveCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str
    label: str
    extensions: list[str]
    read: Literal['supported', 'partial', 'unsupported']
    extract: Literal['supported', 'partial', 'unsupported']
    create: Literal['supported', 'partial', 'unsupported']
    limitations: list[str]


class ArchiveFormatsResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    formats: list[ArchiveCapabilityResponse]


class ArchiveEntryResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str
    name: str
    size_bytes: int
    compressed_bytes: int
    kind: Literal['file', 'directory']
    encrypted: bool
    modified_at: str
    nested_archive: bool
    extractable: bool


class ArchiveEntriesResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    format: str
    entries: list[ArchiveEntryResponse]
    offset: int
    hasMore: bool
    total: int


class FileOutputGrantResponse(BaseModel):
    id: str
    displayName: str
    kind: Literal["file", "directory"]
    expiresAt: float


class FileJobResponse(BaseModel):
    id: str
    state: Literal["queued", "running", "ready", "failed", "cancelled"]
    kind: str | None = None
    progress: int | None = None
    total: int | None = None
    phase: str | None = None
    insights: dict = PydanticField(default_factory=dict)
    error: str | None = None
    resultRef: str | None = None
    cancellationRequested: bool | None = None


class FileJobCancellationResponse(BaseModel):
    id: str
    state: Literal["queued", "running"] | None = None
    cancellationRequested: bool


class FileJobResultResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    offset: int | None = None
    hasMore: bool | None = None
    complete: bool | None = None
    previewId: str | None = None
    files: list[dict[str, Any]] | None = None
    groups: list[dict[str, Any]] | None = None
    items: list[dict[str, Any]] | None = None
    saved: bool | None = None
    displayName: str | None = None
    size_bytes: int | None = None


class FileRevealRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    itemId: str = PydanticField(pattern=r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')


class FileRevealResponse(BaseModel):
    path: str


@app.post('/api/file-jobs/{job_id}/reveals', response_model=FileRevealResponse)
def resolve_file_reveal(job_id: str, body: FileRevealRequest, request: Request):
    try:
        file_selection_store.authorize(request.headers.get('X-OfficeKit-Native-Grant', ''))
        return {'path': file_job_store.reveal_path(job_id, body.itemId)}
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


def direct_file_error(error):
    if isinstance(error, PermissionError):
        return HTTPException(status_code=403, detail="Access to this selection or destination was not granted.")
    if isinstance(error, FileExistsError):
        return HTTPException(status_code=409, detail="Files or destination changed. Review the selection again.")
    if isinstance(error, FileNotFoundError):
        return HTTPException(status_code=404, detail="Selection or result is unavailable. Choose it again.")
    if isinstance(error, RuntimeError):
        return HTTPException(status_code=503, detail="The file queue is full. Wait for an operation to finish and try again.")
    return HTTPException(status_code=422, detail="The file operation could not be completed. Check the selection and options.")


@app.post('/api/storage-scans', status_code=201, response_model=StorageStatus)
def create_storage_scan(body: ScanRequest, request: Request):
    try:
        result = storage_cleaner.submit(body, request.headers.get('X-OfficeKit-Native-Grant', ''))
        return JSONResponse(StorageStatus.model_validate(result).model_dump(), status_code=201,
                            headers={'Location': f"/api/storage-scans/{result['id']}"})
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.get('/api/storage-scans/{scan_id}', response_model=StorageStatus)
def get_storage_scan(scan_id: str):
    try:
        return storage_cleaner.status(scan_id)
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.delete('/api/storage-scans/{scan_id}', response_model=StorageCancellation)
def cancel_storage_scan(scan_id: str):
    try:
        return storage_cleaner.cancel(scan_id)
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.post('/api/storage-cleanup-plans', status_code=201, response_model=StoragePlan)
def create_storage_cleanup_plan(body: PlanRequest):
    try:
        result = storage_cleaner.plan(body)
        return JSONResponse(StoragePlan.model_validate(result).model_dump(), status_code=201,
                            headers={'Location': f"/api/storage-cleanup-plans/{result['id']}"})
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.post('/api/storage-cleanup-plans/{plan_id}/execution', response_model=StorageExecution)
def execute_storage_cleanup(plan_id: str, body: EmptyRequest, request: Request):
    try:
        return storage_cleaner.execute(plan_id, request.headers.get('X-OfficeKit-Native-Grant', ''))
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.get('/api/storage-cleanup-plans/{plan_id}/execution', response_model=StorageExecutionProgress)
def get_storage_cleanup_progress(plan_id: str):
    try:
        return storage_cleaner.execution_status(plan_id)
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.delete('/api/storage-cleanup-plans/{plan_id}/execution', response_model=StorageExecutionStop)
def stop_storage_cleanup(plan_id: str):
    try:
        return storage_cleaner.stop_execution(plan_id)
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


def _trash_development_only():
    if RELEASE_PROFILE.name == "private-beta":
        raise HTTPException(status_code=403, detail=TRASH_BETA_MESSAGE)


@app.get("/api/trash-records", response_model=TrashRecordPage)
def list_trash_records(offset: int = Query(default=0, ge=0, le=10_000), limit: int = Query(default=200, ge=1, le=200)):
    _trash_development_only()
    try:
        return trash_restorer.page(offset, limit)
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.post("/api/trash-restore-grants", status_code=201, response_model=TrashRestoreGrant)
def create_trash_restore_grant(body: TrashRestoreGrantRequest, request: Request):
    _trash_development_only()
    try:
        return trash_restorer.mint(body, request.headers.get("X-OfficeKit-Native-Grant", ""))
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from None
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.post("/api/trash-restorations", status_code=201, response_model=TrashRestoration)
def create_trash_restoration(body: TrashRestoreRequest, request: Request):
    _trash_development_only()
    try:
        return trash_restorer.restore(body, request.headers.get("X-OfficeKit-Native-Grant", ""))
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from None
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.delete("/api/trash-records/{record_id}", status_code=204)
def delete_trash_record(record_id: str, request: Request):
    _trash_development_only()
    try:
        trash_restorer.forget(record_id, request.headers.get("X-OfficeKit-Native-Grant", ""))
        return Response(status_code=204)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from None
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.post("/api/file-selections", status_code=201, response_model=FileSelectionResponse)
def create_file_selection(body: SelectionRequest, request: Request):
    try:
        result = file_selection_store.register_native(body.paths, body.access, credential=request.headers.get("X-OfficeKit-Native-Grant", ""))
        response = FileSelectionResponse.model_validate(result)
        return JSONResponse(response.model_dump(), status_code=201, headers={"Location": f"/api/file-selections/{result['id']}"})
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.post("/api/file-output-grants", status_code=201, response_model=FileOutputGrantResponse)
def create_file_output_grant(body: OutputGrantRequest, request: Request):
    try:
        result = file_selection_store.register_output(body.path, body.kind, body.job_kind, body.overwrite, request.headers.get("X-OfficeKit-Native-Grant", ""))
        response = FileOutputGrantResponse.model_validate(result)
        return JSONResponse(response.model_dump(), status_code=201, headers={"Location": f"/api/file-output-grants/{result['id']}"})
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.get("/api/file-selections/{selection_id}", response_model=FileManifestResponse)
def get_file_selection(selection_id: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=200)):
    try:
        return {**file_selection_store.metadata(selection_id), **file_selection_store.manifest(selection_id, offset, limit)}
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.get("/api/file-selections/{selection_id}/image-summary", response_model=ImageSummaryResponse)
def get_file_selection_image_summary(selection_id: str):
    try:
        extensions = SimilarImageEngine.SUPPORTED_EXTENSIONS | SimilarImageEngine.MACOS_HEIC_EXTENSIONS
        return {**file_selection_store.count_by_root(selection_id, extensions), "limit": SimilarImageEngine.MAX_FILES}
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.post("/api/file-selections/{selection_id}/subsets", status_code=201, response_model=FileSelectionResponse)
def create_file_selection_subset(selection_id: str, body: FileSelectionSubsetRequest):
    try:
        response = FileSelectionResponse.model_validate(file_selection_store.derive_files(selection_id, body.fileIds))
        return JSONResponse(response.model_dump(), status_code=201)
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.get("/api/file-selections/{selection_id}/files/{file_id}/content", response_class=Response, responses={
    200: {"description": "Selected file content", "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}},
})
def get_selected_file_content(selection_id: str, file_id: str):
    try:
        item = file_selection_store.find_file(selection_id, file_id)
        if item.signature[2] > MAX_API_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="This file exceeds the 64 MiB tool input limit.")

        file_context = file_selection_store.open_file(item)
        source = file_context.__enter__()

        def chunks():
            try:
                while chunk := source.read(64 * 1024):
                    yield chunk
            finally:
                file_context.__exit__(None, None, None)

        return StreamingResponse(chunks(), media_type="application/octet-stream", headers={
            "Content-Disposition": content_disposition_attachment(item.name),
            "Content-Length": str(item.signature[2]),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        })
    except HTTPException:
        raise
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.get('/api/archive-formats', response_model=ArchiveFormatsResponse)
def get_archive_formats():
    return {'formats': engine_archive_manager.capabilities()}


@app.get('/api/file-selections/{selection_id}/archive-entries', response_model=ArchiveEntriesResponse)
def get_archive_entries(selection_id: str, offset: int = Query(default=0, ge=0, le=10_000), limit: int = Query(default=100, ge=1, le=200)):
    pinned = False
    try:
        file_selection_store.pin(selection_id)
        pinned = True
        selection = file_selection_store.get(selection_id)
        if len(selection.roots) != 1 or selection.roots[0][2]:
            raise ValueError('Choose one archive file to browse.')
        items = list(file_selection_store.iter_files(selection_id))
        if len(items) != 1 or os.path.isdir(items[0].path):
            raise ValueError('Choose one archive file to browse.')
        item = items[0]
        with file_selection_store.open_file(item) as source:
            extension_format = engine_archive_manager.extension_hint(item.name)
            detected_format = 'zip' if zipfile.is_zipfile(source) else ('unknown' if extension_format == 'zip' else extension_format)
            extractable_format = next((fmt['extract'] == 'supported' for fmt in engine_archive_manager.capabilities() if fmt['id'] == detected_format), False)
            if os.name == 'nt':
                archive_path, pass_fds = item.path, ()
            else:
                archive_path, pass_fds = f'/dev/fd/{source.fileno()}', (source.fileno(),)
            entries = engine_archive_manager.list_archive(archive_path, pass_fds=pass_fds)
        page = entries[offset:offset + limit]
        for entry in page:
            entry['id'] = str(uuid.uuid5(uuid.UUID(selection_id), entry['name']))
            entry['nested_archive'] = any(entry['name'].lower().endswith(ext) for _, _, exts, _ in engine_archive_manager.REQUESTED_FORMATS for ext in exts)
            entry['extractable'] = not entry['encrypted'] and extractable_format
        return {'format': detected_format,
                'entries': page, 'offset': offset, 'hasMore': len(entries) > offset + limit, 'total': len(entries)}
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None
    finally:
        if pinned:
            file_selection_store.unpin(selection_id)


@app.delete("/api/file-selections/{selection_id}", status_code=204)
def delete_file_selection(selection_id: str):
    try:
        file_job_store.revoke_selection(selection_id)
        return Response(status_code=204)
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.post("/api/file-jobs", status_code=202, response_model=FileJobResponse)
def create_file_job(body: FileJobRequest):
    try:
        return file_job_store.submit(body)
    except ReleaseScopeError as error:
        raise HTTPException(status_code=403, detail=str(error)) from None
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.get("/api/file-jobs/{job_id}", response_model=FileJobResponse)
def get_file_job(job_id: str):
    try:
        return file_job_store.status(job_id)
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


class EmptyFileCancellationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


@app.post("/api/file-jobs/{job_id}/cancellations", status_code=202, response_model=FileJobCancellationResponse)
def cancel_file_job(job_id: str, body: EmptyFileCancellationRequest):
    try:
        return file_job_store.cancel(job_id)
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


@app.get("/api/file-jobs/{job_id}/results", response_model=FileJobResultResponse)
def get_file_job_result(job_id: str, offset: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=200), format: Literal["json", "page"] = "page"):
    try:
        if format == "json":
            exported = file_job_store.export(job_id)
            validated = FileJobResultResponse.model_validate(json.loads(exported))
            return JSONResponse(validated.model_dump(exclude_none=True), headers={"Content-Disposition": content_disposition_attachment("file-result.json")})
        return file_job_store.result(job_id, offset, limit)
    except (OSError, ValueError, RuntimeError) as error:
        raise direct_file_error(error) from None


class ArchiveExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    archive_name: str = PydanticField(min_length=1, max_length=1024)
    output_name: str = PydanticField(min_length=1, max_length=255)


class WorkspaceSplitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: WorkspaceFileName
    chunk_size_bytes: StrictInt = PydanticField(default=52_428_800, ge=1, le=536_870_912)


class WorkspaceJoinRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    archive_name: WorkspaceFileName
    output_name: str = PydanticField(min_length=1, max_length=255, strict=True)


class WorkspaceSplitPartResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: StrictInt = PydanticField(ge=1, le=999)
    name: str = PydanticField(min_length=1, max_length=32, strict=True)
    size_bytes: StrictInt = PydanticField(ge=0, le=536_870_912)
    sha256: str = PydanticField(pattern=r"^[0-9a-f]{64}$", strict=True)


class WorkspaceSplitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str = PydanticField(pattern=r"^[a-f0-9]{32}$", strict=True)
    original_name: WorkspaceFileName
    total_bytes: StrictInt = PydanticField(ge=0, le=536_870_912)
    chunk_size_bytes: StrictInt = PydanticField(ge=1, le=536_870_912)
    chunk_count: StrictInt = PydanticField(ge=1, le=999)
    sha256: str = PydanticField(pattern=r"^[0-9a-f]{64}$", strict=True)
    parts: List[WorkspaceSplitPartResponse] = PydanticField(min_length=1, max_length=999)
    download_name: str = PydanticField(min_length=1, max_length=300, strict=True)

    @model_validator(mode="after")
    def split_metadata_matches_parts(self):
        if self.chunk_count != len(self.parts):
            raise ValueError("Split result part count does not match its manifest")
        if [part.index for part in self.parts] != list(range(1, self.chunk_count + 1)):
            raise ValueError("Split result part indexes must be contiguous and ordered")
        if sum(part.size_bytes for part in self.parts) != self.total_bytes:
            raise ValueError("Split result byte total does not match its parts")
        return self


class WorkspaceJoinResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_id: str = PydanticField(pattern=r"^[a-f0-9]{32}$", strict=True)
    output_name: str = PydanticField(min_length=1, max_length=255, strict=True)
    total_bytes: StrictInt = PydanticField(ge=0, le=536_870_912)
    part_count: StrictInt = PydanticField(ge=1, le=999)
    sha256: str = PydanticField(pattern=r"^[0-9a-f]{64}$", strict=True)
    download_name: str = PydanticField(min_length=1, max_length=300, strict=True)


class WorkspaceRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filenames: List[WorkspaceFileName] = PydanticField(min_length=1, max_length=1000)
    pattern_type: Literal["sequence", "affix", "casing", "replace"] = "sequence"
    prefix: str = PydanticField(default="", max_length=128)
    suffix: str = PydanticField(default="", max_length=128)
    start_num: int = PydanticField(default=1, ge=0, le=9_999_999_999)
    digits: int = PydanticField(default=3, ge=1, le=12)
    casing: Literal["kebab", "snake", "camel", "title"] = "kebab"
    find_text: str = PydanticField(default="", max_length=256)
    replace_text: str = PydanticField(default="", max_length=256)

    def rename_options(self) -> dict:
        return self.model_dump(exclude={"filenames"})


class DuplicateReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_entries: int = PydanticField(default=10_000, ge=1, le=10_000)


class StorageReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top_n: int = PydanticField(default=10, ge=0, le=1000)


class WorkspaceStorageFileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: WorkspaceFileName
    size_bytes: int = PydanticField(ge=0, le=536_870_912)
    size_mb: float = PydanticField(ge=0, le=512, allow_inf_nan=False)


class WorkspaceStorageFolderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: WorkspaceFileName
    file_count: int = PydanticField(ge=1, le=10_000)
    size_bytes: int = PydanticField(ge=0, le=536_870_912)


class WorkspaceStorageScanErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[WorkspaceFileName]
    message: Literal["A file could not be read during the storage scan."]


class WorkspaceStorageReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_files: int = PydanticField(ge=0, le=10_000)
    total_size_bytes: int = PydanticField(ge=0, le=536_870_912)
    total_size_mb: float = PydanticField(ge=0, le=512, allow_inf_nan=False)
    largest_files: List[WorkspaceStorageFileResponse] = PydanticField(max_length=1000)
    largest_folders: List[WorkspaceStorageFolderResponse] = PydanticField(max_length=1000)
    complete: bool
    skipped_symlinks: int = PydanticField(ge=0, le=10_000)
    errors: List[WorkspaceStorageScanErrorResponse] = PydanticField(max_length=10_000)


class WorkspaceFolderComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left_folder: WorkspaceFileName
    right_folder: WorkspaceFileName


class FolderComparisonFileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: WorkspaceFileName
    status: Literal["identical", "changed", "left-only", "right-only"]
    left_name: Optional[WorkspaceFileName]
    right_name: Optional[WorkspaceFileName]
    left_size_bytes: Optional[int] = PydanticField(ge=0, le=536_870_912)
    right_size_bytes: Optional[int] = PydanticField(ge=0, le=536_870_912)
    left_sha256: Optional[str] = PydanticField(pattern=r"^[0-9a-f]{64}$")
    right_sha256: Optional[str] = PydanticField(pattern=r"^[0-9a-f]{64}$")


class FolderComparisonSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identical: int = PydanticField(ge=0, le=1000)
    changed: int = PydanticField(ge=0, le=1000)
    left_only: int = PydanticField(ge=0, le=1000)
    right_only: int = PydanticField(ge=0, le=1000)


class FolderComparisonDirectoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: WorkspaceFileName
    status: Literal["identical", "changed", "left-only", "right-only"]
    left_empty: Optional[bool]
    right_empty: Optional[bool]


class FolderComparisonDirectorySummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identical: int = PydanticField(ge=0, le=10_000)
    changed: int = PydanticField(ge=0, le=10_000)
    left_only: int = PydanticField(ge=0, le=10_000)
    right_only: int = PydanticField(ge=0, le=10_000)


class WorkspaceFolderComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left_folder: WorkspaceFileName
    right_folder: WorkspaceFileName
    files_compared: int = PydanticField(ge=0, le=1000)
    total_paths: int = PydanticField(ge=0, le=1000)
    summary: FolderComparisonSummaryResponse
    files: List[FolderComparisonFileResponse] = PydanticField(max_length=1000)
    directory_summary: FolderComparisonDirectorySummaryResponse
    directories: List[FolderComparisonDirectoryResponse] = PydanticField(max_length=10_000)
    complete: Literal[True]

    @model_validator(mode="after")
    def counts_match_file_results(self):
        if self.total_paths != len(self.files):
            raise ValueError("Folder-comparison path count does not match the file list")
        counts = {key: 0 for key in ("identical", "changed", "left_only", "right_only")}
        for item in self.files:
            counts[item.status.replace("-only", "_only").replace("-", "_")] += 1
        if counts != self.summary.model_dump():
            raise ValueError("Folder-comparison summary does not match its file results")
        directory_counts = {key: 0 for key in ("identical", "changed", "left_only", "right_only")}
        for item in self.directories:
            directory_counts[item.status.replace("-only", "_only").replace("-", "_")] += 1
            if item.status == "right-only" and (item.left_empty is not None or not isinstance(item.right_empty, bool)):
                raise ValueError("Right-only folders must have a right-side directory state")
            if item.status == "left-only" and (item.right_empty is not None or not isinstance(item.left_empty, bool)):
                raise ValueError("Left-only folders must have a left-side directory state")
            if item.status == "identical" and (item.left_empty is None or item.left_empty != item.right_empty):
                raise ValueError("Identical folders must have matching directory state")
            if item.status == "changed" and (item.left_empty is None or item.right_empty is None or item.left_empty == item.right_empty):
                raise ValueError("Changed folders must differ in empty-directory state")
        if directory_counts != self.directory_summary.model_dump():
            raise ValueError("Folder-comparison directory summary does not match its directory results")
        return self


class SimilarImageReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filenames: List[WorkspaceFileName] = PydanticField(min_length=1, max_length=500)
    threshold: int = PydanticField(default=8, ge=0, le=64, strict=True)


class SimilarImagePairResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left: WorkspaceFileName
    right: WorkspaceFileName
    distance: int = PydanticField(ge=0, le=64)


class SimilarImageGroupResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    files: List[WorkspaceFileName] = PydanticField(min_length=2, max_length=500)


class SimilarImageErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: WorkspaceFileName
    message: str = PydanticField(max_length=160)


class SimilarImageReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairs: List[SimilarImagePairResponse]
    groups: List[SimilarImageGroupResponse]
    scanned_images: int = PydanticField(ge=0, le=10_000)
    skipped_files: List[WorkspaceFileName]
    errors: List[SimilarImageErrorResponse]
    complete: bool
    method: Literal["dct-perceptual-hash"]
    frames_per_file: Literal[1]


class WorkspaceHashRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filenames: List[WorkspaceFileName] = PydanticField(min_length=1, max_length=1000)
    algorithm: Literal["sha256", "sha512"] = "sha256"


class FileTypeReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filenames: List[WorkspaceFileName] = PydanticField(min_length=1, max_length=1000)


class FileTypeRecordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: WorkspaceFileName
    size_bytes: int = PydanticField(ge=0, le=536_870_912)
    extension: str = PydanticField(max_length=1024, strict=True)
    detected_type: str = PydanticField(min_length=1, max_length=64, strict=True)
    mime_type: str = PydanticField(min_length=1, max_length=128, strict=True)
    extension_matches: Optional[bool]
    method: Literal["magic-bytes+utf8"]


class FileTypeReportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total_files: int = PydanticField(ge=1, le=1000)
    complete: Literal[True]
    files: List[FileTypeRecordResponse] = PydanticField(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def counts_match_records(self):
        if self.total_files != len(self.files):
            raise ValueError("File-type result count does not match its file list")
        return self


class WorkspaceFileHashResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: WorkspaceFileName
    size_bytes: int = PydanticField(ge=0, le=536_870_912)
    digest: str = PydanticField(pattern=r"^(?:[0-9a-f]{64}|[0-9a-f]{128})$")


class WorkspaceHashResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    algorithm: Literal["sha256", "sha512"]
    total_files: int = PydanticField(ge=1, le=1000)
    total_bytes: int = PydanticField(ge=0, le=536_870_912)
    complete: Literal[True]
    files: List[WorkspaceFileHashResponse] = PydanticField(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def digest_lengths_match_algorithm(self):
        expected_length = 64 if self.algorithm == "sha256" else 128
        if self.total_files != len(self.files):
            raise ValueError("Hash result count does not match its file list")
        if any(len(file.digest) != expected_length for file in self.files):
            raise ValueError("Hash digest length does not match the selected algorithm")
        if sum(file.size_bytes for file in self.files) != self.total_bytes:
            raise ValueError("Hash byte total does not match its file list")
        return self


@app.post("/api/workspaces", status_code=201)
async def api_create_workspace(
    files: List[UploadFile] = File(default=[]),
    directories: List[str] = Form(default=[]),
):
    workspace_id = workspace_store.create_workspace()
    try:
        if not files and not directories:
            raise HTTPException(status_code=422, detail="Select at least one file or folder.")
        workspace_store.add_files(
            workspace_id,
            ((file.filename or "", file.file) for file in files),
            directories=directories,
        )
        return workspace_store.get_workspace(workspace_id)
    except WorkspaceLimitError as error:
        workspace_store.clear_workspace(workspace_id)
        raise HTTPException(status_code=413, detail=str(error)) from error
    except ValueError as error:
        workspace_store.clear_workspace(workspace_id)
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception:
        workspace_store.clear_workspace(workspace_id)
        raise
    finally:
        for file in files:
            await file.close()


@app.get("/api/workspaces/{workspace_id}")
def api_get_workspace(workspace_id: str):
    try:
        return workspace_store.get_workspace(workspace_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Workspace not found") from error


@app.post("/api/workspaces/{workspace_id}/extractions")
def api_create_workspace_extraction(workspace_id: str, req: ArchiveExtractRequest):
    try:
        return workspace_store.extract_archive(workspace_id, req.archive_name, req.output_name)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WorkspaceLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post(
    "/api/workspaces/{workspace_id}/splits",
    status_code=201,
    response_model=WorkspaceSplitResponse,
)
def api_create_workspace_split(
    workspace_id: str, req: WorkspaceSplitRequest
) -> WorkspaceSplitResponse:
    try:
        return WorkspaceSplitResponse.model_validate(
            workspace_store.create_split_artifact(
                workspace_id, req.filename, chunk_size=req.chunk_size_bytes
            )
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Workspace or selected file not found") from error
    except WorkspaceLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post(
    "/api/workspaces/{workspace_id}/joins",
    status_code=201,
    response_model=WorkspaceJoinResponse,
)
def api_create_workspace_join(
    workspace_id: str, req: WorkspaceJoinRequest
) -> WorkspaceJoinResponse:
    try:
        return WorkspaceJoinResponse.model_validate(
            workspace_store.create_join_artifact(
                workspace_id, req.archive_name, req.output_name
            )
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Workspace or selected split archive not found") from error
    except WorkspaceLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/workspaces/{workspace_id}/rename-previews")
def api_preview_workspace_rename(workspace_id: str, req: WorkspaceRenameRequest):
    try:
        return {"files": workspace_store.preview_rename(workspace_id, req.filenames, **req.rename_options())}
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WorkspaceLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/workspaces/{workspace_id}/renamed-artifacts", status_code=201)
def api_create_workspace_rename_artifact(workspace_id: str, req: WorkspaceRenameRequest):
    try:
        return workspace_store.create_renamed_artifact(
            workspace_id, req.filenames, **req.rename_options()
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except WorkspaceLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/workspaces/{workspace_id}/duplicate-reports")
def api_workspace_duplicate_report(workspace_id: str, req: DuplicateReportRequest):
    try:
        return workspace_store.find_duplicate_report(workspace_id, max_entries=req.max_entries)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Workspace not found") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post(
    "/api/workspaces/{workspace_id}/storage-reports",
    response_model=WorkspaceStorageReportResponse,
)
def api_workspace_storage_report(workspace_id: str, req: StorageReportRequest):
    try:
        return WorkspaceStorageReportResponse.model_validate(
            workspace_store.storage_report(workspace_id, top_n=req.top_n)
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Workspace not found") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post(
    "/api/workspaces/{workspace_id}/folder-comparisons",
    response_model=WorkspaceFolderComparisonResponse,
)
def api_workspace_folder_comparison(
    workspace_id: str,
    req: WorkspaceFolderComparisonRequest,
    format: Literal["json", "csv"] = "json",
) -> WorkspaceFolderComparisonResponse | Response:
    try:
        report = WorkspaceFolderComparisonResponse.model_validate(
            workspace_store.compare_folders(workspace_id, req.left_folder, req.right_folder)
        )
        if format == "csv":
            content = render_folder_comparison_csv(report.model_dump())
            return Response(
                content=content,
                media_type="text/csv",
                headers={"Content-Disposition": content_disposition_attachment("folder-comparison.csv")},
            )
        return report
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Workspace or selected folder not found") from error
    except WorkspaceLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except WorkspaceExportLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post(
    "/api/workspaces/{workspace_id}/similar-image-reports",
    response_model=SimilarImageReportResponse,
)
def api_workspace_similar_image_report(workspace_id: str, req: SimilarImageReportRequest) -> SimilarImageReportResponse:
    try:
        return SimilarImageReportResponse.model_validate(
            workspace_store.similar_image_report(workspace_id, req.filenames, threshold=req.threshold)
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SimilarImageDependencyError as error:
        raise HTTPException(status_code=503, detail="Image similarity scanning is unavailable.") from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/workspaces/{workspace_id}/file-type-reports", response_model=FileTypeReportResponse)
def api_workspace_file_type_report(
    workspace_id: str, req: FileTypeReportRequest
) -> FileTypeReportResponse:
    try:
        return FileTypeReportResponse.model_validate(
            workspace_store.file_type_report(workspace_id, req.filenames)
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Workspace or selected file not found") from error
    except WorkspaceLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/api/workspaces/{workspace_id}/hash-reports", response_model=WorkspaceHashResponse)
def api_workspace_hash_report(workspace_id: str, req: WorkspaceHashRequest) -> WorkspaceHashResponse:
    try:
        return WorkspaceHashResponse.model_validate(
            workspace_store.hash_files(workspace_id, req.filenames, algorithm=req.algorithm)
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Workspace or selected file not found") from error
    except WorkspaceLimitError as error:
        raise HTTPException(status_code=413, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/workspaces/{workspace_id}/artifacts/{artifact_id}")
def api_download_workspace_artifact(workspace_id: str, artifact_id: str):
    try:
        artifact_path = workspace_store.artifact_path(workspace_id, artifact_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Artifact not found") from error
    return FileResponse(artifact_path, media_type="application/zip", filename="OfficeKit-output.zip")


@app.delete("/api/workspaces/{workspace_id}", status_code=204)
def api_clear_workspace(workspace_id: str):
    try:
        workspace_store.clear_workspace(workspace_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail="Workspace not found") from error
    return Response(status_code=204)

# ==========================================
# 7. Communications, Support, Updates & Search
# ==========================================
from officekit.engines.engine_comms import SupportEngine, SupportStoreError, CommsEngine

@app.get("/api/tools/search")
def api_search_tools(q: str = Query(default="", max_length=256)):
    tools = CommsEngine.search_tools(q)
    if RELEASE_PROFILE.name == "private-beta":
        tools = [tool for tool in tools if tool["id"] in RELEASE_PROFILE.tool_ids]
    return {"tools": tools}

@app.get("/api/system/check-update")
def api_check_update():
    return CommsEngine.check_for_updates()

@app.get("/api/communications/banner")
def api_get_banner():
    return CommsEngine.get_announcement_banner()

class TicketSystemInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    os: Optional[str] = PydanticField(default=None, max_length=64, strict=True)
    app_version: Optional[str] = PydanticField(default=None, max_length=32, strict=True)
    platform: Optional[str] = PydanticField(default=None, max_length=128, strict=True)
    user_agent: Optional[str] = PydanticField(default=None, alias="userAgent", max_length=512, strict=True)


class TicketCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    user_email: Optional[StrictStr] = PydanticField(default=None, min_length=3, max_length=254)
    ticket_type: Literal["bug", "support", "feature", "testimonial"]
    title: str = PydanticField(min_length=1, max_length=160, strict=True)
    description: str = PydanticField(min_length=1, max_length=20_000, strict=True)
    system_info: Optional[TicketSystemInfo] = None
    display_name: Optional[StrictStr] = PydanticField(default=None, max_length=80)
    publication_consent: StrictBool = False

    @field_validator("user_email")
    @classmethod
    def validate_ticket_email(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("A valid email address is required")
        return value

    @model_validator(mode="after")
    def validate_publication_consent(self):
        if self.publication_consent and self.ticket_type != "testimonial":
            raise ValueError("Publication consent is only available for testimonials")
        if self.publication_consent and not self.display_name:
            raise ValueError("A display name is required when publication is allowed")
        return self

    @field_validator("title", "description")
    @classmethod
    def validate_nonblank_ticket_text(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Ticket text must not be blank or contain NUL characters")
        return value


class TicketTimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["received", "saved_locally"]
    message: str = PydanticField(max_length=160, strict=True)
    timestamp: float = PydanticField(ge=0, allow_inf_nan=False)


class TicketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticket_id: str = PydanticField(min_length=1, max_length=64, strict=True)
    user_email: Optional[StrictStr] = PydanticField(default=None, min_length=3, max_length=254)
    ticket_type: Literal["bug", "support", "feature", "testimonial"]
    title: str = PydanticField(min_length=1, max_length=160, strict=True)
    description: str = PydanticField(min_length=1, max_length=20_000, strict=True)
    system_info: Dict[str, str]
    display_name: Optional[StrictStr] = PydanticField(default=None, max_length=80)
    publication_consent: StrictBool = False
    status: Literal["received", "saved_locally"]
    created_at: float = PydanticField(ge=0, allow_inf_nan=False)
    timeline: List[TicketTimelineEntry] = PydanticField(min_length=1, max_length=1)


class TicketListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tickets: List[TicketResponse] = PydanticField(max_length=100)


def _support_storage_unavailable(error: Exception) -> HTTPException:
    logger.exception("Local OfficeKit support storage operation failed", exc_info=error)
    return HTTPException(status_code=503, detail="Ticket was not saved because local support storage is unavailable.")


@app.post("/api/support/tickets", response_model=TicketResponse)
def api_create_ticket(req: TicketCreateRequest):
    try:
        return SupportEngine.create_ticket(
            user_email=req.user_email,
            ticket_type=req.ticket_type,
            title=req.title,
            description=req.description,
            system_info=req.system_info.model_dump(exclude_none=True, by_alias=True) if req.system_info else None,
            display_name=req.display_name,
            publication_consent=req.publication_consent,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (SupportStoreError, OSError) as error:
        raise _support_storage_unavailable(error) from error

@app.get("/api/support/tickets/{ticket_id}", response_model=TicketResponse)
def api_get_ticket(ticket_id: str):
    try:
        t = SupportEngine.get_ticket(ticket_id)
    except (SupportStoreError, OSError) as error:
        raise _support_storage_unavailable(error) from error
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return t

@app.get("/api/support/tickets", response_model=TicketListResponse)
def api_list_tickets(
    user_email: Optional[str] = Query(default=None, max_length=254),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10_000),
):
    if user_email is not None and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", user_email):
        raise HTTPException(status_code=422, detail="A valid email address is required")
    try:
        return {"tickets": SupportEngine.list_user_tickets(user_email, limit=limit, offset=offset)}
    except (SupportStoreError, OSError) as error:
        raise _support_storage_unavailable(error) from error

# ==========================================
# 7b. Unified Clipboard Manager & Snippets Studio
# ==========================================
from officekit.engines.engine_clipboard import (
    clipboard_store,
    apply_transformation,
    parse_template_variables,
    render_template,
    TriggerError,
)

class ClipCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text_content: Optional[str] = PydanticField(default="", max_length=10_000_000)
    content_type: Optional[str] = PydanticField(default=None, max_length=32)
    rich_content: Optional[str] = PydanticField(default=None, max_length=10_000_000)
    image_data: Optional[str] = PydanticField(default=None, max_length=6_000_000)
    category: Optional[str] = PydanticField(default=None, max_length=64)
    source_app: Optional[str] = PydanticField(default=None, max_length=256)
    source_bundle_id: Optional[str] = PydanticField(default=None, max_length=255)
    metadata_types: Optional[List[str]] = PydanticField(default=None, max_length=64)

class GlobalClipboardSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capture_enabled: Optional[bool] = None
    expansion_enabled: Optional[bool] = None
    skip_bundle_ids: Optional[List[str]] = PydanticField(default=None, max_length=64)
    retention_clips: Optional[int] = PydanticField(default=None, ge=50, le=5000)
    retention_days: Optional[int] = PydanticField(default=None, ge=1, le=365)
    # Checked against the allowed choices by the clipboard store, which answers 422 for other values.
    capture_pause: Optional[str] = PydanticField(default=None, max_length=16)
    panel_default_filter: Optional[str] = PydanticField(default=None, max_length=16)

class ClipPinRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    pinned: Optional[bool] = None

class ClipboardClearRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    keep_pinned: bool = True

class ClipboardTransformRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str
    transform: str

class FolderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = PydanticField(min_length=1, max_length=100)
    icon: Optional[str] = "fa-folder"

class SnippetSaveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = PydanticField(min_length=1, max_length=200)
    content: str
    folder_id: Optional[str] = "default"
    trigger_key: Optional[str] = None
    shortcut_number: Optional[int] = None
    snippet_id: Optional[str] = None

class SnippetRenderRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    template: str
    values: Optional[Dict[str, str]] = None
    current_clipboard: Optional[str] = ""

class SnippetImportRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: Dict[str, Any]
    merge: bool = True

@app.get("/api/clipboard/history")
def api_clipboard_history(
    search: Optional[str] = Query(default=None, max_length=256),
    category: Optional[str] = Query(default=None, max_length=64),
    pinned_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=10_000),
    types: Optional[str] = Query(default=None, max_length=64),
    include_images: bool = Query(default=True),
):
    type_filters = [item.strip() for item in types.split(",") if item.strip()] if types else None
    return clipboard_store.list_clips(
        search=search, category=category, pinned_only=pinned_only, limit=limit, offset=offset,
        types=type_filters, include_image_data=include_images,
    )

@app.get("/api/clipboard/clips/{clip_id}")
def api_clipboard_get_clip(clip_id: str):
    clip = clipboard_store.get_clip(clip_id)
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return {"clip": clip}

@app.get("/api/clipboard/global-settings")
def api_clipboard_get_global_settings():
    return {"settings": clipboard_store.get_settings()}

@app.post("/api/clipboard/global-settings")
def api_clipboard_put_global_settings(req: GlobalClipboardSettingsRequest):
    try:
        settings = clipboard_store.update_settings(req.model_dump(exclude_none=True))
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    return {"settings": settings}

@app.post("/api/clipboard/clips")
def api_clipboard_save_clip(req: ClipCreateRequest):
    clip = clipboard_store.add_clip(
        text_content=req.text_content,
        content_type=req.content_type,
        rich_content=req.rich_content,
        image_data=req.image_data,
        category=req.category,
        source_app=req.source_app,
        metadata_types=req.metadata_types,
        source_bundle_id=req.source_bundle_id,
    )
    if clip is None:
        return {"status": "ignored", "reason": "concealed_or_empty", "clip": None}
    return {"status": "saved", "clip": clip}

@app.post("/api/clipboard/clips/{clip_id}/pin")
def api_clipboard_pin_clip(clip_id: str, req: ClipPinRequest):
    updated = clipboard_store.toggle_pin(clip_id, pinned=req.pinned)
    if not updated:
        raise HTTPException(status_code=404, detail="Clip not found")
    return {"clip": updated}

@app.post("/api/clipboard/clips/{clip_id}/use")
def api_clipboard_use_clip(clip_id: str):
    updated = clipboard_store.touch_clip(clip_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Clip not found")
    return {"clip": updated}

@app.delete("/api/clipboard/clips/{clip_id}")
def api_clipboard_delete_clip(clip_id: str):
    success = clipboard_store.delete_clip(clip_id)
    if not success:
        raise HTTPException(status_code=404, detail="Clip not found")
    return {"status": "deleted", "id": clip_id}

@app.post("/api/clipboard/clear")
def api_clipboard_clear_history(req: ClipboardClearRequest):
    deleted_count = clipboard_store.clear_history(keep_pinned=req.keep_pinned)
    return {"status": "cleared", "deleted_count": deleted_count}

@app.post("/api/clipboard/transform")
def api_clipboard_transform(req: ClipboardTransformRequest):
    try:
        return apply_transformation(req.text, req.transform)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

@app.get("/api/clipboard/folders")
def api_clipboard_list_folders():
    return {"folders": clipboard_store.list_folders()}

@app.post("/api/clipboard/folders")
def api_clipboard_create_folder(req: FolderCreateRequest):
    return {"folder": clipboard_store.create_folder(req.name, req.icon or "fa-folder")}

@app.delete("/api/clipboard/folders/{folder_id}")
def api_clipboard_delete_folder(folder_id: str):
    if folder_id == "default":
        raise HTTPException(status_code=400, detail="Cannot delete default folder")
    success = clipboard_store.delete_folder(folder_id)
    if not success:
        raise HTTPException(status_code=404, detail="Folder not found")
    return {"status": "deleted", "id": folder_id}

@app.get("/api/clipboard/snippets")
def api_clipboard_list_snippets(
    folder_id: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=256),
):
    snippets = clipboard_store.list_snippets(folder_id=folder_id, search=search)
    return {"snippets": snippets}

@app.post("/api/clipboard/snippets")
def api_clipboard_save_snippet(req: SnippetSaveRequest):
    try:
        snippet = clipboard_store.save_snippet(
            title=req.title,
            content=req.content,
            folder_id=req.folder_id or "default",
            trigger_key=req.trigger_key,
            shortcut_number=req.shortcut_number,
            snippet_id=req.snippet_id,
        )
    except TriggerError as error:
        status = 409 if error.code in ("duplicate", "prefix") else 422
        raise HTTPException(status_code=status, detail=str(error))
    return {"snippet": snippet}

@app.delete("/api/clipboard/snippets/{snippet_id}")
def api_clipboard_delete_snippet(snippet_id: str):
    success = clipboard_store.delete_snippet(snippet_id)
    if not success:
        raise HTTPException(status_code=404, detail="Snippet not found")
    return {"status": "deleted", "id": snippet_id}

@app.post("/api/clipboard/snippets/render")
def api_clipboard_render_snippet(req: SnippetRenderRequest):
    variables = parse_template_variables(req.template)
    rendered = render_template(
        req.template,
        values=req.values,
        current_clipboard=req.current_clipboard or "",
    )
    return {
        "template": req.template,
        "variables": variables,
        "rendered": rendered,
    }

@app.get("/api/clipboard/snippets/export")
def api_clipboard_export_snippets():
    return clipboard_store.export_snippets()

@app.post("/api/clipboard/snippets/import")
def api_clipboard_import_snippets(req: SnippetImportRequest):
    try:
        res = clipboard_store.import_snippets(req.data, merge=req.merge)
        return {"status": "imported", **res}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

# ==========================================
# 8. Interactive Frontend Web Dashboard
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    dashboard_path = Path(__file__).resolve().with_name("index.html")
    with dashboard_path.open("r", encoding="utf-8") as f:
        return f.read()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="127.0.0.1",
        port=8000,
        reload=False,
        log_level="warning",
        access_log=False,
    )
