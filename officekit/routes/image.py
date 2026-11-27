"""Image slice routes (I06-I07, I10-I12, I14-I20), mounted by ``app.py`` through ``officekit.routes``.

Every route is a ``POST`` that derives an unstored result, so the success status is 200.
Errors share one body shape, ``{"detail": "<fixed message>", "code": "<CODE>"}``, produced by
``_guarded``. Caps are checked before parsing: ``BODY_LIMITS`` (P-036) bounds each request
before multipart parsing, and the JSON-in-form fields are bounded before ``json.loads``.
Image bytes are never logged, stored or echoed in an error.
"""

from __future__ import annotations

import functools
import json
import os
import re
from typing import Annotated, Literal, Optional, Union

from fastapi import APIRouter, Body, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from officekit.engines.engine_conversion_errors import ConversionInputError
from officekit.engines.engine_file_converter import ImageOutputLimitError, ImageWorkLimitError
from officekit.engines.engine_file_responses import content_disposition_attachment
from officekit.engines.engine_image_compose import (
    COLLAGE_MAX_IMAGES,
    CONTACT_SHEET_MAX_FILES,
    CollageLayout,
    ContactSheetLayout,
    ImageComposeEngine,
    PLATFORMS,
)
from officekit.engines.engine_image_tools import (
    MAX_BATCH_FILES,
    MAX_DATA_URI_BINARY_BYTES,
    MAX_DATA_URI_CHARS as MAX_DATA_URI_CHARACTERS,
    ImageToolInputError,
    ImageToolsEngine,
    RenditionOp,
)
from officekit.engines.engine_uploads import UploadTooLargeError, read_bounded_upload
from officekit.routes.common import MAX_API_UPLOAD_BYTES, MAX_MULTIPART_OVERHEAD_BYTES

MIB = 1024 * 1024
MAX_UPLOAD_BYTES = MAX_API_UPLOAD_BYTES
MAX_DATA_URI_BODY_BYTES = 12 * MIB
MAX_CONTACT_SHEET_INPUT_BYTES = 128 * MIB
MAX_OPTION_BYTES = 16 * 1024
MAX_LAYOUT_BYTES = 4 * 1024
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"})
DATA_URI_EXTENSIONS = IMAGE_EXTENSIONS | {".svg"}
EXTENSION_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
    ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff", ".gif": "image/gif", ".svg": "image/svg+xml",
}
MEDIA_EXTENSIONS = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "application/pdf": "pdf", "application/zip": "zip",
}
HEX_COLOUR_PATTERN = r"^#[0-9A-F]{6}$"
PLATFORM_LIST_PATTERN = re.compile(r"^[a-z]+(,[a-z]+)*$")

BODY_LIMITS = {
    "/api/image-renditions": MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
    "/api/image-rendition-batches": MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
    "/api/image-metadata-reports": MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
    "/api/image-palettes": MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
    "/api/data-uris": MAX_DATA_URI_BINARY_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
    "/api/data-uri-images": MAX_DATA_URI_BODY_BYTES,
    "/api/icon-packs": MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
    "/api/image-collages": MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
    "/api/contact-sheets": MAX_CONTACT_SHEET_INPUT_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
    "/api/image-comparisons": MAX_UPLOAD_BYTES + MAX_MULTIPART_OVERHEAD_BYTES,
}

EXPOSE_HEADERS = ("X-OfficeKit-Image-Density", "X-OfficeKit-Upscaled-Sizes")

VALIDATION_DETAIL = "Request contains invalid or unsupported values."


def _binary(media_types: tuple[str, ...], headers: tuple[tuple[str, str], ...] = ()) -> dict:
    """Declare a binary 200 response and the success headers the contract names."""
    return {200: {
        "content": {media: {} for media in media_types},
        "headers": {name: {"description": text, "schema": {"type": "string"}} for name, text in headers},
    }}


