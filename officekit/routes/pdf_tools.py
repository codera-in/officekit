"""PDF tool slice routes (P06, P08, P10, P12, P13, P15, P16, P17).

Every route is multipart POST. ``options`` is a JSON string form field (<= 4,096 bytes) parsed with
duplicate-key rejection, then validated strictly with ``extra="forbid"``. Errors never echo parser
text or filenames: typed refusals return fixed copy, everything else returns the generic PDF message.
"""

import unicodedata
from contextlib import contextmanager
from decimal import Decimal
from typing import Literal

import pikepdf
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from officekit.engines.engine_devtools import DevToolsEngine
from officekit.engines.engine_file_responses import content_disposition_attachment
from officekit.engines.engine_images_to_pdf import ImageInputError, ImagesToPdfEngine
from officekit.engines.engine_pdf_flatten import FlattenRefusedError, PdfFlattenEngine
from officekit.engines.engine_pdf_grayscale import GrayscaleLimitError, GrayscaleRefusedError, PdfGrayscaleEngine
from officekit.engines.engine_pdf_inspect import PdfInspectEngine
from officekit.engines.engine_pdf_page_tools import PageToolsEngine
from officekit.engines.engine_pdf_security import PDF_OUTPUT_LIMIT_ERROR, PdfOutputLimitError
from officekit.engines.engine_pdf_stamp import (
    PageNumberSpec,
    PdfStampEngine,
    PdfStampInputError,
    WatermarkSpec,
    format_ranges,
)
from officekit.engines.engine_pdf_tool_common import PdfOptionError, count_pages
from officekit.engines.engine_uploads import UploadTooLargeError, read_bounded_upload
from officekit.routes.common import (
    MAX_API_UPLOAD_BYTES,
    MAX_MULTIPART_OVERHEAD_BYTES,
    PDF_INPUT_ERROR_MESSAGE,
    read_api_upload,
)

router = APIRouter()

MAX_WATERMARK_IMAGE_BYTES = 8 * 1024 * 1024
MAX_OPTIONS_BYTES = 4096
WATERMARK_TEXT_MAX_CHARS = 200
INVALID_OPTIONS_MESSAGE = "Request contains invalid or unsupported values."

_STANDARD_BODY = MAX_API_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES
_WATERMARK_BODY = (MAX_API_UPLOAD_BYTES + MAX_WATERMARK_IMAGE_BYTES) + MAX_MULTIPART_OVERHEAD_BYTES

BODY_LIMITS = {
    "/api/pdf/page-rotations": _STANDARD_BODY,
    "/api/pdf/image-pdfs": _STANDARD_BODY,
    "/api/pdf/inspections": _STANDARD_BODY,
    "/api/pdf/watermarks": _WATERMARK_BODY,
    "/api/pdf/watermarks/previews": _WATERMARK_BODY,
    "/api/pdf/page-numbers": _STANDARD_BODY,
    "/api/pdf/page-numbers/previews": _STANDARD_BODY,
    "/api/pdf/page-sizes": _STANDARD_BODY,
    "/api/pdf/grayscale-conversions": _STANDARD_BODY,
    "/api/pdf/flattenings": _STANDARD_BODY,
}

EXPOSE_HEADERS = (
    "X-OfficeKit-Affected-Pages",
    "X-OfficeKit-Page-Count",
    "X-OfficeKit-Overlap-Pages",
    "X-OfficeKit-Scale",
    "X-OfficeKit-Grayscale-Method",
    "X-OfficeKit-Output-Input-Ratio",
    "X-OfficeKit-Flattened-Fields",
    "X-OfficeKit-Flattened-Annotations",
)

_STRICT = ConfigDict(extra="forbid", strict=True)
_ANCHORS = Literal[
    "bottom-left", "bottom-center", "bottom-right", "center-left", "center", "center-right",
    "top-left", "top-center", "top-right",
]


class RotationOptions(BaseModel):
    model_config = _STRICT
    angle: Literal[90, 180, 270]
    page_ranges: str = Field("", max_length=4096)


