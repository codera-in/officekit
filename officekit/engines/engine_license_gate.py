"""Sidecar licence gate: in-memory entitlement, route classification and the native grant check.

The Rust shell verifies the signed Keychain receipt and pushes only a short summary here. The
summary lives in memory with a monotonic-clock lifetime, so stopping the shell closes the gate.
There is deliberately no off switch: tests install an entitlement through ``GATE_STATE``.
"""

import hmac
import math
import re
import sys
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field as PydanticField, StrictInt, StrictStr, field_validator

NATIVE_GRANT_ENVIRONMENT_KEY = "OFFICEKIT_NATIVE_GRANT_TOKEN"
NATIVE_GRANT_HEADER = "X-OfficeKit-Native-Grant"
MIN_GRANT_TOKEN_LENGTH = 32
MAX_GRANT_TOKEN_LENGTH = 128

EDITION_PAID = "paid"
ACTIVATION_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{22}")
FEATURE_PATTERN = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
MAX_FEATURES = 128
MIN_VALID_FOR_SECONDS = 60
MAX_VALID_FOR_SECONDS = 3600
MAX_ENTITLEMENT_BODY_BYTES = 16 * 1024

# Reachable without an entitlement: liveness, build info, licence state and handoff, support and
# announcements. Update checks are NOT exempt (updates are disabled while locked), and neither is
# anything Settings uses. Anything not listed here, in FREE_ROUTES or in ROUTE_FEATURES is gated.
GATE_EXEMPT_ROUTES = frozenset({
    ("GET", "/api/health"),
    ("GET", "/api/release"),
    ("GET", "/api/license/status"),
    ("PUT", "/api/license/entitlement"),
    ("DELETE", "/api/license/entitlement"),
    ("POST", "/api/license/activate"),
    ("POST", "/api/support/tickets"),
    ("GET", "/api/support/tickets"),
    ("GET", "/api/support/tickets/{ticket_id}"),
    ("GET", "/api/communications/banner"),
})

# Product-free routes: the whole Calculators, Converters and Developer & Data catalog categories
# work without a licence, even with no entitlement, an expired one or a revoked one. The middleware
# treats these like exempt routes, but they are a separate state so that "free by product decision"
# is never confused with "needed to operate or activate the app". A route shared with a paid tool
# is NOT listed here (it stays in ROUTE_FEATURES).
FREE_ROUTES = frozenset({
    # Catalog listing: tool names and categories only, no file content. The gallery, search and
    # recents load every tool from it, so a locked app needs it to render the free tools and the
    # Locked chips on the rest.
    ("GET", "/api/tools/search"),
    # Calculators: Loan & Mortgage EMI, Compound Interest, VAT & Sales Tax, Freelance Rate,
    # Margin & Markup, Break-even, Simple Interest, Depreciation, Everyday Percentages
    # (percent-of, percentage-change, discount), Scientific Calculator (math/eval).
    ("POST", "/api/calculator/break-even"),
    ("POST", "/api/calculator/compound-interest"),
    ("POST", "/api/calculator/depreciation"),
    ("POST", "/api/calculator/discount"),
    ("POST", "/api/calculator/freelance-rate"),
    ("POST", "/api/calculator/loan-emi"),
    ("POST", "/api/calculator/margin-markup"),
    ("POST", "/api/calculator/percent-of"),
    ("POST", "/api/calculator/percentage-change"),
    ("POST", "/api/calculator/simple-interest"),
    ("POST", "/api/calculator/vat-sales-tax"),
    ("POST", "/api/math/eval"),
    # Calculators added with the calculator slice: Weighted Average, Fractions & Ratios, ROI, CAGR,
    # Date Difference, Age, Business Days, Work Hours, Time Zone Converter, Quadratic Solver,
    # GCD & LCM, Descriptive Statistics, Geometry.
    ("POST", "/api/calculator/averages"),
    ("POST", "/api/calculator/fractions"),
    ("POST", "/api/calculator/roi"),
    ("POST", "/api/calculator/cagr"),
    ("POST", "/api/calculator/date-differences"),
    ("POST", "/api/calculator/ages"),
    ("POST", "/api/calculator/business-days"),
    ("POST", "/api/calculator/work-hours"),
    ("GET", "/api/calculator/time-zones"),
    ("POST", "/api/calculator/time-zone-conversions"),
    ("POST", "/api/calculator/quadratics"),
    ("POST", "/api/calculator/gcd-lcm"),
    ("POST", "/api/calculator/statistics"),
    ("POST", "/api/calculator/geometry"),
    # Developer & Data tools added with the developer slice: JSON Compare, Text Diff, Text Case,
    # Text Metrics, Timestamp Converter, UUID Generator, QR Generator.
    ("POST", "/api/developer/json-diffs"),
    ("POST", "/api/developer/text-diffs"),
    ("POST", "/api/developer/text-case-conversions"),
    ("POST", "/api/developer/text-analyses"),
    ("POST", "/api/developer/timestamp-conversions"),
    ("GET", "/api/developer/time-zones"),
    ("POST", "/api/developer/uuids"),
    ("POST", "/api/developer/qr-codes"),
    # Converters: Unit Converter (units catalog and convert), Color Converter.
    ("GET", "/api/units/catalog"),
    ("POST", "/api/units/convert"),
    ("POST", "/api/colors/convert"),
    # Developer & Data: JSON & YAML Formatter, URL Encoder & Decoder and Offline JWT Inspector
    # (all via devtools/process); Spreadsheet & Data Converter (the data half of the converter tab).
    ("POST", "/api/devtools/process"),
    ("POST", "/api/convert/data"),
    ("POST", "/api/convert/data/sheets"),
    # Clipboard & Snippets Studio is catalogued under Developer & Data but is a paid tool (owner
    # decision 2026-10-22): its /api/clipboard routes are in ROUTE_FEATURES, not here.
})

