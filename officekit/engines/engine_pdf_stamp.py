"""Watermarks (P12) and page numbers (P13) drawn as reportlab overlays, placed by page geometry.

Every stamp is drawn in displayed coordinates (after /Rotate) and placed into the unrotated page
through a counter-rotation matrix, so text reads upright as the viewer shows it. Previews render the
same stamped document that the output path produces (P-164).
"""

import dataclasses
import hashlib
import io
import math
import os
import sys
import unicodedata
from dataclasses import dataclass

import pikepdf
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as reportlab_canvas

from officekit.engines.engine_pdf_advanced import AdvancedPdfEngine
from officekit.engines.engine_pdf_tool_common import (
    MM_TO_PT,
    PdfOptionError,
    open_source_pdf,
    page_rotation,
    page_xobjects,
    save_bounded,
    selected_indexes,
    wrap_page_content,
)

_HELVETICA = "Helvetica"
_TTF_NAME = "OfficeKitWatermarkSans"


def _bundled_font_path(filename: str) -> str:
    """Packaged sidecar copy first (PyInstaller puts assets under fonts/), then the repo copy."""
    candidates = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(os.path.join(sys._MEIPASS, "fonts", filename))
    candidates.append(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "fonts", filename))
    return next((path for path in candidates if os.path.isfile(path)), candidates[-1])