class ResizeOptions(BaseModel):
    model_config = _STRICT
    preset: Literal["a4", "a5", "letter", "legal", "tabloid", "custom"]
    width: str | None = Field(None, pattern=r"^\d{1,6}(\.\d{1,2})?$")
    height: str | None = Field(None, pattern=r"^\d{1,6}(\.\d{1,2})?$")
    unit: Literal["mm", "in", "pt"] | None = None
    orientation: Literal["keep", "portrait", "landscape"] = "keep"
    mode: Literal["scale", "canvas"]
    anchor: _ANCHORS = "center"
    page_ranges: str = Field("", max_length=4096)

    @model_validator(mode="after")
    def _custom_size_is_complete(self):
        # A custom size needs width, height and unit; a named preset takes none of them (CR-4, ARCH-11).
        sized = self.width is not None or self.height is not None or self.unit is not None
        if self.preset == "custom" and (self.width is None or self.height is None or self.unit is None):
            raise ValueError("A custom size needs width, height and unit.")
        if self.preset != "custom" and sized:
            raise ValueError("Width, height and unit apply only to a custom size.")
        return self


class ImagesOptions(BaseModel):
    model_config = _STRICT
    page_size: Literal["a4", "letter", "legal", "image"]
    orientation: Literal["auto", "portrait", "landscape"]
    fit: Literal["contain", "cover", "actual"]
    margin_mm: int = Field(ge=0, le=50)


class WatermarkOptions(BaseModel):
    model_config = _STRICT
    kind: Literal["text", "image"]
    text: str | None = Field(None, min_length=1, max_length=WATERMARK_TEXT_MAX_CHARS)
    font_size: int = Field(ge=8, le=144)
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    opacity: int = Field(ge=5, le=100)
    angle: int = Field(ge=-90, le=90)
    position: Literal[
        "center", "tile", "top-left", "top-center", "top-right",
        "bottom-left", "bottom-center", "bottom-right",
    ]
    page_ranges: str = Field("", max_length=4096)

    @field_validator("text")
    @classmethod
    def _no_control_characters(cls, value: str | None) -> str | None:
        if value is not None and any(unicodedata.category(character) == "Cc" for character in value):
            raise ValueError("Watermark text cannot contain control characters.")
        return value

    @model_validator(mode="after")
    def _text_belongs_to_text_kind(self):
        # text is required for a text watermark and not allowed otherwise (the image part is checked in the route).
        if (self.kind == "text") != (self.text is not None):
            raise ValueError("Text is required for text watermarks and not allowed otherwise.")
        return self


class WatermarkPreviewOptions(WatermarkOptions):
    preview_page: int = Field(ge=0, le=2000)


class PageNumberOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)
    number_format: Literal["number", "page", "page-of-total", "roman-lower", "roman-upper", "custom"] = Field(
        alias="format")
    template: str | None = Field(None, max_length=64)
    start: int = Field(1, ge=0, le=9999)
    position: Literal["top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right"]
    margin_mm: int = Field(ge=0, le=50)
    font_size: int = Field(ge=6, le=36)
    page_ranges: str = Field("", max_length=4096)
    count_skipped: bool = False

    @model_validator(mode="after")
    def _template_belongs_to_custom_format(self):
        if self.number_format == "custom":
            if self.template is None or not self.template:
                raise ValueError("A custom format needs a template.")
            remainder = self.template.replace("{n}", "").replace("{total}", "")
            if "{" in remainder or "}" in remainder:
                raise ValueError("Templates may only use the {n} and {total} tokens.")
        elif self.template is not None:
            raise ValueError("A template is only used with the custom format.")
        return self


class PageNumberPreviewOptions(PageNumberOptions):
    preview_page: int = Field(ge=0, le=2000)


class GrayscaleOptions(BaseModel):
    model_config = _STRICT
    method: Literal["vector", "raster"] = "vector"
    dpi: Literal[150, 300] | None = None

    @model_validator(mode="after")
    def _dpi_belongs_to_raster(self):
        # DPI applies only to rasterized output, and rasterizing needs a DPI (ARCH-11, CR-4).
        if self.method == "vector" and self.dpi is not None:
            raise ValueError("DPI applies only to rasterized grayscale.")
        if self.method == "raster" and self.dpi is None:
            raise ValueError("Rasterized grayscale needs 150 or 300 DPI.")
        return self


class FlattenOptions(BaseModel):
    model_config = _STRICT
    scope: Literal["all", "forms", "annotations"] = "all"
    acknowledge_signature_loss: bool = False


class DocInfoEntry(BaseModel):
    key: str
    label: str
    standard: bool
    present: bool
    value: str | None
    truncated: bool