# Every other route needs a live entitlement. The value is the feature slug the entitlement must
# carry, or None when any paid entitlement is enough. No separable add-on features are defined by
# the product yet, so all routes are None; bind a route by replacing its None with a slug.
ROUTE_FEATURES: dict[tuple[str, str], str | None] = {
    ("GET", "/api/archive-formats"): None,
    ("POST", "/api/clipboard/clear"): None,
    ("POST", "/api/clipboard/clips"): None,
    ("DELETE", "/api/clipboard/clips/{clip_id}"): None,
    ("GET", "/api/clipboard/clips/{clip_id}"): None,
    ("POST", "/api/clipboard/clips/{clip_id}/pin"): None,
    ("GET", "/api/clipboard/folders"): None,
    ("POST", "/api/clipboard/folders"): None,
    ("DELETE", "/api/clipboard/folders/{folder_id}"): None,
    ("GET", "/api/clipboard/global-settings"): None,
    ("POST", "/api/clipboard/global-settings"): None,
    ("GET", "/api/clipboard/history"): None,
    ("GET", "/api/clipboard/snippets"): None,
    ("POST", "/api/clipboard/snippets"): None,
    ("GET", "/api/clipboard/snippets/export"): None,
    ("POST", "/api/clipboard/snippets/import"): None,
    ("POST", "/api/clipboard/snippets/render"): None,
    ("DELETE", "/api/clipboard/snippets/{snippet_id}"): None,
    ("POST", "/api/clipboard/transform"): None,
    ("POST", "/api/convert/image"): None,
    ("POST", "/api/crypto/hashes"): None,
    ("POST", "/api/crypto/passphrase"): None,
    ("POST", "/api/crypto/password"): None,
    ("POST", "/api/dictate/cleanup"): None,
    ("POST", "/api/dictate/format-notes"): None,
    ("POST", "/api/export/csv"): None,
    ("POST", "/api/export/excel"): None,
    ("POST", "/api/export/result"): None,
    ("POST", "/api/export/xls"): None,
    ("POST", "/api/extract/statement"): None,
    ("POST", "/api/file-jobs"): None,
    ("GET", "/api/file-jobs/{job_id}"): None,
    ("POST", "/api/file-jobs/{job_id}/cancellations"): None,
    ("GET", "/api/file-jobs/{job_id}/results"): None,
    ("POST", "/api/file-jobs/{job_id}/reveals"): None,
    ("POST", "/api/file-output-grants"): None,
    ("POST", "/api/file-selections"): None,
    ("DELETE", "/api/file-selections/{selection_id}"): None,
    ("GET", "/api/file-selections/{selection_id}"): None,
    ("GET", "/api/file-selections/{selection_id}/archive-entries"): None,
    ("POST", "/api/files/rename-plan"): None,
    ("GET", "/api/trash-records"): None,
    ("POST", "/api/trash-restore-grants"): None,
    ("POST", "/api/trash-restorations"): None,
    ("DELETE", "/api/trash-records/{record_id}"): None,
    ("POST", "/api/file-selections/{selection_id}/subsets"): None,
    ("GET", "/api/file-selections/{selection_id}/files/{file_id}/content"): None,
    ("POST", "/api/image-renditions"): None,
    ("POST", "/api/image-rendition-batches"): None,
    ("POST", "/api/image-metadata-reports"): None,
    ("POST", "/api/image-palettes"): None,
    ("POST", "/api/data-uris"): None,
    ("POST", "/api/data-uri-images"): None,
    ("POST", "/api/icon-packs"): None,
    ("POST", "/api/image-collages"): None,
    ("POST", "/api/contact-sheets"): None,
    ("POST", "/api/image-comparisons"): None,
    ("POST", "/api/pdf/page-rotations"): None,
    ("POST", "/api/pdf/image-pdfs"): None,
    ("POST", "/api/pdf/inspections"): None,
    ("POST", "/api/pdf/watermarks"): None,
    ("POST", "/api/pdf/watermarks/previews"): None,
    ("POST", "/api/pdf/page-numbers"): None,
    ("POST", "/api/pdf/page-numbers/previews"): None,
    ("POST", "/api/pdf/page-sizes"): None,
    ("POST", "/api/pdf/grayscale-conversions"): None,
    ("POST", "/api/pdf/flattenings"): None,
    ("POST", "/api/image/metadata"): None,
    ("POST", "/api/image/resize"): None,
    ("POST", "/api/images/resize"): None,
    ("GET", "/api/media-artifacts/{artifact_id}"): None,
    ("GET", "/api/media-capabilities"): None,
    ("GET", "/api/media-folder-watches"): None,
    ("POST", "/api/media-folder-watches"): None,
    ("DELETE", "/api/media-folder-watches/{watch_id}"): None,
    ("PATCH", "/api/media-folder-watches/{watch_id}"): None,
    ("POST", "/api/media-image-stagings"): None,
    ("DELETE", "/api/media-image-stagings/{staging_id}"): None,
    ("POST", "/api/media-import-previews"): None,
    ("POST", "/api/media-jobs"): None,
    ("GET", "/api/media-jobs/{job_id}"): None,
    ("POST", "/api/media-jobs/{job_id}/cancellations"): None,
    ("DELETE", "/api/media-operation-defaults"): None,
    ("GET", "/api/media-operation-defaults"): None,
    ("PUT", "/api/media-operation-defaults/{operation_id}"): None,
    ("GET", "/api/media-pipeline-triggers"): None,
    ("DELETE", "/api/media-pipeline-triggers/{trigger}"): None,
    ("PUT", "/api/media-pipeline-triggers/{trigger}"): None,
    ("GET", "/api/media-pipelines"): None,
    ("POST", "/api/media-pipelines"): None,
    ("DELETE", "/api/media-pipelines/{pipeline_id}"): None,
    ("PATCH", "/api/media-pipelines/{pipeline_id}"): None,
    ("PUT", "/api/media-pipelines/{pipeline_id}"): None,
    ("GET", "/api/media-preset-zones"): None,
    ("POST", "/api/media-preset-zones"): None,
    ("DELETE", "/api/media-preset-zones/{zone_id}"): None,
    ("PATCH", "/api/media-preset-zones/{zone_id}"): None,
    ("PUT", "/api/media-preset-zones/{zone_id}/name"): None,
    ("PUT", "/api/media-preset-zones/{zone_id}/pipeline"): None,
    ("GET", "/api/media-previews/{selection_id}/{file_id}"): None,
    ("POST", "/api/media-watermark-stagings"): None,
    ("DELETE", "/api/media-watermark-stagings/{staging_id}"): None,
    ("POST", "/api/network/dns"): None,
    ("POST", "/api/network/interfaces"): None,
    ("POST", "/api/network/ping"): None,
    ("POST", "/api/pdf-documents"): None,
    ("DELETE", "/api/pdf-documents/{document_id}"): None,
    ("GET", "/api/pdf-documents/{document_id}"): None,
    ("POST", "/api/pdf-documents/{document_id}/exports"): None,
    ("GET", "/api/pdf-documents/{document_id}/objects"): None,
    ("POST", "/api/pdf-documents/{document_id}/ocr-reviews"): None,
    ("GET", "/api/pdf-documents/{document_id}/ocr-reviews/{review_id}"): None,
    ("GET", "/api/pdf-documents/{document_id}/previews/{page}"): None,
    ("POST", "/api/pdf-documents/{document_id}/revisions"): None,
    ("GET", "/api/pdf-documents/{document_id}/revisions/{revision}"): None,
    ("POST", "/api/pdf-documents/{document_id}/signatures"): None,
    ("GET", "/api/pdf-documents/{document_id}/signatures/{job_id}"): None,
    ("POST", "/api/pdf-documents/{document_id}/verifications"): None,
    ("POST", "/api/pdf-signing-providers"): None,
    ("POST", "/api/pdf-signing-providers/native"): None,
    ("GET", "/api/pdf-workspace-artifacts/{artifact_id}"): None,
    ("GET", "/api/pdf-workspace-jobs/{job_id}"): None,
    ("POST", "/api/pdf-workspace-jobs/{job_id}/cancellations"): None,
    ("POST", "/api/pdf/compress"): None,
    ("POST", "/api/pdf/images"): None,
    ("POST", "/api/pdf/merge"): None,
    ("POST", "/api/pdf/metadata"): None,
    ("POST", "/api/pdf/page-counts"): None,
    ("POST", "/api/pdf/page-thumbnails"): None,
    ("POST", "/api/pdf/pages/delete"): None,
    ("POST", "/api/pdf/pages/reorder"): None,
    ("POST", "/api/pdf/protect"): None,
    ("POST", "/api/pdf/split"): None,
    ("POST", "/api/pdf/split/groups"): None,
    ("POST", "/api/pdf/tables"): None,
    ("POST", "/api/pdf/tables/export"): None,
    ("POST", "/api/pdf/text"): None,
    ("POST", "/api/pdf/unlock"): None,
    ("POST", "/api/privacy/pii/redact"): None,
    ("POST", "/api/privacy/pii/scan"): None,
    ("POST", "/api/screenshot/edit"): None,
    ("POST", "/api/storage-cleanup-plans"): None,
    ("POST", "/api/storage-cleanup-plans/{plan_id}/execution"): None,
    ("POST", "/api/storage-scans"): None,
    ("DELETE", "/api/storage-scans/{scan_id}"): None,
    ("GET", "/api/storage-scans/{scan_id}"): None,
    ("GET", "/api/system/check-update"): None,
    ("GET", "/api/system/info"): None,
    ("GET", "/api/system/metrics"): None,
    ("GET", "/api/system/processes"): None,
    ("POST", "/api/system/processes/terminate"): None,
    ("GET", "/api/system/resources"): None,
    ("POST", "/api/workspaces"): None,
    ("DELETE", "/api/workspaces/{workspace_id}"): None,
    ("GET", "/api/workspaces/{workspace_id}"): None,
    ("GET", "/api/workspaces/{workspace_id}/artifacts/{artifact_id}"): None,
    ("POST", "/api/workspaces/{workspace_id}/duplicate-reports"): None,
    ("POST", "/api/workspaces/{workspace_id}/extractions"): None,
    ("POST", "/api/workspaces/{workspace_id}/file-type-reports"): None,
    ("POST", "/api/workspaces/{workspace_id}/folder-comparisons"): None,
    ("POST", "/api/workspaces/{workspace_id}/hash-reports"): None,
    ("POST", "/api/workspaces/{workspace_id}/joins"): None,
    ("POST", "/api/workspaces/{workspace_id}/rename-previews"): None,
    ("POST", "/api/workspaces/{workspace_id}/renamed-artifacts"): None,
    ("POST", "/api/workspaces/{workspace_id}/similar-image-reports"): None,
    ("POST", "/api/workspaces/{workspace_id}/splits"): None,
    ("POST", "/api/workspaces/{workspace_id}/storage-reports"): None,
    # Added on main after the licence work was written (invoices, storage-cleanup progress, image summary,
    # clipboard reuse, network health): all belong to paid tools, so any paid entitlement is enough.
    ("POST", "/api/network/health"): None,
    ("GET", "/api/invoice-libraries"): None,
    ("POST", "/api/invoice-libraries"): None,
    ("POST", "/api/invoice-restorations"): None,
    ("GET", "/api/invoice-libraries/{library_id}"): None,
    ("POST", "/api/invoice-libraries/{library_id}/reconnections"): None,
    ("POST", "/api/invoice-libraries/{library_id}/reloads"): None,
    ("GET", "/api/invoice-libraries/{library_id}/history"): None,
    ("POST", "/api/invoice-libraries/{library_id}/backups"): None,
    ("GET", "/api/invoice-libraries/{library_id}/businesses"): None,
    ("POST", "/api/invoice-libraries/{library_id}/businesses"): None,
    ("GET", "/api/invoice-libraries/{library_id}/businesses/{identifier}"): None,
    ("PUT", "/api/invoice-libraries/{library_id}/businesses/{identifier}"): None,
    ("GET", "/api/invoice-libraries/{library_id}/clients"): None,
    ("POST", "/api/invoice-libraries/{library_id}/clients"): None,
    ("GET", "/api/invoice-libraries/{library_id}/clients/{identifier}"): None,
    ("PUT", "/api/invoice-libraries/{library_id}/clients/{identifier}"): None,
    ("GET", "/api/invoice-libraries/{library_id}/items"): None,
    ("POST", "/api/invoice-libraries/{library_id}/items"): None,
    ("GET", "/api/invoice-libraries/{library_id}/items/{identifier}"): None,
    ("PUT", "/api/invoice-libraries/{library_id}/items/{identifier}"): None,
    ("GET", "/api/invoice-libraries/{library_id}/schedules"): None,
    ("POST", "/api/invoice-libraries/{library_id}/schedules"): None,
    ("GET", "/api/invoice-libraries/{library_id}/schedules/{identifier}"): None,
    ("PUT", "/api/invoice-libraries/{library_id}/schedules/{identifier}"): None,
    ("GET", "/api/invoice-libraries/{library_id}/documents"): None,
    ("POST", "/api/invoice-libraries/{library_id}/documents"): None,
    ("GET", "/api/invoice-libraries/{library_id}/documents/{identifier}"): None,
    ("PUT", "/api/invoice-libraries/{library_id}/documents/{identifier}"): None,
    ("POST", "/api/invoice-libraries/{library_id}/documents/{identifier}/transitions"): None,
    ("POST", "/api/invoice-libraries/{library_id}/documents/{identifier}/archives"): None,
    ("POST", "/api/invoice-libraries/{library_id}/document-conversions"): None,
    ("GET", "/api/invoice-libraries/{library_id}/documents/{identifier}/payments"): None,
    ("POST", "/api/invoice-libraries/{library_id}/documents/{identifier}/payments"): None,
    ("POST", "/api/invoice-libraries/{library_id}/documents/{identifier}/payment-corrections"): None,
    ("POST", "/api/invoice-libraries/{library_id}/recurring-draft-batches"): None,
    ("POST", "/api/invoice-libraries/{library_id}/document-previews"): None,
    ("GET", "/api/invoice-libraries/{library_id}/documents/{identifier}/pdf"): None,
    ("POST", "/api/invoice-libraries/{library_id}/assets"): None,
    ("GET", "/api/invoice-libraries/{library_id}/assets/{identifier}"): None,
    ("GET", "/api/invoice-libraries/{library_id}/reports"): None,
    ("GET", "/api/invoice-libraries/{library_id}/reports.csv"): None,
    ("GET", "/api/storage-cleanup-plans/{plan_id}/execution"): None,
    ("DELETE", "/api/storage-cleanup-plans/{plan_id}/execution"): None,
    ("GET", "/api/file-selections/{selection_id}/image-summary"): None,
    ("POST", "/api/clipboard/clips/{clip_id}/use"): None,
}

