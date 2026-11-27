import io
import platform
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageFont

from officekit.engines.engine_conversion_errors import ConversionInputError
from officekit.engines.engine_media_models import MediaOperation
from officekit.engines.engine_media_optimizer import (
    MediaOperationUnavailableError,
    MediaOptimizerEngine,
)
from officekit.engines.engine_file_converter import FileConverterEngine
from officekit.engines import engine_media_native as native
from officekit.engines import engine_file_converter as converter_module
from officekit.engines import engine_media_capabilities as capabilities_module


def image_bytes(fmt="PNG", size=(320, 240), color=(20, 120, 200)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format=fmt)
    return stream.getvalue()


def operation(operation_id, options):
    return MediaOperation.model_validate({"operation_id": operation_id, "options": options})


def test_convert_image_reuses_existing_converter_and_returns_safe_media_metadata():
    result = MediaOptimizerEngine.execute(
        image_bytes(), "portrait.png", [operation("image-convert", {"target_format": "webp", "quality": 80})]
    )
    assert result.extension == "webp"
    assert result.media_type == "image/webp"
    assert result.attributes["width"] == 320
    assert result.attributes["height"] == 240
    with Image.open(io.BytesIO(result.data)) as image:
        assert image.format == "WEBP"


def test_lossless_webp_conversion_preserves_decoded_pixels_and_reports_mode():
    source = image_bytes("PNG")
    result = MediaOptimizerEngine.execute(
        source, "portrait.png", [operation("image-convert", {"target_format": "webp", "lossless": True})],
    )
    assert result.extension == "webp"
    assert result.attributes["lossless"] is True
    with Image.open(io.BytesIO(source)) as original, Image.open(io.BytesIO(result.data)) as converted:
        assert converted.format == "WEBP"
        assert original.convert("RGBA").tobytes() == converted.convert("RGBA").tobytes()


def test_same_format_lossy_conversion_returns_the_original_bytes():
    source = image_bytes("PNG")
    result = MediaOptimizerEngine.execute(
        source, "portrait.png", [operation("image-convert", {"target_format": "png"})],
    )
    assert result.data == source
    assert result.attributes["no_op"] is True


def test_adaptive_image_format_chooses_smaller_lossy_or_lossless_copy(monkeypatch):
    calls = []

    def encode(_data, target, quality, preserve_metadata, preserve_color_profile):
        calls.append((target, quality, preserve_metadata, preserve_color_profile))
        return (b"jpeg" if target == "jpeg" else b"png" * 10, "image/jpeg" if target == "jpeg" else "image/png")

    monkeypatch.setattr(FileConverterEngine, "convert_image", encode)
    source = image_bytes("JPEG")
    output = MediaOptimizerEngine.execute(source, "photo.jpg", [operation("image-optimize", {"adaptive": True})])
    assert output.extension == "jpg" and output.media_type == "image/jpeg"
    assert output.attributes["selected_format"] == "jpeg"
    assert output.attributes["adaptive"] is True
    assert [call[0] for call in calls] == ["jpeg", "png"]

    transparent = io.BytesIO()
    Image.new("RGBA", (20, 20), (20, 40, 60, 100)).save(transparent, format="PNG")
    calls.clear()
    output = MediaOptimizerEngine.execute(
        transparent.getvalue(), "icon.png", [operation("image-optimize", {"adaptive": True})],
    )
    assert output.extension == "png" and output.attributes["selected_format"] == "png"
    assert [call[0] for call in calls] == ["png"]


def test_image_compression_factor_maps_to_quality_and_preserves_source(monkeypatch):
    calls = []

    def encode(_data, target, quality, preserve_metadata, preserve_color_profile):
        calls.append((target, quality))
        return b"optimized", "image/jpeg"

    monkeypatch.setattr(FileConverterEngine, "convert_image", encode)
    source = image_bytes("JPEG")
    output = MediaOptimizerEngine.execute(source, "photo.jpg", [operation("image-optimize", {"compression": 50})])
    assert calls == [("jpeg", 62)]
    assert output.attributes["compression"] == 50
    assert source == image_bytes("JPEG")


