"""Honest, build-specific Media Toolkit operation availability."""

from importlib.util import find_spec
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr

from .engine_file_converter import avif_encoder_available, jxl_encoder_available
from .engine_media_native import native_audio_format_available, native_av1_encoder_available, native_media_available, native_media_operation_available, native_video_format_available


class MediaCapabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MediaCapabilityOperation(MediaCapabilityModel):
    id: StrictStr
    label: StrictStr
    available: StrictBool
    formats: list[StrictStr]
    reason: StrictStr | None


class MediaCapabilityGroup(MediaCapabilityModel):
    id: Literal["image", "video", "pdf", "audio"]
    label: StrictStr
    operations: list[MediaCapabilityOperation]


class MediaCapabilitiesResponse(MediaCapabilityModel):
    version: StrictInt
    maxInputBytes: StrictInt
    maxBatchItems: StrictInt
    media: list[MediaCapabilityGroup]

MEDIA_OPERATIONS = (
    ("image-optimize", "Optimize image", "image", True, ["jpg", "jpeg", "png", "webp"]),
    ("image-fit-size", "Fit image to size", "image", True, ["jpg", "jpeg", "png", "webp"]),
    ("image-convert", "Convert image", "image", True, ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff", "ico", "pdf"]),
    ("image-resize", "Resize image", "image", True, ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff", "ico"]),
    ("image-crop", "Crop image", "image", True, ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"]),
    ("image-strip-metadata", "Remove image metadata", "image", True, ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"]),
    ("image-watermark", "Add text watermark", "image", True, ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"]),
    ("image-watermark-overlay", "Add image watermark", "image", True, ["jpg", "jpeg", "png", "webp", "bmp", "tif", "tiff"]),
    ("video-optimize", "Optimize / convert video", "video", False, []),
    ("video-hevc-convert", "Convert video to HEVC", "video", False, []),
    ("video-fit-size", "Fit video to size", "video", False, []),
    ("video-crop", "Crop video", "video", False, []),
    ("video-resize", "Resize video", "video", False, []),
    ("video-speed", "Change video speed", "video", False, []),
    ("video-mute", "Remove video audio", "video", False, []),
    ("video-strip-metadata", "Remove video metadata", "video", False, []),
    ("video-to-gif", "Convert video to GIF", "video", False, []),
    ("video-watermark-overlay", "Add video watermark", "video", False, []),
    ("pdf-lossless-compress", "Lossless PDF compression", "pdf", True, ["pdf"]),
    ("pdf-visual-optimize", "Visual PDF compression", "pdf", True, ["pdf"]),
    ("pdf-fit-size", "Fit PDF to size", "pdf", True, ["pdf"]),
    ("pdf-crop", "Fit PDF pages", "pdf", True, ["pdf"]),
    ("pdf-uncrop", "Restore PDF crop", "pdf", True, ["pdf"]),
    ("audio-optimize", "Optimize / convert audio", "audio", False, []),
    ("audio-convert", "Convert audio", "audio", False, []),
    ("audio-fit-size", "Fit audio to size", "audio", False, []),
    ("audio-normalize", "Normalize loudness", "audio", False, []),
    ("audio-artwork", "Resize embedded artwork", "audio", False, []),
)


def media_capabilities():
    """Return a bounded catalog including unavailable operations for discovery."""
    pdf_raster_ready = find_spec("pypdfium2") is not None and find_spec("reportlab") is not None
    pdf_crop_ready = find_spec("pypdf") is not None
    avif_ready = avif_encoder_available()
    jxl_ready = jxl_encoder_available()
    def operation_state(operation_id, available, formats):
        runtime_image_format_operations = {
            "image-convert", "image-optimize", "image-fit-size", "image-resize", "image-strip-metadata",
        }
        if avif_ready and operation_id in runtime_image_format_operations:
            formats = [*formats, "avif"]
        if jxl_ready and operation_id in runtime_image_format_operations:
            formats = [*formats, "jxl"]
        if operation_id.startswith("video-") and native_media_operation_available(operation_id):
            if operation_id == "video-hevc-convert":
                return True, ["mov"]
            if operation_id == "video-to-gif":
                return True, ["gif"]
            if operation_id in {"video-speed", "video-mute", "video-strip-metadata", "video-crop", "video-resize", "video-watermark-overlay"}:
                return True, ["mov"]
            formats = ["m4v", "mov"] if native_media_available("video") else []
            if native_av1_encoder_available() and operation_id in {"video-optimize", "video-fit-size"}:
                formats.append("av1")
            if operation_id in {"video-optimize", "video-fit-size"}:
                formats.extend(target for target in ("mp4", "webm", "x265") if native_video_format_available(target))
            return True, formats
        if operation_id.startswith("audio-") and native_media_operation_available(operation_id):
            if operation_id in {"audio-artwork", "audio-normalize"}:
                return True, ["m4a"]
            formats = ["m4a", "wav", "aiff"]
            if native_audio_format_available("flac"):
                formats.append("flac")
            if native_audio_format_available("mp3"):
                formats.append("mp3")
            return True, formats
        if operation_id in {"pdf-visual-optimize", "pdf-fit-size"} and pdf_raster_ready:
            return True, ["pdf"]
        if operation_id in {"pdf-crop", "pdf-uncrop"} and pdf_crop_ready:
            return True, ["pdf"]
        return available, formats
    return {
        "version": 1,
        "maxInputBytes": 67_108_864,
        "maxBatchItems": 30,
        "media": [
            {
                "id": media_id,
                "label": label,
                "operations": [
                    {
                        "id": operation_id,
                        "label": operation_label,
                        "available": operation_state(operation_id, available, formats)[0],
                        "formats": operation_state(operation_id, available, formats)[1],
                        "reason": (
                            None if operation_state(operation_id, available, formats)[0]
                            else "A local engine for this operation is not packaged in this build yet."
                        ),
                    }
                    for operation_id, operation_label, group_id, available, formats in MEDIA_OPERATIONS
                    if group_id == media_id
                ],
            }
            for media_id, label in (("image", "Images"), ("video", "Video"), ("pdf", "PDF"), ("audio", "Audio"))
        ],
    }
