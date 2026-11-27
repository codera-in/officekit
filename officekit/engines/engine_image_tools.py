"""Image tools engine: bounded renditions, metadata, palette, data URIs and comparison.

Every decoder entry point checks header dimensions and frame counts before any
pixel is loaded (P-165, P-047), budgets cumulative work (P-040), and bounds
encoded output. Limits are read from ``FileConverterEngine`` so one number
changes everywhere; module constants here are read at call time so tests can
patch them.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
import unicodedata
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Sequence

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageOps, ImageSequence, UnidentifiedImageError
from PIL import JpegImagePlugin

from officekit.engines.engine_colors import ColorConverterEngine
from officekit.engines.engine_conversion_errors import ConversionInputError
from officekit.engines.engine_file_converter import (
    FileConverterEngine,
    ImageOutputLimitError,
    ImageWorkLimitError,
    _BoundedImageBuffer,
)
from officekit.engines.engine_similar_images import SimilarImagePixelBudget, SimilarImagePixelBudgetError

FRAME_PIXELS = FileConverterEngine.MAX_RESIZE_FRAME_PIXELS
TOTAL_PIXELS = FileConverterEngine.MAX_RESIZE_TOTAL_PIXELS
MAX_FRAMES = FileConverterEngine.MAX_RESIZE_FRAMES
MAX_SIDE = FileConverterEngine.MAX_RESIZE_DIMENSION
MAX_BATCH_FILES = FileConverterEngine.MAX_RESIZE_BATCH_FILES
MAX_RENDITION_WORK_PIXELS = 400_000_000
MAX_OPERATIONS = 8
MAX_DATA_URI_BINARY_BYTES = 8 * 1024 * 1024
MAX_DATA_URI_CHARS = 11_184_900
MAX_JPEG_SEGMENT_PAYLOAD = 65_533
PALETTE_SAMPLE_EDGE = 256
DATA_URI_MIME_TYPES = frozenset({
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp", "image/tiff", "image/svg+xml",
})
DATA_URI_PATTERN = re.compile(r"^data:image/(png|jpeg|webp|gif|bmp|tiff|svg\+xml);base64,([A-Za-z0-9+/]*={0,2})\Z")
SVG_ROOT = re.compile(
    r"\s*(<\?xml[^>]*\?>\s*)?((<!--.*?-->|<!DOCTYPE[^>]*>)\s*)*<svg[\s>]", re.DOTALL,
)

ACCEPTED_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "BMP", "TIFF", "GIF"})
CLOCKWISE_TRANSPOSE = {
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}
FLIP_TRANSPOSE = {
    "horizontal": Image.Transpose.FLIP_LEFT_RIGHT,
    "vertical": Image.Transpose.FLIP_TOP_BOTTOM,
}
OUTPUT_EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "BMP": "bmp", "TIFF": "tiff", "GIF": "gif"}
MEDIA_TYPES = {
    "JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp",
    "BMP": "image/bmp", "TIFF": "image/tiff", "GIF": "image/gif",
}
CM_PER_INCH = 2.54
HEX_COLOUR = re.compile(r"^#[0-9A-F]{6}$")
JPEG_SOI = b"\xff\xd8"
JPEG_SOS = 0xDA
JPEG_APP0 = 0xE0
JPEG_APP1 = 0xE1
EXIF_HEADER = b"Exif\x00\x00"
EXIF_ORIENTATION = 0x0112
EXIF_X_RESOLUTION = 0x011A
EXIF_Y_RESOLUTION = 0x011B
EXIF_RESOLUTION_UNIT = 0x0128

PUBLIC_MESSAGES = {
    "INVALID_IMAGE": "The image file is invalid or cannot be decoded.",
    "UNSUPPORTED_FORMAT": "Choose a supported image file.",
    "INVALID_OPERATION": "The requested image operation is invalid.",
    "DENSITY_UNSUPPORTED": "This output format cannot store the requested density.",
    "CORNER_RADIUS_TOO_LARGE": "The corner radius is larger than half the bordered image.",
    "NO_OPAQUE_PIXELS": "The image has no opaque pixels to sample.",
    "CANVAS_TOO_LARGE": "The requested layout is larger than the supported canvas.",
    "MIME_MISMATCH": "The file contents do not match its image type.",
    "INVALID_DATA_URI": "The data URI is not a valid base64 image.",
    "TOO_LARGE_BINARY": "The image exceeds the supported 8 MiB binary limit.",
}


class ImageToolInputError(ConversionInputError):
    """Invalid or unsupported image input, with a stable machine code."""

    def __init__(self, code: str = "INVALID_IMAGE"):
        super().__init__()
        if code not in PUBLIC_MESSAGES:
            code = "INVALID_IMAGE"
        self.code = code
        self.public_message = PUBLIC_MESSAGES[code]
        self.status_code = 413 if code.startswith("TOO_LARGE") else 422

    def __str__(self) -> str:
        return self.public_message


@dataclass(frozen=True)
class RenditionOp:
    """One rendition step. Only the fields named by ``kind`` are read."""

    kind: str
    degrees_cw: int = 0
    axis: str = ""
    brightness: int = 0
    contrast: int = 0
    saturation: int = 0
    width: int = 0
    corner_radius: int = 0
    fill: str = "#FFFFFF"
    fill_opacity: int = 100
    x: int = 0
    y: int = 0
    unit: str = ""


@dataclass(frozen=True)
class Rendition:
    content: bytes
    extension: str
    media_type: str
    width: int
    height: int
    density: tuple[float, float, str] | None
    warnings: tuple[str, ...]


def _invalid_operation() -> ImageToolInputError:
    return ImageToolInputError("INVALID_OPERATION")


def validate_operations(operations: Sequence[RenditionOp]) -> None:
    """Re-check every operation at the engine boundary, not only in the route DTO."""
    if not 1 <= len(operations) <= MAX_OPERATIONS:
        raise _invalid_operation()
    for index, op in enumerate(operations):
        if op.kind == "rotate":
            if op.degrees_cw not in CLOCKWISE_TRANSPOSE:
                raise _invalid_operation()
        elif op.kind == "flip":
            if op.axis not in FLIP_TRANSPOSE:
                raise _invalid_operation()
        elif op.kind == "grayscale":
            continue
        elif op.kind == "adjust":
            for value in (op.brightness, op.contrast, op.saturation):
                if type(value) is not int or not -100 <= value <= 100:
                    raise _invalid_operation()
        elif op.kind == "border":
            if type(op.width) is not int or not 0 <= op.width <= 2000:
                raise _invalid_operation()
            if type(op.corner_radius) is not int or not 0 <= op.corner_radius <= 5000:
                raise _invalid_operation()
            if not isinstance(op.fill, str) or not HEX_COLOUR.match(op.fill):
                raise _invalid_operation()
            if type(op.fill_opacity) is not int or not 0 <= op.fill_opacity <= 100:
                raise _invalid_operation()
        elif op.kind == "density":
            if index != len(operations) - 1:
                raise _invalid_operation()
            if type(op.x) is not int or type(op.y) is not int:
                raise _invalid_operation()
            if not (1 <= op.x <= 2400 and 1 <= op.y <= 2400) or op.unit not in {"inch", "cm"}:
                raise _invalid_operation()
        else:
            raise _invalid_operation()


def _open_source(content: bytes) -> Image.Image:
    if not isinstance(content, bytes):
        raise ImageToolInputError("INVALID_IMAGE")
    try:
        source = Image.open(io.BytesIO(content))
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError):
        raise ImageToolInputError("INVALID_IMAGE") from None
    if (source.format or "").upper() not in ACCEPTED_FORMATS:
        source.close()
        raise ImageToolInputError("UNSUPPORTED_FORMAT")
    return source


@contextmanager
def decoding():
    """Map pixel-decoding failures (truncated or corrupt data passes Image.open) to INVALID_IMAGE."""
    try:
        yield
    except ImageToolInputError:
        raise
    except (OSError, ValueError, SyntaxError, EOFError, Image.DecompressionBombError):
        raise ImageToolInputError("INVALID_IMAGE") from None


def _check_geometry(width: int, height: int, running_total: int) -> int:
    """Reject from header dimensions alone, before any pixel is decoded (P-165)."""
    if width <= 0 or height <= 0:
        raise ImageToolInputError("INVALID_IMAGE")
    if width > MAX_SIDE or height > MAX_SIDE or width * height > FRAME_PIXELS:
        raise ImageWorkLimitError()
    total = running_total + width * height
    if total > TOTAL_PIXELS:
        raise ImageWorkLimitError()
    return total


def _check_header_sides(width: int, height: int) -> None:
    """Header-only sanity for reads that decode no pixels: no pixel budget applies."""
    if width <= 0 or height <= 0:
        raise ImageToolInputError("INVALID_IMAGE")
    if width > MAX_SIDE or height > MAX_SIDE:
        raise ImageWorkLimitError()


def _normalise_mode(frame: Image.Image) -> tuple[Image.Image, bool]:
    """Return an RGB, RGBA, L or LA frame, and whether a colour conversion was needed."""
    if frame.mode in {"RGB", "RGBA", "L", "LA"}:
        return frame, False
    if frame.mode == "1":
        return frame.convert("L"), False
    if frame.mode == "P":
        # Palette expansion keeps the pixels in the profile's colour space, so the profile still applies.
        return frame.convert("RGBA" if "transparency" in frame.info else "RGB"), False
    has_alpha = frame.mode in {"RGBA", "LA", "PA"}
    return frame.convert("RGBA" if has_alpha else "RGB"), True


def _exif_from_bytes(raw: bytes | None) -> Image.Exif:
    exif = Image.Exif()
    if raw:
        try:
            exif.load(raw)
        except (OSError, SyntaxError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError):
            return Image.Exif()
    return exif


@dataclass
class _Frames:
    image_format: str
    original_size: tuple[int, int]
    frames: list
    durations: list
    info: dict
    exif_raw: bytes | None
    icc_profile: bytes | None
    quantization: dict | None
    sampling: int | None
    warnings: list


def _load_frames(source: Image.Image, draft_size: tuple[int, int] | None = None) -> _Frames:
    """Validate every frame's header geometry, then decode each frame once."""
    frame_count = getattr(source, "n_frames", 1)
    if frame_count < 1:
        raise ImageToolInputError("INVALID_IMAGE")
    if frame_count > MAX_FRAMES:
        raise ImageWorkLimitError()
    info = dict(source.info)
    warnings: list[str] = []
    frames: list[Image.Image] = []
    durations: list = []
    total = 0
    converted_any = False
    original_size = source.size
    quantization = getattr(source, "quantization", None)
    sampling = JpegImagePlugin.get_sampling(source) if source.format == "JPEG" else None
    with decoding():
        for frame in ImageSequence.Iterator(source):
            total = _check_geometry(frame.width, frame.height, total)
            if draft_size is not None and not frames and source.format == "JPEG":
                frame.draft("RGB", draft_size)
            frame.load()
            durations.append(frame.info.get("duration", info.get("duration")))
            normalised, converted = _normalise_mode(ImageOps.exif_transpose(frame.copy()))
            if converted:
                converted_any = True
                normalised.info.pop("icc_profile", None)  # Pillow's save reads frame.info as well
                if "color_mode_converted" not in warnings:
                    warnings.append("color_mode_converted")
            frames.append(normalised)
    if not frames:
        raise ImageToolInputError("INVALID_IMAGE")
    return _Frames(
        image_format=(source.format or "").upper(),
        original_size=original_size,
        frames=frames,
        durations=durations,
        info=info,
        exif_raw=info.get("exif"),
        # A profile describes the stored pixels; CMYK and other converted pixels no longer match it, so it is dropped.
        icc_profile=None if converted_any else info.get("icc_profile"),
        quantization=quantization,
        sampling=sampling,
        warnings=warnings,
    )


