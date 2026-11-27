"""Strict contracts for media operations exposed by the local Media Toolkit."""

from decimal import Decimal, InvalidOperation
import math
import re
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, field_validator, model_validator

from .engine_media_devices import resolve_device_aspect, resolve_paper_aspect
from .engine_media_naming import validate_output_name_template
from .engine_media_crop import parse_crop_aspect_ratio


MAX_MEDIA_JOB_ITEMS = 30
MAX_MEDIA_OPERATIONS = 8
MAX_MEDIA_OUTPUT_BYTES = 32 * 1024**3
MAX_IMAGE_OUTPUT_BYTES = 64 * 1024**2


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class EmptyOptions(StrictModel):
    pass


class ImageConvertOptions(StrictModel):
    target_format: Literal["png", "jpeg", "webp", "bmp", "tiff", "ico", "pdf", "avif", "jxl"] = Field(alias="targetFormat")
    quality: StrictInt = Field(default=90, ge=1, le=100)
    lossless: bool = False

    @model_validator(mode="after")
    def lossless_format(self):
        if self.lossless and self.target_format not in {"webp", "jxl"}:
            raise ValueError("Lossless conversion is supported only for WebP and JPEG XL")
        return self


class ImageOptimizeOptions(StrictModel):
    quality: StrictInt = Field(default=82, ge=1, le=100)
    preserve_metadata: bool = Field(default=False, alias="preserveMetadata")
    compression: StrictInt | Literal["adaptive"] | None = None
    adaptive: bool = False

    @field_validator("compression")
    @classmethod
    def compression_range(cls, value):
        if isinstance(value, int) and not 5 <= value <= 100:
            raise ValueError("Image compression factor must be between 5 and 100")
        return value


class ImageFitOptions(StrictModel):
    target_bytes: StrictInt = Field(alias="targetBytes", ge=1, le=MAX_MEDIA_OUTPUT_BYTES)
    target_format: Literal["jpeg", "webp", "png", "avif", "jxl"] = Field(default="webp", alias="targetFormat")
    min_quality: StrictInt = Field(default=30, alias="minQuality", ge=1, le=100)
    max_quality: StrictInt = Field(default=90, alias="maxQuality", ge=1, le=100)

    @model_validator(mode="after")
    def quality_order(self):
        if self.min_quality > self.max_quality:
            raise ValueError("Minimum quality cannot exceed maximum quality")
        return self


class ResizeOptions(StrictModel):
    max_width: StrictInt = Field(alias="maxWidth", ge=1, le=10_000)
    max_height: StrictInt = Field(alias="maxHeight", ge=1, le=10_000)


class VideoResizeOptions(ResizeOptions):
    fps: StrictInt | None = Field(default=None, ge=1, le=120)


class CropOptions(StrictModel):
    x: StrictInt | None = Field(default=None, ge=0, le=40_000)
    y: StrictInt | None = Field(default=None, ge=0, le=40_000)
    width: StrictInt | None = Field(default=None, ge=1, le=40_000)
    height: StrictInt | None = Field(default=None, ge=1, le=40_000)
    aspect_ratio: StrictStr | None = Field(default=None, alias="aspectRatio", min_length=3, max_length=15)
    smart_crop: bool = Field(default=False, alias="smartCrop")

    @field_validator("aspect_ratio")
    @classmethod
    def normalize_aspect_ratio(cls, value):
        ratio = parse_crop_aspect_ratio(value)
        return f"{ratio.numerator}:{ratio.denominator}"

    @model_validator(mode="after")
    def require_one_crop_target(self):
        rectangle_fields = {"x", "y", "width", "height"}
        if self.aspect_ratio is not None:
            if self.model_fields_set & rectangle_fields:
                raise ValueError("Choose a crop rectangle or aspectRatio, not both")
        elif any(getattr(self, field) is None for field in rectangle_fields):
            raise ValueError("Choose a complete crop rectangle or aspectRatio")
        elif self.smart_crop:
            raise ValueError("smartCrop requires aspectRatio")
        return self


class WatermarkOptions(StrictModel):
    text: str = Field(min_length=1, max_length=256)
    opacity: StrictInt = Field(default=70, ge=1, le=100)
    position: Literal["top-left", "top-right", "bottom-left", "bottom-right", "center"] = "bottom-right"


