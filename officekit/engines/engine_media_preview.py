"""Bounded local previews for the files selected in the Media Toolkit: images, PDFs, video and audio."""

import base64
import io
import os
import threading

from PIL import Image, ImageOps

from .engine_conversion_errors import ConversionInputError

MAX_PREVIEW_SOURCE_BYTES = 64 * 1024 * 1024
MAX_PREVIEW_SOURCE_PIXELS = 100_000_000
MAX_PREVIEW_EDGE = 2048
MIN_PREVIEW_EDGE = 32
MAX_PREVIEW_PDF_PAGE_POINTS = 14_400
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".ico", ".heic", ".heif"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".wav", ".aiff", ".aif", ".flac", ".caf", ".ogg", ".opus"}
PDF_EXTENSIONS = {".pdf"}
# Kept for callers that only draw pictures.
PREVIEW_EXTENSIONS = IMAGE_EXTENSIONS
# pdfium is not thread safe; the API runs routes in a thread pool.
_PDFIUM_LOCK = threading.Lock()


class MediaPreviewUnavailableError(Exception):
    """The file is a type this build cannot draw a preview for."""


class MediaPreviewLockedError(Exception):
    """The PDF is password protected, so its pages cannot be drawn."""


class MediaPreviewEngine:
    @classmethod
    def kind(cls, filename):
        """``image``, ``pdf``, ``video``, ``audio``, or None when the type has no preview."""
        if not isinstance(filename, str):
            return None
        extension = os.path.splitext(filename)[1].lower()
        for name, extensions in (("image", IMAGE_EXTENSIONS), ("pdf", PDF_EXTENSIONS), ("video", VIDEO_EXTENSIONS), ("audio", AUDIO_EXTENSIONS)):
            if extension in extensions:
                return name
        return None

    @classmethod
    def supports(cls, filename):
        return cls.kind(filename) == "image"

    @staticmethod
    def _check_edge(max_edge):
        if type(max_edge) is not int or not MIN_PREVIEW_EDGE <= max_edge <= MAX_PREVIEW_EDGE:
            raise ConversionInputError()

    @classmethod
    def render(cls, input_bytes, filename, max_edge=640):
        """Return the original pixel size and a thumbnail of at most ``max_edge`` pixels on its long side."""
        if not isinstance(input_bytes, bytes) or not input_bytes or len(input_bytes) > MAX_PREVIEW_SOURCE_BYTES:
            raise ConversionInputError()
        cls._check_edge(max_edge)
        if not cls.supports(filename):
            raise MediaPreviewUnavailableError()
        if os.path.splitext(filename)[1].lower() in {".heic", ".heif"}:
            from .engine_media_native import NativeMediaUnavailableError, decode_heif_to_png_bytes
            try:
                input_bytes = decode_heif_to_png_bytes(input_bytes)
            except NativeMediaUnavailableError as error:
                raise MediaPreviewUnavailableError() from error
        try:
            with Image.open(io.BytesIO(input_bytes)) as image:
                width, height = image.size
                if not (0 < width and 0 < height and width * height <= MAX_PREVIEW_SOURCE_PIXELS):
                    raise ConversionInputError()
                # Report the pixel size as the picture is displayed: a rotated phone photo swaps its sides.
                turned = image.getexif().get(0x0112) in {5, 6, 7, 8}
                shown_width, shown_height = (height, width) if turned else (width, height)
                image.draft("RGB", (max_edge * 2, max_edge * 2))
                image = ImageOps.exif_transpose(image)
                if getattr(image, "n_frames", 1) > 1:
                    image.seek(0)
                has_alpha = image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info
                image = image.convert("RGBA" if has_alpha else "RGB")
                image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                data, content_type = cls._encode(image, has_alpha)
        except ConversionInputError:
            raise
        except (OSError, ValueError, Image.DecompressionBombError, SyntaxError) as error:
            raise ConversionInputError() from error
        return {
            "kind": "image",
            "width": shown_width,
            "height": shown_height,
            "contentType": content_type,
            "dataBase64": base64.b64encode(data).decode("ascii"),
        }

    @staticmethod
    def _encode(image, has_alpha):
        buffer = io.BytesIO()
        if has_alpha:
            image.save(buffer, "PNG", optimize=True)
            return buffer.getvalue(), "image/png"
        image.save(buffer, "JPEG", quality=82, optimize=True)
        return buffer.getvalue(), "image/jpeg"

    @classmethod
    def render_pdf(cls, input_bytes, max_edge=640, page=1):
        """Draw one page (1-based) of a PDF and report the page count; password-protected files raise MediaPreviewLockedError."""
        if not isinstance(input_bytes, bytes) or not input_bytes or len(input_bytes) > MAX_PREVIEW_SOURCE_BYTES:
            raise ConversionInputError()
        cls._check_edge(max_edge)
        if type(page) is not int or page < 1:
            raise ConversionInputError()
        try:
            import pypdfium2 as pdfium
        except ImportError as error:
            raise MediaPreviewUnavailableError() from error
        with _PDFIUM_LOCK:
            try:
                document = pdfium.PdfDocument(input_bytes)
            except pdfium.PdfiumError as error:
                if "password" in str(error).lower():
                    raise MediaPreviewLockedError() from error
                raise ConversionInputError() from error
            try:
                page_count = len(document)
                if not 1 <= page_count <= 100_000 or page > page_count:
                    raise ConversionInputError()
                pdf_page = document[page - 1]
                try:
                    page_width, page_height = pdf_page.get_size()
                    if not (0 < page_width <= MAX_PREVIEW_PDF_PAGE_POINTS and 0 < page_height <= MAX_PREVIEW_PDF_PAGE_POINTS):
                        raise ConversionInputError()
                    scale = max_edge / max(page_width, page_height)
                    bitmap = pdf_page.render(scale=scale)
                    image = bitmap.to_pil().convert("RGB")
                finally:
                    pdf_page.close()
            except ConversionInputError:
                raise
            except (pdfium.PdfiumError, ValueError, OSError, MemoryError) as error:
                raise ConversionInputError() from error
            finally:
                document.close()
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        data, content_type = cls._encode(image, False)
        return {
            "kind": "pdf",
            "width": int(round(page_width)),
            "height": int(round(page_height)),
            "contentType": content_type,
            "dataBase64": base64.b64encode(data).decode("ascii"),
            "pageCount": page_count,
            "page": page,
        }

    @classmethod
    def render_av(cls, source, filename, kind, max_edge=640, position=10):
        """A video frame, or an audio waveform (plus cover art when the file has it), drawn on this Mac."""
        cls._check_edge(max_edge)
        if kind not in {"video", "audio"} or cls.kind(filename) != kind:
            raise MediaPreviewUnavailableError()
        from .engine_media_native import NativeMediaUnavailableError, render_media_preview
        try:
            details = render_media_preview(source, os.path.splitext(filename)[1], kind, max_edge, position)
        except NativeMediaUnavailableError as error:
            raise MediaPreviewUnavailableError() from error
        result = {"kind": kind, "durationSeconds": round(details["duration"], 2)}
        if kind == "video":
            result.update(width=details["width"], height=details["height"])
        else:
            result["peaks"] = details["peaks"]
        if details["image"] is not None:
            result["contentType"] = "image/jpeg"
            result["dataBase64"] = base64.b64encode(details["image"]).decode("ascii")
        return result