def test_heic_image_optimize_uses_local_bounded_decoder_and_emits_webp_copy():
    if platform.system() != "Darwin" or not native.native_heif_decoder_available():
        pytest.skip("macOS ImageIO via sips is not available")
    source_path = Path("tests/fixtures/similar-images/cc0/heic/still-medium.heic")
    source = source_path.read_bytes()
    result = MediaOptimizerEngine.execute(
        source, source_path.name, [operation("image-optimize", {"quality": 82})],
    )
    assert result.extension == "webp"
    assert result.media_type == "image/webp"
    assert result.data[:4] == b"RIFF" and result.data[8:12] == b"WEBP"
    assert result.attributes["converted_from"] == "heif"
    assert result.attributes["width"] == 1200
    assert result.attributes["height"] == 1600
    assert source_path.read_bytes() == source


def test_heic_image_resize_runs_through_the_existing_pillow_engine():
    if platform.system() != "Darwin" or not native.native_heif_decoder_available():
        pytest.skip("macOS ImageIO via sips is not available")
    source_path = Path("tests/fixtures/similar-images/cc0/heic/still-medium.heic")
    result = MediaOptimizerEngine.execute(
        source_path.read_bytes(), source_path.name,
        [operation("image-resize", {"max_width": 600, "max_height": 600})],
    )
    assert result.extension == "png"
    with Image.open(io.BytesIO(result.data)) as resized:
        assert resized.size == (450, 600)