class DatesSummary(BaseModel):
    CreationDate: str | None
    ModDate: str | None


class XmpEntry(BaseModel):
    name: str
    value: str
    truncated: bool


class XmpSummary(BaseModel):
    present: bool
    entries: list[XmpEntry]


class PageSizeGroup(BaseModel):
    width_pt: float
    height_pt: float
    rotate: int
    count: int


class FormsSummary(BaseModel):
    fields: int
    signature_fields: int
    signed: bool
    xfa: bool


class PdfInspectionResponse(BaseModel):
    pdf_version: str
    page_count: int
    docinfo: list[DocInfoEntry]
    dates: DatesSummary
    xmp: XmpSummary
    page_sizes: list[PageSizeGroup]
    other_count: int
    forms: FormsSummary
    annotations: int
    encrypted: bool
    truncated: bool


# ----------------------------------------------------------------- helpers


def parse_options(raw: str, model):
    """Strict JSON options: bounded text, duplicate-key rejection, then strict DTO validation."""
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_OPTIONS_BYTES:
        raise HTTPException(status_code=422, detail=INVALID_OPTIONS_MESSAGE)
    try:
        parsed = DevToolsEngine._parse_json(raw)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=422, detail=INVALID_OPTIONS_MESSAGE) from error
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=422, detail=INVALID_OPTIONS_MESSAGE)
    for key in ("width", "height"):
        # Decimal sizes arrive as JSON numbers; the DTO takes their canonical text form.
        value = parsed.get(key)
        if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
            parsed[key] = format(Decimal(value), "f")
    try:
        return model.model_validate(parsed, strict=True)
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=INVALID_OPTIONS_MESSAGE) from error


@contextmanager
def pdf_errors():
    """Map engine failures to the public statuses; anything unexpected propagates to the 500 boundary."""
    try:
        yield
    except PdfOutputLimitError:
        raise HTTPException(status_code=413, detail=PDF_OUTPUT_LIMIT_ERROR) from None
    except GrayscaleRefusedError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "message": error.message}) from None
    except GrayscaleLimitError as error:
        raise HTTPException(status_code=422, detail=error.message) from None
    except FlattenRefusedError as error:
        raise HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message}) \
            from None
    except (PdfStampInputError, ImageInputError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except PdfOptionError:
        raise HTTPException(status_code=422, detail=INVALID_OPTIONS_MESSAGE) from None
    except (ValueError, OSError, pikepdf.PdfError, pikepdf.PasswordError):
        raise HTTPException(status_code=422, detail=PDF_INPUT_ERROR_MESSAGE) from None


PDF_BINARY = {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}
PNG_BINARY = {"image/png": {"schema": {"type": "string", "format": "binary"}}}


def binary_responses(media: dict, description: str, *, errors: dict | None = None) -> dict:
    """OpenAPI declaration for a binary 2xx plus the statuses the contract rows list."""
    responses = {
        200: {"description": description, "content": media},
        413: {"description": "The output exceeds the processing limit. No body is returned."},
        422: {"description": "Invalid input or options. The message is fixed copy."},
    }
    responses.update(errors or {})
    return responses


def stem_of(upload: UploadFile) -> str:
    name = upload.filename or "document.pdf"
    return name.rsplit(".", 1)[0] if "." in name else name


def pdf_response(content: bytes, filename: str, page_count: int, extra: dict | None = None) -> Response:
    headers = {
        "Content-Disposition": content_disposition_attachment(filename),
        "X-OfficeKit-Page-Count": str(page_count),
    }
    headers.update(extra or {})
    return Response(content=content, media_type="application/pdf", headers=headers)


def png_response(content: bytes, extra: dict | None = None) -> Response:
    return Response(content=content, media_type="image/png", headers=dict(extra or {}))


def _watermark_spec(options: WatermarkOptions, image: bytes | None) -> WatermarkSpec:
    return WatermarkSpec(
        kind=options.kind, text=options.text, image=image, font_size=options.font_size,
        color=options.color, opacity=options.opacity, angle=options.angle,
        position=options.position, page_ranges=options.page_ranges,
    )


def _number_spec(options: PageNumberOptions) -> PageNumberSpec:
    return PageNumberSpec(
        number_format=options.number_format, template=options.template, start=options.start,
        position=options.position, margin_mm=options.margin_mm, font_size=options.font_size,
        page_ranges=options.page_ranges, count_skipped=options.count_skipped,
    )


async def _watermark_image(image: UploadFile | None, options: WatermarkOptions) -> bytes | None:
    if options.kind == "image":
        if image is None:
            raise HTTPException(status_code=422, detail=INVALID_OPTIONS_MESSAGE)
        try:
            return await read_bounded_upload(image, MAX_WATERMARK_IMAGE_BYTES)
        except UploadTooLargeError as error:
            raise HTTPException(status_code=413, detail=str(error)) from error
    if image is not None:
        raise HTTPException(status_code=422, detail=INVALID_OPTIONS_MESSAGE)
    return None


# ------------------------------------------------------------------ routes


@router.post("/api/pdf/page-rotations", responses=binary_responses(PDF_BINARY, "The PDF with the rotated pages."))
async def api_rotate_pdf_pages(
    file: UploadFile = File(...),
    options: str = Form(..., max_length=MAX_OPTIONS_BYTES),
):
    """Set the real /Rotate of selected pages (or all pages when no range is given)."""
    content = await read_api_upload(file)
    settings = parse_options(options, RotationOptions)
    with pdf_errors():
        output, affected = PageToolsEngine.rotate_pages(content, settings.angle, settings.page_ranges)
        pages = count_pages(output)
    return pdf_response(output, f"{stem_of(file)}-rotated.pdf", pages,
                        {"X-OfficeKit-Affected-Pages": str(affected)})


@router.post("/api/pdf/image-pdfs", responses=binary_responses(PDF_BINARY, "One PDF page per image."))
async def api_images_to_pdf(
    files: list[UploadFile] = File(...),
    options: str = Form(..., max_length=MAX_OPTIONS_BYTES),
):
    """Build one PDF page per image, in the order the files were submitted."""
    settings = parse_options(options, ImagesOptions)
    if not 1 <= len(files) <= ImagesToPdfEngine.MAX_IMAGES:
        raise HTTPException(status_code=422, detail=INVALID_OPTIONS_MESSAGE)
    images = []
    total = 0
    for upload in files:
        data = await read_api_upload(upload)
        total += len(data)
        if total > MAX_API_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="The images exceed the 64 MiB processing limit.")
        images.append(data)
    with pdf_errors():
        output = ImagesToPdfEngine.build(images, settings.page_size, settings.orientation, settings.fit,
                                         settings.margin_mm)
        pages = count_pages(output)
    return pdf_response(output, "images.pdf", pages)