class _CodedValidationRoute(APIRoute):
    """Framework 422s on these routes carry the stable code too. Other routes are unchanged."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def coded_handler(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                # The detail is fixed and the rejected input is never echoed (see app.py validation handler).
                return _error_response(422, VALIDATION_DETAIL, "INVALID_OPTIONS")

        return coded_handler


router = APIRouter(route_class=_CodedValidationRoute)


class _RouteError(Exception):
    def __init__(self, status_code: int, detail: str, code: str):
        super().__init__(code)
        self.status_code = status_code
        self.detail = detail
        self.code = code


def _error_response(status_code: int, detail: str, code: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail, "code": code})


def _guarded(handler):
    """Translate engine and upload errors into the shared {detail, code} body."""

    @functools.wraps(handler)
    async def wrapper(*args, **kwargs):
        try:
            return await handler(*args, **kwargs)
        except _RouteError as error:
            return _error_response(error.status_code, error.detail, error.code)
        except UploadTooLargeError:
            return _error_response(413, "The image exceeds the supported 64 MiB input limit.", "TOO_LARGE_INPUT")
        except ImageWorkLimitError:
            return _error_response(
                413, "The image requires too much processing; select fewer or smaller images.", "TOO_LARGE_WORK",
            )
        except ImageOutputLimitError:
            return _error_response(413, "The output exceeds the supported 64 MiB limit.", "TOO_LARGE_OUTPUT")
        except ImageToolInputError as error:
            return _error_response(error.status_code, error.public_message, error.code)
        except ConversionInputError:
            return _error_response(422, ConversionInputError.public_message, "INVALID_IMAGE")

    return wrapper


def _source_name(file: UploadFile) -> str:
    return (file.filename or "image").replace("\\", "/").rsplit("/", 1)[-1]


def _base_name(filename: str) -> str:
    return os.path.splitext(filename)[0] or "image"


def _require_extension(filename: str, allowed: frozenset[str]) -> None:
    if os.path.splitext(filename)[1].lower() not in allowed:
        raise _RouteError(415, "Choose a supported image file.", "UNSUPPORTED_MEDIA")


async def _read(file: UploadFile, limit: int, message: str) -> bytes:
    """Read one upload within the remaining budget. A zero budget accepts only an empty part."""
    if limit <= 0:
        if await file.read(1):
            raise _RouteError(413, message, "TOO_LARGE_INPUT")
        return b""
    try:
        return await read_bounded_upload(file, limit)
    except UploadTooLargeError as error:
        raise _RouteError(413, message, "TOO_LARGE_INPUT") from error


async def _read_all(files: list[UploadFile], budget: int, message: str) -> list[bytes]:
    """Read several uploads against one shared byte budget, in upload order."""
    contents = []
    total = 0
    for file in files:
        content = await _read(file, budget - total, message)
        total += len(content)
        contents.append(content)
    return contents


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _parse_options(raw: str, model, label: str, limit: int = MAX_OPTION_BYTES):
    """Bound, parse and validate a JSON-in-form field into a strict DTO."""
    _check_form_text(raw, limit, label)
    try:
        data = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
        return model.model_validate(data)
    except (ValueError, RecursionError, ValidationError):
        raise _RouteError(422, f"The {label} options are invalid.", "INVALID_OPTIONS") from None


def _check_form_text(raw: str, limit: int, label: str) -> None:
    if len(raw.encode("utf-8")) > limit:
        raise _RouteError(422, f"The {label} options are too large.", "INVALID_OPTIONS")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RotateOperation(_Strict):
    type: Literal["rotate"]
    degrees_cw: Literal[90, 180, 270]


class FlipOperation(_Strict):
    type: Literal["flip"]
    axis: Literal["horizontal", "vertical"]


class GrayscaleOperation(_Strict):
    type: Literal["grayscale"]


class AdjustOperation(_Strict):
    type: Literal["adjust"]
    brightness: int = Field(default=0, ge=-100, le=100)
    contrast: int = Field(default=0, ge=-100, le=100)
    saturation: int = Field(default=0, ge=-100, le=100)


class BorderOperation(_Strict):
    type: Literal["border"]
    width: int = Field(ge=0, le=2000)
    corner_radius: int = Field(default=0, ge=0, le=5000)
    fill: str = Field(default="#FFFFFF", pattern=HEX_COLOUR_PATTERN)
    fill_opacity: int = Field(default=100, ge=0, le=100)


class DensityOperation(_Strict):
    type: Literal["density"]
    x: int = Field(ge=1, le=2400)
    y: int = Field(ge=1, le=2400)
    unit: Literal["inch", "cm"]


RenditionOperation = Annotated[
    Union[RotateOperation, FlipOperation, GrayscaleOperation, AdjustOperation, BorderOperation, DensityOperation],
    Field(discriminator="type"),
]


class RenditionRequest(_Strict):
    operations: list[RenditionOperation] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_density_position(self):
        densities = [index for index, op in enumerate(self.operations) if op.type == "density"]
        if len(densities) > 1 or (densities and densities[0] != len(self.operations) - 1):
            raise ValueError("density must be used at most once and must be the last operation")
        return self


class CollageRequest(_Strict):
    columns: int = Field(ge=1, le=10)
    cell_width: int = Field(ge=16, le=4000)
    cell_height: int = Field(ge=16, le=4000)
    fit: Literal["contain", "cover"]
    gap: int = Field(ge=0, le=200)
    padding: int = Field(ge=0, le=400)
    background: str = Field(pattern=r"^(#[0-9A-F]{6}|transparent)$")
    format: Literal["png", "jpeg", "webp"]


class ContactSheetRequest(_Strict):
    page: Literal["a4", "letter"]
    orientation: Literal["portrait", "landscape"]
    columns: int = Field(ge=1, le=10)
    rows: int = Field(ge=1, le=20)
    show_names: bool = True
    format: Literal["pdf", "png-zip"]
    preview_first_page: bool = False


class DataUriDecodeRequest(_Strict):
    data_uri: str = Field(max_length=MAX_DATA_URI_CHARACTERS)


class MetadataGroupEntry(BaseModel):
    group: Literal["date", "camera", "exposure", "image", "location"]
    tag: str
    label: str
    value: str = Field(max_length=512)
    status: Literal["present", "missing", "unsupported", "malformed"]


class MetadataLocation(BaseModel):
    present: bool
    withheld: bool
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    altitude_m: Optional[float] = None


class MetadataReport(BaseModel):
    format: str
    width: int
    height: int
    frames: int
    groups: list[MetadataGroupEntry] = Field(max_length=256)
    location: MetadataLocation
    has_icc: bool
    has_xmp: bool
    has_iptc: bool


class PaletteSwatch(BaseModel):
    hex: str
    rgb: list[int] = Field(min_length=3, max_length=3)
    share: float
    pixels: int


class Palette(BaseModel):
    colors: list[PaletteSwatch]
    sampled_pixels: int
    excluded_transparent_pixels: int


class DataUri(BaseModel):
    mime: str
    byte_length: int
    data_uri_length: int
    data_uri: str


class ComparisonSize(BaseModel):
    w: int
    h: int


class Comparison(BaseModel):
    a: ComparisonSize
    b: ComparisonSize
    comparable: bool
    reason: Optional[Literal["size_mismatch"]] = None
    scaled_b: bool
    threshold: int
    compared_pixels: Optional[int] = None
    changed_pixels: Optional[int] = None
    changed_ratio: Optional[float] = None
    max_channel_delta: Optional[int] = None
    mean_abs_delta: Optional[float] = None
    changed_bbox: Optional[list[int]] = None
    profiles_differ: bool
    difference_png: Optional[str] = None


def _engine_operation(operation) -> RenditionOp:
    if operation.type == "rotate":
        return RenditionOp("rotate", degrees_cw=operation.degrees_cw)
    if operation.type == "flip":
        return RenditionOp("flip", axis=operation.axis)
    if operation.type == "grayscale":
        return RenditionOp("grayscale")
    if operation.type == "adjust":
        return RenditionOp(
            "adjust", brightness=operation.brightness, contrast=operation.contrast, saturation=operation.saturation,
        )
    if operation.type == "border":
        return RenditionOp(
            "border", width=operation.width, corner_radius=operation.corner_radius,
            fill=operation.fill, fill_opacity=operation.fill_opacity,
        )
    return RenditionOp("density", x=operation.x, y=operation.y, unit=operation.unit)


def _density_header(density) -> str:
    x, y, unit = density
    return f"{x:g},{y:g},{unit}"


def _attachment(name: str, media_type: str, content: bytes, **headers) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": content_disposition_attachment(name), **headers},
    )


@router.post("/api/image-renditions", responses=_binary(("image/*",), (
    ("X-OfficeKit-Image-Width", "Pixel width of the rendition."),
    ("X-OfficeKit-Image-Height", "Pixel height of the rendition."),
    ("X-OfficeKit-Image-Density", "Density tag written, when a density operation ran."),
)))
@_guarded
async def api_image_rendition(
    file: UploadFile = File(...),
    operations: str = Form(...),
    output_format: Literal["same", "png", "jpeg", "webp"] = Form("same", alias="format"),
    quality: Optional[int] = Form(None, ge=1, le=100),
    preview_max_edge: Optional[int] = Form(None, ge=64, le=2048),
):
    """Apply a bounded list of rotate, flip, grayscale, adjust, border and density operations."""
    filename = _source_name(file)
    _require_extension(filename, IMAGE_EXTENSIONS)
    request = _parse_options(operations, RenditionRequest, "rendition")
    content = await _read(file, MAX_UPLOAD_BYTES, "The image exceeds the supported 64 MiB input limit.")
    rendition = ImageToolsEngine.render_rendition(
        content,
        [_engine_operation(operation) for operation in request.operations],
        output_format,
        quality=quality,
        preview_max_edge=preview_max_edge,
    )
    headers = {
        "X-OfficeKit-Image-Width": str(rendition.width),
        "X-OfficeKit-Image-Height": str(rendition.height),
    }
    if rendition.density is not None:
        headers["X-OfficeKit-Image-Density"] = _density_header(rendition.density)
    return _attachment(
        f"{_base_name(filename)}_edited.{rendition.extension}", rendition.media_type, rendition.content, **headers,
    )


@router.post("/api/image-rendition-batches", responses={200: {"content": {"application/zip": {}}}})
@_guarded
async def api_image_rendition_batch(
    files: list[UploadFile] = File(...),
    operations: str = Form(...),
    output_format: Literal["same", "png", "jpeg", "webp"] = Form("same", alias="format"),
    quality: Optional[int] = Form(None, ge=1, le=100),
):
    """Apply the same operations to 1-50 images and return a bounded ZIP."""
    if not files:
        raise _RouteError(422, "Choose at least one image.", "INVALID_OPTIONS")
    if len(files) > MAX_BATCH_FILES:
        raise _RouteError(413, "A batch can contain at most 50 images.", "TOO_LARGE_INPUT")
    for file in files:
        _require_extension(_source_name(file), IMAGE_EXTENSIONS)
    request = _parse_options(operations, RenditionRequest, "rendition")
    contents = await _read_all(files, MAX_UPLOAD_BYTES, "The image batch exceeds the supported 64 MiB input limit.")
    batch = [(_source_name(file), content) for file, content in zip(files, contents)]
    archive = ImageToolsEngine.render_rendition_batch(
        batch, [_engine_operation(operation) for operation in request.operations], output_format, quality=quality,
    )
    return _attachment("edited_images.zip", "application/zip", archive)


@router.post("/api/image-metadata-reports", response_model=MetadataReport)
@_guarded
async def api_image_metadata_report(
    file: UploadFile = File(...),
    include_location: bool = Form(False),
):
    """Describe EXIF fields. Coordinates are returned only when the caller asks for them."""
    _require_extension(_source_name(file), IMAGE_EXTENSIONS)
    content = await _read(file, MAX_UPLOAD_BYTES, "The image exceeds the supported 64 MiB input limit.")
    return ImageToolsEngine.metadata_report(content, include_location=include_location)


@router.post("/api/image-palettes", response_model=Palette)
@_guarded
async def api_image_palette(
    file: UploadFile = File(...),
    count: int = Form(6, ge=1, le=12),
    alpha_threshold: int = Form(128, ge=1, le=255),
):
    """Return deterministic dominant colours for the first frame."""
    _require_extension(_source_name(file), IMAGE_EXTENSIONS)
    content = await _read(file, MAX_UPLOAD_BYTES, "The image exceeds the supported 64 MiB input limit.")
    return ImageToolsEngine.palette(content, count=count, alpha_threshold=alpha_threshold)


@router.post("/api/data-uris", response_model=DataUri)
@_guarded
async def api_data_uri_encode(file: UploadFile = File(...)):
    """Encode an image (including SVG) as a base64 data URI, with its MIME checked against its bytes."""
    filename = _source_name(file)
    _require_extension(filename, DATA_URI_EXTENSIONS)
    declared = EXTENSION_MIME[os.path.splitext(filename)[1].lower()]
    content = await _read(
        file, MAX_DATA_URI_BINARY_BYTES, "The image exceeds the supported 8 MiB binary limit.",
    )
    return ImageToolsEngine.encode_data_uri(content, declared)


@router.post("/api/data-uri-images", responses=_binary(("image/*",), (
    ("X-Content-Type-Options", "Always nosniff."),
)))
@_guarded
async def api_data_uri_decode(payload: DataUriDecodeRequest = Body(...)):
    """Decode an image data URI to an attachment. Never previewed; SVG is served as a download."""
    decoded, mime = ImageToolsEngine.decode_data_uri(payload.data_uri)
    extension = MEDIA_EXTENSIONS.get(mime) or mime.split("/", 1)[1].replace("+xml", "")
    return _attachment(
        f"decoded.{extension}", mime, decoded, **{"X-Content-Type-Options": "nosniff"},
    )


def _platform_list(raw: str) -> list[str]:
    _check_form_text(raw, 64, "platform")
    if not PLATFORM_LIST_PATTERN.match(raw):
        raise _RouteError(422, "Choose one to three platforms.", "INVALID_OPTIONS")
    platforms = raw.split(",")
    if not 1 <= len(platforms) <= len(PLATFORMS) or len(set(platforms)) != len(platforms):
        raise _RouteError(422, "Choose one to three different platforms.", "INVALID_OPTIONS")
    if any(platform not in PLATFORMS for platform in platforms):
        raise _RouteError(422, "Choose web, windows or macos.", "INVALID_OPTIONS")
    return platforms


@router.post("/api/icon-packs", responses=_binary(("application/zip",), (
    ("X-OfficeKit-Upscaled-Sizes", "Comma-separated icon sizes that were enlarged from the source."),
)))
@_guarded
async def api_icon_pack(
    file: UploadFile = File(...),
    platforms: str = Form(...),
    fit: Literal["pad", "crop"] = Form("pad"),
):
    """Build web, Windows and macOS icon sets in one ZIP. Upscaled sizes are disclosed in a header."""
    filename = _source_name(file)
    _require_extension(filename, IMAGE_EXTENSIONS)
    selected = _platform_list(platforms)
    content = await _read(file, MAX_UPLOAD_BYTES, "The image exceeds the supported 64 MiB input limit.")
    archive, upscaled = ImageComposeEngine.build_icon_pack(content, selected, fit)
    return _attachment(
        f"{_base_name(filename)}_icons.zip",
        "application/zip",
        archive,
        **{"X-OfficeKit-Upscaled-Sizes": ",".join(str(size) for size in upscaled)},
    )


@router.post("/api/image-collages", responses=_binary(("image/*",), (
    ("X-OfficeKit-Image-Width", "Canvas width in pixels."),
    ("X-OfficeKit-Image-Height", "Canvas height in pixels."),
)))
@_guarded
async def api_image_collage(
    files: list[UploadFile] = File(...),
    layout: str = Form(...),
    preview_max_edge: Optional[int] = Form(None, ge=64, le=2048),
):
    """Compose 2-50 images in upload order. The canvas is checked from the layout before any decode."""
    if not 2 <= len(files) <= COLLAGE_MAX_IMAGES:
        raise _RouteError(422, "Choose between 2 and 50 images.", "INVALID_OPTIONS")
    for file in files:
        _require_extension(_source_name(file), IMAGE_EXTENSIONS)
    request = _parse_options(layout, CollageRequest, "collage", MAX_LAYOUT_BYTES)
    collage = CollageLayout(
        columns=request.columns, cell_width=request.cell_width, cell_height=request.cell_height,
        fit=request.fit, gap=request.gap, padding=request.padding,
        background=request.background, format=request.format,
    )
    ImageComposeEngine.collage_canvas(len(files), collage)
    contents = await _read_all(files, MAX_UPLOAD_BYTES, "The image batch exceeds the supported 64 MiB input limit.")
    image, media_type, (width, height) = ImageComposeEngine.build_collage(
        contents, collage, preview_max_edge=preview_max_edge,
    )
    extension = MEDIA_EXTENSIONS[media_type]
    return _attachment(
        f"collage.{extension}", media_type, image,
        **{"X-OfficeKit-Image-Width": str(width), "X-OfficeKit-Image-Height": str(height)},
    )


@router.post("/api/contact-sheets", responses=_binary(("application/pdf", "application/zip", "image/png"), (
    ("X-OfficeKit-Page-Count", "Number of contact-sheet pages, including every page of a preview request."),
)))
@_guarded
async def api_contact_sheet(
    files: list[UploadFile] = File(...),
    sheet: str = Form(...),
):
    """Paginate 1-200 thumbnails as a PDF or a ZIP of PNG pages. Page count is in a header."""
    if not 1 <= len(files) <= CONTACT_SHEET_MAX_FILES:
        raise _RouteError(422, "Choose between 1 and 200 images.", "INVALID_OPTIONS")
    for file in files:
        _require_extension(_source_name(file), IMAGE_EXTENSIONS)
    request = _parse_options(sheet, ContactSheetRequest, "contact sheet", MAX_LAYOUT_BYTES)
    layout = ContactSheetLayout(
        page=request.page, orientation=request.orientation, columns=request.columns,
        rows=request.rows, show_names=request.show_names, format=request.format,
    )
    contents = await _read_all(
        files, MAX_CONTACT_SHEET_INPUT_BYTES, "The contact sheet inputs exceed the supported 128 MiB limit.",
    )
    named = [(_source_name(file), content) for file, content in zip(files, contents)]
    if request.preview_first_page:
        output, media_type, pages = ImageComposeEngine.build_contact_sheet(named, layout, first_page_only=True)
        return Response(content=output, media_type=media_type, headers={"X-OfficeKit-Page-Count": str(pages)})
    output, media_type, pages = ImageComposeEngine.build_contact_sheet(named, layout)
    extension = MEDIA_EXTENSIONS[media_type]
    return _attachment(
        f"contact-sheet.{extension}", media_type, output,
        **{"X-OfficeKit-Page-Count": str(pages)},
    )


@router.post("/api/image-comparisons", response_model=Comparison)
@_guarded
async def api_image_comparison(
    image_a: UploadFile = File(...),
    image_b: UploadFile = File(...),
    alignment: Literal["none", "scale-b-to-a"] = Form("none"),
    threshold: int = Form(0, ge=0, le=255),
):
    """Compare two images at a stated threshold. Results are counts, never a claim of identity."""
    _require_extension(_source_name(image_a), IMAGE_EXTENSIONS)
    _require_extension(_source_name(image_b), IMAGE_EXTENSIONS)
    content_a = await _read(image_a, MAX_UPLOAD_BYTES, "The images exceed the supported 64 MiB input limit.")
    content_b = await _read(
        image_b, MAX_UPLOAD_BYTES - len(content_a), "The images exceed the supported 64 MiB input limit.",
    )
    return ImageToolsEngine.compare(content_a, content_b, alignment=alignment, threshold=threshold)