def test_heif_decoder_rejects_oversized_dimensions_before_pixel_conversion(monkeypatch):
    calls = []

    def inspect_only(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=b"pixelWidth: 10001\npixelHeight: 1\n",
            stderr=b"",
        )

    monkeypatch.setattr(native.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(native.subprocess, "run", inspect_only)
    with pytest.raises(ConversionInputError):
        native.decode_heif_to_png_bytes(b"untrusted heif")
    assert len(calls) == 1
    assert calls[0][1:5] == ["-g", "pixelWidth", "-g", "pixelHeight"]


def test_avif_conversion_optimize_and_fit_when_local_encoder_is_available():
    if not FileConverterEngine.avif_encoder_available():
        pytest.skip("Pillow AVIF encoder is unavailable in this environment")
    source = image_bytes("JPEG", (160, 120), (80, 120, 180))
    original = source[:]
    converted = MediaOptimizerEngine.execute(source, "photo.jpg", [operation("image-convert", {
        "target_format": "avif", "quality": 78,
    })])
    assert converted.extension == "avif"
    assert converted.media_type == "image/avif"
    with Image.open(io.BytesIO(converted.data)) as image:
        assert image.format == "AVIF"

    optimized = MediaOptimizerEngine.execute(converted.data, "photo.avif", [operation("image-optimize", {"quality": 72})])
    assert optimized.extension == "avif"
    resized = MediaOptimizerEngine.execute(converted.data, "photo.avif", [operation("image-resize", {
        "max_width": 80, "max_height": 80,
    })])
    assert resized.extension == "avif"
    assert (resized.attributes["width"], resized.attributes["height"]) == (80, 60)
    fitted = MediaOptimizerEngine.execute(source, "photo.jpg", [operation("image-fit-size", {
        "target_bytes": 50_000, "target_format": "avif", "min_quality": 25, "max_quality": 80,
    })])
    assert fitted.extension == "avif"
    assert fitted.attributes["actual_bytes"] == len(fitted.data)
    assert source == original
    with Image.open(io.BytesIO(optimized.data)) as image:
        assert image.format == "AVIF"
    with Image.open(io.BytesIO(resized.data)) as image:
        assert image.format == "AVIF"


def test_avif_output_fails_closed_and_is_not_advertised_without_an_encoder(monkeypatch):
    monkeypatch.setattr(converter_module, "avif_encoder_available", lambda: False)
    monkeypatch.setattr(capabilities_module, "avif_encoder_available", lambda: False)
    with pytest.raises(ConversionInputError):
        FileConverterEngine.convert_image(image_bytes(), "avif")
    operations = {
        operation["id"]: operation
        for group in capabilities_module.media_capabilities()["media"]
        for operation in group["operations"]
    }
    assert all("avif" not in operation["formats"] for operation in operations.values())


def test_jxl_output_fails_closed_and_is_not_advertised_without_an_encoder(monkeypatch):
    monkeypatch.setattr(converter_module, "jxl_encoder_available", lambda: False)
    monkeypatch.setattr(capabilities_module, "jxl_encoder_available", lambda: False)
    with pytest.raises(ConversionInputError):
        FileConverterEngine.convert_image(image_bytes(), "jxl")
    operations = {
        operation["id"]: operation
        for group in capabilities_module.media_capabilities()["media"]
        for operation in group["operations"]
    }
    assert all("jxl" not in operation["formats"] for operation in operations.values())


def test_jxl_conversion_optimize_resize_and_fit_when_local_encoder_is_available():
    if not FileConverterEngine.jxl_encoder_available():
        pytest.skip(f"JPEG XL plugin or encoder is unavailable: {converter_module._JXL_PLUGIN_LOAD_ERROR!r}")
    source = image_bytes("JPEG", (160, 120), (80, 120, 180))
    original = source[:]
    converted = MediaOptimizerEngine.execute(source, "photo.jpg", [operation("image-convert", {
        "target_format": "jxl", "quality": 82,
    })])
    assert converted.extension == "jxl"
    assert converted.media_type == "image/jxl"
    with Image.open(io.BytesIO(converted.data)) as image:
        assert image.format == "JXL"

    optimized = MediaOptimizerEngine.execute(converted.data, "photo.jxl", [operation("image-optimize", {"quality": 72})])
    resized = MediaOptimizerEngine.execute(converted.data, "photo.jxl", [operation("image-resize", {
        "max_width": 80, "max_height": 80,
    })])
    assert optimized.extension == "jxl"
    assert resized.extension == "jxl"
    assert (resized.attributes["width"], resized.attributes["height"]) == (80, 60)
    fitted = MediaOptimizerEngine.execute(source, "photo.jpg", [operation("image-fit-size", {
        "target_bytes": 50_000, "target_format": "jxl", "min_quality": 25, "max_quality": 80,
    })])
    assert fitted.extension == "jxl"
    assert fitted.attributes["actual_bytes"] == len(fitted.data)
    assert source == original
    for output in (optimized.data, resized.data, fitted.data):
        with Image.open(io.BytesIO(output)) as image:
            assert image.format == "JXL"
    cleaned = MediaOptimizerEngine.execute(converted.data, "photo.jxl", [operation("image-strip-metadata", {})])
    with Image.open(io.BytesIO(cleaned.data)) as image:
        assert image.format == "JXL"
        assert not image.getexif()


def test_jxl_conversion_and_metadata_stripping_remove_exif_xmp_and_jumbf():
    if not FileConverterEngine.jxl_encoder_available():
        pytest.skip(f"JPEG XL plugin or encoder is unavailable: {converter_module._JXL_PLUGIN_LOAD_ERROR!r}")
    exif = Image.Exif()
    exif[270] = "private fixture"
    source_stream = io.BytesIO()
    Image.new("RGB", (24, 16), (100, 120, 140)).save(source_stream, format="JPEG", exif=exif)
    source = source_stream.getvalue()

    converted, _mime = FileConverterEngine.convert_image(source, "jxl", preserve_metadata=False)
    with Image.open(io.BytesIO(converted)) as image:
        assert not image.getexif()
        assert not image.info.get("xmp")
        assert not image.info.get("jumbf")

    metadata_rich = Image.new("RGB", (24, 16), (100, 120, 140))
    metadata_rich.info.update(exif=exif.tobytes(), xmp=b"private xmp", jumbf=b"private jumbf")
    jxl_stream = io.BytesIO()
    metadata_rich.save(jxl_stream, format="JXL", exif=exif.tobytes(), xmp=b"private xmp", jumbf=b"private jumbf")
    stripped = FileConverterEngine.strip_exif(jxl_stream.getvalue())
    with Image.open(io.BytesIO(stripped)) as image:
        assert not image.getexif()
        assert not image.info.get("xmp")
        assert not image.info.get("jumbf")


@pytest.mark.parametrize("detected,expected_x", [(True, 100), (False, 50)])
def test_typed_smart_crop_uses_private_current_image_and_preserves_source(monkeypatch, detected, expected_x):
    image = Image.new("RGB", (200, 100), (255, 0, 0))
    image.paste((0, 0, 255), (100, 0, 200, 100))
    original = io.BytesIO()
    image.save(original, format="PNG")
    source = original.getvalue()
    calls = []

    def saliency(path, kind, **_kwargs):
        calls.append(Path(path))
        assert kind == "image" and Path(path).read_bytes() == source
        assert Path(path).stat().st_mode & 0o777 == 0o600
        return {"sourceWidth": 200, "sourceHeight": 100, "detected": detected,
                "x": 0.8, "y": 0.4, "width": 0.1, "height": 0.2}

    monkeypatch.setattr(native, "probe_smart_crop_bounds", saliency)
    result = MediaOptimizerEngine.execute(source, "photo.png", [operation("image-crop", {
        "aspectRatio": "1:1", "smartCrop": True,
    })])
    assert result.attributes == {"width": 100, "height": 100, "x": expected_x, "y": 0,
                                 "smart_crop": True, "saliency_detected": detected}
    assert len(calls) == 1 and not calls[0].exists()
    with Image.open(io.BytesIO(result.data)) as prepared:
        assert prepared.getpixel((0, 0))[:3] == ((0, 0, 255) if detected else (255, 0, 0))
        assert prepared.getpixel((99, 99))[:3] == (0, 0, 255)
    assert source == original.getvalue()


def test_typed_aspect_crop_respects_exif_display_orientation_without_vision(monkeypatch):
    stream = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (200, 100), (20, 120, 200)).save(stream, format="JPEG", exif=exif)
    source = stream.getvalue()
    monkeypatch.setattr(native, "probe_smart_crop_bounds", lambda *_args, **_kwargs: pytest.fail("centered crop does not use Vision"))
    result = MediaOptimizerEngine.execute(source, "portrait.jpg", [operation("image-crop", {"aspectRatio": "1:2"})])
    assert result.attributes["width"] == 100 and result.attributes["height"] == 200
    with Image.open(io.BytesIO(result.data)) as prepared:
        assert prepared.size == (100, 200)
    assert source == stream.getvalue()