def _reserve(budget: SimilarImagePixelBudget, pixels: int) -> None:
    try:
        budget.reserve(pixels)
    except SimilarImagePixelBudgetError:
        raise ImageWorkLimitError() from None


def _hex_rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def _apply_adjust(frame: Image.Image, op: RenditionOp) -> Image.Image:
    if frame.mode == "LA":
        frame = frame.convert("RGBA")
    elif frame.mode == "L":
        frame = frame.convert("RGB")
    alpha = None
    if frame.mode == "RGBA":
        red, green, blue, alpha = frame.split()
        colour = Image.merge("RGB", (red, green, blue))
    else:
        colour = frame
    if op.brightness:
        colour = ImageEnhance.Brightness(colour).enhance(1 + op.brightness / 100)
    if op.contrast:
        colour = ImageEnhance.Contrast(colour).enhance(1 + op.contrast / 100)
    if op.saturation:
        colour = ImageEnhance.Color(colour).enhance(1 + op.saturation / 100)
    if alpha is None:
        return colour
    red, green, blue = colour.split()
    return Image.merge("RGBA", (red, green, blue, alpha))


def _apply_border(frame: Image.Image, op: RenditionOp, factor: float) -> tuple[Image.Image, tuple[int, int, int, int]]:
    width = round(op.width * factor)
    radius = round(op.corner_radius * factor)
    if frame.mode != "RGBA":
        frame = frame.convert("RGBA")
    canvas_width = frame.width + 2 * width
    canvas_height = frame.height + 2 * width
    if canvas_width > MAX_SIDE or canvas_height > MAX_SIDE:
        raise ImageWorkLimitError()
    if radius > min(canvas_width, canvas_height) / 2:
        raise ImageToolInputError("CORNER_RADIUS_TOO_LARGE")
    red, green, blue = _hex_rgb(op.fill)
    fill_alpha = round(op.fill_opacity * 255 / 100)
    canvas = Image.new("RGBA", (canvas_width, canvas_height), (red, green, blue, fill_alpha))
    canvas.paste(frame, (width, width))
    if radius > 0:
        mask = Image.new("L", (canvas_width, canvas_height), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, canvas_width - 1, canvas_height - 1), radius=radius, fill=255)
        canvas.putalpha(ImageChops.multiply(canvas.getchannel("A"), mask))
    return canvas, (red, green, blue, fill_alpha)