NO_MATCH = object()

# Lookup tables built once at import; match_route takes a mapping.
_EXEMPT_LOOKUP = {route: True for route in GATE_EXEMPT_ROUTES}
_FREE_LOOKUP = {route: True for route in FREE_ROUTES}


def _segment_matches(template_part: str, actual_part: str) -> bool:
    if template_part.startswith("{") and template_part.endswith("}"):
        return bool(actual_part) and actual_part not in {".", ".."}
    return template_part == actual_part


def match_route(table: Mapping[tuple[str, str], object], method: str, path: str):
    """Return the table value for the most specific (literal-first) template, else NO_MATCH."""
    actual = path.split("/")
    best, best_literals = NO_MATCH, -1
    for (route_method, template), value in table.items():
        if route_method != method:
            continue
        parts = template.split("/")
        if len(parts) != len(actual) or not all(
            _segment_matches(expected, seen) for expected, seen in zip(parts, actual)
        ):
            continue
        literals = sum(not (part.startswith("{") and part.endswith("}")) for part in parts)
        if literals > best_literals:
            best, best_literals = value, literals
    return best


def is_gate_exempt(path: str, method: str | None = None) -> bool:
    """True when the request may proceed without an entitlement; without a method, any listed method."""
    methods: Iterable[str] = (method,) if method is not None else ("GET", "POST", "PUT", "PATCH", "DELETE")
    return any(match_route(_EXEMPT_LOOKUP, candidate, path) is True for candidate in methods)