def test_resize_crop_metadata_and_watermark_are_supported_image_operations():
    source = image_bytes("JPEG", (800, 600))
    resized = MediaOptimizerEngine.execute(source, "portrait.jpg", [operation("image-resize", {"max_width": 400, "max_height": 400})])
    assert resized.extension == "jpg"
    assert resized.attributes["width"] == 400
    assert resized.attributes["height"] == 300
    cropped = MediaOptimizerEngine.execute(source, "portrait.jpg", [operation("image-crop", {"x": 5, "y": 5, "width": 120, "height": 90})])
    assert cropped.extension == "jpg"
    assert cropped.attributes["width"] == 120
    assert cropped.attributes["height"] == 90
    cleaned = MediaOptimizerEngine.execute(source, "portrait.jpg", [operation("image-strip-metadata", {})])
    assert cleaned.attributes["metadata_removed"] is True
    watermarked = MediaOptimizerEngine.execute(source, "portrait.jpg", [operation("image-watermark", {"text": "OfficeKit", "opacity": 60})])
    assert watermarked.attributes["watermarked"] is True
    assert watermarked.data != source
    with Image.open(io.BytesIO(watermarked.data)) as image:
        assert image.format == "JPEG"


def test_image_watermark_overlay_uses_uploaded_pixels_and_keeps_original_bytes():
    source = image_bytes("PNG", (100, 80), (20, 80, 180))
    mark_stream = io.BytesIO()
    Image.new("RGBA", (20, 10), (240, 30, 20, 255)).save(mark_stream, format="PNG")
    watermark = mark_stream.getvalue()
    result = MediaOptimizerEngine.execute(
        source, "photo.png", [operation("image-watermark-overlay", {
            "placement": "top-left", "margin_percent": 0,
            "size_percent": 20, "opacity_percent": 100,
        })], watermark_image=watermark,
    )
    assert result.attributes["watermarked"] is True
    with Image.open(io.BytesIO(result.data)) as output:
        assert output.getpixel((5, 5))[:3] == (240, 30, 20)
        assert output.getpixel((50, 40))[:3] == (20, 80, 180)
    with Image.open(io.BytesIO(source)) as original:
        assert original.getpixel((5, 5))[:3] == (20, 80, 180)


