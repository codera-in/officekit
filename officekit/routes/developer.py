"""Developer slice routes (D04, D10–D11, D15–D17).

Every POST path has a pre-parse body cap in ``BODY_LIMITS`` (P-036). Request
DTOs forbid extra fields and use strict types. A 422 carries one fixed message
per route, and neither DTO nor engine detail is echoed (P-013).
"""

from typing import Literal

from fastapi import APIRouter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from officekit.engines import engine_developer
from officekit.engines.engine_developer import DeveloperInputError

# Pre-filter by code points. The engine enforces the contract limit of 1,048,576
# UTF-8 bytes (`DevToolsEngine._text_bytes`); any text over this many code points is
# also over the byte limit, so the DTO never accepts more than the engine would.
MAX_TEXT_CHARS = 1_048_576
MAX_UUID_NAME_CHARS = 1_024
MAX_BATCH = 1_000
MAX_TARGET_ZONES = 8
MAX_QR_PAYLOAD_CHARS = 2_953
MAX_TIME_ZONE_RESPONSE = 1_000
MAX_DIFF_CHANGES = 10_000
MAX_CASE_RESULT_CHARS = 1_048_576

JSON_DIFF_PATH = "/api/developer/json-diffs"
TEXT_DIFF_PATH = "/api/developer/text-diffs"
TEXT_CASE_PATH = "/api/developer/text-case-conversions"
TEXT_ANALYSIS_PATH = "/api/developer/text-analyses"
TIMESTAMP_PATH = "/api/developer/timestamp-conversions"
TIME_ZONES_PATH = "/api/developer/time-zones"
UUIDS_PATH = "/api/developer/uuids"
QR_PATH = "/api/developer/qr-codes"

FIXED_MESSAGES = {
    JSON_DIFF_PATH: "JSON comparison input is invalid or exceeds supported limits.",
    TEXT_DIFF_PATH: "Text comparison input is invalid, too different, or exceeds supported limits.",
    TEXT_CASE_PATH: "Text input is invalid or exceeds supported limits.",
    TEXT_ANALYSIS_PATH: "Text input is invalid or exceeds supported limits.",
    TIMESTAMP_PATH: "Timestamp input is invalid, ambiguous or out of range.",
    UUIDS_PATH: "UUID request is invalid or exceeds the batch limit.",
    QR_PATH: "QR payload is empty, invalid or too long for this error-correction level.",
}

BODY_LIMITS = {
    JSON_DIFF_PATH: 16 * 1024 * 1024,
    TEXT_DIFF_PATH: 16 * 1024 * 1024,
    TEXT_CASE_PATH: 8 * 1024 * 1024,
    TEXT_ANALYSIS_PATH: 8 * 1024 * 1024,
    TIMESTAMP_PATH: 4 * 1024,
    # Sized for the largest valid name: 1,024 control characters, each a six-byte JSON escape.
    UUIDS_PATH: 8 * 1024,
    QR_PATH: 32 * 1024,
}

EXPOSE_HEADERS = ()


class _FixedMessageRoute(APIRoute):
    """Replace validation and engine-input failures with this route's fixed 422 message."""

    def get_route_handler(self):
        handler = super().get_route_handler()
        message = FIXED_MESSAGES.get(self.path)
        if message is None:
            return handler

        async def fixed_message_handler(request):
            try:
                return await handler(request)
            except (RequestValidationError, DeveloperInputError):
                return JSONResponse(status_code=422, content={"detail": message})

        return fixed_message_handler


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class JsonDiffRequest(_StrictModel):
    original: str = Field(max_length=MAX_TEXT_CHARS)
    changed: str = Field(max_length=MAX_TEXT_CHARS)
    array_order: Literal["ordered", "unordered"] = "ordered"
    numeric: Literal["value", "lexical"] = "value"


class JsonChange(BaseModel):
    path: str
    kind: Literal["added", "removed", "changed", "type_changed"]
    before: str | None = None
    after: str | None = None


class JsonCounts(BaseModel):
    added: int
    removed: int
    changed: int
    type_changed: int


class JsonDiffResponse(BaseModel):
    equal: bool
    changes: list[JsonChange] = Field(max_length=MAX_DIFF_CHANGES)
    truncated: bool
    counts: JsonCounts


class TextDiffRequest(_StrictModel):
    original: str = Field(max_length=MAX_TEXT_CHARS)
    changed: str = Field(max_length=MAX_TEXT_CHARS)
    whitespace: Literal["exact", "ignore_trailing", "ignore_all"] = "exact"
    line_endings: Literal["normalize", "exact"] = "normalize"
    unicode_nfc: bool = False
    context: StrictInt = Field(default=3, ge=0, le=20)


class TextSpan(BaseModel):
    start: int
    end: int


class TextRow(BaseModel):
    op: Literal["equal", "insert", "delete", "change"]
    left_no: int | None = None
    right_no: int | None = None
    left: str | None = None
    right: str | None = None
    left_spans: list[TextSpan] | None = None
    right_spans: list[TextSpan] | None = None


class TextStats(BaseModel):
    inserted: int
    deleted: int
    changed: int


class LineEndingReport(BaseModel):
    original: Literal["none", "lf", "crlf", "cr", "mixed"]
    changed: Literal["none", "lf", "crlf", "cr", "mixed"]