_ROMAN = (
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
    (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
)


class PdfStampInputError(ValueError):
    """A caller-visible input problem whose message is a fixed public copy."""


@dataclass(frozen=True)
class WatermarkSpec:
    kind: str
    text: str | None
    image: bytes | None
    font_size: int
    color: str
    opacity: int
    angle: int
    position: str
    page_ranges: str


@dataclass(frozen=True)
class PageNumberSpec:
    number_format: str
    template: str | None
    start: int
    position: str
    margin_mm: int
    font_size: int
    page_ranges: str
    count_skipped: bool


def _roman(value: int) -> str:
    if not 1 <= value <= 3999:
        raise PdfOptionError("Roman numerals need values between 1 and 3,999.")
    pieces = []
    remaining = value
    for amount, symbol in _ROMAN:
        while remaining >= amount:
            pieces.append(symbol)
            remaining -= amount
    return "".join(pieces)


def _matrix_for(rotation: int, width: float, height: float, x0: float, y0: float):
    """Map displayed coordinates (u, v) to the unrotated page as ``[a b c d e f]``."""
    if rotation == 0:
        return (1.0, 0.0, 0.0, 1.0, x0, y0)
    if rotation == 90:
        return (0.0, 1.0, -1.0, 0.0, width + x0, y0)
    if rotation == 180:
        return (-1.0, 0.0, 0.0, -1.0, width + x0, height + y0)
    return (0.0, -1.0, 1.0, 0.0, x0, height + y0)


def _apply(matrix, u: float, v: float) -> tuple[float, float]:
    a, b, c, d, e, f = matrix
    return a * u + c * v + e, b * u + d * v + f


def format_ranges(pages: list[int], limit: int = 256) -> str:
    """Compact 1-based ranges such as ``1-3,5``; cut with an ellipsis at ``limit`` characters."""
    if not pages:
        return ""
    ordered = sorted(set(pages))
    parts = []
    start = previous = ordered[0]
    for number in ordered[1:] + [None]:
        if number is not None and number == previous + 1:
            previous = number
            continue
        parts.append(str(start) if start == previous else f"{start}-{previous}")
        if number is not None:
            start = previous = number
    text = ",".join(parts)
    if len(text) > limit:
        text = text[: limit - 1].rstrip(",") + "…"
    return text


class PdfStampEngine:
    MAX_OUTPUT_BYTES = AdvancedPdfEngine.MAX_OUTPUT_BYTES
    MAX_IMAGE_BYTES = 8 * 1024 * 1024
    MAX_IMAGE_PIXELS = 16_000_000
    MAX_TEXT_CHARS = 200
    MAX_TILES_PER_PAGE = 2_000
    MAX_OBJECTS_PER_PAGE = 10_000
    PREVIEW_EDGE_PX = 800
    PREVIEW_MAX_BYTES = 4 * 1024 * 1024
    MARGIN_PT = 36.0
    WATERMARK_POSITIONS = (
        "center", "tile", "top-left", "top-center", "top-right",
        "bottom-left", "bottom-center", "bottom-right",
    )
    NUMBER_POSITIONS = (
        "top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right",
    )
    NUMBER_FORMATS = ("number", "page", "page-of-total", "roman-lower", "roman-upper", "custom")
    # Bundled Noto Sans covers Latin, Greek and Cyrillic. Tamil is not offered: its shaping
    # (conjuncts, vowel-sign reordering) needs HarfBuzz, which reportlab does not run here.
    # If the file is ever missing, the Helvetica built-in covers printable ASCII only.
    WATERMARK_FONT_PATH = _bundled_font_path("NotoSans-Regular.ttf")
    UNSUPPORTED_GLYPH_MESSAGE = ("The watermark text uses characters the bundled font can't draw. "
                                 "Latin, Greek and Cyrillic are supported.")
    PREVIEW_FIRST_LANDSCAPE = 0
    UNSUPPORTED_NUMBER_TEXT_MESSAGE = "The page number text uses characters the bundled font can't draw."
    IMAGE_ERROR_MESSAGE = "The watermark image could not be read."

    # ------------------------------------------------------------------ fonts

    @classmethod
    def _font(cls):
        """Return (font name, coverage predicate). A bundled TrueType font wins when present."""
        path = cls.WATERMARK_FONT_PATH
        if os.path.isfile(path):
            # Keyed by path so a different font file never reuses another file's registration.
            name = f"{_TTF_NAME}-{hashlib.sha256(os.path.abspath(path).encode('utf-8')).hexdigest()[:12]}"
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, path))
            glyphs = pdfmetrics.getFont(name).face.charToGlyph
            return name, lambda character: ord(character) in glyphs
        return _HELVETICA, lambda character: 0x20 <= ord(character) <= 0x7E

    @classmethod
    def _check_text(cls, text: str, message: str) -> None:
        _, covers = cls._font()
        if not all(covers(character) for character in text):
            raise PdfStampInputError(message)

    # ------------------------------------------------------------ validation

    @classmethod
    def _validate_watermark(cls, spec: WatermarkSpec) -> None:
        if spec.kind not in ("text", "image"):
            raise PdfOptionError("Watermark kind must be text or image.")
        if not 8 <= spec.font_size <= 144:
            raise PdfOptionError("Watermark font size must be between 8 and 144.")
        if not isinstance(spec.color, str) or len(spec.color) != 7 or not spec.color.startswith("#"):
            raise PdfOptionError("Watermark color must be #RRGGBB.")
        if isinstance(spec.opacity, bool) or not 5 <= spec.opacity <= 100:
            raise PdfOptionError("Watermark opacity must be between 5 and 100.")
        if isinstance(spec.angle, bool) or not -90 <= spec.angle <= 90:
            raise PdfOptionError("Watermark angle must be between -90 and 90.")
        if spec.position not in cls.WATERMARK_POSITIONS:
            raise PdfOptionError("Unknown watermark position.")
        if spec.kind == "text":
            if spec.image is not None or spec.text is None:
                raise PdfOptionError("Text watermarks need text and no image.")
            text = unicodedata.normalize("NFC", spec.text)
            if not 1 <= len(text) <= cls.MAX_TEXT_CHARS:
                raise PdfOptionError("Watermark text must be 1 to 200 characters.")
            if any(unicodedata.category(character) == "Cc" for character in text):
                raise PdfOptionError("Watermark text cannot contain control characters.")
            cls._check_text(text, cls.UNSUPPORTED_GLYPH_MESSAGE)
        else:
            if spec.text is not None or spec.image is None:
                raise PdfOptionError("Image watermarks need an image and no text.")

    @classmethod
    def _image_reader(cls, data: bytes) -> ImageReader:
        if not isinstance(data, bytes) or not 0 < len(data) <= cls.MAX_IMAGE_BYTES:
            raise PdfStampInputError(cls.IMAGE_ERROR_MESSAGE)
        try:
            with Image.open(io.BytesIO(data)) as header:
                if header.format not in ("PNG", "JPEG"):
                    raise PdfStampInputError(cls.IMAGE_ERROR_MESSAGE)
                if header.width * header.height > cls.MAX_IMAGE_PIXELS:
                    raise PdfStampInputError(cls.IMAGE_ERROR_MESSAGE)
                size = header.size
        except PdfStampInputError:
            raise
        except Exception as error:
            raise PdfStampInputError(cls.IMAGE_ERROR_MESSAGE) from error
        return ImageReader(io.BytesIO(data)), size

    @classmethod
    def _validate_numbers(cls, spec: PageNumberSpec) -> None:
        if spec.number_format not in cls.NUMBER_FORMATS:
            raise PdfOptionError("Unknown page number format.")
        if spec.number_format == "custom":
            if spec.template is None or len(spec.template) > 64:
                raise PdfOptionError("A custom template needs 1 to 64 characters.")
            remainder = spec.template.replace("{n}", "").replace("{total}", "")
            if "{" in remainder or "}" in remainder:
                raise PdfOptionError("Templates may only use the {n} and {total} tokens.")
        elif spec.template is not None:
            raise PdfOptionError("A template is only used with the custom format.")
        if spec.number_format.startswith("roman"):
            if not 1 <= spec.start <= 3999:
                raise PdfOptionError("Roman numbering starts between 1 and 3,999.")
        elif isinstance(spec.start, bool) or not 0 <= spec.start <= 9_999:
            raise PdfOptionError("Start must be between 0 and 9,999.")
        if spec.position not in cls.NUMBER_POSITIONS:
            raise PdfOptionError("Unknown page number position.")
        if isinstance(spec.margin_mm, bool) or not 0 <= spec.margin_mm <= 50:
            raise PdfOptionError("Margin must be between 0 and 50 mm.")
        if not 6 <= spec.font_size <= 36:
            raise PdfOptionError("Font size must be between 6 and 36.")
        if not isinstance(spec.count_skipped, bool):
            raise PdfOptionError("count_skipped must be true or false.")

    # ----------------------------------------------------------- geometry

    @staticmethod
    def _geometry(page) -> dict:
        x0, y0, x1, y1 = (float(value) for value in page.cropbox)
        width, height = x1 - x0, y1 - y0
        rotation = page_rotation(page.obj)
        displayed = (height, width) if rotation in (90, 270) else (width, height)
        return {
            "display": displayed,
            "matrix": _matrix_for(rotation, width, height, x0, y0),
        }

    @staticmethod
    def _anchor(position: str, display_w: float, display_h: float, margin: float, text_w: float, size: float):
        vertical, horizontal = position.split("-")
        x = {"left": margin, "center": (display_w - text_w) / 2, "right": display_w - margin - text_w}[horizontal]
        y = {"top": display_h - margin - size, "bottom": margin}[vertical]
        return x, y

    # ------------------------------------------------------------ drawing

    @classmethod
    def _draw_watermark(cls, canvas, spec: WatermarkSpec, image, width: float, height: float):
        font_name, _ = cls._font()
        canvas.saveState()
        canvas.setFillAlpha(spec.opacity / 100.0)
        canvas.setFillColor(HexColor(spec.color))
        if spec.kind == "text":
            text = spec.text
            text_w = pdfmetrics.stringWidth(text, font_name, spec.font_size)
            if spec.position == "tile":
                cls._draw_tiles(canvas, spec, font_name, text, text_w, width, height)
            elif spec.position == "center":
                canvas.saveState()
                canvas.translate(width / 2, height / 2)
                canvas.rotate(spec.angle)
                canvas.setFont(font_name, spec.font_size)
                canvas.drawString(-text_w / 2, -spec.font_size * 0.35, text)
                canvas.restoreState()
            else:
                x, y = cls._anchor(spec.position, width, height, cls.MARGIN_PT, text_w, spec.font_size)
                canvas.saveState()
                canvas.translate(x, y)
                canvas.rotate(spec.angle)
                canvas.setFont(font_name, spec.font_size)
                canvas.drawString(0, 0, text)
                canvas.restoreState()
        else:
            reader, (image_w, image_h) = image
            longest = min(width, height) * 0.4
            scale = longest / max(image_w, image_h)
            draw_w, draw_h = image_w * scale, image_h * scale
            canvas.saveState()
            canvas.translate(width / 2, height / 2)
            canvas.rotate(spec.angle)
            canvas.drawImage(reader, -draw_w / 2, -draw_h / 2, draw_w, draw_h, mask="auto")
            canvas.restoreState()
        canvas.restoreState()

    @classmethod
    def _draw_tiles(cls, canvas, spec, font_name, text, text_w, width, height):
        step_x = text_w + spec.font_size * 4
        step_y = spec.font_size * 4
        reach = math.hypot(width, height)
        columns = math.ceil(2 * reach / step_x) + 1
        rows = math.ceil(2 * reach / step_y) + 1
        if columns * rows > cls.MAX_TILES_PER_PAGE:
            raise PdfOptionError("The watermark tile pattern is too dense for this page.")
        canvas.translate(width / 2, height / 2)
        canvas.rotate(spec.angle)
        canvas.setFont(font_name, spec.font_size)
        for column in range(-columns // 2, columns // 2 + 1):
            for row in range(-rows // 2, rows // 2 + 1):
                canvas.drawString(column * step_x - text_w / 2, row * step_y, text)
        canvas.rotate(-spec.angle)
        canvas.translate(-width / 2, -height / 2)

    @classmethod
    def _draw_numbers(cls, canvas, spec: PageNumberSpec, label: str, width: float, height: float):
        font_name, covers = cls._font()
        if not all(covers(character) for character in label):
            raise PdfStampInputError(cls.UNSUPPORTED_NUMBER_TEXT_MESSAGE)
        margin = spec.margin_mm * MM_TO_PT
        text_w = pdfmetrics.stringWidth(label, font_name, spec.font_size)
        x, y = cls._anchor(spec.position, width, height, margin, text_w, spec.font_size)
        canvas.saveState()
        canvas.setFillColor(HexColor("#000000"))
        canvas.setFont(font_name, spec.font_size)
        canvas.drawString(x, y, label)
        canvas.restoreState()
        return (x, y, x + text_w, y + spec.font_size)

    # --------------------------------------------------------- core stamp

    @classmethod
    def _stamp(cls, content: bytes, page_ranges: str, drawer):
        """Draw one overlay per selected page and place it. Returns (bytes, per-page boxes, indexes, geometries)."""
        pdf = open_source_pdf(content)
        try:
            indexes = selected_indexes(page_ranges, len(pdf.pages))
            if not indexes:
                raise PdfOptionError("Select at least one page or page range.")
            geometries = [cls._geometry(pdf.pages[index]) for index in indexes]
            overlay = io.BytesIO()
            canvas = reportlab_canvas.Canvas(overlay, pagesize=geometries[0]["display"])
            boxes_per_page = []
            for position, (index, geometry) in enumerate(zip(indexes, geometries)):
                display_w, display_h = geometry["display"]
                canvas.setPageSize((display_w, display_h))
                boxes_per_page.append(drawer(canvas, position, display_w, display_h) or [])
                canvas.showPage()
            canvas.save()
            overlay_pdf = pikepdf.open(io.BytesIO(overlay.getvalue()))
            try:
                for position, (index, geometry) in enumerate(zip(indexes, geometries)):
                    cls._place(pdf, pdf.pages[index], overlay_pdf.pages[position], geometry, position)
            finally:
                overlay_pdf.close()
            output = save_bounded(pdf, cls.MAX_OUTPUT_BYTES)
        finally:
            pdf.close()
        return output, boxes_per_page, indexes, geometries

    @staticmethod
    def _place(pdf, page, overlay_page, geometry, token: int) -> None:
        form = pdf.copy_foreign(overlay_page.as_form_xobject())
        name = f"/OfficeKitStamp{token}"
        page_xobjects(page)[name] = form
        a, b, c, d, e, f = geometry["matrix"]
        stamp = f"q {a:.6f} {b:.6f} {c:.6f} {d:.6f} {e:.6f} {f:.6f} cm {name} Do Q\n".encode("ascii")
        wrap_page_content(pdf, page, stamp)

    @classmethod
    def _overlap_pages(cls, content: bytes, indexes, geometries, boxes_per_page) -> list[int]:
        """1-based pages where a label box intersects a text or image object of the source page."""
        hits = []
        document = pdfium.PdfDocument(content)
        try:
            for index, geometry, boxes in zip(indexes, geometries, boxes_per_page):
                if not boxes:
                    continue
                page = document[index]
                try:
                    objects = []
                    for obj in page.get_objects(filter=(pdfium_c.FPDF_PAGEOBJ_TEXT, pdfium_c.FPDF_PAGEOBJ_IMAGE)):
                        objects.append(obj)
                        if len(objects) > cls.MAX_OBJECTS_PER_PAGE:
                            break
                    if len(objects) > cls.MAX_OBJECTS_PER_PAGE:
                        hits.append(index + 1)
                        continue
                    stamp_boxes = []
                    for left, bottom, right, top in boxes:
                        corners = [_apply(geometry["matrix"], u, v)
                                   for u, v in ((left, bottom), (right, bottom), (left, top), (right, top))]
                        xs = [point[0] for point in corners]
                        ys = [point[1] for point in corners]
                        stamp_boxes.append((min(xs), min(ys), max(xs), max(ys)))
                    for obj in objects:
                        o_left, o_bottom, o_right, o_top = obj.get_bounds()
                        if any(o_left < s_right and o_right > s_left and o_bottom < s_top and o_top > s_bottom
                               for s_left, s_bottom, s_right, s_top in stamp_boxes):
                            hits.append(index + 1)
                            break
                finally:
                    page.close()
        finally:
            document.close()
        return sorted(set(hits))

    @classmethod
    def _preview_index(cls, document, preview_page: int) -> int:
        if isinstance(preview_page, bool):
            raise PdfOptionError("The preview page is outside this PDF.")
        if preview_page == cls.PREVIEW_FIRST_LANDSCAPE:
            for index in range(len(document)):
                page = document[index]
                try:
                    width, height = page.get_size()
                finally:
                    page.close()
                if width > height:
                    return index
            raise PdfOptionError("This PDF has no landscape page to preview.")
        if not 1 <= preview_page <= len(document):
            raise PdfOptionError("The preview page is outside this PDF.")
        return preview_page - 1

    @classmethod
    def _render_png(cls, content: bytes, preview_page: int) -> bytes:
        document = pdfium.PdfDocument(content)
        try:
            page = document[cls._preview_index(document, preview_page)]
            try:
                width, height = page.get_size()
                scale = PdfStampEngine.PREVIEW_EDGE_PX / max(width, height)
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                finally:
                    bitmap.close()
                output = io.BytesIO()
                image.save(output, format="PNG")
            finally:
                page.close()
        finally:
            document.close()
        data = output.getvalue()
        if len(data) > PdfStampEngine.PREVIEW_MAX_BYTES:
            raise ValueError("The preview image exceeds the preview size limit.")
        return data

    # ------------------------------------------------------------ public

    @classmethod
    def watermark(cls, content: bytes, spec: WatermarkSpec) -> bytes:
        if spec.kind == "text" and isinstance(spec.text, str):
            spec = dataclasses.replace(spec, text=unicodedata.normalize("NFC", spec.text))
        cls._validate_watermark(spec)
        image = cls._image_reader(spec.image) if spec.kind == "image" else None

        def drawer(canvas, _position, width, height):
            cls._draw_watermark(canvas, spec, image, width, height)
            return None

        output, _, _, _ = cls._stamp(content, spec.page_ranges, drawer)
        return output

    @classmethod
    def watermark_preview(cls, content: bytes, spec: WatermarkSpec, preview_page: int) -> bytes:
        return cls._render_png(cls.watermark(content, spec), preview_page)

    @classmethod
    def page_numbers(cls, content: bytes, spec: PageNumberSpec) -> tuple[bytes, list[int]]:
        cls._validate_numbers(spec)
        with open_source_pdf(content) as source:
            page_count = len(source.pages)
        selected = selected_indexes(spec.page_ranges, page_count)
        if not selected:
            raise PdfOptionError("Select at least one page or page range.")
        ordered = sorted(selected)
        if spec.count_skipped:
            value_of = {index: spec.start + index for index in ordered}
            total = page_count
        else:
            value_of = {index: spec.start + rank for rank, index in enumerate(ordered)}
            total = len(ordered)
        if spec.number_format.startswith("roman") and max(value_of.values()) > 3999:
            raise PdfOptionError("Roman numbering stops at 3,999.")
        labels = {index: cls._label(spec, value_of[index], total) for index in ordered}

        def drawer(canvas, position, width, height):
            label = labels[selected[position]]
            return [cls._draw_numbers(canvas, spec, label, width, height)]

        output, boxes, indexes, geometries = cls._stamp(content, spec.page_ranges, drawer)
        overlaps = cls._overlap_pages(content, indexes, geometries, boxes)
        return output, overlaps

    @classmethod
    def page_numbers_preview(cls, content: bytes, spec: PageNumberSpec, preview_page: int):
        output, overlaps = cls.page_numbers(content, spec)
        return cls._render_png(output, preview_page), overlaps

    @staticmethod
    def _label(spec: PageNumberSpec, value: int, total: int) -> str:
        if spec.number_format == "number":
            return str(value)
        if spec.number_format == "page":
            return f"Page {value}"
        if spec.number_format == "page-of-total":
            return f"Page {value} of {total}"
        if spec.number_format == "roman-lower":
            return _roman(value).lower()
        if spec.number_format == "roman-upper":
            return _roman(value)
        return spec.template.replace("{n}", str(value)).replace("{total}", str(total))