def _is_noop(op: RenditionOp) -> bool:
    if op.kind == "adjust":
        return not (op.brightness or op.contrast or op.saturation)
    if op.kind == "border":
        return op.width == 0 and op.corner_radius == 0
    return False


def _density_tuple(op: RenditionOp) -> tuple[float, float, str]:
    if op.unit == "inch":
        return float(op.x), float(op.y), "inch"
    return op.x * CM_PER_INCH, op.y * CM_PER_INCH, "inch"


def _resolve_output(source_format: str, output_format: str) -> str:
    if output_format == "same":
        if source_format not in ACCEPTED_FORMATS:
            raise ImageToolInputError("UNSUPPORTED_FORMAT")
        return source_format
    return {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}[output_format]


def _resized(frame: Image.Image, factor: float) -> Image.Image:
    size = (max(1, round(frame.width * factor)), max(1, round(frame.height * factor)))
    return frame if frame.size == size else frame.resize(size, Image.Resampling.LANCZOS)


def _render_pixels(loaded: _Frames, operations: Sequence[RenditionOp], preview_max_edge, budget):
    """Run every pixel operation on every frame. Returns (frames, border_fill)."""
    factor = 1.0
    if preview_max_edge is not None:
        factor = min(1.0, preview_max_edge / max(loaded.original_size))
    frames = loaded.frames
    if factor < 1.0:
        frames = [_resized(frame, factor) for frame in frames]
    border_fill = None
    for op in operations:
        if op.kind == "density" or _is_noop(op):
            continue
        stepped = []
        for frame in frames:
            if op.kind == "rotate":
                output = frame.transpose(CLOCKWISE_TRANSPOSE[op.degrees_cw])
            elif op.kind == "flip":
                output = frame.transpose(FLIP_TRANSPOSE[op.axis])
            elif op.kind == "grayscale":
                output = frame.convert("LA" if frame.mode in {"RGBA", "LA"} else "L")
                output.info.pop("icc_profile", None)
                loaded.icc_profile = None
            elif op.kind == "adjust":
                output = _apply_adjust(frame, op)
            else:
                output, border_fill = _apply_border(frame, op, factor)
            _reserve(budget, output.width * output.height)
            stepped.append(output)
        frames = stepped
    return frames, border_fill