def test_image_watermark_overlay_requires_valid_uploaded_image():
    with pytest.raises(MediaOperationUnavailableError, match="Choose a watermark image"):
        MediaOptimizerEngine.execute(
            image_bytes(), "photo.png", [operation("image-watermark-overlay", {})],
        )


def test_optimize_and_fit_size_always_encode_from_the_original():
    source = image_bytes("JPEG", (640, 480), (120, 120, 120))
    optimized = MediaOptimizerEngine.execute(source, "photo.jpg", [operation("image-optimize", {"quality": 55})])
    assert optimized.extension == "jpg"
    fit = MediaOptimizerEngine.execute(source, "photo.jpg", [operation("image-fit-size", {"target_bytes": 30_000, "target_format": "jpeg", "min_quality": 25, "max_quality": 80})])
    assert fit.attributes["attempts"] <= MediaOptimizerEngine.MAX_FIT_ATTEMPTS
    assert fit.attributes["target_met"] is True
    assert len(fit.data) <= 30_000
    assert len(source) > 0


def test_image_optimize_preserves_exif_only_when_the_option_is_enabled():
    exif = Image.Exif()
    exif[270] = "OfficeKit metadata fixture"
    stream = io.BytesIO()
    Image.new("RGB", (24, 16), (100, 120, 140)).save(stream, format="JPEG", exif=exif)
    source = stream.getvalue()

    stripped = MediaOptimizerEngine.execute(source, "photo.jpg", [operation("image-optimize", {"quality": 80})])
    preserved = MediaOptimizerEngine.execute(source, "photo.jpg", [operation(
        "image-optimize", {"quality": 80, "preserve_metadata": True},
    )])

    with Image.open(io.BytesIO(stripped.data)) as image:
        assert image.getexif().get(270) is None
    with Image.open(io.BytesIO(preserved.data)) as image:
        assert image.getexif().get(270) == "OfficeKit metadata fixture"


def test_fit_size_reports_unreachable_target_without_claiming_success():
    source = image_bytes("PNG", (64, 64), (255, 0, 0))
    result = MediaOptimizerEngine.execute(source, "tiny.png", [operation("image-fit-size", {"target_bytes": 1, "target_format": "png", "min_quality": 1, "max_quality": 10})])
    assert result.attributes["target_met"] is False
    assert result.attributes["actual_bytes"] == len(result.data)


