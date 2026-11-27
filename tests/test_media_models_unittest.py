import pytest
from pydantic import ValidationError
from uuid import UUID

from officekit.engines.engine_media_models import (
    MEDIA_OPERATION_IDS,
    MediaJobCreate,
    MediaOperation,
)


@pytest.mark.parametrize("operation_id", ["image-crop", "video-crop"])
def test_typed_crop_accepts_one_oriented_aspect_target_and_optional_smart_selection(operation_id):
    operation = MediaOperation.model_validate({"operationId": operation_id, "options": {
        "aspectRatio": "1.50:1", "smartCrop": True,
    }})
    assert operation.options == {"aspect_ratio": "3:2", "smart_crop": True}


@pytest.mark.parametrize("options", [
    {}, {"aspectRatio": None}, {"aspectRatio": "0:1"}, {"aspectRatio": "100:1"},
    {"aspectRatio": "16:9", "smartCrop": "true"},
    {"aspectRatio": "16:9", "x": None},
    {"aspectRatio": "16:9", "x": 0, "y": 0, "width": 100, "height": 100},
    {"x": 0, "y": 0, "width": 100, "height": 100, "smartCrop": True},
])
def test_typed_crop_rejects_missing_mixed_or_untrusted_targets(options):
    with pytest.raises(ValidationError):
        MediaOperation.model_validate({"operationId": "image-crop", "options": options})


def test_operation_catalog_covers_all_media_modes_and_existing_tools():
    assert {
        "image-convert", "image-optimize", "image-fit-size", "image-resize",
        "image-crop", "image-strip-metadata", "image-watermark",
        "image-watermark-overlay",
        "video-optimize", "video-hevc-convert", "video-fit-size", "video-crop", "video-resize", "video-speed",
        "video-mute", "video-strip-metadata", "video-to-gif", "video-watermark-overlay", "pdf-lossless-compress", "pdf-pages-to-images",
        "pdf-visual-optimize", "pdf-fit-size", "pdf-crop", "pdf-uncrop",
        "audio-optimize", "audio-convert", "audio-fit-size",
        "audio-normalize", "audio-artwork", "audio-speed",
    } <= MEDIA_OPERATION_IDS


