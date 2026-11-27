"""Ordered image batch to PDF (P08): one page per image, sized and fitted by the options.

Headers are read and the pixel budget is checked before any decode (P-165). JPEG inputs without an
alpha channel or EXIF rotation are embedded undecoded. Everything else is decoded once, EXIF
orientation is applied, and alpha is composited on white.
"""

import io
import math

from PIL import Image, ImageOps
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as reportlab_canvas

from officekit.engines.engine_pdf_advanced import AdvancedPdfEngine
from officekit.engines.engine_pdf_security import BoundedPdfBuffer
from officekit.engines.engine_pdf_tool_common import MM_TO_PT, PAGE_PRESETS_PT

_EXIF_ORIENTATION = 0x0112
_SWAP_ORIENTATIONS = {5, 6, 7, 8}
_ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "TIFF", "GIF", "BMP"}


class ImageInputError(ValueError):
    """A per-image failure. The public copy names the 1-based position only."""

    def __init__(self, position: int):
        self.position = position
        super().__init__(f"Image {position} could not be read.")


class ImagesToPdfEngine:
    MAX_OUTPUT_BYTES = AdvancedPdfEngine.MAX_OUTPUT_BYTES
    MAX_IMAGES = 200
    MAX_IMAGE_PIXELS = 40_000_000
    # Each decoded image is held as RGB (3 bytes a pixel) until the PDF is saved, so 150 M pixels is about 450 MB.
    MAX_TOTAL_PIXELS = 150_000_000
    DEFAULT_DPI = 96
    MIN_DPI = 1
    MAX_DPI = 2_400
    MAX_PAGE_SIDE_PT = 14_400.0
    PAGE_SIZES = ("a4", "letter", "legal", "image")
    ORIENTATIONS = ("auto", "portrait", "landscape")
    FITS = ("contain", "cover", "actual")

    @classmethod
    def build(cls, images: list[bytes], page_size: str, orientation: str, fit: str, margin_mm: int) -> bytes:
        cls._validate_options(images, page_size, orientation, fit, margin_mm)
        records = cls._read_headers(images)
        margin = 0.0 if page_size == "image" else margin_mm * MM_TO_PT

        buffer = BoundedPdfBuffer(cls.MAX_OUTPUT_BYTES)
        canvas = reportlab_canvas.Canvas(buffer, pagesize=(612, 792))
        for record in records:
            page_w, page_h = cls._page_size(record, page_size, orientation)
            canvas.setPageSize((page_w, page_h))
            cls._draw(canvas, record, page_w, page_h, margin, fit, page_size)
            canvas.showPage()
        canvas.save()
        return buffer.getvalue()

    # ------------------------------------------------------------ validation

    @classmethod
    def _validate_options(cls, images, page_size, orientation, fit, margin_mm) -> None:
        if not isinstance(images, list) or not 1 <= len(images) <= cls.MAX_IMAGES:
            raise ValueError("Select between 1 and 200 images.")
        if page_size not in cls.PAGE_SIZES:
            raise ValueError("Page size must be a4, letter, legal or image.")
        if orientation not in cls.ORIENTATIONS:
            raise ValueError("Orientation must be auto, portrait or landscape.")
        if fit not in cls.FITS:
            raise ValueError("Fit must be contain, cover or actual.")
        if isinstance(margin_mm, bool) or not isinstance(margin_mm, int) or not 0 <= margin_mm <= 50:
            raise ValueError("Margin must be a whole number from 0 to 50 mm.")

    # --------------------------------------------------------------- reading

    @classmethod
    def _read_headers(cls, images) -> list[dict]:
        records = []
        total_pixels = 0
        for position, data in enumerate(images, start=1):
            if not isinstance(data, bytes) or not data:
                raise ImageInputError(position)
            try:
                with Image.open(io.BytesIO(data)) as header:
                    if header.format not in _ALLOWED_FORMATS:
                        raise ImageInputError(position)
                    width, height = header.size
                    exif = header.getexif()
                    orientation = int(exif.get(_EXIF_ORIENTATION, 1)) if exif else 1
                    dpi = header.info.get("dpi")
                    has_alpha = header.mode in ("RGBA", "LA", "PA") or "transparency" in header.info
                    fmt = header.format
            except ImageInputError:
                raise
            except Exception as error:
                raise ImageInputError(position) from error
            if width < 1 or height < 1 or width * height > cls.MAX_IMAGE_PIXELS:
                raise ImageInputError(position)
            total_pixels += width * height
            if total_pixels > cls.MAX_TOTAL_PIXELS:
                raise ImageInputError(position)
            if orientation not in range(1, 9):
                orientation = 1
            records.append({
                "position": position, "data": data, "format": fmt, "width": width, "height": height,
                "orientation": orientation, "dpi": cls._dpi(dpi), "alpha": has_alpha,
            })
        return records

    @classmethod
    def _dpi(cls, value) -> int:
        try:
            horizontal = float(value[0]) if value else cls.DEFAULT_DPI
        except (TypeError, ValueError, IndexError):
            horizontal = cls.DEFAULT_DPI
        if not math.isfinite(horizontal) or horizontal <= 0:
            horizontal = cls.DEFAULT_DPI
        return int(min(cls.MAX_DPI, max(cls.MIN_DPI, round(horizontal))))

    @staticmethod
    def _oriented(record) -> tuple[int, int]:
        if record["orientation"] in _SWAP_ORIENTATIONS:
            return record["height"], record["width"]
        return record["width"], record["height"]

    @classmethod
    def _page_size(cls, record, page_size: str, orientation: str) -> tuple[float, float]:
        width_px, height_px = cls._oriented(record)
        if page_size == "image":
            # The page follows the picture's size at its tagged DPI, clamped to the PDF page limit with aspect kept.
            width_pt, height_pt = width_px * 72.0 / record["dpi"], height_px * 72.0 / record["dpi"]
            scale = min(1.0, cls.MAX_PAGE_SIDE_PT / max(width_pt, height_pt))
            return width_pt * scale, height_pt * scale
        base_w, base_h = PAGE_PRESETS_PT[page_size]
        if orientation == "auto":
            landscape = width_px > height_px
        else:
            landscape = orientation == "landscape"
        return (max(base_w, base_h), min(base_w, base_h)) if landscape else (min(base_w, base_h), max(base_w, base_h))

    # -------------------------------------------------------------- drawing

    @classmethod
    def _draw(cls, canvas, record, page_w, page_h, margin, fit, page_size) -> None:
        width_px, height_px = cls._oriented(record)
        natural_w = width_px * 72.0 / record["dpi"]
        natural_h = height_px * 72.0 / record["dpi"]
        reader = cls._reader(record)

        if fit == "actual" and page_size != "image":
            draw_w, draw_h = natural_w, natural_h
        elif page_size == "image":
            draw_w, draw_h = page_w, page_h
        else:
            avail_w, avail_h = page_w - 2 * margin, page_h - 2 * margin
            if fit == "contain":
                scale = min(avail_w / natural_w, avail_h / natural_h)
            else:
                scale = max(avail_w / natural_w, avail_h / natural_h)
            draw_w, draw_h = natural_w * scale, natural_h * scale
        x = (page_w - draw_w) / 2
        y = (page_h - draw_h) / 2

        canvas.saveState()
        if fit == "cover" and page_size != "image":
            clip = canvas.beginPath()
            clip.rect(margin, margin, page_w - 2 * margin, page_h - 2 * margin)
            canvas.clipPath(clip, stroke=0, fill=0)
        canvas.drawImage(reader, x, y, draw_w, draw_h, mask=None)
        canvas.restoreState()

    @classmethod
    def _reader(cls, record) -> ImageReader:
        data = record["data"]
        if record["format"] == "JPEG" and not record["alpha"] and record["orientation"] == 1:
            with Image.open(io.BytesIO(data)) as header:
                if header.mode in ("RGB", "L"):
                    return ImageReader(io.BytesIO(data))
        try:
            with Image.open(io.BytesIO(data)) as source:
                image = ImageOps.exif_transpose(source)
                image.load()
                if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    backdrop = Image.new("RGB", rgba.size, (255, 255, 255))
                    backdrop.paste(rgba, mask=rgba.split()[3])
                    decoded = backdrop
                else:
                    decoded = image.convert("RGB")
        except Exception as error:
            raise ImageInputError(record["position"]) from error
        return ImageReader(decoded)