def test_optimization_pipeline_applies_steps_in_order_and_rejects_unsupported_adapters(monkeypatch):
    source = image_bytes()
    result = MediaOptimizerEngine.execute(source, "image.png", [
        operation("image-resize", {"max_width": 160, "max_height": 120}),
        operation("image-convert", {"target_format": "webp", "quality": 70}),
    ])
    assert result.extension == "webp"
    assert (result.attributes["width"], result.attributes["height"]) == (160, 120)
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: None)
    with pytest.raises(MediaOperationUnavailableError):
        MediaOptimizerEngine.execute(source, "clip.mp4", [operation("video-mute", {})])


def test_invalid_image_bytes_and_crop_bounds_fail_safely():
    with pytest.raises(ConversionInputError):
        MediaOptimizerEngine.execute(b"not an image", "photo.png", [operation("image-optimize", {})])
    with pytest.raises(ConversionInputError):
        MediaOptimizerEngine.execute(image_bytes(), "photo.png", [operation("image-crop", {"x": 300, "y": 0, "width": 30, "height": 30})])


def test_unavailable_video_and_audio_operations_fail_closed(monkeypatch):
    monkeypatch.setattr(native, "native_media_transform_tool", lambda: None)
    monkeypatch.setattr(native, "native_audio_loudnorm_available", lambda: False)
    with pytest.raises(MediaOperationUnavailableError):
        MediaOptimizerEngine.execute(b"audio", "clip.mp4", [operation("video-mute", {})])
    with pytest.raises(MediaOperationUnavailableError):
        MediaOptimizerEngine.execute(b"audio", "voice.wav", [operation("audio-normalize", {})])


def test_visual_pdf_operation_rejects_malformed_pdf_without_disclosing_parser_errors():
    with pytest.raises(ConversionInputError):
        MediaOptimizerEngine.execute(b"%PDF-1.7\n", "scan.pdf", [operation("pdf-visual-optimize", {})])


def test_pdf_lossless_compression_reuses_existing_engine():
    import pikepdf

    source = io.BytesIO()
    pdf = pikepdf.Pdf.new()
    pdf.add_blank_page()
    pdf.save(source)
    result = MediaOptimizerEngine.execute(source.getvalue(), "scan.pdf", [operation("pdf-lossless-compress", {"profile": "balanced"})])
    assert result.extension == "pdf"
    assert result.attributes["lossless"] is True
    assert result.attributes["compression_ratio"] > 0


def test_pdf_pages_to_images_returns_bounded_archive_and_preserves_source():
    import zipfile

    source_path = Path("tests/fixtures/pdf-page-management-source.pdf")
    source = source_path.read_bytes()
    result = MediaOptimizerEngine.execute(
        source, source_path.name,
        [operation("pdf-pages-to-images", {"target_format": "png", "quality": 90, "dpi": 120})],
    )
    assert result.extension == "zip" and result.media_type == "application/zip"
    assert result.attributes["page_count"] == 3
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        assert archive.namelist() == ["page-001.png", "page-002.png", "page-003.png"]
        assert all(archive.read(name).startswith(b"\x89PNG\r\n\x1a\n") for name in archive.namelist())
    assert source_path.read_bytes() == source


def test_pdf_pages_to_images_cancellation_is_not_reported_as_invalid_input():
    from threading import Event
    from officekit.engines.engine_media_pdf import MediaPdfCancelledError

    cancelled = Event()
    cancelled.set()
    source = Path("tests/fixtures/pdf-page-management-source.pdf").read_bytes()
    with pytest.raises(MediaPdfCancelledError):
        MediaOptimizerEngine.execute(
            source, "source.pdf", [operation("pdf-pages-to-images", {})], cancel_event=cancelled,
        )


def test_execute_rejects_invalid_input_name_pipeline_and_nonvalidated_operation():
    valid = operation("image-strip-metadata", {})
    with pytest.raises(ConversionInputError):
        MediaOptimizerEngine.execute(b"", "x.png", [valid])
    with pytest.raises(ConversionInputError):
        MediaOptimizerEngine.execute(image_bytes(), "", [valid])
    with pytest.raises(ConversionInputError):
        MediaOptimizerEngine.execute(image_bytes(), "x.png", [])
    with pytest.raises(ConversionInputError):
        MediaOptimizerEngine.execute(image_bytes(), "x.png", [object()])
    with pytest.raises(MediaOperationUnavailableError):
        MediaOptimizerEngine.execute(image_bytes(), "x.png", [MediaOperation.model_construct(operation_id="image-unknown", options={})])