def _encode_frames(loaded: _Frames, frames, target: str, quality, density, border_fill, warnings) -> bytes:
    output = _BoundedImageBuffer(FileConverterEngine.MAX_RESIZE_OUTPUT_BYTES)
    prepared = []
    for frame in frames:
        if target == "JPEG":
            if frame.mode in {"RGBA", "LA"}:
                background = Image.new("RGB", frame.size, border_fill[:3] if border_fill else (255, 255, 255))
                background.paste(frame.convert("RGBA"), mask=frame.convert("RGBA").getchannel("A"))
                frame = background
                if "alpha_flattened" not in warnings:
                    warnings.append("alpha_flattened")
            elif frame.mode != "RGB":
                frame = frame.convert("RGB")
        elif target == "WEBP" and frame.mode not in {"RGB", "RGBA"}:
            frame = frame.convert("RGBA" if frame.mode == "LA" else "RGB")
        elif target == "BMP" and frame.mode == "LA":
            frame = frame.convert("RGBA")
        prepared.append(frame)

    save_kwargs: dict = {}
    if loaded.icc_profile and target in {"JPEG", "PNG", "WEBP", "TIFF"}:
        save_kwargs["icc_profile"] = loaded.icc_profile
    if density is not None:
        dpi = (density[0], density[1])
        if target in {"JPEG", "PNG", "TIFF", "BMP"}:
            save_kwargs["dpi"] = dpi
    elif loaded.info.get("dpi") and target in {"JPEG", "PNG", "TIFF", "BMP"}:
        save_kwargs["dpi"] = loaded.info["dpi"]
    if target in {"JPEG", "PNG", "WEBP", "TIFF"} and loaded.exif_raw:
        exif = _exif_from_bytes(loaded.exif_raw)
        if EXIF_ORIENTATION in exif:
            del exif[EXIF_ORIENTATION]
        if density is not None:
            # The kept EXIF resolution must match the density tags written beside it (inches).
            exif[EXIF_X_RESOLUTION] = density[0]
            exif[EXIF_Y_RESOLUTION] = density[1]
            exif[EXIF_RESOLUTION_UNIT] = 2
        if len(exif):
            save_kwargs["exif"] = exif.tobytes()
    if target == "JPEG":
        if quality is None and loaded.image_format == "JPEG" and loaded.quantization:
            save_kwargs["qtables"] = loaded.quantization
            save_kwargs["subsampling"] = loaded.sampling
        save_kwargs["quality"] = quality if quality is not None else 90
    elif target == "WEBP":
        save_kwargs["quality"] = quality if quality is not None else 90
    if len(prepared) > 1:
        save_kwargs.update(save_all=True, append_images=prepared[1:])
        if target in {"GIF", "WEBP"}:
            if any(loaded.durations):
                save_kwargs["duration"] = [duration or 0 for duration in loaded.durations[: len(prepared)]]
            if loaded.info.get("loop") is not None:
                save_kwargs["loop"] = loaded.info["loop"]
    prepared[0].save(output, format=target, **save_kwargs)
    return output.getvalue()


def _jpeg_segments(content: bytes):
    """Yield (marker, payload) for every segment before the scan data (SOS)."""
    position = 2
    while True:
        if position + 4 > len(content) or content[position] != 0xFF:
            raise ImageToolInputError("INVALID_IMAGE")
        marker = content[position + 1]
        if marker == JPEG_SOS:
            return
        length = int.from_bytes(content[position + 2:position + 4], "big")
        if length < 2 or position + 2 + length > len(content):
            raise ImageToolInputError("INVALID_IMAGE")
        yield marker, content[position + 4:position + 2 + length]
        position += 2 + length


def _sos_offset(content: bytes) -> int:
    position = 2
    for marker, payload in _jpeg_segments(content):
        position += 4 + len(payload)
    return position


def _rewrite_jpeg_density(content: bytes, x: int, y: int, unit_code: int, exif: Image.Exif) -> bytes:
    """Rewrite JFIF and EXIF resolution bytes; the scan data after SOS is copied unchanged."""
    if content[:2] != JPEG_SOI:
        raise ImageToolInputError("INVALID_IMAGE")
    jfif = bytearray(b"JFIF\x00" + bytes([1, 2, 0]) + (1).to_bytes(2, "big") + (1).to_bytes(2, "big") + b"\x00\x00")
    others = []
    for marker, payload in _jpeg_segments(content):
        if marker == JPEG_APP0 and payload.startswith(b"JFIF\x00") and len(payload) >= 14:
            jfif = bytearray(payload[:14])
        elif marker == JPEG_APP1 and payload.startswith(EXIF_HEADER):
            continue
        else:
            others.append((marker, payload))
    jfif[7] = unit_code
    jfif[8:10] = x.to_bytes(2, "big")
    jfif[10:12] = y.to_bytes(2, "big")

    exif[EXIF_X_RESOLUTION] = x
    exif[EXIF_Y_RESOLUTION] = y
    exif[EXIF_RESOLUTION_UNIT] = 3 if unit_code == 2 else 2
    tiff = exif.tobytes()
    if tiff.startswith(EXIF_HEADER):
        tiff = tiff[len(EXIF_HEADER):]
    exif_payload = EXIF_HEADER + tiff
    if len(exif_payload) > MAX_JPEG_SEGMENT_PAYLOAD:
        raise ImageToolInputError("INVALID_IMAGE")

    body = bytearray(JPEG_SOI)
    body += bytes([0xFF, JPEG_APP0]) + (len(jfif) + 2).to_bytes(2, "big") + bytes(jfif)
    body += bytes([0xFF, JPEG_APP1]) + (len(exif_payload) + 2).to_bytes(2, "big") + exif_payload
    for marker, payload in others:
        body += bytes([0xFF, marker]) + (len(payload) + 2).to_bytes(2, "big") + payload
    body += content[_sos_offset(content):]
    if len(body) > FileConverterEngine.MAX_RESIZE_OUTPUT_BYTES:
        raise ImageOutputLimitError("Density output exceeds the supported limit.")
    return bytes(body)