class ImageWatermarkOverlayOptions(StrictModel):
    placement: Literal["bottom-right", "bottom-left", "top-right", "top-left", "center", "tile"] = "bottom-right"
    margin_percent: StrictInt = Field(default=4, alias="marginPercent", ge=0, le=20)
    size_percent: StrictInt = Field(default=18, alias="sizePercent", ge=5, le=60)
    opacity_percent: StrictInt = Field(default=72, alias="opacityPercent", ge=10, le=100)


class VideoOptimizeOptions(StrictModel):
    target_format: Literal["m4v", "mov", "mp4", "webm", "x265", "av1"] = Field(default="m4v", alias="targetFormat")
    quality: Literal["smaller", "balanced", "higher"] = "balanced"
    compression: StrictInt | Literal["adaptive"] | None = None
    @field_validator("compression")
    @classmethod
    def compression_range(cls, value):
        if isinstance(value, int) and not 5 <= value <= 100:
            raise ValueError("Video compression factor must be between 5 and 100")
        return value
    target_bytes: StrictInt | None = Field(default=None, alias="targetBytes", ge=1, le=MAX_MEDIA_OUTPUT_BYTES)

    @model_validator(mode="after")
    def compression_requires_h264_mp4(self):
        if self.compression is not None and self.target_format != "mp4":
            raise ValueError("Compression factor is supported only for H.264 MP4 output")
        return self


class VideoFitOptions(StrictModel):
    target_format: Literal["m4v", "mov", "mp4", "webm", "x265", "av1"] = Field(default="m4v", alias="targetFormat")
    target_bytes: StrictInt = Field(alias="targetBytes", ge=1, le=MAX_MEDIA_OUTPUT_BYTES)
    quality: Literal["smaller", "balanced", "higher"] = "balanced"
    compression: StrictInt | Literal["adaptive"] | None = None
    @field_validator("compression")
    @classmethod
    def compression_range(cls, value):
        if isinstance(value, int) and not 5 <= value <= 100:
            raise ValueError("Video compression factor must be between 5 and 100")
        return value

    @model_validator(mode="after")
    def compression_requires_h264_mp4(self):
        if self.compression is not None and self.target_format != "mp4":
            raise ValueError("Compression factor is supported only for H.264 MP4 output")
        return self


class SpeedOptions(StrictModel):
    factor_percent: StrictInt = Field(alias="factorPercent", ge=25, le=400)


class GifOptions(StrictModel):
    fps: StrictInt = Field(default=15, ge=1, le=60)
    max_width: StrictInt = Field(default=720, alias="maxWidth", ge=16, le=1920)
    max_duration_seconds: StrictInt = Field(default=30, alias="maxDurationSeconds", ge=1, le=60)


class PdfLosslessOptions(StrictModel):
    profile: Literal["fast", "balanced", "maximum"] = "balanced"


class PdfVisualOptions(StrictModel):
    quality: StrictInt = Field(default=75, ge=1, le=100)
    dpi: StrictInt = Field(default=150, ge=72, le=300)


class PdfFitOptions(StrictModel):
    target_bytes: StrictInt = Field(alias="targetBytes", ge=1, le=MAX_MEDIA_OUTPUT_BYTES)
    quality: StrictInt = Field(default=75, ge=1, le=100)
    dpi: StrictInt = Field(default=150, ge=72, le=300)


class PdfPagesToImagesOptions(StrictModel):
    target_format: Literal["png", "jpeg"] = Field(default="jpeg", alias="targetFormat")
    quality: StrictInt = Field(default=80, ge=1, le=100)
    dpi: StrictInt = Field(default=150, ge=36, le=300)