def is_free_route(path: str, method: str) -> bool:
    """True when the route belongs to a product-free tool and may proceed without an entitlement."""
    return match_route(_FREE_LOOKUP, method, path) is True


def feature_for_route(method: str, path: str) -> str | None:
    """Feature slug a gated route needs; None means any live paid entitlement is enough."""
    value = match_route(ROUTE_FEATURES, method, path)
    return None if value is NO_MATCH else value


@dataclass(frozen=True)
class Entitlement:
    edition: str
    features: frozenset[str]
    valid_until_epoch: int


def sleep_aware_clock(platform: str = sys.platform, time_module=time) -> Callable[[], float]:
    """A monotonic clock that keeps counting while the machine sleeps.

    ``time.monotonic`` pauses during macOS sleep, which would stretch a pushed lifetime by the time
    the lid was closed. ``CLOCK_MONOTONIC_RAW`` (macOS) and ``CLOCK_BOOTTIME`` (Linux) keep counting
    and, like ``time.monotonic``, ignore wall-clock changes. Windows' ``time.monotonic`` already
    counts sleep, so it (and any platform without those clocks) uses ``time.monotonic``.
    """
    name = "CLOCK_MONOTONIC_RAW" if platform == "darwin" else "CLOCK_BOOTTIME"
    clock_id = getattr(time_module, name, None)
    if clock_id is None:
        return time_module.monotonic
    return lambda: time_module.clock_gettime(clock_id)