def test_image_info_rejects_valid_but_unsupported_pillow_format():
    source = io.BytesIO()
    Image.new("RGB", (10, 10)).save(source, format="PPM")
    with pytest.raises(ConversionInputError):
        MediaOptimizerEngine.execute(source.getvalue(), "sample.ppm", [operation("image-optimize", {})])


def test_image_optimize_and_fit_reject_animated_source():
    source = io.BytesIO()
    frames = [Image.new("RGB", (16, 16), color) for color in ("red", "blue")]
    frames[0].save(source, format="GIF", save_all=True, append_images=frames[1:])
    with pytest.raises(MediaOperationUnavailableError):
        MediaOptimizerEngine.execute(source.getvalue(), "animated.gif", [operation("image-optimize", {})])
    with pytest.raises(MediaOperationUnavailableError):
        MediaOptimizerEngine.execute(source.getvalue(), "animated.gif", [operation("image-fit-size", {"target_bytes": 1000})])
    with pytest.raises(MediaOperationUnavailableError):
        MediaOptimizerEngine.execute(source.getvalue(), "animated.gif", [operation("image-crop", {"x": 0, "y": 0, "width": 10, "height": 10})])


def test_fit_size_binary_search_selects_highest_quality_under_target(monkeypatch):
    source = image_bytes("JPEG", (40, 30))
    calls = []

    def encode(data, target_format, quality):
        calls.append((target_format, quality))
        return b"x" * (100 + quality), "image/jpeg"

    monkeypatch.setattr(FileConverterEngine, "convert_image", encode)
    result = MediaOptimizerEngine.execute(source, "fit.jpg", [operation("image-fit-size", {
        "target_bytes": 160, "target_format": "jpeg", "min_quality": 30, "max_quality": 90,
    })])
    assert result.attributes["target_met"] is True
    assert result.attributes["quality"] == 60
    assert result.attributes["actual_bytes"] == 160
    assert calls[0] == ("jpeg", 90)
    assert calls[1] == ("jpeg", 30)
    assert len(calls) > 2


def test_watermark_center_and_failure_paths(monkeypatch):
    source = image_bytes("PNG", (100, 80))
    centered = MediaOptimizerEngine.execute(source, "x.png", [operation("image-watermark", {
        "text": "mark", "position": "center", "opacity": 35,
    })])
    assert centered.attributes["watermarked"] is True
    assert centered.attributes["output_format"] == "PNG"
    monkeypatch.setattr(ImageFont, "load_default", lambda **_kwargs: (_ for _ in ()).throw(OSError("font unavailable")))
    with pytest.raises(ConversionInputError):
        MediaOptimizerEngine.execute(source, "x.png", [operation("image-watermark", {"text": "mark"})])


def test_watermark_rejects_animated_images_and_oversized_outputs(monkeypatch):
    stream = io.BytesIO()
    frames = [Image.new("RGB", (16, 16), color) for color in ("red", "blue")]
    frames[0].save(stream, format="GIF", save_all=True, append_images=frames[1:])
    with pytest.raises(MediaOperationUnavailableError):
        MediaOptimizerEngine.execute(stream.getvalue(), "animated.gif", [operation("image-watermark", {"text": "mark"})])

    monkeypatch.setattr(FileConverterEngine, "MAX_CONVERT_OUTPUT_BYTES", 1)
    with pytest.raises(ConversionInputError):
        MediaOptimizerEngine.execute(image_bytes("PNG", (100, 80)), "large.png", [operation("image-watermark", {"text": "mark"})])