class PdfCropOptions(StrictModel):
    page_size: Literal["a4", "letter", "mobile", "tablet"] | None = Field(default=None, alias="pageSize")
    aspect_ratio: StrictStr | None = Field(default=None, alias="aspectRatio", min_length=3, max_length=15)
    device_name: StrictStr | None = Field(default=None, alias="deviceName", min_length=1, max_length=80)
    paper_size_name: StrictStr | None = Field(default=None, alias="paperSizeName", min_length=1, max_length=80)
    page_layout: Literal["auto", "portrait", "landscape"] = Field(default="auto", alias="pageLayout")
    extend: bool = False

    @field_validator("aspect_ratio")
    @classmethod
    def validate_aspect_ratio(cls, value):
        if value is None:
            return value
        parts = value.split(":")
        if len(parts) != 2 or not all(re.fullmatch(r"[0-9]+(?:\.[0-9]{1,4})?", part, flags=re.ASCII) for part in parts):
            raise ValueError("Aspect ratio must use width:height, such as 16:9 or 1.91:1")
        try:
            decimals = max(len(part.partition(".")[2]) for part in parts)
            scale = 10 ** decimals
            width, height = (int(Decimal(part) * scale) for part in parts)
        except (InvalidOperation, ValueError):
            raise ValueError("Aspect ratio dimensions are invalid") from None
        if width <= 0 or height <= 0 or width / height < 0.1 or width / height > 10:
            raise ValueError("Aspect ratio dimensions must be between 1:10 and 10:1")
        common = math.gcd(width, height)
        width //= common
        height //= common
        if max(width, height) > 10000:
            raise ValueError("Reduced aspect ratio dimensions must not exceed 10,000")
        return f"{min(width, height)}:{max(width, height)}"

    @model_validator(mode="after")
    def require_crop_target(self):
        targets = (self.page_size, self.aspect_ratio, self.device_name, self.paper_size_name)
        if sum(value is not None for value in targets) != 1:
            raise ValueError("Choose exactly one pageSize, aspectRatio, deviceName, or paperSizeName")
        if self.device_name is not None:
            resolve_device_aspect(self.device_name)
        if self.paper_size_name is not None:
            resolve_paper_aspect(self.paper_size_name)
        return self


class AudioOptimizeOptions(StrictModel):
    target_format: Literal["m4a", "wav", "aiff", "flac", "mp3"] = Field(default="m4a", alias="targetFormat")
    bitrate_kbps: StrictInt = Field(default=192, alias="bitrateKbps", ge=32, le=640)
    compression: StrictInt | Literal["adaptive"] | None = None
    no_upscale: bool = Field(default=False, alias="noUpscale")

    @field_validator("compression")
    @classmethod
    def compression_range(cls, value):
        if isinstance(value, int) and not 5 <= value <= 100:
            raise ValueError("Audio compression factor must be between 5 and 100")
        return value


class AudioConvertOptions(StrictModel):
    target_format: Literal["m4a", "wav", "aiff", "flac", "mp3"] = Field(default="m4a", alias="targetFormat")
    bitrate_kbps: StrictInt = Field(default=192, alias="bitrateKbps", ge=32, le=640)


class AudioFitOptions(StrictModel):
    target_bytes: StrictInt = Field(alias="targetBytes", ge=1, le=MAX_MEDIA_OUTPUT_BYTES)
    target_format: Literal["m4a", "wav", "aiff", "flac", "mp3"] = Field(default="m4a", alias="targetFormat")
    bitrate_kbps: StrictInt = Field(default=192, alias="bitrateKbps", ge=32, le=640)


class AudioNormalizeOptions(StrictModel):
    target_lufs: StrictFloat | StrictInt = Field(default=-14, alias="targetLufs", ge=-24, le=-5)


class ArtworkOptions(StrictModel):
    max_edge: StrictInt = Field(default=1024, alias="maxEdge", ge=64, le=4096)