@pytest.mark.parametrize("operation", [
    {"operation_id": "image-convert", "options": {"target_format": "webp", "quality": 82}},
    {"operation_id": "image-convert", "options": {"target_format": "webp", "lossless": True}},
    {"operation_id": "image-convert", "options": {"target_format": "avif", "quality": 82}},
    {"operation_id": "image-convert", "options": {"target_format": "jxl", "quality": 82}},
    {"operation_id": "image-resize", "options": {"max_width": 1280, "max_height": 720}},
    {"operation_id": "image-strip-metadata", "options": {}},
    {"operation_id": "video-speed", "options": {"factor_percent": 150}},
    {"operation_id": "video-mute", "options": {}},
    {"operation_id": "video-strip-metadata", "options": {}},
    {"operation_id": "pdf-lossless-compress", "options": {"profile": "balanced"}},
    {"operation_id": "pdf-pages-to-images", "options": {"target_format": "jpeg", "quality": 80, "dpi": 150}},
    {"operation_id": "audio-normalize", "options": {"target_lufs": -14}},
    {"operation_id": "image-optimize", "options": {"quality": 75, "preserve_metadata": False}},
    {"operation_id": "image-optimize", "options": {"compression": 55}},
    {"operation_id": "image-optimize", "options": {"compression": "adaptive"}},
    {"operation_id": "image-fit-size", "options": {"target_bytes": 2_000_000, "min_quality": 40, "max_quality": 85}},
    {"operation_id": "image-fit-size", "options": {"target_bytes": 2_000_000, "target_format": "avif", "min_quality": 40, "max_quality": 85}},
    {"operation_id": "image-fit-size", "options": {"target_bytes": 2_000_000, "target_format": "jxl", "min_quality": 40, "max_quality": 85}},
    {"operation_id": "image-crop", "options": {"x": 0, "y": 0, "width": 400, "height": 300}},
    {"operation_id": "image-watermark", "options": {"text": "OfficeKit", "opacity": 70, "position": "bottom-right"}},
    {"operation_id": "image-watermark-overlay", "options": {"placement": "tile", "margin_percent": 4, "size_percent": 18, "opacity_percent": 72}},
    {"operation_id": "video-watermark-overlay", "options": {"placement": "bottom-right", "margin_percent": 4, "size_percent": 18, "opacity_percent": 72}},
    {"operation_id": "video-optimize", "options": {"target_format": "m4v", "quality": "balanced", "target_bytes": 5_000_000}},
    {"operation_id": "video-optimize", "options": {"target_format": "av1", "quality": "smaller"}},
    {"operation_id": "video-optimize", "options": {"target_format": "mp4", "quality": "balanced"}},
    {"operation_id": "video-optimize", "options": {"target_format": "mp4", "compression": 55}},
    {"operation_id": "video-optimize", "options": {"target_format": "webm", "quality": "balanced"}},
    {"operation_id": "video-optimize", "options": {"target_format": "x265", "quality": "balanced"}},
    {"operation_id": "video-hevc-convert", "options": {}},
    {"operation_id": "video-fit-size", "options": {"target_format": "mov", "quality": "smaller", "target_bytes": 5_000_000}},
    {"operation_id": "video-fit-size", "options": {"target_format": "av1", "quality": "balanced", "target_bytes": 5_000_000}},
    {"operation_id": "video-fit-size", "options": {"target_format": "webm", "quality": "balanced", "target_bytes": 5_000_000}},
    {"operation_id": "video-crop", "options": {"x": 0, "y": 0, "width": 640, "height": 360}},
    {"operation_id": "video-resize", "options": {"max_width": 1280, "max_height": 720}},
    {"operation_id": "video-resize", "options": {"max_width": 1920, "max_height": 1080, "fps": 24}},
    {"operation_id": "video-to-gif", "options": {"fps": 12, "max_width": 640, "max_duration_seconds": 20}},
    {"operation_id": "pdf-visual-optimize", "options": {"quality": 72, "dpi": 150}},
    {"operation_id": "pdf-fit-size", "options": {"target_bytes": 5_000_000, "quality": 65, "dpi": 120}},
    {"operation_id": "pdf-crop", "options": {"page_size": "mobile"}},
    {"operation_id": "pdf-uncrop", "options": {}},
    {"operation_id": "pdf-crop", "options": {"aspect_ratio": "9:16"}},
    {"operation_id": "pdf-crop", "options": {"aspect_ratio": "1.91:1"}},
    {"operation_id": "pdf-crop", "options": {"device_name": "iPad Air"}},
    {"operation_id": "pdf-crop", "options": {"paper_size_name": "Letter"}},
    {"operation_id": "pdf-crop", "options": {"aspect_ratio": "9:16", "page_layout": "landscape", "extend": True}},
    {"operation_id": "audio-optimize", "options": {"target_format": "m4a", "bitrate_kbps": 192}},
    {"operation_id": "audio-optimize", "options": {"target_format": "m4a", "compression": 55}},
    {"operation_id": "audio-convert", "options": {"target_format": "aiff"}},
    {"operation_id": "audio-convert", "options": {"target_format": "flac"}},
    {"operation_id": "audio-convert", "options": {"target_format": "mp3"}},
    {"operation_id": "audio-fit-size", "options": {"target_bytes": 5_000_000, "target_format": "m4a", "bitrate_kbps": 96}},
    {"operation_id": "audio-fit-size", "options": {"target_bytes": 5_000_000, "target_format": "mp3", "bitrate_kbps": 96}},
    {"operation_id": "audio-artwork", "options": {"max_edge": 512}},
    {"operation_id": "audio-speed", "options": {"factor_percent": 150}},
])
def test_valid_typed_operations_are_normalized(operation):
    parsed = MediaOperation.model_validate(operation)
    expected = operation
    if operation.get("operation_id") == "pdf-crop" and operation["options"].get("aspect_ratio") == "1.91:1":
        expected = {**operation, "options": {"aspect_ratio": "100:191"}}
    assert parsed.model_dump() == expected