class EntitlementState:
    """Thread-safe, memory-only summary of the entitlement the native shell last verified."""

    def __init__(
        self,
        clock: Callable[[], float] | None = None,
        wall_clock: Callable[[], float] = time.time,
    ):
        self._clock = clock if clock is not None else sleep_aware_clock()
        self._wall_clock = wall_clock
        self._lock = threading.Lock()
        self._entitlement: tuple[Entitlement, float] | None = None

    def install(self, edition: str, features: Iterable[str], valid_for_seconds: int) -> None:
        if edition != EDITION_PAID:
            raise ValueError("Unsupported edition")
        if type(valid_for_seconds) is not int or valid_for_seconds <= 0:
            raise ValueError("Entitlement lifetime must be a positive integer")
        with self._lock:
            summary = Entitlement(
                edition,
                frozenset(features),
                int(math.floor(self._wall_clock())) + valid_for_seconds,
            )
            self._entitlement = (summary, self._clock() + valid_for_seconds)

    def clear(self) -> None:
        with self._lock:
            self._entitlement = None

    def current(self) -> Entitlement | None:
        with self._lock:
            if self._entitlement is None:
                return None
            summary, expires_at = self._entitlement
            if self._clock() >= expires_at:
                self._entitlement = None
                return None
            return summary


