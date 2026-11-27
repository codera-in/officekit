"""Bounded PDF visual compression, target sizing, and page-box cropping."""

from __future__ import annotations

from io import BytesIO
import math
import tempfile
from pathlib import Path

from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .engine_conversion_errors import ConversionInputError
from .engine_media_devices import resolve_device_aspect, resolve_paper_aspect


class MediaPdfCancelledError(RuntimeError):
    """Raised when a media job is cancelled between PDF pages."""


class _BoundedBuffer(BytesIO):
    def write(self, value):
        if self.tell() + len(value) > MediaPdfEngine.MAX_OUTPUT_BYTES:
            raise ConversionInputError()
        return super().write(value)


class MediaPdfEngine:
    MAX_INPUT_BYTES = 64 * 1024 * 1024
    MAX_OUTPUT_BYTES = 64 * 1024 * 1024
    MAX_PAGES = 100
    MAX_PAGE_PIXELS = 24_000_000
    MAX_RENDER_PIXELS_PER_ATTEMPT = 60_000_000
    MAX_FIT_ATTEMPTS = 10
    MAX_FIT_RENDER_PIXELS = 180_000_000
    MIN_FIT_DPI = 72
    MAX_DPI_SCAN_OBJECTS = 10_000
    MAX_DPI_SCAN_DEPTH = 15
    _PAGE_ASPECTS = {
        "a4": 210 / 297,
        "letter": 612 / 792,
        "mobile": 9 / 16,
        "tablet": 4 / 3,
    }

    @classmethod
    def image_dpi_range(cls, input_bytes: bytes):
        """Read effective placed-image DPI without decoding or rendering pixels.

        Return the lowest and highest axis DPI across all placed images. Vector
        documents have no image DPI; incomplete or invalid scans are rejected.
        """
        import pypdfium2.raw as pdfium_c
        from pypdf import PdfReader

        try:
            minimum, maximum = math.inf, 0.0
            count = 0
            with cls._open_pdfium(input_bytes) as document:
                if not 1 <= len(document) <= cls.MAX_PAGES:
                    raise ConversionInputError()
                # PDFium exposes object transforms but not the page's UserUnit.
                # Read that scalar with the existing PDF parser, without pixels.
                reader = PdfReader(BytesIO(input_bytes), strict=True)
                if reader.is_encrypted or len(reader.pages) != len(document):
                    raise ConversionInputError()
                for page_index in range(len(document)):
                    unit = float(reader.pages[page_index].user_unit)
                    if not math.isfinite(unit) or unit <= 0:
                        raise ConversionInputError()
                    page = document[page_index]
                    try:
                        for obj in page.get_objects(max_depth=cls.MAX_DPI_SCAN_DEPTH):
                            count += 1
                            if count > cls.MAX_DPI_SCAN_OBJECTS:
                                raise ConversionInputError()
                            if obj.type == pdfium_c.FPDF_PAGEOBJ_FORM and obj.level >= cls.MAX_DPI_SCAN_DEPTH - 1:
                                raise ConversionInputError()
                            if obj.type != pdfium_c.FPDF_PAGEOBJ_IMAGE:
                                continue
                            width, height = obj.get_px_size()
                            matrix = obj.get_matrix()
                            parent = obj.container
                            while parent is not None:
                                matrix = matrix.multiply(parent.get_matrix())
                                parent = parent.container
                            axes = math.hypot(matrix.a, matrix.b), math.hypot(matrix.c, matrix.d)
                            if not all(math.isfinite(axis) and axis > 0 for axis in axes) or width <= 0 or height <= 0:
                                raise ConversionInputError()
                            dpi = width * 72 / axes[0] / unit, height * 72 / axes[1] / unit
                            if not all(math.isfinite(value) and value > 0 for value in dpi):
                                raise ConversionInputError()
                            minimum = min(minimum, *dpi)
                            maximum = max(maximum, *dpi)
                    finally:
                        page.close()
            return None if maximum == 0 else (minimum, maximum)
        except ConversionInputError:
            raise
        except Exception:
            raise ConversionInputError() from None

    @classmethod
    def reset_crop_boxes(cls, input_bytes: bytes):
        """Restore each page's visible crop to its media bounds in a new PDF copy."""
        if not isinstance(input_bytes, bytes) or not input_bytes or len(input_bytes) > cls.MAX_INPUT_BYTES:
            raise ConversionInputError()
        try:
            from pypdf import PdfReader, PdfWriter

            reader = PdfReader(BytesIO(input_bytes), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= cls.MAX_PAGES:
                raise ConversionInputError()
            writer = PdfWriter(clone_from=reader)
            for page in writer.pages:
                media_box = page.mediabox
                coordinates = tuple(float(value) for value in media_box)
                if not all(math.isfinite(value) for value in coordinates):
                    raise ConversionInputError()
                if coordinates[2] <= coordinates[0] or coordinates[3] <= coordinates[1]:
                    raise ConversionInputError()
                page.cropbox = media_box
            output = BytesIO()
            writer.write(output)
            data = output.getvalue()
            output.close()
            if not data or len(data) > cls.MAX_OUTPUT_BYTES:
                raise ConversionInputError()
            return data, {"page_count": len(writer.pages), "crop_boxes_restored": True}
        except ConversionInputError:
            raise
        except Exception:
            raise ConversionInputError() from None

    @classmethod
    def visual_optimize(cls, input_bytes: bytes, options: dict, cancel_event=None):
        dpi = options.get("dpi", 150)
        quality = options.get("quality", 75)
        data, page_count, _target_met, attempts, _pixels = cls._raster_pdf(
            input_bytes, dpi, quality, cancel_event
        )
        return data, {
            "page_count": page_count,
            "dpi": dpi,
            "quality": quality,
            "visual_only": True,
            "searchable_text_preserved": False,
            "interactive_content_preserved": False,
            "attempts": attempts,
        }

    @classmethod
    def fit_size(cls, input_bytes: bytes, options: dict, cancel_event=None):
        target_bytes = options["target_bytes"]
        requested_dpi = options.get("dpi", 150)
        requested_quality = options.get("quality", 75)
        dpi = requested_dpi
        quality_steps = list(range(requested_quality, 29, -10))
        if not quality_steps or quality_steps[-1] != 30:
            quality_steps.append(30)
        attempts = 0
        last_data = b""
        last_pages = 0
        rendered_pixels = 0
        while attempts < cls.MAX_FIT_ATTEMPTS and dpi >= cls.MIN_FIT_DPI:
            for quality in quality_steps:
                if attempts >= cls.MAX_FIT_ATTEMPTS:
                    break
                attempts += 1
                data, page_count, _target_met, _attempts, attempt_pixels = cls._raster_pdf(
                    input_bytes,
                    dpi,
                    quality,
                    cancel_event,
                    cumulative_attempt=attempts,
                    pixel_limit=min(
                        cls.MAX_RENDER_PIXELS_PER_ATTEMPT,
                        cls.MAX_FIT_RENDER_PIXELS - rendered_pixels,
                    ),
                )
                rendered_pixels += attempt_pixels
                last_data, last_pages = data, page_count
                if len(data) <= target_bytes:
                    return data, {
                        "page_count": page_count,
                        "dpi": dpi,
                        "quality": quality,
                        "target_bytes": target_bytes,
                        "actual_bytes": len(data),
                        "target_met": True,
                        "visual_only": True,
                        "searchable_text_preserved": False,
                        "interactive_content_preserved": False,
                        "attempts": attempts,
                    }
            if dpi == cls.MIN_FIT_DPI or rendered_pixels >= cls.MAX_FIT_RENDER_PIXELS:
                break
            dpi = max(cls.MIN_FIT_DPI, math.floor(dpi * 0.72))
            quality_steps = [30]

        return last_data, {
            "page_count": last_pages,
            "dpi": dpi,
            "quality": 30,
            "target_bytes": target_bytes,
            "actual_bytes": len(last_data),
            "target_met": False,
            "visual_only": True,
            "searchable_text_preserved": False,
            "interactive_content_preserved": False,
            "attempts": attempts,
        }

    @classmethod
    def _raster_pdf(
        cls, input_bytes, dpi, quality, cancel_event,
        cumulative_attempt=1, pixel_limit=MAX_RENDER_PIXELS_PER_ATTEMPT,
    ):
        source = cls._open_pdfium(input_bytes)
        try:
            page_count = len(source)
        except Exception:
            source.close()
            raise ConversionInputError() from None
        if not 1 <= page_count <= cls.MAX_PAGES:
            source.close()
            raise ConversionInputError()

        total_pixels = 0
        page_sizes = []
        scale = dpi / 72
        try:
            for page_index in range(page_count):
                page = source[page_index]
                try:
                    width, height = page.get_size()
                    pixel_width = max(1, math.ceil(width * scale))
                    pixel_height = max(1, math.ceil(height * scale))
                    pixels = pixel_width * pixel_height
                    if (
                        not all(math.isfinite(value) and value > 0 for value in (width, height))
                        or pixels > cls.MAX_PAGE_PIXELS
                    ):
                        raise ConversionInputError()
                    total_pixels += pixels
                    if total_pixels > pixel_limit:
                        raise ConversionInputError()
                    page_sizes.append((width, height, pixels))
                finally:
                    page.close()
        except Exception:
            source.close()
            raise

        try:
            with tempfile.TemporaryDirectory(prefix="officekit-media-pdf-") as temp_dir:
                images = []
                image_bytes = 0
                rendered_pixels = 0
                for page_index, (width, height, pixels) in enumerate(page_sizes):
                    cls._check_cancel(cancel_event)
                    rendered_pixels += pixels
                    if rendered_pixels > cls.MAX_RENDER_PIXELS_PER_ATTEMPT:
                        raise ConversionInputError()
                    page = source[page_index]
                    bitmap = page.render(
                        scale=scale,
                        fill_color=(255, 255, 255, 255),
                        rev_byteorder=True,
                        maybe_alpha=True,
                        draw_annots=True,
                        limit_image_cache=True,
                    )
                    try:
                        rendered = bitmap.to_pil()
                        image = rendered if rendered.mode in ("RGB", "L") else rendered.convert("RGB")
                        image_path = Path(temp_dir) / f"page-{page_index:03d}.jpg"
                        image.save(image_path, format="JPEG", quality=quality, optimize=True)
                        image_bytes += image_path.stat().st_size
                        if image_bytes > cls.MAX_OUTPUT_BYTES:
                            raise ConversionInputError()
                        images.append((image_path, width, height))
                        if image is not rendered:
                            image.close()
                        rendered.close()
                    finally:
                        bitmap.close()
                        page.close()

                output = _BoundedBuffer()
                pdf = canvas.Canvas(output, pageCompression=1, invariant=1)
                pdf.setCreator("OfficeKit Media Toolkit")
                pdf.setTitle("Visually optimized PDF")
                for image_path, width, height in images:
                    cls._check_cancel(cancel_event)
                    pdf.setPageSize((width, height))
                    pdf.drawImage(ImageReader(str(image_path)), 0, 0, width=width, height=height)
                    pdf.showPage()
                pdf.save()
                data = output.getvalue()
                output.close()
                if not data or len(data) > cls.MAX_OUTPUT_BYTES:
                    raise ConversionInputError()
                return data, page_count, True, cumulative_attempt, total_pixels
        except MediaPdfCancelledError:
            raise
        except ConversionInputError:
            raise
        except Exception:
            raise ConversionInputError() from None
        finally:
            source.close()

    @classmethod
    def crop_pages(cls, input_bytes: bytes, options: dict):
        if not isinstance(input_bytes, bytes) or not input_bytes or len(input_bytes) > cls.MAX_INPUT_BYTES:
            raise ConversionInputError()
        try:
            from pypdf import PdfReader, PdfWriter
            from pypdf.generic import RectangleObject

            reader = PdfReader(BytesIO(input_bytes), strict=True)
            if reader.is_encrypted or not 1 <= len(reader.pages) <= cls.MAX_PAGES:
                raise ConversionInputError()
            writer = PdfWriter(clone_from=reader)
            page_size = options.get("page_size")
            if page_size:
                preset_aspect = cls._PAGE_ASPECTS[page_size]
                target_aspect = min(preset_aspect, 1 / preset_aspect)
                aspect_ratio = None
            else:
                ratio = options.get("aspect_ratio")
                if options.get("device_name"):
                    ratio = resolve_device_aspect(options["device_name"])
                elif options.get("paper_size_name"):
                    ratio = resolve_paper_aspect(options["paper_size_name"])
                ratio_width, ratio_height = (int(part) for part in ratio.split(":"))
                target_aspect = min(ratio_width, ratio_height) / max(ratio_width, ratio_height)
                aspect_ratio = f"{ratio_width}:{ratio_height}"
            page_layout = options.get("page_layout", "auto")
            extend = options.get("extend", False)
            for page in writer.pages:
                box = page.cropbox
                left, bottom = float(box.left), float(box.bottom)
                right, top = float(box.right), float(box.top)
                width, height = right - left, top - bottom
                if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                    raise ConversionInputError()
                rotated = page.rotation % 180 == 90
                visible_width, visible_height = (height, width) if rotated else (width, height)
                if page_layout == "portrait":
                    visible_target_aspect = target_aspect
                elif page_layout == "landscape":
                    visible_target_aspect = 1 / target_aspect
                else:
                    visible_target_aspect = target_aspect if visible_width <= visible_height else 1 / target_aspect
                page_aspect = 1 / visible_target_aspect if rotated else visible_target_aspect
                current_aspect = width / height
                if extend:
                    if current_aspect > page_aspect:
                        extended_height = width / page_aspect
                        bottom -= (extended_height - height) / 2
                        top = bottom + extended_height
                    else:
                        extended_width = height * page_aspect
                        left -= (extended_width - width) / 2
                        right = left + extended_width
                    if max(right - left, top - bottom) > 200_000:
                        raise ConversionInputError()
                    extended_box = RectangleObject((left, bottom, right, top))
                    page.mediabox = extended_box
                    page.cropbox = extended_box
                else:
                    if current_aspect > page_aspect:
                        cropped_width = height * page_aspect
                        left += (width - cropped_width) / 2
                        right = left + cropped_width
                    else:
                        cropped_height = width / page_aspect
                        bottom += (height - cropped_height) / 2
                        top = bottom + cropped_height
                    page.cropbox = RectangleObject((left, bottom, right, top))
            output = _BoundedBuffer()
            writer.write(output)
            data = output.getvalue()
            output.close()
            if not data or len(data) > cls.MAX_OUTPUT_BYTES:
                raise ConversionInputError()
            return data, {
                "page_count": len(reader.pages),
                "page_size": page_size,
                "aspect_ratio": aspect_ratio,
                "page_layout": page_layout,
                "extended": extend,
                "vector_content_preserved": True,
                "crop_centered": not extend,
            }
        except ConversionInputError:
            raise
        except Exception:
            raise ConversionInputError() from None

    @staticmethod
    def _open_pdfium(input_bytes):
        if not isinstance(input_bytes, bytes) or not input_bytes or len(input_bytes) > MediaPdfEngine.MAX_INPUT_BYTES:
            raise ConversionInputError()
        try:
            import pypdfium2 as pdfium

            return pdfium.PdfDocument(input_bytes)
        except Exception:
            raise ConversionInputError() from None

    @staticmethod
    def _check_cancel(cancel_event):
        if cancel_event is not None and cancel_event.is_set():
            raise MediaPdfCancelledError()