def test_fit_size_rejects_inverted_quality_range():
    with pytest.raises(ValidationError):
        MediaOperation.model_validate({
            "operation_id": "image-fit-size",
            "options": {"target_bytes": 100_000, "min_quality": 90, "max_quality": 40},
        })


@pytest.mark.parametrize("options", [
    {"target_format": "mp4", "compression": 4},
    {"target_format": "mp4", "compression": 101},
    {"target_format": "webm", "compression": 55},
])
def test_video_compression_factor_is_bounded_and_h264_only(options):
    with pytest.raises(ValidationError):
        MediaOperation.model_validate({"operation_id": "video-optimize", "options": options})


@pytest.mark.parametrize("compression", [4, 101, True, "auto"])
def test_image_compression_factor_is_bounded_and_accepts_only_adaptive(compression):
    with pytest.raises(ValidationError):
        MediaOperation.model_validate({"operation_id": "image-optimize", "options": {"compression": compression}})


@pytest.mark.parametrize("compression", [4, 101, True, "auto"])
def test_audio_compression_factor_is_bounded_and_accepts_only_adaptive(compression):
    with pytest.raises(ValidationError):
        MediaOperation.model_validate({"operation_id": "audio-optimize", "options": {"compression": compression}})


def test_audio_convert_rejects_optimize_only_compression_option():
    with pytest.raises(ValidationError):
        MediaOperation.model_validate({"operation_id": "audio-convert", "options": {"targetFormat": "m4a", "compression": 55}})


@pytest.mark.parametrize("target_format", ["png", "jpeg", "avif"])
def test_lossless_image_conversion_is_limited_to_lossless_encoders(target_format):
    with pytest.raises(ValidationError, match="Lossless conversion"):
        MediaOperation.model_validate({
            "operation_id": "image-convert", "options": {"target_format": target_format, "lossless": True},
        })


def test_pdf_page_export_must_be_the_final_pipeline_step():
    source = {"kind": "import", "import_id": "123e4567-e89b-42d3-a456-426614174000"}
    export = {"operation_id": "pdf-pages-to-images", "options": {}}
    cleanup = {"operation_id": "pdf-uncrop", "options": {}}
    with pytest.raises(ValidationError, match="final"):
        MediaJobCreate.model_validate({"items": [{"source": source, "operations": [export, cleanup]}]})


def test_video_watermark_job_requires_the_same_single_use_logo_grant():
    payload = {
        "items": [{
            "source": {"kind": "import", "import_id": "123e4567-e89b-42d3-a456-426614174000"},
            "operations": [{"operation_id": "video-watermark-overlay", "options": {}}],
        }],
    }
    with pytest.raises(ValidationError, match="staged watermark image"):
        MediaJobCreate.model_validate(payload)
    parsed = MediaJobCreate.model_validate({
        **payload, "watermark_staging_id": "123e4567-e89b-42d3-a456-426614174099",
    })
    assert parsed.items[0].operations[0].operation_id == "video-watermark-overlay"