class TextDiffResponse(BaseModel):
    equal: bool
    rows: list[TextRow]
    spans_omitted: bool
    hunks: int
    stats: TextStats
    line_endings: LineEndingReport
    patch: str
    markdown: str


class TextCaseRequest(_StrictModel):
    text: str = Field(max_length=MAX_TEXT_CHARS)
    style: Literal["lower", "upper", "title", "sentence", "camel", "pascal", "snake", "kebab", "constant"]
    locale: Literal["root", "tr", "az"] = "root"


class TextCaseResponse(BaseModel):
    result: str = Field(max_length=MAX_CASE_RESULT_CHARS)
    style: str
    locale: str


class TextAnalysisRequest(_StrictModel):
    text: str = Field(max_length=MAX_TEXT_CHARS)


class TextAnalysisResponse(BaseModel):
    graphemes: int
    code_points: int
    utf8_bytes: int
    utf16_units: int
    words: int
    lines: int
    blank_lines: int
    whitespace: int
    longest_line_graphemes: int


class TimestampRequest(_StrictModel):
    value: str = Field(min_length=1, max_length=64)
    input_type: Literal["unix_seconds", "unix_milliseconds", "unix_microseconds", "iso_8601", "local_datetime"]
    source_zone: str | None = Field(default=None, max_length=64)
    fold: Literal["reject", "earlier", "later"] = "reject"
    target_zones: list[str] = Field(min_length=1, max_length=MAX_TARGET_ZONES)


class ZoneConversion(BaseModel):
    zone: str
    local_iso: str
    offset: str
    abbreviation: str
    is_dst: bool
    weekday: str


class TimestampResponse(BaseModel):
    instant_utc: str
    unix_seconds: str
    unix_milliseconds: str
    unix_microseconds: str
    conversions: list[ZoneConversion]
    warnings: list[str]


class TimeZonesResponse(BaseModel):
    zones: list[str] = Field(max_length=MAX_TIME_ZONE_RESPONSE)
    local_zone: str | None


class UuidRequest(_StrictModel):
    version: Literal[4, 5, 7]
    count: StrictInt = Field(default=1, ge=1, le=MAX_BATCH)
    namespace: str | None = Field(default=None, max_length=36)
    name: str | None = Field(default=None, max_length=MAX_UUID_NAME_CHARS)
    case: Literal["lower", "upper"] = "lower"
    style: Literal["canonical", "braces", "urn", "compact"] = "canonical"


class UuidResponse(BaseModel):
    uuids: list[str] = Field(max_length=MAX_BATCH)
    version: Literal[4, 5, 7]
    count: int


class QrRequest(_StrictModel):
    payload: str = Field(min_length=1, max_length=MAX_QR_PAYLOAD_CHARS)
    error_correction: Literal["L", "M", "Q", "H"] = "M"
    size_px: StrictInt = Field(default=512, ge=128, le=2_048)
    format: Literal["png", "svg"] = "png"


class QrResponse(BaseModel):
    format: Literal["png", "svg"]
    data: str
    qr_version: int
    modules: int
    payload_bytes: int
    size_px: int


router = APIRouter(prefix="/api/developer", route_class=_FixedMessageRoute)


@router.post("/json-diffs", response_model=JsonDiffResponse, response_model_exclude_none=True)
def compare_json_documents(body: JsonDiffRequest) -> dict:
    return engine_developer.compare_json(
        body.original,
        body.changed,
        array_order=body.array_order,
        numeric=body.numeric,
    )


@router.post("/text-diffs", response_model=TextDiffResponse, response_model_exclude_none=True)
def compare_text_documents(body: TextDiffRequest) -> dict:
    return engine_developer.compare_text(
        body.original,
        body.changed,
        whitespace=body.whitespace,
        line_endings=body.line_endings,
        unicode_nfc=body.unicode_nfc,
        context=body.context,
    )


@router.post("/text-case-conversions", response_model=TextCaseResponse)
def convert_text_case(body: TextCaseRequest) -> dict:
    return engine_developer.convert_case(body.text, body.style, body.locale)


@router.post("/text-analyses", response_model=TextAnalysisResponse)
def analyze_text(body: TextAnalysisRequest) -> dict:
    return engine_developer.text_metrics(body.text)


@router.post("/timestamp-conversions", response_model=TimestampResponse)
def convert_timestamps(body: TimestampRequest) -> dict:
    return engine_developer.convert_timestamp(
        body.value,
        body.input_type,
        body.source_zone,
        body.fold,
        body.target_zones,
    )


@router.get("/time-zones", response_model=TimeZonesResponse)
def list_time_zones() -> dict:
    return engine_developer.list_time_zones()


@router.post("/uuids", response_model=UuidResponse)
def generate_uuids(body: UuidRequest) -> dict:
    return engine_developer.generate_uuids(
        body.version,
        body.count,
        namespace=body.namespace,
        name=body.name,
        case=body.case,
        style=body.style,
    )


@router.post("/qr-codes", response_model=QrResponse)
def generate_qr_code(body: QrRequest) -> dict:
    return engine_developer.generate_qr(body.payload, body.error_correction, body.size_px, body.format)
