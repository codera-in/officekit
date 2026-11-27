"""Bounded local rendering of PDF pages to a downloadable image archive."""

import io
import math
import base64
import zipfile

from .engine_media_pdf import MediaPdfCancelledError


class PdfImageExportEngine:
    MIN_DPI = 36
    MAX_DPI = 300
    MAX_PAGES = 100
    MAX_PAGE_PIXELS = 20_000_000
    MAX_TOTAL_PIXELS = 120_000_000
    MAX_PDF_BYTES = 64 * 1024 * 1024
    MAX_OUTPUT_BYTES = 128 * 1024 * 1024
    MAX_THUMBNAIL_DOCUMENT_PAGES = 2_000
    MAX_THUMBNAIL_WINDOW = 24
    MAX_THUMBNAIL_EDGE_PIXELS = 240
    MAX_THUMBNAIL_RESPONSE_BYTES = 16 * 1024 * 1024

    @classmethod
    def render_page_thumbnails(cls, content, page_numbers, pdfium_module=None):
        """Render a bounded, ordered set of source pages for local page review."""
        if not isinstance(content, bytes) or not content or len(content) > cls.MAX_PDF_BYTES:
            raise ValueError("PDF input is empty or exceeds the processing limit")
        if not isinstance(page_numbers, list) or not 1 <= len(page_numbers) <= cls.MAX_THUMBNAIL_WINDOW:
            raise ValueError("Select between 1 and 24 pages for thumbnail preview")
        if any(
            isinstance(number, bool) or not isinstance(number, int)
            or not 1 <= number <= cls.MAX_THUMBNAIL_DOCUMENT_PAGES
            for number in page_numbers
        ) or len(set(page_numbers)) != len(page_numbers):
            raise ValueError("Thumbnail pages must be unique valid page numbers")

        if pdfium_module is None:
            try:
                import pypdfium2 as pdfium_module
            except ImportError as error:
                raise RuntimeError("PDF page rendering is unavailable in this installation") from error

        try:
            document = pdfium_module.PdfDocument(content)
        except Exception as error:
            raise ValueError("PDF input could not be opened") from error

        try:
            page_count = len(document)
            if page_count < 1 or page_count > cls.MAX_THUMBNAIL_DOCUMENT_PAGES:
                raise ValueError("PDF input has an unsupported page count")
            if any(page_number > page_count for page_number in page_numbers):
                raise ValueError("Thumbnail page exceeds the document page count")

            rendered_pages = []
            response_bytes = 0
            for page_number in page_numbers:
                page = document[page_number - 1]
                bitmap = None
                image = None
                try:
                    width_points, height_points = page.get_size()
                    if not all(math.isfinite(value) and value > 0 for value in (width_points, height_points)):
                        raise ValueError("PDF page dimensions are invalid")
                    scale = min(cls.MAX_THUMBNAIL_EDGE_PIXELS / max(width_points, height_points), 1.0)
                    bitmap = page.render(
                        scale=scale,
                        fill_color=(255, 255, 255, 255),
                        rev_byteorder=True,
                        maybe_alpha=True,
                        draw_annots=True,
                        limit_image_cache=True,
                    )
                    image = bitmap.to_pil().copy()
                    encoded = io.BytesIO()
                    image.save(encoded, format="PNG")
                    data = encoded.getvalue()
                    encoded_b64 = base64.b64encode(data).decode("ascii")
                    response_bytes += len(encoded_b64)
                    if response_bytes > cls.MAX_THUMBNAIL_RESPONSE_BYTES:
                        raise ValueError("PDF thumbnails exceed the response size limit")
                    rendered_pages.append({
                        "page_number": page_number,
                        "width_points": float(width_points),
                        "height_points": float(height_points),
                        "data_base64": encoded_b64,
                    })
                finally:
                    if image is not None:
                        image.close()
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
            return {"page_count": page_count, "pages": rendered_pages}
        except ValueError:
            raise
        except Exception as error:
            raise ValueError("PDF thumbnails could not be rendered") from error
        finally:
            document.close()

    @classmethod
    def render_pdf(cls, content, target_format, dpi=150, quality=90, pdfium_module=None, cancel_event=None):
        """Render every PDF page to ordered PNG/JPEG entries in a ZIP archive."""
        if not isinstance(content, bytes) or not content or len(content) > cls.MAX_PDF_BYTES:
            raise ValueError("PDF input is empty or exceeds the processing limit")
        if not isinstance(target_format, str):
            raise ValueError("Output format must be PNG or JPEG")
        image_format = target_format.casefold().lstrip(".")
        if image_format == "jpg":
            image_format = "jpeg"
        if image_format not in {"png", "jpeg"}:
            raise ValueError("Output format must be PNG or JPEG")
        if isinstance(dpi, bool) or not isinstance(dpi, int) or not cls.MIN_DPI <= dpi <= cls.MAX_DPI:
            raise ValueError(f"DPI must be a whole number from {cls.MIN_DPI} to {cls.MAX_DPI}")
        if isinstance(quality, bool) or not isinstance(quality, int) or not 1 <= quality <= 100:
            raise ValueError("JPEG quality must be a whole number from 1 to 100")

        if pdfium_module is None:
            try:
                import pypdfium2 as pdfium_module
            except ImportError as error:
                raise RuntimeError("PDF page rendering is unavailable in this installation") from error

        try:
            document = pdfium_module.PdfDocument(content)
        except Exception as error:
            raise ValueError("PDF input could not be opened") from error

        try:
            page_count = len(document)
            if page_count < 1:
                raise ValueError("PDF input contains no pages")
            if page_count > cls.MAX_PAGES:
                raise ValueError(f"PDF input exceeds the {cls.MAX_PAGES}-page rendering limit")

            scale = dpi / 72
            planned_pixels = []
            total_pixels = 0
            for index in range(page_count):
                cls._check_cancel(cancel_event)
                page = document[index]
                try:
                    width_points, height_points = page.get_size()
                    if not all(math.isfinite(value) and value > 0 for value in (width_points, height_points)):
                        raise ValueError("PDF page dimensions are invalid")
                    width_pixels = math.ceil(width_points * scale)
                    height_pixels = math.ceil(height_points * scale)
                    pixels = width_pixels * height_pixels
                    if pixels > cls.MAX_PAGE_PIXELS:
                        raise ValueError("A PDF page exceeds the image rendering pixel limit")
                    total_pixels += pixels
                    if total_pixels > cls.MAX_TOTAL_PIXELS:
                        raise ValueError("PDF pages exceed the total image rendering pixel limit")
                    planned_pixels.append((width_pixels, height_pixels))
                finally:
                    page.close()

            archive_stream = io.BytesIO()
            output_bytes = 0
            with zipfile.ZipFile(archive_stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
                for index, (width_pixels, height_pixels) in enumerate(planned_pixels):
                    cls._check_cancel(cancel_event)
                    page = document[index]
                    bitmap = None
                    image = None
                    try:
                        bitmap = page.render(
                            scale=scale,
                            fill_color=(255, 255, 255, 255),
                            rev_byteorder=True,
                            maybe_alpha=True,
                            draw_annots=True,
                            limit_image_cache=True,
                        )
                        image = bitmap.to_pil().copy()
                        if image_format == "jpeg" and image.mode not in {"RGB", "L"}:
                            image = image.convert("RGB")
                        encoded = io.BytesIO()
                        save_options = {"quality": quality, "optimize": True} if image_format == "jpeg" else {}
                        image.save(encoded, format="JPEG" if image_format == "jpeg" else "PNG", **save_options)
                        output_bytes += encoded.tell()
                        if output_bytes > cls.MAX_OUTPUT_BYTES:
                            raise ValueError("Rendered images exceed the download size limit")
                        ext = "jpg" if image_format == "jpeg" else "png"
                        archive.writestr(f"page-{index + 1:03d}.{ext}", encoded.getvalue())
                    finally:
                        if image is not None:
                            image.close()
                        if bitmap is not None:
                            bitmap.close()
                        page.close()

            return archive_stream.getvalue(), page_count
        except (ValueError, MediaPdfCancelledError):
            raise
        except Exception as error:
            raise ValueError("PDF pages could not be rendered") from error
        finally:
            document.close()

    @staticmethod
    def _check_cancel(cancel_event):
        if cancel_event is not None and cancel_event.is_set():
            raise MediaPdfCancelledError("PDF image export was cancelled")