METADATA_FIELDS = (
    ("date", "DateTimeOriginal", 0x9003, True, "Taken"),
    ("date", "DateTime", 0x0132, False, "Modified"),
    ("date", "DateTimeDigitized", 0x9004, True, "Digitised"),
    ("camera", "Make", 0x010F, False, "Make"),
    ("camera", "Model", 0x0110, False, "Model"),
    ("camera", "LensModel", 0xA434, True, "Lens"),
    ("exposure", "ExposureTime", 0x829A, True, "Exposure"),
    ("exposure", "FNumber", 0x829D, True, "Aperture"),
    ("exposure", "ISOSpeedRatings", 0x8827, True, "ISO"),
    ("exposure", "FocalLength", 0x920A, True, "Focal length"),
    ("image", "Orientation", 0x0112, False, "Orientation"),
    ("image", "ColorSpace", 0xA001, True, "Colour space"),
    ("image", "Artist", 0x013B, False, "Artist"),
    ("image", "ImageDescription", 0x010E, False, "Description"),
    ("image", "UserComment", 0x9286, True, "Comment"),
    ("image", "Software", 0x0131, False, "Software"),
)
LOCATION_FIELDS = (("GPSLatitude", "Latitude"), ("GPSLongitude", "Longitude"), ("GPSAltitude", "Altitude"))
EXIF_IFD_POINTER = 0x8769
GPS_IFD_POINTER = 0x8825
MAX_METADATA_VALUE_CHARS = 512
USER_COMMENT_TAG = 0x9286


def _sub_ifd(exif: Image.Exif, pointer: int) -> tuple[dict | None, bool]:
    """Return (ifd, readable). An absent pointer is readable and empty; an unreadable one is not."""
    if pointer not in exif:
        return {}, True
    try:
        ifd = exif.get_ifd(pointer)
    except (OSError, SyntaxError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError, OverflowError):
        return None, False
    if not ifd:
        return None, False
    return ifd, True


def _format_number(value) -> str:
    if isinstance(value, int):
        return str(value)
    denominator = getattr(value, "denominator", None)
    numerator = getattr(value, "numerator", None)
    if denominator is not None and numerator is not None:
        if denominator == 1:
            return str(numerator)
    return f"{float(value):g}"


def _clean_text(text: str) -> str:
    cleaned = "".join(character for character in unicodedata.normalize("NFC", text) if unicodedata.category(character) != "Cc")
    return cleaned.strip()[:MAX_METADATA_VALUE_CHARS]


def _decode_user_comment(value: bytes) -> tuple[str, str]:
    """Return (status, text) for an EXIF UserComment with its 8-byte charset prefix."""
    charset, payload = value[:8], value[8:]
    if charset == b"ASCII\x00\x00\x00":
        return "present", payload.decode("ascii")
    if charset == b"UNICODE\x00":
        if payload[:2] == b"\xff\xfe":
            return "present", payload[2:].decode("utf-16-le")
        if payload[:2] == b"\xfe\xff":
            return "present", payload[2:].decode("utf-16-be")
        return "present", payload.decode("utf-16-be")
    return "unsupported", ""


