"""OfficeKit-owned media operations composed from existing local engines."""

from dataclasses import dataclass, field
import io
import math
import os
import tempfile

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from .engine_conversion_errors import ConversionInputError
from .engine_file_converter import FileConverterEngine
from .engine_media_models import MediaOperation
from .engine_media_crop import crop_rectangle, smart_crop_rectangle
from .engine_media_native import NativeMediaCancelledError, NativeMediaUnavailableError, convert_native_media
from .engine_media_pdf import MediaPdfCancelledError, MediaPdfEngine
from .engine_screenshot_editor import ScreenshotEditError, ScreenshotEditorEngine


class MediaOperationUnavailableError(RuntimeError):
    """The requested typed operation has no packaged adapter on this build."""


@dataclass(frozen=True)
class MediaOutput:
    data: bytes
    extension: str
    media_type: str
    attributes: dict = field(default_factory=dict)


class MediaOptimizerEngine:
    MAX_INPUT_BYTES = 64 * 1024 * 1024
    MAX_FIT_ATTEMPTS = 48
    MAX_FIT_DIMENSION = 10_000
    _EXTENSIONS = {
        "JPEG": ("jpg", "image/jpeg"),
        "PNG": ("png", "image/png"),
        "WEBP": ("webp", "image/webp"),
        "AVIF": ("avif", "image/avif"),
        "JXL": ("jxl", "image/jxl"),
        "BMP": ("bmp", "image/bmp"),
        "TIFF": ("tiff", "image/tiff"),
        "GIF": ("gif", "image/gif"),
        "ICO": ("ico", "image/x-icon"),
        "PDF": ("pdf", "application/pdf"),
    }

    @classmethod
    def execute(cls, input_bytes: bytes, filename: str, operations: list[MediaOperation], cancel_event=None, watermark_image=None) -> MediaOutput:
        if not isinstance(input_bytes, bytes) or not input_bytes or len(input_bytes) > cls.MAX_INPUT_BYTES:
            raise ConversionInputError()
        if not isinstance(filename, str) or not filename or len(filename) > 1024:
            raise ConversionInputError()
        if not isinstance(operations, list) or not 1 <= len(operations) <= 8:
            raise ConversionInputError()
        if any(operation.operation_id == "pdf-pages-to-images" for operation in operations[:-1]):
            raise ConversionInputError()

        source_is_heif = os.path.splitext(filename)[1].lower() in {".heic", ".heif"}
        if source_is_heif:
            from .engine_media_native import NativeMediaUnavailableError, decode_heif_to_png_bytes
            try:
                input_bytes = decode_heif_to_png_bytes(input_bytes)
            except NativeMediaUnavailableError as error:
                raise MediaOperationUnavailableError("HEIC/HEIF decoding is not available in this build.") from error
            filename = os.path.splitext(filename)[0] + ".png"

        current = input_bytes
        output = None
        for operation in operations:
            if not isinstance(operation, MediaOperation):
                raise ConversionInputError()
            current, output = cls._apply(current, filename, operation, cancel_event, watermark_image, source_is_heif)
            source_is_heif = False
        return output

    @classmethod
    def _apply(cls, input_bytes: bytes, filename: str, operation: MediaOperation, cancel_event=None, watermark_image=None, source_is_heif=False):
        operation_id = operation.operation_id
        options = operation.options
        if operation_id == "pdf-lossless-compress":
            from .engine_pdf_advanced import AdvancedPdfEngine

            data, ratio = AdvancedPdfEngine.compress_pdf(input_bytes, options.get("profile", "balanced"))
            return data, MediaOutput(data, "pdf", "application/pdf", {"compression_ratio": ratio, "lossless": True})
        if operation_id == "pdf-visual-optimize":
            data, attributes = MediaPdfEngine.visual_optimize(input_bytes, options, cancel_event)
            return data, MediaOutput(data, "pdf", "application/pdf", attributes)
        if operation_id == "pdf-fit-size":
            data, attributes = MediaPdfEngine.fit_size(input_bytes, options, cancel_event)
            return data, MediaOutput(data, "pdf", "application/pdf", attributes)
        if operation_id == "pdf-pages-to-images":
            from .engine_pdf_images import PdfImageExportEngine

            try:
                data, page_count = PdfImageExportEngine.render_pdf(
                    input_bytes,
                    options.get("target_format", "jpeg"),
                    options.get("dpi", 150),
                    options.get("quality", 80),
                    cancel_event=cancel_event,
                )
            except ValueError as error:
                raise ConversionInputError() from error
            return data, MediaOutput(data, "zip", "application/zip", {
                "page_count": page_count,
                "image_format": options.get("target_format", "jpeg"),
                "dpi": options.get("dpi", 150),
                "quality": options.get("quality", 80),
            })
        if operation_id == "pdf-crop":
            data, attributes = MediaPdfEngine.crop_pages(input_bytes, options)
            return data, MediaOutput(data, "pdf", "application/pdf", attributes)
        if operation_id == "pdf-uncrop":
            data, attributes = MediaPdfEngine.reset_crop_boxes(input_bytes)
            return data, MediaOutput(data, "pdf", "application/pdf", attributes)
        if operation_id.startswith(("video-", "audio-")):
            try:
                data, extension, media_type, attributes = convert_native_media(
                    input_bytes, filename, operation_id, options, cancel_event=cancel_event,
                    watermark_image=watermark_image,
                )
            except NativeMediaUnavailableError as error:
                raise MediaOperationUnavailableError("This media operation is not available in this build.") from error
            except NativeMediaCancelledError:
                raise
            return data, MediaOutput(data, extension, media_type, attributes)
        if not operation_id.startswith("image-"):
            raise MediaOperationUnavailableError("This media operation is not available in this build.")

        format_name, width, height, frame_count = cls._image_info(input_bytes)
        if operation_id == "image-convert":
            target_format = options["target_format"].lower()
            normalized_source = {"jpeg": "jpeg", "tiff": "tiff"}.get(format_name.lower(), format_name.lower())
            if target_format in {"jpg", "jpeg"}:
                target_format = "jpeg"
            if target_format == normalized_source and not options.get("lossless", False):
                extension, media_type = cls._EXTENSIONS[format_name]
                return input_bytes, MediaOutput(input_bytes, extension, media_type, {
                    "width": width, "height": height, "no_op": True,
                })
            data, media_type = FileConverterEngine.convert_image(
                input_bytes, target_format, options.get("quality", 90), lossless=options.get("lossless", False),
            )
            extension, _mime = cls._EXTENSIONS[target_format.upper()]
            attributes = {"width": width, "height": height}
            if options.get("lossless", False):
                attributes["lossless"] = True
            return data, MediaOutput(data, extension, media_type, attributes)
        if operation_id == "image-optimize":
            if format_name not in {"JPEG", "PNG", "WEBP", "AVIF", "JXL"} or frame_count != 1:
                raise MediaOperationUnavailableError("Optimization for this image format is not available in this build.")
            if format_name == "AVIF" and not FileConverterEngine.avif_encoder_available():
                raise MediaOperationUnavailableError("AVIF encoding is not available in this build.")
            if format_name == "JXL" and not FileConverterEngine.jxl_encoder_available():
                raise MediaOperationUnavailableError("JPEG XL encoding is not available in this build.")
            quality = options.get("quality", 82)
            compression = options.get("compression")
            if isinstance(compression, int):
                quality = round(95 - (compression - 5) * 70 / 95)
            elif compression == "adaptive":
                quality = 78 if len(input_bytes) > 8 * 1024 * 1024 else 88
            preserve_metadata = options.get("preserve_metadata", False)
            if options.get("adaptive"):
                with Image.open(io.BytesIO(input_bytes)) as source:
                    has_transparency = (
                        "A" in source.getbands() and source.getchannel("A").getextrema()[0] < 255
                    ) or ("transparency" in source.info)
                candidates = ("png",) if has_transparency else ("jpeg", "png")
                encoded = [
                    (target, *FileConverterEngine.convert_image(
                        input_bytes, target, quality, preserve_metadata, preserve_metadata,
                    ))
                    for target in candidates
                ]
                selected_format, data, media_type = min(encoded, key=lambda candidate: (len(candidate[1]), candidate[0]))
                extension, _media = cls._EXTENSIONS[selected_format.upper()]
                return data, MediaOutput(data, extension, media_type, {
                    "width": width, "height": height, "adaptive": True,
                    "selected_format": selected_format,
                })
            if source_is_heif:
                data, media_type = FileConverterEngine.convert_image(
                    input_bytes, "webp", quality, preserve_metadata=False, preserve_color_profile=False,
                )
                attributes = {"width": width, "height": height, "converted_from": "heif"}
                if compression is not None:
                    attributes["compression"] = compression
                return data, MediaOutput(data, "webp", media_type, attributes)
            data, media_type = FileConverterEngine.convert_image(
                input_bytes, format_name.lower(), quality,
                preserve_metadata=preserve_metadata, preserve_color_profile=preserve_metadata,
            )
            attributes = {"width": width, "height": height}
            if compression is not None:
                attributes["compression"] = compression
            if compression == "adaptive":
                attributes["quality"] = quality
            return data, MediaOutput(data, cls._EXTENSIONS[format_name][0], media_type, attributes)
        if operation_id == "image-fit-size":
            result = cls._fit_image(input_bytes, options)
            return result.data, result
        if operation_id == "image-resize":
            data, (new_width, new_height) = FileConverterEngine.resize_image(
                input_bytes, options["max_width"], options["max_height"]
            )
            new_format, _width, _height, _frames = cls._image_info(data)
            extension, media_type = cls._EXTENSIONS[new_format]
            return data, MediaOutput(data, extension, media_type, {"width": new_width, "height": new_height})
        if operation_id == "image-strip-metadata":
            data = FileConverterEngine.strip_exif(input_bytes)
            result_format, new_width, new_height, _frames = cls._image_info(data)
            extension, media_type = cls._EXTENSIONS[result_format]
            return data, MediaOutput(data, extension, media_type, {
                "width": new_width, "height": new_height, "metadata_removed": True,
            })
        if operation_id == "image-crop":
            if frame_count != 1:
                raise MediaOperationUnavailableError("Cropping animated images is not available in this build.")
            try:
                geometry, crop_attributes = cls._image_crop_options(input_bytes, format_name, width, height, options, cancel_event)
                data, (new_width, new_height) = ScreenshotEditorEngine.edit_image(
                    input_bytes,
                    [{"type": "crop", **geometry}],
                    target_format="jpeg" if format_name == "JPEG" else "png",
                )
            except NativeMediaUnavailableError as error:
                raise MediaOperationUnavailableError("Smart cropping is not available in this build.") from error
            except (ScreenshotEditError, ValueError, OSError) as error:
                raise ConversionInputError() from error
            output_format = "JPEG" if format_name == "JPEG" else "PNG"
            extension, media_type = cls._EXTENSIONS[output_format]
            return data, MediaOutput(data, extension, media_type, {"width": new_width, "height": new_height, **crop_attributes})
        if operation_id == "image-watermark":
            data, output_format = cls._watermark(input_bytes, options)
            result_format, new_width, new_height, _frames = cls._image_info(data)
            extension, media_type = cls._EXTENSIONS[result_format]
            return data, MediaOutput(data, extension, media_type, {
                "width": new_width, "height": new_height, "watermarked": True,
                "output_format": output_format,
            })
        if operation_id == "image-watermark-overlay":
            if watermark_image is None:
                raise MediaOperationUnavailableError("Choose a watermark image before preparing this copy.")
            data, output_format = cls._watermark_overlay(input_bytes, watermark_image, options)
            result_format, new_width, new_height, _frames = cls._image_info(data)
            extension, media_type = cls._EXTENSIONS[result_format]
            return data, MediaOutput(data, extension, media_type, {
                "width": new_width, "height": new_height, "watermarked": True,
                "output_format": output_format,
            })
        raise MediaOperationUnavailableError("This image operation is not available in this build.")

    @classmethod
    def _image_crop_options(cls, input_bytes, format_name, width, height, options, cancel_event):
        if "aspect_ratio" not in options:
            return {key: options[key] for key in ("x", "y", "width", "height")}, {}
        with Image.open(io.BytesIO(input_bytes)) as image:
            if image.getexif().get(274) in {5, 6, 7, 8}:
                width, height = height, width
        attributes = {}
        if options.get("smart_crop"):
            from .engine_media_native import probe_smart_crop_bounds

            with tempfile.TemporaryDirectory(prefix="officekit-image-crop-") as workspace:
                source_path = os.path.join(workspace, "source." + format_name.lower())
                descriptor = os.open(source_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as source:
                    source.write(input_bytes)
                saliency = probe_smart_crop_bounds(source_path, "image", cancel_event=cancel_event)
                if cancel_event is not None and cancel_event.is_set():
                    raise NativeMediaCancelledError()
            if (saliency["sourceWidth"], saliency["sourceHeight"]) != (width, height):
                raise ConversionInputError("Smart crop dimensions do not match the selected image.")
            geometry = smart_crop_rectangle(width, height, options["aspect_ratio"], saliency)
            attributes.update(smart_crop=True, saliency_detected=saliency["detected"])
        else:
            geometry = crop_rectangle(width, height, options["aspect_ratio"])
        attributes.update(x=geometry["x"], y=geometry["y"])
        return geometry, attributes

    @classmethod
    def _image_info(cls, input_bytes: bytes):
        try:
            with Image.open(io.BytesIO(input_bytes)) as image:
                format_name = (image.format or "").upper()
                width, height = image.size
                frame_count = getattr(image, "n_frames", 1)
                if (
                    format_name not in cls._EXTENSIONS
                    or width < 1 or height < 1
                    or width > FileConverterEngine.MAX_RESIZE_DIMENSION
                    or height > FileConverterEngine.MAX_RESIZE_DIMENSION
                    or width * height > FileConverterEngine.MAX_RESIZE_FRAME_PIXELS
                ):
                    raise ConversionInputError()
                return format_name, width, height, frame_count
        except ConversionInputError:
            raise
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
            raise ConversionInputError() from None

    @classmethod
    def _image_dpi(cls, input_bytes: bytes):
        cls._image_info(input_bytes)
        try:
            with Image.open(io.BytesIO(input_bytes)) as image:
                dpi = image.info.get("dpi")
                if isinstance(dpi, (int, float)) and not isinstance(dpi, bool):
                    axes = (float(dpi), float(dpi))
                elif isinstance(dpi, (tuple, list)) and len(dpi) == 2:
                    axes = tuple(float(value) for value in dpi)
                else:
                    return None
                if any(not math.isfinite(value) or not 1 <= value <= 100_000 for value in axes):
                    return None
                return axes
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, OverflowError, TypeError, ValueError):
            raise ConversionInputError() from None

    @classmethod
    def _fit_image(cls, input_bytes: bytes, options: dict) -> MediaOutput:
        format_name, original_width, original_height, frame_count = cls._image_info(input_bytes)
        if frame_count != 1 or format_name not in {"JPEG", "PNG", "WEBP", "AVIF", "JXL", "BMP", "TIFF", "ICO"}:
            raise MediaOperationUnavailableError("Size targeting for this image format is not available in this build.")

        target_bytes = options["target_bytes"]
        target_format = options.get("target_format", "webp")
        low_quality = options.get("min_quality", 30)
        high_quality = options.get("max_quality", 90)
        attempts = 0
        final_data = b""
        final_size = (original_width, original_height)
        final_quality = low_quality

        for attempt in range(cls.MAX_FIT_ATTEMPTS):
            attempts = attempt + 1
            factor = 0.82 ** attempt
            width = max(1, math.floor(original_width * factor))
            height = max(1, math.floor(original_height * factor))
            if attempt and (width, height) == final_size:
                continue
            source = input_bytes
            if attempt:
                source, final_size = FileConverterEngine.resize_image(input_bytes, width, height)
            else:
                final_size = (original_width, original_height)
            candidate, media_type = FileConverterEngine.convert_image(source, target_format, high_quality)
            if len(candidate) <= target_bytes:
                return cls._fit_result(candidate, target_format, media_type, final_size, high_quality, attempts, target_bytes)
            min_candidate, media_type = FileConverterEngine.convert_image(source, target_format, low_quality)
            final_data = min_candidate
            final_quality = low_quality
            if len(min_candidate) <= target_bytes:
                best = min_candidate
                best_quality = low_quality
                lower, upper = low_quality + 1, high_quality - 1
                while lower <= upper:
                    quality = (lower + upper) // 2
                    encoded, media_type = FileConverterEngine.convert_image(source, target_format, quality)
                    if len(encoded) <= target_bytes:
                        best, best_quality = encoded, quality
                        lower = quality + 1
                    else:
                        upper = quality - 1
                return cls._fit_result(best, target_format, media_type, final_size, best_quality, attempts, target_bytes)

        return cls._fit_result(
            final_data, target_format, media_type, final_size, final_quality, attempts,
            target_bytes, target_met=False,
        )

    @classmethod
    def _fit_result(cls, data, target_format, media_type, dimensions, quality, attempts, target_bytes, target_met=True):
        target_format = target_format.upper()
        extension, _ = cls._EXTENSIONS[target_format]
        return MediaOutput(data, extension, media_type, {
            "width": dimensions[0], "height": dimensions[1], "quality": quality,
            "attempts": attempts, "target_bytes": target_bytes,
            "actual_bytes": len(data), "target_met": target_met,
        })

    @classmethod
    def _watermark(cls, input_bytes, options):
        format_name, width, height, frame_count = cls._image_info(input_bytes)
        if frame_count != 1 or width * height > 40_000_000:
            raise MediaOperationUnavailableError("Watermarking this image is not available in this build.")
        try:
            with Image.open(io.BytesIO(input_bytes)) as source:
                image = source.convert("RGBA")
            overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            text = options["text"]
            font = ImageFont.load_default(size=max(10, min(48, width // 24)))
            text_box = draw.textbbox((0, 0), text, font=font)
            text_width, text_height = text_box[2] - text_box[0], text_box[3] - text_box[1]
            margin = max(8, min(width, height) // 40)
            position = options.get("position", "bottom-right")
            x = margin if "left" in position else width - text_width - margin
            y = margin if "top" in position else height - text_height - margin
            if position == "center":
                x, y = (width - text_width) // 2, (height - text_height) // 2
            alpha = round(255 * options.get("opacity", 70) / 100)
            draw.text((max(0, x), max(0, y)), text, font=font, fill=(255, 255, 255, alpha), stroke_width=1, stroke_fill=(0, 0, 0, alpha))
            image = Image.alpha_composite(image, overlay)
            output_format = "JPEG" if format_name == "JPEG" else "PNG"
            if output_format == "JPEG":
                image = image.convert("RGB")
            stream = io.BytesIO()
            if output_format == "JPEG":
                image.save(stream, format=output_format, quality=90)
            else:
                image.save(stream, format=output_format)
            data = stream.getvalue()
            if len(data) > FileConverterEngine.MAX_CONVERT_OUTPUT_BYTES:
                raise ConversionInputError()
            return data, output_format
        except ConversionInputError:
            raise
        except (OSError, ValueError, Image.DecompressionBombError):
            raise ConversionInputError() from None

    @classmethod
    def _watermark_overlay(cls, input_bytes, watermark_bytes, options):
        format_name, width, height, frame_count = cls._image_info(input_bytes)
        _mark_format, mark_width, mark_height, mark_frames = cls._image_info(watermark_bytes)
        if frame_count != 1 or mark_frames != 1 or mark_width * mark_height > 20_000_000:
            raise MediaOperationUnavailableError("Watermarking these image formats is not available in this build.")
        try:
            with Image.open(io.BytesIO(input_bytes)) as source:
                base = source.convert("RGBA")
            with Image.open(io.BytesIO(watermark_bytes)) as mark_source:
                mark = mark_source.convert("RGBA")
            target_width = max(1, round(width * options.get("size_percent", 18) / 100))
            target_height = max(1, round(mark.height * target_width / mark.width))
            if target_height > height:
                target_height = height
                target_width = max(1, round(mark.width * target_height / mark.height))
            mark = mark.resize((target_width, target_height), Image.Resampling.LANCZOS)
            opacity = options.get("opacity_percent", 72) / 100
            alpha = mark.getchannel("A").point(lambda value: round(value * opacity))
            mark.putalpha(alpha)
            margin = round(min(width, height) * options.get("margin_percent", 4) / 100)
            placement = options.get("placement", "bottom-right")
            if placement == "tile":
                gap_x = max(margin, target_width // 2)
                gap_y = max(margin, target_height // 2)
                step_x, step_y = target_width + gap_x, target_height + gap_y
                xs = range(margin, width - target_width + 1, step_x)
                ys = range(margin, height - target_height + 1, step_y)
                if len(xs) == 0 or len(ys) == 0:
                    base.alpha_composite(mark, ((width - target_width) // 2, (height - target_height) // 2))
                for y in ys:
                    for x in xs:
                        base.alpha_composite(mark, (x, y))
            else:
                x = margin if placement.endswith("left") else width - target_width - margin
                y = margin if placement.startswith("top") else height - target_height - margin
                if placement == "center":
                    x, y = (width - target_width) // 2, (height - target_height) // 2
                base.alpha_composite(mark, (max(0, x), max(0, y)))
            output_format = "JPEG" if format_name == "JPEG" else "PNG"
            if output_format == "JPEG":
                base = base.convert("RGB")
            stream = io.BytesIO()
            save_options = {"quality": 90} if output_format == "JPEG" else {}
            base.save(stream, format=output_format, **save_options)
            data = stream.getvalue()
            if len(data) > FileConverterEngine.MAX_CONVERT_OUTPUT_BYTES:
                raise ConversionInputError()
            return data, output_format
        except ConversionInputError:
            raise
        except (OSError, ValueError, Image.DecompressionBombError):
            raise ConversionInputError() from None