GATE_STATE = EntitlementState()


class EntitlementPushRequest(BaseModel):
    """Body of PUT /api/license/entitlement, written only by the native shell."""

    model_config = ConfigDict(extra="forbid", strict=True)

    activation_id: StrictStr
    edition: Literal["paid"]
    features: list[StrictStr] = PydanticField(max_length=MAX_FEATURES)
    valid_for_seconds: StrictInt = PydanticField(ge=MIN_VALID_FOR_SECONDS, le=MAX_VALID_FOR_SECONDS)

    @field_validator("activation_id")
    @classmethod
    def _activation_id_shape(cls, value: str) -> str:
        if not ACTIVATION_ID_PATTERN.fullmatch(value):
            raise ValueError("invalid activation id")
        return value

    @field_validator("features")
    @classmethod
    def _features_are_sorted_unique_slugs(cls, value: list[str]) -> list[str]:
        if any(not FEATURE_PATTERN.fullmatch(feature) for feature in value) or value != sorted(set(value)):
            raise ValueError("invalid features")
        return value


class ReleaseResponse(BaseModel):
    """GET /api/release: the release profile (what this build ships), build identity and the active
    edition (None while locked)."""

    profile: Literal["development", "private-beta"]
    tool_ids: list[str]
    version: str
    edition: Literal["paid"] | None