@router.post("/api/pdf/inspections", response_model=PdfInspectionResponse,
             responses={422: {"description": "Invalid input. The message is fixed copy."}})
async def api_inspect_pdf(file: UploadFile = File(...)):
    """Read-only report: document info, XMP, page geometry and form/annotation summary."""
    content = await read_api_upload(file)
    with pdf_errors():
        report = PdfInspectEngine.inspect(content)
    return PdfInspectionResponse(**report)


@router.post("/api/pdf/watermarks", responses=binary_responses(PDF_BINARY, "The watermarked PDF."))
async def api_watermark_pdf(
    file: UploadFile = File(...),
    options: str = Form(..., max_length=MAX_OPTIONS_BYTES),
    image: UploadFile | None = File(None),
):
    """Stamp text or a PNG/JPEG image on selected pages, placed by page geometry."""
    content = await read_api_upload(file)
    settings = parse_options(options, WatermarkOptions)
    picture = await _watermark_image(image, settings)
    with pdf_errors():
        output = PdfStampEngine.watermark(content, _watermark_spec(settings, picture))
        pages = count_pages(output)
    return pdf_response(output, f"{stem_of(file)}-watermarked.pdf", pages)


@router.post("/api/pdf/watermarks/previews", responses=binary_responses(PNG_BINARY, "PNG of one stamped page."))
async def api_watermark_preview(
    file: UploadFile = File(...),
    options: str = Form(..., max_length=MAX_OPTIONS_BYTES),
    image: UploadFile | None = File(None),
):
    """PNG of one stamped page, rendered from the same path as the output."""
    content = await read_api_upload(file)
    settings = parse_options(options, WatermarkPreviewOptions)
    picture = await _watermark_image(image, settings)
    with pdf_errors():
        png = PdfStampEngine.watermark_preview(content, _watermark_spec(settings, picture), settings.preview_page)
    return png_response(png)