@pytest.mark.parametrize("operation", [
    {"operation_id": "unknown", "options": {}},
    {"operation_id": "image-resize", "options": {"max_width": 0, "max_height": 200}},
    {"operation_id": "image-convert", "options": {"target_format": "exe", "quality": 90}},
    {"operation_id": "image-convert", "options": {"target_format": "jpeg", "quality": True}},
    {"operation_id": "image-strip-metadata", "options": {"path": "/tmp/source.jpg"}},
    {"operation_id": "video-speed", "options": {"factor_percent": 0}},
    {"operation_id": "video-resize", "options": {"max_width": 0, "max_height": 720}},
    {"operation_id": "video-resize", "options": {"max_width": 1920, "max_height": 1080, "fps": 121}},
    {"operation_id": "pdf-lossless-compress", "options": {"profile": "lossy"}},
    {"operation_id": "audio-normalize", "options": {"target_lufs": -100}},
    {"operation_id": "video-mute", "options": {}, "shell": "rm -rf /"},
    {"operation_id": "video-fit-size", "options": {"quality": "smaller"}},
    {"operation_id": "pdf-fit-size", "options": {"quality": 60}},
    {"operation_id": "pdf-crop", "options": {"aspect_ratio": "16/9"}},
    {"operation_id": "pdf-crop", "options": {"aspect_ratio": "1.91:1.abc"}},
    {"operation_id": "pdf-crop", "options": {"aspect_ratio": "9:16", "page_layout": "diagonal"}},
    {"operation_id": "pdf-crop", "options": {"aspect_ratio": "9:16", "extend": "true"}},
    {"operation_id": "pdf-crop", "options": {"device_name": "Unknown Device"}},
    {"operation_id": "pdf-crop", "options": {"paper_size_name": "Unknown Paper"}},
    {"operation_id": "pdf-crop", "options": {"page_size": "a4", "device_name": "iPad Air"}},
    {"operation_id": "pdf-crop", "options": {"aspect_ratio": "16:9", "page_size": "mobile"}},
    {"operation_id": "pdf-crop", "options": {}},
    {"operation_id": "audio-fit-size", "options": {"bitrate_kbps": 64}},
])
def test_invalid_or_untrusted_operation_fields_are_rejected(operation):
    with pytest.raises(ValidationError):
        MediaOperation.model_validate(operation)


def test_job_accepts_bounded_selection_items_and_independent_operations():
    result = MediaJobCreate.model_validate({
        "items": [{
            "source": {
                "kind": "selection",
                "selection_id": "123e4567-e89b-42d3-a456-426614174000",
                "file_id": "123e4567-e89b-42d3-a456-426614174001",
            },
            "operations": [{"operation_id": "image-strip-metadata", "options": {}}],
        }],
    })
    assert len(result.items) == 1
    assert result.items[0].source.kind == "selection"


def test_job_accepts_import_source_and_native_uuid_objects():
    result = MediaJobCreate.model_validate({
        "items": [{
            "source": {"kind": "import", "import_id": "123e4567-e89b-42d3-a456-426614174000"},
            "operations": [{"operation_id": "video-mute", "options": {}}],
        }],
    })
    assert result.items[0].source.kind == "import"
    result = MediaJobCreate.model_validate({
        "items": [{
            "source": {
                "kind": "selection",
                "selection_id": UUID("123e4567-e89b-42d3-a456-426614174000"),
                "file_id": UUID("123e4567-e89b-42d3-a456-426614174001"),
            },
            "operations": [{"operation_id": "video-mute", "options": {}}],
        }],
    })
    assert result.items[0].source.kind == "selection"


@pytest.mark.parametrize("payload", [
    {"items": []},
    {"items": [{"source": {"kind": "selection", "selection_id": "bad", "file_id": "bad"}, "operations": [{"operation_id": "image-strip-metadata", "options": {}}]}]},
    {"items": [{"source": {"kind": "import", "import_id": "123e4567-e89b-42d3-a456-426614174000", "selection_id": "extra"}, "operations": [{"operation_id": "image-strip-metadata", "options": {}}]}]},
    {"items": [{"source": {"kind": "selection", "selection_id": "123e4567-e89b-42d3-a456-426614174000", "file_id": "123e4567-e89b-42d3-a456-426614174001"}, "operations": []}]},
    {"items": [{"source": {"kind": "selection", "selection_id": "123e4567-e89b-42d3-a456-426614174000", "file_id": "123e4567-e89b-42d3-a456-426614174001"}, "operations": [{"operation_id": "image-strip-metadata", "options": {}}] * 9}]},
    {"items": [{"source": {"kind": "selection", "selection_id": "123e4567-e89b-42d3-a456-426614174000", "file_id": "123e4567-e89b-42d3-a456-426614174001"}, "operations": [{"operation_id": "image-strip-metadata", "options": {}}]}], "tenant_id": "other"},
])
def test_invalid_job_bounds_and_authority_fields_are_rejected(payload):
    with pytest.raises(ValidationError):
        MediaJobCreate.model_validate(payload)