OPERATION_OPTIONS = {
    "image-convert": ImageConvertOptions,
    "image-optimize": ImageOptimizeOptions,
    "image-fit-size": ImageFitOptions,
    "image-resize": ResizeOptions,
    "image-crop": CropOptions,
    "image-strip-metadata": EmptyOptions,
    "image-watermark": WatermarkOptions,
    "image-watermark-overlay": ImageWatermarkOverlayOptions,
    "video-optimize": VideoOptimizeOptions,
    "video-hevc-convert": EmptyOptions,
    "video-fit-size": VideoFitOptions,
    "video-crop": CropOptions,
    "video-resize": VideoResizeOptions,
    "video-speed": SpeedOptions,
    "video-watermark-overlay": ImageWatermarkOverlayOptions,
    "video-mute": EmptyOptions,
    "video-strip-metadata": EmptyOptions,
    "video-to-gif": GifOptions,
    "pdf-lossless-compress": PdfLosslessOptions,
    "pdf-visual-optimize": PdfVisualOptions,
    "pdf-fit-size": PdfFitOptions,
    "pdf-pages-to-images": PdfPagesToImagesOptions,
    "pdf-crop": PdfCropOptions,
    "pdf-uncrop": EmptyOptions,
    "audio-optimize": AudioOptimizeOptions,
    "audio-convert": AudioConvertOptions,
    "audio-fit-size": AudioFitOptions,
    "audio-normalize": AudioNormalizeOptions,
    "audio-artwork": ArtworkOptions,
    "audio-speed": SpeedOptions,
}
MEDIA_OPERATION_IDS = frozenset(OPERATION_OPTIONS)


def validate_operation_sequence(operations):
    if any(operation.operation_id == "pdf-pages-to-images" for operation in operations[:-1]):
        raise ValueError("Extracting PDF pages as images must be the final pipeline step")
    return operations


class MediaOperation(StrictModel):
    operation_id: str = Field(alias="operationId")
    options: dict

    @model_validator(mode="after")
    def validate_operation(self):
        options_model = OPERATION_OPTIONS.get(self.operation_id)
        if options_model is None:
            raise ValueError("Unsupported media operation")
        parsed = options_model.model_validate(self.options)
        self.options = parsed.model_dump(exclude_unset=True)
        return self


class SelectedSource(StrictModel):
    kind: Literal["selection"]
    selection_id: UUID = Field(alias="selectionId")
    file_id: UUID = Field(alias="fileId")

    @field_validator("selection_id", "file_id", mode="before")
    @classmethod
    def parse_identifier(cls, value):
        return UUID(value) if isinstance(value, str) else value


class ImportedSource(StrictModel):
    kind: Literal["import"]
    import_id: UUID = Field(alias="importId")

    @field_validator("import_id", mode="before")
    @classmethod
    def parse_identifier(cls, value):
        return UUID(value) if isinstance(value, str) else value


class StagedImageSource(StrictModel):
    kind: Literal["staged-image"]
    staging_id: UUID = Field(alias="stagingId")

    @field_validator("staging_id", mode="before")
    @classmethod
    def parse_identifier(cls, value):
        return UUID(value) if isinstance(value, str) else value


MediaSource = Annotated[Union[SelectedSource, ImportedSource, StagedImageSource], Field(discriminator="kind")]


class MediaJobItem(StrictModel):
    source: MediaSource
    operations: list[MediaOperation] = Field(min_length=1, max_length=MAX_MEDIA_OPERATIONS)
    output_name_template: StrictStr | None = Field(default=None, alias="outputNameTemplate", max_length=120)

    @field_validator("output_name_template")
    @classmethod
    def validate_template(cls, value):
        return validate_output_name_template(value)

    @model_validator(mode="after")
    def validate_sequence(self):
        validate_operation_sequence(self.operations)
        return self


class MediaJobCreate(StrictModel):
    items: list[MediaJobItem] = Field(min_length=1, max_length=MAX_MEDIA_JOB_ITEMS)
    watermark_staging_id: UUID | None = Field(default=None, alias="watermarkStagingId")

    @field_validator("watermark_staging_id", mode="before")
    @classmethod
    def parse_watermark_identifier(cls, value):
        return UUID(value) if isinstance(value, str) else value

    @model_validator(mode="after")
    def unique_sources(self):
        has_overlay = any(
            operation.operation_id in {"image-watermark-overlay", "video-watermark-overlay"}
            for item in self.items for operation in item.operations
        )
        if has_overlay != (self.watermark_staging_id is not None):
            raise ValueError("Watermark overlay operations require one staged watermark image")
        keys = []
        for item in self.items:
            if isinstance(item.source, SelectedSource):
                keys.append(("selection", item.source.selection_id, item.source.file_id))
            elif isinstance(item.source, ImportedSource):
                keys.append(("import", item.source.import_id))
            else:
                keys.append(("staged-image", item.source.staging_id))
        if len(set(keys)) != len(keys):
            raise ValueError("Each source can appear only once in a media job")
        return self