@router.post("/api/pdf/page-numbers", responses=binary_responses(PDF_BINARY, "The numbered PDF."))
async def api_page_numbers_pdf(
    file: UploadFile = File(...),
    options: str = Form(..., max_length=MAX_OPTIONS_BYTES),
):
    """Number selected pages; reports pages whose number box touches existing text or images."""
    content = await read_api_upload(file)
    settings = parse_options(options, PageNumberOptions)
    with pdf_errors():
        output, overlaps = PdfStampEngine.page_numbers(content, _number_spec(settings))
        pages = count_pages(output)
    return pdf_response(output, f"{stem_of(file)}-numbered.pdf", pages,
                        {"X-OfficeKit-Overlap-Pages": format_ranges(overlaps)})


@router.post("/api/pdf/page-numbers/previews", responses=binary_responses(PNG_BINARY, "PNG of one numbered page."))
async def api_page_numbers_preview(
    file: UploadFile = File(...),
    options: str = Form(..., max_length=MAX_OPTIONS_BYTES),
):
    content = await read_api_upload(file)
    settings = parse_options(options, PageNumberPreviewOptions)
    with pdf_errors():
        png, overlaps = PdfStampEngine.page_numbers_preview(content, _number_spec(settings), settings.preview_page)
    return png_response(png, {"X-OfficeKit-Overlap-Pages": format_ranges(overlaps)})


@router.post("/api/pdf/page-sizes", responses=binary_responses(PDF_BINARY, "The PDF with resized pages."))
async def api_resize_pdf_pages(
    file: UploadFile = File(...),
    options: str = Form(..., max_length=MAX_OPTIONS_BYTES),
):
    """Change page size by scaling content to fit, or by changing the canvas around it."""
    content = await read_api_upload(file)
    settings = parse_options(options, ResizeOptions)
    with pdf_errors():
        target = PageToolsEngine.target_size(settings.preset, settings.width, settings.height, settings.unit)
        output, minimum_scale = PageToolsEngine.resize_pages(
            content, target=target, orientation=settings.orientation, mode=settings.mode,
            anchor=settings.anchor, page_ranges=settings.page_ranges,
        )
        pages = count_pages(output)
    return pdf_response(output, f"{stem_of(file)}-resized.pdf", pages,
                        {"X-OfficeKit-Scale": f"{minimum_scale:.4f}"})


@router.post("/api/pdf/grayscale-conversions",
             responses=binary_responses(PDF_BINARY, "The grayscale PDF."))
async def api_grayscale_pdf(
    file: UploadFile = File(...),
    options: str = Form(..., max_length=MAX_OPTIONS_BYTES),
):
    """Vector grayscale when exact; rasterized grayscale is an explicit, labelled alternative."""
    content = await read_api_upload(file)
    settings = parse_options(options, GrayscaleOptions)
    with pdf_errors():
        output, method = PdfGrayscaleEngine.convert(content, settings.method, settings.dpi)
        pages = count_pages(output)
    ratio = len(output) / len(content)
    return pdf_response(output, f"{stem_of(file)}-grayscale.pdf", pages, {
        "X-OfficeKit-Grayscale-Method": method,
        "X-OfficeKit-Output-Input-Ratio": f"{ratio:.4f}",
    })


@router.post("/api/pdf/flattenings", responses=binary_responses(
    PDF_BINARY, "The flattened PDF.",
    errors={409: {"description": "A signed field needs acknowledgement. The body is a stable code."}},
))
async def api_flatten_pdf(
    file: UploadFile = File(...),
    options: str = Form(..., max_length=MAX_OPTIONS_BYTES),
):
    """Irreversible: draws widget and annotation appearances into the page and removes them."""
    content = await read_api_upload(file)
    settings = parse_options(options, FlattenOptions)
    with pdf_errors():
        output, fields, annotations = PdfFlattenEngine.flatten(
            content, settings.scope, settings.acknowledge_signature_loss)
        pages = count_pages(output)
    return pdf_response(output, f"{stem_of(file)}-flattened.pdf", pages, {
        "X-OfficeKit-Flattened-Fields": str(fields),
        "X-OfficeKit-Flattened-Annotations": str(annotations),
    })