class LicenseStatusResponse(BaseModel):
    """GET /api/license/status: the in-memory entitlement summary, never a key, email or token."""

    activated: bool
    edition: Literal["paid"] | None
    features: list[str]
    valid_until_epoch: int | None


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    """The licence gate's and entitlement handoff's error body."""

    error: ErrorBody


def load_native_grant_token(environment: Mapping[str, str], api_token: str | None) -> str | None:
    """Return the shell's grant token, or None (fail closed) when unset, malformed or equal to the API token."""
    token = environment.get(NATIVE_GRANT_ENVIRONMENT_KEY)
    if (
        not isinstance(token, str)
        or not MIN_GRANT_TOKEN_LENGTH <= len(token) <= MAX_GRANT_TOKEN_LENGTH
        or not token.isascii()
        or any(not character.isprintable() or character.isspace() for character in token)
        or (api_token is not None and hmac.compare_digest(token.encode(), api_token.encode()))
    ):
        return None
    return token


def is_native_grant_valid(presented: str | None, expected: str | None) -> bool:
    """Constant-time grant comparison; any missing, empty or non-ASCII value is rejected.

    There is no length check on the presented value: a wrong-length value simply fails the digest
    comparison (the request body limit and header size limits bound it).
    """
    if (
        not isinstance(presented, str)
        or not isinstance(expected, str)
        or not presented
        or not presented.isascii()
    ):
        return False
    return hmac.compare_digest(presented.encode("ascii"), expected.encode("ascii"))


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def license_required_payload() -> dict:
    return _error("license_required", "An active OfficeKit licence is required.")


def feature_not_licensed_payload() -> dict:
    return _error("feature_not_licensed", "Your licence does not include this feature.")


def native_grant_required_payload() -> dict:
    return _error("native_grant_required", "The request is not authorized.")


def invalid_entitlement_payload() -> dict:
    return _error("invalid_entitlement", "The entitlement summary is invalid.")