def _utf8_if_mojibake(text: str) -> str:
    """Pillow decodes ASCII-typed EXIF bytes as latin-1; writers often store UTF-8 there."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _format_exif_value(tag: int, value) -> tuple[str, str]:
    if value is None:
        return "missing", ""
    try:
        if isinstance(value, bytes):
            if tag == USER_COMMENT_TAG:
                status, text = _decode_user_comment(value)
                if status != "present":
                    return status, ""
            else:
                text = value.decode("utf-8")
        elif isinstance(value, str):
            text = _utf8_if_mojibake(value)
        elif isinstance(value, tuple):
            text = " ".join(_format_number(item) for item in value)
        elif isinstance(value, (int, float)) or hasattr(value, "numerator"):
            text = _format_number(value)
        else:
            return "unsupported", ""
    except (UnicodeDecodeError, ValueError, ZeroDivisionError, TypeError, OverflowError):
        return "malformed", ""
    text = _clean_text(text)
    return ("present", text) if text else ("missing", "")


def _dms_to_degrees(value, reference: str, limit: float) -> float:
    if not isinstance(value, tuple) or len(value) != 3:
        raise ValueError("coordinate is not degrees, minutes and seconds")
    degrees, minutes, seconds = (float(part) for part in value)
    result = degrees + minutes / 60 + seconds / 3600
    if reference in {"S", "W"}:
        result = -result
    if abs(result) > limit:
        raise ValueError("coordinate is out of range")
    return result


def _location_report(gps: dict | None, include_location: bool):
    """Return (location object, group entries). Coordinates are emitted only when requested."""
    if gps is None:
        entries = [_location_entry(name, label, "malformed", "") for name, label in LOCATION_FIELDS]
        return {"present": False, "withheld": False}, entries
    try:
        latitude = _dms_to_degrees(gps.get(2), gps.get(1), 90.0)
        longitude = _dms_to_degrees(gps.get(4), gps.get(3), 180.0)
    except (ValueError, TypeError, ZeroDivisionError):
        present = False
        coordinate_status = "malformed" if (2 in gps or 4 in gps) else "missing"
        entries = [_location_entry(name, label, coordinate_status, "") for name, label in LOCATION_FIELDS[:2]]
        entries.append(_location_entry(LOCATION_FIELDS[2][0], LOCATION_FIELDS[2][1], "missing", ""))
        return {"present": present, "withheld": False}, entries

    altitude = None
    altitude_status = "missing"
    if 6 in gps:
        try:
            altitude = float(gps[6]) * (-1 if gps.get(5) in (1, b"\x01") else 1)
            altitude_status = "present"
        except (ZeroDivisionError, TypeError, ValueError):
            altitude_status = "malformed"
    entries = []
    if include_location:
        entries = [
            _location_entry("GPSLatitude", "Latitude", "present", f"{latitude:.6f}"),
            _location_entry("GPSLongitude", "Longitude", "present", f"{longitude:.6f}"),
            _location_entry(
                "GPSAltitude", "Altitude", altitude_status,
                f"{altitude:.2f}" if altitude_status == "present" else "",
            ),
        ]
        location = {"present": True, "withheld": False, "latitude": latitude, "longitude": longitude}
        if altitude_status == "present":
            location["altitude_m"] = altitude
        return location, entries
    return {"present": True, "withheld": True}, entries


def _location_entry(tag: str, label: str, status: str, value: str) -> dict:
    return {"group": "location", "tag": tag, "label": label, "value": value, "status": status}


COMPARE_ALIGNMENTS = frozenset({"none", "scale-b-to-a"})
COMPARE_DIFF_EDGE = 2048
COMPARE_FALLBACK_EDGE = 512
COMPARE_DATA_URI_CHAR_LIMIT = 16_000_000


def _comparison_frame(content: bytes, budget: SimilarImagePixelBudget) -> tuple[Image.Image, bytes | None]:
    """First frame, EXIF-transposed and RGBA, with no colour management (HLD compare rule)."""
    with _open_source(content) as source:
        _check_geometry(source.width, source.height, 0)
        _reserve(budget, source.width * source.height)
        icc_profile = source.info.get("icc_profile")
        with decoding():
            source.load()
            frame = ImageOps.exif_transpose(source).convert("RGBA")
    return frame, icc_profile


def _over_neutral(frame: Image.Image) -> Image.Image:
    """Composite an RGBA frame over opaque white."""
    return Image.alpha_composite(Image.new("RGBA", frame.size, (255, 255, 255, 255)), frame)


def _difference_data_uri(reference: Image.Image, changed_mask: Image.Image) -> str:
    """Heatmap: changed pixels in red over a faded copy of the first image, bounded in edge length."""
    faded = Image.blend(Image.new("RGB", reference.size, (255, 255, 255)), reference.convert("RGB"), 0.25)
    heatmap = Image.composite(Image.new("RGB", reference.size, (220, 30, 30)), faded, changed_mask)
    uri = ""
    for edge in (COMPARE_DIFF_EDGE, COMPARE_FALLBACK_EDGE):
        image = heatmap.copy()
        image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        output = _BoundedImageBuffer(FileConverterEngine.MAX_RESIZE_OUTPUT_BYTES)
        image.save(output, format="PNG")
        uri = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
        if len(uri) <= COMPARE_DATA_URI_CHAR_LIMIT:
            break
    return uri


class ImageToolsEngine:
    @staticmethod
    def render_rendition(
        content: bytes,
        operations: Sequence[RenditionOp],
        output_format: str,
        quality: int | None = None,
        preview_max_edge: int | None = None,
        work_budget: SimilarImagePixelBudget | None = None,
    ) -> Rendition:
        """Apply the operation list to every frame and encode one rendition."""
        validate_operations(operations)
        if output_format not in {"same", "png", "jpeg", "webp"}:
            raise _invalid_operation()
        if quality is not None and (type(quality) is not int or not 1 <= quality <= 100):
            raise _invalid_operation()
        if preview_max_edge is not None and (type(preview_max_edge) is not int or not 64 <= preview_max_edge <= 2048):
            raise _invalid_operation()
        budget = work_budget if work_budget is not None else SimilarImagePixelBudget(MAX_RENDITION_WORK_PIXELS)
        pixel_ops = [op for op in operations if op.kind != "density"]
        density_op = operations[-1] if operations[-1].kind == "density" else None
        if preview_max_edge is not None:
            density_op = None

        with _open_source(content) as source:
            target = _resolve_output(source.format.upper(), output_format)
            if preview_max_edge is not None:
                target = "PNG"
            if density_op is not None and target in {"WEBP", "GIF"}:
                raise ImageToolInputError("DENSITY_UNSUPPORTED")
            draft_size = (preview_max_edge, preview_max_edge) if preview_max_edge is not None else None
            loaded = _load_frames(source, draft_size=draft_size)

            if not any(not _is_noop(op) for op in pixel_ops) and density_op is not None and target == "JPEG" and loaded.image_format == "JPEG":
                exif = _exif_from_bytes(loaded.exif_raw)
                encoded = _rewrite_jpeg_density(
                    content, density_op.x, density_op.y, 1 if density_op.unit == "inch" else 2, exif,
                )
                width, height = loaded.original_size
                return Rendition(
                    encoded, OUTPUT_EXTENSIONS[target], MEDIA_TYPES[target], width, height,
                    _density_tuple(density_op), tuple(loaded.warnings),
                )

            if not any(not _is_noop(op) for op in pixel_ops):
                for frame in loaded.frames:
                    _reserve(budget, frame.width * frame.height)
            frames, border_fill = _render_pixels(loaded, pixel_ops, preview_max_edge, budget)
            warnings = list(loaded.warnings)
            density = _density_tuple(density_op) if density_op is not None else None
            encoded = _encode_frames(loaded, frames, target, quality, density, border_fill, warnings)
            width, height = frames[0].size
            return Rendition(
                encoded, OUTPUT_EXTENSIONS[target], MEDIA_TYPES[target], width, height, density, tuple(warnings),
            )

    @staticmethod
    def render_rendition_batch(
        files: Sequence[tuple[str, bytes]],
        operations: Sequence[RenditionOp],
        output_format: str,
        quality: int | None = None,
    ) -> bytes:
        """Render each file with one shared work budget into a bounded ZIP of safe names."""
        if not isinstance(files, (list, tuple)) or not 1 <= len(files) <= MAX_BATCH_FILES:
            raise _invalid_operation()
        budget = SimilarImagePixelBudget(MAX_RENDITION_WORK_PIXELS)
        output = _BoundedImageBuffer(FileConverterEngine.MAX_RESIZE_OUTPUT_BYTES)
        used_names: set[str] = set()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for source_name, source_bytes in files:
                base_name = source_name.replace("\\", "/").rsplit("/", 1)[-1]
                stem = base_name.rsplit(".", 1)[0] if "." in base_name else base_name
                stem = "".join(character for character in stem if character.isalnum() or character in " ._-")
                stem = stem.strip(" .")[:100] or "image"
                rendition = ImageToolsEngine.render_rendition(
                    source_bytes, operations, output_format, quality=quality, work_budget=budget,
                )
                candidate = f"{stem}_edited.{rendition.extension}"
                suffix = 2
                while candidate.casefold() in used_names:
                    candidate = f"{stem}_edited ({suffix}).{rendition.extension}"
                    suffix += 1
                used_names.add(candidate.casefold())
                archive.writestr(candidate, rendition.content)
        return output.getvalue()

    @staticmethod
    def metadata_report(content: bytes, include_location: bool = False) -> dict:
        """Describe EXIF fields by group. GPS is withheld unless the caller asks for it."""
        with _open_source(content) as source:
            frame_count = getattr(source, "n_frames", 1)
            if frame_count > MAX_FRAMES:
                raise ImageWorkLimitError()
            _check_header_sides(source.width, source.height)
            try:
                exif = source.getexif()
            except (OSError, SyntaxError, ValueError, KeyError, IndexError, TypeError, ZeroDivisionError):
                exif = Image.Exif()
            exif_ifd, exif_readable = _sub_ifd(exif, EXIF_IFD_POINTER)
            gps_ifd, gps_readable = _sub_ifd(exif, GPS_IFD_POINTER)

            groups = []
            for group, name, tag, in_exif_ifd, label in METADATA_FIELDS:
                if in_exif_ifd and not exif_readable:
                    status, value = "malformed", ""
                else:
                    source_ifd = exif_ifd if in_exif_ifd else exif
                    status, value = _format_exif_value(tag, source_ifd.get(tag))
                groups.append({"group": group, "tag": name, "label": label, "value": value, "status": status})

            location, location_entries = _location_report(gps_ifd if gps_readable else None, include_location)
            if include_location:
                groups.extend(location_entries)
            info = source.info
            return {
                "format": (source.format or "").upper(),
                "width": source.width,
                "height": source.height,
                "frames": frame_count,
                "groups": groups,
                "location": location,
                "has_icc": bool(info.get("icc_profile")),
                "has_xmp": "xmp" in info or "XML:com.adobe.xmp" in info,
                "has_iptc": "photoshop" in info,
            }

    @staticmethod
    def palette(content: bytes, count: int = 6, alpha_threshold: int = 128) -> dict:
        """Deterministic dominant colours of the first frame, with transparent pixels excluded."""
        if type(count) is not int or not 1 <= count <= 12:
            raise _invalid_operation()
        if type(alpha_threshold) is not int or not 1 <= alpha_threshold <= 255:
            raise _invalid_operation()
        with _open_source(content) as source:
            _check_geometry(source.width, source.height, 0)
            with decoding():
                image = source.convert("RGBA")
        image.thumbnail((PALETTE_SAMPLE_EDGE, PALETTE_SAMPLE_EDGE), Image.Resampling.BOX)
        data = image.tobytes()
        kept = bytearray()
        excluded = 0
        for offset in range(0, len(data), 4):
            if data[offset + 3] < alpha_threshold:
                excluded += 1
            else:
                kept += data[offset:offset + 3]
        kept_count = len(kept) // 3
        if kept_count == 0:
            raise ImageToolInputError("NO_OPAQUE_PIXELS")
        row = Image.frombytes("RGB", (kept_count, 1), bytes(kept))
        quantized = row.quantize(colors=count, method=Image.Quantize.MEDIANCUT, kmeans=0, dither=Image.Dither.NONE)
        flat_palette = quantized.getpalette() or []
        swatches = []
        for pixel_count, index in quantized.getcolors(maxcolors=kept_count):
            red, green, blue = flat_palette[3 * index:3 * index + 3]
            hex_value = ColorConverterEngine.convert(f"rgb({red}, {green}, {blue})", "rgb", "hex").upper()
            swatches.append({
                "hex": hex_value,
                "rgb": [red, green, blue],
                "share": round(pixel_count / kept_count, 4),
                "pixels": pixel_count,
            })
        swatches.sort(key=lambda swatch: (-swatch["pixels"], swatch["hex"]))
        return {
            "colors": swatches,
            "sampled_pixels": kept_count,
            "excluded_transparent_pixels": excluded,
        }

    @staticmethod
    def sniff_mime(content: bytes) -> str | None:
        """Identify an image by its signature. SVG is text with an svg root, never rasterised."""
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if content.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            return "image/webp"
        if content[:4] in (b"II*\x00", b"MM\x00*"):
            return "image/tiff"
        if content[:2] == b"BM" and len(content) >= 26:
            return "image/bmp"
        if len(content) <= MAX_DATA_URI_BINARY_BYTES:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                return None
            if SVG_ROOT.match(text):
                return "image/svg+xml"
        return None

    @staticmethod
    def encode_data_uri(content: bytes, declared_mime: str) -> dict:
        """Base64-encode an image whose sniffed type matches the declared one."""
        if not isinstance(content, bytes):
            raise ImageToolInputError("INVALID_IMAGE")
        if len(content) > MAX_DATA_URI_BINARY_BYTES:
            raise ImageToolInputError("TOO_LARGE_BINARY")
        if declared_mime not in DATA_URI_MIME_TYPES or ImageToolsEngine.sniff_mime(content) != declared_mime:
            raise ImageToolInputError("MIME_MISMATCH")
        data_uri = f"data:{declared_mime};base64," + base64.b64encode(content).decode("ascii")
        return {
            "mime": declared_mime,
            "byte_length": len(content),
            "data_uri_length": len(data_uri),
            "data_uri": data_uri,
        }

    @staticmethod
    def decode_data_uri(data_uri: str) -> tuple[bytes, str]:
        """Decode a strict base64 image data URI. Returns the bytes and their verified MIME type."""
        if not isinstance(data_uri, str) or len(data_uri) > MAX_DATA_URI_CHARS:
            raise ImageToolInputError("INVALID_DATA_URI")
        match = DATA_URI_PATTERN.match(data_uri)
        if match is None:
            raise ImageToolInputError("INVALID_DATA_URI")
        declared = f"image/{match.group(1)}"
        try:
            decoded = base64.b64decode(match.group(2), validate=True)
        except (binascii.Error, ValueError):
            raise ImageToolInputError("INVALID_DATA_URI") from None
        if len(decoded) > MAX_DATA_URI_BINARY_BYTES:
            raise ImageToolInputError("TOO_LARGE_BINARY")
        if ImageToolsEngine.sniff_mime(decoded) != declared:
            raise ImageToolInputError("MIME_MISMATCH")
        return decoded, declared

    @staticmethod
    def compare(
        image_a: bytes,
        image_b: bytes,
        alignment: str = "none",
        threshold: int = 0,
    ) -> dict:
        """Count pixels whose largest channel delta exceeds the threshold. Reports measured counts only."""
        if alignment not in COMPARE_ALIGNMENTS:
            raise _invalid_operation()
        if type(threshold) is not int or not 0 <= threshold <= 255:
            raise _invalid_operation()
        budget = SimilarImagePixelBudget(MAX_RENDITION_WORK_PIXELS)
        frame_a, icc_a = _comparison_frame(image_a, budget)
        frame_b, icc_b = _comparison_frame(image_b, budget)
        profiles_differ = bool(icc_a) != bool(icc_b) or (bool(icc_a) and icc_a != icc_b)
        # Count visible pixels only; both frames sit over the same white so hidden RGB under alpha 0 is ignored.
        frame_a = _over_neutral(frame_a)
        frame_b = _over_neutral(frame_b)
        report = {
            "a": {"w": frame_a.width, "h": frame_a.height},
            "b": {"w": frame_b.width, "h": frame_b.height},
            "threshold": threshold,
            "profiles_differ": profiles_differ,
        }
        scaled_b = False
        if frame_a.size != frame_b.size:
            if alignment == "none":
                report.update(
                    comparable=False, reason="size_mismatch", scaled_b=False, compared_pixels=None,
                    changed_pixels=None, changed_ratio=None, max_channel_delta=None, mean_abs_delta=None,
                    changed_bbox=None, difference_png=None,
                )
                return report
            frame_b = frame_b.resize(frame_a.size, Image.Resampling.LANCZOS)
            scaled_b = True

        bands = [ImageChops.difference(band_a, band_b) for band_a, band_b in zip(frame_a.split(), frame_b.split())]
        maximum = bands[0]
        for band in bands[1:]:
            maximum = ImageChops.lighter(maximum, band)
        changed_mask = maximum.point(lambda value: 255 if value > threshold else 0)
        compared = frame_a.width * frame_a.height
        changed = changed_mask.histogram()[255]
        total_delta = sum(
            value * count for band in bands for value, count in enumerate(band.histogram())
        )
        report.update(
            comparable=True,
            reason=None,
            scaled_b=scaled_b,
            compared_pixels=compared,
            changed_pixels=changed,
            changed_ratio=round(changed / compared, 6),
            max_channel_delta=maximum.getextrema()[1],
            mean_abs_delta=round(total_delta / (4 * compared), 3),
            changed_bbox=list(changed_mask.getbbox()) if changed else None,
            difference_png=_difference_data_uri(frame_a, changed_mask),
        )
        return report
